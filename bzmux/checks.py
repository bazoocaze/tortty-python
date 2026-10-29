"""Os checks do bzmux: uma fonte de verdade, chamada pelo --selftest e pelo pytest.

Cada função é um teste de comportamento, sem display e sem PyGObject — o módulo
só importa term (que puxa graphics), palette, mouse, kitty_kbd e style. Um bug
corrigido virou uma asserção (regressão vale mais que cobertura); nada de
matriz de casos.
"""

import base64
import contextlib
import io
import json
import os
import tempfile
import zlib

from . import kitty_kbd, mouse, shortcut, state, style
from .palette import DEF_BG, DEF_FG, FG_DEFAULT, cell_rgb, rgb
from .term import Term


def _row_text(row):
    return "".join(c[0] for c in row)


def _screen_text(t):
    return "".join(_row_text(r) for r in t.grid).rstrip()


# -- parser VT ---------------------------------------------------------
def parser_text_and_cursor():
    """Texto digitado e o cursor andando; CUP."""
    t = Term()
    t.feed("oi")
    assert t.row_text(0)[:2] == "oi"
    assert (t.cx, t.cy) == (2, 0)
    t = Term()
    t.feed("\x1b[2;5H*\x1b[1;1H#")
    assert t.grid[1][4][0] == "*"
    assert t.grid[0][0][0] == "#"


def sgr_and_erasing():
    """SGR de cor, EL 2 e ED 2."""
    t = Term()
    t.feed("\x1b[31mX\x1b[0mY")
    assert (t.grid[0][0][1], t.grid[0][1][1]) == (1, DEF_FG)
    t = Term()
    t.feed("abc\x1b[2K")
    assert t.row_text(0)[:3] == "   "
    t = Term()
    t.feed("abc\x1b[2Jx")
    assert (t.row_text(0)[0], (t.cx, t.cy)) == ("x", (1, 0))


def alt_screen_and_scroll():
    """Alt-screen volta ao conteúdo de antes, scroll e região de margem."""
    t = Term()
    t.feed("\x1b[?1049hALT\x1b[?1049l")
    assert t.row_text(0)[:3] == "   "
    t2 = Term()
    t2.feed("\x1b[?1049hALT")
    assert t2.row_text(0)[:3] == "ALT"
    t = Term()
    for _ in range(30):
        t.feed("l\n")
    assert len(t.scrollback) > 0
    assert t.cy == 23
    t = Term()
    t.feed("\x1b[3;10r")
    assert (t.top, t.bottom) == (2, 9)


def charset_and_replies():
    """Charset DEC, DA, DSR/CPR e título por OSC."""
    t = Term()
    t.feed("\x1b(0qqqq\x1b(B")
    assert t.row_text(0)[:4] == "────"
    t = Term()
    t.feed("\x1b[c")
    assert bytes(t.child_out) == b"\x1b[?62c"
    t.child_out = bytearray()
    t.feed("\x1b[5;9H\x1b[6n")
    assert bytes(t.child_out) == b"\x1b[5;9R"
    t = Term()
    t.feed("\x1b]0;titulo\x07")
    assert t.title == "titulo"
    # consultas que as TUIs fazem: tamanho de célula, cores e paleta
    t = Term()
    t.cell_size = (10, 21)
    t.feed("\x1b[16t")
    assert bytes(t.child_out) == b"\x1b[6;21;10t"
    t.child_out = bytearray()
    t.feed("\x1b]11;?\x07")
    assert bytes(t.child_out).startswith(b"\x1b]11;rgb:")
    t.child_out = bytearray()
    t.feed("\x1b]4;1;?\x07")
    assert bytes(t.child_out).startswith(b"\x1b]4;1;rgb:")


def csi_with_intermediate():
    """CSI com intermediário (DECSACE do icat) não vira texto na tela."""
    t = Term(cols=20, rows=2)
    t.feed("\x1b[?s\x1b[*x\x1b[4lA")
    assert _row_text(t.grid[0]).rstrip() == "A"


