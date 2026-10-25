"""A janela GTK: pty, event loop, desenho em cairo e teclado.

É a única camada que fala com o Gtk; toda a lógica de terminal está em `term`.
"""

import codecs
import math
import os
import pty
import signal
import struct
import sys
import termios

from .gui import Gtk, Gdk, GLib, cairo
from .keys import encode_key
from .palette import (DEF_FG, DEF_BG, BOLD, UL, INV, PALETTE256,
                      BG_DEFAULT, FG_DEFAULT)
from .term import Term


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
        """Traduz e manda a tecla; a tradução em si está em keys.encode_key."""
        out, self.dead_mark, handled = encode_key(
            ev.keyval, ev.state, self.dead_mark, self.term.app_cursor)
        if out:
            try:
                os.write(self.master, out.encode("utf-8", "replace"))
            except OSError:
                pass
        return handled
