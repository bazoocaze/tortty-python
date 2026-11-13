"""A view de uma sessão: pty, desenho em cairo e eventos de input.

Era o `TorttyWindow` inteiro até o P11 (abas): o que é por-aba veio pra cá, e
`window.py` ficou com a janela — `Gtk.Notebook`, atalhos globais e o ciclo de
vida das abas. Continua sendo a única camada que desenha; o estado do
terminal está em `term`.
"""

import codecs
import io
import json
import math
import os
import pty
import signal
import struct
import subprocess
import sys
import termios
import time

from . import mouse
from .config import tab_command
from .gui import Gdk, GLib, Gtk, Pango, PangoCairo, cairo
from .keys import encode_key, is_modifier
from .palette import (
    BLINK,
    BOLD,
    DEF_BG,
    DEF_FG,
    DIM,
    HIDDEN,
    INV,
    ITALIC,
    OVERLINE,
    STRIKE,
    UL,
    UL_CURLY,
    UL_DASHED,
    UL_DOTTED,
    UL_DOUBLE,
    UL_MASK,
    ul_style,
)
from .term import DEFAULT_TITLE, CellAnchor, Term, link_allowed, shell_quoted

_PROF = bool(os.environ.get("PYTERM_PROF"))  # mede o custo de draw e de pty
_NODRAW = bool(os.environ.get("PYTERM_NODRAW"))  # sonda: só pty -> grade, sem desenho
_NOPARSE = bool(os.environ.get("PYTERM_NOPARSE"))  # sonda: só lê o pty e descarta
_DEBUG_LOG = None  # log JSONL do ?2026 x scroll; None = desligado (B22)
_SYNC_MS = 200  # teto da transação ?2026: app que esquece de fechar não congela
UL_BITS = UL | UL_MASK  # presença + estilo do sublinhado, como vai para o run
# o que o run carrega de decoração: sublinhado (+ estilo), riscado e sobrelinha
DECO_BITS = UL_BITS | STRIKE | OVERLINE


def set_prof(on):
    """Liga/desliga a medição de custo em execução (verbo `prof` do socket)."""
    global _PROF
    _PROF = bool(on)


def set_debug_log(path):
    """Liga o log de depuração do ?2026 no caminho dado; None desliga."""
    global _DEBUG_LOG
    _DEBUG_LOG = path or None


def _slog(**ev):
    """Uma linha JSONL no log de depuração do ?2026 (B22)."""
    if not _DEBUG_LOG:
        return
    ev["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + ".%03d" % (
        int((time.time() % 1) * 1000)
    )
    try:
        with open(_DEBUG_LOG, "a") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except OSError:
        pass


DRAG_SLOP = 3  # px de folga: abaixo disso o mouse não "arrastou"
SB_W = 8  # largura da barra de rolagem, em px (o app testa o mesmo número)
CLICK_MS = 400  # janela do duplo/triplo clique, em ms
BLINK_MS = 530  # ritmo do cursor piscando (`cursor_blink`); não é opção
CELL_BLINK_MS = 500  # ritmo do SGR 5/6 (P66): timer próprio, não o do cursor


def _tick(prof, name, t0):
    """Acumula (chamadas, segundos) de uma etapa; só faz algo com PYTERM_PROF."""
    if _PROF:
        st = prof.setdefault(name, [0, 0.0])
        st[0] += 1
        st[1] += time.perf_counter() - t0


def surface_from_image(img, cairo):
    """Image do protocolo de gráficos -> cairo.ImageSurface.

    Devolve `(surface, keepalive)`: o cairo NÃO copia os dados de
    `create_for_data`, então o bytearray tem que continuar vivo — quem chama
    guarda o segundo item da tupla.
    """
    if img.fmt == 100:  # PNG: o cairo lê direto
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
    surf = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, w, h, stride)
    return surf, buf


