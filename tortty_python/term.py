"""Terminal state: cell grid, cursor and VT parser.

No GTK in here: it is what makes the parser testable by `--selftest` without a
window (and without a display). `window.TorttyWindow` does the drawing.
"""

import base64
import re
import unicodedata
from array import array
from typing import NamedTuple
from urllib.parse import unquote

from .graphics import Graphics
from .palette import (
    BLINK,
    BOLD,
    DEC_SPECIAL,
    DEF_BG,
    DEF_FG,
    DIM,
    HIDDEN,
    INV,
    ITALIC,
    OVERLINE,
    STRIKE,
    TC,
    UL,
    UL_DOUBLE,
    Theme,
    int_rgb,
    parse_osc_color,
    rgb,
    ul_off,
    ul_on,
    ul_style,
)

# Parser fast path (P20): end of the printable run and the escape -> colour cache.
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_DCS_END = re.compile("[\x07\x1b]")  # BEL or ESC: where a DCS body stops
_DCS_KEEP = 256  # chars of the DCS body kept for debugging (P81)
_ESC_CACHE = {}
_ESC_MAX = 1024

# Layout C: a row is `ch` (one str per cell), `pk` (array('Q') with fg, bg and
# flags packed) and `lk` (array('i') of links, only when the row has a link).


class Row:
    """One row: characters, packed attributes and links.

    `ch` is a list in the live grid and a `str` in the frozen history (`frozen`).
    """

    __slots__ = ("ch", "pk", "lk")

    def __init__(self, ch, pk, lk=None):
        self.ch, self.pk, self.lk = ch, pk, lk


def frozen(row):
    """Freezes the row on its way to the history: chars in a `str`, not a list.

    The history is immutable (read only, by reflow and by the snapshot), so the
    pointer list (8 B per cell) need not exist: a `str` keeps ASCII in one byte
    per cell and CJK in 2-3, instead of one `str` object per cell. A cell with a
    combining mark has more than one code point and would stop matching the
    column, so that row stays a list.
    """
    ch = row.ch
    if type(ch) is str:
        return row
    texto = "".join(ch)
    if len(texto) != len(ch):
        return row
    return Row(texto, row.pk, row.lk)


def row_text(row, a=0, b=None):
    """Text of a slice of the row (frozen or live)."""
    ch = row.ch
    if type(ch) is str:
        return ch[a:b]
    return "".join(ch[a:b])


# 25 bits of fg, 25 of bg, 12 of flags: truecolor white (0x1FFFFFF) fits exactly.
_FG_MASK = (1 << 25) - 1


def _pack(fg, bg, fl):
    """Packed cell: fg in bits 0-24, bg in 25-49, flags in 50-61."""
    return (fl << 50) | (bg << 25) | fg


def _unpack(v):
    return (v & _FG_MASK, (v >> 25) & _FG_MASK, v >> 50)


_BLANK_V = _pack(DEF_FG, DEF_BG, 0)

# Repeating a value into an array slice needs a source of the same typecode: the
# cache keeps the ready array, because the value is constant across the run.
_REP = {}


def _rep(tipo, v, n):
    """`array(kind, [v]) * n`, cached (small cap: few values per run)."""
    chave = (tipo, v, n)
    a = _REP.get(chave)
    if a is None:
        if len(_REP) > 512:
            _REP.clear()
        a = _REP[chave] = array(tipo, [v]) * n
    return a


def row_link(row, x):
    """Hyperlink index at cell `x` (0 = none)."""
    return row.lk[x] if row.lk is not None else 0


def _erase(row, x0, x1, v):
    """Cells `x0`..`x1` blank with value `v` (bce: no link)."""
    n = x1 - x0
    if n <= 0:
        return
    row.ch[x0:x1] = [" "] * n
    row.pk[x0:x1] = _rep("Q", v, n)
    if row.lk is not None:
        row.lk[x0:x1] = _rep("i", 0, n)


def _crop_row(row, cols):
    """Row cropped (or padded with blank) to `cols` cells."""
    lk = None if row.lk is None else row.lk[:cols]
    ch, pk = row.ch[:cols], row.pk[:cols]
    falta = cols - len(ch)
    if falta > 0:
        ch.extend([" "] * falta)
        pk.extend(_rep("Q", _BLANK_V, falta))
        if lk is not None:
            lk.extend(_rep("i", 0, falta))
    return Row(ch, pk, lk)


# CSI parameter cache (P22): (CSI body, final) -> (nums, prefix). Independent of
# the terminal state: only the number parsing is cached.
_CSI_CACHE = {}
_CSI_MAX = 1024

# `OSC 9`/`777`: cap on the stored text — an app notifying in a loop cannot grow
# it without bound (the text is for one toast/badge line).
NOTIF_MAX = 512
# title stack (`CSI 22`/`23 t`): the Rust stops at 16 too
TITLE_STACK_MAX = 16


_SHELL_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-+=@,:")


def shell_quoted(path):
    """Path ready for the shell (P62): as is when safe, single quoted otherwise.

    Same rule as the Rust (`shell_quoted`): only what has a space, `$`, `*`, `'`
    or anything outside the safe set gets quotes — and a single quote inside the
    path becomes `'\''`.
    """
    if path and all(c in _SHELL_SAFE for c in path):
        return path
    return "'" + path.replace("'", "'\\''") + "'"


# -- snapshot of the tab (P57) ----------------------------------------------
# `restore_state content`: what leaves on close and comes back on the next open,
# in ANSI because the reader already exists (the parser). Reopening in a narrow
# window re-wraps through the resize code, so a soft wrap does not become `\n`.
# Out of the snapshot: image, clipboard, notification, title — all that DOES.


def _sgr(fg, bg, fl):
    """SGR that reproduces a cell's pen, starting from the reset (P57)."""
    out = ["\x1b[0"]
    for bit, code in (
        (BOLD, ";1"),
        (DIM, ";2"),
        (ITALIC, ";3"),
        (BLINK, ";5"),
        (INV, ";7"),
        (HIDDEN, ";8"),
        (STRIKE, ";9"),
        (OVERLINE, ";53"),
    ):
        if fl & bit:
            out.append(code)
    if fl & UL:
        estilo = ul_style(fl)
        # a style out of the known range falls back to simple: an invented SGR
        # would paint the wrong cell on the way back
        out.append(";4:%d" % (estilo + 1) if 0 < estilo <= 4 else ";4")
    out.append(_sgr_color(fg, True))
    out.append(_sgr_color(bg, False))
    out.append("m")
    return "".join(out)


