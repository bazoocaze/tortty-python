"""The tortty_python checks: one source of truth, called by --selftest and by pytest.

Each function is a behaviour test, with no display and no PyGObject — the module
imports only term (which pulls graphics), palette, mouse, kitty_kbd and style. A
fixed bug became an assertion (regression is worth more than coverage); no case
matrix.
"""

import base64
import contextlib
import io
import json
import math
import os
import shutil
import socket
import struct
import tempfile
import time
import zlib

from . import kitty_kbd, mouse, shortcut, state, style, term
from .palette import (
    BLINK,
    BOLD,
    DEF_BG,
    DEF_FG,
    DIM,
    FG_DEFAULT,
    HIDDEN,
    INV,
    ITALIC,
    OVERLINE,
    STRIKE,
    TC,
    UL,
    UL_CURLY,
    UL_DOUBLE,
    UL_SINGLE,
    cell_rgb,
    rgb,
    ul_on,
    ul_style,
)
from .term import (
    _BLANK_V,
    MARK_CAP,
    TITLE_STACK_MAX,
    Mark,
    Term,
    _pack,
    _unpack,
    link_allowed,
)


def _row_text(row):
    from .term import row_text

    return row_text(row)


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
    assert t.cell(1, 4)[0] == "*"
    assert t.cell(0, 0)[0] == "#"


def sgr_and_erasing():
    """SGR de cor, EL 2 e ED 2."""
    t = Term()
    t.feed("\x1b[31mX\x1b[0mY")
    assert (t.cell(0, 0)[1], t.cell(0, 1)[1]) == (1, DEF_FG)
    t = Term()
    t.feed("abc\x1b[2K")
    assert t.row_text(0)[:3] == "   "
    t = Term()
    t.feed("abc\x1b[2Jx")
    assert (t.row_text(0)[0], (t.cx, t.cy)) == ("x", (1, 0))


def sgr_italic_and_underline_styles():
    """SGR 3/23 (itálico) e 4:n (estilo do sublinhado), sem confundir 4:3 com 4;3."""
    t = Term()
    t.feed("\x1b[3m")
    assert t.flags & ITALIC
    t.feed("\x1b[23m")
    assert not t.flags & ITALIC
    # 4:n é estilo; 4;3 é "sublinhado simples + itálico" — o mesmo texto
    t = Term()
    t.feed("\x1b[4:2m")
    assert (t.flags & UL, ul_style(t.flags)) == (UL, UL_DOUBLE)
    t.feed("\x1b[4:3m")
    assert ul_style(t.flags) == UL_CURLY
    t.feed("\x1b[4m")
    assert ul_style(t.flags) == UL_SINGLE  # 4 volta ao simples
    t.feed("\x1b[24m")
    assert not t.flags & UL
    t.feed("\x1b[4;3m")
    assert (t.flags & UL, ul_style(t.flags), bool(t.flags & BOLD)) == (UL, UL_SINGLE, False)
    assert t.flags & ITALIC
    # a célula carrega o estilo (é o que o desenho lê)
    t = Term()
    t.feed("\x1b[3;4:4mX")
    assert t.cell(0, 0)[3] & ITALIC
    assert ul_style(t.cell(0, 0)[3]) == 3  # pontilhado


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
    # P82: icat desiste de imagem sem a área em pixels (14) — e a 15/19 também
    t.child_out = bytearray()
    t.feed("\x1b[14t\x1b[15t\x1b[19t")
    h, w = t.rows * 21, t.cols * 10
    assert bytes(t.child_out) == (
        f"\x1b[4;{h};{w}t\x1b[5;{h};{w}t\x1b[9;{t.rows};{t.cols}t".encode()
    )
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


def csi_hpa():
    """HPA (`) moves to the column, as CHA does, with the same default of 1."""
    t = Term(cols=20, rows=2)
    t.feed("abcd\x1b[2`X")
    assert _row_text(t.grid[0]).rstrip() == "aXcd"
    t.feed("\r\n\x1b[`Y")
    assert _row_text(t.grid[1]).rstrip() == "Y"


# -- linha de comando --------------------------------------------------
def argv_parsing():
    """--help sai sem abrir janela; opção inválida é erro de uso (exit 2)."""
    from . import cli

    vazio = cli.Args()  # sem argumento nenhum: tudo no padrão
    assert cli.parse_args(["tortty_python"]) == vazio
    assert cli.parse_args(["tortty_python", "--cmd", "mc", "--quit-after", "2"]) == vazio._replace(
        cmd="mc", quit_after=2
    )
    # --cols/--rows (P63): trava a grade; zero e não-número são erro de uso
    grade = cli.parse_args(["tortty_python", "--cols", "80", "--rows", "24"])
    assert (grade.cols, grade.rows) == (80, 24)
    assert cli.parse_args(["tortty_python", "--cols", "0"])[6] == "--cols"
    assert cli.parse_args(["tortty_python", "--rows", "x"])[6] == "--rows"
    assert cli.parse_args(["tortty_python", "--cols"])[6] == "--cols"
    assert cli.parse_args(["tortty_python", "-c", "/tmp/x.conf"])[3] == "/tmp/x.conf"
    assert cli.parse_args(["tortty_python", "--config", "/tmp/x.conf"])[3] == "/tmp/x.conf"
    # --debug-log troca o caminho do log; `off` desliga (vence a config)
    assert cli.parse_args(["tortty_python", "--debug-log", "/tmp/x.log"])[4] == "/tmp/x.log"
    assert cli.parse_args(["tortty_python", "--debug-log", "off"])[4] == "off"
    # socket de introspecção: valor obrigatório, `auto` resolvido depois
    assert cli.parse_args(["tortty_python", "--debug-socket", "auto"])[5] == "auto"
    assert cli.parse_args(["tortty_python", "--debug-socket", "/tmp/b.sock"])[5] == "/tmp/b.sock"
    # P98: opção de configuração na linha de comando (vence o arquivo)
    over = cli.parse_args(
        ["x", "--font-family", "Fira Code", "--font-size", "11.5", "--scrollback", "200"]
    )
    assert over.over == {"font_family": "Fira Code", "font_size": "11.5", "scrollback": "200"}
    assert over.erro is None and cli.parse_args(["x", "--font-size"]).erro == "--font-size"
    # --dpi (P109): the pt->px resolution; out of range is a usage error
    assert cli.parse_args(["x", "--dpi", "144"]).dpi == 144.0
    assert cli.parse_args(["x"]).dpi is None
    for ruim in ("abc", "0", "-5", "2000"):
        assert cli.parse_args(["x", "--dpi", ruim]).erro == "--dpi"
    assert cli.parse_args(["x", "--dpi"]).erro == "--dpi"
    assert cli.parse_args(["tortty_python", "--cmd"])[6] == "--cmd"
    assert cli.parse_args(["tortty_python", "--nada"])[6] == "--nada"
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["tortty_python", "--version"]) == 0
    # versão vem de tortty_python/__init__.py (fonte única; o pyproject lê de lá)
    assert out.getvalue() == "tortty-python %s\n" % cli.__version__
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["tortty_python", "-V"]) == 0
    assert out.getvalue().startswith("tortty-python ")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["tortty_python", "--help"]) == 0
    assert out.getvalue().startswith("usage: tortty-python")
    with contextlib.redirect_stderr(err):
        assert cli.main(["tortty_python", "--nada"]) == 2
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
    p = os.path.join(d, "tortty_python.conf")
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
    # paridade fina com o Rust: cor vazia é erro, `debug_log` vazio desliga
    with open(p, "w") as f:
        f.write("color3\ndebug_log\n")
    cfg = config.load(p)
    assert [e.split(": ")[1] for e in cfg.errors] == ["color is empty (use #RRGGBB)"]
    assert cfg.debug_log is None  # vazio = `off` (Rust), não erro


def config_options():
    """P34: fonte, cursor, histórico, padding, bell e copy_on_select."""
    from . import config, keymap

    # o default embarcado é a FONTE dos valores, e é o `defaults_parse_clean` do
    # Rust: ele tem que carregar sem erro nenhum, com todas as chaves e com o
    # mesmo valor da rede de segurança (`FALLBACK`) — se divergir, alguém editou
    # um dos dois.
    emb = {}
    for e in config.parse(config.DATA.read_text()):
        if e.key in config.ACCUMULATE:  # `map`/`unmap` acumulam, como no _validated
            emb[e.key] = (emb[e.key] + "\n" + e.value) if emb.get(e.key) else e.value
        else:
            emb[e.key] = e.value
    assert set(emb) == set(config.KNOWN), set(emb) ^ set(config.KNOWN)
    # `map` acumula: FALLBACK é vazio e a tabela vem do arquivo, linha a linha,
    # então a comparação dela é com a config efetiva — as outras chaves seguem
    # iguais à rede de segurança
    sem_mapa = {k: v for k, v in config.FALLBACK.items() if k != "map"}
    assert {k: v for k, v in emb.items() if k != "map"} == sem_mapa, "conf != FALLBACK"
    padroes = config.load(os.path.join(tempfile.mkdtemp(), "nao-existe.conf"))
    assert (padroes.ok, padroes.warnings) == (True, []), config.message(padroes)
    assert emb["map"] == padroes.values["map"] and padroes.map_lines == keymap.DEFAULTS
    # as 19 de cor repetem a paleta do palette.py (o guard está no palette_config)
    d = tempfile.mkdtemp()
    p = os.path.join(d, "tortty_python.conf")
    # sem arquivo do usuário valem os padrões, chave a chave
    cfg = config.load(os.path.join(d, "nao-existe.conf"))
    assert (cfg.font_family, cfg.font_size) == ("Monospace", 12.0)
    # P98: a linha de comando vence o arquivo, e um valor ruim é recusado
    assert config.check_over({"font_size": "11.5", "scrollback": "200"}) is None
    assert "out of range" in config.check_over({"font_size": "99"})
    assert config.check_over({"font_family": "Fira Code"}) is None
    cfg = config.load(os.path.join(d, "nao-existe.conf"), {"font_size": "11.5", "scrollback": "7"})
    assert (cfg.font_size, cfg.scrollback, cfg.ok) == (11.5, 7, True), (cfg.font_size, cfg.ok)
    with open(p, "w") as f:
        f.write("font_size 20\n")
    cfg = config.load(p, {"font_size": "9"})  # o argv ganha do arquivo
    assert cfg.font_size == 9.0, cfg.font_size
    assert (cfg.cursor_shape, cfg.cursor_blink) == ("block", False)
    assert (cfg.scrollback, cfg.padding) == (1000, 0)
    assert (cfg.bell, cfg.copy_on_select) == ("none", False)
    assert (cfg.bold_as_bright, cfg.letter_spacing) == (False, 0)
    assert cfg.debug_log == "/tmp/tortty-python.debug.log"
    # valor válido de cada chave: família com espaço, fonte fracionária
    with open(p, "w") as f:
        f.write(
            "font_family DejaVu Sans Mono\nfont_size 12.5\ncursor_shape beam\n"
            "cursor_blink yes\nscrollback 200\nwindow_padding_width 4\n"
            "bell visual\ncopy_on_select on\n"
            "bold_as_bright on\nletter_spacing 5\n"
        )
    cfg = config.load(p)
    assert cfg.ok, config.message(cfg)
    assert (cfg.font_family, cfg.font_size) == ("DejaVu Sans Mono", 12.5)
    assert (cfg.cursor_shape, cfg.cursor_blink) == ("beam", True)
    assert (cfg.scrollback, cfg.padding) == (200, 4)
    assert (cfg.bell, cfg.copy_on_select) == ("visual", True)
    assert (cfg.bold_as_bright, cfg.letter_spacing) == (True, 5)
    # debug_log: caminho livre, `off` desliga, vazio é erro
    with open(p, "w") as f:
        f.write("debug_log /tmp/outro.log\n")
    assert config.load(p).debug_log == "/tmp/outro.log"
    with open(p, "w") as f:
        f.write("debug_log off\n")
    assert config.load(p).debug_log is None
    with open(p, "w") as f:
        f.write("debug_log\n")
    cfg = config.load(p)  # vazio desliga, como no Rust (não é erro)
    assert (cfg.ok, cfg.debug_log) == (True, None)
    # erro é por linha: o válido aplica, o inválido fica no padrão
    for lixo, esperado in (
        ("font_size abc", "font_size is not a number"),
        ("font_size 0", "font_size out of range"),
        ("font_family", "font_family is empty"),
        ("cursor_shape square", "cursor_shape invalid"),
        ("cursor_blink talvez", "cursor_blink invalid"),
        ("scrollback -1", "scrollback out of range"),
        ("scrollback 0", "scrollback out of range (1..10000)"),  # era aceito
        ("scrollback 10001", "scrollback out of range"),
        ("font_size 30.5", "font_size out of range"),  # teto 30 desde 0.0.14
        ("window_padding_width 201", "window_padding_width out of range"),
        ("window_padding_width 8px", "is not a number"),
        ("bell beep", "bell invalid"),
        ("copy_on_select 2", "copy_on_select invalid"),
        ("bold_as_bright talvez", "bold_as_bright invalid"),
        ("letter_spacing 21", "letter_spacing out of range"),
        ("letter_spacing -1", "letter_spacing out of range"),
        ("letter_spacing 1.5", "letter_spacing is not a number"),
    ):
        with open(p, "w") as f:
            f.write("font_size 20\n" + lixo + "\n")
        cfg = config.load(p)
        assert not cfg.ok and esperado in config.message(cfg), (lixo, config.message(cfg))
        assert cfg.font_size == 20.0  # a linha válida antes do erro aplicou

    # as pontas válidas continuam valendo (faixa inclusiva)
    with open(p, "w") as f:
        f.write(
            "font_size 4\nfont_size 30\nscrollback 1\nscrollback 10000\n"
            "letter_spacing 0\nletter_spacing 20\n"
        )
    cfg = config.load(p)
    assert (cfg.ok, cfg.font_size, cfg.scrollback, cfg.letter_spacing) == (
        True,
        30.0,
        10000,
        20,
    ), cfg.errors

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


