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
import shutil
import socket
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
    # DA2 tem de responder no formato DA2 ('>'); o DA1 ficou com o dele
    t.feed("\x1b[>c")
    assert bytes(t.child_out).startswith(b"\x1b[>")
    t.child_out = bytearray()
    # DECRQM: modo conhecido desligado = 2, ligado = 1, desconhecido = 0
    t.feed("\x1b[?2026$p")
    assert bytes(t.child_out) == b"\x1b[?2026;2$y"
    t.child_out = bytearray()
    t.feed("\x1b[?2026h\x1b[?2026$p")
    assert t.sync_output
    assert bytes(t.child_out) == b"\x1b[?2026;1$y"
    t.child_out = bytearray()
    t.feed("\x1b[?2026l\x1b[?9999$p")
    assert bytes(t.child_out) == b"\x1b[?9999;0$y"
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

    assert cli.parse_args(["bzmux"]) == (None, 0, None, None, None, None, None)
    assert cli.parse_args(["bzmux", "--cmd", "mc", "--quit-after", "2"]) == (
        "mc",
        2,
        None,
        None,
        None,
        None,
        None,
    )
    assert cli.parse_args(["bzmux", "-c", "/tmp/x.conf"])[3] == "/tmp/x.conf"
    assert cli.parse_args(["bzmux", "--config", "/tmp/x.conf"])[3] == "/tmp/x.conf"
    # --debug-log troca o caminho do log; `off` desliga (vence a config)
    assert cli.parse_args(["bzmux", "--debug-log", "/tmp/x.log"])[4] == "/tmp/x.log"
    assert cli.parse_args(["bzmux", "--debug-log", "off"])[4] == "off"
    # socket de introspecção: valor obrigatório, `auto` resolvido depois
    assert cli.parse_args(["bzmux", "--debug-socket", "auto"])[5] == "auto"
    assert cli.parse_args(["bzmux", "--debug-socket", "/tmp/b.sock"])[5] == "/tmp/b.sock"
    assert cli.parse_args(["bzmux", "--cmd"])[6] == "--cmd"
    assert cli.parse_args(["bzmux", "--nada"])[6] == "--nada"
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["bzmux", "--version"]) == 0
    # versão vem de bzmux/__init__.py (fonte única; o pyproject lê de lá)
    assert out.getvalue() == "pybzmux %s\n" % cli.__version__
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["bzmux", "-V"]) == 0
    assert out.getvalue().startswith("pybzmux ")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["bzmux", "--help"]) == 0
    assert out.getvalue().startswith("usage: pybzmux")
    with contextlib.redirect_stderr(err):
        assert cli.main(["bzmux", "--nada"]) == 2
    assert "--cmd" in err.getvalue()


