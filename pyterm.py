#!/usr/bin/env python3
"""pyterm — terminal mínimo em Python puro (experimento).

Propósito: sentir na pele o custo do caminho quente (parse VT + grade +
desenho) em Python, comparado ao núcleo C do gtkterm. Roda shell de verdade
e aguenta o `mc` — devagar, e esse é o ponto.

Uso:
    python3 pyterm.py [--cmd 'comando'] [--quit-after SEG] [--selftest]

Só depende de PyGObject (Gtk3) + pycairo, que já existem no sistema.
GPL-3.0-only.
"""

import codecs
import math
import os
import pty
import signal
import struct
import sys
import termios
import unicodedata

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gtk, Gdk, GLib
try:
    from gi.repository import GdkX11
except (ImportError, ValueError):
    GdkX11 = None
import cairo

# ---------------------------------------------------------------- grade ---

# célula: [char, fg, bg, flags]  (fg/bg: 0-15, 256=default fg, 257=default bg)
# flags: 1=bold 2=underline 4=inverse
DEF_FG, DEF_BG = 256, 257
BOLD, UL, INV = 1, 2, 4

PALETTE = [
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
    (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
    (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
]
def _build_256():
    pal = list(PALETTE)
    steps = [0, 95, 135, 175, 215, 255]
    for r in steps:
        for g in steps:
            for b in steps:
                pal.append((r, g, b))
    for i in range(24):
        v = 8 + i * 10
        pal.append((v, v, v))
    return pal


PALETTE256 = _build_256()

BG_DEFAULT = (0, 0, 0)
FG_DEFAULT = (214, 214, 214)

# DEC special graphics (ESC ( 0): tecla -> unicode
DEC_SPECIAL = {
    "`": "◆", "a": "▒", "f": "°", "g": "±", "j": "┘", "k": "┐",
    "l": "┌", "m": "└", "n": "┼", "o": "‾", "p": "‾", "q": "─",
    "r": "‾", "s": "_", "t": "├", "u": "┤", "v": "┴", "w": "┬",
    "x": "│", "y": "≤", "z": "≥", "{": "π", "|": "≠", "}": "£",
    "~": "•", "0": "█", ",": "←", "+": "→", ".": "↓", "-": "↑",
    "/": "↓", "h": "␤",
}


# Dead keys do X11: keysym -> marca combinante.
DEAD_MARKS = {
    0xfe50: 0x0300, 0xfe51: 0x0301, 0xfe52: 0x0302, 0xfe53: 0x0303,
    0xfe54: 0x0304, 0xfe55: 0x0306, 0xfe56: 0x0307, 0xfe57: 0x0308,
    0xfe58: 0x030a, 0xfe59: 0x030b, 0xfe5a: 0x030c, 0xfe5b: 0x0327,
    0xfe5c: 0x0328,
}
# dead key + espaço: o caractere espaçado (convenção X11)
DEAD_STANDALONE = {
    0x0300: "`", 0x0301: "'", 0x0302: "^", 0x0303: "~", 0x0304: "¯",
    0x0306: "˘", 0x0307: "˙", 0x0308: '"', 0x030a: "˚", 0x030b: "˝",
    0x030c: "ˇ", 0x0327: "¸", 0x0328: "˛",
}


class Term:
    """Estado do terminal: grade, cursor, parser VT. Sem GTK aqui."""

    def __init__(self, cols=80, rows=24):
        self.cols, self.rows = cols, rows
        self.grid = [self._blank_row() for _ in range(rows)]
        self.alt_grid = None          # None = buffer principal
        self.scrollback = []
        self.cx, self.cy = 0, 0
        self.fg, self.bg, self.flags = DEF_FG, DEF_BG, 0
        self.top, self.bottom = 0, rows - 1   # scroll region
        self.wrap_pending = False
        self.cursor_visible = True
        self.app_cursor = False       # DECCKM (?1): setas em modo aplicação
        self.charset_dec = False      # ESC ( 0 ativo?
        self.saved = None
        self.child_out = bytearray()  # respostas ao filho (DA, CPR...)
        self.title = "pyterm"
        self.state = "ground"
        self.csi = ""
        self.osc = ""
        # resposta a query de tamanho (o icat pergunta; aqui só o básico)
        self.respond_size = False

    # -- grade ------------------------------------------------------
    def _blank_row(self):
        return [[" ", DEF_FG, self.bg if False else DEF_BG, 0]
                for _ in range(self.cols)]

    def blank_cell(self):
        # áreas apagadas herdam o bg corrente (bce, como terminal real)
        return [" ", DEF_FG, self.bg, 0]

    def reset(self):
        """RIS (ESC c): limpa tudo, mantém o tamanho."""
        cols, rows = self.cols, self.rows
        self.__init__(cols, rows)

    def resize(self, cols, rows):
        """Redimensiona preservando o conteúdo (recorta/preenche)."""
        old_grid, old_cols, old_rows = self.grid, self.cols, self.rows
        self.cols, self.rows = cols, rows
        new = []
        for y in range(rows):
            if y < old_rows:
                row = old_grid[y][:cols]
                if len(row) < cols:
                    row = row + [self._blank_cell_raw()
                                 for _ in range(cols - len(row))]
                new.append(row)
            else:
                new.append([self._blank_cell_raw() for _ in range(cols)])
        self.grid = new
        self.top, self.bottom = 0, rows - 1
        self.cx = min(self.cx, cols - 1)
        self.cy = min(self.cy, rows - 1)
        self.wrap_pending = False

    def _blank_cell_raw(self):
        return [" ", DEF_FG, DEF_BG, 0]

    def scroll_up(self):
        if self.alt_grid is not None:
            self.grid.pop(self.top)
            self.grid.insert(self.bottom, self._blank_row())
        else:
            if self.top == 0 and self.bottom == self.rows - 1:
                self.scrollback.append(self.grid.pop(0))
                if len(self.scrollback) > 1000:
                    self.scrollback.pop(0)
                self.grid.append(self._blank_row())
            else:
                self.grid.pop(self.top)
                self.grid.insert(self.bottom, self._blank_row())

    def newline(self):
        if self.cy == self.bottom:
            self.scroll_up()
        else:
            self.cy = min(self.cy + 1, self.rows - 1)

    def put(self, ch):
        if self.wrap_pending:
            self.cx = 0
            self.newline()
            self.wrap_pending = False
        if ch == "\n":
            self.newline()
            return
        if ch == "\r":
            self.cx, self.wrap_pending = 0, False
            return
        if ch == "\b":
            self.cx, self.wrap_pending = max(0, self.cx - 1), False
            return
        if ch == "\t":
            self.cx = min(self.cols - 1, ((self.cx // 8) + 1) * 8)
            return
        if self.charset_dec:
            ch = DEC_SPECIAL.get(ch, ch)
        self.grid[self.cy][self.cx] = [ch, self.fg, self.bg, self.flags]
        if self.cx == self.cols - 1:
            self.wrap_pending = True
        else:
            self.cx += 1

    # -- comandos ----------------------------------------------------
    def cursor_to(self, r, c):
        self.cy = max(0, min(self.rows - 1, r))
        self.cx = max(0, min(self.cols - 1, c))
        self.wrap_pending = False

    def erase_display(self, n):
        if n == 2 or n == 3:
            for y in range(self.rows):
                self.grid[y] = [self.blank_cell() for _ in range(self.cols)]
            if n == 3:
                self.scrollback.clear()
            self.cursor_to(0, 0)
        elif n == 1:
            for x in range(self.cx + 1):
                self.grid[self.cy][x] = self.blank_cell()
            for y in range(self.cy):
                self.grid[y] = [self.blank_cell() for _ in range(self.cols)]
        else:  # 0
            for x in range(self.cx, self.cols):
                self.grid[self.cy][x] = self.blank_cell()
            for y in range(self.cy + 1, self.rows):
                self.grid[y] = [self.blank_cell() for _ in range(self.cols)]

    def erase_line(self, n):
        if n == 2:
            self.grid[self.cy] = [self.blank_cell() for _ in range(self.cols)]
        elif n == 1:
            for x in range(self.cx + 1):
                self.grid[self.cy][x] = self.blank_cell()
        else:
            for x in range(self.cx, self.cols):
                self.grid[self.cy][x] = self.blank_cell()

    def insert_lines(self, n):
        for _ in range(n):
            self.grid.pop(self.bottom)
            self.grid.insert(self.cy, [self.blank_cell()
                                       for _ in range(self.cols)])

    def delete_lines(self, n):
        for _ in range(n):
            self.grid.pop(self.cy)
            self.grid.insert(self.bottom, [self.blank_cell()
                                           for _ in range(self.cols)])

    def sgr(self, params):
        it = iter(params)
        for p in it:
            if p == 0:
                self.fg, self.bg, self.flags = DEF_FG, DEF_BG, 0
            elif p == 1:
                self.flags |= BOLD
            elif p == 4:
                self.flags |= UL
            elif p == 7:
                self.flags |= INV
            elif p == 22:
                self.flags &= ~BOLD
            elif p == 24:
                self.flags &= ~UL
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
                    # truecolor: aproxima para a paleta (experimento mínimo)
                    if len(vals) == 3:
                        idx = self._nearest(*vals)
                        if p == 38:
                            self.fg = idx
                        else:
                            self.bg = idx

    @staticmethod
    def _nearest(r, g, b):
        best, bd = 0, 1e9
        for i, (pr, pg, pb) in enumerate(PALETTE):
            d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if d < bd:
                best, bd = i, d
        return best

    def set_mode(self, params, private, on):
        for p in params:
            if private and p == 25:
                self.cursor_visible = on
            elif private and p == 1:
                # DECCKM: com o modo ligado as setas viram \EOA..\EOD
                # (é o que o terminfo de xterm chama de "aplicação"; mc,
                # vim e less ligam isso ao entrar em tela cheia)
                self.app_cursor = on
            elif p in (47, 1047, 1049):
                if on and self.alt_grid is None:
                    self.alt_grid = self.grid
                    self.grid = [self._blank_row() for _ in range(self.rows)]
                    self.saved = (self.cx, self.cy)
                    self.cursor_to(0, 0)
                    if p == 1049:
                        self.scrollback.clear()
                elif not on and self.alt_grid is not None:
                    self.grid = self.alt_grid
                    self.alt_grid = None
                    if self.saved:
                        self.cx, self.cy = self.saved
                    self.top, self.bottom = 0, self.rows - 1
            elif p == 1048:
                if on:
                    self.saved = (self.cx, self.cy)
                elif self.saved:
                    self.cx, self.cy = self.saved
            # mouse (1000/1002/1006), bracketed paste (2004),
            # foco (1004): rastreados e ignorados — sem mouse aqui

    def csi_dispatch(self, final, params, private):
        get = lambda i, d: (params[i] if i < len(params)
                            and params[i] is not None else d)

        if final == "m":
            self.sgr(params or [0])
        elif final in "ABCDEFG":
            k = get(0, 1) or 1
            if final in "AE":
                self.cursor_to(self.cy - k if final == "A" else self.cy + k,
                               self.cx)
            elif final in "CD":
                self.cursor_to(self.cy,
                               self.cx + k if final == "C" else self.cx - k)
            elif final == "B":
                self.cursor_to(self.cy + k, self.cx)
            elif final == "F":
                self.cursor_to(self.cy - k, 0)
            elif final == "G":
                self.cursor_to(self.cy, k - 1)
        elif final in "Hf":
            self.cursor_to(get(0, 1) - 1, get(1, 1) - 1)
        elif final == "d":
            self.cursor_to(get(0, 1) - 1, self.cx)
        elif final == "J":
            self.erase_display(get(0, 0))
        elif final == "K":
            self.erase_line(get(0, 0))
        elif final == "L":
            self.insert_lines(get(0, 1) or 1)
        elif final == "M":
            self.delete_lines(get(0, 1) or 1)
        elif final == "@":
            k = get(0, 1) or 1
            row = self.grid[self.cy]
            row[self.cx:self.cx] = [self.blank_cell()] * k
            del row[self.cols:]
        elif final == "P":
            k = get(0, 1) or 1
            row = self.grid[self.cy]
            del row[self.cx:self.cx + k]
            row.extend([self.blank_cell()] * k)
        elif final == "X":
            k = get(0, 1) or 1
            for x in range(self.cx, min(self.cols, self.cx + k)):
                self.grid[self.cy][x] = self.blank_cell()
        elif final == "r":
            t, b = get(0, 1) - 1, get(1, self.rows) - 1
            if 0 <= t < b < self.rows:
                self.top, self.bottom = t, b
                self.cursor_to(0, 0)
        elif final == "s":
            self.saved = (self.cx, self.cy)
        elif final == "u":
            if self.saved:
                self.cx, self.cy = self.saved
        elif final in "hl":
            self.set_mode(params or [0], private, final == "h")
        elif final == "c" and not params and not private:
            self.child_out += b"\x1b[?62c"  # DA: VT102
        elif final == "n" and params == [6]:
            # DSR: informa posição do cursor
            self.child_out += f"\x1b[{self.cy + 1};{self.cx + 1}R".encode()
        # resto: ignorado silenciosamente (experimento mínimo)

    # -- parser -------------------------------------------------------
    def feed(self, text):
        for ch in text:
            o = ord(ch)
            st = self.state
            if st == "ground":
                if ch == "\x1b":
                    self.state = "esc"
                elif ch in "\x07":
                    pass  # BEL
                elif o < 0x20 or o == 0x7f:
                    if ch in "\n\r\b\t":
                        self.put(ch)
                    # resto dos C0 ignorado
                else:
                    self.put(ch)
            elif st == "esc":
                if ch == "[":
                    self.state, self.csi = "csi", ""
                elif ch == "]":
                    self.state, self.osc = "osc", ""
                elif ch == "(":
                    self.state = "charset"
                elif ch == "M":
                    self.cursor_to(self.cy - 1, self.cx)  # RI
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
                    self.state = "ground"  # IND/NEL/HTS: só volta
                elif ch in "=>":
                    self.state = "ground"  # teclado numérico
                else:
                    self.state = "ground"
            elif st == "csi":
                if ch.isdigit() or ch in ";?: " or ch in "<=>":
                    self.csi += ch
                else:
                    body = self.csi
                    private = body.startswith("?")
                    body = body.lstrip("?")
                    parts = []
                    for tok in body.split(";") if body else []:
                        tok = tok.strip()
                        if tok == "" or tok.startswith((" ", "<", "=", ">")):
                            parts.append(None if tok == "" else 0)
                        else:
                            try:
                                parts.append(int(tok))
                            except ValueError:
                                parts.append(None)
                    nums = [p if p is not None else 0 for p in parts]
                    self.csi_dispatch(ch, nums, private)
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
            elif st == "charset":
                self.charset_dec = (ch == "0")
                self.state = "ground"

    def _osc_done(self):
        # só título (0/2); resto ignorado
        if self.osc[:2] in ("0;", "2;"):
            self.title = self.osc[2:]
        self.osc = ""
        self.state = "ground"

    def row_text(self, y):
        return "".join(c[0] for c in self.grid[y])


# ------------------------------------------------------------------
# autochetcagem sem GTK: python3 pyterm.py --selftest
# ------------------------------------------------------------------

def selftest():
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: obtido {got!r}, esperado {want!r}")
        else:
            print(f"  ok: {name}")

    t = Term()
    t.feed("oi")
    check("texto", t.row_text(0)[:2], "oi")
    check("cursor", (t.cx, t.cy), (2, 0))

    t = Term()
    t.feed("\x1b[31mX\x1b[0mY")
    check("SGR fg", (t.grid[0][0][1], t.grid[0][1][1]), (1, DEF_FG))

    t = Term()
    t.feed("\x1b[2;5H*\x1b[1;1H#")
    check("CUP", (t.grid[1][4][0], t.grid[0][0][0]), ("*", "#"))

    t = Term()
    t.feed("abc\x1b[2K")
    check("EL 2", t.row_text(0)[:3], "   ")
    t.feed("abc\x1b[2Jx")
    check("ED 2", (t.row_text(0)[0], (t.cx, t.cy)), ("x", (1, 0)))

    t = Term()
    t.feed("\x1b[?1049hALT\x1b[?1049l")
    check("altscreen volta", t.row_text(0)[:3], "   ")
    t2 = Term()
    t2.feed("\x1b[?1049hALT")
    check("altscreen mostra", t2.row_text(0)[:3], "ALT")

    t = Term()
    t2 = t
    for _ in range(30):
        t.feed("l\n")
    check("scroll", (len(t.scrollback) > 0, t.cy), (True, 23))

    t = Term()
    t.feed("\x1b(0qqqq\x1b(B")
    check("DEC linha", t.row_text(0)[:4], "────")

    t = Term()
    t.feed("\x1b[c")
    check("DA responde", bytes(t.child_out), b"\x1b[?62c")
    t.child_out = bytearray()
    t.feed("\x1b[5;9H\x1b[6n")
    check("DSR/CPR", bytes(t.child_out), b"\x1b[5;9R")

    t = Term()
    t.feed("\x1b[3;10r")
    check("scroll region", (t.top, t.bottom), (2, 9))

    t = Term()
    t.feed("\x1b]0;titulo\x07")
    check("OSC título", t.title, "titulo")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}):")
        for f in fails:
            print("  FAIL:", f)
        return 1
    print("SELFTEST OK")
    return 0


# ------------------------------------------------------------------ GTK ---

class PyTermWindow(Gtk.Window):
    def __init__(self, cmd=None, quit_after=0, dump_to=None):
        super().__init__(title="pyterm")
        self.dump_to = dump_to
        self.dead_mark = 0   # dead key pendente (marca combinante)
        self.term = Term()
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.add(self.area)
        self.area.connect("draw", self.on_draw)
        self.connect("key-press-event", self.on_key)
        # size-allocate (e não configure-event): o configure do GtkWindow
        # chega ANTES do filho ser re-alocado, então get_allocation() ali
        # ainda devolve o tamanho antigo e o resize nunca era aplicado.
        self.area.connect("size-allocate", self.on_resize)
        self.connect("destroy", Gtk.main_quit)
        self.font_size = 16
        self._metrics = None
        self.set_default_size(680, 420)

        self.master = None
        self.child_pid = None
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.spawn(cmd or os.environ.get("SHELL", "/bin/bash"))
        if quit_after:
            GLib.timeout_add_seconds(quit_after, self._on_quit_after)
        # SIGUSR1 dumpar a grade na hora (depuração: "kill -USR1 <pid>")
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1,
                             self._on_dump_signal)

    # -- pty --------------------------------------------------------
    def spawn(self, cmd):
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "xterm-256color"
            try:
                os.execlp("sh", "sh", "-c", cmd)
            except Exception:
                os._exit(127)
        self.child_pid = pid
        self.master = fd
        os.set_blocking(fd, False)
        GLib.io_add_watch(fd, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                           self.on_pty)

    def on_pty(self, fd, cond):
        try:
            data = os.read(fd, 65536)
        except OSError:
            return False
        if not data:
            self.dump()
            Gtk.main_quit()
            return False
        self.term.feed(self.decoder.decode(data))
        # respostas do núcleo (DA/CPR) voltam ao filho
        if self.term.child_out:
            try:
                os.write(fd, bytes(self.term.child_out))
            except OSError:
                pass
            self.term.child_out = bytearray()
        if self.term.title != self.get_title():
            self.set_title(self.term.title)
        self.area.queue_draw()
        return True

    def _on_quit_after(self):
        self.dump()
        Gtk.main_quit()
        return False

    def _on_dump_signal(self):
        self.dump()
        return True

    def dump(self):
        if not self.dump_to:
            self.dump_to = "/tmp/pyterm-dump.txt"
        if not self.dump_to:
            return
        t = self.term
        lines = []
        if t.scrollback:
            lines.append(f"=== scrollback ({len(t.scrollback)}) ===")
            for row in t.scrollback[-40:]:
                lines.append("".join(c[0] for c in row).rstrip())
        lines.append(f"=== viewport {t.cols}x{t.rows} ===")
        for y in range(t.rows):
            lines.append(t.row_text(y).rstrip())
        lines.append(f"=== cursor {t.cx},{t.cy} ===")
        try:
            with open(self.dump_to, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            print("dump falhou:", e, file=sys.stderr)

    # -- métricas ----------------------------------------------------
    def metrics(self):
        if self._metrics:
            return self._metrics
        surf = cairo.ImageSurface(cairo.FORMAT_A1, 8, 8)
        ctx = cairo.Context(surf)
        ctx.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                             cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(self.font_size)
        # largura da célula = avanço da fonte arredondado PRA CIMA: se for
        # menor que o avanço real, o texto derrapa e as colunas desalinham.
        adv = ctx.text_extents("M")[4]
        ascent, descent = ctx.font_extents()[0], ctx.font_extents()[1]
        self._metrics = (math.ceil(adv), math.ceil(ascent + descent))
        return self._metrics

    def on_resize(self, widget, alloc):
        if alloc.width < 10 or alloc.height < 10:
            return False
        cw, ch = self.metrics()
        cols = max(2, alloc.width // int(cw))
        rows = max(1, alloc.height // int(ch))
        if (cols, rows) != (self.term.cols, self.term.rows):
            self.term.resize(cols, rows)
            self._send_winsize(cols, rows)
            self.area.queue_draw()
        return False

    def _send_winsize(self, cols, rows):
        import fcntl
        cw, ch = self.metrics()
        winsz = struct.pack("HHHH", rows, cols,
                            int(cols * cw), int(rows * ch))
        try:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, winsz)
            os.kill(self.child_pid, signal.SIGWINCH)
        except OSError:
            pass

    # -- desenho ------------------------------------------------------
    def on_draw(self, area, cr):
        t = self.term
        cw, ch = self.metrics()
        cw, ch = int(cw), int(ch)
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(self.font_size)
        ascent = cr.font_extents()[0]
        # fundo
        r, g, b = [c / 255 for c in BG_DEFAULT]
        cr.set_source_rgb(r, g, b)
        cr.paint()
        for y in range(t.rows):
            row = t.grid[y]
            x = 0
            while x < t.cols:
                cell = row[x]
                j = x
                while (j < t.cols and row[j][1] == cell[1]
                       and row[j][2] == cell[2]
                       and row[j][3] == cell[3]):
                    j += 1
                fg, bg, fl = cell[1], cell[2], cell[3]
                if fl & INV:
                    fg, bg = bg, fg
                bgc = BG_DEFAULT if bg == DEF_BG else PALETTE256[bg % 256]
                if bgc != BG_DEFAULT:
                    cr.set_source_rgb(*[c / 255 for c in bgc])
                    cr.rectangle(x * cw, y * ch, (j - x) * cw, ch)
                    cr.fill()
                fgc = FG_DEFAULT if fg == DEF_FG else PALETTE256[fg % 256]
                cr.set_source_rgb(*[c / 255 for c in fgc])
                txt = "".join(c[0] for c in row[x:j])
                if fl & BOLD:
                    cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                                        cairo.FONT_WEIGHT_BOLD)
                cr.move_to(x * cw, y * ch + ascent + 1)
                cr.show_text(txt)
                if fl & BOLD:
                    cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                                        cairo.FONT_WEIGHT_NORMAL)
                if fl & UL:
                    cr.rectangle(x * cw, y * ch + ch - 2, (j - x) * cw, 1)
                    cr.fill()
                x = j
        # cursor bloco
        if t.cursor_visible and t.cy < t.rows and t.cx < t.cols:
            cr.set_source_rgb(*[c / 255 for c in FG_DEFAULT])
            cr.rectangle(t.cx * cw, t.cy * ch, cw, ch)
            cr.fill()
            cell = t.grid[t.cy][t.cx]
            bgc = BG_DEFAULT if cell[2] == DEF_BG else PALETTE256[cell[2] % 256]
            cr.set_source_rgb(*[c / 255 for c in bgc])
            cr.move_to(t.cx * cw, t.cy * ch + ascent + 1)
            cr.show_text(cell[0])
        return False

    # -- teclado -------------------------------------------------------
    def on_key(self, widget, ev):
        t = self.term
        mods = ev.state & (Gdk.ModifierType.CONTROL_MASK |
                           Gdk.ModifierType.SHIFT_MASK |
                           Gdk.ModifierType.MOD1_MASK)
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        kv = ev.keyval
        out = None

        SIMPLE = {
            Gdk.KEY_Return: "\r", Gdk.KEY_KP_Enter: "\r",
            Gdk.KEY_BackSpace: "\x7f", Gdk.KEY_Tab: "\t",
            Gdk.KEY_Escape: "\x1b",
            Gdk.KEY_Up: "\x1b[A", Gdk.KEY_Down: "\x1b[B",
            Gdk.KEY_Right: "\x1b[C", Gdk.KEY_Left: "\x1b[D",
            Gdk.KEY_Home: "\x1b[H", Gdk.KEY_End: "\x1b[F",
            Gdk.KEY_Insert: "\x1b[2~", Gdk.KEY_Delete: "\x1b[3~",
            Gdk.KEY_Page_Up: "\x1b[5~", Gdk.KEY_Page_Down: "\x1b[6~",
            Gdk.KEY_F1: "\x1bOP", Gdk.KEY_F2: "\x1bOQ",
            Gdk.KEY_F3: "\x1bOR", Gdk.KEY_F4: "\x1bOS",
            Gdk.KEY_F5: "\x1b[15~", Gdk.KEY_F6: "\x1b[17~",
            Gdk.KEY_F7: "\x1b[18~", Gdk.KEY_F8: "\x1b[19~",
            Gdk.KEY_F9: "\x1b[20~", Gdk.KEY_F10: "\x1b[21~",
            Gdk.KEY_F11: "\x1b[23~", Gdk.KEY_F12: "\x1b[24~",
        }
        if kv == Gdk.KEY_ISO_Left_Tab:
            out = "\x1b[Z"
        elif kv in SIMPLE:
            out = SIMPLE[kv]
            if t.app_cursor:
                out = {Gdk.KEY_Up: "\x1bOA", Gdk.KEY_Down: "\x1bOB",
                       Gdk.KEY_Right: "\x1bOC", Gdk.KEY_Left: "\x1bOD",
                       Gdk.KEY_Home: "\x1bOH", Gdk.KEY_End: "\x1bOF",
                       }.get(kv, out)
            if kv == Gdk.KEY_Tab and (ev.state &
                                      Gdk.ModifierType.SHIFT_MASK):
                out = "\x1b[Z"
        elif ctrl and Gdk.KEY_a <= kv <= Gdk.KEY_z:
            out = chr(kv & 0x1f)
        elif ctrl and Gdk.KEY_A <= kv <= Gdk.KEY_Z:
            out = chr((kv + 32) & 0x1f)
        elif ctrl and kv in (Gdk.KEY_space, Gdk.KEY_2):
            out = "\x00"
        elif ctrl and kv == Gdk.KEY_minus:
            out = "\x1f"
        elif kv in DEAD_MARKS and not (ctrl or alt):
            # dead key: guarda a marca e não manda nada agora
            self.dead_mark = DEAD_MARKS[kv]
            return True
        else:
            # SÓ caractere imprimível vira byte. Keyval de modificador e de
            # tecla de função fica na faixa 0xff00-0xffff (Shift_L=0xffe1,
            # Control_L=0xffe3, Alt_L=0xffe9, Super_L=0xffeb, Caps_Lock=0xffe5,
            # Menu=0xff67); sem este filtro cada tecla dessas virava um
            # caractere sem glifo (a "caixinha" na tela).
            s = ""
            if kv >= 0x01000000:            # unicode direto
                try:
                    s = chr(kv & 0xFFFFFF)
                except ValueError:
                    s = ""
            elif 0x20 <= kv <= 0x7e or 0xa0 <= kv <= 0xff:
                s = chr(kv)                  # latin-1 imprimível
            if not s or ctrl:
                return False
            if self.dead_mark:
                mark, self.dead_mark = self.dead_mark, 0
                if s == " ":
                    out = DEAD_STANDALONE.get(mark, " ")
                else:
                    comp = unicodedata.normalize("NFC", s + chr(mark))
                    out = comp if len(comp) == 1 else s
                if alt:
                    out = "\x1b" + out
            else:
                out = ("\x1b" + s) if alt else s
        if out:
            try:
                os.write(self.master, out.encode("utf-8", "replace"))
            except OSError:
                pass
            return True
        return False


def main(argv):
    if "--selftest" in argv:
        return selftest()
    cmd, quit_after = None, 0
    args = list(argv[1:])
    while args:
        a = args.pop(0)
        if a == "--cmd" and args:
            cmd = args.pop(0)
        elif a == "--quit-after" and args:
            quit_after = int(args.pop(0))
    dump_to = None
    args = list(argv[1:])
    while args:
        a = args.pop(0)
        if a == "--dump-to" and args:
            dump_to = args.pop(0)
    win = PyTermWindow(cmd=cmd, quit_after=quit_after, dump_to=dump_to)
    win.show_all()
    # O Marco (MATE) nega present() com timestamp 0 (GDK_CURRENT_TIME): é
    # preciso o timestamp ATUAL do servidor X, como fazem os apps Qt.
    gdkwin = win.get_window()
    ts = GdkX11.x11_get_server_time(gdkwin) if GdkX11 else Gdk.CURRENT_TIME
    win.present_with_time(ts)
    win.area.grab_focus()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