def graphics_chunked():
    """P80: chunked transmission — each chunk is base64 on its own, `=` included."""
    dados = bytes(range(64))
    pedacos = [base64.b64encode(dados[:32]).decode(), base64.b64encode(dados[32:]).decode()]
    assert all(p.endswith("=") for p in pedacos)
    t = Term(cols=20, rows=4)
    t.feed(f"\x1b_Ga=t,f=32,s=4,v=4,i=9,m=1;{pedacos[0]}\x1b\\")
    assert not t.graphics.images  # not finished yet
    t.feed(f"\x1b_Gm=0;{pedacos[1]}\x1b\\")
    assert bytes(t.child_out) == b"\x1b_Gi=9;OK\x1b\\"
    assert t.graphics.images[9].data == dados
    # the other shape: the base64 cut at a multiple of 4, no `=` in the middle
    b64 = base64.b64encode(dados).decode()
    t = Term(cols=20, rows=4)
    t.feed(f"\x1b_Ga=t,f=32,s=4,v=4,i=4,m=1;{b64[:32]}\x1b\\")
    t.feed(f"\x1b_Gm=0;{b64[32:]}\x1b\\")
    assert t.graphics.images[4].data == dados


def _png_b64(w, h):
    """PNG RGBA w x h em base64: cabeçalho de verdade para o png_size."""

    def chunk(tag, data):
        corpo = tag + data
        return struct.pack(">I", len(data)) + corpo + struct.pack(">I", zlib.crc32(corpo))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


def iterm2_inline():
    """P84: OSC 1337 File= draws at the cursor, with units and aspect."""
    t = Term(cols=20, rows=6)
    t.cell_size = (7, 16)
    t.feed("\x1b]1337;File=inline=1;width=4;height=2:" + _png_b64(10, 5) + "\x07")
    pl = t.graphics.placements[0]
    assert (pl.col, pl.row, pl.cols, pl.rows) == (0, 0, 4, 2)
    assert t.graphics.images[pl.image_id].fmt == 100
    assert (t.cx, t.cy) == (0, 2)  # the cursor went below the picture
    # Npx and N% of the screen: 70px / 7 = 10 columns, 50% of 140px = 10 too
    for spec in ("70px", "50%"):
        t = Term(cols=20, rows=6)
        t.cell_size = (7, 16)
        t.feed(f"\x1b]1337;File=inline=1;width={spec};height=1:{_png_b64(4, 4)}\x07")
        assert t.graphics.placements[0].cols == 10, spec
    # preserveAspectRatio: only the width, the height comes from the picture
    t = Term(cols=20, rows=8)
    t.cell_size = (7, 16)
    t.feed("\x1b]1337;File=inline=1;width=5:" + _png_b64(10, 20) + "\x07")
    assert t.graphics.placements[0].rows == max(1, math.ceil(5 * 7 * 20 / 10 / 16))
    # inline=0 only downloads, and a broken payload draws nothing
    for corpo in (
        "\x1b]1337;File=inline=0:" + _png_b64(4, 4) + "\x07",
        "\x1b]1337;File=inline=1:@@@@\x07",
        "\x1b]1337;SetUserVar=foo=YmFy\x07",
    ):
        t = Term(cols=20, rows=6)
        t.cell_size = (7, 16)
        t.feed(corpo)
        assert not t.graphics.placements and not t.graphics.images
    # the erased cells take this picture too (P86 applies to both protocols)
    t = Term(cols=20, rows=6)
    t.cell_size = (7, 16)
    t.feed("\x1b]1337;File=inline=1;width=4;height=2:" + _png_b64(8, 8) + "\x07")
    t.feed("\x1b[2J")
    assert not t.graphics.placements


def iterm2_measures_unknown_size():
    """P90: sem width/height e fora do PNG, quem mede é o gancho do view.py."""
    corpo = base64.b64encode(b"II*\x00" + bytes(64)).decode()  # TIFF falso, sem IHDR

    def manda(gancho=None):
        t = Term(cols=20, rows=6)
        t.cell_size = (7, 16)
        t.graphics.measure = gancho
        t.feed(f"\x1b]1337;File=inline=1:{corpo}\x07")
        return t

    assert not manda().graphics.placements  # sem gancho nada aparece, como antes
    t = manda(lambda dados: (20, 10))
    pl = t.graphics.placements[0]
    assert (pl.cols, pl.rows) == (3, 1)  # 20 px / 7 e 10 px / 16, para cima
    assert t.cy == 1  # o cursor desceu a linha da imagem
    # um gancho que não sabe ler (ou que estoura) não pode derrubar o feed
    for gancho in (lambda dados: (0, 0), lambda dados: 1 / 0):
        assert not manda(gancho).graphics.placements


def oversized_body_is_dropped():
    """P88: a body past OSC_MAX is consumed to the terminator and thrown away."""
    from . import term as modterm

    antigo = modterm.OSC_MAX
    modterm.OSC_MAX = 64  # teto baixo para o teste caber num piscar
    try:
        corpo = "A" * 200
        t = Term(cols=20, rows=4)
        t.cell_size = (7, 16)
        t.feed("\x1b]1337;File=inline=1;width=2;height=2:" + corpo + "\x07")
        assert not t.graphics.images and not t.graphics.placements
        assert not _screen_text(t)  # nada do corpo vaza para a tela
        assert t.state == "ground"
        t.feed("\x1b_Ga=T,f=32,s=2,v=2,i=5;" + corpo + "\x1b\\")
        assert not t.graphics.images  # o APC também respeita o teto
        # abaixo do teto continua funcionando, e o parser segue saudável
        t.feed("\x1b]0;titulo\x07")
        assert t.title == "titulo"
        t.feed("oi")
        assert _screen_text(t).startswith("oi")
    finally:
        modterm.OSC_MAX = antigo


def sixel_decoded():
    """P83: DECSIXEL — cor, banda, repetição, transparência e o DCS no parser."""
    from .graphics import decode_sixel

    # raster 3x8: `~` pinta as 6 linhas da banda 0 em vermelho; `-` desce a banda
    # e `!2A` pinta 2 colunas no bit 1 em verde; o resto fica transparente
    corpo = '"1;1;3;8#0;2;100;0;0#1;2;0;100;0#0~~~#1-!2A'
    w, h, buf = decode_sixel(corpo)

    def px(x, y):
        i = (y * w + x) * 4
        return tuple(buf[i : i + 4])  # BGRA

    assert (w, h) == (3, 8)
    assert px(0, 0) == (0, 0, 255, 255) and px(2, 5) == (0, 0, 255, 255)
    assert px(0, 7) == (0, 255, 0, 255) and px(1, 7) == (0, 255, 0, 255)
    assert px(2, 7) == (0, 0, 0, 0)  # fora da repetição
    assert px(0, 6) == (0, 0, 0, 0)  # entre as bandas
    # P101: com o fundo do tema, o que o stream não seta fica opaco nessa cor e
    # a cor antes do primeiro `#` deixa de ser preto
    w2, h2, buf2 = decode_sixel(corpo, (30, 40, 50))

    def px2(x, y):
        i = (y * w2 + x) * 4
        return tuple(buf2[i : i + 4])

    assert px2(0, 6) == (50, 40, 30, 255)  # entre as bandas: o bg, BGRA
    assert px2(2, 7) == (50, 40, 30, 255)
    assert px2(0, 0) == (0, 0, 255, 255)  # o vermelho do stream não muda
    antes = decode_sixel("~", (30, 40, 50))[2]
    assert tuple(antes[:4]) == (50, 40, 30, 255)  # sem `#`: cor do fundo
    # HLS (`Pu=1`) e um bitmap largo demais
    assert tuple(decode_sixel("#0;1;0;50;100#0~")[2][:4]) == (0, 0, 255, 255)
    assert decode_sixel("#0;2;0;0;0" + "~" * 9000)[0] == 0

    # no parser: ST e BEL fecham o DCS, e a imagem entra como uma colocação só
    for fim in ("\x1b\\", "\x07"):
        t = Term(cols=20, rows=6)
        t.cell_size = (7, 16)
        t.feed("\x1bP0;0;0q" + corpo + fim)
        pl = t.graphics.placements[0]
        assert (pl.cols, pl.rows, pl.col, pl.row) == (1, 1, 0, 0)
        assert t.graphics.images[pl.image_id].fmt == 101  # ARGB32 pronto
        assert (t.cx, t.cy) == (0, 1)  # o cursor desceu a imagem
        # o Term passa o fundo da aba: o buraco entre as bandas não é transparente
        img = t.graphics.images[pl.image_id]
        assert tuple(img.data[(6 * 3 + 0) * 4 : (6 * 3 + 0) * 4 + 4]) != (0, 0, 0, 0)
        assert tuple(img.data[(6 * 3 + 0) * 4 : (6 * 3 + 0) * 4 + 4]) == tuple(
            reversed(t.theme.bg)
        ) + (255,)
    # DCS que não é sixel continua consumido e descartado (XTVERSION)
    t = Term(cols=20, rows=6)
    t.cell_size = (7, 16)
    t.feed("\x1bP>|XTVERSION(3.4.0)\x1b\\")
    assert not t.graphics.images and not _screen_text(t)


def huge_osc_is_linear():
    """P89: a 1 MB OSC/APC must not cost quadratic time (`str +=` did)."""

    def tempo(kb):
        t = Term(cols=40, rows=10)
        t.cell_size = (7, 16)
        corpo = "\x1b]1337;File=inline=1;width=2;height=2:" + "A" * (kb * 1024) + "\x07"
        t0 = time.perf_counter()
        t.feed(corpo)
        return time.perf_counter() - t0

    tempo(32)  # aquece o interpretador
    pequeno, grande = tempo(100), tempo(400)
    # linear = 4x; quadrático = 16x. A folga cobre máquina carregada.
    assert grande < max(0.25, pequeno * 8), f"{pequeno:.3f}s -> {grande:.3f}s"
    # e o conteúdo continua chegando inteiro, no APC também
    t = Term(cols=40, rows=10)
    t.cell_size = (7, 16)
    dados = bytes(range(256)) * 400  # 100 KB
    b64 = base64.b64encode(dados).decode()
    t.feed(f"\x1b_Ga=t,f=32,s=160,v=160,i=7;{b64}\x1b\\")
    assert t.graphics.images[7].data == dados


def dcs_is_consumed():
    """P81/P83: DCS never prints — sixel draws, anything else is dropped."""
    t = Term(cols=40, rows=3)
    t.feed('\x1bP0;0;0q"1;1;4;4#0;2;0;0;0#1!4~$-#2~~\x1b\\fim')
    assert _screen_text(t).strip() == "fim"  # o texto segue abaixo da imagem
    assert t.child_out == bytearray()  # sixel gets no answer
    assert len(t.graphics.images) == 1  # e agora desenha (P83)
    t = Term(cols=40, rows=3)
    t.feed("\x1bP+q544e\x1b\\A")
    assert _row_text(t.grid[0]).rstrip() == "A" and not t.dcs  # não é sixel
    t = Term(cols=40, rows=3)
    t.feed("\x1bP1$qm\x07B")  # BEL also ends it
    assert _row_text(t.grid[0]).rstrip() == "B"
    t = Term(cols=40, rows=3)
    t.feed("\x1bP" + "x" * 5000 + "\x1b\\C")
    assert _row_text(t.grid[0]).rstrip() == "C" and not t.dcs