def config_file():
    """P33: formato do kitty, merge com o default embutido e validação."""
    from . import config

    # o arquivo de padrões embarca no pacote (mesmo tratamento do ícone)
    assert config.DATA.exists()
    emb = {e.key: e.value for e in config.parse(config.DATA.read_text())}
    assert emb["shell"] == ""  # vazio = herda o $SHELL do ambiente
    # comentário de linha inteira e no fim da linha, espaço, chave repetida
    vals = config.parse("# cabeçalho\n  shell   /bin/sh   # inline\n\nfoo bar\nshell /bin/bash\n")
    assert [(e.key, e.value, e.line) for e in vals] == [
        ("shell", "/bin/sh", 2),
        ("foo", "bar", 4),
        ("shell", "/bin/bash", 5),
    ]
    d = tempfile.mkdtemp()
    p = os.path.join(d, "bzmux.conf")
    # merge: o usuário só sobrescreve o que escreveu
    with open(p, "w") as f:
        f.write("shell /bin/sh\n")
    cfg = config.load(p)
    assert (cfg.shell, cfg.errors, cfg.warnings) == ("/bin/sh", [], [])
    assert cfg.exists
    # repetida: aviso com as linhas, vale a última, o resto aplica
    with open(p, "w") as f:
        f.write("shell /bin/sh\nshell /bin/bash\n")
    cfg = config.load(p)
    assert (cfg.shell, cfg.ok, len(cfg.warnings)) == ("/bin/bash", True, 1)
    assert "line 2: shell repeated" in config.message(cfg)
    assert "line 1 ignored" in config.message(cfg)
    # sem arquivo do usuário: valem os padrões, sem erro
    cfg = config.load(os.path.join(d, "nao-existe.conf"))
    assert (cfg.shell, cfg.ok, cfg.exists) == ("", True, False)
    # a herança é resolvida por effective_shell: config > $SHELL > /bin/bash,
    # e o valor sai em caminho (vai virar o $SHELL do filho)
    assert config.effective_shell("/bin/sh") == "/bin/sh"
    assert config.effective_shell("", {"SHELL": "/bin/bash"}) == "/bin/bash"
    assert config.effective_shell("", {}) == "/bin/bash"
    assert config.effective_shell("nao-existe-xyz", {"SHELL": "/x"}) == "/bin/bash"
    # aba nova: `--cmd` decide o comando e NÃO mexe no $SHELL do filho, e o
    # reload só alcança as abas seguintes porque o $SHELL já foi exportado
    # no fork (a aba aberta continua com o shell que rodava)
    env = {"SHELL": "/bin/sh"}
    assert config.tab_command(None, "/bin/bash", env) == ("/bin/bash", "/bin/bash")
    assert config.tab_command(None, "", env) == ("/bin/sh", "/bin/sh")
    assert config.tab_command(None, "", {}) == ("/bin/bash", "/bin/bash")
    assert config.tab_command("seq 3", "/bin/bash", env) == ("seq 3", "/bin/bash")
    assert config.tab_command("seq 3", "", env) == ("seq 3", "/bin/sh")
    # chave desconhecida é erro, mas o resto do arquivo VALE (carga inicial)
    with open(p, "w") as f:
        f.write("foo bar\nshell /bin/sh\n")
    cfg = config.load(p)
    assert (cfg.shell, cfg.ok) == ("/bin/sh", False)
    assert "line 1: unknown key: foo" in config.message(cfg)
    # valor inválido fica no padrão (a chave não aplica) e o erro vai pro toast
    with open(p, "w") as f:
        f.write("# nada aqui\nshell /nao/existe/xyz\n")
    cfg = config.load(p)
    assert (cfg.shell, cfg.ok) == ("", False)
    assert "line 2: shell not executable" in config.message(cfg)


def config_options():
    """P34: fonte, cursor, histórico, padding, bell e copy_on_select."""
    from . import config

    # o default embarcado documenta TODAS as chaves, com os valores de fábrica
    emb = {e.key: e.value for e in config.parse(config.DATA.read_text())}
    assert emb == config.DEFAULTS
    d = tempfile.mkdtemp()
    p = os.path.join(d, "bzmux.conf")
    # sem arquivo do usuário valem os padrões, chave a chave
    cfg = config.load(os.path.join(d, "nao-existe.conf"))
    assert (cfg.font_family, cfg.font_size) == ("Monospace", 12.0)
    assert (cfg.cursor_shape, cfg.cursor_blink) == ("block", False)
    assert (cfg.scrollback, cfg.padding) == (1000, 0)
    assert (cfg.bell, cfg.copy_on_select) == ("none", False)
    assert cfg.debug_log == "/tmp/tortty-python.debug.log"
    # valor válido de cada chave: família com espaço, fonte fracionária
    with open(p, "w") as f:
        f.write(
            "font_family DejaVu Sans Mono\nfont_size 12.5\ncursor_shape beam\n"
            "cursor_blink yes\nscrollback 200\nwindow_padding_width 4\n"
            "bell visual\ncopy_on_select on\n"
        )
    cfg = config.load(p)
    assert cfg.ok, config.message(cfg)
    assert (cfg.font_family, cfg.font_size) == ("DejaVu Sans Mono", 12.5)
    assert (cfg.cursor_shape, cfg.cursor_blink) == ("beam", True)
    assert (cfg.scrollback, cfg.padding) == (200, 4)
    assert (cfg.bell, cfg.copy_on_select) == ("visual", True)
    # debug_log: caminho livre, `off` desliga, vazio é erro
    with open(p, "w") as f:
        f.write("debug_log /tmp/outro.log\n")
    assert config.load(p).debug_log == "/tmp/outro.log"
    with open(p, "w") as f:
        f.write("debug_log off\n")
    assert config.load(p).debug_log is None
    with open(p, "w") as f:
        f.write("debug_log\n")
    cfg = config.load(p)
    assert not cfg.ok and "debug_log is empty" in cfg.errors[0]
    # erro é por linha: o válido aplica, o inválido fica no padrão
    for lixo, esperado in (
        ("font_size abc", "font_size is not a number"),
        ("font_size 0", "font_size out of range"),
        ("font_family", "font_family is empty"),
        ("cursor_shape square", "cursor_shape invalid"),
        ("cursor_blink talvez", "cursor_blink invalid"),
        ("scrollback -1", "scrollback out of range"),
        ("window_padding_width 8px", "is not a number"),
        ("bell beep", "bell invalid"),
        ("copy_on_select 2", "copy_on_select invalid"),
    ):
        with open(p, "w") as f:
            f.write("font_size 20\n" + lixo + "\n")
        cfg = config.load(p)
        assert not cfg.ok and esperado in config.message(cfg), (lixo, config.message(cfg))
        assert cfg.font_size == 20.0  # a linha válida antes do erro aplicou

    # o toast da carga inicial é UM só: primeiro erro + contagem dos outros
    with open(p, "w") as f:
        f.write("bell beep\nfont_size 20\ncursor_shape square\n")
    cfg = config.load(p)
    assert (cfg.bell, cfg.font_size, cfg.ok) == ("none", 20.0, False)
    assert "line 1: bell invalid" in config.first_error(cfg)
    assert config.first_error(cfg).endswith("(+1)")


