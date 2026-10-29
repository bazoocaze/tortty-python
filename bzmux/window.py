"""A janela GTK: workspaces (P12) e, dentro de cada um, abas (P11).

    BzmuxWindow  Gtk.Box[ lateral (Gtk.ListBox) | Gtk.Stack ]
    Workspace     um Gtk.Notebook + as TermView dele + o cartão da lateral

Cada workspace tem o seu conjunto de abas (`Gtk.Stack` e não trocar páginas do
mesmo notebook: assim cada um guarda a aba selecionada, a ordem e os títulos).
O que é de sessão mora na `view.py`; aqui só há ciclo de vida e atalhos.
"""

import os
import signal
import sys

from . import state, style
from .gui import Gdk, GdkX11, GLib, Gtk, Pango
from .view import TermView

SIDEBAR_W = 170  # largura fixa (arrastável fica pra depois)


def _geom():
    # PYTERM_GEOM=980x640 trava o tamanho: medir exige a mesma grade nos dois
    m = os.environ.get("PYTERM_GEOM", "")
    w, _, h = m.partition("x")
    if w.isdigit() and h.isdigit() and int(w) > 0 and int(h) > 0:
        return int(w), int(h)
    return 980, 640


TAB_TITLE_CHARS = 20  # aba: largura em chars, não em px (o título trunca)
_styled = False  # o provider é da tela: aplica uma vez por processo