def image_animation():
    """P92: `a=f` empilha frames, `a=a` liga/para, e o `z=` manda no relógio."""
    from .graphics import Graphics, argb32

    g = Graphics()

    def corpo(acao, cor, extra=""):
        dados = base64.b64encode(cor * 4).decode()  # 2x2 RGBA
        return f"G{acao},f=32,s=2,v=2,i=1{extra};{dados}"

    assert g.handle(corpo("a=t", bytes([255, 0, 0, 255])))[0] == ["Gi=1;OK"]
    assert g.handle(corpo("a=f", bytes([0, 255, 0, 255]), ",z=30"))[0] == ["Gi=1;OK"]
    assert g.handle(corpo("a=f", bytes([0, 0, 255, 255])))[0] == ["Gi=1;OK"]
    # frame retangular: compõe um pedaço sobre o frame anterior (P102)
    pedaco = base64.b64encode(bytes([9, 8, 7, 255])).decode()  # 1x1
    assert g.handle(f"Ga=f,f=32,s=1,v=1,x=1,y=0,i=1;{pedaco}")[0] == ["Gi=1;OK"]
    assert len(g.images[1].frames) == 4
    # fora da imagem é recusado (o recorte não pode crescer o bitmap)
    fora = base64.b64encode(bytes([1, 2, 3, 255])).decode()
    assert "EINVAL" in g.handle(f"Ga=f,f=32,s=2,v=1,x=1,y=0,i=1;{fora}")[0][0]
    assert "ENOENT" in g.handle(corpo("a=f", bytes([0, 0, 0, 255]), ",i=9"))[0][0]

    img = g.images[1]
    assert len(img.frames) == 4  # os 3 inteiros + o retangular
    # memória do ARGB32 é B,G,R,A: o pedaço RGB(9,8,7) cai em (1,0)
    assert img.argb(4)[4:8] == bytes([7, 8, 9, 255])
    assert img.argb(4)[:4] == img.argb(3)[:4]  # o resto veio do frame anterior
    assert img.argb(4)[8:] == img.argb(3)[8:]
    g.images[1].frames.pop()  # o retangular era só prova: o resto do check é de 3

    def rgb():
        return tuple(img.data[2::-1])  # ARGB32 é BGRA na memória

    assert not g.has_animation()  # transmitir não é animar
    assert g.handle("Ga=a,i=1,s=3,v=0")[0] == ["Gi=1;OK"]
    assert g.has_animation() and img.anim.current == 1 and rgb() == (255, 0, 0)
    # `z=30` no frame 2, o default de 40 ms nos outros, laço infinito
    assert g.anim_tick(0.0) == ([1], 30) and rgb() == (0, 255, 0)
    assert g.anim_tick(10.0) == ([], 20) and rgb() == (0, 255, 0)
    assert g.anim_tick(31.0) == ([1], 40) and rgb() == (0, 0, 255)
    assert g.anim_tick(72.0) == ([1], 40) and rgb() == (255, 0, 0)  # voltou ao 1
    # `s=1` para, e uma animação parada não arma timer
    assert g.handle("Ga=a,i=1,s=1")[0] == ["Gi=1;OK"]
    assert not g.has_animation()
    # `z=-1`: frame de base, nunca mostrado
    g2 = Graphics()
    g2.handle(corpo("a=t", bytes([255, 0, 0, 255])))
    g2.handle(corpo("a=f", bytes([0, 255, 0, 255]), ",z=-1"))
    g2.handle(corpo("a=f", bytes([0, 0, 255, 255]), ",z=20"))
    g2.handle("Ga=a,i=1,s=2")  # roda uma vez e para no último
    img2 = g2.images[1]
    g2.anim_tick(0.0)
    assert img2.anim.current == 3, img2.anim.current  # pulou o `z<0`
    assert g2.has_animation()  # `s=2` ainda espera frames novos no fim
    g2.anim_tick(40.0)  # vence a espera e não há para onde ir
    assert not g2.has_animation() and img2.anim.mode == 1
    # alpha parcial é premultiplicado para o cairo
    meio = argb32(bytes([200, 100, 50, 128]), 1, 1, 32)
    assert tuple(meio) == (25, 50, 100, 128), tuple(meio)  # B,G,R já multiplicados


def image_z_and_compose():
    """P99/P102: `z=` manda no empilhamento (negativo atrás do texto), `a=c` compõe."""
    from .graphics import Graphics

    g = Graphics()

    def transmite(ident, cor, extra=""):
        dados = base64.b64encode(cor * 4).decode()  # 2x2
        return g.handle(f"Ga=T,f=32,s=2,v=2,i={ident}{extra};{dados}")[0]

    assert transmite(1, bytes([255, 0, 0, 255])) == ["Gi=1;OK"]
    assert transmite(2, bytes([0, 255, 0, 255]), ",z=5") == ["Gi=2;OK"]
    assert transmite(3, bytes([0, 0, 255, 255]), ",z=-3") == ["Gi=3;OK"]
    assert transmite(4, bytes([9, 9, 9, 255]), ",z=5") == ["Gi=4;OK"]
    # atrás do texto: só o negativo; na frente: em ordem de z, empate = chegada
    assert [p.image_id for p in g.paint_order(behind=True)] == [3]
    assert [p.image_id for p in g.paint_order(behind=False)] == [1, 2, 4]

    # `a=c`: compõe o retângulo no bitmap da imagem, sem criar frame
    antes = g.images[1].stamp
    pedaco = base64.b64encode(bytes([5, 6, 7, 255])).decode()  # 1x1
    assert g.handle(f"Ga=c,f=32,s=1,v=1,x=1,y=1,i=1;{pedaco}")[0] == ["Gi=1;OK"]
    img = g.images[1]
    assert len(img.frames) == 1  # `a=c` não é frame novo
    assert img.stamp != antes  # o view larga a surface velha por isto
    # memória BGRA, 2x2: (1,1) é o pedaço, (0,0) continua vermelho
    assert img.data[12:16] == bytes([7, 6, 5, 255]) and img.data[0:4] == bytes([0, 0, 255, 255])
    # fora da imagem e id desconhecido são recusados
    fora = base64.b64encode(bytes([1, 2, 3, 255])).decode()
    assert "EINVAL" in g.handle(f"Ga=c,f=32,s=2,v=2,x=1,y=1,i=1;{fora}")[0][0]
    assert "ENOENT" in g.handle(f"Ga=c,f=32,s=1,v=1,i=77;{pedaco}")[0][0]
    # uma transmissão nova com o mesmo id é outro bitmap: serial diferente
    velho = g.images[1].stamp
    transmite(1, bytes([1, 2, 3, 255]))
    assert g.images[1].stamp != velho


def erasing_takes_the_picture():
    """P86: the cells are the picture's place — erasing them takes it (parity B3)."""
    rgba = base64.b64encode(bytes([200, 30, 30, 255]) * 16).decode()

    def imagem(t):
        t.feed(f"\x1b_Ga=T,f=32,s=4,v=4,i=1;{rgba}\x1b\\")

    t = Term(20, 6)
    t.cell_size = (8, 16)
    t.feed("\x1b[1;1H")
    imagem(t)
    assert len(t.graphics.placements) == 1
    t.feed("\x1b[2J")
    assert not t.graphics.placements, "ED 2 took it"
    t.feed("\x1b[2;9H")
    imagem(t)
    t.feed("\x1b[2;1H\x1b[K")
    assert not t.graphics.placements, "EL 0 took it"
    t.feed("\x1b[3;13H")
    imagem(t)
    t.feed("\x1b[3;1H\x1b[4X")
    assert len(t.graphics.placements) == 1, "ECH to its left leaves it"
    # the alternate screen is its own place, and leaving gives the main one back
    t = Term(20, 6)
    t.cell_size = (8, 16)
    t.feed("\x1b[1;1H")
    imagem(t)
    t.feed("\x1b[?1049h\x1b[H\x1b[2J")
    assert not t.graphics.placements, "the alt screen starts empty"
    imagem(t)
    assert len(t.graphics.placements) == 1, "the alt one has its own"
    t.feed("\x1b[?1049l")
    assert [(p.row, p.col) for p in t.graphics.placements] == [(0, 0)]
    # the screen is what was erased: a picture in the history stays
    t = Term(20, 4)
    t.cell_size = (8, 16)
    t.feed("\x1b[1;1H")
    imagem(t)
    t.feed("\r\n\r\n\r\n")
    assert t.graphics.placements[0].row < 0
    t.feed("\x1b[H\x1b[2J")
    assert len(t.graphics.placements) == 1, "ED 2 clears the screen, not the history"


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
    # layout B: cada linha é uma lista plana própria — escrever numa não
    # pode aparecer na outra
    t = Term(cols=4, rows=2)
    assert t.grid[0] is not t.grid[1]
    t.feed("x")
    assert t.cell(0, 0)[0] == "x" and t.cell(1, 1)[0] == " "


def deccawm():
    """P64: `CSI ?7 l` desliga a quebra mole — o cursor para na última coluna."""
    t = Term(cols=5, rows=2)
    t.feed("\x1b[?7l")
    assert not t.autowrap
    t.feed("abcdef")  # 'f' sobrescreve a última coluna, sem ir para a linha 2
    assert (_row_text(t.grid[0]), _row_text(t.grid[1])) == ("abcdf", "     ")
    assert (t.cx, t.cy, t.row_wrapped[0]) == (4, 0, False)
    # DECRQM acompanha e o DECSTR volta ao padrão (wrap ligado)
    t.child_out = bytearray()
    t.feed("\x1b[?7$p")
    assert bytes(t.child_out) == b"\x1b[?7;2$y", bytes(t.child_out)
    t.feed("\x1b[!p")
    assert t.autowrap
    # religado, a quebra mole volta (o inverso do P15)
    t = Term(cols=5, rows=2)
    t.feed("\x1b[?7labcdef\x1b[?7hXY")
    assert (_row_text(t.grid[0]), _row_text(t.grid[1])) == ("abcdX", "Y    ")
    assert (t.cx, t.cy, t.row_wrapped[0]) == (1, 1, True)


def sgr_faint_and_hidden():
    """P64: SGR 2 (faint) e 8 (hidden) entram nas flags; 22 tira os dois."""
    t = Term()
    t.feed("\x1b[2m")
    assert t.flags & DIM
    t.feed("\x1b[8m\x1b[1m")
    assert t.flags & (HIDDEN | BOLD)
    t.feed("\x1b[22m")  # intensidade normal: nem negrito nem faint
    assert not t.flags & (BOLD | DIM)
    assert t.flags & HIDDEN  # o 22 não mexe no hidden
    t.feed("\x1b[0m")
    assert t.flags == 0
    # a flag entra na célula (é o run do desenho que lê, não o estado atual)
    t.feed("\x1b[2mx\x1b[8my")
    assert t.cell(0, 0)[3] & DIM
    assert t.cell(0, 1)[3] & HIDDEN


def sgr_blink():
    """P66: SGR 5/6 ligam o piscar; 25, 0 e o soft reset voltam a não piscar."""
    t = Term()
    t.feed("\x1b[5ma\x1b[6mb")
    assert t.cell(0, 0)[3] & BLINK  # 5 e 6 compartilham o bit (xterm)
    assert t.cell(0, 1)[3] & BLINK
    t.feed("\x1b[25mc")
    assert not t.cell(0, 2)[3] & BLINK  # SGR 25: volta a não piscar
    t.feed("\x1b[5m\x1b[0md")
    assert not t.cell(0, 3)[3] & BLINK  # 0 limpa a caneta
    t.feed("\x1b[5m\x1b[!pe")
    assert not t.cell(0, 4)[3] & BLINK  # soft reset (P59) limpa a caneta


def osc52_clipboard():
    """P64: `OSC 52` decodifica base64 para o clipboard; consulta devolve vazio."""
    t = Term()
    payload = base64.b64encode("oi".encode()).decode()
    t.feed("\x1b]52;c;" + payload + "\x07")
    assert (t.clip_seq, t.clip_text, t.clip_sel) == (1, "oi", "clipboard")
    t.feed("\x1b]52;p;" + base64.b64encode("primário".encode()).decode() + "\x1b\\")
    assert (t.clip_seq, t.clip_text, t.clip_sel) == (2, "primário", "primary")
    # base64 inválido e payload sem `;` não viram clipboard nem contam
    t.feed("\x1b]52;c;!!!\x07\x1b]52;so\x07")
    assert (t.clip_seq, t.clip_text) == (2, "primário")
    # consulta: mesmo formato com payload vazio (o conteúdo mora no Gtk)
    t.child_out = bytearray()
    t.feed("\x1b]52;p;?\x07")
    assert bytes(t.child_out) == b"\x1b]52;p;;\x1b\\", bytes(t.child_out)
    assert t.clip_seq == 2  # consulta não mexe no clipboard
    # payload vazio limpa o clipboard (conta como entrega)
    t.feed("\x1b]52;c;\x07")
    assert (t.clip_seq, t.clip_text, t.clip_sel) == (3, "", "clipboard")


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


def dch_beyond_row_width():
    """DCH/ICH além da largura: a linha não passa de cols (a re-quebra supõe isso)."""
    t = Term(cols=10, rows=2)
    t.feed("abcdefghij")
    t.feed("\x1b[1;5H\x1b[99P")  # apaga 99 a partir da coluna 5: só 6 existem
    assert len(t.grid[0].ch) == 10
    assert _row_text(t.grid[0]) == "abcd      "
    t.feed("\x1b[1;3H\x1b[99@")  # insere 99 na coluna 3: entra o que cabe
    assert len(t.grid[0].ch) == 10
    assert _row_text(t.grid[0]) == "ab        "


def reflow_keeps_styled_blank():
    """O corte de branco do reflow não come espaço sublinhado nem de link."""
    t = Term(cols=20, rows=4)
    t.feed("\x1b[4mab    \x1b[0m\r\nx")  # linha 0 fora do cursor: sem blindagem
    t.resize(10, 4)
    linha = t.grid[0]
    assert _row_text(linha).rstrip() == "ab"
    assert [bool(_unpack(v)[2] & UL) for v in linha.pk[:8]] == [True, True] + [True] * 4 + [
        False
    ] * 2
    # célula de espaço com hyperlink também é conteúdo, não é branco
    t = Term(cols=20, rows=4)
    t.feed("\x1b]8;;http://x/\x1b\\ab  \x1b]8;;\x1b\\\r\nx")
    t.resize(10, 4)
    lk = t.grid[0].lk
    assert lk is not None and t.link_key(lk[3]) == "http://x/"