def scrollback_and_bell():
    """P34: teto de histórico configurável e BEL contado (não silenciado)."""
    t = Term(cols=12, rows=3)
    t.set_scrollback(2)
    for i in range(20):
        t.feed("linha %d\r\n" % i)
    assert len(t.scrollback) == 2  # corta pela mais antiga, não pela que chega
    assert t.row_text(1).startswith("linha 19")  # o vivo não é afetado
    t.set_scrollback(0)  # reduzir corta na hora
    assert t.scrollback == []
    t.set_scrollback(2)
    for i in range(10):
        t.feed("linha %d\r\n" % i)
    t.feed("\x1bc")  # RIS limpa a tela mas não é dono da configuração
    assert (t.scrollback_limit, t.scrollback) == (2, [])
    t.set_scrollback(0)
    assert t.bells == 0
    t.feed("\a")
    assert t.bells == 1  # a view zera e avisa a janela
    # DECSCUSR (CSI 6 q) vira pedido do app; 0 volta para a config
    t.feed("\x1b[4 q")
    assert t.app_cursor_style == ("underline", False)
    t.feed("\x1b[5 q")
    assert t.app_cursor_style == ("beam", True)
    t.feed("\x1b[0 q")
    assert t.app_cursor_style is None


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
    assert t.cx == 9  # quebra pendente, cursor na última coluna
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
    assert [_row_text(r).rstrip() for r in t.visible_rows(99)] == [
        "a",
        "b",
        "c",
    ]


def scroll_anchor():
    """P32: no histórico, o output não arranca a visão da linha que se lê."""
    t = Term(cols=10, rows=3)
    t.feed("".join("%d\r\n" % i for i in range(10)))
    anchor = t.scrolled - 2  # o usuário subiu 2 linhas e parou aqui
    topo = _row_text(t.visible_rows(2)[0]).rstrip()
    t.feed("".join("%d\r\n" % i for i in range(10, 15)))  # app escreveu 5
    assert _row_text(t.visible_rows(t.anchored_view_off(anchor))[0]).rstrip() == topo
    # no teto do scrollback o `len()` para de crescer: a conta "por diferença
    # de tamanho" deixaria o texto derrapar linha a linha; a absoluta não
    t.feed("".join("%d\r\n" % i for i in range(15, 1100)))
    assert len(t.scrollback) == 1000
    anchor = t.scrolled - 3
    topo = _row_text(t.visible_rows(3)[0]).rstrip()
    t.feed("".join("%d\r\n" % i for i in range(1100, 1110)))
    off = t.anchored_view_off(anchor)
    assert (off, _row_text(t.visible_rows(off)[0]).rstrip()) == (13, topo)
    # a conta antiga (offset fixo em 3) mostraria outra linha: 10 de deriva
    assert _row_text(t.visible_rows(3)[0]).rstrip() != topo
    # limpar o histórico (CSI 3J) destrói a âncora: não há o que ler, vivo
    t.feed("\x1b[3J")
    assert t.anchored_view_off(anchor) == 0


