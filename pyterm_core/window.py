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
from .keys import encode_key, is_modifier
from . import mouse
from .palette import (DEF_FG, DEF_BG, BOLD, UL, INV, PALETTE256,
                      BG_DEFAULT, FG_DEFAULT)
from .term import Term


def _in_sel(y, x, sel):
    """A célula (y, x) está dentro da seleção? (r1,c1,r2,c2) inclusivo."""
    r1, c1, r2, c2 = sel
    if y < r1 or y > r2:
        return False
    if y == r1 and x < c1:
        return False
    if y == r2 and x > c2:
        return False
    return True


class PyTermWindow(Gtk.Window):
    def __init__(self, cmd=None, quit_after=0, dump_to=None):
        super().__init__(title="pyterm")
        self.dump_to = dump_to
        self.dead_mark = 0   # dead key pendente (marca combinante)
        self.term = Term()
        # seleção local (quando o app NÃO pediu mouse): âncora e ponta
        self.sel_start = None
        self.sel_end = None
        self.dragging = False
        self._held = None    # botão do protocolo apertado agora
        self._state = 0      # modificadores do último evento (shift/alt/ctrl)
        self.view_off = 0    # 0 = vivo; >0 = linhas de histórico na tela
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                             Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK |
                             Gdk.EventMask.SCROLL_MASK)
        self.add(self.area)
        self.area.connect("draw", self.on_draw)
        self.connect("key-press-event", self.on_key)
        self.area.connect("button-press-event", self.on_button_press)
        self.area.connect("button-release-event", self.on_button_release)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("scroll-event", self.on_scroll)
        self.connect("focus-in-event", self.on_focus_in)
        self.connect("focus-out-event", self.on_focus_out)
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
        # output novo volta pro vivo (é o que todo terminal faz: o app está
        # falando, o usuário não está mais lendo o histórico)
        if self.view_off:
            self.view_off = 0
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

    # -- histórico (P2) -----------------------------------------------
    def visible_rows(self):
        return self.term.visible_rows(self.view_off)

    def scroll_view(self, delta):
        """Rola a visão no histórico. `delta` > 0 = pra trás no tempo."""
        t = self.term
        if t.alt_grid is not None:
            return False      # alt-screen não tem histórico que rolar
        off = max(0, min(len(t.scrollback), self.view_off + delta))
        if off != self.view_off:
            self.view_off = off
            self.area.queue_draw()
        return True

    def back_to_live(self):
        if self.view_off:
            self.view_off = 0
            self.area.queue_draw()

    # -- desenho ------------------------------------------------------
    def sel_range(self):
        """Seleção normalizada (r1, c1, r2, c2) ou None."""
        if self.sel_start is None or self.sel_end is None:
            return None
        (r1, c1), (r2, c2) = self.sel_start, self.sel_end
        if (r1, c1) > (r2, c2):
            (r1, c1), (r2, c2) = (r2, c2), (r1, c1)
        return (r1, c1, r2, c2)

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
        sel = self.sel_range()
        rows = self.visible_rows()
        for y, row in enumerate(rows):
            x = 0
            while x < t.cols:
                cell = row[x]
                fg, bg, fl = cell[1], cell[2], cell[3]
                s0 = bool(sel) and _in_sel(y, x, sel)
                j = x + 1
                while j < t.cols:
                    c2 = row[j]
                    if (c2[1] != fg or c2[2] != bg or c2[3] != fl
                            or (bool(sel) and _in_sel(y, j, sel)) != s0):
                        break
                    j += 1
                # a cor vira RGB ANTES de inverter: trocar os índices e só
                # depois converter transformava o texto default (256) em
                # "cor 1" (vermelho), porque 256/257 são sentinelas e não
                # índices da paleta.
                fgc = FG_DEFAULT if fg == DEF_FG else PALETTE256[fg % 256]
                bgc = BG_DEFAULT if bg == DEF_BG else PALETTE256[bg % 256]
                if (fl & INV) or s0:
                    fgc, bgc = bgc, fgc      # inverso / seleção = reverso
                if bgc != BG_DEFAULT:
                    cr.set_source_rgb(*[c / 255 for c in bgc])
                    cr.rectangle(x * cw, y * ch, (j - x) * cw, ch)
                    cr.fill()
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
        # cursor bloco — só no vivo: no histórico o cursor do app não está ali
        if (self.view_off == 0 and t.cursor_visible
                and t.cy < t.rows and t.cx < t.cols):
            cr.set_source_rgb(*[c / 255 for c in FG_DEFAULT])
            cr.rectangle(t.cx * cw, t.cy * ch, cw, ch)
            cr.fill()
            cell = t.grid[t.cy][t.cx]
            bgc = BG_DEFAULT if cell[2] == DEF_BG else PALETTE256[cell[2] % 256]
            cr.set_source_rgb(*[c / 255 for c in bgc])
            cr.move_to(t.cx * cw, t.cy * ch + ascent + 1)
            cr.show_text(cell[0])
        if self.view_off:
            # marcador de histórico no canto ("↑") com o quanto se voltou
            label = f"↑{self.view_off} "
            ext = cr.text_extents(label)
            x0 = (t.cols - 1) * cw - ext[2]
            cr.set_source_rgb(*[c / 255 for c in FG_DEFAULT])
            cr.rectangle(x0 - 2, 0, ext[2] + 4, ch)
            cr.fill()
            cr.set_source_rgb(*[c / 255 for c in BG_DEFAULT])
            cr.move_to(x0, ascent + 1)
            cr.show_text(label)
        return False

    # -- mouse, seleção e cópia ---------------------------------------
    def cell_at(self, px, py):
        """Pixel -> (col, row) 0-based, preso à grade."""
        cw, ch = self.metrics()
        t = self.term
        col = max(0, min(t.cols - 1, int(px // int(cw))))
        row = max(0, min(t.rows - 1, int(py // int(ch))))
        return col, row

    def _write_child(self, data):
        if not data:
            return
        try:
            os.write(self.master, data.encode("utf-8", "replace"))
        except OSError:
            pass

    def report_mouse(self, button, col, row, pressed=True, motion=False):
        """Manda um evento de mouse pro app (o app pediu com ?1000/1002/3)."""
        st = self._state
        mods = mouse.mods_from_state(
            bool(st & Gdk.ModifierType.SHIFT_MASK),
            bool(st & Gdk.ModifierType.MOD1_MASK),
            bool(st & Gdk.ModifierType.CONTROL_MASK))
        self._write_child(mouse.encode(button, col, row, pressed=pressed,
                                       sgr=self.term.mouse_sgr, mods=mods,
                                       motion=motion))

    def on_button_press(self, widget, ev):
        t = self.term
        self._state = ev.state
        col, row = self.cell_at(ev.x, ev.y)
        self.back_to_live()      # clicar sempre volta pro vivo
        btn = mouse.GDK_BUTTONS.get(ev.button)
        if t.mouse_mode and btn is not None:
            # o app quer saber do mouse: nada de seleção local
            self._held = btn
            self.report_mouse(btn, col, row, True)
            return True
        if ev.button == 1:
            self.sel_start = self.sel_end = (row, col)
            self.dragging = True
            self.area.queue_draw()
            return True
        if ev.button == 2:
            self.paste(Gdk.SELECTION_PRIMARY)
            return True
        return False

    def on_button_release(self, widget, ev):
        t = self.term
        self._state = ev.state
        col, row = self.cell_at(ev.x, ev.y)
        if t.mouse_mode and self._held is not None:
            self.report_mouse(self._held, col, row, False)
            self._held = None
            return True
        if ev.button == 1 and self.dragging:
            self.dragging = False
            self.area.queue_draw()
            # convenção X11: seleção também vai pro PRIMARY (colar com o
            # botão do meio), sem precisar do Ctrl+Shift+C
            self.copy(Gdk.SELECTION_PRIMARY)
            return True
        return False

    def on_motion(self, widget, ev):
        t = self.term
        self._state = ev.state
        if self.dragging:
            col, row = self.cell_at(ev.x, ev.y)
            if (row, col) != self.sel_end:
                self.sel_end = (row, col)
                self.area.queue_draw()
            return True
        if t.mouse_mode == 2 and self._held is not None:
            self.report_mouse(self._held, *self.cell_at(ev.x, ev.y),
                              motion=True)
            return True
        if t.mouse_mode == 3:
            # movimento sem botão: código 35 (32 + "botão 3")
            self.report_mouse(mouse.RELEASE, *self.cell_at(ev.x, ev.y),
                              motion=True)
            return True
        return False

    def on_scroll(self, widget, ev):
        t = self.term
        self._state = ev.state
        btn = {Gdk.ScrollDirection.UP: mouse.WHEEL_UP,
               Gdk.ScrollDirection.DOWN: mouse.WHEEL_DOWN,
               Gdk.ScrollDirection.LEFT: mouse.WHEEL_LEFT,
               Gdk.ScrollDirection.RIGHT: mouse.WHEEL_RIGHT}.get(ev.direction)
        if btn is None:
            return False
        back = btn in (mouse.WHEEL_UP, mouse.WHEEL_LEFT)
        # lendo histórico: o wheel continua rolando a visão, não vai pro app
        if self.view_off or not t.mouse_mode:
            return self.scroll_view(3 if back else -3)
        col, row = self.cell_at(ev.x, ev.y)
        self.report_mouse(btn, col, row, True)
        self.report_mouse(btn, col, row, False)
        return True

    def on_focus_in(self, widget, ev):
        if self.term.focus_report:
            self._write_child("\x1b[I")
        return False

    def on_focus_out(self, widget, ev):
        if self.term.focus_report:
            self._write_child("\x1b[O")
        return False

    # -- área de transferência ----------------------------------------
    def copy(self, selection=Gdk.SELECTION_CLIPBOARD):
        """Copia a seleção — ou a viewport inteira, se não houver seleção."""
        rows = self.visible_rows()
        sel = self.sel_range()
        if sel:
            r1, c1, r2, c2 = sel
            text = self.term.selection_text((r1, c1), (r2, c2), rows=rows)
            if text:
                text += "\n"          # seleção de linha inteira já vem sem
        else:
            text = self.term.all_text(rows=rows)
        cb = Gtk.Clipboard.get(selection)
        cb.set_text(text, -1)
        cb.store()
        return text

    def paste(self, selection=Gdk.SELECTION_CLIPBOARD):
        text = Gtk.Clipboard.get(selection).wait_for_text()
        if text:
            self._write_child(text)
        return bool(text)

    # -- teclado -------------------------------------------------------
    def on_key(self, widget, ev):
        """Traduz e manda a tecla; a tradução em si está em keys.encode_key."""
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        kv = ev.keyval
        # Ctrl+Shift+C/V são do terminal, não do app (senão Ctrl+Shift+C
        # virava o mesmo ^C de Ctrl+C e matava o processo)
        if ctrl and shift and kv in (Gdk.KEY_c, Gdk.KEY_C):
            self.copy()
            return True
        if ctrl and shift and kv in (Gdk.KEY_v, Gdk.KEY_V):
            self.paste()
            return True
        # Shift+PgUp/PgDn/Home/End olham o histórico (P2) sem falar com o app
        if shift and kv == Gdk.KEY_Page_Up:
            return self.scroll_view(self.term.rows - 1)
        if shift and kv == Gdk.KEY_Page_Down:
            return self.scroll_view(-(self.term.rows - 1))
        if shift and kv == Gdk.KEY_Home and self.term.scrollback:
            return self.scroll_view(len(self.term.scrollback))
        if shift and kv == Gdk.KEY_End:
            return self.scroll_view(-len(self.term.scrollback))
        if self.view_off and not is_modifier(kv):
            # tecla de verdade volta pro vivo (a tecla também vai pro app);
            # só modificador não, senão o Shift do Shift+PgUp já resetava
            self.back_to_live()
        out, self.dead_mark, handled = encode_key(
            ev.keyval, ev.state, self.dead_mark, self.term.app_cursor)
        self._write_child(out or "")
        return handled