def alt_screen_keeps_scrollback():
    """`?1049` e `ED 3` na tela cheia não comem o histórico do principal (P79)."""
    t = Term(cols=40, rows=8)
    t.feed("".join("linha %d\r\n" % i for i in range(40)))
    antes = [_row_text(r) for r in t.scrollback]
    assert len(antes) == 33
    t.feed("\x1b[?1049hALT only")
    assert [_row_text(r) for r in t.scrollback] == antes
    t.feed("\x1b[3J")  # `clear` na tela cheia é assunto dela
    assert [_row_text(r) for r in t.scrollback] == antes
    assert not _row_text(t.grid[0]).strip(), "o ED 3 limpou a tela do alto"
    t.feed("\x1b[?1049l")
    assert [_row_text(r) for r in t.scrollback] == antes
    assert all("ALT only" not in r for r in antes)  # tela cheia não vira histórico
    assert _row_text(t.grid[0]).startswith("linha 33")  # a tela principal voltou
    t.feed("\x1b[3J")  # no principal o ED 3 continua limpando
    assert not t.scrollback

    u = Term(cols=20, rows=4)
    u.feed("a\x1b]8;;https://e\x1b\\L\x1b]8;;\x1b\\\r\n")
    u.feed("\x1b[?1049h\x1b[3J\x1b[?1049l")
    assert u.links == ["https://e"], "o ED 3 na tela cheia não leva o link"


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


def combining_marks():
    """P73: marca combinante ocupa a célula anterior e não empurra a linha."""
    t = Term(10, 2)
    t.feed("e\u0301x")
    assert t.cell(0, 0)[0] == "e\u0301", t.cell(0, 0)[0]
    assert t.cx == 2  # duas células, não três
    assert t.cell(0, 1)[0] == "x"
    # o caminho rápido (`_put_run`) tem que dar o mesmo resultado
    t.feed("\r\n")
    t.feed("caf\u00e9 e p\u00e3o \u0301")
    assert t.cell(0, 3)[0] == "\u00e9"
    # a linha encheu (10 células): o espaço quebra e a marca cola nele
    assert t.cell(1, 0)[0] == " \u0301"
    assert t.cx == 1
    # seleção de emoji: VS16 cola na célula do coração
    t2 = Term(6, 2)
    t2.feed("\u2764\ufe0fZ")
    assert t2.cell(0, 0)[0] == "\u2764\ufe0f"
    assert (t2.cell(0, 1)[0], t2.cx) == ("Z", 2)
    # a coluna cheia + marca não pode avançar a linha
    t3 = Term(2, 3)
    t3.feed("ab\u0301")
    assert t3.cell(0, 1)[0] == "b\u0301"
    assert (t3.cy, t3.cx) == (0, 1)


def mark_on_blank_row():
    """P73: marca sobre linha nunca escrita não corrompe as outras linhas."""
    t = Term(cols=10, rows=3)
    t.feed("\x1b[3;5H")  # cursor na coluna 5 de uma linha nunca escrita
    t.feed("\u0301")
    # a marca entrou na célula da própria linha, na caneta de quem escreveu
    assert t.cell(2, 3) == (" \u0301", DEF_FG, DEF_BG, 0, 0), t.cell(2, 3)
    # as outras linhas seguem no molde branco, cada uma na própria linha
    assert t.grid[0].ch == [" "] * 10 and list(t.grid[0].pk) == [_BLANK_V] * 10
    assert t.grid[1].ch == [" "] * 10 and t.grid[1].lk is None
    # as linhas que não receberam a marca seguem em branco
    assert _row_text(t.grid[0]) == " " * 10
    assert _row_text(t.grid[1]) == " " * 10
    # e a base real continua recebendo a marca (P73)
    t.feed("\x1b[1;1He\u0301")
    assert t.cell(0, 0)[0] == "e\u0301"
    assert _row_text(t.grid[1]) == " " * 10


def frozen_scrollback():
    """Histórico congelado: `ch` vira `str` e o texto sobrevive a reflow e foto."""
    from .term import _unpack, row_text

    def linhas(rows):
        return [row_text(r).rstrip() for r in rows if row_text(r).strip()]

    # 1. o que sai da tela vira str do tamanho de `cols`, e o texto é o mesmo
    t = Term(cols=12, rows=4)
    t.set_scrollback(50)
    for i in range(10):
        t.feed("linha%02d abc\r\n" % i)
    assert t.scrollback, "nada foi para o histórico"
    assert all(type(r.ch) is str for r in t.scrollback), "histórico devia estar congelado"
    assert all(len(r.ch) == 12 for r in t.scrollback), "str congelada tem de ter `cols`"
    assert all(row_text(r) == r.ch for r in t.scrollback), "row_text na str é a própria str"
    assert "linha00" in row_text(t.scrollback[0]), "primeira linha do histórico se perdeu"
    viva = "".join(t.row_text(y) for y in range(t.rows))
    assert "linha09" in viva, "a linha viva continua na grade"

    # 2. atributo sobrevive ao congelamento (a célula vem pelo caminho frio)
    t2 = Term(cols=12, rows=4)
    t2.feed("\x1b[31mvermelho\x1b[0m\r\n")
    for _ in range(4):
        t2.feed("enche\r\n")
    alvo = [r for r in t2.scrollback if "vermelho" in row_text(r)]
    assert alvo and type(alvo[0].ch) is str, "linha colorida devia congelar"
    fg, bg, fl = _unpack(alvo[0].pk[0])
    assert (fg, bg, fl) == (1, DEF_BG, 0), (fg, bg, fl)

    # 3. marca combinante tem mais de um code point por célula: fica lista
    t3 = Term(cols=8, rows=3)
    t3.feed("e\u0301abc\r\n")
    for _ in range(3):
        t3.feed("\r\n")
    com_marca = [r for r in t3.scrollback if "e\u0301" in row_text(r)]
    assert com_marca, "a linha com marca devia estar no histórico"
    assert type(com_marca[0].ch) is list, "linha com marca não pode congelar"

    # 4. reflow: a linha congelada re-quebra sem perder conteúdo
    t4 = Term(cols=20, rows=3)
    t4.set_scrollback(20)
    for i in range(6):
        t4.feed("linha %02d com texto\r\n" % i)
    # estreitar re-quebra cada linha em duas, então compara o texto lógico
    antes = "".join(linhas(t4.scrollback))
    t4.resize(10, 3)
    depois = "".join(linhas(t4.scrollback + t4.grid))
    assert depois.startswith(antes), (antes, depois)

    # 5. a foto do P57 atravessa a str congelada
    t5 = Term(cols=10, rows=3)
    for i in range(5):
        t5.feed("foto%02d\r\n" % i)
    volta = Term(cols=10, rows=3)
    volta.feed(t5.snapshot())
    assert "foto00" in "".join(linhas(volta.scrollback)), "a foto perdeu linha congelada"


def cell_packed_roundtrip():
    """Layout C: `_pack`/`_unpack` aguentam paleta, sentinelas, truecolor e flags."""
    # paleta (0-257, com os sentinelas do default) nos dois campos
    for fg, bg, fl in ((0, 0, 0), (1, 4, 0), (196, 16, 0), (DEF_FG, DEF_BG, 0)):
        assert _unpack(_pack(fg, bg, fl)) == (fg, bg, fl)
    # truecolor no extremo: branco é o maior valor que cabe em 25 bits
    branco = TC | 0xFFFFFF
    assert branco == (1 << 25) - 1
    assert _unpack(_pack(branco, branco, 0)) == (branco, branco, 0)
    # todas as flags juntas, com o estilo do sublinhado
    fl = ul_on(BOLD | INV | ITALIC | STRIKE | OVERLINE | DIM | HIDDEN | BLINK, UL_CURLY)
    assert _unpack(_pack(branco, 3, fl)) == (branco, 3, fl)
    assert ul_style(_unpack(_pack(0, 0, fl))[2]) == UL_CURLY
    # ida e volta pela grade: a célula que entra é a que sai
    t = Term(4, 2)
    t.feed("\x1b[1;4;7;9;53m\x1b[38;2;255;255;255m\x1b[48;5;196mX")
    assert t.cell(0, 0) == ("X", branco, 196, BOLD | UL | INV | STRIKE | OVERLINE, 0)
    t.feed("\x1b[0m")
    assert t.cell(0, 1) == (" ", DEF_FG, DEF_BG, 0, 0)
    # toda linha em branco compartilha o mesmo valor empacotado
    limpo = Term(4, 2)
    assert {v for row in limpo.grid for v in row.pk} == {_BLANK_V}
    assert _BLANK_V == _pack(DEF_FG, DEF_BG, 0)


def osc8_link_id():
    """P76: o `id=` agrupa células em um link; sem ele, o URI é a chave."""
    t = Term(10, 2)
    E = "\x1b]8;"
    t.feed(E + "id=A:foo=1;https://a\x1b\\x" + E + ";\x1b\\")
    t.feed(E + "id=A;https://a/outra\x1b\\y" + E + ";\x1b\\")
    t.feed(E + ";https://a\x1b\\z" + E + ";\x1b\\")
    assert t.link_of(t.cell(0, 0)[4]) == "https://a"
    assert t.link_key(t.cell(0, 0)[4]) == "A"  # o `id` vira a chave
    assert t.link_key(t.cell(0, 1)[4]) == "A"  # mesmo id, outro URI: mesmo link
    assert t.link_of(t.cell(0, 1)[4]) == "https://a/outra"
    assert t.link_key(t.cell(0, 2)[4]) == "https://a"  # sem id: o URI agrupa
    t.feed("\x1b[3J")  # a tabela morre junto com o histórico
    assert (t.links, t.link_keys) == ([], [])


def link_table_cap():
    """OSC 8: the table stops at LINK_MAX — past it the text is still text."""
    from . import term as modterm

    t = Term(20, 4)
    for n in range(modterm.LINK_MAX + 8):
        t.feed(f"\x1b]8;;http://x/{n}\x1b\\a\x1b]8;;\x1b\\")
    assert len(t.links) == modterm.LINK_MAX
    assert t.link == 0  # past the ceiling the cell has no link
    assert "a" in t.row_text(t.rows - 1)
    # a repeated URI still reuses its index: the ceiling counts distinct ones
    t2 = Term(20, 2)
    for _ in range(modterm.LINK_MAX + 8):
        t2.feed("\x1b]8;;http://same\x1b\\a\x1b]8;;\x1b\\")
    assert len(t2.links) == 1


def link_uri_clean():
    """OSC 8: a control character never reaches the link table (it goes to a menu
    and to xdg-open), and a URI of nothing but control is no link at all."""
    t = Term(20, 2)
    t.feed("\x1b]8;;http://a\x01b\x7fc\x1b\\x\x1b]8;;\x1b\\")
    assert t.links == ["http://abc"]
    assert t.link_of(t.cell(0, 0)[4]) == "http://abc"
    t2 = Term(20, 2)
    t2.feed("\x1b]8;;\x01\x02\x1b\\x\x1b]8;;\x1b\\")
    assert t2.links == [] and t2.link == 0
    # o resto do URI passa inteiro, espaço inclusive
    t3 = Term(20, 2)
    t3.feed("\x1b]8;;mailto:a b@c\x1b\\x\x1b]8;;\x1b\\")
    assert t3.links == ["mailto:a b@c"]


def title_sanitized():
    """OSC 0/2: the title carries no control, zero-width or direction mark, and
    what is text survives untouched (same rule as the Rust `sanitize_title`)."""
    from .term import sanitize_title

    # a U+202E would reverse the rest of the tab text; a control only breaks it
    assert sanitize_title("proj\r\n\x1b[31m\u202ex") == "proj[31mx"
    t = Term(20, 2)
    t.feed("\x1b]2;proj\r\n\x01\u202ex\u200b\u2060\u00ad\x7f\u009b\x07")
    assert t.title == "projx"
    # the title stack keeps the clean value too
    t.feed("\x1b[22;0t\x1b]0;outro\x07")
    assert t.title == "outro"
    t.feed("\x1b[23;0t")
    assert t.title == "projx"
    # normal text, space included, is not touched
    t.feed("\x1b]0;caf\u00e9 \u65e5\u672c \U0001f370\x07")
    assert t.title == "caf\u00e9 \u65e5\u672c \U0001f370"


def chrome_config():
    """P75: as cores do chrome vêm da configuração e vão para o CSS."""
    from . import config, style

    # o padrão é o token do `style.py`: uma fonte só
    padrao = style.defaults()
    assert set(padrao) == set(style.CHROME)
    assert {k: config.FALLBACK[k] for k in padrao} == padrao
    cfg = config.load(os.path.join(tempfile.mkdtemp(), "nao-existe.conf"))
    assert cfg.chrome == padrao
    # override chega no CSS pelos tokens certos (e só neles)
    css = style.css({"chrome_bg": "#101010"})
    assert "#sidebar { background-color: #101010; }" in css
    assert "notebook > header { background-color: #101010;" in css
    assert style.css({"chrome_accent_bg": "#222222"}).count("#222222") == 2
    # chave inválida não passa
    d = tempfile.mkdtemp()
    p = os.path.join(d, "tortty.conf")
    with open(p, "w") as f:
        f.write("chrome_fg vermelho\n")
    cfg = config.load(p)
    assert not cfg.ok and cfg.chrome["chrome_fg"] == padrao["chrome_fg"]