def _sgr_color(c, fg):
    """Cell colour in SGR: 39/49, 30-37/90-97, 38;5;n or 38;2;r;g;b."""
    if c is None or c == DEF_FG or c == DEF_BG:
        return ";39" if fg else ";49"
    if c & TC:
        return ";%d;2;%d;%d;%d" % (38 if fg else 48, (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)
    if c < 8:
        return ";%d" % ((30 if fg else 40) + c)
    if c < 16:
        return ";%d" % ((90 if fg else 100) + c - 8)
    return ";%d;5;%d" % (38 if fg else 48, c)


def _padding(row, x):
    """Cell at `x` that draws and carries nothing: the padding on the right."""
    return row.ch[x] == " " and row.pk[x] == _BLANK_V and not row_link(row, x)


def _link_text(uri):
    """URI without control characters: it came from the child and would close the OSC."""
    return "".join(c for c in uri if not (ord(c) < 32 or ord(c) == 127))


def snapshot(term):
    """The whole tab (history and screen) in ANSI: feeding a Term rebuilds it (P57)."""
    alt = term.alt_grid is not None
    if alt:
        # in alt screen the snapshot is of the saved main buffer, and its cursor
        # is unknown while the app holds the screen (no CUP at the end)
        rows = term.scrollback + term.alt_grid
        wrapped = term.sb_wrapped + term.alt_wrapped
        chrome = term.sb_chrome + term.alt_chrome
    else:
        rows = term.scrollback + term.grid
        wrapped = term.sb_wrapped + term.row_wrapped
        chrome = term.sb_chrome + term.row_chrome
    out = []
    pen = None  # no SGR emitted yet: the first cell always emits
    link = 0
    prev_wrapped = False
    first = True
    for row, wrap, deco in zip(rows, wrapped, chrome):
        if deco:
            continue  # the restore marker: on screen, out of the snapshot
        if not first and not prev_wrapped:
            out.append("\r\n")
        first, prev_wrapped = False, wrap
        # a soft-wrapped row is full by definition: the blanks at the end are
        # content, and cutting them would move the wrap
        end = len(row.ch) if wrap else _end_of_content(row)
        pks, lks = row.pk, row.lk
        # text leaves by slice (not by cell): the frozen row is a `str`, so the
        # slice is a cut, and the live row joins in one go
        pend = 0
        for x in range(end):
            i = lks[x] if lks is not None else 0
            v = pks[x]
            if i == link and v == pen:
                continue
            if x > pend:
                out.append(row_text(row, pend, x))
                pend = x
            if i != link:
                if link:
                    out.append("\x1b]8;;\x1b\\")
                link = 0
                uri = term.links[i - 1] if 0 < i <= len(term.links) else None
                if uri:
                    out.append("\x1b]8;;" + _link_text(uri) + "\x1b\\")
                    link = i
            if v != pen:
                fg, bg, fl = _unpack(v)
                out.append(_sgr(fg, bg, fl))
                pen = v
        if end > pend:
            out.append(row_text(row, pend, end))
    if link:
        out.append("\x1b]8;;\x1b\\")
    if pen is not None:
        out.append("\x1b[0m")
    if not alt:
        out.append("\x1b[%d;%dH" % (term.cy + 1, term.cx + 1))
    return "".join(out)


def _end_of_content(row):
    """Index (in cells) after the last one that carries anything (cuts the padding)."""
    for x in range(len(row.ch) - 1, -1, -1):
        if not _padding(row, x):
            return x + 1
    return 0


def _osc_progress(arg):
    """`9;4;state[;%]`: mintty/ConEmu progress (state, %), or None (P65)."""
    parts = arg.split(";")
    if parts[0] != "4" or not 2 <= len(parts) <= 3:
        return None
    if not all(p.isdigit() for p in parts[1:]):
        return None
    pct = min(100, int(parts[2])) if len(parts) == 3 else None
    return (int(parts[1]), pct)


# Whole short CSI in the buffer: body with no intermediates, final in 0x40-0x7e.
# Anything that does not match here (split chunk, intermediate, Unicode digit)
# falls to the slow parser, which remains the owner of the grammar.
_CSI_RE = re.compile(r"\x1b\[([0-9;:?]*)([\x40-\x7e])")


# Title until the app sends OSC 0/2: the value `view` compares to know whether
# the title came from the child.
DEFAULT_TITLE = "TorTTY (Python)"

# Schemes Ctrl+click hands to xdg-open: the URI comes from the child, which does
# not get to choose which desktop handler runs.
LINK_SCHEMES = ("http://", "https://", "file://", "ftp://", "mailto:")


def link_allowed(uri):
    """Only the known schemes go to xdg-open."""
    return uri.lower().startswith(LINK_SCHEMES)


def _link_ident(params):
    """O `id=` dos parâmetros do `OSC 8` (P76); vazio = sem agrupamento."""
    for tok in params.split(":"):
        if tok.startswith("id="):
            return tok[3:]
    return ""


# P73: marcas combinantes colam na célula anterior, então um trecho que as tenha
# não pode ir de uma vez. A resposta é cacheada por string: o mesmo prompt volta
# sempre e o custo de decidir sai do caminho.
_MARK_CACHE = {}
_MARK_MAX = 4096


def _has_mark(text):
    """True se o trecho tem marca combinante (Mn/Me)."""
    hit = _MARK_CACHE.get(text)
    if hit is not None:
        return hit
    hit = any(unicodedata.category(c) in ("Mn", "Me") for c in text)
    if len(_MARK_CACHE) > _MARK_MAX:
        _MARK_CACHE.clear()
    _MARK_CACHE[text] = hit
    return hit


def _vazia(row, i):
    """Célula sem nada pintado: espaço, fundo default, sem atributo e sem link."""
    v = row.pk[i]
    return (
        row.ch[i] == " "
        and (v >> 25) & _FG_MASK == DEF_BG
        and not v >> 50
        and (row.lk is None or not row.lk[i])
    )


class CellAnchor(NamedTuple):
    """Célula em coordenada absoluta: não envelhece quando a tela rola."""

    line: int  # linha absoluta: `Term.scrolled` é o topo do vivo
    col: int
    gen: int  # geração do mapa (ver `Term.abs_gen`)


def _csi_parse(body, final):
    """Corpo do CSI (sem ESC[ e sem final) -> (nums, prefixo, intermediários)."""
    inter = ""
    while body and " " <= body[-1] <= "/":
        inter = body[-1] + inter  # DECRQM (`$p`) e afins: o intermediário importa
        body = body[:-1]
    prefix = ""
    while body and body[0] in "?<=>":
        prefix += body[0]
        body = body[1:]
    parts = []
    for tok in body.split(";") if body else []:
        tok = tok.strip()
        if ":" in tok and final == "m":
            # subparâmetro: guarda a posição (o vazio conta)
            parts.append(tuple(int(v) if v else None for v in tok.split(":")))
        elif tok == "" or tok.startswith((" ", "<", "=", ">")):
            parts.append(None if tok == "" else 0)
        else:
            try:
                parts.append(int(tok))
            except ValueError:
                parts.append(None)
    return tuple(p if p is not None else 0 for p in parts), prefix, inter


def _parse_truecolor(key):
    """`\x1b[38;2;r;g;bm`/`48;2;...` -> (True se fg, cor) ou False."""
    if not (key.startswith("\x1b[38;2;") or key.startswith("\x1b[48;2;")):
        return False
    p = key[2:-1].split(";")
    if len(p) != 5 or p[1] != "2":
        return False
    try:
        r, g, b = int(p[2]), int(p[3]), int(p[4])
    except ValueError:
        return False
    if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
        return False
    return (p[0] == "38", rgb(r, g, b))


class Term:
    """Estado do terminal: grade, cursor, parser VT. Sem GTK aqui."""

    def __init__(self, cols=80, rows=24):
        self.cols, self.rows = cols, rows
        self.grid = [self._blank_row() for _ in range(rows)]
        self.alt_grid = None  # None = buffer principal
        self.scrolled = 0  # linhas que saíram pelo topo (índice absoluto)
        # absolute map generation: reflow (rows join/split) and clearing the
        # history (CSI 3J) invalidate old anchors. The cap trim does NOT: the
        # absolute row stays the same (as in P32).
        self.abs_gen = 0
        # `CSI 3J` wipes the history: whoever is scrolling has to know (B20)
        self.hist_gen = 0
        self.scrollback = []
        self.scrollback_limit = 1000  # teto de linhas do histórico (P34)
        # draw damage (P27): rows with a cell changed since the last draw;
        # dirty_all = the whole grid (scroll, resize, RIS, alt-screen)
        self.dirty, self.dirty_all = set(), True
        # reflow (P3): row_wrapped[i] = "this row continues on the next one"
        # (soft wrap, not '\n'). It is what allows re-wrapping on resize instead
        # of cropping. sb_wrapped is the same, parallel to the scrollback.
        self.row_wrapped = [False] * rows
        # P57: row written by the TERMINAL (the restore marker), not by the
        # child. Decoration is not content: it stays on screen and out of the
        # snapshot. The three are parallel to grid/history, like row_wrapped.
        self.row_chrome = [False] * rows
        self.chrome_feed = False
        # tab stops (P53): `ESC H` sets, `CSI g` clears, `CSI I`/`Z` walk them —
        # the Rust re-seeds them every 8 on resize too
        self.tabstops = [x % 8 == 0 for x in range(cols)]
        # last printed character (`REP`, P56); the ECMA default is a space
        self.last_char = " "
        # keypad in application mode (DECKPAM, P56): state only, the bytes do
        # not change (the Rust decision, see `keypad_app`)
        self.keypad_app = False
        self.sb_wrapped = []
        self.alt_wrapped = None
        self.sb_chrome = []
        self.alt_chrome = None
        self.cx, self.cy = 0, 0
        self.fg, self.bg, self.flags = DEF_FG, DEF_BG, 0
        # LNM (`CSI 20 h`, P58): with it LF also returns to column 0
        self.lnm = False
        self.top, self.bottom = 0, rows - 1  # scroll region
        self.wrap_pending = False
        self.autowrap = True  # DECAWM (?7): desligado para na última coluna
        self.origin = False  # DECOM (?6): cursor relativo à região e preso a ela
        self.cursor_visible = True
        self.app_cursor = False  # DECCKM (?1): setas em modo aplicação
        # DECSCUSR (CSI 6 q): (shape, blink) asked by the app; None = config
        self.app_cursor_style = None
        self.bells = 0  # BEL contados (o host decide visual/audível)
        # app notification (`OSC 9`/`777`, P44): the text and the counter stay
        # here; the window decides toast, badge and urgency
        self.notifs = 0
        self.notif_text = ""
        # progress (`OSC 9;4`, P65): (state, %) or None; the window shows it (in
        # the tab label), on the same poll that delivers `notifs`
        self.progress = None
        # `OSC 52` (the app's clipboard, P64): the decoded text and the counter;
        # the view is who puts it in Gtk.Clipboard (same shape as notifications)
        self.clip_seq = 0
        self.clip_text = ""
        self.clip_sel = "clipboard"  # alvo: clipboard (c, 0-7) ou primary (p, s)
        self.cwd = None  # `OSC 7`: diretório do shell (fallback do /proc)
        self.mouse_mode = 0  # ?1000=1 ?1002=2 ?1003=3 (0 = off)
        self.mouse_sgr = False  # ?1006: coordenadas SGR
        self.mouse_utf8 = False  # ?1005: coordenadas em UTF-8 (P69)
        self.mouse_urxvt = False  # ?1015: CSI b;x;yM em decimal (P69)
        self.mouse_px = False  # ?1016: SGR com coordenadas em pixels
        self.focus_report = False  # ?1004: avisar foco in/out
        self.bracketed_paste = False  # ?2004: colar com marcadores
        self.sync_output = False  # ?2026: transação de desenho aberta
        # kitty keyboard protocol (P5): current flags + stack for push/pop
        # (CSI > flags u / CSI < n u / CSI = flags ; mode u)
        self.kbd_flags = 0
        self.kbd_stack = []
        self.cell_size = (10, 19)  # px por célula (o window ajusta)
        self.charset_dec = False  # ESC ( 0 ativo?
        self.saved = None
        self.child_out = bytearray()  # respostas ao filho (DA, CPR...)
        self.graphics = Graphics()  # protocolo de imagens do kitty (P6)
        self.apc = ""
        self.title = DEFAULT_TITLE
        # `CSI 22;Ps t` pushes the title and `23` gives it back (P52): vim/less/
        # screen come and go without leaving the label stuck on their title
        self.title_stack = []
        self.theme = Theme()  # cores desta aba (P49): config + OSC 4/10-12
        # OSC 8: current hyperlink (index into `links`, 0 = none). The URI is
        # interned, so the cell carries just an int in the fifth field.
        self.link = 0
        self.links = []
        self.link_keys = []  # P76: chave de agrupamento (`id=`) de cada link
        self._link_ids = {}
        self.state = "ground"
        self.csi = ""
        self.osc = ""
        self.apc = ""
        self.dcs = ""  # kept only to the cap; DCS is consumed and ignored (P81)
        # answer to a size query (icat asks; only the basics here)
        self.respond_size = False

    # -- grid --------------------------------------------------------
    def _blank_row(self):
        """Blank row: `cols` spaces and the packed blank value."""
        return Row([" "] * self.cols, array("Q", [_BLANK_V]) * self.cols)

    def _blank_v(self):
        """Packed value of the erased area (bce: inherits the current bg)."""
        return _pack(DEF_FG, self.bg, 0)

    def _bce_row(self):
        """Blank row with the current bg (erased area, bce)."""
        return Row([" "] * self.cols, array("Q", [self._blank_v()]) * self.cols)

    def blank_cell(self):
        """Blank cell with the current bg, as a 5-tuple (cold path)."""
        return (" ", DEF_FG, self.bg, 0, 0)

    def cell(self, y, x):
        """Cell of the grid as a 5-tuple (cold path: allocates)."""
        row = self.grid[y]
        fg, bg, fl = _unpack(row.pk[x])
        return (row.ch[x], fg, bg, fl, row_link(row, x))

    def sb_cell(self, i, x):
        """Cell of the history as a 5-tuple (cold path: allocates)."""
        row = self.scrollback[i]
        fg, bg, fl = _unpack(row.pk[x])
        return (row.ch[x], fg, bg, fl, row_link(row, x))

    def cell_abs(self, i, x):
        """Cell of `scrollback + grid` as a 5-tuple (cold path: allocates)."""
        sb = len(self.scrollback)
        row = self.scrollback[i] if i < sb else self.grid[i - sb]
        fg, bg, fl = _unpack(row.pk[x])
        return (row.ch[x], fg, bg, fl, row_link(row, x))

    def reset(self):
        """RIS (ESC c): clears everything, keeps the size and the history cap."""
        cols, rows, gen = self.cols, self.rows, self.abs_gen + 1
        limit = self.scrollback_limit  # o teto é configuração, não estado do app
        hist = self.hist_gen
        self.__init__(cols, rows)
        self.abs_gen = gen
        self.hist_gen = hist
        self.scrollback_limit = limit

    def resize(self, cols, rows):
        """Resizes: reflows the main buffer.

        Alt-screen has no reflow — whoever is in full screen (mc, vim) redraws
        itself whole on SIGWINCH, and re-wrapping over what it wrote would only
        get in the way.
        """
        if (cols, rows) == (self.cols, self.rows):
            return
        self.touch_all()  # tudo se move com o reflow
        if self.alt_grid is None:
            self._reflow(cols, rows)
        else:
            self._resize_crop(cols, rows)
        # tabs (P53): like the Rust, the resize re-seeds them every 8 instead of
        # preserving the ones the app set — new width, default stops again
        self.tabstops = [x % 8 == 0 for x in range(self.cols)]

    def _resize_crop(self, cols, rows):
        """Alt-screen: crops the screen and reflows the saved main buffer.

        `alt_grid` (the main buffer saved while the app holds the screen) has to
        follow the new size TOO — otherwise, leaving `mc`/`vim` after a resize
        brings the grid back in the old width and the first `EL` overflows
        (`IndexError` in `erase_line`), which kills the pty watch and freezes
        the terminal.
        """
        old_grid, old_cols, old_rows = self.grid, self.cols, self.rows
        old_wrapped, old_cx, old_cy = self.row_wrapped, self.cx, self.cy
        old_chrome = self.row_chrome
        if self.alt_grid is not None:
            self.grid, self.row_wrapped = self.alt_grid, self.alt_wrapped
            self.row_chrome = self.alt_chrome
            self.cols, self.rows = old_cols, old_rows
            self.cx, self.cy = self.saved or (0, 0)
            self._reflow(cols, rows)  # re-quebra o principal salvo
            self.alt_grid, self.alt_wrapped = self.grid, self.row_wrapped
            self.alt_chrome = self.row_chrome
            self.saved = (self.cx, self.cy)
        self.cols, self.rows = cols, rows
        new = []
        for y in range(rows):
            if y < old_rows:
                new.append(_crop_row(old_grid[y], cols))
            else:
                new.append(self._blank_row())
        self.grid = new
        self.row_wrapped = old_wrapped[:rows] + [False] * max(0, rows - len(old_wrapped))
        self.row_chrome = old_chrome[:rows] + [False] * max(0, rows - len(old_chrome))
        self.top, self.bottom = 0, rows - 1
        self.cx = min(old_cx, cols - 1)
        self.cy = min(old_cy, rows - 1)
        self.wrap_pending = False

    def _reflow(self, cols, rows):
        """Joins the logical rows (scrollback + grid), cuts at the new width and
        puts the cursor back on the equivalent cell.

        A logical row = a sequence of screen rows joined by soft wrap. Narrowing
        turns one long row into several; widening turns several back into one.
        What overflows at the top goes to the scrollback, what is missing at the
        bottom is filled — and the cursor stays over the same character.
        """
        old_cols = self.cols
        self.abs_gen += 1  # as linhas absolutas antigas não valem mais
        total = len(self.scrollback) + len(self.grid)
        cur_abs = len(self.scrollback) + self.cy
        cur_off = None
        lines, row_info = [], []
        line_chrome = []
        cur = None
        off = 0
        for i in range(total):
            if i < len(self.scrollback):
                row, wrapped = self.scrollback[i], self.sb_wrapped[i]
                deco = self.sb_chrome[i]
            else:
                j = i - len(self.scrollback)
                row, wrapped = self.grid[j], self.row_wrapped[j]
                deco = self.row_chrome[j]
            if cur is None:
                cur = Row([], array("Q"), None)
                lines.append(cur)
                line_chrome.append(False)
                off = 0
            row_info.append((len(lines) - 1, off))
            # decoration travels with the paragraph (P57): the restore marker
            # cannot come back as content after a re-wrap
            line_chrome[-1] = line_chrome[-1] or deco
            n0 = len(cur.ch)
            cur.ch.extend(row.ch)
            cur.pk.extend(row.pk)
            if row.lk is not None or cur.lk is not None:
                if cur.lk is None:
                    cur.lk = array("i", _rep("i", 0, n0))
                cur.lk.extend(row.lk if row.lk is not None else _rep("i", 0, len(row.ch)))
            off += len(row.ch)
            if not wrapped:
                cur = None
        if cur is not None and not cur.ch:
            lines.pop()
        if cur_abs < len(row_info):
            line_idx, off0 = row_info[cur_abs]
            cur_off = off0 + min(self.cx, old_cols - 1)
        else:
            line_idx, cur_off = None, None

        # Cuts the trailing blank of every logical row. Without it, a 3-char row
        # in a 68-column screen re-wraps into TWO rows (the second only spaces)
        # and the content shows up interleaved with empty rows when narrowing.
        # Only a truly empty cell is cut (space, default bg, no attribute and no
        # link) — a coloured bar/status background, an underlined space and a
        # hyperlink space stay.
        for li, line in enumerate(lines):
            real = len(line.ch)
            while real and _vazia(line, real - 1):
                real -= 1
            if li == line_idx and cur_off is not None and cur_off > real:
                real = cur_off  # não perde a posição do cursor
            del line.ch[real:]
            del line.pk[real:]
            if line.lk is not None:
                del line.lk[real:]

        new_rows, new_wrap, new_chrome = [], [], []
        cur_new = None
        for li, line in enumerate(lines):
            nch = max(1, (len(line.ch) + cols - 1) // cols)
            for ci in range(nch):
                k = ci * cols
                ch = line.ch[k : k + cols]
                pk = line.pk[k : k + cols]
                lk = None if line.lk is None else line.lk[k : k + cols]
                falta = cols - len(ch)
                if falta:
                    ch.extend([" "] * falta)
                    pk.extend(_rep("Q", _BLANK_V, falta))
                    if lk is not None:
                        lk.extend(_rep("i", 0, falta))
                new_rows.append(Row(ch, pk, lk))
                new_wrap.append(ci < nch - 1)
                new_chrome.append(line_chrome[li])
                # only the first chunk holding the cursor wins (without this the
                # last chunk of the row overwrote it and the cursor jumped)
                if (
                    li == line_idx
                    and cur_off is not None
                    and cur_new is None
                    and (cur_off < (ci + 1) * cols or ci == nch - 1)
                ):
                    cur_new = (
                        len(new_rows) - 1,
                        max(0, min(cols - 1, cur_off - ci * cols)),
                    )
        # what comes AFTER the cursor is blank area: no point pushing an empty
        # row into the scrollback just because the screen got wider
        if cur_new is not None:
            while len(new_rows) - 1 > cur_new[0]:
                last = new_rows[-1]
                if any(not _vazia(last, i) for i in range(len(last.ch))):
                    break
                new_rows.pop()
                new_wrap.pop()
                new_chrome.pop()

        split = max(0, len(new_rows) - rows)
        self.scrollback = [frozen(r) for r in new_rows[:split]]
        self.sb_wrapped = new_wrap[:split]
        self.sb_chrome = new_chrome[:split]
        self._trim_scrollback()
        self.grid = new_rows[split:]
        self.row_wrapped = new_wrap[split:]
        self.row_chrome = new_chrome[split:]
        while len(self.grid) < rows:
            self.grid.append(Row([" "] * cols, array("Q", [_BLANK_V]) * cols))
            self.row_wrapped.append(False)
            self.row_chrome.append(False)

        # Image placements live in SCREEN ROWS, and the reflow just changed how
        # many rows exist above the grid: what fell out of the history became
        # unreachable (not even with the wheel) and would never be drawn again —
        # better to drop it than to keep junk. The ones still in range stay where
        # they are (an image does not follow reflow row by row, as in kitty).
        self.graphics.drop_above(-len(self.scrollback))

        self.cols, self.rows = cols, rows
        self.top, self.bottom = 0, rows - 1
        self.wrap_pending = False
        if cur_new is not None:
            self.cy = max(0, min(rows - 1, cur_new[0] - split))
            self.cx = max(0, min(cols - 1, cur_new[1]))
        else:
            self.cx = min(self.cx, cols - 1)
            self.cy = min(self.cy, rows - 1)

    def set_scrollback(self, n):
        """New history cap (P34): trims the excess right away."""
        n = max(0, int(n))
        if n == self.scrollback_limit:
            return False
        self.scrollback_limit = n
        self._trim_scrollback()
        self.graphics.drop_above(-len(self.scrollback))
        return True

    def touch(self, y):
        """Marks the row as changed: the host only has to draw that one."""
        self.dirty.add(y)

    def touch_all(self):
        """The whole grid changed (scroll, resize, RIS, buffer switch)."""
        self.dirty_all = True

    def take_damage(self):
        """Rows changed since the last draw; None = the whole grid."""
        if self.dirty_all:
            self.dirty.clear()
            self.dirty_all = False
            return None
        linhas, self.dirty = self.dirty, set()
        return linhas

    def _trim_scrollback(self):
        """Cuts the history at the cap (called when the cap changes and on scroll)."""
        n = self.scrollback_limit
        if len(self.scrollback) > n:
            del self.scrollback[: len(self.scrollback) - n]
            del self.sb_wrapped[: max(0, len(self.sb_wrapped) - n)]
            del self.sb_chrome[: max(0, len(self.sb_chrome) - n)]

    def scroll_up(self):
        self.touch_all()  # a tela desliza: toda linha muda de conteúdo
        self.scrolled += 1
        # full-screen scroll: the row leaving at the top goes to the history, so
        # the image that was on it keeps existing (on a negative row) and comes
        # back when the view scrolls up the scrollback
        self.graphics.scroll(
            self.top, self.bottom, -(self.scrollback_limit + 1) if self.top == 0 else None
        )
        if self.alt_grid is not None:
            self.grid.pop(self.top)
            self.grid.insert(self.bottom, self._blank_row())
            self.row_wrapped.pop(self.top)
            self.row_wrapped.insert(self.bottom, False)
            self.row_chrome.pop(self.top)
            self.row_chrome.insert(self.bottom, False)
        else:
            if self.top == 0 and self.bottom == self.rows - 1:
                self.scrollback.append(frozen(self.grid.pop(0)))
                self.sb_wrapped.append(self.row_wrapped.pop(0))
                self.sb_chrome.append(self.row_chrome.pop(0))
                if len(self.scrollback) > self.scrollback_limit:
                    self.scrollback.pop(0)
                    self.sb_wrapped.pop(0)
                    self.sb_chrome.pop(0)
                    # what was pinned to that row is gone for good
                    self.graphics.drop_above(-len(self.scrollback))
                self.grid.append(self._blank_row())
                self.row_wrapped.append(False)
                self.row_chrome.append(False)
            else:
                self.grid.pop(self.top)
                self.grid.insert(self.bottom, self._blank_row())
                self.row_wrapped.pop(self.top)
                self.row_wrapped.insert(self.bottom, False)
                self.row_chrome.pop(self.top)
                self.row_chrome.insert(self.bottom, False)

    def newline(self):
        if self.cy == self.bottom:
            self.scroll_up()
        else:
            self.cy = min(self.cy + 1, self.rows - 1)

    def reverse_index(self):
        """`ESC M` (RI): at the top of the region, scrolls the region one row down."""
        if self.cy == self.top:
            self.scroll_down(1)
        else:
            self.cy = max(0, self.cy - 1)

    def scroll_down(self, n=1):
        """`CSI T` (SD) and `ESC M` at the top: the region goes down, the top gains a row."""
        self.touch_all()
        for _ in range(max(1, n)):
            self.graphics.scroll(self.top, self.bottom, None)
            self.grid.pop(self.bottom)
            self.grid.insert(self.top, self._blank_row())
            self.row_wrapped.pop(self.bottom)
            self.row_wrapped.insert(self.top, False)
            self.row_chrome.pop(self.bottom)
            self.row_chrome.insert(self.top, False)

    def link_of(self, i):
        """Hyperlink URI by the cell's slot index (5th field), or None."""
        if not i or i > len(self.links):
            return None
        return self.links[i - 1]

    def link_key(self, i):
        """Link grouping key by the index (5th field): `id=` or URI (P76)."""
        if not i or i > len(self.link_keys):
            return None
        return self.link_keys[i - 1]

    def _link_id(self, uri, ident=""):
        """Index of the link in the table: same URI and same `id=` reuse the same int."""
        if not uri:
            return 0
        i = self._link_ids.get((uri, ident))
        if i is None:
            self.links.append(uri)
            # with no `id=` the grouping is the URI itself: two cells of the same
            # URI are still a single link
            self.link_keys.append(ident or uri)
            i = len(self.links)
            self._link_ids[(uri, ident)] = i
        return i

    def put(self, ch):
        # Control comes BEFORE the pending wrap: a `\r\n` after a row that filled
        # the width advanced TWO rows (the pending wrap + the LF), and an app that
        # fills the whole row (pi, Ink) fell into doubled layout and a screen
        # scrolling without stopping (P15).
        if ch == "\r":
            self.cx, self.wrap_pending = 0, False
            return
        if ch == "\n":
            self.wrap_pending = False
            if self.lnm:  # P58: LF também volta a coluna para o zero
                self.cx = 0
            self.newline()
            return
        if ch == "\b":
            self.cx, self.wrap_pending = max(0, self.cx - 1), False
            return
        if ch == "\t":
            self.wrap_pending = False
            self.forward_tab(1)
            return
        if ch >= "\u0300" and unicodedata.category(ch) in ("Mn", "Me"):
            # P73: a combining mark (accent, VS16) glues to the previous cell
            # instead of taking another one — the row walked one column too far
            col = self.cols - 1 if self.wrap_pending else self.cx - 1
            if col >= 0:
                row = self.grid[self.cy]
                row.ch[col] = row.ch[col] + ch
                self.dirty.add(self.cy)
                return
        if self.wrap_pending:
            # the row that filled up continues on the next one (soft wrap): it is
            # what reflow uses to join them again when widening
            self.row_wrapped[self.cy] = True
            self.cx = 0
            self.newline()
            self.wrap_pending = False
        if self.charset_dec:
            ch = DEC_SPECIAL.get(ch, ch)
        self.last_char = ch  # `REP` repete o último impresso (P56)
        x = self.cx
        row = self.grid[self.cy]
        row.ch[x] = ch
        row.pk[x] = _pack(self.fg, self.bg, self.flags)
        if self.link or row.lk is not None:
            if row.lk is None:
                row.lk = array("i", _rep("i", 0, self.cols))
            row.lk[x] = self.link
        if self.chrome_feed:
            self.row_chrome[self.cy] = True
        self.dirty.add(self.cy)
        if self.cx == self.cols - 1:
            self.wrap_pending = self.autowrap
        else:
            self.cx += 1

    # -- commands ----------------------------------------------------
    def forward_tab(self, n=1):
        """`HT`/`CSI I`: walks `n` tab stops to the right (P53)."""
        for _ in range(max(1, n)):
            x = self.cx + 1
            while x < self.cols and not self.tabstops[x]:
                x += 1
            self.cx = min(self.cols - 1, x)
        self.wrap_pending = False

    def backward_tab(self, n=1):
        """`CSI Z` (CBT): walks `n` stops to the left (P53)."""
        for _ in range(max(1, n)):
            x = self.cx
            while x > 0:
                x -= 1
                if self.tabstops[x]:
                    break
            self.cx = x
        self.wrap_pending = False

    def cursor_to(self, r, c):
        if self.origin and self.top <= self.bottom:
            # DECOM (P68): the absolute row is held inside the scroll region
            self.cy = max(self.top, min(self.bottom, r))
        else:
            self.cy = max(0, min(self.rows - 1, r))
        self.cx = max(0, min(self.cols - 1, c))
        self.wrap_pending = False

    def row_abs(self, r):
        """Relative-addressing row (DECOM) turned into an absolute one."""
        return r + self.top if self.origin else r

    def erase_display(self, n):
        self.touch_all()
        v = self._blank_v()
        if n == 2 or n == 3:
            self.graphics.erase(0, self.rows, 0, self.cols)  # P86
            for y in range(self.rows):
                self.grid[y] = self._bce_row()
            # `ED 3` in alt screen is the alternate buffer's business: it has no
            # history and no say about what it covers — clearing took the main
            # history and its images with it (P79, parity with B63)
            if n == 3 and self.alt_grid is None:
                self.scrollback.clear()
                self.sb_wrapped.clear()
                self.sb_chrome.clear()
                self.graphics.clear()
                self.links.clear()  # os índices das células deixam de valer
                self.link_keys.clear()
                self._link_ids.clear()
                self.link = 0
                self.abs_gen += 1  # o histórico sumiu: âncora antiga morreu
                self.hist_gen += 1
            self.cursor_to(0, 0)
        elif n == 1:
            self.graphics.erase(0, self.cy, 0, self.cols)  # P86
            self.graphics.erase(self.cy, self.cy + 1, 0, self.cx + 1)
            _erase(self.grid[self.cy], 0, self.cx + 1, v)
            for y in range(self.cy):
                self.grid[y] = self._bce_row()
        else:  # 0
            self.graphics.erase(self.cy + 1, self.rows, 0, self.cols)  # P86
            self.graphics.erase(self.cy, self.cy + 1, self.cx, self.cols)
            _erase(self.grid[self.cy], self.cx, self.cols, v)
            for y in range(self.cy + 1, self.rows):
                self.grid[y] = self._bce_row()

    def erase_line(self, n):
        self.dirty.add(self.cy)
        row = self.grid[self.cy]
        if n == 2:
            self.graphics.erase(self.cy, self.cy + 1, 0, self.cols)  # P86
            self.grid[self.cy] = self._bce_row()
        elif n == 1:
            self.graphics.erase(self.cy, self.cy + 1, 0, self.cx + 1)
            _erase(row, 0, self.cx + 1, self._blank_v())
        else:
            self.graphics.erase(self.cy, self.cy + 1, self.cx, self.cols)
            _erase(row, self.cx, self.cols, self._blank_v())

    def insert_lines(self, n):
        self.touch_all()
        for _ in range(n):
            self.grid.pop(self.bottom)
            self.grid.insert(self.cy, self._bce_row())
            self.row_wrapped.pop(self.bottom)
            self.row_wrapped.insert(self.cy, False)
            self.row_chrome.pop(self.bottom)
            self.row_chrome.insert(self.cy, False)

    def delete_lines(self, n):
        self.touch_all()
        for _ in range(n):
            self.grid.pop(self.cy)
            self.grid.insert(self.bottom, self._bce_row())
            self.row_wrapped.pop(self.cy)
            self.row_wrapped.insert(self.bottom, False)
            self.row_chrome.pop(self.cy)
            self.row_chrome.insert(self.bottom, False)

    def sgr(self, params):
        # subparâmetros com ':' (38:2::r:g:b) chegam como tupla: acha a forma
        # canônica com ';' antes de interpretar (só aloca `flat` se houver).
        # `4:n` fica tupla de propósito: o estilo do sublinhado não cabe num
        # int sem se confundir com o parâmetro seguinte (`4:3` != `4;3`).
        flat = params
        for p in params:
            if isinstance(p, tuple):
                flat = []
                for q in params:
                    if isinstance(q, tuple) and q and q[0] == 4:
                        flat.append(q)
                    elif isinstance(q, tuple):
                        flat.extend(self._sgr_subparams(q))
                    else:
                        flat.append(q)
                break
        it = iter(flat)
        for p in it:
            if isinstance(p, tuple):
                if p[0] == 4:
                    self._underline(p[1] if len(p) > 1 else None)
                continue
            if p == 0:
                self.fg, self.bg, self.flags = DEF_FG, DEF_BG, 0
            elif p == 1:
                self.flags |= BOLD
            elif p == 2:
                self.flags |= DIM  # faint: cor a meio caminho do fundo (P64)
            elif p == 3:
                self.flags |= ITALIC
            elif p == 4:
                self.flags = ul_on(self.flags)
            elif p in (5, 6):
                # 6 (rápido) compartilha o bit e o ritmo do 5, como o xterm
                self.flags |= BLINK
            elif p == 7:
                self.flags |= INV
            elif p == 8:
                self.flags |= HIDDEN  # o glifo sai; fundo e decoração ficam (P64)
            elif p == 9:
                self.flags |= STRIKE
            elif p == 29:
                self.flags &= ~STRIKE
            elif p == 53:
                self.flags |= OVERLINE
            elif p == 55:
                self.flags &= ~OVERLINE
            elif p == 21:
                # ECMA-48: 21 é sublinhado duplo (e não "desliga o negrito")
                self.flags = ul_on(self.flags, UL_DOUBLE)
            elif p == 22:
                # intensidade normal (ECMA-48): nem negrito nem faint
                self.flags &= ~(BOLD | DIM)
            elif p == 23:
                self.flags &= ~ITALIC
            elif p == 24:
                self.flags = ul_off(self.flags)
            elif p == 25:
                self.flags &= ~BLINK  # SGR 25: volta a não piscar
            elif p == 27:
                self.flags &= ~INV
            elif 30 <= p <= 37:
                self.fg = p - 30
            elif p == 39:
                self.fg = DEF_FG
            elif 40 <= p <= 47:
                self.bg = p - 40
            elif p == 49:
                self.bg = DEF_BG
            elif 90 <= p <= 97:
                self.fg = p - 90 + 8
            elif 100 <= p <= 107:
                self.bg = p - 100 + 8
            elif p in (38, 48):
                try:
                    mode = next(it)
                except StopIteration:
                    break
                if mode == 5:
                    try:
                        c = next(it)
                    except StopIteration:
                        break
                    if 0 <= c <= 255:
                        if p == 38:
                            self.fg = c
                        else:
                            self.bg = c
                elif mode == 2:
                    vals = []
                    for _ in range(3):
                        try:
                            vals.append(next(it))
                        except StopIteration:
                            break
                    # truecolor de verdade (P4): o RGB fica na célula, sem
                    # passar por tabela de cores alocadas. Antes disto o
                    # `38;2;r;g;b` era aproximado pro vizinho mais próximo da
                    # paleta 256 — vim com termguicolors, bat e gradiente em
                    # texto caíam todos em faixas chapadas.
                    if len(vals) == 3:
                        c = rgb(
                            min(255, max(0, vals[0])),
                            min(255, max(0, vals[1])),
                            min(255, max(0, vals[2])),
                        )
                        if p == 38:
                            self.fg = c
                        else:
                            self.bg = c

    def _underline(self, style):
        """SGR 4:n: 0 desliga, 1 simples, 2 duplo, 3 curvo, 4 pontilhado, 5 tracejado."""
        if style is None:
            self.flags = ul_on(self.flags)
        elif style == 0:
            self.flags = ul_off(self.flags)
        elif 1 <= style <= 5:
            self.flags = ul_on(self.flags, style - 1)

    @staticmethod
    def _sgr_subparams(sub):
        """`38:2::r:g:b` (SGR com ':') -> forma canônica com ';'.

        O campo vazio é o "espaço de cor" omitido (`38:2::1:2:3` ==
        `38:2:0:1:2:3` == `38;2;1;2;3`), então o descarte só vale quando a
        posição é de espaço de cor — filtrar todos os vazios mudaria o
        significado de `48:5::196`.
        """
        vals = list(sub)
        if len(vals) >= 5 and vals[1] == 2:
            last3 = [0 if v is None else v for v in vals[-3:]]
            return [vals[0], 2] + last3
        return [0 if v is None else v for v in vals]

    def soft_reset(self):
        """DECSTR (P59): volta atributos e modos ao padrão, sem limpar a tela.

        A lista é a do Rust (`soft_reset`): o que não existe aqui (cor de
        sublinhado) não tem o que resetar, e o LNM e o
        cursor pedido por `CSI 6 q` ficam de fora — o Rust também os deixa.
        """
        self.fg, self.bg, self.flags = DEF_FG, DEF_BG, 0
        self.cursor_visible = True
        self.app_cursor = False
        self.keypad_app = False
        self.autowrap = True
        self.origin = False
        self.top, self.bottom = 0, self.rows - 1
        self.wrap_pending = False

    def set_mode(self, params, private, on):
        for p in params:
            if not private and p == 20:
                self.lnm = on  # P58
            elif private and p == 25:
                self.cursor_visible = on
            elif private and p == 1:
                # DECCKM: com o modo ligado as setas viram \EOA..\EOD
                # (é o que o terminfo de xterm chama de "aplicação"; mc,
                # vim e less ligam isso ao entrar em tela cheia)
                self.app_cursor = on
            elif private and p == 6:
                # DECOM (P68): endereçamento relativo à região; ligar ou
                # desligar manda o cursor para casa (o topo da região)
                self.origin = on
                self.cursor_to(0, 0)
            elif private and p == 7:
                # DECAWM (P64): desligado o cursor para na última coluna — o
                # caractere seguinte sobrescreve, sem quebra mole
                self.autowrap = on
                if not on:
                    self.wrap_pending = False
            elif p in (47, 1047, 1049):
                # a troca de buffer muda o mapa absoluto: âncora velha morre
                self.touch_all()  # o buffer inteiro troca
                if on and self.alt_grid is None:
                    self.abs_gen += 1
                    self.graphics.enter_alt()  # P86: o alt tem as suas imagens
                    self.alt_grid = self.grid
                    self.alt_wrapped = self.row_wrapped
                    self.alt_chrome = self.row_chrome
                    self.grid = [self._blank_row() for _ in range(self.rows)]
                    self.row_wrapped = [False] * self.rows
                    self.row_chrome = [False] * self.rows
                    self.saved = (self.cx, self.cy)
                    self.cursor_to(0, 0)
                    # P79: `?1049` salva o cursor e troca para o buffer
                    # ALTERNATIVO (é ele que nasce limpo); o histórico do
                    # buffer principal volta na saída, como em qualquer
                    # terminal — limpar aqui apagava para sempre a leitura de
                    # quem estava lendo antes de abrir o `mc`/`vim`.
                elif not on and self.alt_grid is not None:
                    self.abs_gen += 1
                    self.graphics.leave_alt()  # P86: as do principal voltam
                    self.grid = self.alt_grid
                    self.alt_grid = None
                    if len(self.alt_wrapped) == self.rows:
                        self.row_wrapped = self.alt_wrapped
                    if len(self.alt_chrome) == self.rows:
                        self.row_chrome = self.alt_chrome
                    self.alt_wrapped = None
                    self.alt_chrome = None
                    if self.grid and len(self.grid[0].ch) != self.cols:
                        # tamanho mudou com a tela cheia ligada: re-quebra
                        # em vez de deixar linha curta na grade
                        self._reflow(self.cols, self.rows)
                    if self.saved:
                        self.cx, self.cy = self.saved
                    self.top, self.bottom = 0, self.rows - 1
            elif p == 1048:
                if on:
                    self.saved = (self.cx, self.cy)
                elif self.saved:
                    self.cx, self.cy = self.saved
            elif private and p in (1000, 1002, 1003):
                # modos de mouse: 1 = só cliques, 2 = clique + arrasto,
                # 3 = qualquer movimento. Desligar qualquer um desliga o
                # report (é o que o xterm faz).
                self.mouse_mode = {1000: 1, 1002: 2, 1003: 3}[p] if on else 0
            elif private and p == 1006:
                self.mouse_sgr = on  # coordenadas SGR (>223 e release)
            elif private and p == 1016:
                # SGR com pixels: não existe protocolo antigo de pixel, então
                # quem liga isto já força a forma SGR (P46)
                self.mouse_px = on
            elif private and p == 1004:
                self.focus_report = on  # CSI I / CSI O no foco
            elif private and p in (1005, 1015):
                # UTF-8 (1005) e urxvt (1015): P69
                if p == 1005:
                    self.mouse_utf8 = on
                else:
                    self.mouse_urxvt = on
            elif private and p == 2004:
                # bracketed paste: o app pede pra saber que o texto colado não
                # foi digitado. Sem isso, colar 3 linhas no shell executa 3.
                self.bracketed_paste = on
            elif private and p == 2026:
                # synchronized output: o app abre uma transação, redesenha
                # várias vezes e fecha. Quem desenha segura o frame até o
                # fecho — senão a tela mostra o meio de cada repaint.
                self.sync_output = on

    def mode_state(self, p, private):
        """DECRQM: 1 = ligado, 2 = desligado, 0 = modo desconhecido."""
        if private:
            if p == 1:
                return 1 if self.app_cursor else 2
            if p == 6:
                return 1 if self.origin else 2
            if p == 7:
                return 1 if self.autowrap else 2
            if p == 25:
                return 1 if self.cursor_visible else 2
            if p in (47, 1047, 1049):
                return 1 if self.alt_grid is not None else 2
            if p in (1000, 1002, 1003):
                return 1 if self.mouse_mode == {1000: 1, 1002: 2, 1003: 3}[p] else 2
            if p == 1006:
                return 1 if self.mouse_sgr else 2
            if p == 1005:
                return 1 if self.mouse_utf8 else 2
            if p == 1015:
                return 1 if self.mouse_urxvt else 2
            if p == 1016:
                return 1 if self.mouse_px else 2
            if p == 1004:
                return 1 if self.focus_report else 2
            if p == 2004:
                return 1 if self.bracketed_paste else 2
            if p == 2026:
                return 1 if self.sync_output else 2
            if p == 66:
                return 1 if self.keypad_app else 2
            return 0
        if p == 20:  # LNM (P58); os outros modos ANSI (IRM...) não existem
            return 1 if self.lnm else 2
        return 0

    def csi_dispatch(self, final, params, prefix="", inter=""):
        def get(i, d):
            return params[i] if i < len(params) and params[i] is not None else d

        private = prefix == "?"

        if final == "m":
            self.sgr(params or [0])
        elif final in "ABCDEFG":
            k = get(0, 1) or 1
            if final in "AE":
                self.cursor_to(self.cy - k if final == "A" else self.cy + k, self.cx)
            elif final in "CD":
                self.cursor_to(self.cy, self.cx + k if final == "C" else self.cx - k)
            elif final == "B":
                self.cursor_to(self.cy + k, self.cx)
            elif final == "F":
                self.cursor_to(self.cy - k, 0)
            elif final == "G":
                self.cursor_to(self.cy, k - 1)
        elif final in "Hf":
            self.cursor_to(self.row_abs(get(0, 1) - 1), get(1, 1) - 1)
        elif final == "d":
            self.cursor_to(self.row_abs(get(0, 1) - 1), self.cx)
        elif final == "J":
            self.erase_display(get(0, 0))
        elif final == "K":
            self.erase_line(get(0, 0))
        elif final == "L":
            self.insert_lines(get(0, 1) or 1)
        elif final == "M":
            self.delete_lines(get(0, 1) or 1)
        elif final == "@":
            k = min(get(0, 1) or 1, self.cols - self.cx)  # além da borda não entra
            self.dirty.add(self.cy)
            row = self.grid[self.cy]
            row.ch[self.cx : self.cx] = [" "] * k
            row.pk[self.cx : self.cx] = _rep("Q", self._blank_v(), k)
            if row.lk is not None:
                row.lk[self.cx : self.cx] = _rep("i", 0, k)
            del row.ch[self.cols :]
            del row.pk[self.cols :]
            if row.lk is not None:
                del row.lk[self.cols :]
        elif final == "P":
            # sem o limite, del apagava menos do que k e o extend devolvia k
            # células: a linha crescia além de self.cols e o histórico ficava
            # com linha de largura errada (a re-quebra supõe len(row) == cols)
            k = min(get(0, 1) or 1, self.cols - self.cx)
            self.dirty.add(self.cy)
            row = self.grid[self.cy]
            del row.ch[self.cx : self.cx + k]
            del row.pk[self.cx : self.cx + k]
            if row.lk is not None:
                del row.lk[self.cx : self.cx + k]
            row.ch.extend([" "] * k)
            row.pk.extend(_rep("Q", self._blank_v(), k))
            if row.lk is not None:
                row.lk.extend(_rep("i", 0, k))
        elif final == "X":
            hi = min(self.cols, self.cx + (get(0, 1) or 1))
            self.dirty.add(self.cy)
            self.graphics.erase(self.cy, self.cy + 1, self.cx, hi)  # P86
            _erase(self.grid[self.cy], self.cx, hi, self._blank_v())
        elif final == "r":
            t, b = get(0, 1) - 1, get(1, self.rows) - 1
            if 0 <= t < b < self.rows:
                self.top, self.bottom = t, b
                self.cursor_to(0, 0)
        elif final in "ST":
            # SU/SD (P55): rola a tela sem mexer no cursor. Não desce para o
            # histórico ao subir: é rolagem de conteúdo, não de newline.
            n = get(0, 1) or 1
            if final == "S":
                for _ in range(n):
                    self.scroll_up()
            else:
                self.scroll_down(n)
        elif final == "I":
            self.forward_tab(get(0, 1) or 1)  # CHT (P53)
        elif final == "Z":
            self.backward_tab(get(0, 1) or 1)  # CBT (P53)
        elif final == "b":
            # REP (P56): repete o último caractere gráfico impresso
            for _ in range(get(0, 1) or 1):
                self.put(self.last_char)
        elif final == "g":
            # TBC (P53): 0 tira a parada desta coluna, 3 tira todas
            n = get(0, 0)
            if n == 0:
                self.tabstops[self.cx] = False
            elif n == 3:
                self.tabstops = [False] * self.cols
        elif final == "s":
            self.saved = (self.cx, self.cy)
        elif final == "u" and prefix:
            self._kbd_protocol(params, prefix)
        elif final == "u":
            if self.saved:
                self.cx, self.cy = self.saved
        elif final in "hl":
            self.set_mode(params or [0], private, final == "h")
        elif final == "c" and prefix == ">":
            # DA2: identificação secundária — a resposta TEM de começar com
            # '>'. Responder no formato do DA1 (o que acontecia antes) deixa o
            # app sem saber com quem está falando.
            self.child_out += b"\x1b[>1;100;0c"
        elif final == "c" and not prefix and params in ((), (0,)):
            self.child_out += b"\x1b[?62c"  # DA1: VT102
        elif final == "p" and inter == "!" and (not params or params == (0,)):
            # DECSTR (P59): soft reset — não toca na grade nem no histórico
            self.soft_reset()
        elif final == "p" and inter == "$":
            # DECRQM: o app pergunta se um modo existe/suporta
            ps = get(0, 0)
            st = self.mode_state(ps, private)
            self.child_out += f"\x1b[{'?' if private else ''}{ps};{st}$y".encode()
        elif final == "t" and params:
            # 14/15 = area in pixels, 16 = cell in pixels, 18/19 = area in chars.
            # TUI apps (pi, neovim) and `kitten icat` ask and wait; 14 missing
            # made icat give up on images (P82).
            cw, ch = self.cell_size
            if params[0] == 14:
                self.child_out += f"\x1b[4;{self.rows * ch};{self.cols * cw}t".encode()
            elif params[0] == 15:
                self.child_out += f"\x1b[5;{self.rows * ch};{self.cols * cw}t".encode()
            elif params[0] == 16:
                self.child_out += f"\x1b[6;{ch};{cw}t".encode()
            elif params[0] == 18:
                self.child_out += f"\x1b[8;{self.rows};{self.cols}t".encode()
            elif params[0] == 19:
                self.child_out += f"\x1b[9;{self.rows};{self.cols}t".encode()
            elif params[0] in (22, 23) and get(1, 0) <= 2:
                # 22 salva, 23 devolve (xterm); Ps 1/2 são os ícones, que não
                # existem aqui — o título de janela é o mesmo
                if params[0] == 22:
                    if len(self.title_stack) < TITLE_STACK_MAX:
                        self.title_stack.append(self.title)
                elif self.title_stack:
                    # pilha vazia não inventa título: deixa como está
                    self.title = self.title_stack.pop()
        elif final == "q" and inter == " ":
            # DECSCUSR: 1..6 = forma+pisca; 0 (ou fora da faixa) volta à config
            ps = get(0, 0)
            if 1 <= ps <= 6:
                forma = ("block", "underline", "beam")[(ps - 1) // 2]
                self.app_cursor_style = (forma, ps % 2 == 1)
            else:
                self.app_cursor_style = None
        elif final == "n" and params == (6,):
            # DSR: informa posição do cursor
            self.child_out += f"\x1b[{self.cy + 1};{self.cx + 1}R".encode()
        # resto: ignorado silenciosamente (não implementado)

    # -- parser -------------------------------------------------------
    def _sgr_fast(self, text, i):
        """`CSI 38;2;r;g;b m` aplicado direto; devolve o índice seguinte ou None."""
        end = text.find("m", i + 2)
        if end < 0 or end - i > 24:
            return None
        key = text[i : end + 1]
        v = _ESC_CACHE.get(key)
        if v is None:
            v = _parse_truecolor(key)
            if len(_ESC_CACHE) > _ESC_MAX:
                _ESC_CACHE.clear()
            _ESC_CACHE[key] = v
        if v is False:
            return None
        is_fg, color = v
        if is_fg:
            self.fg = color
        else:
            self.bg = color
        return end + 1

    def _put_cells(self, row, x, text):
        """Escreve um trecho na linha a partir da coluna `x` com a caneta corrente.

        O atributo é constante no trecho: uma fatia de array comprado pronto
        (`_rep`) sai no nível do C em vez de célula a célula em Python.
        """
        n = len(text)
        fim = x + n
        row.ch[x:fim] = text
        row.pk[x:fim] = _rep("Q", _pack(self.fg, self.bg, self.flags), n)
        # o `or` importa: com link velho na linha, a escrita tem de zerar a célula
        if self.link or row.lk is not None:
            if row.lk is None:
                row.lk = array("i", _rep("i", 0, self.cols))
            row.lk[x:fim] = _rep("i", self.link, n)

    def _put_run(self, run):
        """Trecho imprimível de uma vez, com a mesma quebra mole do put."""
        if not run.isascii() and _has_mark(run):
            # P73: com marca combinante o destino é a célula anterior, então o
            # trecho vai um a um (raro, e o cache evita reler a mesma string)
            for ch in run:
                self.put(ch)
            return
        self.last_char = run[-1]  # `REP` repete o último impresso (P56)
        i, n = 0, len(run)
        while i < n:
            if self.wrap_pending:
                self.row_wrapped[self.cy] = True
                self.cx = 0
                self.newline()
                self.wrap_pending = False
            cx = self.cx
            avail = self.cols - cx
            k = n - i
            row = self.grid[self.cy]
            if self.chrome_feed:  # P57: decoração, não conteúdo
                self.row_chrome[self.cy] = True
            self.dirty.add(self.cy)
            if k >= avail:  # enche até a última coluna: quebra mole
                self._put_cells(row, cx, run[i : i + avail])
                self.cx = self.cols - 1
                self.wrap_pending = self.autowrap
                i += avail
            else:
                self._put_cells(row, cx, run[i:])
                self.cx = cx + k
                i = n

    def _csi_fast(self, text, i):
        """CSI completo no buffer, resolvido pelo cache de parâmetros."""
        m = _CSI_RE.match(text, i)
        if m is None:
            return None
        key = (m.group(1), m.group(2))
        parsed = _CSI_CACHE.get(key)
        if parsed is None:
            parsed = _csi_parse(key[0], key[1])
            if len(_CSI_CACHE) > _CSI_MAX:
                _CSI_CACHE.clear()
            _CSI_CACHE[key] = parsed
        self.csi_dispatch(key[1], parsed[0], parsed[1], parsed[2])
        return m.end()

    def feed(self, text):
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            st = self.state
            if st == "ground":
                if ch == "\x1b":
                    # P20/P22: SGR truecolor aplica direto; qualquer outro CSI
                    # curto resolve pelo cache; o resto cai no parser de sempre
                    j = self._sgr_fast(text, i)
                    if j is None:
                        j = self._csi_fast(text, i)
                    if j is not None:
                        i = j
                        continue
                    self.state = "esc"
                elif ch in "\x07":
                    self.bells += 1  # BEL: o host decide visual/audível (P34)
                elif ch < " " or ch == "\x7f":
                    if ch in "\n\r\b\t":
                        self.put(ch)
                    # resto dos C0 ignorado
                elif not self.charset_dec:
                    # P20: texto imprimível de uma vez (slice na linha)
                    m = _CTRL.search(text, i)
                    j = m.start() if m else n
                    self._put_run(text[i:j])
                    i = j
                    continue
                else:
                    self.put(ch)
            elif st == "esc":
                if ch == "[":
                    self.state, self.csi = "csi", ""
                elif ch == "]":
                    self.state, self.osc = "osc", ""
                elif ch == "_":
                    self.state, self.apc = "apc", ""
                elif ch == "P":
                    self.state, self.dcs = "dcs", ""
                elif ch == "(":
                    self.state = "charset"
                elif ch == "M":
                    self.reverse_index()  # RI
                    self.state = "ground"
                elif ch == "7":
                    self.saved = (self.cx, self.cy)
                    self.state = "ground"
                elif ch == "8":
                    if self.saved:
                        self.cx, self.cy = self.saved
                    self.state = "ground"
                elif ch in "c":
                    self.reset()  # RIS
                elif ch in "DEH":
                    if ch == "H":
                        # HTS: põe uma parada de tabulação na coluna atual (P53)
                        self.tabstops[self.cx] = True
                    self.state = "ground"  # IND/NEL/HTS: só volta
                elif ch in "=>":
                    # DECKPAM / DECKPNM (P56): estado do teclado numérico; os
                    # bytes da tecla não mudam, como no Rust
                    self.keypad_app = ch == "="
                    self.state = "ground"
                else:
                    self.state = "ground"
            elif st == "csi":
                # ECMA-48: params 0x30-0x3f, DEPOIS intermediários 0x20-0x2f,
                # e só então o byte final. Sem aceitar os intermediários, um
                # `CSI * x` (DECSACE, que o icat manda) terminava no `*` e o
                # `x` caía no ground — imprimia um "x" solto na tela.
                if ch.isdigit() or ch in ";?: " or ch in "<=>" or " " <= ch <= "/":
                    self.csi += ch
                else:
                    key = (self.csi, ch)
                    parsed = _CSI_CACHE.get(key)
                    if parsed is None:
                        parsed = _csi_parse(self.csi, ch)
                        if len(_CSI_CACHE) > _CSI_MAX:
                            _CSI_CACHE.clear()
                        _CSI_CACHE[key] = parsed
                    self.csi_dispatch(ch, parsed[0], parsed[1], parsed[2])
                    self.state = "ground"
            elif st == "osc":
                if ch == "\x07":
                    self._osc_done()
                elif ch == "\x1b":
                    self.state = "osc-esc"
                else:
                    self.osc += ch
            elif st == "osc-esc":
                if ch == "\\":
                    self._osc_done()
                else:  # ESC sozinho: volta a interpretar
                    self.state = "ground"
                    self.feed(ch)
            elif st == "apc":
                if ch == "\x07":
                    self._apc_done()
                elif ch == "\x1b":
                    self.state = "apc-esc"
                else:
                    self.apc += ch
            elif st == "apc-esc":
                if ch == "\\":
                    self._apc_done()
                else:
                    self.state = "ground"
            elif st == "dcs":
                # DCS (sixel, DECRQSS, XTVERSION): consumed, never decoded, so
                # the payload cannot leak to the screen as text (P81). Skipping
                # by find keeps a megabyte of sixel off the per-char loop.
                m = _DCS_END.search(text, i)
                j = m.start() if m else n
                if len(self.dcs) < _DCS_KEEP:
                    self.dcs += text[i:j][: _DCS_KEEP - len(self.dcs)]
                if not m:
                    i = n
                    continue
                self.state = "ground" if text[j] == "\x07" else "dcs-esc"
                i = j + 1
                continue
            elif st == "dcs-esc":
                self.state = "ground" if ch == "\\" else "dcs"
                if self.state == "dcs":
                    self.dcs = ""
            elif st == "charset":
                self.charset_dec = ch == "0"
                self.state = "ground"
            i += 1

    def _apc_done(self):
        body, self.apc = self.apc, ""
        self.state = "ground"
        cw, ch = self.cell_size
        resp, used, move = self.graphics.handle(body, (self.cx, self.cy), (cw, ch))
        for r in resp:
            self.child_out += b"\x1b_" + r.encode() + b"\x1b\\"
        if move and used:
            for _ in range(used):
                self.newline()

    def _osc_done(self):
        o = self.osc
        self.osc = ""
        self.state = "ground"
        if o[:2] in ("0;", "2;"):
            self.title = o[2:]
        elif o.startswith("7;"):
            self._osc_cwd(o[2:])
        elif o.startswith("9;"):
            # `9;4;estado[;%]` é a barra de progresso (mintty/ConEmu): vira
            # estado na aba (P65); um TUI ocupado manda a 1 Hz, não é toast
            p = _osc_progress(o[2:])
            if p is None:
                self._notify(o[2:])
            elif p[0] == 0:
                self.progress = None
            elif p[0] <= 4:
                self.progress = p  # estado fora de 0..4: engolido, como sempre
        elif o.startswith("777;"):
            self._osc_notify777(o[4:])
        elif o.startswith("52;"):
            self._osc_clip(o[3:])
        elif o.startswith("8;"):
            # OSC 8 ; params ; URI: URI vazio fecha o link corrente
            parts = o.split(";", 2)
            if len(parts) > 2:
                self.link = self._link_id(parts[2], _link_ident(parts[1]))
            else:
                self.link = 0
        elif o[:3] in ("10;", "11;", "12;"):
            # cor de frente/fundo/cursor: define (`;#rgb`) ou consulta (`;?`)
            which = int(o[:2])
            spec = o[3:]
            if spec == "?":
                if which == 10:
                    r, g, b = self.theme.fg
                elif which == 11:
                    r, g, b = self.theme.bg
                else:
                    r, g, b = self.theme.cursor or self.theme.fg
                resp = f"\x1b]{which};rgb:{r * 257:04x}/{g * 257:04x}/{b * 257:04x}"
                self.child_out += (resp + "\x1b\\").encode()
            else:
                c = parse_osc_color(spec)
                if c is not None:
                    self.theme.set_color(which, int_rgb(c))
        elif o.startswith("4;"):
            # `OSC 4;índice;cor` define (0..15, como o Rust) e `;?` consulta;
            # os pares continuam (4;1;?;2;?)
            parts = o.split(";")[1:]
            out = ""
            for i in range(0, len(parts) - 1, 2):
                try:
                    n = int(parts[i])
                except ValueError:
                    continue
                if not 0 <= n < 16:
                    continue
                spec = parts[i + 1]
                if spec == "?":
                    r, g, b = self.theme.color(n)
                    out += f"\x1b]4;{n};rgb:{r * 257:04x}/{g * 257:04x}/{b * 257:04x}\x1b\\"
                else:
                    c = parse_osc_color(spec)
                    if c is not None:
                        self.theme.set_osc4(n, int_rgb(c))
            if out:
                self.child_out += out.encode()
        elif o == "104" or o.startswith("104;"):
            # `OSC 104[;índice...]`: as entradas voltam para a base da configuração
            if o == "104":
                self.theme.reset_osc4()
            else:
                idxs = [int(p) for p in o[4:].split(";") if p.isdigit() and int(p) < 16]
                self.theme.reset_osc4(idxs)
        elif o in ("110", "111", "112"):
            # `OSC 110/111/112`: frente, fundo e cursor de volta ao configurado
            self.theme.reset_color(int(o) - 100)

    def _osc_clip(self, arg):
        """`OSC 52;Pc;Pd` (P64): Pd em base64 vira clipboard; `?` consulta.

        Pc escolhe o alvo (`p`/`s` = primary, o resto = clipboard); o
        conteúdo do `?` mora no clipboard do Gtk, então a resposta é o
        mesmo formato com payload vazio.
        """
        parts = arg.split(";", 1)
        if len(parts) != 2:
            return
        sel, data = parts
        if data == "?":
            self.child_out += ("\x1b]52;" + sel + ";;\x1b\\").encode()
            return
        try:
            raw = base64.b64decode(data, validate=True)
        except ValueError:  # binascii.Error é subclasse de ValueError
            return
        self.clip_text = raw.decode("utf-8", "replace")
        self.clip_sel = "primary" if sel in ("p", "s") else "clipboard"
        self.clip_seq += 1

    def _notify(self, text):
        """Notificação do app (P44): texto limpo e contador.

        O host é quem decide (toast na aba da frente, badge na de trás); aqui
        só entra o que uma linha de tela aguenta.
        """
        clean = "".join(c for c in text if c >= " " and c != "\x7f")[:NOTIF_MAX]
        if not clean:
            return
        self.notif_text = clean
        self.notifs += 1

    def _osc_notify777(self, arg):
        """`OSC 777;notify;título;corpo` (urxvt): só `notify` é recado."""
        parts = arg.split(";", 2)
        if parts[0] != "notify":
            return
        title = parts[1] if len(parts) > 1 else ""
        body = parts[2] if len(parts) > 2 else ""
        if not title:
            self._notify(body)
        elif body:
            self._notify(title + ": " + body)
        else:
            self._notify(title)

    def _osc_cwd(self, arg):
        """`OSC 7`: `file://host/caminho` do shell, já decodificado (P47).

        Com `/proc` respondendo isto é só um atalho; sem ele (processo que não
        é descendente do pty) é o que sobra. Payload fora do formato não apaga
        o que já se sabia.
        """
        if not arg:
            self.cwd = None
            return
        if not arg.startswith("file://"):
            return
        rest = arg[len("file://") :]
        path = rest[rest.find("/") :] if "/" in rest else ""
        clean = "".join(c for c in unquote(path) if c >= " " and c != "\x7f")
        self.cwd = clean or None

    def _kbd_protocol(self, params, prefix):
        """CSI > flags u (push) / CSI < n u (pop) / CSI = flags ; modo u (set)
        / CSI ? u (query). Modo: 1 = substitui, 2 = acrescenta, 3 = remove."""
        if prefix == "?":
            self.child_out += f"\x1b[?{self.kbd_flags}u".encode()
        elif prefix == ">":
            self.kbd_stack.append(self.kbd_flags)
            self.kbd_flags = params[0] if params else 0
        elif prefix == "<":
            for _ in range(params[0] if params else 1):
                self.kbd_flags = self.kbd_stack.pop() if self.kbd_stack else 0
        elif prefix == "=":
            flags = params[0] if params else 0
            mode = params[1] if len(params) > 1 else 1
            if mode == 1:
                self.kbd_flags = flags
            elif mode == 2:
                self.kbd_flags |= flags
            elif mode == 3:
                self.kbd_flags &= ~flags

    def row_text(self, y):
        return row_text(self.grid[y])

    def visible_rows(self, off=0):
        """As `rows` linhas que estão na tela, com `off` linhas de histórico.

        `off`=0 é o vivo (a grade). `off`>0 puxa as últimas `off` linhas do
        scrollback pra cima da grade — a tela é uma janela que desliza, sem
        mexer no cursor nem no que o app escreveu.
        """
        off = max(0, min(off, len(self.scrollback)))
        if not off:
            return self.grid
        sb = self.scrollback
        if off >= self.rows:
            # janela inteira dentro do histórico: sempre `rows` linhas (antes
            # `grid[:rows-off]` com off > rows devolvia a lista inteira do
            # scrollback, e o draw pintava off linhas — rolar para cima ficava
            # linearmente mais lento)
            lo = len(sb) - off
            return sb[lo : lo + self.rows]
        return sb[-off:] + self.grid[: self.rows - off]

    def anchored_view_off(self, anchor):
        """`view_off` que mantém a linha absoluta `anchor` no topo da visão.

        `scrolled` é o índice absoluto da linha do topo do vivo e nunca volta
        (nem quando o scrollback bate no teto e descarta linha velha), então a
        conta serve para segurar o texto lido no lugar enquanto o app escreve.
        Limpa o histórico (`CSI 3J`) e o clampe devolve o vivo: a âncora sumiu.
        """
        return max(0, min(self.scrolled - anchor, len(self.scrollback)))

    def pinned_view_off(self, pin):
        """`view_off` que segura `pin` linhas atrás do vivo depois do `CSI 3J`.

        A âncora absoluta morre com o histórico, mas a distância do vivo não
        precisa morrer: o app que limpou reescreve o mesmo texto (B20).
        """
        return min(pin, len(self.scrollback))

    def abs_row(self, line):
        """A fileira de células da linha absoluta, ou None se ela não existe."""
        lo = self.scrolled - len(self.scrollback)
        if line < lo:
            return None
        if line < self.scrolled:
            return self.scrollback[line - lo]
        if line < self.scrolled + len(self.grid):
            return self.grid[line - self.scrolled]
        return None

    def feed_chrome(self, text):
        """Alimenta uma DECORAÇÃO: as linhas que escreve ficam fora da foto (P57).

        É para a marca que separa a foto restaurada da execução que começa —
        conteúdo que o terminal escreveu, não o filho.
        """
        self.chrome_feed = True
        try:
            self.feed(text)
        finally:
            self.chrome_feed = False

    def snapshot(self):
        """A aba inteira em ANSI: alimentar um `Term` novo refaz a imagem (P57)."""
        return snapshot(self)

    def abs_wrapped(self, line):
        """A linha absoluta encheu a largura (a de baixo é continuação dela)."""
        lo = self.scrolled - len(self.scrollback)
        if line < lo or line >= self.scrolled + len(self.grid):
            return False
        if line < self.scrolled:
            i = line - lo
            return self.sb_wrapped[i] if i < len(self.sb_wrapped) else False
        return self.row_wrapped[line - self.scrolled]

    def line_span(self, line):
        """Primeira e última linha física da linha LÓGICA que contém `line`."""
        first, last = line, line
        while first > self.scrolled - len(self.scrollback) and self.abs_wrapped(first - 1):
            first -= 1
        while self.abs_wrapped(last) and self.abs_row(last + 1) is not None:
            last += 1
        return first, last

    def word_span(self, line, col):
        """Colunas (início, fim) inclusivas da palavra sob `col`.

        Palavra termina só em espaço em branco: um caminho selecionado sai
        inteiro. Clicar no espaço seleciona a corrida de espaços.
        """
        row = self.abs_row(line)
        if row is None:
            return col, col
        text = row_text(row).rstrip()  # o espaço da direita não é palavra
        if not text:
            return 0, 0
        col = max(0, min(len(text) - 1, col))
        sep = text[col].isspace()
        first = col
        while first > 0 and text[first - 1].isspace() == sep:
            first -= 1
        last = col
        while last + 1 < len(text) and text[last + 1].isspace() == sep:
            last += 1
        return first, last

    def logical_line_span(self, line):
        """Âncoras (início, fim) da linha lógica, já sem o espaço da direita."""
        first, last = self.line_span(line)
        row = self.abs_row(last)
        text = row_text(row).rstrip() if row is not None else ""
        return (first, 0), (last, max(0, len(text) - 1))

    # -- âncoras de célula (B17) ---------------------------------------
    def anchor_at(self, view_off, row, col):
        """Âncora absoluta da célula (row, col) da visão com `view_off`."""
        return CellAnchor(self.scrolled - view_off + row, col, self.abs_gen)

    def anchor_row(self, anchor, view_off):
        """Fileira da visão onde a âncora cai; fora da tela dá <0 ou >= rows."""
        return anchor.line - self.scrolled + view_off

    def anchor_alive(self, anchor):
        """A âncora ainda aponta para conteúdo existente (não sumiu nem refluiu)."""
        if anchor.gen != self.abs_gen:
            return False
        return self.abs_row(anchor.line) is not None

    def anchor_text(self, start, end):
        """Texto entre duas âncoras, mesmo fora da visão (a seleção não some)."""
        if (start.line, start.col) > (end.line, end.col):
            start, end = end, start
        if not self.anchor_alive(start) or not self.anchor_alive(end):
            return ""
        rows = [self.abs_row(line) for line in range(start.line, end.line + 1)]
        if any(r is None for r in rows):
            return ""
        return self._span_text(rows, (0, start.col), (len(rows) - 1, end.col))

    def anchor_block_text(self, start, end):
        """Bloco (P61): as mesmas colunas em toda linha, uma linha por vez.

        A linha que quebrou mole NÃO continua na de baixo aqui — o bloco é
        cortado por linha, porque o que se quer são as colunas (é a regra do
        Rust). Espaço à direita de cada linha sai fora.
        """
        if not (self.anchor_alive(start) and self.anchor_alive(end)):
            return ""
        lo = min(start.col, end.col)
        hi = max(start.col, end.col) + 1
        y1, y2 = min(start.line, end.line), max(start.line, end.line)
        out = []
        for line in range(y1, y2 + 1):
            row = self.abs_row(line)
            if row is None:
                return ""
            out.append(row_text(row, lo, hi).rstrip())
        return "\n".join(out)

    # -- texto (cópia) ------------------------------------------------
    def paste_payload(self, text):
        """O que mandar pro filho quando o usuário cola `text`.

        Com `?2004` ligado, o texto vai entre `ESC[200~` e `ESC[201~`: o app
        (readline, vim, python) sabe que é cola e não trata `\n` como Enter.
        A política mora aqui (e não na janela) pra ser testável sem display.
        """
        if self.bracketed_paste:
            return "\x1b[200~" + text + "\x1b[201~"
        return text

    def selection_text(self, start, end, rows=None):
        """Texto entre duas células (row, col), 0-based, pontas inclusivas.

        Ordem invertida (arrastar de baixo pra cima) é normalizada. Espaço à
        direita de cada linha sai fora — é o que todo terminal faz ao copiar.
        `rows` permite copiar da visão de histórico em vez da grade viva.
        """
        if rows is None:
            rows = self.grid
        return self._span_text(rows, start, end)

    def _span_text(self, rows, start, end):
        """Texto entre duas células de `rows` (pontas inclusivas, sem espaço à direita)."""
        (r1, c1), (r2, c2) = start, end
        if (r1, c1) > (r2, c2):
            (r1, c1), (r2, c2) = (r2, c2), (r1, c1)
        last = len(rows) - 1
        r1 = max(0, min(last, r1))
        r2 = max(0, min(last, r2))
        out = []
        for y in range(r1, r2 + 1):
            a = c1 if y == r1 else 0
            b = (c2 + 1) if y == r2 else self.cols
            row = rows[y]
            out.append(row_text(row, a, b).rstrip())
        return "\n".join(out)

    def all_text(self, rows=None):
        """A viewport inteira (Ctrl+Shift+C sem seleção)."""
        rows = self.grid if rows is None else rows
        lines = [row_text(row).rstrip() for row in rows]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines) + ("\n" if lines else "")
