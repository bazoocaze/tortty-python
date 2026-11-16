"""The GTK window: workspaces (P12) and, inside each one, tabs (P11).

    TorttyWindow  Gtk.Box[ sidebar (Gtk.ListBox) | Gtk.Stack ]
    Workspace     one Gtk.Notebook + its TermViews + the sidebar card

Each workspace has its own set of tabs (`Gtk.Stack` instead of swapping pages of
the same notebook: that way each one keeps its selected tab, order and titles).
What belongs to a session lives in `view.py`; here there is only life cycle and
shortcuts.
"""

import os
import shlex
import signal
import sys

from . import config as config_mod
from . import debugsock, mouse, state, style
from .gui import Gdk, GdkX11, GLib, Gtk, Pango
from .term import DEFAULT_TITLE, row_text
from .view import TermView, set_debug_log, set_prof

SIDEBAR_W = 170  # largura fixa (arrastável fica pra depois)


def _geom():
    # PYTERM_GEOM=980x640 trava o tamanho: medir exige a mesma grade nos dois
    m = os.environ.get("PYTERM_GEOM", "")
    w, _, h = m.partition("x")
    if w.isdigit() and h.isdigit() and int(w) > 0 and int(h) > 0:
        return int(w), int(h)
    return 980, 640


TAB_TITLE_CHARS = 20  # aba: largura em chars, não em px (o título trunca)
BELL_FLASH_MS = 800  # `bell visual`: quanto tempo a aba fica marcada (P34)
NOTIF_TOAST_S = 8  # `OSC 9`/`777` na aba da frente: quanto tempo fica na tela
NOTIFY_BUS = "org.freedesktop.Notifications"  # daemon de notificação (P74)
NOTIFY_PATH = "/org/freedesktop/Notifications"
NOTIFY_TIMEOUT_MS = 1000
_styled = False  # o provider é da tela: aplica uma vez por processo
_provider = None


def apply_style(over=None):
    """Registra o CSS de `style.py` na tela e o recarrega com o chrome daqui.

    O provider é um só: chamar de novo troca o CSS na hora, que é o que o
    reload de configuração precisa (P75).
    """
    global _styled, _provider
    if _provider is None:
        _provider = Gtk.CssProvider()
    _provider.load_from_data(style.css(over).encode())
    if _styled:
        return
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        _provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    _styled = True


def _leaf_descendant(pid, depth=8):
    """Último descendente de `pid` (a cadeia `sh -c` -> programa)."""
    for _ in range(depth):
        try:
            with open(f"/proc/{pid}/task/{pid}/children") as f:
                kids = f.read().split()
        except OSError:
            return pid
        if not kids:
            return pid
        try:
            pid = int(kids[-1])
        except ValueError:
            return pid
    return pid


def _digit_of(ev):
    """Dígito "cru" da tecla física, ignorando Shift.

    `Ctrl+Shift+1` chega com keyval de `exclam` (`!`), e no ABNT2 o símbolo
    shiftado de cada dígito é outro (`2` → `@`, `6` → `¨`). Traduzir o keycode
    com estado zero dá o dígito em qualquer layout — mapear os símbolos à mão
    funcionaria no US e quebraria no ABNT2.
    """
    ok, kv, _, _, _ = Gdk.Keymap.get_default().translate_keyboard_state(
        ev.hardware_keycode, 0, ev.group
    )
    if ok and Gdk.KEY_0 <= kv <= Gdk.KEY_9:
        return kv - Gdk.KEY_0
    return None


def _card_info(text):
    """Texto pequeno da segunda linha do cartão (a cor vem da classe .info)."""
    return "<small>" + GLib.markup_escape_text(text) + "</small>"


def _widget_name(w):
    """Nome curto do widget para o `state`: classe do GTK e, se tiver, o nome."""
    nome = w.get_name() if hasattr(w, "get_name") else None
    cls = type(w).__name__
    return f"{cls}#{nome}" if nome else cls


def _progress_prefix(p):
    """Prefixo textual do `OSC 9;4` no rótulo da aba (P65), sem cor."""
    if p is None:
        return ""
    state, pct = p
    if state == 2:  # erro
        return "! · "
    if pct is not None:
        return f"{pct}% · "
    return "… · "  # 3 indeterminado, 4 pausado sem %, 1 sem %


def _status_markup(status):
    """`OSC 133;D` como marca colorida no rótulo da aba (P103), ou ""."""
    if status is None:
        return ""
    if status == 0:
        return f'<span foreground="{style.TAB_OK_FG}">✓</span> · '
    # o número só quando cabe: 127, 130 e 137 são os que dizem alguma coisa
    return f'<span foreground="{style.TAB_ERR_FG}">✗{status}</span> · '


def _progress_markup(p):
    """O progresso do `OSC 9;4` como markup: a cor do prefixo é do style."""
    texto = _progress_prefix(p)
    if not texto:
        return ""
    cor = style.TAB_ERR_FG if p[0] == 2 else style.CARD_FG
    return f'<span foreground="{cor}">{GLib.markup_escape_text(texto)}</span>'