def hyperlinks():
    """OSC 8: o URI mora na célula, repetido reusa o índice, e o clique tem whitelist."""
    t = Term()
    t.feed("\x1b]8;;https://example.com\x1b\\A\x1b]8;;\x1b\\B")
    assert t.link_of(t.cell(0, 0)[4]) == "https://example.com"
    assert t.link_of(t.cell(0, 1)[4]) is None  # URI vazio fecha o link
    t.feed("\x1b]8;;https://example.com\x1b\\C")
    assert t.links == ["https://example.com"]  # internado, não duplicado
    assert t.link_of(t.cell(0, 2)[4]) == "https://example.com"
    assert link_allowed("https://x/y") and link_allowed("MAILTO:a@b")
    assert not link_allowed("javascript:alert(1)")
    assert not link_allowed("data:text/html,<script>")
    # CSI 3J apaga o histórico e a tabela: não sobra índice apontando pra nada
    t.feed("\x1b[3J")
    assert (t.links, t.link) == ([], 0)


def notifications():
    """`OSC 9`/`777` contam e guardam o texto; a barra de progresso não."""
    t = Term()
    t.feed("\x1b]9;build done\x07")
    assert (t.notifs, t.notif_text) == (1, "build done")
    # `9;4;estado[;%]` é a barra do mintty/ConEmu: engolida, não é recado
    t.feed("\x1b]9;4;1;50\x07\x1b]9;4;3\x07")
    assert (t.notifs, t.notif_text) == (1, "build done")
    # `777;notify;título;corpo` (urxvt) junta os dois; o resto do 777 não é nada
    t.feed("\x1b]777;notify;make;all done\x07")
    assert t.notif_text == "make: all done"
    t.feed("\x1b]777;notify;;body only\x07")
    assert t.notif_text == "body only"
    t.feed("\x1b]777;foo;bar\x07\x1b]777\x07\x1b]9;\x07")
    assert t.notifs == 3  # nada disso conta: nem 777 alheio, nem texto vazio
    # controle sai do texto (vai para uma linha de tela) e o tamanho tem teto
    t.feed("\x1b]9;a\nb\tc\x07")
    assert t.notif_text == "abc"
    t.feed("\x1b]9;" + "x" * 900 + "\x07")
    assert len(t.notif_text) == term.NOTIF_MAX


def osc9_progress():
    """`OSC 9;4` guarda (estado, %) em `Term.progress` (P65)."""
    t = Term()
    assert t.progress is None
    t.feed("\x1b]9;4;1;50\x07")
    assert t.progress == (1, 50)
    t.feed("\x1b]9;4;3\x07")
    assert t.progress == (3, None)  # sem % (indeterminado/pausado)
    t.feed("\x1b]9;4;1;999\x07")
    assert t.progress == (1, 100)  # % fora de 0..100: clamp
    t.feed("\x1b]9;4;7\x07")
    assert t.progress == (1, 100) and t.notifs == 0  # estado 7: engolido
    t.feed("\x1b]9;4;0\x07")
    assert t.progress is None
    t.feed("\x1b]9;4;1;x\x07")  # forma ruim: recado, como o `9;` comum
    assert t.notifs == 1 and t.progress is None


def osc7_cwd():
    """P47: `OSC 7` guarda o cwd do shell, com `%XX` decodificado."""
    t = Term()
    assert t.cwd is None  # sem OSC 7 o host pergunta ao /proc
    t.feed("\x1b]7;file://localhost/home/user\x07")
    assert t.cwd == "/home/user"
    t.feed("\x1b]7;file://host/with%20space\x07")
    assert t.cwd == "/with space"
    t.feed("\x1b]7;file://host\x07")  # sem caminho não há o que guardar
    assert t.cwd is None
    t.feed("\x1b]7;file:///srv\x07")
    t.feed("\x1b]7;nao-e-url\x07")  # payload fora do formato não apaga
    assert t.cwd == "/srv"
    t.feed("\x1b]7;\x07")
    assert t.cwd is None


def wheel_notches():
    """P48: a fração do touchpad só vira detente ao completar; direção zera."""
    n = mouse.Notches()
    assert n.add(0.4) == 0 and n.add(0.4) == 0  # fração não completa
    assert n.add(0.3) == 1  # 1.1 completa e sobra 0.1
    assert n.add(-0.6) == 0  # dedo virou: o resto (+0.1) foi descartado
    assert n.add(-0.5) == -1  # -1.1 completa, sobra -0.1
    # detente inteiro (mouse) chega de uma vez e não deixa resto pendente
    n = mouse.Notches()
    assert n.add(1) == 1 and n.add(-1) == -1
    # um flick largo entrega vários passos de uma vez
    n = mouse.Notches()
    assert n.add(3.2) == 3 and n.add(-0.3) == 0
    n.reset()
    assert n.add(0.9) == 0  # reset descarta a fração pendente
    # unidade maior que 1 (caso geral do acumulador)
    n = mouse.Notches()
    assert n.add(3, unit=2) == 1 and n.add(1, unit=2) == 1


# -- mouse, seleção e colagem (P1/P7) ----------------------------------
def mouse_modes_and_sgr():
    """Modos de mouse e a codificação SGR/X10."""
    t = Term()
    t.feed("\x1b[?1002h\x1b[?1006h")
    assert (t.mouse_mode, t.mouse_sgr) == (2, True)
    assert mouse.encode(mouse.LEFT, 0, 0, True, sgr=True) == "\x1b[<0;1;1M"
    assert mouse.encode(mouse.LEFT, 4, 2, False, sgr=True) == "\x1b[<0;5;3m"
    assert mouse.encode(mouse.LEFT, 0, 0, True) == ("\x1b[M" + chr(32) + chr(33) + chr(33))


def origin_mode():
    """P68: ?6 prende o cursor à região de rolagem e torna CUP relativo a ela."""
    t = Term()
    t.feed("\x1b[5;10r")  # região nas linhas 5..10 (0-based)
    t.feed("\x1b[?6h")
    assert t.origin and t.mode_state(6, True) == 1
    assert (t.cy, t.cx) == (4, 0)  # ligar manda o cursor para casa (o topo)
    t.feed("\x1b[2;3H")  # CUP relativo: linha 2 da região = linha 6 da tela
    assert (t.cy, t.cx) == (5, 2)
    t.feed("\x1b[99;1H")  # endereço além do fim: preso ao fundo da região
    assert t.cy == 9
    t.feed("\x1b[1;1H\x1b[5d")  # VPA também é relativo
    assert t.cy == 8
    t.feed("\x1b[?6l")  # desligado: volta ao endereçamento absoluto
    assert not t.origin and (t.cy, t.cx) == (0, 0)
    t.feed("\x1b[2;3H")
    assert (t.cy, t.cx) == (1, 2)
    t.feed("\x1b[?6h\x1b[!p")  # o soft reset (P59) volta a origin desligado
    assert not t.origin


# -- mouse: as formas de coordenada (P46/P69) -------------------------


def mouse_urxvt_and_utf8():
    """P69: ?1015 (decimal, botão+32) e ?1005 (coordenadas em UTF-8)."""
    t = Term()
    t.feed("\x1b[?1015h")
    assert t.mouse_urxvt and t.mode_state(1015, True) == 1
    # botão 0 + 32 = 32, coordenadas 1-based
    assert mouse.encode(mouse.LEFT, 3, 4, True, urxvt=True) == "\x1b[32;4;5M"
    assert mouse.encode(mouse.LEFT, 3, 4, False, urxvt=True) == "\x1b[35;4;5M"
    # passa do 223 do protocolo antigo (é a razão de existir)
    assert mouse.encode(mouse.LEFT, 499, 249, True, urxvt=True) == "\x1b[32;500;250M"
    t.feed("\x1b[?1015l\x1b[?1005h")
    assert not t.mouse_urxvt and t.mouse_utf8 and t.mode_state(1005, True) == 1
    # coluna 100: 101 + 32 = 133 -> dois bytes UTF-8 (C2 85)
    esperado = "\x1b[M" + chr(32) + b"\xc2\x85".decode("latin-1") + chr(4 + 1 + 32)
    assert mouse.encode(mouse.LEFT, 100, 4, True, utf8=True) == esperado
    # abaixo de 95 o UTF-8 é idêntico ao protocolo antigo
    assert mouse.encode(mouse.LEFT, 3, 4, True, utf8=True) == (
        "\x1b[M" + chr(32) + chr(36) + chr(37)
    )


def pixel_mouse():
    """P46: `?1016` é a forma SGR com as coordenadas em pixels, sem ?1006."""
    t = Term()
    t.feed("\x1b[?1016h")
    assert t.mouse_px and t.mode_state(1016, True) == 1
    assert mouse.encode(mouse.LEFT, 123, 456, True, pixels=True) == "\x1b[<0;124;457M"
    # sem ?1006 a forma continua SGR: não existe protocolo antigo de pixel
    assert mouse.encode(mouse.LEFT, 3, 4, False, pixels=True) == "\x1b[<0;4;5m"
    t.feed("\x1b[?1016l")
    assert not t.mouse_px and t.mode_state(1016, True) == 2
    # e sem pixel o protocolo antigo continua igual (col/row 0-based + 33)
    assert mouse.encode(mouse.LEFT, 3, 4, True) == ("\x1b[M" + chr(32) + chr(3 + 33) + chr(4 + 33))


# -- `OSC 9`/`777` e `OSC 7`: o que o app avisa (P44/P47) --------------


def double_and_triple_click():
    """Duplo clique: palavra até o espaço; triplo: linha lógica (soft-wrap incluso)."""
    t = Term()
    t.feed("foo bar/baz.txt   \r\n")
    assert t.word_span(0, 0) == (0, 2)  # foo
    assert t.word_span(0, 5) == (4, 14)  # o caminho inteiro, não só até a barra
    # o espaço da direita da linha não é palavra: clicar nele pega a última
    assert t.word_span(0, 16) == (4, 14)
    assert Term().word_span(0, 3) == (0, 0)  # linha em branco
    # linha lógica: a linha de 80 colunas que encheu e continuou na de baixo
    t = Term()
    t.feed("x" * 85 + "  tail   ")
    assert t.row_wrapped[0]
    assert t.line_span(1) == (0, 1)
    assert t.logical_line_span(1) == ((0, 0), (1, 10))  # sem o espaço da direita
    assert t.line_span(2) == (2, 2)  # linha sozinha não puxa vizinha


def selection():
    """Seleção multi-linha, invertida e sem newline sobrando no fim."""
    t = Term()
    t.feed("abc\r\ndef\r\nghi")
    assert t.selection_text((0, 1), (1, 1)) == "bc\nde"
    assert t.selection_text((0, 0), (0, 2)) == "abc"
    # a coluna 0 da linha de baixo fecha a seleção: nada da linha entra, só o
    # newline que separa (o caso do arrasto que termina no começo da linha)
    assert t.selection_text((0, 0), (1, 0)) == "abc\n"
    assert t.selection_text((0, 0), (0, 0)) == "a"  # dentro de uma linha, inclusiva
    assert t.selection_text((1, 1), (0, 1)) == "bc\nde"


def block_selection():
    """P61: Alt+arrasto copia a coluna (mesmas colunas em toda linha)."""
    from .term import CellAnchor, Term

    t = Term(cols=20, rows=4)
    t.feed("alpha\r\nbravo\r\ncharlie")
    g = t.abs_gen
    # colunas 1..3 das três linhas: "lph", "rav", "har"
    a = CellAnchor(0, 1, g)
    b = CellAnchor(2, 3, g)
    assert t.anchor_block_text(a, b) == "lph\nrav\nhar"
    # a ordem do arrasto não importa (de baixo para cima, da direita para a esquerda)
    assert t.anchor_block_text(b, a) == "lph\nrav\nhar"
    assert t.anchor_block_text(CellAnchor(0, 3, g), CellAnchor(2, 1, g)) == "lph\nrav\nhar"
    # a linear, na mesma âncora, junta o resto das linhas (é a diferença do bloco)
    assert t.anchor_text(a, b) == "lpha\nbravo\nchar"
    # coluna única e ponta além da linha: espaço à direita sai fora
    assert t.anchor_block_text(CellAnchor(0, 0, g), CellAnchor(1, 0, g)) == "a\nb"
    assert t.anchor_block_text(CellAnchor(2, 10, g), CellAnchor(2, 18, g)) == ""


def dropped_path():
    """P62: o caminho solto na janela vai cotado pro shell (regra do Rust)."""
    from .term import shell_quoted

    # o que passa sem aspas: caminho comum e os caracteres que o shell aceita
    assert shell_quoted("/tmp/a.txt") == "/tmp/a.txt"
    assert shell_quoted("/a,b=c@d:e+f-g_h.i/j") == "/a,b=c@d:e+f-g_h.i/j"
    # espaço, `$`, `*` e afins pedem aspas simples
    assert shell_quoted("/tmp/a b.txt") == "'/tmp/a b.txt'"
    assert shell_quoted("/tmp/$HOME*") == "'/tmp/$HOME*'"
    assert shell_quoted("/tmp/a;rm -rf /") == "'/tmp/a;rm -rf /'"
    # a aspa simples dentro do caminho vira '\'' (senão a citação fecha cedo)
    assert shell_quoted("/tmp/it's") == "'/tmp/it'\\''s'"
    # vazio também é cotado: sem aspas, o shell receberia nada
    assert shell_quoted("") == "''"


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
    assert t.cell(0, 0)[1] == rgb(18, 52, 86)
    assert t.cell(0, 1)[2] == rgb(250, 128, 114)
    assert cell_rgb(t.cell(0, 0)[1], FG_DEFAULT) == (18, 52, 86)
    t.feed("\x1b[38:2::7:8:9mC")
    assert cell_rgb(t.cell(0, 2)[1], FG_DEFAULT) == (7, 8, 9)
    t = Term()
    t.feed("\x1b[38;5;196mA\x1b[0mB")
    assert t.cell(0, 0)[1] == 196
    assert t.cell(0, 1)[1] == DEF_FG
    assert t.cell(0, 1)[2] == DEF_BG
    t = Term(cols=4, rows=2)
    t.feed("\x1b[38;2;1;2;3mXYZW")
    t.resize(8, 2)
    assert t.cell(0, 0)[1] == rgb(1, 2, 3)