def redraw_keeps_history_position():
    """B20: o repaint do app (`2J H 3J` dentro do 2026) não joga pro topo."""
    t = Term(cols=12, rows=4)
    t.set_scrollback(200)
    for i in range(1, 41):
        t.feed("l%02d\r\n" % i)
    off = 12  # o usuário rolou 12 linhas para trás
    anchor = t.scrolled - off
    antes = _row_text(t.visible_rows(off)[0]).rstrip()
    gen = t.hist_gen
    # exatamente o começo do fullRender(clear) do pi
    t.feed("\x1b[?2026h\x1b[2J\x1b[H\x1b[3J")
    assert t.hist_gen == gen + 1  # é por aqui que a view descobre a limpeza
    assert t.scrollback == []
    # a âncora absoluta morreu: sem o pin, o clamp devolveria o vivo e, com o
    # buffer reescrito, escoraria no topo (era o bug)
    assert t.anchored_view_off(anchor) == 0
    for i in range(1, 41):  # o app reescreve o mesmo buffer
        t.feed("l%02d\r\n" % i)
    t.feed("\x1b[?2026l")
    assert len(t.scrollback) >= off
    pin = t.pinned_view_off(off)  # distância do vivo, não âncora absoluta
    assert pin == off
    assert _row_text(t.visible_rows(pin)[0]).rstrip() == antes
    # o caminho da âncora absoluta dá o topo do histórico novo — era o bug
    assert t.anchored_view_off(anchor) == len(t.scrollback) != off
    assert _row_text(t.visible_rows(len(t.scrollback))[0]).rstrip() != antes


def draw_damage():
    """P27: o dano diz QUAL linha mudou; rolagem/resize/RIS dizem "tudo"."""
    t = Term(cols=10, rows=5)
    t.take_damage()  # o primeiro draw é sempre a grade inteira
    assert t.take_damage() == set(), "dano deveria ter sido consumido"
    # um caractere numa linha: só ela
    t.feed("\x1b[3;1Hx")
    assert t.take_damage() == {2}, "trocar 1 célula deveria sujar 1 linha"
    assert t.take_damage() == set()
    # texto corrido em duas linhas
    t.feed("\x1b[1;1Habcdefghij\x1b[2;1Hyz")
    d = t.take_damage()
    assert d == {0, 1}, d
    # EL/ED, ICH/DCH/ECH: linha corrente; ED: tudo
    t.feed("\x1b[2;3H\x1b[K")
    assert t.take_damage() == {1}
    t.feed("\x1b[2;1H\x1b[2X")
    assert t.take_damage() == {1}
    t.feed("\x1b[2J")
    assert t.take_damage() is None, "ED2 muda a tela toda"
    # rolagem, resize e RIS: grade inteira (as linhas mudam de posição)
    t.feed("\x1b[5;1H\n")
    assert t.take_damage() is None, "rolagem move toda linha"
    t.resize(8, 4)
    assert t.take_damage() is None, "reflow move toda linha"
    t.feed("\x1bc")
    assert t.take_damage() is None, "RIS recomeça a grade"


