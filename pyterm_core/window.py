"""A janela GTK: abas (P11) e, adiante, workspaces (P12).

Cada aba é uma `TermView` (pty + desenho + input) dentro de um `Gtk.Notebook`.
Aqui mora só o que é global: ciclo de vida das abas, título delas e os atalhos
que o filho **não pode** ver (`Ctrl+Shift+T/W`, `Alt+N`).
"""

import os
import signal

from .gui import Gtk, Gdk, GLib
from .view import TermView


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
        ev.hardware_keycode, 0, ev.group)
    if ok and Gdk.KEY_0 <= kv <= Gdk.KEY_9:
        return kv - Gdk.KEY_0
    return None


class PyTermWindow(Gtk.Window):
    def __init__(self, cmd=None, quit_after=0, dump_to=None):
        super().__init__(title="pyterm")
        # O comando dado na linha de comando é replicado em cada aba nova
        # (decisão do P11): `run.sh --cmd ...` e os testes continuam
        # previsíveis. Sem `--cmd`, cada aba nasce com $SHELL.
        self.cmd = cmd
        self.dump_to = dump_to
        self.quit_after = quit_after
        self.views = []
        self.font_size = 16
        self._closing = False

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.connect("switch-page", self.on_switch_page)
        self.add(self.notebook)
        self.set_default_size(680, 420)
        self.connect("destroy", self.on_destroy)

        self.new_tab()
        if quit_after:
            GLib.timeout_add_seconds(quit_after, self._on_quit_after)
        # SIGUSR1 dumpar as abas na hora (depuração: "kill -USR1 <pid>")
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1,
                             self._on_dump_signal)

    # -- abas ---------------------------------------------------------
    @property
    def view(self):
        """A view da aba corrente (ou None)."""
        i = self.notebook.get_current_page()
        if 0 <= i < len(self.views):
            return self.views[i]
        return self.views[0] if self.views else None

    def new_tab(self):
        """Aba nova, herdando o cwd da aba corrente."""
        v = TermView(cmd=self.cmd, cwd=self._current_cwd(),
                     font_size=self.font_size,
                     on_exit=self.on_view_exit,
                     on_title=self.on_view_title,
                     shortcuts=self.handle_shortcut)
        self.views.append(v)
        label = Gtk.Label(label=self._label_text(v))
        # Gtk.Label não tem janela própria: sem EventBox não chega evento de
        # mouse pra fechar a aba com o clique do meio
        box = Gtk.EventBox()
        # sem a máscara o EventBox tem janela mas recebe zero eventos
        # (get_events() == 0), então o clique do meio nunca chegava
        box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        box.add(label)
        box.connect("button-press-event", self.on_tab_click, v)
        v.tab_label = label        # atualizado no on_view_title
        self.notebook.append_page(v, box)
        self.notebook.set_tab_reorderable(v, True)
        # widget recém-anexado nasce HIDDEN: o notebook simplesmente ignora o
        # set_current_page enquanto a página não está visível (silencioso, o
        # get_current_page segue devolvendo a aba antiga e a tecla vai pra
        # ela), então mostra a página e o rótulo na mão.
        v.show_all()
        box.show_all()
        self.notebook.set_current_page(self.views.index(v))
        v.grab_focus()
        return v

    def close_tab(self, view=None):
        """Fecha a aba (e a janela, se era a última)."""
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
            self.dump()
            if not self._closing:
                self._closing = True
                self.destroy()          # -> on_destroy -> Gtk.main_quit
        else:
            self.view.grab_focus()
        return True

    def select_tab(self, index):
        """Seleciona a aba N (0-based); devolve False se não existe."""
        if 0 <= index < len(self.views):
            self.notebook.set_current_page(index)
            return True
        return False

    def on_tab_click(self, widget, ev, view):
        if ev.button == 2:              # clique do meio fecha a aba
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
        v.queue_draw()          # aba escondida não recebe size-allocate
        self.set_title(self._label_text(v))

    def _focus_idle(self, v):
        v.grab_focus()
        return False

    def on_view_title(self, view, title):
        # set_tab_label_text TROCARIA o widget do rótulo (e com ele o
        # EventBox do clique do meio), então mexe no texto do Label guardado
        label = getattr(view, "tab_label", None)
        if label is not None:
            label.set_text(self._label_text(view))
        if view is self.view:
            self.set_title(self._label_text(view))

    def on_view_exit(self, view):
        """O shell da aba morreu: fecha a aba (P8, agora por aba)."""
        self.dump()
        self.close_tab(view)

    def _label_text(self, view):
        """Rótulo da aba: título do app ou, sem OSC, o cwd da sessão.

        O bash não manda OSC 0/2 por padrão, então todas as abas ficariam
        "pyterm"; o diretório é a informação que o usuário usa pra saber onde
        está (o `Alt+N` já dá o número, por isso não tem prefixo numérico).
        """
        if view.app_title and view._title:
            return view._title
        return os.path.basename(view.start_cwd or "") or "pyterm"

    def _title_of(self, view):
        return view._title or "pyterm"

    def _current_cwd(self):
        """cwd do filho da aba corrente (`/proc/<pid>/cwd`), sem OSC 7."""
        v = self.view
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

    # -- atalhos que o filho não vê ------------------------------------
    def handle_shortcut(self, ev):
        """Atalhos globais. Roda ANTES do encoding da tecla (na view)."""
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        kv = ev.keyval
        if ctrl and shift:
            if kv in (Gdk.KEY_t, Gdk.KEY_T):
                self.new_tab()
                return True
            if kv in (Gdk.KEY_w, Gdk.KEY_W):
                self.close_tab()
                return True
        if alt:
            n = _digit_of(ev)
            if n is not None:
                return self.select_tab(9 if n == 0 else n - 1)
        return False

    # -- dump / ciclo de vida ------------------------------------------
    def dump(self):
        path = self.dump_to or "/tmp/pyterm-dump.txt"
        parts, multi = [], len(self.views) > 1
        for i, v in enumerate(self.views):
            if multi:
                parts.append(f"=== aba {i + 1}: {self._title_of(v)} ===")
            parts.append(v.dump_text())
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(parts) + "\n")
        except OSError as e:
            print("dump falhou:", e, file=sys.stderr)

    def _on_dump_signal(self):
        self.dump()
        return True

    def _on_quit_after(self):
        self.dump()
        self._closing = True
        for v in list(self.views):
            v.shutdown()
        self.destroy()
        return False

    def on_destroy(self, *_):
        self._closing = True
        for v in list(self.views):
            v.shutdown()
        self.views = []
        Gtk.main_quit()

    def grab_focus_current(self):
        v = self.view
        if v is not None:
            v.grab_focus()
