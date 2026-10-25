"""A view de uma sessão: pty, desenho em cairo e eventos de input.

Era o `PyTermWindow` inteiro até o P11 (abas): o que é por-aba veio pra cá, e
`window.py` ficou com a janela — `Gtk.Notebook`, atalhos globais e o ciclo de
vida das abas. Continua sendo a única camada que desenha; o estado do
terminal está em `term`.
"""

import codecs
import io
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
from .palette import (DEF_FG, DEF_BG, BOLD, UL, INV, BG_DEFAULT, FG_DEFAULT,
                      cell_rgb)
from .term import Term


def surface_from_image(img, cairo):
    """Image do protocolo de gráficos -> cairo.ImageSurface.

    Devolve `(surface, keepalive)`: o cairo NÃO copia os dados de
    `create_for_data`, então o bytearray tem que continuar vivo — quem chama
    guarda o segundo item da tupla.
    """
    if img.fmt == 100:                       # PNG: o cairo lê direto
        return cairo.ImageSurface.create_from_png(io.BytesIO(img.data)), None
    w, h = img.width, img.height
    src = img.data
    n = 4 if img.fmt == 32 else 3
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, w)
    buf = bytearray(stride * h)
    for y in range(h):
        si = y * w * n
        oi = y * stride
        for _ in range(w):
            # ARGB32 do cairo é BGRA nesta ordem de bytes (little-endian)
            buf[oi] = src[si + 2]
            buf[oi + 1] = src[si + 1]
            buf[oi + 2] = src[si]
            buf[oi + 3] = src[si + 3] if n == 4 else 255
            si += n
            oi += 4
    surf = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, w, h,
                                              stride)
    return surf, buf


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