def selection_follows_history():
    """B17: a seleção vive no conteúdo — rolar e output não trocam o texto."""
    t = Term(cols=10, rows=5)
    t.feed("".join("%03d\r\n" % i for i in range(20)))
    # seleciona "018" no vivo; rolar duas linhas leva o realce junto (antes ele
    # ficava na fileira 2, já sobre "016")
    a, b = t.anchor_at(0, 2, 0), t.anchor_at(0, 2, 2)
    assert t.anchor_text(a, b) == "018"
    for off in (1, 2):
        pintado = _row_text(t.visible_rows(off)[t.anchor_row(a, off)]).rstrip()
        assert pintado == "018", off
    assert _row_text(t.visible_rows(2)[2]).rstrip() == "016"  # a fileira antiga
    # rolou muito: a seleção sai da tela mas continua copiando o mesmo texto
    assert t.anchor_row(a, 10) >= t.rows
    assert t.anchor_text(a, b) == "018"
    # ordem inversa: rolar, selecionar no histórico e voltar ao vivo
    c, d = t.anchor_at(6, 0, 0), t.anchor_at(6, 0, 2)
    assert t.anchor_text(c, d) == "010"
    assert t.anchor_row(c, 0) < 0  # sumiu da tela, não da seleção
    assert t.anchor_text(c, d) == "010"
    # output do app com a seleção no histórico: o texto não sai do lugar, nem
    # quando o scrollback bate no teto e descarta linha velha
    t.feed("".join("%03d\r\n" % i for i in range(20, 1100)))
    assert len(t.scrollback) == 1000
    e, f = t.anchor_at(3, 0, 0), t.anchor_at(3, 0, t.cols - 1)
    texto = t.anchor_text(e, f)
    assert texto
    t.feed("".join("%03d\r\n" % i for i in range(1100, 1110)))
    assert (len(t.scrollback), t.anchor_alive(e), t.anchor_alive(f)) == (1000, True, True)
    off = t.anchored_view_off(e.line)  # P32: a visão segue a linha lida
    assert t.anchor_row(e, off) == 0
    assert _row_text(t.visible_rows(off)[0]).rstrip() == texto
    assert t.anchor_text(e, f) == texto
    # limpar o histórico (CSI 3J) mata a âncora: não há mais o texto
    t.feed("\x1b[3J")
    assert (t.anchor_alive(e), t.anchor_text(e, f)) == (False, "")
    # reflow muda o mapa absoluto (linha junta/parte): âncora velha não vale
    v = Term(cols=10, rows=3)
    v.feed("".join("%03d\r\n" % i for i in range(10)))
    g = v.anchor_at(2, 0, 0)
    v.resize(20, 3)
    assert not v.anchor_alive(g)


# -- mouse, seleção e colagem (P1/P7) ----------------------------------
def mouse_modes_and_sgr():
    """Modos de mouse e a codificação SGR/X10."""
    t = Term()
    t.feed("\x1b[?1002h\x1b[?1006h")
    assert (t.mouse_mode, t.mouse_sgr) == (2, True)
    assert mouse.encode(mouse.LEFT, 0, 0, True, sgr=True) == "\x1b[<0;1;1M"
    assert mouse.encode(mouse.LEFT, 4, 2, False, sgr=True) == "\x1b[<0;5;3m"
    assert mouse.encode(mouse.LEFT, 0, 0, True) == ("\x1b[M" + chr(32) + chr(33) + chr(33))


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
    for fg, bg in (
        (style.CARD_FG, style.SIDEBAR_BG),
        (style.CARD_INFO_FG, style.SIDEBAR_BG),
        (style.CARD_SEL_FG, style.CARD_SEL_BG),
        (style.CARD_SEL_INFO_FG, style.CARD_SEL_BG),
        (style.CARD_FG, style.TAB_BAR_BG),
        (style.CARD_FG, style.TAB_ACTIVE_BG),
        (style.CARD_FG, style.BELL_BG),
        (style.TOAST_FG, style.TOAST_BG),
        (style.TOAST_DETAIL_FG, style.TOAST_BG),
        (style.TOAST_WARN_FG, style.TOAST_WARN_BG),
        (style.TOAST_DETAIL_FG, style.TOAST_WARN_BG),
        (style.TOAST_ERR_FG, style.TOAST_ERR_BG),
        (style.TOAST_DETAIL_FG, style.TOAST_ERR_BG),
    ):
        assert style.contrast(fg, bg) >= 4.5, (fg, bg, style.contrast(fg, bg))
    # e o CSS tem que realmente usar os tokens, não uma cópia à mão
    css = style.css()
    for token in (
        style.SIDEBAR_BG,
        style.CARD_SEL_BG,
        style.CARD_SEL_FG,
        style.TAB_BAR_BG,
        style.TAB_ACTIVE_BG,
        style.BELL_BG,
        style.TAB_SEP,
        style.TOAST_ACCENT,
        style.TOAST_DETAIL_FG,
        style.TOAST_WARN_BG,
        style.TOAST_WARN_ACCENT,
        style.TOAST_ERR_ACCENT,
    ):
        assert token in css
    assert style.CARD_INFO_FG in css