# -- linha de comando --------------------------------------------------
def argv_parsing():
    """--help sai sem abrir janela; opção inválida é erro de uso (exit 2)."""
    from . import cli

    assert cli.parse_args(["bzmux"]) == (None, 0, None, None)
    assert cli.parse_args(["bzmux", "--cmd", "mc", "--quit-after", "2"]) == (
        "mc", 2, None, None)
    assert cli.parse_args(["bzmux", "--cmd"])[3] == "--cmd"
    assert cli.parse_args(["bzmux", "--nada"])[3] == "--nada"
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["bzmux", "--help"]) == 0
    assert out.getvalue().startswith("uso: bzmux")
    with contextlib.redirect_stderr(err):
        assert cli.main(["bzmux", "--nada"]) == 2
    assert "--cmd" in err.getvalue()


# -- protocolo de teclado do kitty (P5) --------------------------------
def kitty_keyboard():
    """CSI-u: legado sem flags, modificadores, release e pilha de flags."""
    enc = kitty_kbd.encode
    assert enc(0x61, 0, 0, 0, 0, 0) is None
    assert enc(0xFF0D, 0, 0, 0, 0, 1) == "\x1b[13u"
    assert enc(0x61, 0, 0, 1, 0, 1) == "\x1b[97;5u"
    assert enc(0x61, 1, 0, 1, 0, 1) == "\x1b[97;6u"
    assert enc(0xFF52, 1, 0, 0, 0, 1) == "\x1b[1;2A"
    assert enc(0x61, 0, 0, 0, 0, 8) == "\x1b[97u"
    assert enc(0x61, 0, 0, 1, 0, 3, event=kitty_kbd.RELEASE) == "\x1b[97;5:3u"
    # Release nunca cai no legado: texto puro com a flag 2 não sai duas vezes
    assert enc(0x61, 0, 0, 0, 0, 7, event=kitty_kbd.RELEASE) == ""
    assert enc(0x61, 0, 0, 0, 0, 7, event=kitty_kbd.PRESS) is None
    t = Term()
    t.feed("\x1b[>1u\x1b[=2;2u")
    assert (t.kbd_flags, t.kbd_stack) == (3, [0])
    t.feed("\x1b[<u")
    assert t.kbd_flags == 0


# -- gráficos do kitty (P6) --------------------------------------------
def graphics_image_and_offset():
    """Imagem + placement, rolagem junto e o=z com offset em pixel."""
    t = Term(cols=20, rows=4)
    t.feed("\r\n")
    rgba = base64.b64encode(bytes([9, 8, 7, 255] * 4)).decode()
    t.feed(f"\x1b_Ga=T,f=32,s=2,v=2,i=3;{rgba}\x1b\\")
    img = t.graphics.images.get(3)
    assert (img.width, img.height, img.fmt) == (2, 2, 32)
    assert [(p.image_id, p.col, p.row) for p in t.graphics.placements] == [(3, 0, 1)]
    t.feed("\x1b[4;1H\r\n")
    assert [p.row for p in t.graphics.placements] == [0]
    t = Term(cols=20, rows=4)
    b64 = base64.b64encode(zlib.compress(bytes(range(24)))).decode()
    t.feed(f"\x1b_Ga=T,f=24,o=z,s=4,v=2,C=1,X=3;{b64}\x1b\\")
    pl = t.graphics.placements[0]
    assert (pl.dx, pl.cols, pl.rows) == (3, 1, 1)


def graphics_follow_history():
    """Imagem que sai pelo topo vai pro scrollback e o reflow poda o inalcançável."""
    t = Term(cols=20, rows=4)
    rgba = base64.b64encode(bytes([9, 8, 7, 255] * 4)).decode()
    t.feed(f"\x1b_Ga=T,f=32,s=2,v=2,i=7;{rgba}\x1b\\")
    for _ in range(6):
        t.feed("\r\n")
    pl = t.graphics.placements[0]
    assert pl.row < 0
    assert pl.row + len(t.scrollback) >= 0
    t.resize(40, 4)
    assert all(p.row >= -len(t.scrollback) for p in t.graphics.placements)