class Workspace:
    """Um conjunto de abas + o cartão dele na lateral."""

    def __init__(self, win):
        self.win = win
        self.name = ""  # nunca renomeada: a linha 1 do cartão vira o título (P65)
        self.views = []
        self._tab_seq = 0  # nome da aba: o `state` diz qual delas tem o foco
        self._bell_timers = {}  # view -> (fonte do timer, contexto do rótulo)
        self._notif = set()  # views com badge de atenção (`OSC 9`/`777`, P44)
        self._tab_wheel = mouse.Notches()  # fração do touchpad na barra (P48)
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.connect("switch-page", self.on_switch_page)
        # arrastar a aba reordena as páginas sem tocar em `self.views`, e a
        # partir daí página 0 != views[0]: o foco do switch-page ia para uma aba
        # e o `view` (copiar, buscar, salvar layout) para outra
        self.notebook.connect("page-reordered", self.on_page_reordered)

        # cartão da lateral: "<n>  <nome|título>" e, embaixo, o título (P65)
        # ellipsize + max_width_chars(1): o texto deixa de definir a largura (o
        # mínimo o ellipsize já zera, o natural o max_width_chars) e quem manda
        # é o SIDEBAR_W; trunca no que sobrar, inteiro no tooltip (P14)
        self.name_label = Gtk.Label(xalign=0)
        self.info_label = Gtk.Label(xalign=0)
        for label in (self.name_label, self.info_label):
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_single_line_mode(True)
            label.set_max_width_chars(1)
        self.info_label.get_style_context().add_class("info")
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        vbox.set_border_width(6)
        vbox.pack_start(self.name_label, False, True, 0)  # fill: truncar no 170
        vbox.pack_start(self.info_label, False, True, 0)
        self.card = Gtk.EventBox()
        # o EventBox é transparente no CSS: quem pinta o fundo é a ListBoxRow,
        # senão o cartão cobre o :selected do tema
        self.card.get_style_context().add_class("card")
        # sem a máscara o EventBox tem janela e máscara vazia (get_events()==0)
        # e não chega nenhum clique
        self.card.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.card.connect("button-press-event", self.on_card_click)
        self.card.add(vbox)
        self.row = Gtk.ListBoxRow()
        self.row.add(self.card)
        self.update_card()

    # -- abas ---------------------------------------------------------
    @property
    def view(self):
        # a página do notebook é a verdade; `views` é só a ordem (e o arrasto de
        # aba já a desalinhou uma vez: índice aqui era foco na aba errada)
        page = self.notebook.get_nth_page(self.notebook.get_current_page())
        if isinstance(page, TermView):
            return page
        return self.views[0] if self.views else None

    def new_tab(self, cmd=None, cwd=None, restore=None):
        """Aba nova, herdando o cwd da corrente (ou o dado pela restauração, P50)."""
        v = TermView(
            cmd=cmd if cmd is not None else self.win.cmd,
            cwd=cwd if cwd is not None else self.win.current_cwd(self),
            restore=restore,  # P57: foto da execução anterior, se houver
            shell=self.win.shell,
            font_family=self.win.font_family,
            font_size=self.win.font_size,
            font_features=self.win.font_features,
            padding=self.win.padding,
            cursor_shape=self.win.cursor_shape,
            cursor_blink=self.win.cursor_blink,
            copy_on_select=self.win.copy_on_select,
            bold_as_bright=self.win.bold_as_bright,
            letter_spacing=self.win.letter_spacing,
            scrollback=self.win.config.scrollback,
            colors=self.win.config.colors,  # P49: as 19 chaves da configuração
            on_exit=self.on_view_exit,
            on_title=self.on_view_title,
            on_progress=self.on_view_progress,
            on_status=self.on_view_status,
            on_context=self.on_view_context,
            on_bell=self.win.on_view_bell,
            on_notify=self.win.on_view_notify,
            shortcuts=self.win.handle_shortcut,
        )
        self._tab_seq += 1
        v.set_name("tab%d" % self._tab_seq)
        self.views.append(v)
        # mesmo motivo do cartão (P14): sem limite o título longo vira largura
        # mínima e a janela inteira estica (o notebook se recusa a encolher)
        label = Gtk.Label()
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_width_chars(TAB_TITLE_CHARS)
        label.set_max_width_chars(TAB_TITLE_CHARS)
        self.set_tab_label(v, label)
        box = Gtk.EventBox()
        box.set_name("tablabel")  # alvo do CSS e do flash do bell (style.py)
        box.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.SMOOTH_SCROLL_MASK
        )
        box.add(label)
        box.connect("button-press-event", self.on_tab_click, v)
        box.connect("scroll-event", self.on_tab_scroll, v)
        v.tab_label = label  # atualizado no on_view_title
        v.tab_box = box  # o EventBox da aba: alvo do bell e do badge (P34/P44)
        self.notebook.append_page(v, box)
        self.notebook.set_tab_reorderable(v, True)
        # página recém-anexada nasce HIDDEN e o notebook ignora o
        # set_current_page enquanto ela não está visível (silencioso: a tecla
        # segue indo pra aba antiga)
        v.show_all()
        box.show_all()
        self.notebook.set_current_page(self.views.index(v))
        v.grab_focus()
        self.update_card()
        return v

    def close_tab(self, view=None):
        view = view or self.view
        if view is None:
            return False
        self._clear_bell(view)
        self._notif.discard(view)  # o rótulo vai embora com a remoção da página
        view.shutdown()
        if view in self.views:
            self.views.remove(view)
            page = self.notebook.page_num(view)
            if page >= 0:
                self.notebook.remove_page(page)
        if not self.views:
            self.win.close_workspace(self)  # última aba: fecha o workspace
        else:
            self.view.grab_focus()
            self.update_card()
        return True

    def select_tab(self, index):
        if 0 <= index < len(self.views):
            self.notebook.set_current_page(index)
            return True
        return False

    def on_tab_click(self, widget, ev, view):
        if ev.button == 3:  # P71: menu na aba
            return self.win.context_menu(ev, view=view)
        if ev.button == 2:  # clique do meio fecha a aba
            self.close_tab(view)
            return True
        if ev.button == 1:
            # devolver False deixa o press chegar no handler padrão do
            # GtkNotebook (é ele que permite arrastar a aba), e esse handler
            # leva o foco de teclado para o notebook: a digitação morria ali até
            # algo devolvê-la (P78). O padrão roda DEPOIS deste, então agarrar o
            # foco aqui não pega — o idle pega, e ele respeita o Entry de renomear.
            GLib.idle_add(self._focus_idle, view)
        return False

    def on_tab_scroll(self, widget, ev, view):
        """Roda sobre a barra: cicla uma aba por detente (P48).

        Cicla (com módulo) e não para na ponta: a intenção de rolar é seguir,
        e a lista de abas é curta.
        """
        if ev.direction == Gdk.ScrollDirection.SMOOTH:
            n = self._tab_wheel.add(-ev.delta_y)  # n>0 = pra cima
            if not n:
                return True
        else:
            self._tab_wheel.reset()  # detente inteiro não acumula fração
            n = 1 if ev.direction == Gdk.ScrollDirection.UP else -1
        if not self.views:
            return True
        # cicla a partir da aba ATIVA, não da aba sob o ponteiro: o gesto é
        # "andar pelas abas", e a barra inteira é um alvo só
        atual = self.view
        i = self.views.index(atual) if atual in self.views else 0
        self.select_tab((i - n) % len(self.views))
        return True

    def pages(self):
        """As views na ordem das páginas do notebook (o arrasto de aba muda esta)."""
        nb = self.notebook
        return [nb.get_nth_page(i) for i in range(nb.get_n_pages())]

    def on_page_reordered(self, nb, child, num):
        """A ordem das páginas é a verdade: a lista `views` passa a segui-la."""
        ordem = [w for w in self.pages() if isinstance(w, TermView)]
        if len(ordem) == len(self.views):
            self.views = ordem
            self.update_card()

    def on_switch_page(self, nb, page, page_num):
        # a view vem do sinal, não de `views[page_num]`: o índice só coincide com
        # a lista enquanto ninguém arrastou uma aba
        v = page if isinstance(page, TermView) else None
        if v is None:
            return
        # grab_focus aqui não pega: no instante do switch-page a página nova
        # ainda não está mapeada e o foco fica no notebook (as teclas seguintes
        # não chegavam em ninguém). Um idle resolve.
        GLib.idle_add(self._focus_idle, v)
        v.queue_draw()  # aba escondida não recebe size-allocate
        # visitar a aba reconhece o aviso (`OSC 9`/`777`, P44)
        self.clear_notif(v)
        # dentro do switch-page o notebook ainda responde a página ANTIGA em
        # get_current_page(): usar a view do sinal, senão cartão e título ficam
        # uma troca atrás (B21)
        self.update_card(v)
        self.win.sync_title(v)

    def _focus_idle(self, v):
        # não roubar o foco do Gtk.Entry de renomear o cartão: o clique que
        # seleciona o workspace agenda este idle, e ele rodava DEPOIS do
        # grab_focus do entry (a digitação do nome ia pro terminal)
        w = self.win.get_focus()
        if w is not None and w is not v and isinstance(w, Gtk.Entry):
            return False
        v.grab_focus()
        return False

    def set_tab_label(self, view, label=None):
        """Rótulo da aba: prefixo colorido (P103/P65) + título, e o tooltip.

        `set_tab_label_text` TROCARIA o widget do rótulo (e com ele o EventBox do
        clique do meio), então mexe no Label guardado. O prefixo vai em markup
        porque a cor vem do `style.py`; o título é escapado, nunca é markup.
        """
        label = label if label is not None else getattr(view, "tab_label", None)
        if label is None:
            return
        prefixo = _status_markup(view.term.cmd_status)
        prefixo += _progress_markup(view.term.progress)
        label.set_markup(prefixo + GLib.markup_escape_text(self.label_text(view)))
        label.set_tooltip_text(self.label_text(view, progress=True))

    def on_view_title(self, view, title):
        self.set_tab_label(view)
        self.update_card()
        if view is self.view:
            self.win.sync_title()

    def on_view_progress(self, view, progress):
        """`OSC 9;4`: o progresso entra no rótulo da aba (P65)."""
        self.set_tab_label(view)

    def on_view_status(self, view, status):
        """`OSC 133;D`: o status do último comando da aba (P103)."""
        self.set_tab_label(view)

    def on_view_context(self, view, ev):
        """Botão direito na sessão: o menu da janela (P71)."""
        return self.win.context_menu(ev, view=view)

    def on_view_exit(self, view):
        """O shell da aba morreu: fecha a aba (P8, agora por aba)."""
        self.win.dump()
        self.close_tab(view)

    def flash_tab(self, view):
        """`bell visual` (P34): marca a aba por BELL_FLASH_MS."""
        box = self.notebook.get_tab_label(view)
        if box is None:
            return
        self._clear_bell(view)  # flash anterior desta aba, se ainda estava lá
        ctx = box.get_style_context()
        ctx.add_class("bell")

        def off():
            self._clear_bell(view)
            return False

        self._bell_timers[view] = (GLib.timeout_add(BELL_FLASH_MS, off), ctx)

    def _clear_bell(self, view):
        """Tira o flash (timer + classe do rótulo). Também no fechar da aba."""
        ent = self._bell_timers.pop(view, None)
        if ent:
            GLib.source_remove(ent[0])
            ent[1].remove_class("bell")

    def mark_notif(self, view):
        """`OSC 9`/`777` numa aba que não está na frente (P44): badge.

        Diferente do flash do bell, o badge não tem timer: fica até a aba ser
        visitada, senão o aviso pisca e some enquanto ninguém olha.
        """
        box = getattr(view, "tab_box", None)
        if box is None or view in self._notif:
            return
        self._notif.add(view)
        box.get_style_context().add_class("notif")
        self.update_card()

    def clear_notif(self, view):
        """Visitar a aba reconhece o aviso: tira o badge dela."""
        if view not in self._notif:
            return
        self._notif.discard(view)
        box = getattr(view, "tab_box", None)
        if box is not None:
            box.get_style_context().remove_class("notif")
        self.update_card()

    def label_text(self, view, progress=False):
        """Rótulo da aba: título do app ou, sem OSC, o cwd da sessão.

        O bash não manda OSC 0/2 por padrão, então todas as abas ficariam
        com o título padrão; o diretório é a informação que o usuário usa pra saber onde
        está (o `Alt+N` já dá o número, por isso não tem prefixo numérico).
        """
        if view.app_title and view._title:
            text = view._title
        else:
            # sem OSC 0/2: o cwd do shell — `OSC 7` quando ele avisa (P47), senão o
            # diretório com que a sessão nasceu
            cwd = view.term.cwd or view.start_cwd
            text = os.path.basename(cwd or "") or "TorTTY (Python)"
        # os prefixos (status P103, progresso P65) só no rótulo da aba e no
        # tooltip: título da janela, cartão e dump ficam limpos
        if not progress:
            return text
        st = view.term.cmd_status
        marca = "" if st is None else ("✓ · " if st == 0 else f"✗{st} · ")
        return marca + _progress_prefix(view.term.progress) + text

    # -- cartão da lateral ---------------------------------------------
    def update_card(self, v=None):
        """Cartão da lateral: número, nome (ou o título, quando sem nome)."""
        try:
            n = self.win.workspaces.index(self) + 1
        except ValueError:
            n = 0
        v = v if v is not None else self.view
        title = self.label_text(v) if v is not None else "-"
        if self.name:
            line1 = f"<b>{n}</b>  {GLib.markup_escape_text(self.name)}"
            line2 = title
            tip = f"{n}. {self.name}\n{title}"
        else:
            # nunca renomeada (como o Rust `card_lines`): a linha 1 é o título
            # e a 2 fica em branco — o espaço mantém a altura de duas linhas (P65)
            line1 = f"<b>{n}</b>  {GLib.markup_escape_text(title)}"
            line2 = " "
            tip = f"{n}. {title}"
        if self._notif:  # aviso esperando visita (`OSC 9`/`777`, P44)
            line2 = "• " + line2
        self.name_label.set_markup(line1)
        self.info_label.set_markup(_card_info(line2))
        self.card.set_tooltip_text(tip)

    def on_card_click(self, widget, ev):
        if ev.button == 3:  # P71: menu no cartão da sidebar
            return self.win.context_menu(ev, ws=self)
        if ev.type == Gdk.EventType._2BUTTON_PRESS and ev.button == 1:
            self.start_rename()
            return True
        if ev.button == 2:
            self.win.close_workspace(self)
            return True
        if ev.button == 1:
            self.win.select_workspace(self)
            return True
        return False

    def start_rename(self):
        """Duplo clique no cartão: edita o nome no lugar."""
        box = self.card.get_child()
        entry = Gtk.Entry()
        entry.set_width_chars(6)  # mínimo, não largura: ver P14
        entry.set_text(self.name)
        box.remove(self.name_label)
        box.pack_start(entry, False, False, 0)
        box.reorder_child(entry, 0)
        entry.show()
        entry.grab_focus()
        done = []

        def finish(keep):
            if done:
                return False
            done.append(True)
            novo = entry.get_text().strip()
            if keep:  # vazio limpa o nome (a linha 1 volta ao título, P65)
                self.name = novo
            box.remove(entry)
            box.pack_start(self.name_label, False, False, 0)
            box.reorder_child(self.name_label, 0)
            self.name_label.show()
            self.update_card()
            # o Entry removido leva o foco embora: sem isto a digitação e os
            # atalhos param de chegar até alguém (a sessão ficava surda)
            if self.view is not None:
                self.view.grab_focus()
            return False

        entry.connect("activate", lambda *_: finish(True))
        entry.connect("focus-out-event", lambda *_: finish(True))
        entry.connect("key-press-event", self._rename_key)
        self._rename_finish = finish
        return True

    def _rename_key(self, entry, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self._rename_finish(False)
            return True
        return False


class TorttyWindow(Gtk.Window):
    def __init__(
        self,
        cmd=None,
        quit_after=0,
        dump_to=None,
        config_path=None,
        debug_log=None,
        debug_socket=None,
        cols=None,
        rows=None,
        over=None,
    ):
        super().__init__(title="TorTTY (Python)")
        # O comando dado na linha de comando é replicado em cada aba nova
        # (decisão do P11): `run.sh --cmd ...` e os testes continuam
        # previsíveis. Sem `--cmd`, cada aba nasce com o `shell` da configuração.
        # P98: a linha de comando vence o arquivo, como no Rust
        self._over = dict(over or {})
        self.config = config_mod.load(config_path, self._over)
        self._cmd_fixo = cmd is not None  # --cmd não é sobrescrito pela config
        # bruto: vazio herda o $SHELL do ambiente, e quem resolve é a view
        self.shell = self.config.shell
        self.cmd = cmd if cmd is not None else self.shell
        self.dump_to = dump_to
        self.quit_after = quit_after
        # --debug-log vence a configuração (como o --cmd vence o `shell`)
        self._debug_log_cli = debug_log
        self.workspaces = []
        # fonte e demais opções vêm da configuração (P34); padrão 12 pontos
        self._apply_options()
        self._closing = False
        # geometria lembrada entre execuções. Com PYTERM_GEOM quem manda é o
        # protocolo de medição: não restaura e não salva (a grade do bench
        # precisa ser a mesma nos dois terminais comparados).
        # --cols/--rows (P63) também travam a grade: quem manda é a linha de
        # comando, então a sessão anterior não é restaurada nem regravada
        self._pin = (cols, rows)
        # P91: one owner of the state. A probe (--cmd), `restore_state none` and
        # a pinned grid never take the lock, so they leave the hot session alone.
        dono = (
            not os.environ.get("PYTERM_GEOM")
            and not any(self._pin)
            and cmd is None
            and self.config.restore_state != "none"
        )
        self._lock = state.lock() if dono else None
        self._remember = dono and self._lock is not None
        self._saved = (state.load() or {}) if self._remember else {}
        self._max = bool(self._saved.get("max"))
        # P50: layout da sessão anterior (workspaces, abas e o cwd de cada
        # uma); consumido por new_workspace no startup. `restore_state none`
        # (ou PYTERM_GEOM, que já zera o _saved) não tem o que restaurar.
        # `content` (P57) restaura o layout E a foto de cada aba.
        lay = (
            state.layout(self._saved)
            if self.config.restore_state in ("layout", "content")
            else None
        )
        self._restore = lay
        self._restore_front = (lay["ws"], lay["tab"]) if lay else None

        self.bindings = self.config.bindings  # P95: a tabela de atalhos do config
        apply_style(self.config.chrome)
        self.sidebar = Gtk.ListBox()
        self.sidebar.set_name("sidebar")  # alvo do CSS (style.py)
        # roda sobre a lateral: anda um cartão por detente (P48)
        self.sidebar.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.sidebar.connect("scroll-event", self.on_sidebar_scroll)
        # arquivo solto em qualquer ponto da janela vira o caminho colado (P62)
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self.on_drop)
        self._side_wheel = mouse.Notches()
        self.sidebar.set_size_request(SIDEBAR_W, -1)
        self.sidebar.set_visible(False)  # só com 2+ workspaces
        # sem isto o show_all() da janela mostra a lateral de novo e ela come
        # 170 px da grade mesmo com um workspace só (P17)
        self.sidebar.set_no_show_all(True)
        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        hbox.pack_start(self.sidebar, False, False, 0)
        hbox.pack_start(self.stack, True, True, 0)
        # toast (P33): aviso sobre a grade, estilo Android. Fica num
        # Gtk.Overlay para não tirar espaço de nada. Dura 3 s quando é ok e
        # 10 s nos outros; clique dispensa (no erro abre a configuração); com
        # um visível o novo espera na fila em vez de perder o anterior.
        self.overlay = Gtk.Overlay()
        self.overlay.add(hbox)
        self.toast = Gtk.Revealer()
        self.toast.set_valign(Gtk.Align.END)
        self.toast.set_halign(Gtk.Align.CENTER)
        self.toast.set_margin_bottom(28)
        self.toast.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.toast.set_transition_duration(220)
        # EventBox e não Label: o #toast precisa de um widget que pinte o
        # fundo do CSS (label não pinta de forma confiável no GTK3)
        self.toast_box = Gtk.EventBox()
        self.toast_box.set_name("toast")
        self.toast_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.toast_box.connect("button-press-event", self._on_toast_click)
        # o EventBox ignora padding do CSS no tamanho: quem respira é a
        # caixa interna, com meia altura da fonte em todos os lados
        self.toast_corpo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.toast_barra = Gtk.EventBox()
        self.toast_barra.get_style_context().add_class("barra")
        self.toast_barra.set_size_request(4, -1)
        self.toast_textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        textos = self.toast_textos
        # a mesma fonte da grade (config P34): o toast acompanha fonte/tamanho
        self.toast_titulo = Gtk.Label()
        self.toast_titulo.set_xalign(0)
        self.toast_detalhe = Gtk.Label()
        self.toast_detalhe.get_style_context().add_class("detalhe")
        self.toast_detalhe.set_xalign(0)
        self.toast_detalhe.set_line_wrap(True)
        self._set_toast_font()
        # sem teto de largura: o detalhe cresce até a borda e quebra
        textos.pack_start(self.toast_titulo, False, False, 0)
        textos.pack_start(self.toast_detalhe, False, False, 0)
        self.toast_corpo.pack_start(self.toast_barra, False, False, 0)
        self.toast_corpo.pack_start(textos, False, False, 0)
        self.toast_box.add(self.toast_corpo)
        self.toast.add(self.toast_box)
        # show_all() não pode revelá-lo: quem mostra é o show_toast
        for w in (
            self.toast,
            self.toast_box,
            self.toast_corpo,
            self.toast_barra,
            self.toast_textos,
            self.toast_titulo,
            self.toast_detalhe,
        ):
            w.set_no_show_all(True)
        self.overlay.add_overlay(self.toast)
        self._toast_timer = 0
        self._toast_queue = []  # (titulo, detalhe, erro, aviso, segs) à espera
        self._toast_erro = False  # o visível é erro? (clique abre a config)
        self._toast_pad = None  # meia altura da fonte, medida no 1º show
        self.add(self.overlay)
        # 680x420 casava com a fonte de 16 px; com 13 pontos (23 px nesta tela)
        # a grade caía para 48x14. 980x640 devolve ~70x20.
        geom = state.fit(
            self._saved.get("x"),
            self._saved.get("y"),
            self._saved.get("w"),
            self._saved.get("h"),
            self._monitors(),
        )
        self.set_default_size(*(geom[2:] if geom else _geom()))
        if geom:
            self.move(geom[0], geom[1])
        if self._max:
            self.maximize()
        # a geometria é guardada a cada configure: no destroy o Gtk já devolveu
        # o tamanho padrão (medido: salvava 980x640 com a janela em 920x610)
        self.connect("configure-event", self.on_configure)
        self.connect("window-state-event", self.on_window_state)
        self.connect("destroy", self.on_destroy)
        # a view trata e retorna True (o sinal não sobe); este handler é a
        # rede pra quando o foco NÃO está numa sessão (cartão da lateral,
        # Entry de renomear, notebook)
        self.connect("key-press-event", self.on_window_key)

        self.new_workspace()
        self._restore_session()  # P50: workspaces restantes + a que estava na frente
        # aviso de configuração (P33) só depois da janela existir. Na carga
        # inicial o que validou já valeu (P34): o toast mostra o PRIMEIRO erro,
        # com a contagem dos outros, em vez da lista inteira.
        if not self.config.ok:
            self.show_toast("Configuration error", config_mod.first_error(self.config), erro=True)
        elif self.config.warnings:
            self.show_toast("Configuration warning", config_mod.message(self.config), aviso=True)
        # a referência tem de sobreviver: sem ela o Gio.FileMonitor é coletado
        # e o auto-reload simplesmente não acontece (monitor mudo)
        self._conf_monitor = config_mod.watch(self.reload_config, self.config.path)
        if quit_after:
            GLib.timeout_add_seconds(quit_after, self._on_quit_after)
        # SIGUSR1 dumpar as abas na hora (depuração: "kill -USR1 <pid>")
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, self._on_dump_signal)
        # SIGTERM fecha como o --quit-after: o dump e o prof saem no fim
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._on_term_signal)
        # socket de introspecção (P35): só com --debug-socket, desligado por
        # omissão; `auto` resolve para o arquivo com o pid em XDG_RUNTIME_DIR
        self._debugsock = None
        caminho = debugsock.resolve(debug_socket)
        if caminho:
            self._debugsock = debugsock.Server(caminho, self)
            erro = self._debugsock.start()
            if erro:
                self._debugsock = None
                self.show_toast("Debug socket", erro, erro=True)
            else:
                # superfície de debug: só existe com a flag, mas quem abriu tem
                # de saber que ela está de pé
                self.show_toast(
                    "Security warning",
                    "debug socket enabled: %s" % caminho,
                    aviso=True,
                )

    # -- introspecção (--debug-socket, P35) -----------------------------
    def debug_state(self):
        """O que o agente precisa ver de uma vez, inclusive o que o dump omite."""
        v = self.view
        t = v.term if v is not None else None
        return {
            "pid": os.getpid(),
            "xid": self._xid(),
            "cols": t.cols if t else 0,
            "rows": t.rows if t else 0,
            "cursor": [t.cy, t.cx] if t else None,
            "title": t.title if t else "",
            "notifs": t.notifs if t else 0,  # `OSC 9`/`777` na aba da frente
            "notif_pending": len(self.current._notif) if self.current else 0,
            "view_off": v.view_off if v is not None else 0,
            "pin": v._pin_off if v is not None else 0,
            "sync": bool(t.sync_output) if t else False,
            "scrolled": t.scrolled if t else 0,
            "scrollback": len(t.scrollback) if t else 0,
            "tabs": len(self.views),
            # as duas ordens de aba lado a lado: `tab_order` é o que a barra
            # mostra, `views_order` é a lista que o app percorre — o arrasto de
            # aba já as separou (foco numa aba, copiar/buscar em outra)
            "tab_order": [w.get_name() for w in self.current.pages()] if self.current else [],
            "views_order": [w.get_name() for w in self.current.views] if self.current else [],
            "page": self.current.notebook.get_current_page() if self.current else -1,
            "workspaces": len(self.workspaces),
            # a ORDEM importa: é o que prova o `ws_move_up`/`ws_move_down` (P97)
            "workspace_names": [w.name or self._stack_name(w) for w in self.workspaces],
            "config": str(self.config.path),
            "errors": list(self.config.errors),
            "focus": self._focus_name(),
            **(v.debug_metrics() if v is not None else {}),
        }

    def _focus_name(self):
        """Quem tem o foco de teclado: classe do widget e se é a view da frente.

        O teclado só chega no terminal com o foco na view; sem isso o `state`
        dizia que estava tudo bem enquanto a digitação ia para o notebook (P78).
        """
        w = self.get_focus()
        if w is None:
            return None
        return _widget_name(w)

    def _xid(self):
        """XID da janela: quem vai capturar pixel pergunta ao app, não ao X."""
        try:
            gdkwin = self.get_window()
            return int(GdkX11.X11Window.get_xid(gdkwin)) if gdkwin else 0
        except (AttributeError, TypeError):
            return 0

    def debug_prof(self, on=None):
        """Contadores de custo; `on` liga/desliga a medição em execução."""
        if on is not None:
            set_prof(on)
        v = self.view
        return v.debug_prof() if v is not None else {"on": bool(on), "etapas": {}}

    def debug_resize(self, cols, rows):
        """Redimensiona a JANELA para caber cols x rows; o resultado vem no
        próximo `state` (a alocação e o TIOCSWINSZ acontecem no ciclo do Gtk)."""
        v = self.view
        if v is None:
            return {"requested": [0, 0], "cols": 0, "rows": 0}
        cols, rows = max(1, int(cols)), max(1, int(rows))
        cw, ch = v.metrics()
        w = self.get_allocated_width() + (cols - v.term.cols) * cw
        h = self.get_allocated_height() + (rows - v.term.rows) * ch
        self.resize(max(1, w), max(1, h))
        return {"requested": [cols, rows]}

    def debug_keys(self, spec):
        """Tecla pelo caminho do app (atalho, scroll, encoder), não pelo pty."""
        nome, mods = debugsock.parse_key(spec)
        # o keysym é `F13`, `Page_Up`; quem digita no socket manda minúsculo
        keyval = 0
        for cand in (nome, nome.capitalize(), nome.title(), nome.upper()):
            kv = Gdk.keyval_from_name(cand)
            if kv != Gdk.KEY_VoidSymbol:
                keyval = kv
                break
        if not keyval and len(nome) == 1:
            keyval = ord(nome)
        if not keyval:
            raise ValueError("tecla desconhecida: %s" % nome)
        mascaras = {
            "ctrl": Gdk.ModifierType.CONTROL_MASK,
            "shift": Gdk.ModifierType.SHIFT_MASK,
            "alt": Gdk.ModifierType.MOD1_MASK,
            "super": Gdk.ModifierType.SUPER_MASK,
        }
        ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        estado = Gdk.ModifierType(0)  # flags, não int: o campo exige o tipo
        for m in mods:
            estado |= mascaras[m]
        ev.keyval = keyval
        ev.state = estado
        # um evento de teclado de verdade traz o texto em `string` (o encoder e
        # a barra de busca leem daí); sem isto o socket não digita texto (P94)
        ev.string = chr(keyval) if 0x20 <= keyval <= 0x10FFFF else ""
        # keycode físico real: `_digit_of` (Alt+1..9) traduz o keycode com o
        # estado zerado, e 0 devolve "não sei" — sem isto os atalhos de dígito
        # morriam no socket (a tecla vazava pro pty e digitava sozinha)
        ok, entradas = Gdk.Keymap.get_default().get_entries_for_keyval(keyval)
        ev.hardware_keycode = entradas[0].keycode if ok and entradas else 0
        v = self.view
        if v is None:
            return {"key": nome, "mods": list(mods), "handled": False}
        return {"key": nome, "mods": list(mods), "handled": bool(v.on_key(v, ev))}

    def debug_text(self, where="view", start=0, count=40):
        """Linhas do que a tela mostra (`view`), da grade viva ou do histórico."""
        v = self.view
        if v is None:
            return []
        t = v.term
        start, count = max(0, int(start)), max(1, min(int(count), 2000))
        if where == "history":
            linhas = t.scrollback[start : start + count]
            return [row_text(row).rstrip() for row in linhas]
        if where == "screen":
            return [t.row_text(y).rstrip() for y in range(start, min(t.rows, start + count))]
        linhas = t.visible_rows(v.view_off)[start : start + count]
        return [row_text(row).rstrip() for row in linhas]

    def debug_sel(self):
        """Seleção atual: o texto e se é bloco (o verbo `sel` do Rust)."""
        v = self.view
        if v is None:
            return {"text": None, "block": False}
        return {"text": v.selection_text(), "block": bool(v.sel_block)}

    def debug_drop(self, path):
        """O que um arquivo solto na janela faz, sem precisar de origem XDND."""
        v = self.view
        if v is None:
            raise ValueError("sem aba")
        v.drop_path(path)
        return {"path": path}

    def debug_write(self, data):
        """Bytes crus no pty, como se o usuário tivesse digitado."""
        v = self.view
        if v is not None and v.master is not None:
            os.write(v.master, data.encode("utf-8", "replace"))

    def debug_log(self, value):
        """Liga/desliga/troca o caminho do `debug_log` em execução."""
        caminho = config_mod.debug_log_path(value)
        set_debug_log(caminho)
        return caminho or "off"

    def debug_quit(self):
        """Fecha o app: o destroy vai no idle, senão a resposta não sai."""
        GLib.idle_add(self._debug_quit_now)
        return True

    def _debug_quit_now(self):
        self.destroy()  # -> on_destroy -> dump, shutdown das views e Gtk.main_quit
        return False

    # -- configuração (P33/P34) ----------------------------------------
    def _apply_options(self):
        """Opções da config que viram atributo da janela (fonte, padding...)."""
        cfg = self.config
        self.font_family = cfg.font_family
        self.font_size = cfg.font_size
        self.font_features = cfg.ligature_features
        self.padding = cfg.padding
        self.cursor_shape = cfg.cursor_shape
        self.cursor_blink = cfg.cursor_blink
        self.copy_on_select = cfg.copy_on_select
        self.bold_as_bright = cfg.bold_as_bright  # P64: negrito como o xterm
        self.letter_spacing = cfg.letter_spacing  # P64: px extra na célula
        # log JSONL de depuração do ?2026: `off` desliga, o CLI vence a config
        log = self._debug_log_cli
        set_debug_log(config_mod.debug_log_path(log if log is not None else cfg.debug_log))
        if getattr(self, "toast_titulo", None) is not None:
            self._set_toast_font()

    def _set_toast_font(self):
        """Toast com a fonte da grade (segue a config, inclusive no reload)."""
        d = Pango.FontDescription()
        d.set_family(self.font_family)
        d.set_size(round(self.font_size * Pango.SCALE))
        for label in (self.toast_titulo, self.toast_detalhe):
            label.override_font(d)
        self._toast_pad = None  # a meia altura da fonte mudou: remede no 1º show

    def on_view_bell(self, view):
        """BEL do app (P34): `bell visual` marca a aba, `audible` apita."""
        modo = self.config.bell
        if modo == "audible":
            Gdk.beep()
        elif modo == "visual":
            for ws in self.workspaces:
                if view in ws.views:
                    ws.flash_tab(view)
                    break

    def on_view_notify(self, view, text):
        """`OSC 9`/`777` (P44): a aba da frente mostra, a de trás ganha badge.

        A urgência vai sempre: quem decide piscar a janela é o WM, e o aviso
        pode chegar com o terminal atrás de outra janela.
        """
        gdkwin = self.get_window()
        if gdkwin is not None:
            gdkwin.set_urgency_hint(True)
        if not self.is_active():
            self.notify_desktop(text)  # P74: fora da frente, o daemon avisa
        ws = self.current
        if ws is not None and view is ws.view:
            self.show_toast("Notification", text, segundos=NOTIF_TOAST_S)
            return
        for w in self.workspaces:
            if view in w.views:
                w.mark_notif(view)  # badge: fica até a visita
                break

    def notify_desktop(self, texto):
        """`OSC 9`/`777` no daemon de notificação (P74); sem ele, silêncio.

        Não somos um `Gtk.Application`, então a chamada é D-Bus direta — e o
        terminal continua funcionando igual em sessão sem daemon.
        """
        try:
            from gi.repository import Gio

            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync(
                NOTIFY_BUS,
                NOTIFY_PATH,
                NOTIFY_BUS,
                "Notify",
                GLib.Variant(
                    "(susssasa{sv}i)",
                    ("tortty-python", 0, "", "Terminal", texto, [], {}, -1),
                ),
                None,
                Gio.DBusCallFlags.NONE,
                NOTIFY_TIMEOUT_MS,
                None,
            )
        except Exception:
            pass  # sem barramento de sessão ou sem daemon: só a janela piscou

    def show_toast(self, titulo, detalhe="", erro=False, aviso=False, segundos=None):
        """Aviso flutuante na base da janela, como no Android."""
        if segundos is None:
            segundos = 3 if not (erro or aviso) else 10
        if self.toast.get_reveal_child():  # um visível: entra na fila
            self._toast_queue.append((titulo, detalhe, erro, aviso, segundos))
            return
        self._show_toast(titulo, detalhe, erro, aviso, segundos)

    def _show_toast(self, titulo, detalhe, erro, aviso, segundos):
        if self._toast_pad is None:  # meia altura da fonte do toast
            lay = self.toast_titulo.create_pango_layout("Xg")
            self._toast_pad = max(1, round(lay.get_pixel_size()[1] / 2))
            self.toast_corpo.set_border_width(self._toast_pad)
        self.toast_titulo.set_text(titulo)
        self.toast_detalhe.set_text(detalhe)
        if detalhe:
            self.toast_detalhe.show()
        self._toast_erro = erro
        ctx = self.toast_box.get_style_context()
        if erro:
            ctx.add_class("erro")
            ctx.remove_class("aviso")
        elif aviso:
            ctx.add_class("aviso")
            ctx.remove_class("erro")
        else:
            ctx.remove_class("erro")
            ctx.remove_class("aviso")
        # show(), não show_all(): com no_show_all ligado o show_all() não faz
        # nada nem chamado direto no widget (a caixa ficava invisível)
        self.toast_corpo.show()
        self.toast_barra.show()
        self.toast_textos.show()
        self.toast_titulo.show()
        self.toast_detalhe.set_visible(bool(detalhe))
        self.toast_box.show()
        self.toast.show()
        self.toast.set_reveal_child(True)
        if self._toast_timer:
            GLib.source_remove(self._toast_timer)
        self._toast_timer = GLib.timeout_add_seconds(segundos, self._hide_toast)

    def _hide_toast(self):
        self._toast_timer = 0
        self._toast_next()
        return False

    def _toast_next(self):
        """Timer estourou ou clique dispensou: próximo da fila ou esconde."""
        if self._toast_queue:
            self._show_toast(*self._toast_queue.pop(0))
        else:
            self.toast.set_reveal_child(False)

    def _on_toast_click(self, _w, _ev):
        """Clique dispensa o aviso; no erro abre a configuração."""
        if self._toast_erro:
            self.open_config()
        if self._toast_timer:
            GLib.source_remove(self._toast_timer)
            self._toast_timer = 0
        self._toast_next()
        return True

    def open_config(self):
        """Editar o arquivo de configuração no vim, em aba nova."""
        ws = self.current
        if ws is None:
            return
        conf = str(self.config.path)
        conf_path = os.path.dirname(conf)
        try:
            os.makedirs(conf_path, exist_ok=True)  # vim cria o arquivo ao salvar
        except OSError:
            pass
        ws.new_tab(cmd="vim %s" % shlex.quote(conf))

    def reload_config(self):
        """Arquivo mudou: valida antes de aplicar; inválido mantém o anterior."""
        novo = config_mod.load(self.config.path)
        if not novo.ok:
            self.show_toast("Configuration error", config_mod.message(novo), erro=True)
            return
        self.config = novo
        self.shell = novo.shell
        if not getattr(self, "_cmd_fixo", False):
            self.cmd = self.shell  # vale para as próximas abas
        self._apply_options()  # fonte/padding/cursor valem em TODAS as abas
        self.bindings = novo.bindings  # P95: a tabela também muda a quente
        apply_style(novo.chrome)  # P75: o chrome também muda a quente
        for ws in self.workspaces:
            for v in ws.views:
                v.apply_config(novo)
        aviso = config_mod.message(novo)
        if aviso:
            self.show_toast("Configuration warning", aviso, aviso=True)
            return
        self.show_toast("Configuration applied", "%s %g pt" % (novo.font_family, novo.font_size))

    # -- workspaces ----------------------------------------------------
    @property
    def current(self):
        i = self.stack.get_visible_child_name()
        for ws in self.workspaces:
            if self._stack_name(ws) == i:
                return ws
        return self.workspaces[0] if self.workspaces else None

    @property
    def view(self):
        ws = self.current
        return ws.view if ws is not None else None

    @property
    def views(self):
        ws = self.current
        return ws.views if ws is not None else []

    @staticmethod
    def _stack_name(ws):
        return f"ws{id(ws)}"

    def new_workspace(self):
        """Workspace novo, com uma aba herdando o cwd do workspace atual.

        No startup o `layout` salvo (P50) dá nome e cwds; ele vai sendo
        consumido, então as chamadas do usuário depois disso são normais.
        """
        mem = None
        if self._restore and self._restore["workspaces"]:
            mem = self._restore["workspaces"].pop(0)
        ws = Workspace(self)
        if mem:
            ws.name = mem["name"]
        # P57: com `content`, cada aba volta com a foto da execução anterior. O
        # índice é o da posição no layout (é o mesmo que nomeia o arquivo), e só
        # vale quando o layout também está sendo restaurado.
        iws = len(self.workspaces)
        foto = mem is not None and self.config.restore_state == "content"
        self.workspaces.append(ws)
        self.stack.add_named(ws.notebook, self._stack_name(ws))
        self.sidebar.add(ws.row)
        ws.notebook.show_all()
        ws.row.show_all()
        self.select_workspace(ws)
        cwds = mem["cwds"] if mem else [None]
        for k, cwd in enumerate(cwds):
            ws.new_tab(cwd=cwd, restore=state.load_snapshot(iws, k) if foto else None)
        self.sidebar.set_visible(len(self.workspaces) > 1)
        return ws

    def _restore_session(self):
        """P50: cria as workspaces restantes do salvo e põe a frente na dele."""
        while self._restore and self._restore["workspaces"]:
            self.new_workspace()
        front, self._restore_front = self._restore_front, None
        if front is None:
            return
        iws, itab = front
        if iws < len(self.workspaces):
            ws = self.workspaces[iws]
            self.select_workspace(ws)
            if itab < len(ws.views):
                ws.notebook.set_current_page(itab)

    def select_workspace(self, ws):
        if ws not in self.workspaces:
            return False
        self.stack.set_visible_child_name(self._stack_name(ws))
        self.sidebar.select_row(ws.row)
        v = ws.view
        if v is not None:
            GLib.idle_add(ws._focus_idle, v)
        ws.update_card()
        self.sync_title()
        return True

    def select_workspace_index(self, index):
        if 0 <= index < len(self.workspaces):
            return self.select_workspace(self.workspaces[index])
        return False

    def on_sidebar_scroll(self, widget, ev):
        """Roda sobre a lateral: anda um cartão por detente (P48).

        A lista não rola (cabe na janela), então "andar" é trocar a seleção —
        o gesto do Rust traduzido para a sidebar que existe aqui.
        """
        if ev.direction == Gdk.ScrollDirection.SMOOTH:
            n = self._side_wheel.add(-ev.delta_y)  # n>0 = pra cima
            if not n:
                return True
        else:
            self._side_wheel.reset()  # detente inteiro não acumula fração
            n = 1 if ev.direction == Gdk.ScrollDirection.UP else -1
        if not self.workspaces:
            return True
        ws = self.current
        i = self.workspaces.index(ws) if ws in self.workspaces else 0
        self.select_workspace_index((i - n) % len(self.workspaces))
        return True

    def context_menu(self, ev, ws=None, view=None):
        """Botão direito: as mesmas ações dos atalhos, sem lógica nova (P71)."""
        ws = ws or self.current
        if ws is None:
            return False
        view = view or ws.view
        m = Gtk.Menu()
        itens = (
            ("Copiar", lambda: view.copy() if view else None),
            ("Colar", lambda: view.paste() if view else None),
            ("", None),
            ("Nova aba", ws.new_tab),
            ("Fechar aba", lambda: ws.close_tab(view)),
            ("", None),
            ("Renomear espaço de trabalho", ws.start_rename),
            ("Novo espaço de trabalho", self.new_workspace),
            ("Fechar espaço de trabalho", lambda: self.close_workspace(ws)),
        )
        for rotulo, acao in itens:
            if acao is None:
                m.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem(label=rotulo)
            item.connect("activate", lambda _w, f=acao: f())
            m.append(item)
        m.show_all()
        self._menu = m  # o menu precisa viver enquanto está aberto
        m.popup_at_pointer(ev)
        return True

    def close_workspace(self, ws):
        """Fecha o workspace e todas as abas dele."""
        if ws not in self.workspaces:
            return False
        for v in list(ws.views):
            v.shutdown()
        ws.views = []
        self.workspaces.remove(ws)
        self.stack.remove(ws.notebook)
        self.sidebar.remove(ws.row)
        self.sidebar.set_visible(len(self.workspaces) > 1)
        if not self.workspaces:
            self.dump()
            if not self._closing:
                self._closing = True
                self.destroy()  # -> on_destroy -> Gtk.main_quit
            return True
        for w in self.workspaces:  # renumera os cartões
            w.update_card()
        return self.select_workspace(self.workspaces[0])

    # -- atalhos que o filho não vê ------------------------------------
    def handle_shortcut(self, ev):
        """Atalhos globais pela TABELA do config (P95). Roda antes do encoding."""
        mods = []
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            mods.append("ctrl")
        if ev.state & Gdk.ModifierType.SHIFT_MASK:
            mods.append("shift")
        if ev.state & Gdk.ModifierType.MOD1_MASK:
            mods.append("alt")
        if ev.state & Gdk.ModifierType.SUPER_MASK:
            mods.append("super")
        acao = self._bound(ev, mods)
        if acao is None:
            return False
        return self.run_action(*acao)

    def _bound(self, ev, mods):
        """A ação do acorde desta tecla, ou None (P95)."""
        kv = ev.keyval
        # dígito vem do keycode físico: num layout não-QWERTY o acorde chega
        # no mesmo número (a mesma decisão do Rust)
        n = _digit_of(ev) if ("ctrl" in mods or "alt" in mods or "super" in mods) else None
        if n is not None:
            acao = self.bindings.get(str(n), mods)
            if acao is not None:
                return acao
        for cand in (Gdk.keyval_name(kv) or "", chr(kv) if kv < 0x110000 else ""):
            if not cand:
                continue
            acao = self.bindings.get(cand.lower(), mods)
            if acao is not None:
                return acao
        return None

    def run_action(self, acao, arg=None):
        """Executa uma ação da tabela; False só quando não há onde aplicá-la (P95)."""
        v, ws = self.view, self.current
        if acao == "copy":
            if v is not None:
                v.copy()
        elif acao == "paste":
            if v is not None:
                v.paste()
        elif acao == "new_tab":
            if ws is not None:
                ws.new_tab()
        elif acao == "close_tab":
            if ws is not None:
                ws.close_tab()
        elif acao == "new_workspace":
            self.new_workspace()
        elif acao == "close_workspace":
            if ws is not None:
                self.close_workspace(ws)
        elif acao == "open_config":
            self.open_config()
        elif acao == "search":
            return bool(v is not None and v.start_search())
        elif acao == "copy_mode":
            # o modo recusa em tela cheia, mas a tecla é nossa: não vaza pro app
            if v is not None:
                v.toggle_copy_mode()
            return v is not None
        elif acao == "prev_prompt":
            self.prompt_jump(True)
        elif acao == "next_prompt":
            self.prompt_jump(False)
        elif acao == "select_tab":
            return bool(ws is not None and ws.select_tab(arg - 1))
        elif acao == "select_workspace":
            self.select_workspace_index(arg - 1)  # consome mesmo sem o índice
        elif acao in ("ws_prev", "ws_next"):
            self.walk_workspace(-1 if acao == "ws_prev" else 1)
        elif acao in ("ws_move_up", "ws_move_down"):
            self.move_workspace(-1 if acao == "ws_move_up" else 1)
        elif acao.startswith("scroll_"):
            if v is None:
                return False
            rows = v.term.rows - 1
            delta = {
                "scroll_page_up": rows,
                "scroll_page_down": -rows,
                "scroll_top": len(v.term.scrollback),
                "scroll_bottom": -len(v.term.scrollback),
            }[acao]
            v.scroll_view(delta)
        return True

    def move_workspace(self, delta):
        """Carrega o workspace atual um cartão para cima/baixo (P97)."""
        ws = self.current
        if ws is None:
            return False
        i = self.workspaces.index(ws)
        j = i + delta
        if not 0 <= j < len(self.workspaces):
            return False
        self.workspaces[i], self.workspaces[j] = self.workspaces[j], self.workspaces[i]
        self.sidebar.remove(ws.row)  # ordem da lista é a do Gtk.ListBox
        self.sidebar.insert(ws.row, j)
        return True

    def walk_workspace(self, delta):
        """Anda os workspaces de um em um, circulando (P95)."""
        if not self.workspaces:
            return
        i = self.workspaces.index(self.current) if self.current else 0
        self.select_workspace_index((i + delta) % len(self.workspaces))

    def prompt_jump(self, back):
        """Leva o prompt anterior (`back`) ou o seguinte à primeira fileira (P93)."""
        v = self.view
        if v is None:
            return
        t = v.term
        topo = t.scrolled - v.view_off  # linha absoluta da primeira fileira
        # subir olha estritamente acima; descer olha daqui, senão o prompt que
        # já está no topo contaria como o "próximo"
        line = t.prompt_line(topo - 1 if back else topo, back)
        if line is not None:
            v.go_to_line(line)

    def on_window_key(self, widget, ev):
        return self.handle_shortcut(ev)

    # -- arquivo solto na janela (P62) ---------------------------------
    def on_drop(self, widget, ctx, x, y, data, info, time):
        """O caminho do arquivo entra no filho como colagem, cotado pro shell.

        Nada além disso: nem aba nova nem `cd` — o terminal não sabe o que está
        rodando, e um programa que não é shell ainda recebe um caminho legível
        (a mesma decisão do Rust).
        """
        from gi.repository import Gio

        uris = data.get_uris() if data is not None else None
        v = self.view
        if not uris or v is None:
            return False
        caminho = Gio.File.new_for_uri(uris[0]).get_path()
        if not caminho:
            return False
        v.drop_path(caminho)
        return True

    def pin_grid(self, cols=None, rows=None):
        """Trava a grade em cols x rows (`--cols`/`--rows`, P63).

        A conta parte do que já está na tela: o tamanho da janela que sobra
        fora da grade (barra de abas, lateral, padding) é medido na alocação
        viva e somado de volta, então a primeira passada já cai na grade certa.
        """
        v = self.view
        if v is None or not (cols or rows):
            return
        cw, ch = (int(m) for m in v.metrics())
        c = cols or v.term.cols
        r = rows or v.term.rows
        larg = c * cw + 2 * v.padding
        alt = r * ch + 2 * v.padding
        larg += self.get_allocated_width() - v.get_allocated_width()
        alt += self.get_allocated_height() - v.get_allocated_height()
        self.resize(max(1, larg), max(1, alt))

    # -- cwd herdado ----------------------------------------------------
    def _cwd_view(self, v):
        """cwd de uma view para o filho nascer: /proc (folha) → OSC 7 → None.

        None = a aba abriu no diretório padrão do shell (sem OSC 7 e sem
        /proc legível) — é o que a restauração (P50) guarda nesse caso.
        """
        if v.child_pid:
            # O filho do pty é `sh -c "<cmd>"`, e o sh NÃO faz exec quando o
            # comando tem argumento (`bash --norc`): o programa de verdade é
            # neto, e o cwd do `sh` fica parado em /proc. Descer até o último
            # descendente é o que dá o cwd que o usuário espera.
            for pid in (_leaf_descendant(v.child_pid), v.child_pid):
                try:
                    return os.readlink(f"/proc/{pid}/cwd")
                except OSError:
                    pass
        if v.term.cwd:
            return v.term.cwd  # OSC 7: o shell disse onde está (P47)
        return None

    def current_cwd(self, ws=None):
        """cwd do filho da aba corrente, sem OSC 7 (o spawn cai no atual)."""
        ws = ws or self.current
        v = ws.view if ws is not None else None
        c = self._cwd_view(v) if v is not None else None
        return c if c is not None else os.getcwd()

    # -- título da janela ----------------------------------------------
    def sync_title(self, v=None):
        """Título da janela; `v` existe porque no switch-page a aba é a do sinal."""
        ws = self.current
        if v is None and ws is not None:
            v = ws.view
        self.set_title(ws.label_text(v) if (ws and v) else DEFAULT_TITLE)

    # -- dump / ciclo de vida ------------------------------------------
    def dump(self):
        path = self.dump_to or "/tmp/tortty-python-dump.txt"
        parts = []
        multi_ws = len(self.workspaces) > 1
        for wi, ws in enumerate(self.workspaces, 1):
            if multi_ws:
                parts.append(f"=== workspace {wi}: {ws.name or '-'} ===")
            multi = len(ws.views) > 1
            for i, v in enumerate(ws.views, 1):
                if multi:
                    parts.append(f"=== aba {i}: {ws.label_text(v)} ===")
                parts.append(v.dump_text())
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(parts) + "\n")
        except OSError as e:
            print("dump falhou:", e, file=sys.stderr)

    def _on_dump_signal(self):
        self.dump()
        return True

    def _on_term_signal(self):
        self._on_quit_after()
        return False

    def _on_quit_after(self):
        self.dump()
        self._closing = True
        for ws in list(self.workspaces):
            for v in list(ws.views):
                v.shutdown()
        self.destroy()
        return False

    def _monitors(self):
        """Retângulos dos monitores, para validar o que veio do arquivo."""
        disp = Gdk.Display.get_default()
        if disp is None:
            return []
        out = []
        for i in range(disp.get_n_monitors()):
            g = disp.get_monitor(i).get_geometry()
            out.append((g.x, g.y, g.width, g.height))
        return out

    def _is_x11(self):
        """Só em X11 o WM aceita posição de janela; no Wayland ela não existe."""
        disp = Gdk.Display.get_default()
        return GdkX11 is not None and isinstance(disp, GdkX11.X11Display)

    def on_configure(self, widget, ev):
        """Atualiza a geometria viva; maximizado não sobrescreve a normal."""
        if os.environ.get("PYTERM_GEOMLOG"):  # sonda: cliente x moldura
            import sys

            g = self.get_window()
            ext = g.get_frame_extents() if g else None
            print(
                "geom: ev=%s,%s getpos=%s frame=%s"
                % (
                    ev.x,
                    ev.y,
                    self.get_position(),
                    (ext.x, ext.y, ext.width, ext.height) if ext else None,
                ),
                file=sys.stderr,
                flush=True,
            )
        if self._remember and not self._max:
            self._saved.update(w=ev.width, h=ev.height)
            if self._is_x11():
                # get_position() é a posição da MOLDURA e ev.y é a do cliente:
                # salvar ev.y e restaurar com move() descia a janela 30 px por
                # execução (a barra de título lida duas vezes). Casam com
                # move()/get_frame_extents, então é ele que vai para o arquivo.
                pos = self.get_position()
                self._saved.update(x=pos[0], y=pos[1])
        return False

    def on_window_state(self, widget, ev):
        """Maximizado é evento de WM, não tamanho: marcar aqui, não medir."""
        self._max = bool(ev.new_window_state & Gdk.WindowState.MAXIMIZED)
        return False

    def _layout_memory(self):
        """Workspaces, abas e o cwd de cada uma, na ordem da sessão (P50)."""
        wss = [
            {"name": w.name, "cwds": [self._cwd_view(v) for v in w.views]} for w in self.workspaces
        ]
        if not wss:
            return None
        iws = self.workspaces.index(self.current) if self.current in self.workspaces else 0
        ws = self.workspaces[iws]
        itab = ws.views.index(ws.view) if ws.view in ws.views else 0
        return {"workspaces": wss, "ws": iws, "tab": itab}

    def _save_geometry(self):
        """Grava o que os handlers já coletaram (com PYTERM_GEOM não grava nada)."""
        if not self._remember:
            return
        s = dict(self._saved)
        s["max"] = self._max
        if self.config.restore_state in ("layout", "content"):
            lay = self._layout_memory()
            if lay:
                s["layout"] = lay
        else:
            s.pop("layout", None)  # `none`: o velho do arquivo não pode voltar
        if not self._is_x11():
            s.pop("x", None)  # no Wayland não existe posição para lembrar
            s.pop("y", None)
        self._saved = s
        state.save(s)

    def _save_snapshots(self):
        """P57: a foto de cada aba, gravada na saída (aba fechada não volta)."""
        if not self._remember:
            return  # PYTERM_GEOM/--cols: a bancada não escreve estado
        if self.config.restore_state != "content":
            state.save_snapshots([])  # a chave desligada apaga o que ficou
            return
        snaps = []
        for j, ws in enumerate(self.workspaces):
            for k, v in enumerate(ws.views):
                snaps.append((j, k, v.term.snapshot()))
        state.save_snapshots(snaps)

    def on_destroy(self, *_):
        if getattr(self, "_debugsock", None) is not None:
            self._debugsock.stop()  # fecha o socket e apaga o arquivo
            self._debugsock = None
        self._save_geometry()
        self._save_snapshots()  # antes do shutdown: o Term ainda está inteiro
        if self._lock is not None:
            self._lock.close()  # solta o flock: a próxima janela pode ser dona
            self._lock = None
        self._closing = True
        for ws in list(self.workspaces):
            for v in list(ws.views):
                v.shutdown()
        self.workspaces = []
        Gtk.main_quit()

    def grab_focus_current(self):
        v = self.view
        if v is not None:
            v.grab_focus()