# -- atalho do sistema -------------------------------------------------
def desktop_shortcut():
    """O .desktop tem que casar com o WM_CLASS e o ícone viajar no pacote."""
    txt = shortcut.entry("/opt/bin/bzmux")
    assert "Exec=/opt/bin/bzmux" in txt
    assert f"StartupWMClass={shortcut.WMCLASS}" in txt
    assert "Categories=System;TerminalEmulator;" in txt
    assert "Icon=tortty-python" in txt
    assert "Name=TorTTY (Python)" in txt  # nome visível no menu (rebrand)
    assert shortcut._icon_bytes().lstrip().startswith(b"<svg")  # o wheel tem o asset
    # XDG_DATA_HOME manda nos caminhos (nada de ~/.local/share na mão)
    old = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = "/tmp/xdg-probe"
    try:
        assert shortcut.desktop_path() == ("/tmp/xdg-probe/applications/tortty-python.desktop")
        assert shortcut.icon_path() == (
            "/tmp/xdg-probe/icons/hicolor/scalable/apps/tortty-python.svg"
        )
    finally:
        if old is None:
            del os.environ["XDG_DATA_HOME"]
        else:
            os.environ["XDG_DATA_HOME"] = old


def shortcut_remove_only_own_name():
    """remove() apaga o nome atual e o anterior, não o bzmux do Rust."""
    tmp = tempfile.mkdtemp()
    old = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = tmp
    try:
        made = []
        for name in (shortcut.APP, shortcut.LEGACY, "bzmux"):
            for p in (
                os.path.join(tmp, "applications", name + ".desktop"),
                os.path.join(tmp, "icons", "hicolor", "scalable", "apps", name + ".svg"),
            ):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write("x")
                made.append(p)
        shortcut.remove()
        left = sorted(os.path.basename(p) for p in made if os.path.exists(p))
        assert left == ["bzmux.desktop", "bzmux.svg"], left
    finally:
        if old is None:
            del os.environ["XDG_DATA_HOME"]
        else:
            os.environ["XDG_DATA_HOME"] = old
        shutil.rmtree(tmp)


# -- geometria lembrada ------------------------------------------------
def window_state():
    """Geometria salva: lixo e monitor desconectado são descartados."""
    mons = [(0, 0, 1920, 1080)]
    assert state.fit(300, 200, 900, 600, mons) == (300, 200, 900, 600)
    assert state.fit(5000, 5000, 900, 600, mons) is None  # monitor desconectado
    assert state.fit(300, 200, 100, 50, mons) is None  # tamanho lixo
    assert state.fit("x", None, 900, 600, mons) is None  # arquivo editado à mão
    assert state.fit(300, 200, 900, 600, []) == (300, 200, 900, 600)

    old = os.environ.get("XDG_STATE_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_STATE_HOME"] = tmp
        try:
            assert state.load() is None  # ausente não é erro
            state.save({"x": 1, "y": 2, "w": 3, "h": 4, "max": True})
            assert state.load() == {
                "x": 1,
                "y": 2,
                "w": 3,
                "h": 4,
                "max": True,
            }
            with open(state.state_path(), "w") as f:
                f.write("{quebrado")  # JSON pela metade
            assert state.load() is None
        finally:
            if old is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old