def _in_block(y, x, b):
    """A célula (y, x) está dentro do bloco (r1, c1, r2, c2)? (P61)

    Diferente de `_in_sel`, as colunas valem em TODA linha do intervalo — é o
    que faz a coluna de uma tabela sair inteira.
    """
    return b[0] <= y <= b[2] and b[1] <= x <= b[3]


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

    def __init__(
        self,
        cmd=None,
        cwd=None,
        shell=None,
        font_family="Monospace",
        font_size=12,
        font_features="",
        padding=0,
        cursor_shape="block",
        cursor_blink=False,
        copy_on_select=False,
        bold_as_bright=False,
        letter_spacing=0,
        scrollback=1000,
        colors=None,
        on_exit=None,
        on_title=None,
        on_bell=None,
        on_notify=None,
        on_progress=None,
        on_context=None,
        shortcuts=None,
    ):
        super().__init__()
        self.on_exit = on_exit  # chamada quando o shell sai
        self.on_title = on_title  # chamada quando o título (OSC) muda
        self.on_bell = on_bell  # chamada quando o app manda BEL (P34)
        self.on_notify = on_notify  # chamada no `OSC 9`/`777` (P44)
        self.on_progress = on_progress  # chamada no `OSC 9;4` (P65)
        self.on_context = on_context  # botão direito: menu do window (P71)
        self.shortcuts = shortcuts  # atalhos da janela (prioridade)
        self.font_features = font_features  # liga/calt do Pango (P45)
        self._notifs = 0  # `OSC 9`/`777` já entregues ao host (P44)
        self._progress = None  # último `OSC 9;4` já entregue ao host (P65)
        self._clip_seq = 0  # `OSC 52` já entregue ao clipboard (P64)
        self._cwd = None  # último `OSC 7` já refletido no rótulo (P47)
        self._title = DEFAULT_TITLE
        self.app_title = False  # o app já mandou OSC 0/2?
        self.start_cwd = cwd or os.getcwd()
        self._notified = False
        self.dead_mark = 0  # dead key pendente (marca combinante)
        self.term = Term()
        self.term.set_scrollback(scrollback)
        self.term.theme.apply_colors(colors or {})  # P49: as 19 chaves
        # seleção local (quando o app NÃO pediu mouse): âncora e ponta em
        # coordenada ABSOLUTA (`CellAnchor`), senão o realce fica preso na
        # posição de tela quando o conteúdo rola (B17)
        self.sel_start = None
        self.sel_end = None
        self.sel_block = False  # P61: Alt+arrasto = bloco (colunas fixas)
        self.press_anchor = None  # célula do press: a seleção nasce no arrasto
        self.press_at = None  # pixel do press: a folga de arrasto é medida nele
        self.dragging = False
        self._held = None  # botão do protocolo apertado agora
        self._click = (0, 0, -1, -1)  # (time, botão, fileira, coluna) do último clique
        self._click_n = 0  # 1 clique, 2 palavra, 3 linha lógica
        self._press_time, self._press_xy = 0, (-1.0, -1.0)  # press já tratado
        self._wheel_v = mouse.Notches()  # fração do touchpad no eixo vertical (P48)
        self._sb_drag = False  # arrastando o polegar da barra de rolagem
        self._sb_hover = False  # ponteiro sobre a barra (P67)
        self._ctrl = False  # Ctrl apertado: sublinha os hyperlinks (OSC 8)
        self._hover_link = None  # link sob o ponteiro: sublinha sem Ctrl (P70)
        self._hover_cell = (-1, -1)  # última célula visitada (só redesenha ao trocar)
        self._state = 0  # modificadores do último evento
        self.view_off = 0  # 0 = vivo; >0 = linhas de histórico
        self._anchor = 0  # linha absoluta no topo da visão quando no histórico
        self._hist_gen = 0  # geração do histórico que a visão já viu
        self._pin_off = 0  # distância do vivo a segurar depois de um `CSI 3J`
        self._img_cache = {}  # id da imagem -> (surface, keepalive)

        self.set_can_focus(True)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.SCROLL_MASK
        )
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_button_press)
        self.connect("button-release-event", self.on_button_release)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("leave-notify-event", self._on_leave)
        self.connect("scroll-event", self.on_scroll)
        self.connect("key-press-event", self.on_key)
        self.connect("key-release-event", self.on_key_release)
        # aba oculta não pisca: o Gtk.Notebook desmapeia a página que sai
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        # size-allocate (e não configure-event): o configure do GtkWindow
        # chega ANTES do filho ser re-alocado, então get_allocation() ali
        # ainda devolve o tamanho antigo e o resize nunca era aplicado.
        self.connect("size-allocate", self.on_resize)
        self.font_family = font_family
        self.font_size = font_size
        self.padding = padding  # margem em volta da grade, em px (P34)
        self.cursor_shape = cursor_shape
        self.cursor_blink = cursor_blink
        self.copy_on_select = copy_on_select
        self.bold_as_bright = bold_as_bright  # P64: SGR 1 em 0..7 vira brilhante
        self.letter_spacing = letter_spacing  # px extra na célula (P64)
        self._blink_on = True  # fase do pisca: True = cursor aparece nela
        self._blink_timer = 0
        self._cell_on = True  # fase do SGR 5/6: True = a célula aparece nela
        self._cell_timer = 0
        self._metrics = None
        self._font_desc = None  # Pango.FontDescription (P9)
        self._attrs = [None] * 4  # Pango.AttrList por (negrito, itálico)
        self._advance = None  # avanço real da fonte, em px (float)
        self._dpi = None  # resolução do display (Xft.dpi)
        # cache de layout: texto -> (layout, linha, base), uma tabela por
        # (negrito, itálico) — evita alocar a tupla em cada run (P37)
        self._layouts = ({}, {}, {}, {})

        self.master = None
        self.child_pid = None
        self.child_exited = False  # waitpid já chegou?
        self.exit_code = None
        self._draw_pending = False
        self._cursor_drawn = (0, 0)  # cursor do último draw (linha vai no dano)
        self._sync_timer = 0  # teto da transação de synchronized output
        self._sync_t0 = None  # monotonic da abertura da região (ms no fecho)
        self._prof = {}
        self._prof_bytes = 0  # bytes lidos do master (o que o filho escreveu)
        self._prof_eagain = 0  # BlockingIOError: watch sem byte disponível
        self.pty_watch = 0
        self._closing = False
        self._hungup = False
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        # o SHELL do filho é o que roda de fato (config, senão $SHELL), não o
        # herdado do processo que abriu o tortty_python; com `--cmd`, o comando é outro
        # e o SHELL continua sendo o da config
        cmd, self.shell = tab_command(cmd, shell)
        self.spawn(cmd, cwd)

    def spawn(self, cmd, cwd=None):
        pid, fd = pty.fork()
        if pid == 0:
            # Herança de disposição de sinal é uma armadilha: o debug.sh sobe
            # com `nohup` (SIGHUP ignorado) e o Python ignora SIGPIPE — o
            # filho herdava os dois. Com SIGHUP ignorado o hangup do grupo
            # não matava job nenhum; com SIGPIPE ignorado, `seq 1 100000 |
            # head -3` não parava no pipe quebrado. Volta tudo ao default.
            for sig in (
                signal.SIGHUP,
                signal.SIGPIPE,
                signal.SIGINT,
                signal.SIGQUIT,
                signal.SIGTERM,
            ):
                try:
                    signal.signal(sig, signal.SIG_DFL)
                except (OSError, ValueError):
                    pass
            if cwd:
                try:
                    os.chdir(cwd)
                except OSError:
                    pass  # cwd do filho pode ter sido apagado
            os.environ["TERM"] = "xterm-256color"
            # sem COLORTERM o app acha que só há 256 cores e arredonda o RGB
            # para o cubo: era isto que fazia cor "não bater" com o kitty
            os.environ["COLORTERM"] = "truecolor"
            os.environ["SHELL"] = self.shell
            try:
                os.execlp("sh", "sh", "-c", cmd)
            except Exception:
                os._exit(127)
        self.child_pid = pid
        self.master = fd
        os.set_blocking(fd, False)
        # Prioridade DEFAULT_IDLE (200), não DEFAULT (0): o redraw do GDK roda
        # em GDK_PRIORITY_REDRAW (120) e um pty sempre pronto em prioridade 0
        # ganhava a disputa sempre — com despejo contínuo a tela congelava no
        # último frame desenhado (bug do doom-fire)
        self.pty_watch = GLib.io_add_watch(
            fd,
            GLib.PRIORITY_DEFAULT_IDLE,
            GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
            self.on_pty,
        )
        # O EOF do pty NÃO é sinal confiável de que o shell morreu: no Linux
        # o master devolve EIO, o watch morre e o loop do Gtk segue vivo (a
        # janela ficava aberta depois do Ctrl+D). O sinal de verdade é o
        # waitpid — o GLib reapa e entrega o status aqui.
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, pid, self.on_child_exit)

    def request_draw(self):
        """Pede um desenho, no máximo um a cada ~16 ms (60 Hz).

        `queue_draw` a cada leitura de pty dava dezenas de draws por frame sob
        despejo contínuo: o custo do desenho passava a dominar a vazão e a tela
        ainda congelava, porque o redraw do GDK tem prioridade MENOR que o
        watch do pty. Agora o desenho é coalescido e ritmado.
        """
        if _NODRAW:  # sonda de medição: mede só o caminho pty -> grade
            return
        if self.term.sync_output:
            # ?2026 aberto: o app ainda vai redesenhar. Desenhar agora mostra
            # o meio de cada repaint (é o que faz a tela parecer pular
            # várias telas); segura até o fecho, com teto de segurança.
            self._defer_draw()
            return
        if self._sync_timer:
            GLib.source_remove(self._sync_timer)
            self._sync_timer = 0
        if self._draw_pending:
            return
        self._draw_pending = True
        GLib.timeout_add(16, self._flush_draw)

    def _sync_flush(self):
        """Estourou o teto do ?2026: desenha assim mesmo."""
        self._sync_timer = 0
        self._draw_pending = False
        self._queue_damage()
        return False

    def _defer_draw(self):
        """Adia o desenho até o fecho do ?2026 (ou até o teto de segurança)."""
        if not self._sync_timer:
            self._sync_timer = GLib.timeout_add(_SYNC_MS, self._sync_flush)

    def _flush_draw(self):
        self._draw_pending = False
        if self.term.sync_output:
            self._defer_draw()  # a transação abriu depois do agendamento
            return False
        self._queue_damage()
        return False  # um tiro só

    def _queue_damage(self):
        """Pede só as linhas que o app sujou, não a grade inteira (P27).

        Trocar um caractere (o spinner do pi) custava o mesmo que repintar a
        tela toda: 13,7 ms em 61x18, porque o laço do draw varria as 18 linhas
        e todos os runs. Com o dano do Term viram região do Gdk, e o draw
        respeita o clip: o mesmo spinner desce para o custo de uma linha.
        """
        t = self.term
        rows = t.take_damage()
        if (
            rows is None  # rolagem, resize, RIS, troca de buffer
            or self.view_off  # histórico: o que está na tela não é a grade
            or t.sync_output  # transação aberta: quem manda é o fecho
            or t.graphics.placements  # imagem: o laço de imagens é da grade
        ):
            self._cursor_drawn = (t.cx, t.cy)
            self.queue_draw()
            return
        rows.add(t.cy)  # o cursor sai e volta: as duas linhas mudam
        rows.add(self._cursor_drawn[1])
        self._cursor_drawn = (t.cx, t.cy)
        cw, ch = self.metrics()
        cw, ch = int(cw), int(ch)
        p = self.padding
        larg = max(1, self.get_allocated_width() - 2 * p)
        # linhas vizinhas viram UMA área: um spinner é 1 retângulo só
        linhas = sorted(y for y in rows if 0 <= y < t.rows)
        i = 0
        while i < len(linhas):
            j = i + 1
            while j < len(linhas) and linhas[j] == linhas[j - 1] + 1:
                j += 1
            self.queue_draw_area(p, linhas[i] * ch + p, larg, (j - i) * ch)
            i = j

    def on_pty(self, fd, cond):
        if not _PROF:
            return self._on_pty(fd, cond)
        t0 = time.perf_counter()
        try:
            return self._on_pty(fd, cond)
        finally:
            _tick(self._prof, "pty", t0)

    def _on_pty(self, fd, cond):
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            if _PROF:
                self._prof_eagain += 1  # watch disparou sem byte: mede o giro
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
        if _PROF:
            self._prof_bytes += len(data)  # tem que casar com o que o filho escreveu
        if _NOPARSE:  # sonda: mede só read do pty, sem decode/parse/grade
            return True
        # enquanto o usuário lê o histórico, a visão fica ancorada na linha em
        # que ele parou (P32): o app pode escrever à vontade que o texto lido
        # não sai do lugar. Só tecla, rolar até o fim ou limpeza do histórico
        # (aí o clamp devolve o vivo) tira ele de lá.
        scrolled_before = self.term.scrolled
        was_sync = self.term.sync_output
        self.term.feed(self.decoder.decode(data))
        if self.term.sync_output != was_sync:
            ev = {
                "ev": "2026",
                "on": self.term.sync_output,
                "v": self.view_off,
                "pin": self._pin_off,
                "sb": len(self.term.scrollback),
                "scr": self.term.scrolled,
                "gen": self.term.hist_gen,
            }
            if self.term.sync_output:
                self._sync_t0 = time.monotonic()
            elif self._sync_t0 is not None:
                ev["ms"] = round((time.monotonic() - self._sync_t0) * 1000)
                self._sync_t0 = None
            _slog(**ev)
        # respostas do núcleo (DA/CPR) voltam ao filho
        if self.term.child_out:
            try:
                os.write(fd, bytes(self.term.child_out))
            except OSError:
                pass
            self.term.child_out = bytearray()
        if self.term.title != self._title:
            self._title = self.term.title
            self.app_title = self._title != DEFAULT_TITLE
            if self.on_title:
                self.on_title(self, self._title)
        # output que mexe na tela volta pro vivo (o app está falando, o usuário
        # não está mais lendo o histórico); output invisível não arranca o
        # usuário de onde ele está — senão qualquer tique de 1 Hz do app joga a
        # visão pro rodapé e torna o histórico inutilizável
        jump = self.term.scrolled - scrolled_before
        log = os.environ.get("PYTERM_SCROLLLOG")
        if log and jump > max(2, self.term.rows // 2):
            fmt = "jump=%d rows=%d top=%d bottom=%d alt=%s bytes=%d t=%.3f\n  %r\n"
            with open(log, "a") as f:
                f.write(
                    fmt
                    % (
                        jump,
                        self.term.rows,
                        self.term.top,
                        self.term.bottom,
                        self.term.alt_grid is not None,
                        len(data),
                        time.time(),
                        data[:600],
                    )
                )
        v_before = self.view_off
        if self.term.hist_gen != self._hist_gen:
            # `CSI 3J`: o histórico acabou (o repaint do pi começa assim). A
            # âncora absoluta morre, mas a distância do vivo ainda vale — quem
            # rolou quer continuar lendo, não voltar pro topo nem pro vivo
            self._hist_gen = self.term.hist_gen
            if self.view_off:
                self._pin_off = self.view_off
        # `?2026` aberto: o app está reescrevendo o histórico agora e o parcial
        # não vale como referência (B22) — nem o vivo (`min(pin, 0)` no `3J`)
        # nem a escalada enquanto o histórico cresce. A posição fica onde
        # estava; quem resolve é o chunk do fecho, com o buffer completo, e o
        # `_pin_off` guardado no `3J` segue valendo até lá.
        if not self.term.sync_output:
            if self._pin_off:
                off = self.term.pinned_view_off(self._pin_off)
                self.view_off = off
                self._anchor = self.term.scrolled - off
                if off >= self._pin_off:
                    self._pin_off = 0  # chegou na distância: volta ao modo âncora
            elif self.view_off:
                self.view_off = self.term.anchored_view_off(self._anchor)
        if self.term.sync_output and self.view_off != v_before:
            _slog(
                ev="pos",
                v0=v_before,
                v1=self.view_off,
                pin=self._pin_off,
                sb=len(self.term.scrollback),
                scr=self.term.scrolled,
            )
        if self.term.bells:  # BEL: a janela decide visual/audível (P34)
            self.term.bells = 0
            if self.on_bell:
                self.on_bell(self)
        if self.term.notifs != self._notifs:  # `OSC 9`/`777` (P44)
            self._notifs = self.term.notifs
            if self.on_notify:
                self.on_notify(self, self.term.notif_text)
        if self.term.progress != self._progress:  # `OSC 9;4` (P65)
            self._progress = self.term.progress
            if self.on_progress:
                self.on_progress(self, self._progress)
        if self.term.cwd != self._cwd:  # `OSC 7` (P47): o cwd do shell mudou
            self._cwd = self.term.cwd
            if self.on_title:  # o rótulo sem OSC 0/2 é o cwd
                self.on_title(self, self._title)
        if self.term.clip_seq != self._clip_seq:  # `OSC 52` (P64): clipboard
            self._clip_seq = self.term.clip_seq
            sel = (
                Gdk.SELECTION_PRIMARY
                if self.term.clip_sel == "primary"
                else Gdk.SELECTION_CLIPBOARD
            )
            cb = Gtk.Clipboard.get(sel)
            cb.set_text(self.term.clip_text, -1)
            cb.store()
        if self.cursor_blink or (self.term.app_cursor_style or (0, 0))[1]:
            self._blink_on = True  # output novo: cursor volta a aparecer
            self._ensure_blink()
        self.request_draw()
        return True

    def on_child_exit(self, pid, status):
        """O shell morreu (o GLib já reapou — NÃO chamar waitpid de novo)."""
        try:
            self.exit_code = os.waitstatus_to_exitcode(status)
        except (AttributeError, ValueError):
            self.exit_code = None
        self.child_exited = True
        self._drain_pty()  # não perder o último output (logout, msg de erro)
        # fechar a ABA manda SIGHUP no filho: aí o "código -1" é nosso, não
        # notícia (só interessa a saída que o usuário pediu)
        if self.exit_code and not self._closing:
            print(
                f"tortty-python: shell exited with code {self.exit_code}",
                file=sys.stderr,
            )
        self._notify_exit()
        return False  # remove o child watch

    def _drain_pty(self):
        """Lê o que sobrou no master sem bloquear (fd é non-blocking)."""
        if self.master is None:
            return
        for _ in range(64):  # teto: filho mal comportado não trava a saída
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
        if _PROF and self._prof:
            parts = [
                f"{k} {n}x {t * 1000 / n:.2f}ms/call ({t * 1000:.0f}ms)"
                for k, (n, t) in self._prof.items()
                if n
            ]
            parts.append(f"bytes {self._prof_bytes / 1e6:.2f}MB eagain {self._prof_eagain}")
            print("prof:", " | ".join(parts), file=sys.stderr)
        self._closing = True
        if self._blink_timer:
            GLib.source_remove(self._blink_timer)
            self._blink_timer = 0
        if self._cell_timer:
            GLib.source_remove(self._cell_timer)
            self._cell_timer = 0
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
        self._hungup = True  # _close() e on_destroy() chamam os dois
        try:
            os.killpg(self.child_pid, signal.SIGHUP)
        except OSError:
            pass  # grupo já não existe: shell saiu sozinho

    def debug_metrics(self):
        """Avanço, célula, dpi, padding e fonte da grade (substitui o DIAG)."""
        cw, ch = self.metrics()
        return {
            "advance": round(getattr(self, "_advance", cw), 3),
            "cell": [cw, ch],
            "dpi": round(self.dpi(), 1),
            "padding": self.padding,
            "font": self.font_family,
            "font_size": self.font_size,
        }

    def debug_prof(self):
        """Contadores de custo acumulados desde a última ligação do `prof`."""
        return {
            "on": bool(_PROF),
            "etapas": {
                etapa: {"n": n, "ms": round(seg * 1000, 1)}
                for etapa, (n, seg) in sorted(self._prof.items())
            },
            "bytes": self._prof_bytes,
            "eagain": self._prof_eagain,
        }

    def dump_text(self):
        """Texto do dump (SIGUSR1 / saída) desta sessão."""
        t = self.term
        lines = []
        if t.scrollback:
            lines.append(f"=== scrollback ({len(t.scrollback)}) ===")
            for row in t.scrollback[-40:]:
                lines.append("".join(c[0] for c in row).rstrip())
        # o off vai no cabeçalho: sem ele o dump não conta se a visão está no
        # histórico (as linhas abaixo são a grade VIVA, não a visão rolada)
        off = f" (scrollback +{self.view_off})" if self.view_off else ""
        lines.append(f"=== viewport {t.cols}x{t.rows}{off} ===")
        for y in range(t.rows):
            lines.append(t.row_text(y).rstrip())
        if t.graphics.placements or t.graphics.images:
            lines.append(
                f"=== imagens: {len(t.graphics.images)} guardadas, "
                f"{len(t.graphics.placements)} na tela ==="
            )
            for pl in t.graphics.placements:
                img = t.graphics.images.get(pl.image_id)
                lines.append(
                    f"  id={pl.image_id} em ({pl.col},{pl.row}) "
                    f"{pl.cols}x{pl.rows} "
                    f"+{pl.dx},{pl.dy}px "
                    f"fmt={img.fmt if img else '-'}"
                )
        lines.append(f"=== cursor {t.cx},{t.cy} ===")
        return "\n".join(lines)

    # -- métricas ----------------------------------------------------
    def font_desc(self):
        """Fonte do desenho em PONTOS, como todo terminal (kitty, alacritty,
        GTK/fontconfig): o Pango converte para pixel com o DPI do display, então
        a fonte acompanha tela HiDPI sem mudar de config."""
        if self._font_desc is None:
            d = Pango.FontDescription()
            d.set_family(self.font_family)
            d.set_size(round(self.font_size * Pango.SCALE))
            self._font_desc = d
        return self._font_desc

    def dpi(self):
        """Resolução do display (Xft.dpi), a mesma que a grade usa."""
        if self._dpi is None:
            dpi = PangoCairo.context_get_resolution(self.get_pango_context())
            if dpi <= 0:
                scr = Gdk.Screen.get_default()
                dpi = scr.get_resolution() if scr else 96.0
            self._dpi = dpi
        return self._dpi

    def metrics(self):
        if self._metrics:
            return self._metrics
        # Layout do contexto do PRÓPRIO widget, não de uma ImageSurface solta: o
        # ponto->pixel depende da resolução do contexto (Xft.dpi), e métrica
        # tirada com resolução diferente da que desenha desalinha a grade.
        layout = Pango.Layout(self.get_pango_context())
        PangoCairo.context_set_resolution(layout.get_context(), self.dpi())
        layout.set_font_description(self.font_desc())
        layout.set_text("M", -1)
        # largura = avanço do glifo; altura = ascent + descent do layout. Sai da
        # MESMA fonte que desenha, então não existe divergência de arredondamento
        # entre a grade e o texto.
        w, h = layout.get_size()
        # avanço fica em px porque a célula é o teto dele e a diferença vira
        # letter_spacing (o run tem que ocupar exatamente N células)
        self._advance = w / Pango.SCALE
        # letra extra (P64) entra na largura da célula: o glifo i continua na
        # coluna i, só o vão entre eles cresce — o run fecha N células
        self._metrics = (
            math.ceil(self._advance + self.letter_spacing),
            math.ceil(h / Pango.SCALE),
        )
        self.term.cell_size = self._metrics  # o protocolo de imagem usa isso
        return self._metrics

    def new_layout(self, cr):
        """Layout com a fonte e a resolução da grade."""
        lay = PangoCairo.create_layout(cr)
        PangoCairo.context_set_resolution(lay.get_context(), self.dpi())
        lay.set_font_description(self.font_desc())
        return lay

    def text_attrs(self, bold, italic=False):
        """AttrList do run: espaçamento que faz N caracteres ocuparem N células."""
        slot = (1 if bold else 0) | (2 if italic else 0)
        cached = self._attrs[slot]
        if cached is not None:
            return cached
        cw, _ = self.metrics()
        al = Pango.AttrList()
        # ligaduras (P45): atributo de fonte do run, não a fonte inteira — o
        # shaping de script (árabe, devanágari) continua de qualquer jeito
        if self.font_features:
            al.insert(Pango.attr_font_features_new(self.font_features))
        # letter_spacing vale entre glifos (o último não recebe): run de N fecha
        # N*cw com erro menor que 1 px
        al.insert(Pango.attr_letter_spacing_new(round((cw - self._advance) * Pango.SCALE)))
        if bold:
            al.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        if italic:
            al.insert(Pango.attr_style_new(Pango.Style.ITALIC))
        self._attrs[slot] = al
        return al

    def _deco(self, cr, x0, y0, w, h, deco):
        """Sublinado, riscado e sobrelinha da corrida (P54): uma passada só.

        `deco` é o `fl & DECO_BITS` da célula: o riscado fica a meia altura e a
        sobrelinha no topo, ambos na cor do texto (já posta no contexto).
        """
        if deco & OVERLINE:
            cr.rectangle(x0, y0 + 1, w, 1)
            cr.fill()
        if deco & STRIKE:
            cr.rectangle(x0, y0 + round(h / 2), w, 1)
            cr.fill()
        ul = deco & UL_BITS
        if ul:
            self._underline(cr, x0, y0, w, h, ul_style(ul))

    def _underline(self, cr, x0, y0, w, h, style):
        """Sublinha do SGR 4:n no pé da célula (estilo já decodificado)."""
        y = y0 + h - 2
        if style == UL_DOUBLE:
            cr.rectangle(x0, y - 2, w, 1)
            cr.rectangle(x0, y, w, 1)
            cr.fill()
            return
        if style in (UL_DOTTED, UL_DASHED):
            cr.save()
            cr.set_dash([1, 1] if style == UL_DOTTED else [3, 2])
            cr.set_line_width(1)
            cr.move_to(x0, y + 0.5)
            cr.line_to(x0 + w, y + 0.5)
            cr.stroke()
            cr.restore()
            return
        if style == UL_CURLY:
            # meia onda por passo: passo curto demais vira borrão na largura 1
            n = max(1, int(round(w / max(2.0, h / 8))))
            step = w / n
            cr.save()
            cr.set_line_width(1)
            cr.move_to(x0, y + 0.5)
            for i in range(n):
                cr.line_to(x0 + (i + 1) * step, y + (0.5 - 1.5 if i % 2 == 0 else 2.0))
            cr.stroke()
            cr.restore()
            return
        cr.rectangle(x0, y, w, 1)
        cr.fill()

    def on_resize(self, widget, alloc):
        if alloc.width < 10 or alloc.height < 10:
            return False
        cw, ch = self.metrics()
        cols = max(2, (alloc.width - 2 * self.padding) // int(cw))
        rows = max(1, (alloc.height - 2 * self.padding) // int(ch))
        if (cols, rows) != (self.term.cols, self.term.rows):
            self.term.resize(cols, rows)
            self._send_winsize(cols, rows)
            self.queue_draw()
        return False

    def _send_winsize(self, cols, rows):
        import fcntl

        cw, ch = self.metrics()
        winsz = struct.pack("HHHH", rows, cols, int(cols * cw), int(rows * ch))
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
            return False  # alt-screen não tem histórico que rolar
        off = max(0, min(len(t.scrollback), self.view_off + delta))
        if off != self.view_off:
            if t.sync_output:
                _slog(ev="wheel", d=delta, v0=self.view_off, v1=off, pin=self._pin_off)
            if t.sync_output and self._pin_off:
                # região reescrevendo o histórico: vale a intenção (distância
                # sem o clamp do histórico parcial), não uma âncora absoluta
                self._pin_off = max(0, self.view_off + delta)
            else:
                self._pin_off = 0  # o usuário escolheu: a posição dele manda
            self.view_off = off
            # a âncora é absoluta (P32): o output que chegar depois não arranca
            # o usuário daqui — só rolar até o fim, tecla ou limpeza do histórico
            self._anchor = t.scrolled - off
            # a seleção também é absoluta (B17): rolar não a desfaz nem a deixa
            # sobre outro texto, ela vai junto com o conteúdo
            self.queue_draw()
        return True

    def _draw_links(self, cr, rows, cw, ch, row_lo, row_hi, col_lo, col_hi):
        """Sublinha a corrida com hyperlink: todas com Ctrl, só a do ponteiro sem ele."""
        t = self.term
        alvo = None if self._ctrl else self._hover_link  # P70
        cr.set_source_rgb(*t.theme.rgb_f(DEF_FG))
        for y in range(row_lo, min(row_hi, len(rows) - 1) + 1):
            row = rows[y]
            x = col_lo
            while x < col_hi:
                uri = t.link_of(row[x])
                if not uri:
                    x += 1
                    continue
                j = x + 1
                while j < t.cols and t.link_of(row[j]) == uri:
                    j += 1
                if alvo is None or uri == alvo:
                    cr.rectangle(x * cw, y * ch + ch - 2, (j - x) * cw, 1)
                    cr.fill()
                x = j

    def _cell_uri(self, row, col):
        """URI do hyperlink na célula da visão, ou None."""
        rows = self.term.visible_rows(self.view_off)
        if not (0 <= row < len(rows)) or not (0 <= col < self.term.cols):
            return None
        return self.term.link_of(rows[row][col])

    def open_link(self, uri):
        """Ctrl+clique: entrega o URI ao xdg-open, só nos esquemas conhecidos."""
        if not link_allowed(uri):
            return False
        try:
            subprocess.Popen(
                ["xdg-open", uri],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return True

    def _set_hover_link(self, uri):
        """Link sob o ponteiro mudou: redesenha só para o sublinhado seguir (P70)."""
        if uri == self._hover_link:
            return
        self._hover_link = uri
        self.queue_draw()

    def _set_ctrl(self, on):
        """Ctrl entrou/saiu: redesenha só para sublinhar (ou não) os links."""
        if on != self._ctrl:
            self._ctrl = on
            self.queue_draw()

    def scrollbar_rect(self):
        """(x, largura, topo, altura, histórico) da barra, ou None sem histórico.

        Coordenadas da GRADE (o draw já transladou o padding). A faixa fica
        sobre a ÚLTIMA coluna: larga o bastante para acertar com o mouse,
        estreita o bastante para não comer o texto embaixo.
        """
        t = self.term
        hist = len(t.scrollback)
        if not hist or not t.rows or t.alt_grid is not None:
            # tela cheia não tem histórico que rolar: barra só atrapalharia
            return None
        cw, ch = self.metrics()
        strip = min(SB_W, int(cw))
        return t.cols * int(cw) - strip, strip, 0, t.rows * int(ch), hist

    def _sb_hover_at(self, x, y):
        """O ponteiro está sobre a barra? Coordenadas do widget (P67)."""
        r = self.scrollbar_rect()
        if not r:
            return False
        gx, gy = x - self.padding, y - self.padding
        return r[0] <= gx < r[0] + r[1] and 0 <= gy < r[2] + r[3]

    def _sb_hover_set(self, hover):
        if hover == self._sb_hover:
            return
        self._sb_hover = hover
        r = self.scrollbar_rect()
        if r:
            # repinta só a faixa (mesma área do desenho da barra)
            self.queue_draw_area(r[0] + self.padding, r[2] + self.padding, r[1], r[3])

    def _on_leave(self, *_a):
        """Ponteiro saiu do widget: sem motion depois disso, apaga hover e link."""
        self._sb_hover_set(False)
        self._hover_cell = (-1, -1)
        self._set_hover_link(None)

    def _thumb(self, h, hist):
        """Altura do polegar: a fatia do buffer que a visão mostra."""
        rows = self.term.rows
        return max(12.0, min(float(h), h * rows / (rows + hist)))

    def _draw_scrollbar(self, cr, t):
        """Trilho a 10% (18% no hover) e polegar a 55% (75%): fora do texto."""
        r = self.scrollbar_rect()
        if not r:
            return
        x0, w, top, h, hist = r
        thumb = self._thumb(h, hist)
        off = min(self.view_off, hist) / hist
        y = top + (h - thumb) * (1.0 - off)  # vivo = polegar no fim
        fg = t.theme.rgb_f(DEF_FG)
        trh, thb = (0.18, 0.75) if self._sb_hover else (0.10, 0.55)
        cr.set_source_rgba(*fg, trh)
        cr.rectangle(x0, top, w, h)
        cr.fill()
        cr.set_source_rgba(*fg, thb)
        cr.rectangle(x0, y, w, thumb)
        cr.fill()

    def scroll_to_y(self, py):
        """Põe a visão onde o ponteiro está na barra (clique pula, arrasto anda)."""
        r = self.scrollbar_rect()
        if not r:
            return False
        _x0, _w, top, h, hist = r
        thumb = self._thumb(h, hist)
        travel = h - thumb
        if travel <= 0:
            return False
        y = min(max(py - top - thumb / 2.0, 0.0), travel)
        off = round((1.0 - y / travel) * hist)
        return self.scroll_view(off - self.view_off)

    def clear_selection(self):
        if self.sel_start is not None or self.sel_end is not None:
            self.sel_start = self.sel_end = None
            self.sel_block = False
            self.press_anchor = None
            self.press_at = None
            self.queue_draw()

    def back_to_live(self):
        self._pin_off = 0
        if self.view_off:
            self.view_off = 0
            self._anchor = 0
            self.queue_draw()

    # -- opções vivas (P34) -------------------------------------------
    def apply_config(self, cfg):
        """Aplica as opções da configuração sem recriar a sessão."""
        self.font_family = cfg.font_family
        self.font_size = cfg.font_size
        self.font_features = cfg.ligature_features
        self.term.theme.apply_colors(cfg.colors)  # P49: base; OSC 4 fica
        self.padding = cfg.padding
        self.cursor_shape = cfg.cursor_shape
        self.cursor_blink = cfg.cursor_blink
        self.copy_on_select = cfg.copy_on_select
        self.bold_as_bright = cfg.bold_as_bright
        self.letter_spacing = cfg.letter_spacing
        self.term.set_scrollback(cfg.scrollback)
        # tudo que saiu da fonte medida (layout cacheado incluído)
        self._font_desc = None
        self._metrics = None
        self._advance = None
        self._attrs = [None] * 4
        self._layouts = ({}, {}, {}, {})
        self._ensure_blink()
        # direto (e não só queue_resize): o tamanho alocado pode não mudar e
        # o size-allocate nunca viria, aí a grade ficava com a célula antiga
        self.on_resize(self, self.get_allocation())
        self.queue_resize()
        self.queue_draw()

    def _cursor_style(self):
        """(forma, pisca) — DECSCUSR do app vence a config (P34)."""
        return self.term.app_cursor_style or (self.cursor_shape, self.cursor_blink)

    def _cursor_draw(self):
        """Forma a desenhar agora, ou None (invisível, histórico, pisca off)."""
        t = self.term
        if self.view_off or not t.cursor_visible:
            return None
        if t.cy >= t.rows or t.cx >= t.cols:
            return None
        forma, pisca = self._cursor_style()
        return None if pisca and not self._blink_on else forma

    def _ensure_blink(self):
        """Liga o timer do pisca se algo pediu (config ou app) e a view aparece."""
        if self._blink_timer or not self.get_mapped():
            return  # oculta: quem liga é o _on_map
        if self.cursor_blink or (self.term.app_cursor_style or (0, 0))[1]:
            self._blink_timer = GLib.timeout_add(BLINK_MS, self._blink_tick)

    def _on_map(self, *_a):
        """Voltou a aparecer: cursor visível e o pisca religado."""
        self._blink_on = True
        self._ensure_blink()

    def _on_unmap(self, *_a):
        """Aba oculta: sem timer — com N abas seriam N timers acordando."""
        if self._blink_timer:
            GLib.source_remove(self._blink_timer)
            self._blink_timer = 0
        if self._cell_timer:
            GLib.source_remove(self._cell_timer)
            self._cell_timer = 0
        self._cell_on = True  # ao voltar, a primeira fase é visível

    def _blink_tick(self):
        if not self.get_mapped():  # rede: o _on_unmap normalmente já parou
            self._blink_timer = 0
            return False
        if not (self.cursor_blink or (self.term.app_cursor_style or (0, 0))[1]):
            self._blink_timer = 0
            self._blink_on = True
            return False  # nada pisca: desligar (a config/app religa)
        self._blink_on = not self._blink_on
        self._invalidate_cursor()
        return True

    def _cell_tick(self):
        if not self.get_mapped() or not self._cell_blink_present():
            self._cell_timer = 0
            self._cell_on = True  # sem piscar, volta visível para religar assim
            return False
        self._cell_on = not self._cell_on
        # fase não suja a grade: sem dano total o _queue_damage repinta só o cursor (P66)
        self.term.dirty_all = True
        self.request_draw()
        return True

    def _cell_blink_present(self):
        """Prova de ausência para o timer: alguma célula visível com SGR 5/6."""
        for row in self.visible_rows():
            for cell in row:
                if cell[3] & BLINK:
                    return True
        return False

    def _invalidate_cursor(self):
        """Repinta só a célula do cursor (a cada 530 ms, sem draw inteiro)."""
        t = self.term
        if self.view_off or not t.cursor_visible or t.cy >= t.rows or t.cx >= t.cols:
            return
        cw, ch = self.metrics()
        self.queue_draw_area(
            self.padding + int(t.cx * cw),
            self.padding + int(t.cy * ch),
            int(cw) + 2,
            int(ch) + 2,
        )

    # -- desenho ------------------------------------------------------
    def sel_span(self):
        """Seleção normalizada em âncoras absolutas (início, fim) ou None."""
        a, b = self.sel_start, self.sel_end
        if a is None or b is None:
            return None
        # âncora destruída (CSI 3J, reflow): não há mais o texto pra pintar
        if not (self.term.anchor_alive(a) and self.term.anchor_alive(b)):
            return None
        return (a, b) if (a.line, a.col) <= (b.line, b.col) else (b, a)

    def sel_range(self):
        """Seleção normalizada (r1, c1, r2, c2) nas fileiras da visão ou None.

        O que ficou fora da tela (seleção maior que a viewport) é preso à
        borda: o desenho pinta só o pedaço visível, a cópia usa a âncora.
        """
        span = self.sel_span()
        if span is None:
            return None
        t = self.term
        a, b = span
        r1, r2 = t.anchor_row(a, self.view_off), t.anchor_row(b, self.view_off)
        if r1 >= t.rows or r2 < 0:
            return None  # a seleção inteira está fora da tela
        c1 = a.col if r1 >= 0 else 0
        c2 = b.col if r2 < t.rows else t.cols - 1
        return (max(0, r1), c1, min(t.rows - 1, r2), c2)

    def sel_block_rect(self):
        """(r1, c1, r2, c2) do bloco nas fileiras da visão, ou None (P61).

        As colunas são as mesmas em toda linha; a linha que ficou fora da tela
        é presa na borda, como na seleção linear.
        """
        if not self.sel_block:
            return None
        span = self.sel_span()
        if span is None:
            return None
        t = self.term
        a, b = span
        r1, r2 = t.anchor_row(a, self.view_off), t.anchor_row(b, self.view_off)
        if r1 >= t.rows or r2 < 0:
            return None
        return (
            max(0, r1),
            min(a.col, b.col),
            min(t.rows - 1, r2),
            min(max(a.col, b.col), t.cols - 1),
        )

    def on_draw(self, area, cr):
        if not _PROF:
            return self._on_draw(area, cr)
        t0 = time.perf_counter()
        try:
            return self._on_draw(area, cr)
        finally:
            _tick(self._prof, "draw", t0)

    def _on_draw(self, area, cr):
        t = self.term
        if t.sync_output:
            _slog(
                ev="draw",
                v=self.view_off,
                pin=self._pin_off,
                sb=len(t.scrollback),
                scr=t.scrolled,
            )
        cw, ch = self.metrics()
        cw, ch = int(cw), int(ch)
        # um layout por draw, reaproveitado em cada run (criar por run custaria
        # mais que o próprio desenho). A resolução vem do cr (96 dpi) e NÃO é a
        # da tela: sem pôr a do widget, o texto sai com avanço menor que a
        # célula e a grade inteira desalinha.
        layout = self.new_layout(cr)
        # fundo
        cur = t.theme.rgb_f(DEF_BG)  # a última cor posta no contexto
        cr.set_source_rgb(*cur)
        cr.paint()
        cur_bg = cur_fg = cur  # última cor posta em cada passada
        if self.padding:
            # daqui pra baixo as coordenadas são da GRADE: o padding (P34)
            # vira só translação, inclusive para o mouse (cell_at desconta)
            cr.translate(self.padding, self.padding)
        # clip (já na coordenada da grade): com dano por linha o Gdk entrega
        # só a faixa que mudou — sem isso o laço desenharia a tela toda de
        # qualquer jeito e o custo do spinner voltaria (P27)
        clip_x0, clip_y0, clip_x1, clip_y1 = cr.clip_extents()
        blk = self.sel_block_rect()
        sel = blk if blk is not None else self.sel_range()
        rows = self.visible_rows()
        # sobra sub-célula: quase nunca a janela é múltiplo exato de (cw, ch).
        # A faixa que sobra embaixo/à direita pertence à última fileira/coluna
        # e recebe o fundo DELA, senão um app com fundo colorido (vim com
        # termguicolors, htop) ganha um rodapé preto.
        og_w = max(0, self.get_allocated_width() - 2 * self.padding)
        og_h = max(0, self.get_allocated_height() - 2 * self.padding)
        last_y = len(rows) - 1
        dimmed = None  # memo por draw do SGR 2 (P64): (fg, bg) -> fg ao meio
        blink_seen = False  # presença do BLINK só na área do dano: prova barata (P66)
        # limites do dano já em linha/coluna: comparar inteiro em vez de
        # multiplicar por célula em todo run (P37)
        row_lo = max(0, int(clip_y0 // ch))
        row_hi = min(last_y, int(clip_y1 // ch))
        col_lo = max(0, int(clip_x0 // cw))
        col_hi = min(t.cols, int(clip_x1 // cw) + 1)
        bg_def = t.theme.rgb_f(DEF_BG)  # uma vez por draw, não a cada run (P37)
        rgb, sel_on = t.theme.rgb_f, bool(sel)
        in_sel = _in_block if blk is not None else _in_sel
        quadro = []
        for y, row in enumerate(rows):
            if y < row_lo or y > row_hi:
                continue  # linha fora do dano
            # Runs da linha em lista antes de desenhar: (x, j, cch, fgc, bgc,
            # bold, ul). Duas passadas — todo o fundo, depois todo o texto —
            # porque alternar `fill` e glifo custa muito mais que cada um
            # sozinho (o X troca de estado por operação): medido, 13,0 ms
            # alternando contra 2,6 ms de só fundo e 2,9 ms de só texto.
            runs = []
            x = 0
            while x < t.cols:
                # índices (e não unpack de 4): a célula com hyperlink tem o
                # quinto campo do OSC 8, e o desenho não pode tropeçar nele
                cell = row[x]
                cch, fg, bg, fl = cell[0], cell[1], cell[2], cell[3]
                if fl & BLINK:
                    blink_seen = True
                s0 = sel_on and in_sel(y, x, sel)
                j = x + 1
                while j < t.cols:
                    c2 = row[j]
                    if (
                        c2[1] != fg
                        or c2[2] != bg
                        or c2[3] != fl
                        or (sel_on and in_sel(y, j, sel)) != s0
                    ):
                        break
                    j += 1
                if j > col_lo and x < col_hi:
                    # a cor vira RGB ANTES de inverter: trocar os índices e só
                    # depois converter transformava o texto default (256) em
                    # "cor 1" (vermelho), porque 256/257 são sentinelas e não
                    # índices da paleta
                    fgc, bgc = rgb(fg), rgb(bg)
                    if self.bold_as_bright and fl & BOLD and 0 <= fg <= 7:
                        fgc = rgb(fg + 8)  # P64: como o `boldColors` do xterm
                    if (fl & INV) or s0:
                        fgc, bgc = bgc, fgc  # inverso / seleção = reverso
                    if fl & DIM:
                        if dimmed is None:
                            dimmed = {}
                        k = (fgc, bgc)
                        v = dimmed.get(k)
                        if v is None:
                            v = dimmed[k] = tuple((a + b) / 2.0 for a, b in zip(fgc, bgc))
                        fgc = v  # faint: contraste menor com o fundo
                    runs.append(
                        (
                            x,
                            j,
                            cch,
                            fgc,
                            bgc,
                            bool(fl & BOLD),
                            fl & DECO_BITS,
                            bool(fl & ITALIC),
                            bool(fl & HIDDEN) or (bool(fl & BLINK) and not self._cell_on),
                        )
                    )
                x = j
            if runs:
                quadro.append((row, y * ch, max(ch, og_h - y * ch) if y == last_y else ch, runs))
        if blink_seen and not self._cell_timer and self.get_mapped():
            self._cell_timer = GLib.timeout_add(CELL_BLINK_MS, self._cell_tick)
        for row, ypx, rh, runs in quadro:
            for x, j, _cch, _fgc, bgc, _bold, _deco, _italic, _hidden in runs:
                if bgc is not cur_bg:
                    cr.set_source_rgb(*bgc)
                    cur_bg = bgc
                if bgc is not bg_def:
                    rw = (og_w if j >= t.cols else j * cw) - x * cw
                    cr.rectangle(x * cw, ypx, rw, rh)
                    cr.fill()
        for row, ypx, _rh, runs in quadro:
            for x, j, cch, fgc, _bgc, bold, deco, italic, hidden in runs:
                if fgc is not cur_fg:
                    cr.set_source_rgb(*fgc)
                    cur_fg = fgc
                if hidden:
                    # SGR 8 (P64): o glifo fica de fora; o fundo já saiu na
                    # passada de trás e a decoração continua na cor do texto
                    if deco:
                        self._deco(cr, x * cw, ypx, (j - x) * cw, ch, deco)
                    continue
                # run de uma célula é o caso comum (fundo por célula): pega
                # o char do unpack em vez de montar slice + join (P37)
                txt = cch if j == x + 1 else "".join([c[0] for c in row[x:j]])
                # Pango (P9): layout de verdade, com shaping e fallback de
                # fonte; `cr.move_to` na quina da célula e o layout desenha a
                # partir dali (a linha de base sai do ascent do próprio layout)
                # cache por texto, peso e estilo: `set_text` é o caro do
                # layout, e um run se repete muito (fundo do mesmo tom, app
                # parado). Teto para não crescer sem limite em dump de texto.
                # O índice da tabela é (negrito, itálico) em 4 slots: o run já
                # carrega os dois, então não há tupla para alocar (P37).
                cache = self._layouts[(1 if bold else 0) | (2 if italic else 0)]
                ent = cache.get(txt)
                if ent is None:
                    if len(cache) > 800:
                        cache.clear()
                    lay = self.new_layout(cr)
                    lay.set_attributes(self.text_attrs(bold, italic))
                    lay.set_text(txt, -1)
                    # guardar a linha e a baseline junto: show_layout_line
                    # custa ~17% menos que show_layout e sai idêntico (P25).
                    # linha None = layout com mais de uma linha (texto com
                    # quebra): aí é show_layout, que desenha todas. A decisão
                    # fica no cache — get_line_count() por run custa o ganho.
                    base = lay.get_baseline() / Pango.SCALE
                    line = lay.get_line(0) if lay.get_line_count() == 1 else None
                    ent = (lay, line, base)
                    cache[txt] = ent
                lay, line, base = ent
                if line is None:
                    cr.move_to(x * cw, ypx)
                    PangoCairo.show_layout(cr, lay)
                else:
                    cr.move_to(x * cw, ypx + base)
                    PangoCairo.show_layout_line(cr, line)
                if deco:
                    self._deco(cr, x * cw, ypx, (j - x) * cw, ch, deco)
        # Ctrl apertado: sublinha todo hyperlink da tela (é o convite ao clique)
        if self._ctrl or self._hover_link:
            self._draw_links(cr, rows, cw, ch, row_lo, row_hi, col_lo, col_hi)
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
            x0 = pl.col * cw + pl.dx  # X=/Y=: offset em pixels (centralização)
            y0 = vr * ch + pl.dy
            cr.save()
            cr.rectangle(x0, y0, w, h)
            cr.clip()
            cr.translate(x0, y0)
            cr.scale(w / max(1, surf.get_width()), h / max(1, surf.get_height()))
            cr.set_source_surface(surf, 0, 0)
            cr.paint()
            cr.restore()

        # barra de rolagem sobre a última coluna: por cima do texto, abaixo do
        # cursor — e só existe quando há histórico
        self._draw_scrollbar(cr, t)

        # cursor — só no vivo: no histórico o cursor do app não está ali
        forma = self._cursor_draw()
        if forma == "block":
            cr.set_source_rgb(*t.theme.cursor_f())
            cr.rectangle(t.cx * cw, t.cy * ch, cw, ch)
            cr.fill()
            cell = t.grid[t.cy][t.cx]
            cr.set_source_rgb(*t.theme.rgb_f(cell[2]))
            layout.set_attributes(self.text_attrs(False))
            layout.set_text(cell[0], -1)
            cr.move_to(t.cx * cw, t.cy * ch)
            PangoCairo.show_layout(cr, layout)
        elif forma == "beam":
            bw = max(1, round(cw / 6))
            cr.set_source_rgb(*t.theme.cursor_f())
            cr.rectangle(t.cx * cw, t.cy * ch, bw, ch)
            cr.fill()
        elif forma == "underline":
            bh = max(2, round(ch / 10))
            cr.set_source_rgb(*t.theme.cursor_f())
            cr.rectangle(t.cx * cw, t.cy * ch + ch - bh, cw, bh)
            cr.fill()
        if self.view_off:
            # marcador de histórico no canto ("↑") com o quanto se voltou
            label = f"↑{self.view_off} "
            layout.set_attributes(self.text_attrs(False))
            layout.set_text(label, -1)
            lw = layout.get_pixel_size()[0]
            x0 = (t.cols - 1) * cw - lw
            cr.set_source_rgb(*t.theme.rgb_f(DEF_FG))
            cr.rectangle(x0 - 2, 0, lw + 4, ch)
            cr.fill()
            cr.set_source_rgb(*t.theme.rgb_f(DEF_BG))
            cr.move_to(x0, 0)
            PangoCairo.show_layout(cr, layout)
        return False

    # -- mouse, seleção e cópia ---------------------------------------
    def cell_at(self, px, py):
        """Pixel -> (col, row) 0-based, preso à grade (desconta o padding)."""
        cw, ch = self.metrics()
        t = self.term
        col = max(0, min(t.cols - 1, int((px - self.padding) // int(cw))))
        row = max(0, min(t.rows - 1, int((py - self.padding) // int(ch))))
        return col, row

    def drop_path(self, path):
        """Arquivo solto na janela (P62): o caminho entra como colagem.

        Um só caminho para o XDND e para o verbo `drop` do socket — é o que
        deixa o drop ser testável sem arrastar de verdade.
        """
        self.back_to_live()  # quem cola fala com o app: a visão vai pro vivo
        self._write_child(self.term.paste_payload(shell_quoted(path)))

    def _write_child(self, data):
        if not data:
            return
        try:
            os.write(self.master, data.encode("utf-8", "replace"))
        except OSError:
            pass

    def report_mouse(self, button, col, row, pressed=True, motion=False, px=None, py=None):
        """Manda um evento de mouse pro app (o app pediu com ?1000/1002/3).

        Com `?1016` (P46) o byte leva pixels, não células: quem tem o evento
        passa `px`/`py` e a conversão (menos o padding) acontece aqui.
        """
        st = self._state
        mods = mouse.mods_from_state(
            bool(st & Gdk.ModifierType.SHIFT_MASK),
            bool(st & Gdk.ModifierType.MOD1_MASK),
            bool(st & Gdk.ModifierType.CONTROL_MASK),
        )
        pixels = self.term.mouse_px and px is not None
        if pixels:
            col = max(0, int(px - self.padding))
            row = max(0, int(py - self.padding))
        self._write_child(
            mouse.encode(
                button,
                col,
                row,
                pressed=pressed,
                sgr=self.term.mouse_sgr,
                mods=mods,
                motion=motion,
                pixels=pixels,
                urxvt=self.term.mouse_urxvt,
                utf8=self.term.mouse_utf8,
            )
        )

    def on_button_press(self, widget, ev):
        t = self.term
        self._state = ev.state
        # `Clipboard.store()` roda um laço aninhado no X e o MESMO press volta
        # ao widget: hora e coordenada idênticas são o mesmo evento, não um
        # segundo clique (senão o duplo clique pulava direto para o triplo).
        if ev.time == self._press_time and (ev.x, ev.y) == self._press_xy:
            return True
        self._press_time, self._press_xy = ev.time, (ev.x, ev.y)
        col, row = self.cell_at(ev.x, ev.y)
        btn = mouse.GDK_BUTTONS.get(ev.button)
        sb = self.scrollbar_rect()
        if sb and ev.button == 1 and ev.x - self.padding >= sb[0]:
            # a barra é do terminal, não do app: vem antes do report de mouse
            self._sb_drag = True
            self.scroll_to_y(ev.y - self.padding)
            return True
        if ev.button == 1 and ev.state & Gdk.ModifierType.CONTROL_MASK:
            # Ctrl+clique no hyperlink: abre no navegador e não seleciona
            uri = self._cell_uri(row, col)
            if uri and self.open_link(uri):
                return True
        if t.mouse_mode and btn is not None:
            # o app quer saber do mouse: nada de seleção local. Ele desenha o
            # vivo, então o clique no histórico não significa nada para ele —
            # daí voltar pro vivo antes de reportar (B16)
            self.back_to_live()
            self._held = btn
            self.report_mouse(btn, col, row, True, px=ev.x, py=ev.y)
            return True
        if ev.button == 3 and self.on_context:
            # botão direito fora do modo mouse: o menu do window (P71)
            return self.on_context(self, ev)
        if ev.button == 1:
            # duplo clique = palavra, triplo = linha lógica (inclusive a que
            # quebrou mole): o clique conta por tempo e mesma célula, como no
            # resto do desktop; 400 ms cobre o duplo clique de quem digita
            c0, b0, r0, k0 = self._click
            same = b0 == 1 and (r0, k0) == (row, col) and ev.time - c0 <= CLICK_MS
            self._click = (ev.time, 1, row, col)
            self._click_n = min(3, self._click_n + 1) if same else 1
            if self._click_n > 1:
                self._pick(self._click_n, row, col)
                return True
            # seleção só nasce com arrasto: um clique não pode pintar a célula
            # nem sobrescrever o PRIMARY com 1 caractere. E clicar no histórico
            # NÃO volta pro vivo: o arrasto é justamente para copiar dali (B16)
            self.clear_selection()
            # Alt+arrasto = bloco (P61), como no Rust
            self.sel_block = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
            self.press_anchor = t.anchor_at(self.view_off, row, col)
            self.press_at = (ev.x, ev.y)
            self.dragging = True
            return True
        if ev.button == 2:
            self.back_to_live()  # colar fala com o app: a visão vai pro vivo
            self.paste(Gdk.SELECTION_PRIMARY)
            return True
        return False

    def on_button_release(self, widget, ev):
        t = self.term
        self._state = ev.state
        col, row = self.cell_at(ev.x, ev.y)
        if self._sb_drag:
            self._sb_drag = False
            return True
        if t.mouse_mode and self._held is not None:
            self.report_mouse(self._held, col, row, False, px=ev.x, py=ev.y)
            self._held = None
            return True
        if ev.button == 1 and self.dragging:
            self.dragging = False
            span = self.sel_span()
            # só copia o que foi realmente selecionado (press + arrasto em
            # outra célula); sem arrasto, o PRIMARY do usuário fica intacto
            if span and span[0] != span[1]:
                self.copy(Gdk.SELECTION_PRIMARY)
                if self.copy_on_select:  # P34: já vai para o clipboard também
                    self.copy(Gdk.SELECTION_CLIPBOARD)
            else:
                self.clear_selection()
            self.queue_draw()
            return True
        return False

    def _pick(self, kind, row, col):
        """Seleciona e copia por clique: 2 = palavra, 3 = linha lógica."""
        t = self.term
        line = t.scrolled - self.view_off + row
        if kind == 2:
            first, last = t.word_span(line, col)
            start, end = (line, first), (line, last)
        else:
            start, end = t.logical_line_span(line)
        self.sel_start = CellAnchor(start[0], start[1], t.abs_gen)
        self.sel_end = CellAnchor(end[0], end[1], t.abs_gen)
        self.sel_block = False  # palavra/linha nunca é bloco
        self.dragging = False  # o release não pode desfazer nem recopiar
        self.copy(Gdk.SELECTION_PRIMARY)
        if self.copy_on_select:
            self.copy(Gdk.SELECTION_CLIPBOARD)
        self.queue_draw()

    def on_motion(self, widget, ev):
        t = self.term
        self._state = ev.state
        self._sb_hover_set(self._sb_hover_at(ev.x, ev.y))
        if not self._sb_drag and not self.dragging:
            # P70: só resolve o link quando a célula muda (motion é frequente)
            col, row = self.cell_at(ev.x, ev.y)
            if (row, col) != self._hover_cell:
                self._hover_cell = (row, col)
                self._set_hover_link(self._cell_uri(row, col))
        if self._sb_drag:
            self.scroll_to_y(ev.y - self.padding)
            return True
        if self.dragging:
            col, row = self.cell_at(ev.x, ev.y)
            if self.sel_start is None:
                # folga de arrasto: tremer o mouse com o botão apertado não
                # pode pintar uma célula em reverso (era a "seleção de 1")
                px, py = self.press_at or (ev.x, ev.y)
                if max(abs(ev.x - px), abs(ev.y - py)) <= DRAG_SLOP:
                    return True
                self.sel_start = self.press_anchor  # arrasto começa no press
            cell = t.anchor_at(self.view_off, row, col)
            if cell != self.sel_end:
                self.sel_end = cell
                self.queue_draw()
            return True
        if t.mouse_mode == 2 and self._held is not None:
            self.report_mouse(self._held, *self.cell_at(ev.x, ev.y), motion=True, px=ev.x, py=ev.y)
            return True
        if t.mouse_mode == 3:
            # movimento sem botão: código 35 (32 + "botão 3")
            self.report_mouse(
                mouse.RELEASE,
                *self.cell_at(ev.x, ev.y),
                motion=True,
                px=ev.x,
                py=ev.y,
            )
            return True
        return False

    def on_scroll(self, widget, ev):
        t = self.term
        self._state = ev.state
        if ev.direction == Gdk.ScrollDirection.SMOOTH:
            # touchpad (P48): frações que só valem quando completam um detente;
            # delta_y > 0 é pra baixo e o acumulador quer o sinal de "pra
            # trás" (o mesmo sinal do scroll_view). Eixo horizontal liso é
            # raro e continua sem efeito — o discreto (LEFT/RIGHT) funciona.
            n = self._wheel_v.add(-ev.delta_y)
            if not n:
                return True  # consumido: ainda não completou um passo
            if self.view_off or not t.mouse_mode:
                self.scroll_view(3 * n)
                return True
            col, row = self.cell_at(ev.x, ev.y)
            btn = mouse.WHEEL_UP if n > 0 else mouse.WHEEL_DOWN
            for _ in range(abs(n)):
                self.report_mouse(btn, col, row, True, px=ev.x, py=ev.y)
                self.report_mouse(btn, col, row, False, px=ev.x, py=ev.y)
            return True
        # detente inteiro (mouse): descarta a fração que o touchpad deixou,
        # senão este passo seria engolido pelo resto pendente do outro dispositivo
        self._wheel_v.reset()
        btn = {
            Gdk.ScrollDirection.UP: mouse.WHEEL_UP,
            Gdk.ScrollDirection.DOWN: mouse.WHEEL_DOWN,
            Gdk.ScrollDirection.LEFT: mouse.WHEEL_LEFT,
            Gdk.ScrollDirection.RIGHT: mouse.WHEEL_RIGHT,
        }.get(ev.direction)
        if btn is None:
            return False
        back = btn in (mouse.WHEEL_UP, mouse.WHEEL_LEFT)
        # lendo histórico: o wheel continua rolando a visão, não vai pro app
        if self.view_off or not t.mouse_mode:
            return self.scroll_view(3 if back else -3)
        col, row = self.cell_at(ev.x, ev.y)
        self.report_mouse(btn, col, row, True, px=ev.x, py=ev.y)
        self.report_mouse(btn, col, row, False, px=ev.x, py=ev.y)
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
    def selection_text(self):
        """Texto da seleção (bloco ou linear) sem copiar; None = sem seleção."""
        span = self.sel_span()
        if span is None:
            return None
        if self.sel_block:
            return self.term.anchor_block_text(*span)
        return self.term.anchor_text(*span)

    def copy(self, selection=Gdk.SELECTION_CLIPBOARD):
        """Copia a seleção — ou a viewport inteira, se não houver seleção."""
        # Sem `+ "\n"`: o kitty só junta as linhas com "\n" ENTRE elas, e o fim
        # de linha entra quando o arrasto chega na coluna 0 da linha seguinte
        # (aí a última "linha" da seleção é vazia). O newline incondicional
        # fazia colar "abcdef" executar `abcdef`.
        text = self.selection_text()
        if text is None:
            text = self.term.all_text(rows=self.visible_rows())
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
        if kv in (Gdk.KEY_Control_L, Gdk.KEY_Control_R):
            self._set_ctrl(True)
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
            ev.keyval,
            ev.state,
            self.dead_mark,
            self.term.app_cursor,
            self.term.kbd_flags,
            text=ev.string or "",
        )
        self._write_child(out or "")
        return handled

    def on_key_release(self, widget, ev):
        """Só existe release com a flag `report event types` (P5)."""
        if ev.keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R):
            self._set_ctrl(False)
        if not (self.term.kbd_flags & 2):
            return False
        out, _, handled = encode_key(
            ev.keyval,
            ev.state,
            0,
            self.term.app_cursor,
            self.term.kbd_flags,
            event=3,
        )
        self._write_child(out or "")
        return handled