def wrap_and_control():
    """Linha que enche a largura + CR/LF avança UMA linha (regressão do P15)."""
    t = Term(cols=10, rows=4)
    t.feed("0123456789")
    assert t.cx == 9            # quebra pendente, cursor na última coluna
    t.feed("\r\n")
    assert (t.cx, t.cy) == (0, 1), (t.cx, t.cy)
    # a quebra pendente continua valendo quando vem texto, não controle
    t.feed("0123456789X")
    assert (t.cx, t.cy) == (1, 2), (t.cx, t.cy)
    # P21: célula em branco é compartilhada entre linhas — escrever substitui
    # a célula, nunca muta in-place (mutação pintaria a tela inteira)
    t = Term(cols=4, rows=2)
    assert t.grid[0][0] is t.grid[1][1]
    t.feed("x")
    assert t.grid[0][0][0] == "x" and t.grid[1][1][0] == " "


# -- reflow e histórico (P2/P3) ----------------------------------------
def reflow():
    """Re-quebra mantendo a linha lógica, estreitando e alargando."""
    t = Term(cols=20, rows=4)
    text = "0123456789" * 4
    t.feed(text)
    t.resize(10, 4)
    assert (_screen_text(t), (t.cx, t.cy)) == (text, (9, 3))
    t.resize(20, 4)
    assert (_screen_text(t), (t.cx, t.cy)) == (text, (19, 1))


def history():
    """A visão desliza sobre scrollback + grade."""
    t = Term(cols=10, rows=3)
    t.feed("a\r\nb\r\nc\r\nd\r\ne\r\n")
    live = [_row_text(r).rstrip() for r in t.visible_rows(0)]
    one_back = [_row_text(r).rstrip() for r in t.visible_rows(1)]
    assert live == ["d", "e", ""]
    assert one_back == ["c", "d", "e"]
    # fundo do histórico: a janela nunca passa de `rows` linhas (regressão:
    # off > rows devolvia off linhas e o desenho ficava mais lento ao subir)
    for off in (0, 1, t.rows, t.rows + 1, len(t.scrollback)):
        assert len(t.visible_rows(off)) == t.rows, off
    assert [_row_text(r).rstrip() for r in t.visible_rows(99)] == ["a", "b", "c"]


# -- mouse, seleção e colagem (P1/P7) ----------------------------------
def mouse_modes_and_sgr():
    """Modos de mouse e a codificação SGR/X10."""
    t = Term()
    t.feed("\x1b[?1002h\x1b[?1006h")
    assert (t.mouse_mode, t.mouse_sgr) == (2, True)
    assert mouse.encode(mouse.LEFT, 0, 0, True, sgr=True) == "\x1b[<0;1;1M"
    assert mouse.encode(mouse.LEFT, 4, 2, False, sgr=True) == "\x1b[<0;5;3m"
    assert mouse.encode(mouse.LEFT, 0, 0, True) == "\x1b[M" + chr(32) + chr(33) + chr(33)


def selection():
    """Seleção multi-linha, invertida e sem newline sobrando no fim."""
    t = Term()
    t.feed("abc\r\ndef\r\nghi")
    assert t.selection_text((0, 1), (1, 1)) == "bc\nde"
    assert t.selection_text((0, 0), (0, 2)) == "abc"
    assert t.selection_text((1, 1), (0, 1)) == "bc\nde"


def paste_markers():
    """?2004 liga/desliga os marcadores da colagem."""
    t = Term()
    assert t.paste_payload("a\nb") == "a\nb"
    t.feed("\x1b[?2004h")
    assert t.paste_payload("a\nb") == "\x1b[200~a\nb\x1b[201~"
    t.feed("\x1b[?2004l")
    assert t.paste_payload("a") == "a"


# -- truecolor (P4) ----------------------------------------------------
def truecolor():
    """RGB mora na célula (bit 24), nas formas ';' e ':', sobrevivendo ao resize."""
    t = Term()
    t.feed("\x1b[38;2;18;52;86mA\x1b[48;2;250;128;114mB")
    assert t.grid[0][0][1] == rgb(18, 52, 86)
    assert t.grid[0][1][2] == rgb(250, 128, 114)
    assert cell_rgb(t.grid[0][0][1], FG_DEFAULT) == (18, 52, 86)
    t.feed("\x1b[38:2::7:8:9mC")
    assert cell_rgb(t.grid[0][2][1], FG_DEFAULT) == (7, 8, 9)
    t = Term()
    t.feed("\x1b[38;5;196mA\x1b[0mB")
    assert t.grid[0][0][1] == 196
    assert t.grid[0][1][1] == DEF_FG
    assert t.grid[0][1][2] == DEF_BG
    t = Term(cols=4, rows=2)
    t.feed("\x1b[38;2;1;2;3mXYZW")
    t.resize(8, 2)
    assert t.grid[0][0][1] == rgb(1, 2, 3)