def ligature_config():
    """P45: `ligatures` (off/standard/all) e o `font-features` de cada modo."""
    from . import config

    assert config.LIGATURES == ("off", "standard", "all")
    d = tempfile.mkdtemp()
    p = os.path.join(d, "tortty-python.conf")
    cfg = config.load(os.path.join(d, "nao-existe.conf"))
    assert cfg.ligatures == "standard"  # padrão: ligaduras da fonte, ligadas
    assert cfg.ligature_features == "liga=1,calt=1"
    for modo in config.LIGATURES:
        with open(p, "w") as f:
            f.write("ligatures %s\n" % modo)
        cfg = config.load(p)
        assert cfg.ok, config.message(cfg)
        assert cfg.ligatures == modo and cfg.ligature_features
    with open(p, "w") as f:
        f.write("ligatures none\n")
    cfg = config.load(p)
    assert not cfg.ok  # valor inválido é erro de linha, e o padrão vale
    assert cfg.ligatures == "standard"
    assert "liga=0" in config.LIGATURE_FEATURES["off"]


def palette_config():
    """P49: `#RRGGBB` na config, tema por aba e OSC 4/10/104/110 no Term."""
    from . import config, palette

    # parse da config: #RRGGBB e #RGB; o que não é cor vira erro de linha
    assert palette.parse_color("#d6d6d6") == 0xD6D6D6
    assert palette.parse_color("#fff") == 0xFFFFFF
    assert palette.parse_color("d6d6d6") is None
    assert palette.parse_color("#12345") is None
    # cor de OSC: rgb:r/g/b (1/2/4 dígitos, 4 = byte duplicado, como o xterm)
    assert palette.parse_osc_color("rgb:ff/80/00") == 0xFF8000
    assert palette.parse_osc_color("rgb:ffff/0/0000") == 0xFF0000
    assert palette.parse_osc_color("rgb:zz/0/0") is None
    assert palette.parse_osc_color("nada") is None
    # o default embarcado repete o palette.py: se um dos lados mudar, isto falha
    emb = {e.key: e.value for e in config.parse(config.DATA.read_text())}
    assert palette.int_rgb(palette.parse_color(emb["foreground"])) == palette.FG_DEFAULT
    assert palette.int_rgb(palette.parse_color(emb["background"])) == palette.BG_DEFAULT
    for i in range(16):
        c = palette.parse_color(emb["color%d" % i])
        assert palette.int_rgb(c) == palette.PALETTE[i]
    # tema: base = padrão; config sobrepõe; OSC 4 entra por cima e o 104 volta
    th = palette.Theme()
    assert th.color(1) == palette.PALETTE[1]
    th.apply_colors({"color1": 0x112233, "foreground": 0x445566})
    assert th.color(1) == (0x11, 0x22, 0x33)
    assert th.rgb_f(palette.DEF_FG) == (0x44 / 255, 0x55 / 255, 0x66 / 255)
    th.set_osc4(1, (9, 9, 9))
    assert th.color(1) == (9, 9, 9)
    th.reset_osc4([1])
    assert th.color(1) == (0x11, 0x22, 0x33)  # volta para a base da config
    # o Term escreve no próprio tema (a paleta é por aba) e responde a consulta
    t = Term(cols=10, rows=5)
    t.feed("\x1b]4;1;#123456\x07")
    assert t.theme.color(1) == (0x12, 0x34, 0x56)
    t.child_out = b""
    t.feed("\x1b]4;1;?\x07")
    assert b"rgb:1212/3434/5656" in bytes(t.child_out)
    t.feed("\x1b]4;20;#ffffff\x07")  # só 0..15, como o Rust
    assert t.theme.osc4.get(20) is None
    # frente define, cursor também, e o 110 volta para o valor da configuração
    t.feed("\x1b]10;#010203\x07")
    t.feed("\x1b]12;#aabbcc\x07")
    assert t.theme.fg == (1, 2, 3) and t.theme.cursor == (0xAA, 0xBB, 0xCC)
    t.feed("\x1b]110\x07")
    assert t.theme.fg == palette.FG_DEFAULT
    # 104;1 devolve só a entrada para a base
    t.feed("\x1b]104;1\x07")
    assert t.theme.color(1) == palette.PALETTE[1]


def session_restore():
    """P50: `restore_state` na config e o layout validado no state (puro)."""
    from . import config, state

    # config: padrão é layout; none desliga; content (P57) é o layout + a foto
    cfg = config.load(os.path.join(tempfile.mkdtemp(), "nao-existe.conf"))
    assert cfg.restore_state == "layout"
    p = os.path.join(tempfile.mkdtemp(), "c.conf")
    with open(p, "w") as f:
        f.write("restore_state none\n")
    cfg = config.load(p)
    assert cfg.ok and cfg.restore_state == "none"
    with open(p, "w") as f:
        f.write("restore_state content\n")
    cfg = config.load(p)
    assert cfg.ok and cfg.restore_state == "content"
    with open(p, "w") as f:
        f.write("restore_state foto\n")  # grau que não existe é erro
    cfg = config.load(p)
    assert not cfg.ok and cfg.restore_state == "layout"

    # roundtrip com o formato do Rust: workspaces, cwds e o que estava na frente
    aqui = os.getcwd()
    lay = state.layout(
        {
            "layout": {
                "workspaces": [
                    {"name": "ws um", "cwds": [aqui, None]},
                    {"name": "ws dois", "cwds": ["/tmp"]},
                ],
                "ws": 1,
                "tab": 0,
            }
        }
    )
    assert lay["workspaces"][0]["cwds"] == [aqui, None]
    assert (lay["ws"], lay["tab"]) == (1, 0)
    # sem layout (arquivo antigo) e lixo: None — a janela abre com uma aba
    assert state.layout({}) is None
    assert state.layout("x") is None
    assert state.layout({"layout": {"workspaces": [], "ws": 0, "tab": 0}}) is None
    assert state.layout({"layout": "x"}) is None
    assert state.layout({"layout": {"workspaces": [{"name": 1, "cwds": []}]}}) is None
    # cwd que sumiu vira None (a aba nasce no padrão do shell); índice fora da
    # faixa é preso na primeira posição
    lay = state.layout(
        {
            "layout": {
                "workspaces": [{"name": "w", "cwds": ["/nao/existe/xyz", aqui]}],
                "ws": 9,
                "tab": 9,
            }
        }
    )
    assert lay["workspaces"][0]["cwds"][0] is None
    assert (lay["ws"], lay["tab"]) == (0, 0)


def snapshot_restore():
    """P57: a foto ANSI volta igual, sem a marca, e re-quebra como o resize."""
    from . import state

    def texto(t):
        rows = t.scrollback + t.grid
        return [_row_text(r).rstrip() for r in rows]

    t = Term(cols=20, rows=6)
    t.feed("\x1b[1;31mred bold\x1b[0m plain\r\n")
    t.feed("\x1b[4:3mcurly\x1b[0m \x1b[7minverse\x1b[0m\r\n")
    t.feed("w\xe9 and \u65e5\u672c wide\r\n")
    t.feed("\x1b]8;;https://example.com/x\x1b\\link\x1b]8;;\x1b\\\r\n")
    t.feed("0123456789012345678901234567890123456789")  # quebra mole: 2 linhas
    foto = t.snapshot()
    # o branco à direita da linha não viaja (a linha 1 acaba em "plain")
    assert "\x1b[0;39;49m plain\r\n" in foto
    # volta igual: alimentar um Term novo e fotografar de novo dá os mesmos bytes
    c = Term(cols=20, rows=6)
    c.feed(foto)
    assert c.snapshot() == foto
    assert texto(c) == texto(t)
    # atributos sobrevivem: negrito, cor 1, sublinhado curvo, inverso
    assert c.cell(0, 0)[3] & BOLD and c.cell(0, 0)[1] == 1
    assert c.cell(1, 0)[3] & UL and ul_style(c.cell(1, 0)[3]) == UL_CURLY
    assert c.cell(1, 7)[3] & INV
    # e o link volta com o mesmo URI
    assert c.links == ["https://example.com/x"]
    assert c.link_of(c.cell(3, 0)[4]) == "https://example.com/x"
    # quebra mole não vira `\n`: reaberta mais larga, o parágrafo é uma linha
    largo = Term(cols=40, rows=6)
    largo.feed(foto)
    assert _row_text(largo.grid[4]) == "0123456789012345678901234567890123456789"
    # tela cheia não é o que volta: a foto é do buffer principal
    a = Term(cols=20, rows=4)
    a.feed("shell prompt\r\n")
    a.feed("\x1b[?1049h")
    a.feed("vim owns this")
    assert "shell prompt" in a.snapshot() and "vim owns this" not in a.snapshot()
    # a marca da restauração é decoração: na tela, fora da foto — e segue a
    # linha pela re-quebra sem virar conteúdo
    m = Term(cols=30, rows=4)
    m.feed("before\r\n")
    m.feed_chrome("\r\n\x1b[2m-- restored --\x1b[0m\r\n")
    m.feed("after\r\n")
    assert "before" in m.snapshot() and "after" in m.snapshot()
    assert "restored" not in m.snapshot()
    m.feed_chrome("x" * 40)  # marca que enche duas linhas e quebra mole
    m.resize(20, 4)
    assert "restored" not in m.snapshot() and "xxxx" not in m.snapshot()
    # caractere de controle no URI veio do filho: não pode virar escape
    bad = Term(cols=20, rows=2)
    bad.links.append("a\x1b[31mb")
    bad.link_keys.append("a\x1b[31mb")
    bad.link = 1
    bad.feed("X")  # célula com o link 1, cujo URI tem caractere de controle
    assert bad.cell(0, 0) == ("X", DEF_FG, DEF_BG, 0, 1)
    ruim = bad.snapshot()
    assert "X" in ruim and "a[31mb" in ruim and "\x1b[31m" not in ruim

    # um arquivo por (workspace, aba), ao lado do window.json; o que não foi
    # reescrito é de uma sessão que não existe mais
    old = os.environ.get("XDG_STATE_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_STATE_HOME"] = tmp
        try:
            assert state.load_snapshot(0, 0) is None  # ausente não é erro
            state.save({"x": 1})
            state.save_snapshots([(0, 0, "uma"), (0, 1, "outra")])
            assert state.load_snapshot(0, 1) == "outra"
            assert state.load() == {"x": 1}  # a foto não come o window.json
            state.save_snapshots([(0, 0, "só uma")])
            assert state.load_snapshot(0, 0) == "só uma"
            assert state.load_snapshot(0, 1) is None  # aba fechada não volta
            state.save_snapshots([])  # chave desligada: apaga o que ficou
            assert state.load_snapshot(0, 0) is None
        finally:
            if old is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old