def apply_style():
    """Registra o CSS de `style.py` na tela (idempotente)."""
    global _styled
    if _styled:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(style.css().encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
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


class Workspace:
    """Um conjunto de abas + o cartão dele na lateral."""

    def __init__(self, win, index):
        self.win = win
        self.name = f"workspace {index}"
        self.views = []
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.connect("switch-page", self.on_switch_page)

        # cartão da lateral: "<n>  <nome>" e, embaixo, a aba ativa
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
        i = self.notebook.get_current_page()
        if 0 <= i < len(self.views):
            return self.views[i]
        return self.views[0] if self.views else None

    def new_tab(self):
        """Aba nova, herdando o cwd da aba corrente."""
        v = TermView(
            cmd=self.win.cmd,
            cwd=self.win.current_cwd(self),
            font_size=self.win.font_size,
            on_exit=self.on_view_exit,
            on_title=self.on_view_title,
            shortcuts=self.win.handle_shortcut,
        )
        self.views.append(v)
        # mesmo motivo do cartão (P14): sem limite o título longo vira largura
        # mínima e a janela inteira estica (o notebook se recusa a encolher)
        label = Gtk.Label(label=self.label_text(v))
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_width_chars(TAB_TITLE_CHARS)
        label.set_max_width_chars(TAB_TITLE_CHARS)
        label.set_tooltip_text(self.label_text(v))
        box = Gtk.EventBox()
        box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        box.add(label)
        box.connect("button-press-event", self.on_tab_click, v)
        v.tab_label = label  # atualizado no on_view_title
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
        if ev.button == 2:  # clique do meio fecha a aba
            self.close_tab(view)
            return True
        return False

    def on_switch_page(self, nb, page, page_num):
        v = self.views[page_num] if 0 <= page_num < len(self.views) else None
        if v is None:
            return
        # grab_focus aqui não pega: no instante do switch-page a página nova
        # ainda não está mapeada e o foco fica no notebook (as teclas seguintes
        # não chegavam em ninguém). Um idle resolve.
        GLib.idle_add(self._focus_idle, v)
        v.queue_draw()  # aba escondida não recebe size-allocate
        self.update_card()
        self.win.sync_title()

    def _focus_idle(self, v):
        # não roubar o foco do Gtk.Entry de renomear o cartão: o clique que
        # seleciona o workspace agenda este idle, e ele rodava DEPOIS do
        # grab_focus do entry (a digitação do nome ia pro terminal)
        w = self.win.get_focus()
        if w is not None and w is not v and isinstance(w, Gtk.Entry):
            return False
        v.grab_focus()
        return False

    def on_view_title(self, view, title):
        # set_tab_label_text TROCARIA o widget do rótulo (e com ele o
        # EventBox do clique do meio), então mexe no texto do Label guardado
        label = getattr(view, "tab_label", None)
        if label is not None:
            label.set_text(self.label_text(view))
            label.set_tooltip_text(self.label_text(view))
        self.update_card()
        if view is self.view:
            self.win.sync_title()

    def on_view_exit(self, view):
        """O shell da aba morreu: fecha a aba (P8, agora por aba)."""
        self.win.dump()
        self.close_tab(view)

    def label_text(self, view):
        """Rótulo da aba: título do app ou, sem OSC, o cwd da sessão.

        O bash não manda OSC 0/2 por padrão, então todas as abas ficariam
        "bzmux"; o diretório é a informação que o usuário usa pra saber onde
        está (o `Alt+N` já dá o número, por isso não tem prefixo numérico).
        """
        if view.app_title and view._title:
            return view._title
        return os.path.basename(view.start_cwd or "") or "bzmux"

    # -- cartão da lateral ---------------------------------------------
    def update_card(self):
        try:
            n = self.win.workspaces.index(self) + 1
        except ValueError:
            n = 0
        self.name_label.set_markup(f"<b>{n}</b>  {GLib.markup_escape_text(self.name)}")
        v = self.view
        title = self.label_text(v) if v is not None else "-"
        k = len(self.views)
        info = f"{title} ({k} aba{'s' if k != 1 else ''})"
        self.info_label.set_markup(_card_info(info))
        self.card.set_tooltip_text(f"{n}. {self.name}\n{info}")

    def on_card_click(self, widget, ev):
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
            if keep and novo:
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


class BzmuxWindow(Gtk.Window):
    def __init__(self, cmd=None, quit_after=0, dump_to=None):
        super().__init__(title="bzmux")
        # O comando dado na linha de comando é replicado em cada aba nova
        # (decisão do P11): `run.sh --cmd ...` e os testes continuam
        # previsíveis. Sem `--cmd`, cada aba nasce com $SHELL.
        self.cmd = cmd
        self.dump_to = dump_to
        self.quit_after = quit_after
        self.workspaces = []
        self.font_size = 13  # pontos (convenção de terminal)
        self._closing = False
        # geometria lembrada entre execuções. Com PYTERM_GEOM quem manda é o
        # protocolo de medição: não restaura e não salva (a grade do bench
        # precisa ser a mesma nos dois terminais comparados).
        self._remember = not os.environ.get("PYTERM_GEOM")
        self._saved = (state.load() or {}) if self._remember else {}
        self._max = bool(self._saved.get("max"))

        apply_style()
        self.sidebar = Gtk.ListBox()
        self.sidebar.set_name("sidebar")  # alvo do CSS (style.py)
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
        self.add(hbox)
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
        if quit_after:
            GLib.timeout_add_seconds(quit_after, self._on_quit_after)
        # SIGUSR1 dumpar as abas na hora (depuração: "kill -USR1 <pid>")
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, self._on_dump_signal)
        # SIGTERM fecha como o --quit-after: o dump e o prof saem no fim
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._on_term_signal)

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
        """Workspace novo, com uma aba herdando o cwd do workspace atual."""
        ws = Workspace(self, len(self.workspaces) + 1)
        self.workspaces.append(ws)
        self.stack.add_named(ws.notebook, self._stack_name(ws))
        self.sidebar.add(ws.row)
        ws.notebook.show_all()
        ws.row.show_all()
        self.select_workspace(ws)
        ws.new_tab()
        self.sidebar.set_visible(len(self.workspaces) > 1)
        return ws

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
        """Atalhos globais. Roda ANTES do encoding da tecla (na view)."""
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        sup = bool(ev.state & Gdk.ModifierType.SUPER_MASK)
        kv = ev.keyval
        ws = self.current
        if ctrl and shift:
            if kv in (Gdk.KEY_t, Gdk.KEY_T):
                if ws is not None:
                    ws.new_tab()
                return True
            if kv in (Gdk.KEY_w, Gdk.KEY_W):
                if ws is not None:
                    ws.close_tab()
                return True
            if kv in (Gdk.KEY_n, Gdk.KEY_N):
                self.new_workspace()
                return True
            if kv in (Gdk.KEY_q, Gdk.KEY_Q):
                if ws is not None:
                    self.close_workspace(ws)
                return True
            n = _digit_of(ev)  # Ctrl+Shift+1..9 (0 = o 10º)
            if n is not None:
                self.select_workspace_index(9 if n == 0 else n - 1)
                return True  # consome mesmo sem workspace no índice
        if sup and not ctrl and not alt:
            # alias de workspace pelo Super (o WM pode engolir Super+dígito)
            if kv in (Gdk.KEY_n, Gdk.KEY_N):
                self.new_workspace()
                return True
            if kv in (Gdk.KEY_q, Gdk.KEY_Q):
                if ws is not None:
                    self.close_workspace(ws)
                return True
            n = _digit_of(ev)  # Super+1..9 (0 = o 10º)
            if n is not None:
                self.select_workspace_index(9 if n == 0 else n - 1)
                return True  # senão o dígito vaza pro filho
        if alt:
            n = _digit_of(ev)  # Alt+1..9 (0 = a 10ª aba)
            if n is not None and ws is not None:
                return ws.select_tab(9 if n == 0 else n - 1)
        return False

    def on_window_key(self, widget, ev):
        return self.handle_shortcut(ev)

    # -- cwd herdado ----------------------------------------------------
    def current_cwd(self, ws=None):
        """cwd do filho da aba corrente (`/proc/<pid>/cwd`), sem OSC 7."""
        ws = ws or self.current
        v = ws.view if ws is not None else None
        if v is not None and v.child_pid:
            # O filho do pty é `sh -c "<cmd>"`, e o sh NÃO faz exec quando o
            # comando tem argumento (`bash --norc`): o programa de verdade é
            # neto, e o cwd do `sh` fica parado em /proc. Descer até o último
            # descendente é o que dá o cwd que o usuário espera.
            for pid in (_leaf_descendant(v.child_pid), v.child_pid):
                try:
                    return os.readlink(f"/proc/{pid}/cwd")
                except OSError:
                    pass
        return os.getcwd()

    # -- título da janela ----------------------------------------------
    def sync_title(self):
        ws = self.current
        v = ws.view if ws is not None else None
        self.set_title(ws.label_text(v) if (ws and v) else "bzmux")

    # -- dump / ciclo de vida ------------------------------------------
    def dump(self):
        path = self.dump_to or "/tmp/bzmux-dump.txt"
        parts = []
        multi_ws = len(self.workspaces) > 1
        for wi, ws in enumerate(self.workspaces, 1):
            if multi_ws:
                parts.append(f"=== workspace {wi}: {ws.name} ===")
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

    def _save_geometry(self):
        """Grava o que os handlers já coletaram (com PYTERM_GEOM não grava nada)."""
        if not self._remember:
            return
        s = dict(self._saved)
        s["max"] = self._max
        if not self._is_x11():
            s.pop("x", None)  # no Wayland não existe posição para lembrar
            s.pop("y", None)
        self._saved = s
        state.save(s)

    def on_destroy(self, *_):
        self._save_geometry()
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