def style_contrast():
    """O cromo da janela: texto claro em fundo escuro, com contraste medido.

    "Bem claro" precisa de número: WCAG pede 4.5:1 para texto normal. Se alguém
    escurecer o verde do selecionado ou apagar o texto da segunda linha, isto
    quebra antes de virar reclamação de olho.
    """
    for fg, bg in ((style.CARD_FG, style.SIDEBAR_BG),
                   (style.CARD_INFO_FG, style.SIDEBAR_BG),
                   (style.CARD_SEL_FG, style.CARD_SEL_BG),
                   (style.CARD_SEL_INFO_FG, style.CARD_SEL_BG)):
        assert style.contrast(fg, bg) >= 4.5, (fg, bg, style.contrast(fg, bg))
    # e o CSS tem que realmente usar os tokens, não uma cópia à mão
    css = style.css()
    for token in (style.SIDEBAR_BG, style.CARD_SEL_BG, style.CARD_SEL_FG):
        assert token in css
    assert style.CARD_INFO_FG in css


# -- atalho do sistema -------------------------------------------------
def desktop_shortcut():
    """O .desktop tem que casar com o WM_CLASS e o ícone viajar no pacote."""
    txt = shortcut.entry("/opt/bin/bzmux")
    assert "Exec=/opt/bin/bzmux" in txt
    assert f"StartupWMClass={shortcut.WMCLASS}" in txt
    assert "Categories=System;TerminalEmulator;" in txt
    assert "Icon=bzmux" in txt
    assert shortcut._icon_bytes().lstrip().startswith(b"<svg")   # o wheel tem o asset
    # XDG_DATA_HOME manda nos caminhos (nada de ~/.local/share na mão)
    old = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = "/tmp/xdg-probe"
    try:
        assert shortcut.desktop_path() == "/tmp/xdg-probe/applications/bzmux.desktop"
        assert shortcut.icon_path() == \
            "/tmp/xdg-probe/icons/hicolor/scalable/apps/bzmux.svg"
    finally:
        if old is None:
            del os.environ["XDG_DATA_HOME"]
        else:
            os.environ["XDG_DATA_HOME"] = old


# -- geometria lembrada ------------------------------------------------
def window_state():
    """Geometria salva: lixo e monitor desconectado são descartados."""
    mons = [(0, 0, 1920, 1080)]
    assert state.fit(300, 200, 900, 600, mons) == (300, 200, 900, 600)
    assert state.fit(5000, 5000, 900, 600, mons) is None   # monitor desconectado
    assert state.fit(300, 200, 100, 50, mons) is None      # tamanho lixo
    assert state.fit("x", None, 900, 600, mons) is None    # arquivo editado à mão
    assert state.fit(300, 200, 900, 600, []) == (300, 200, 900, 600)

    old = os.environ.get("XDG_STATE_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_STATE_HOME"] = tmp
        try:
            assert state.load() is None            # ausente não é erro
            state.save({"x": 1, "y": 2, "w": 3, "h": 4, "max": True})
            assert state.load() == {"x": 1, "y": 2, "w": 3, "h": 4, "max": True}
            with open(state.state_path(), "w") as f:
                f.write("{quebrado")               # JSON pela metade
            assert state.load() is None
        finally:
            if old is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old


ALL = (
    parser_text_and_cursor,
    sgr_and_erasing,
    alt_screen_and_scroll,
    charset_and_replies,
    csi_with_intermediate,
    argv_parsing,
    kitty_keyboard,
    graphics_image_and_offset,
    graphics_follow_history,
    wrap_and_control,
    reflow,
    history,
    mouse_modes_and_sgr,
    selection,
    paste_markers,
    truecolor,
    style_contrast,
    desktop_shortcut,
    window_state,
)