def media_transmission():
    """P96: `t=f`/`t=t`/`t=s` — o payload é um caminho, e quem lê é o gancho."""
    import base64 as b64

    from . import media

    # um PNG 2x2 de verdade, montado aqui (nada de arquivo no repositório)
    def png(w, h, px):
        import struct
        import zlib

        raw = b"".join(b"\x00" + bytes(px(i, x)) for i in range(h) for x in range(w))

        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw))

    data = png(4, 2, lambda r, x: (r * 60, x * 60, 0, 255))
    d = tempfile.mkdtemp()

    def escritor(nome, corpo=data):
        p = os.path.join(d, nome)
        with open(p, "wb") as f:
            f.write(corpo)
        return p

    def abre(p, delete=False):
        return media.load(p, delete)

    def termo(load):
        t = Term(20, 6)
        t.cell_size = (7, 16)
        t.graphics.load = load
        return t

    def apc(corpo, path):
        return "\x1b_G%s;%s\x1b\\" % (corpo, b64.b64encode(path.encode()).decode())

    foto = escritor("foto.png")
    # sem gancho (camada pura sozinha) o arquivo não é lido: ENOENT, tela limpa
    t = termo(None)
    t.feed(apc("a=T,f=100,t=f,i=7,c=2,r=1", foto))
    assert (len(t.graphics.images), len(t.graphics.placements)) == (0, 0)
    assert bytes(t.child_out) == b"\x1b_Gi=7;ENOENT:file\x1b\\"
    # com o gancho: lido, guardado como PNG (f=100 pelo magic) e colocado
    t = termo(abre)
    t.feed(apc("a=T,f=100,t=f,i=7,c=2,r=1", foto))
    img = t.graphics.images[7]
    assert (img.width, img.height, img.fmt) == (4, 2, 100), (img.width, img.height, img.fmt)
    assert bytes(t.child_out) == b"\x1b_Gi=7;OK\x1b\\"
    assert (t.cx, t.cy) == (0, 1)  # o cursor desceu uma linha, como no `t=d`
    # `t=t` apaga o temporário; `t=s` lê /dev/shm e NÃO apaga
    tmp = escritor("tmp.png")
    t = termo(abre)
    t.feed(apc("a=t,f=100,t=t,i=8", tmp))
    assert 8 in t.graphics.images and not os.path.exists(tmp), "t=t deve apagar"
    nome = "tortty-check-%d" % os.getpid()
    shm = "/dev/shm/" + nome
    with open(shm, "wb") as f:
        f.write(data)
    try:
        t = termo(abre)
        t.feed(apc("a=t,f=100,t=s,i=9", nome))
        assert 9 in t.graphics.images and os.path.exists(shm), "t=s não apaga"
    finally:
        if os.path.exists(shm):
            os.unlink(shm)
    sonda = escritor("sonda.png")
    # `a=q` com arquivo: OK é a resposta que faz o cliente mandar por ali
    t = termo(abre)
    t.feed(apc("a=q,f=100,t=f,i=1", sonda))
    assert bytes(t.child_out) == b"\x1b_Gi=1;OK\x1b\\", bytes(t.child_out)
    # caminho que não existe: nem sonda nem transmissão passam
    t = termo(abre)
    t.feed(apc("a=T,f=100,t=f,i=2", os.path.join(d, "nao-existe.png")))
    assert not t.graphics.images and b"ENOENT:file" in bytes(t.child_out)
    # teto: um arquivo acima de MEDIA_MAX é recusado, não carregado
    gordo = escritor("gordo.png", data + b"\x00" * (media.MEDIA_MAX + 1))
    assert media.load(gordo) is None
    os.unlink(gordo)


def shortcut_table():
    """P95: acorde, ação e a tabela do config — `unmap` liberta de verdade."""
    from . import keymap

    assert keymap.parse_chord("ctrl+shift+y") == ("y", frozenset({"ctrl", "shift"}))
    assert keymap.parse_chord("shift+page_up") == ("page_up", frozenset({"shift"}))
    assert keymap.parse_chord("f2") == ("f2", frozenset())
    for ruim in ("ctrl+", "ctrl", "", "ctrl+foo+y", "shift+alt"):
        assert keymap.parse_chord(ruim) is None, ruim
    assert keymap.check_map("ctrl+shift+y new_tab") is None
    assert keymap.check_map("ctrl+shift+y no_such_action") == "unknown action: no_such_action"
    assert "not a chord" in keymap.check_map("ctrl++y new_tab")
    assert keymap.check_map("alt+1 select_tab") == "select_tab needs a number"
    assert keymap.check_map("alt+11 select_tab 11") == "select_tab takes 1..10"
    assert keymap.check_map("ctrl+x new_tab 3") == "new_tab takes no number"
    assert keymap.check_map("unmap ctrl+shift+w") is None
    assert keymap.check_unmap("ctrl+shift+w") is None
    assert keymap.check_unmap("ctrl+shift+w extra") == "unmap takes one chord"

    # a tabela: defaults, um `map` novo e um `unmap` que tira o default
    b = keymap.Bindings()
    assert b.get("t", ["ctrl", "shift"]) == ("new_tab", None)
    assert b.get("3", ["alt"]) == ("select_tab", 3)
    b = keymap.Bindings(["map ctrl+shift+t new_workspace", "unmap ctrl+shift+w"])
    assert b.get("t", ["ctrl", "shift"]) == ("new_workspace", None)  # re-ligado
    assert b.get("w", ["ctrl", "shift"]) is None  # libertado
    assert b.get("1", ["alt"]) == ("select_tab", 1)  # o resto intacto
    # P97: carregar o workspace é ação da tabela, como andar por eles
    assert b.get("up", ["super", "shift"]) == ("ws_move_up", None)
    assert b.get("down", ["super", "shift"]) == ("ws_move_down", None)
    # e o config: `map` acumula sobre os defaults, `unmap` normalizado na tabela
    from . import config

    c = config.load(os.path.join(tempfile.mkdtemp(), "nao-existe.conf"))
    assert c.map_lines == keymap.DEFAULTS and (c.ok, c.warnings) == (True, [])
    assert c.bindings.get("f", ["ctrl", "shift"]) == ("search", None)
    p = os.path.join(tempfile.mkdtemp(), "tortty-python.conf")
    with open(p, "w") as f:
        f.write("map ctrl+shift+y new_tab\nunmap ctrl+shift+w\n")
    c = config.load(p)
    assert c.ok, c.errors
    assert c.bindings.get("y", ["ctrl", "shift"]) == ("new_tab", None)  # novo
    assert c.bindings.get("w", ["ctrl", "shift"]) is None  # default libertado
    assert c.bindings.get("t", ["ctrl", "shift"]) == ("new_tab", None)  # default fica
    # linha inválida não derruba o arquivo: vira erro e as outras valem
    with open(p, "w") as f:
        f.write("map ctrl+shift+y nope\nmap ctrl+alt+k new_tab\n")
    c = config.load(p)
    assert not c.ok and "unknown action: nope" in c.errors[0]
    assert c.bindings.get("k", ["ctrl", "alt"]) == ("new_tab", None)


def search_scrollback():
    """P94: `find_hits` acha no histórico e na tela, e a busca anda e circula."""
    from .term import HITS_MAX, Search, find_hits

    t = Term(cols=20, rows=3)
    t.feed("alfa BETA\r\nbeta beta\r\n")
    t.feed("\r\n\r\nbeta no histórico")
    assert t.scrolled == 2  # duas linhas foram para o histórico
    hits = find_hits(t, "beta")
    # linha absoluta: 0 e 1 no histórico, 4 na grade (a linha 2 está vazia)
    assert [tuple(h) for h in hits] == [(0, 5, 4), (1, 0, 4), (1, 5, 4), (4, 0, 4)], hits
    assert find_hits(t, "") == [] and find_hits(t, "zebra") == []
    assert find_hits(t, "BETA") == hits  # dobra de caixa ASCII
    # teto: 5000 ocorrências, não uma por célula de um histórico gigante
    t2 = Term(cols=80, rows=4)
    t2.feed(("a" * 79 + "\r\n") * 200)
    assert len(find_hits(t2, "a")) == HITS_MAX, len(find_hits(t2, "a"))
    # a busca aponta o mais novo e circula nas duas pontas
    s = Search("beta")
    assert s.run(t) == hits[-1] and s.at == len(hits) - 1
    assert s.step(False) == hits[0]  # "próximo" volta ao começo
    assert s.step(True) == hits[-1]  # e "anterior" fecha o círculo
    assert Search("").run(t) is None and Search("x").step(True) is None


def prompt_marks():
    """P93: `OSC 133` guarda A/B/C/D em linha absoluta e sabe saltar entre prompts."""
    t = Term(cols=20, rows=5)
    t.feed("\x1b]133;A\x07$ ls\r\n")
    t.feed("\x1b]133;B\x07")
    t.feed("\x1b]133;C\x07um\r\ndois\r\n")
    t.feed("\x1b]133;D;2\x07")
    kinds = [(m.line, m.kind, m.status) for m in t.marks]
    assert kinds == [(0, "A", None), (1, "B", None), (1, "C", None), (3, "D", 2)], kinds
    # forma desconhecida não vira marca
    t.feed("\x1b]133;Z\x07\x1b]1337;File=inline=1\x07\x1b]133;A;aid=7\x07")
    assert len(t.marks) == 5 and t.marks[-1] == Mark(3, "A", None), t.marks[-1]
    # a marca não anda quando o output empurra o texto para o histórico
    t.feed("\r\n" * 6)
    assert t.scrolled == 5 and [m.line for m in t.marks if m.kind == "A"] == [0, 3]
    # pular: estritamente acima / daqui para baixo
    assert t.prompt_line(3, True) == 0 and t.prompt_line(0, False) == 3
    assert t.prompt_line(0, True) is None and t.prompt_line(3, False) is None
    # o histórico indo embora leva as marcas junto (poda preguiçosa: na
    # próxima marca ou consulta) — o corte do teto não tira linha absoluta
    t.feed("\x1b[3J")
    assert t.prompt_line(t.scrolled, True) is None and t.marks == [], t.marks
    # teto: 600 marcas deixam MARK_CAP
    t2 = Term(cols=20, rows=5)
    for _ in range(600):
        t2.feed("\x1b]133;A\x07")
        t2.feed("\r\n")
    assert len(t2.marks) == MARK_CAP, len(t2.marks)


def prompt_status():
    """P103: `OSC 133;D` vira o status do último comando da aba (e não some)."""
    t = Term(cols=20, rows=5)
    assert t.cmd_status is None  # sem shell integration não há o que mostrar
    t.feed("\x1b]133;A\x07$ false\r\n\x1b]133;C\x07\x1b]133;D;1\x07")
    assert t.cmd_status == 1, t.cmd_status
    # o prompt seguinte não apaga o que o último comando disse: é isso que a
    # aba tem para mostrar enquanto o usuário digita o próximo
    t.feed("\x1b]133;A\x07$ true\r\n\x1b]133;B\x07\x1b]133;C\x07")
    assert t.cmd_status == 1, t.cmd_status
    t.feed("\x1b]133;D;0\x07")
    assert t.cmd_status == 0, t.cmd_status
    # `D` sem número diz "acabou", não "falhou": o status anterior fica
    t.feed("\x1b]133;D\x07")
    assert t.cmd_status == 0, t.cmd_status
    # status grande (128+sinal) passa inteiro, e o histórico rolando não mexe
    t.feed("\x1b]133;D;137\x07\r\n" * 4)
    assert t.cmd_status == 137 and t.scrolled > 0, (t.cmd_status, t.scrolled)
    # forma inválida não inventa status
    t.feed("\x1b]133;D;abc\x07")
    assert t.cmd_status == 137, t.cmd_status
    # RIS volta ao começo: sem marca, sem status
    t.feed("\x1bc")
    assert t.cmd_status is None, t.cmd_status
    # `CSI 3J` leva o histórico, não a verdade sobre o último comando
    t2 = Term(cols=20, rows=5)
    t2.feed("\x1b]133;D;2\x07\x1b[3J")
    assert t2.cmd_status == 2, t2.cmd_status


def copy_mode():
    """P104: o cursor do modo cópia anda preso ao que existe e copia o trecho."""
    t = Term(cols=12, rows=4)
    t.feed("um\r\ndois\r\ntres\r\nquatro\r\ncinco\r\nseis\r\n")
    assert t.scrolled == 3 and len(t.scrollback) == 3, (t.scrolled, len(t.scrollback))
    # começa onde o olho está, não no fim do mundo
    cur = t.anchor_at(0, 0, 0)  # primeira fileira da visão viva
    assert cur.line == t.scrolled, cur
    # andar para trás entra no histórico e para na primeira linha que existe
    c = t.copy_cursor(cur.line, 0, -1, 0)
    assert c.line == t.scrolled - 1, c
    c = t.copy_cursor(c.line, 0, -100, 0)
    assert c.line == t.scrolled - len(t.scrollback) == 0, c  # nem mais para trás
    # para frente para na última linha do vivo (a barra do modo é outra coisa)
    c = t.copy_cursor(cur.line, 0, 100, 0)
    assert c.line == t.scrolled + t.rows - 1, c
    # coluna presa à largura da grade
    assert t.copy_cursor(cur.line, 0, 0, -5).col == 0
    assert t.copy_cursor(cur.line, 0, 0, 999).col == t.cols - 1
    # a geração vem junto: reflow invalida o cursor antigo (a seleção morre)
    velho = t.copy_cursor(0, 0, 0, 0)
    t.resize(20, 4)
    assert not t.anchor_alive(velho), velho
    # o que o `y` copia: da marca ao cursor, mesmo fora da tela
    t2 = Term(cols=12, rows=3)
    t2.feed("linha1\r\nlinha2\r\nlinha3\r\nlinha4\r\nlinha5\r\n")
    topo = t2.scrolled - len(t2.scrollback)
    a = t2.copy_cursor(topo, 0, 0, 0)  # topo do histórico
    b = t2.copy_cursor(topo, 0, 2, 0)  # duas linhas abaixo
    # parar na coluna 0 da terceira linha entrega as duas de cima e o "\n"
    # delas: a coluna 0 é o fim da seleção, não o começo da linha
    assert t2.anchor_text(a, b).split("\n") == ["linha1", "linha2", ""], t2.anchor_text(a, b)
    # parando na última coluna da terceira linha, a linha vem inteira
    b = t2.copy_cursor(topo, 0, 2, 99)
    assert t2.anchor_text(a, b).split("\n") == ["linha1", "linha2", "linha3"], t2.anchor_text(a, b)
    # marca "ao contrário" devolve o mesmo texto (a ordem é normalizada)
    assert t2.anchor_text(b, a) == t2.anchor_text(a, b)


def state_owner_lock():
    """P91: one owner of the state — a second window gets None and stays scratch."""
    from . import state

    old = os.environ.get("XDG_STATE_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_STATE_HOME"] = tmp
        try:
            dono = state.lock()
            assert dono is not None and os.path.exists(
                os.path.join(tmp, "tortty-python", "state.lock")
            )
            assert state.lock() is None  # segunda janela: o lock está tomado
            dono.close()  # fechar solta
            outra = state.lock()
            assert outra is not None
            outra.close()
        finally:
            if old is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old