class TermView(Gtk.DrawingArea):
    """Uma sessão: pty + grade + seleção + histórico + desenho.

    Tudo que é por-aba mora aqui. A janela só empilha views num `Gtk.Notebook`
    (P11) e trata os atalhos globais; com workspaces (P12) cada workspace tem
    o seu notebook.
    """

    def __init__(self, cmd=None, cwd=None, font_size=16, on_exit=None,
                 on_title=None, shortcuts=None):
        super().__init__()
        self.on_exit = on_exit        # chamada quando o shell sai
        self.on_title = on_title      # chamada quando o título (OSC) muda
        self.shortcuts = shortcuts    # atalhos da janela (prioridade)
        self._title = "pyterm"
        self.app_title = False        # o app já mandou OSC 0/2?
        self.start_cwd = cwd or os.getcwd()
        self._notified = False
        self.dead_mark = 0            # dead key pendente (marca combinante)
        self.term = Term()
        # seleção local (quando o app NÃO pediu mouse): âncora e ponta
        self.sel_start = None
        self.sel_end = None
        self.dragging = False
        self._held = None             # botão do protocolo apertado agora
        self._state = 0               # modificadores do último evento
        self.view_off = 0             # 0 = vivo; >0 = linhas de histórico
        self._img_cache = {}          # id da imagem -> (surface, keepalive)

        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK |
                        Gdk.EventMask.SCROLL_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_button_press)
        self.connect("button-release-event", self.on_button_release)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("scroll-event", self.on_scroll)
        self.connect("key-press-event", self.on_key)
        self.connect("key-release-event", self.on_key_release)
        # size-allocate (e não configure-event): o configure do GtkWindow
        # chega ANTES do filho ser re-alocado, então get_allocation() ali
        # ainda devolve o tamanho antigo e o resize nunca era aplicado.
        self.connect("size-allocate", self.on_resize)
        self.font_size = font_size
        self._metrics = None

        self.master = None
        self.child_pid = None
        self.child_exited = False     # waitpid já chegou?
        self.exit_code = None
        self.pty_watch = 0
        self._closing = False
        self._hungup = False
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.spawn(cmd or os.environ.get("SHELL", "/bin/bash"), cwd)

    def spawn(self, cmd, cwd=None):
        pid, fd = pty.fork()
        if pid == 0:
            # Herança de disposição de sinal é uma armadilha: o `run.sh` sobe
            # com `nohup` (SIGHUP ignorado) e o Python ignora SIGPIPE — o
            # filho herdava os dois. Com SIGHUP ignorado o hangup do grupo
            # não matava job nenhum; com SIGPIPE ignorado, `seq 1 100000 |
            # head -3` não parava no pipe quebrado. Volta tudo ao default.
            for sig in (signal.SIGHUP, signal.SIGPIPE, signal.SIGINT,
                        signal.SIGQUIT, signal.SIGTERM):
                try:
                    signal.signal(sig, signal.SIG_DFL)
                except (OSError, ValueError):
                    pass
            if cwd:
                try:
                    os.chdir(cwd)
                except OSError:
                    pass        # cwd do filho pode ter sido apagado
            os.environ["TERM"] = "xterm-256color"
            try:
                os.execlp("sh", "sh", "-c", cmd)
            except Exception:
                os._exit(127)
        self.child_pid = pid
        self.master = fd
        os.set_blocking(fd, False)
        self.pty_watch = GLib.io_add_watch(fd, GLib.IO_IN | GLib.IO_HUP |
                                          GLib.IO_ERR, self.on_pty)
        # O EOF do pty NÃO é sinal confiável de que o shell morreu: no Linux
        # o master devolve EIO, o watch morre e o loop do Gtk segue vivo (a
        # janela ficava aberta depois do Ctrl+D). O sinal de verdade é o
        # waitpid — o GLib reapa e entrega o status aqui.
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, pid, self.on_child_exit)

    def on_pty(self, fd, cond):
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            return True
        except OSError:
            # EIO = todo mundo fechou o lado escravo (o shell saiu). Se o
            # waitpid ainda não chegou, espera ele; senão fecha já.
            self.pty_watch = 0
            if self.child_exited:
                self._notify_exit()
            return False
        if not data:
            self.pty_watch = 0
            if self.child_exited:
                self._notify_exit()
            return False
        if os.environ.get("PYTERM_RAWLOG"):
            with open(os.environ["PYTERM_RAWLOG"], "ab") as f:
                f.write(data)
        self.term.feed(self.decoder.decode(data))
        # respostas do núcleo (DA/CPR) voltam ao filho
        if self.term.child_out:
            try:
                os.write(fd, bytes(self.term.child_out))
            except OSError:
                pass
            self.term.child_out = bytearray()
        if self.term.title != self._title:
            self._title = self.term.title
            self.app_title = self._title != "pyterm"
            if self.on_title:
                self.on_title(self, self._title)
        # output novo volta pro vivo (é o que todo terminal faz: o app está
        # falando, o usuário não está mais lendo o histórico)
        if self.view_off:
            self.view_off = 0
        self.queue_draw()
        return True

    def on_child_exit(self, pid, status):
        """O shell morreu (o GLib já reapou — NÃO chamar waitpid de novo)."""
        try:
            self.exit_code = os.waitstatus_to_exitcode(status)
        except (AttributeError, ValueError):
            self.exit_code = None
        self.child_exited = True
        self._drain_pty()     # não perder o último output (logout, msg de erro)
        # fechar a ABA manda SIGHUP no filho: aí o "código -1" é nosso, não
        # notícia (só interessa a saída que o usuário pediu)
        if self.exit_code and not self._closing:
            print(f"pyterm: shell saiu com código {self.exit_code}",
                  file=sys.stderr)
        self._notify_exit()
        return False          # remove o child watch

    def _drain_pty(self):
        """Lê o que sobrou no master sem bloquear (fd é non-blocking)."""
        if self.master is None:
            return
        for _ in range(64):   # teto: filho mal comportado não trava a saída
            try:
                data = os.read(self.master, 65536)
            except (BlockingIOError, InterruptedError, OSError):
                break
            if not data:
                break
            self.term.feed(self.decoder.decode(data))
            if self.term.child_out:
                try:
                    os.write(self.master, bytes(self.term.child_out))
                except OSError:
                    pass
                self.term.child_out = bytearray()

    def shutdown(self):
        """Fecha a sessão (aba fechada, shell saiu, --quit-after)."""
        if self._closing:
            return
        self._closing = True
        if self.pty_watch:
            GLib.source_remove(self.pty_watch)
            self.pty_watch = 0
        self._hangup()
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass
            self.master = None

    def _notify_exit(self):
        """Avisa a janela UMA vez que a sessão acabou."""
        if self._notified:
            return
        self._notified = True
        if self.on_exit:
            self.on_exit(self)

    def _hangup(self):
        """SIGHUP no grupo do filho: o `pty.fork` fez dele líder de sessão.

        Sem isso, netos do shell (jobs em background, `tail -f`) ficavam
        órfãos segurando o pty quando a janela fechava.
        """
        if not self.child_pid or self._hungup:
            return
        self._hungup = True    # _close() e on_destroy() chamam os dois
        try:
            os.killpg(self.child_pid, signal.SIGHUP)
        except OSError:
            pass              # grupo já não existe: shell saiu sozinho

    def dump_text(self):
        """Texto do dump (SIGUSR1 / saída) desta sessão."""
        t = self.term
        lines = []
        if t.scrollback:
            lines.append(f"=== scrollback ({len(t.scrollback)}) ===")
            for row in t.scrollback[-40:]:
                lines.append("".join(c[0] for c in row).rstrip())
        lines.append(f"=== viewport {t.cols}x{t.rows} ===")
        for y in range(t.rows):
            lines.append(t.row_text(y).rstrip())
        if t.graphics.placements or t.graphics.images:
            lines.append(f"=== imagens: {len(t.graphics.images)} guardadas, "
                         f"{len(t.graphics.placements)} na tela ===")
            for pl in t.graphics.placements:
                img = t.graphics.images.get(pl.image_id)
                lines.append(f"  id={pl.image_id} em ({pl.col},{pl.row}) "
                             f"{pl.cols}x{pl.rows} "
                             f"+{pl.dx},{pl.dy}px "
                             f"fmt={img.fmt if img else '-'}")
        lines.append(f"=== cursor {t.cx},{t.cy} ===")
        return "\n".join(lines)

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
        self.term.cell_size = self._metrics   # o protocolo de imagem usa isso
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
            self.queue_draw()
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
            self.queue_draw()
        return True

    def back_to_live(self):
        if self.view_off:
            self.view_off = 0
            self.queue_draw()

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
        # sobra sub-célula: quase nunca a janela é múltiplo exato de (cw, ch).
        # A faixa que sobra embaixo/à direita pertence à última fileira/coluna
        # e recebe o fundo DELA, senão um app com fundo colorido (vim com
        # termguicolors, htop) ganha um rodapé preto.
        og_w = self.get_allocated_width()
        og_h = self.get_allocated_height()
        last_y = len(rows) - 1
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
                fgc = cell_rgb(fg, FG_DEFAULT)
                bgc = cell_rgb(bg, BG_DEFAULT)
                if (fl & INV) or s0:
                    fgc, bgc = bgc, fgc      # inverso / seleção = reverso
                if bgc != BG_DEFAULT:
                    cr.set_source_rgb(*[c / 255 for c in bgc])
                    rw = (og_w if j >= t.cols else j * cw) - x * cw
                    rh = max(ch, og_h - y * ch) if y == last_y else ch
                    cr.rectangle(x * cw, y * ch, rw, rh)
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
        # imagens do protocolo de gráficos (P6), por cima do texto e abaixo
        # do cursor — é onde o kitty põe
        for pl in t.graphics.placements:
            img = t.graphics.images.get(pl.image_id)
            # No histórico a tela deslizou `view_off` linhas pra dentro do
            # scrollback: a colocação vive em coordenadas da GRADE, então a
            # linha na tela é `row + view_off` (sem isso a imagem ficava
            # parada enquanto o texto rolava por baixo dela).
            vr = pl.row + self.view_off
            if img is None or pl.col >= t.cols or vr < 0 or vr >= t.rows:
                continue
            entry = self._img_cache.get(pl.image_id)
            if entry is None:
                try:
                    entry = surface_from_image(img, cairo)
                except Exception:
                    continue
                self._img_cache[pl.image_id] = entry
            surf = entry[0]
            w = max(1, pl.cols) * cw
            h = max(1, pl.rows) * ch
            x0 = pl.col * cw + pl.dx     # X=/Y=: offset em pixels (centralização)
            y0 = vr * ch + pl.dy
            cr.save()
            cr.rectangle(x0, y0, w, h)
            cr.clip()
            cr.translate(x0, y0)
            cr.scale(w / max(1, surf.get_width()), h / max(1, surf.get_height()))
            cr.set_source_surface(surf, 0, 0)
            cr.paint()
            cr.restore()

        # cursor bloco — só no vivo: no histórico o cursor do app não está ali
        if (self.view_off == 0 and t.cursor_visible
                and t.cy < t.rows and t.cx < t.cols):
            cr.set_source_rgb(*[c / 255 for c in FG_DEFAULT])
            cr.rectangle(t.cx * cw, t.cy * ch, cw, ch)
            cr.fill()
            cell = t.grid[t.cy][t.cx]
            bgc = cell_rgb(cell[2], BG_DEFAULT)
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
            self.queue_draw()
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
            self.queue_draw()
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
                self.queue_draw()
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
            # Sem `+ "\n"`: o kitty só junta as linhas com "\n" ENTRE elas, e
            # o fim de linha entra quando o arrasto chega na coluna 0 da linha
            # seguinte (aí a última "linha" da seleção é vazia). O newline
            # incondicional fazia colar "abcdef" executar `abcdef`.
            text = self.term.selection_text((r1, c1), (r2, c2), rows=rows)
        else:
            text = self.term.all_text(rows=rows)
        cb = Gtk.Clipboard.get(selection)
        cb.set_text(text, -1)
        cb.store()
        return text

    def paste(self, selection=Gdk.SELECTION_CLIPBOARD):
        text = Gtk.Clipboard.get(selection).wait_for_text()
        if text:
            self._write_child(self.term.paste_payload(text))
        return bool(text)

    # -- teclado -------------------------------------------------------
    def on_key(self, widget, ev):
        """Traduz e manda a tecla; a tradução em si está em keys.encode_key."""
        # atalhos da JANELA (abas/workspaces) antes do app: o filho nunca vê
        # Ctrl+Shift+T/W nem Alt+N, senão a tecla morre no app em tela cheia
        if self.shortcuts is not None and self.shortcuts(ev):
            return True
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
            ev.keyval, ev.state, self.dead_mark, self.term.app_cursor,
            self.term.kbd_flags, text=ev.string or "")
        self._write_child(out or "")
        return handled

    def on_key_release(self, widget, ev):
        """Só existe release com a flag `report event types` (P5)."""
        if not (self.term.kbd_flags & 2):
            return False
        out, _, handled = encode_key(
            ev.keyval, ev.state, 0, self.term.app_cursor,
            self.term.kbd_flags, event=3)
        self._write_child(out or "")
        return handled