def debug_socket():
    """P35: despacho pedido -> resposta do socket de introspecção (sem socket)."""
    from . import debugsock

    class Alvo:
        """Alvo falso: registra o que o verbo pediu, sem Gtk."""

        def __init__(self):
            self.escrito = None
            self.log = None
            self.saiu = False

        def debug_state(self):
            return {"cols": 80, "rows": 24, "view_off": 3, "sync": False}

        def debug_text(self, where="view", start=0, count=40):
            return ["%s:%d:%d" % (where, start, count)]

        def debug_write(self, data):
            self.escrito = data

        def debug_log(self, value):
            self.log = value
            return value or "off"

        def debug_quit(self):
            self.saiu = True

        def debug_keys(self, spec):
            return {"key": spec, "handled": True}

        def debug_resize(self, cols=0, rows=0):
            return {"requested": [cols, rows]}

        def debug_prof(self, on=None):
            return {"on": bool(on), "etapas": {}}

    alvo = Alvo()

    def pede(pedido):
        return json.loads(debugsock.dispatch(alvo, json.dumps(pedido)))

    assert pede({"cmd": "state"}) == {
        "ok": True,
        "cols": 80,
        "rows": 24,
        "view_off": 3,
        "sync": False,
    }
    # `text` tem default e o pedido manda onde/quantas
    assert pede({"cmd": "text"})["lines"] == ["view:0:40"]
    assert pede({"cmd": "text", "where": "history", "start": 5, "count": 2})["lines"] == [
        "history:5:2"
    ]
    # write vai como string crua; log devolve o caminho efetivo; quit sai
    assert pede({"cmd": "write", "data": "\x1b[A"})["ok"] and alvo.escrito == "\x1b[A"
    assert pede({"cmd": "log", "value": "/tmp/x.log"})["path"] == "/tmp/x.log"
    assert pede({"cmd": "quit"})["ok"] and alvo.saiu
    # erro não levanta: json torto, verbo desconhecido, write sem data
    assert not json.loads(debugsock.dispatch(alvo, "{"))["ok"]
    assert not json.loads(debugsock.dispatch(alvo, "[1,2]"))["ok"]
    r = json.loads(debugsock.dispatch(alvo, json.dumps({"cmd": "nada"})))
    assert not r["ok"] and "desconhecido" in r["err"]
    r = json.loads(debugsock.dispatch(alvo, json.dumps({"cmd": "write"})))
    assert not r["ok"] and "data" in r["err"]
    r = json.loads(debugsock.dispatch(alvo, json.dumps({"cmd": "text", "start": "x"})))
    assert not r["ok"]
    # keys: uma tecla ou lista, cada uma resolvida pelo alvo
    assert pede({"cmd": "keys", "data": "ctrl+shift+n"})["keys"] == [
        {"key": "ctrl+shift+n", "handled": True}
    ]
    assert len(pede({"cmd": "keys", "data": ["Tab", "Return"]})["keys"]) == 2
    assert not pede({"cmd": "keys"})["ok"]
    # resize devolve o pedido (o resultado aparece no state seguinte)
    assert pede({"cmd": "resize", "cols": 100, "rows": 30})["requested"] == [100, 30]
    assert pede({"cmd": "prof", "on": True})["on"]
    # `parse_key`: modificadores conhecidos, tecla por último
    assert debugsock.parse_key("ctrl+shift+n") == ("n", ("ctrl", "shift"))
    assert debugsock.parse_key("PgUp") == ("Page_Up", ())  # alias do keysym
    assert debugsock.parse_key("shift+pgup") == ("Page_Up", ("shift",))
    assert debugsock.parse_key("esc") == ("Escape", ())
    assert debugsock.parse_key(" alt + F2 ") == ("F2", ("alt",))
    for ruim in ("", "hiper+n", "ctrl+"):
        try:
            debugsock.parse_key(ruim)
        except ValueError:
            pass
        else:
            raise AssertionError("parse_key aceitou %r" % ruim)
    # caminho: `auto` ganha o pid; vazio desliga
    caminho = debugsock.resolve("auto")
    assert caminho.endswith("tortty-python-%d.sock" % os.getpid())
    assert debugsock.resolve(None) is None and debugsock.resolve("") is None
    assert debugsock.resolve("/tmp/x.sock") == "/tmp/x.sock"
    # caminho ocupado: arquivo comum não é apagado, socket vivo não é roubado
    d = tempfile.mkdtemp()
    comum = os.path.join(d, "nao-socket")
    with open(comum, "w") as f:
        f.write("x")
    assert "is not a socket" in debugsock._clear_stale(comum)
    assert os.path.exists(comum)  # não apagou arquivo alheio
    vivo = os.path.join(d, "vivo.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(vivo)
    srv.listen(1)
    assert "listening" in debugsock._clear_stale(vivo)
    srv.close()  # agora é órfão: pode sair
    assert debugsock._clear_stale(vivo) is None and not os.path.exists(vivo)


ALL = (
    parser_text_and_cursor,
    sgr_and_erasing,
    alt_screen_and_scroll,
    charset_and_replies,
    csi_with_intermediate,
    argv_parsing,
    debug_socket,
    kitty_keyboard,
    config_file,
    config_options,
    scrollback_and_bell,
    graphics_image_and_offset,
    graphics_follow_history,
    wrap_and_control,
    reflow,
    history,
    scroll_anchor,
    selection_follows_history,
    draw_damage,
    redraw_keeps_history_position,
    mouse_modes_and_sgr,
    selection,
    paste_markers,
    truecolor,
    style_contrast,
    desktop_shortcut,
    shortcut_remove_only_own_name,
    window_state,
)