def title_stack():
    """P52: `CSI 22 t` empilha o título e `23 t` devolve, com teto e sem invenção."""

    def set_title(txt):
        t.feed("\x1b]2;%s\x07" % txt)

    t = Term(cols=20, rows=4)
    set_title("um")
    t.feed("\x1b[22;0t")
    set_title("dois")
    assert t.title == "dois"
    t.feed("\x1b[23;0t")  # vim sai: o título de antes volta
    assert t.title == "um"
    # pilha vazia não inventa título
    t.feed("\x1b[23;0t")
    assert t.title == "um"
    # Ps acima de 2 (ícone) não mexe na pilha do título
    set_title("tres")
    t.feed("\x1b[22;9t")
    t.feed("\x1b[23;0t")
    assert t.title == "tres"
    # aninhado, como o vim empilha ao abrir outro arquivo
    set_title("a")
    t.feed("\x1b[22;0t")
    set_title("b")
    t.feed("\x1b[22;0t")
    set_title("c")
    for esperado in ("b", "a"):
        t.feed("\x1b[23;0t")
        assert t.title == esperado, (t.title, esperado)
    # teto: a pilha não cresce sem limite
    t2 = Term(cols=20, rows=4)
    for _ in range(40):
        t2.feed("\x1b[22;0t")
    assert len(t2.title_stack) == TITLE_STACK_MAX


def tab_stops():
    """P53: `ESC H`/`CSI g` põem e tiram paradas, `CSI I`/`Z` andam por elas."""

    def cx_after(txt):
        t = Term(cols=40, rows=3)
        t.feed(txt)
        return t.cx

    assert cx_after("\t") == 8  # parada padrão de 8, como antes
    assert cx_after("\t\t") == 16
    assert cx_after("\x1b[4I") == 32  # CHT: quatro paradas
    assert cx_after("\x1b[17G\x1b[2Z") == 0  # CBT: de 16, duas paradas atrás
    assert cx_after("\x1b[17G\x1b[Z") == 8
    # parada posta em 3: o HT vai para 3, a próxima é a 8 (a de sempre)
    assert cx_after("\x1b[4G\x1bH\r\t") == 3
    assert cx_after("\x1b[4G\x1bH\r\t\t") == 8
    # `CSI g` tira a parada desta coluna; `3g` tira todas (o HT vai ao fim).
    # `CSI 9 G` é o índice 8 em 0-based, e é lá que mora a segunda parada
    t = Term(cols=40, rows=3)
    t.feed("\x1b[9G\x1b[g\r\t")
    assert t.cx == 16, t.cx  # a 8 sumiu, então a 16 é a próxima
    t = Term(cols=40, rows=3)
    t.feed("\x1b[3g\r\t")
    assert t.cx == 39, t.cx  # sem parada nenhuma, HT vai à última coluna
    # P100: o resize PRESERVA a parada posta pelo app; a coluna nova ganha a de 8
    t = Term(cols=40, rows=3)
    t.feed("\x1b[4G\x1bH")
    t.resize(41, 3)
    assert t.tabstops[3] is True and len(t.tabstops) == 41
    assert t.tabstops[40] is True and t.tabstops[39] is False  # 40 % 8 == 0
    t.feed("\x1b[3g")  # `3g` tira todas; o resize seguinte não inventa nenhuma
    t.resize(49, 3)
    assert t.tabstops[3] is False and t.tabstops[48] is True  # só as novas de 8
    # encolher corta a lista e mantém o que sobrou
    t = Term(cols=40, rows=3)
    t.feed("\x1b[4G\x1bH")
    t.resize(20, 3)
    assert len(t.tabstops) == 20 and t.tabstops[3] is True
    # tabulação com espaço e texto continua alinhando na célula
    t = Term(cols=40, rows=3)
    t.feed("a\tb")
    assert t.cell(0, 0)[0] == "a" and t.cell(0, 8)[0] == "b"


def strike_and_overline():
    """P54: `SGR 9`/`29` e `53`/`55` põem e tiram riscado e sobrelinha."""
    from .palette import OVERLINE, STRIKE

    t = Term(cols=10, rows=3)
    t.feed("\x1b[9mx\x1b[29my")
    assert t.cell(0, 0)[3] & STRIKE
    assert not t.cell(0, 1)[3] & STRIKE
    t.feed("\x1b[53m\x1b[9mz")
    fl = t.cell(0, 2)[3]
    assert fl & STRIKE and fl & OVERLINE
    t.feed("\x1b[55m\x1b[0mw")
    assert not t.cell(0, 3)[3] & (STRIKE | OVERLINE)
    # SGR 0 limpa as duas
    t.feed("\x1b[9;53ma\x1b[mb")
    assert t.cell(0, 4)[3] & (STRIKE | OVERLINE)
    assert not t.cell(0, 5)[3] & (STRIKE | OVERLINE)


def screen_scroll():
    """P55: `CSI S`/`T` rolam a tela sem mexer no cursor; `ESC M` no topo rola."""
    t = Term(cols=10, rows=4)
    t.feed("1\x1b[2;1H2\x1b[3;1H3\x1b[4;1H4")
    assert [t.row_text(i).strip() for i in range(4)] == ["1", "2", "3", "4"]
    cy, cx = t.cy, t.cx
    t.feed("\x1b[S")  # SU: sobe uma linha, conteúdo sai pelo topo
    assert [t.row_text(i).strip() for i in range(4)] == ["2", "3", "4", ""], [
        t.row_text(i) for i in range(4)
    ]
    assert (t.cy, t.cx) == (cy, cx)  # o cursor não se move
    t.feed("\x1b[T")  # SD: desce de volta
    assert [t.row_text(i).strip() for i in range(4)] == ["", "2", "3", "4"]
    # `n` linhas de uma vez, e a região (DECSTBM) é respeitada
    t.feed("\x1b[2S")
    assert [t.row_text(i).strip() for i in range(4)] == ["3", "4", "", ""]
    # RI no topo da tela rola para baixo: antes disto o cursor só subia
    t2 = Term(cols=10, rows=3)
    t2.feed("a\r\nb\x1b[H\x1bM")
    assert [t2.row_text(i).strip() for i in range(3)] == ["", "a", "b"], [
        t2.row_text(i) for i in range(3)
    ]


def rep_and_keypad():
    """P56: `REP` (`CSI b`), `DECKPAM`/`DECKPNM` e o `?66` no DECRQM."""
    t = Term(cols=20, rows=3)
    t.feed("-")
    t.feed("\x1b[4b")  # repete o último impresso quatro vezes
    assert t.row_text(0).rstrip() == "-----"
    assert t.cx == 5
    # sem nada impresso, o REP repete espaço (default do ECMA)
    t2 = Term(cols=20, rows=3)
    t2.feed("\x1b[3b")
    assert t2.row_text(0)[:3] == "   " and not t2.row_text(0)[3:].strip()
    assert t2.cx == 3
    # REP com contagem zero (ou ausente) é uma vez
    t.feed("\x1b[b")
    assert t.row_text(0).rstrip() == "------"
    # DECKPAM/DECKPNM: só estado, e o DECRQM resposta acompanha
    assert t.keypad_app is False
    t.feed("\x1b=")
    assert t.keypad_app is True
    t.child_out = b""
    t.feed("\x1b[?66$p")
    assert b"\x1b[?66;1$y" in bytes(t.child_out), bytes(t.child_out)
    t.feed("\x1b>")
    assert t.keypad_app is False
    t.child_out = b""
    t.feed("\x1b[?66$p")
    assert b"\x1b[?66;2$y" in bytes(t.child_out), bytes(t.child_out)
    # RIS limpa o modo (como no Rust)
    t.feed("\x1b=\x1bc")
    assert t.keypad_app is False


def lnm_and_soft_reset():
    """P58/P59: `LNM` (LF volta a coluna) e `DECSTR` (soft reset sem limpar)."""
    from .palette import DEF_BG, DEF_FG
    from .term import Term

    # LNM desligado (padrão): `\n` mantém a coluna — é o que faz a escada
    t = Term(cols=20, rows=3)
    t.feed("ab\nc")
    assert t.row_text(1).startswith("  c"), repr(t.row_text(1))
    assert (t.cy, t.cx) == (1, 3)
    # LNM ligado: `\n` volta a coluna ao zero
    t = Term(cols=20, rows=3)
    t.feed("\x1b[20hab\nc")
    assert t.row_text(1).startswith("c"), repr(t.row_text(1))
    assert (t.cy, t.cx) == (1, 1)
    # DECRQM responde pelo modo ANSI (sem `?`: é modo ANSI, não privado)
    t.feed("\x1b[20$p")
    assert t.child_out == b"\x1b[20;1$y", t.child_out
    t.child_out = b""
    t.feed("\x1b[20l\x1b[20$p")
    assert t.child_out == b"\x1b[20;2$y", t.child_out

    # DECSTR: atributos e modos voltam ao padrão, a tela e o histórico ficam
    t = Term(cols=20, rows=4)
    t.feed("\x1b[1;4;9;31;42mtexto")  # bold+under+strike, fg 1, bg 2
    t.feed("\x1b[2;3r")  # região de scroll 1..2 (0-based)
    t.feed("\x1b[?1h\x1b[?25l\x1b=\x1b[10;10H")
    antes = [t.row_text(y) for y in range(4)]
    t.feed("\x1b[!p")
    assert (t.fg, t.bg, t.flags) == (DEF_FG, DEF_BG, 0)
    assert (t.cursor_visible, t.app_cursor, t.keypad_app) == (True, False, False)
    assert (t.top, t.bottom) == (0, 3)
    assert [t.row_text(y) for y in range(4)] == antes  # grade intacta
    # o que o Rust também deixa de fora: LNM e o cursor pedido por `CSI 6 q`
    t = Term(cols=20, rows=3)
    t.feed("\x1b[20h\x1b[4 q\x1b[!p")
    assert (t.lnm, t.app_cursor_style) == (True, ("underline", False))
    # sem parâmetro nenhum de verdade (`CSI ! p` cru, params vazios)
    t.feed("\x1b[1m\x1b[!p")
    assert t.flags == 0


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
        # o status da aba (P103) fica em quatro fundos diferentes
        *[
            (fg, bg)
            for fg in (style.TAB_OK_FG, style.TAB_ERR_FG)
            for bg in (
                style.TAB_BAR_BG,
                style.TAB_ACTIVE_BG,
                style.BELL_BG,
                style.NOTIF_BG,
            )
        ],
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
    txt = shortcut.entry("/opt/bin/tortty-python")
    assert "Exec=/opt/bin/tortty-python" in txt
    assert "StartupWMClass=tortty-python" in txt
    # a classe igual ao nome do .desktop é o que agrupa a janela no dock
    assert shortcut.WMCLASS == shortcut.APP
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
    """remove() apaga o nome atual e o anterior, não o tortty da versão Rust."""
    tmp = tempfile.mkdtemp()
    old = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = tmp
    try:
        made = []
        for name in (shortcut.APP, shortcut.LEGACY, "tortty"):
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
        assert left == ["tortty.desktop", "tortty.svg"], left
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
    sgr_italic_and_underline_styles,
    alt_screen_and_scroll,
    alt_screen_keeps_scrollback,
    charset_and_replies,
    csi_with_intermediate,
    csi_hpa,
    argv_parsing,
    debug_socket,
    kitty_keyboard,
    config_file,
    config_options,
    scrollback_and_bell,
    graphics_image_and_offset,
    graphics_follow_history,
    graphics_chunked,
    iterm2_inline,
    iterm2_measures_unknown_size,
    oversized_body_is_dropped,
    sixel_decoded,
    huge_osc_is_linear,
    dcs_is_consumed,
    image_animation,
    image_z_and_compose,
    erasing_takes_the_picture,
    wrap_and_control,
    deccawm,
    sgr_faint_and_hidden,
    sgr_blink,
    origin_mode,
    osc52_clipboard,
    reflow,
    dch_beyond_row_width,
    reflow_keeps_styled_blank,
    history,
    scroll_anchor,
    selection_follows_history,
    draw_damage,
    redraw_keeps_history_position,
    mouse_modes_and_sgr,
    selection,
    block_selection,
    dropped_path,
    double_and_triple_click,
    hyperlinks,
    osc8_link_id,
    link_table_cap,
    link_uri_clean,
    title_sanitized,
    combining_marks,
    mark_on_blank_row,
    cell_packed_roundtrip,
    frozen_scrollback,
    chrome_config,
    paste_markers,
    truecolor,
    style_contrast,
    ligature_config,
    palette_config,
    session_restore,
    snapshot_restore,
    shortcut_table,
    media_transmission,
    search_scrollback,
    prompt_marks,
    prompt_status,
    copy_mode,
    state_owner_lock,
    title_stack,
    lnm_and_soft_reset,
    tab_stops,
    strike_and_overline,
    screen_scroll,
    rep_and_keypad,
    notifications,
    osc9_progress,
    pixel_mouse,
    mouse_urxvt_and_utf8,
    wheel_notches,
    osc7_cwd,
    desktop_shortcut,
    shortcut_remove_only_own_name,
    window_state,
)
