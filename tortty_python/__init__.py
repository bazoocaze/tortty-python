"""tortty_python — the parts of the terminal, split by responsibility.

    palette.py   cell, xterm-256 palette, DEC charset           (pure data)
    term.py      grid, cursor, VT parser                       (no GTK)
    keys.py      X11 keyval -> terminal bytes                  (no GTK*)
    kitty_kbd.py kitty keyboard protocol (CSI ... u)            (pure)
    mouse.py     mouse protocol (SGR and the old one)          (pure)
    graphics.py  kitty image protocol (APC G)                  (pure)
    gui.py       single import of Gtk/Gdk/GLib/Pango/cairo    (glue only)
    view.py      one session: pty, drawing, input              (GTK only)
    window.py    the window: tabs, sidebar, global shortcuts   (GTK only)
    checks.py    the test battery, no window                  (no GTK)
    selftest.py  dependency-free runner (--selftest)          (no GTK)
    cli.py       argv and startup                              (wires it all)

* keys uses the Gdk keyval constants, but does not import Gtk.

Dependency: `term`/`palette` do not know `window`. That is what lets the parser
run on a machine without PyGObject (`python3 -m tortty_python --selftest`) and the
window be replaced without touching the core.

MIT (see LICENSE).
"""

# Fonte única da versão: o pyproject lê daqui (hatch) e o `--version` mostra.
# O patch sobe ao fechar um item de backlog, não a cada commit.
__version__ = "0.0.37"

__all__ = ["Term", "TorttyWindow", "selftest", "__version__"]


def __getattr__(name):
    """Import preguiçoso: `tortty_python.Term` não puxa o Gtk."""
    if name == "Term":
        from .term import Term

        return Term
    if name == "TorttyWindow":
        from .window import TorttyWindow

        return TorttyWindow
    if name == "selftest":
        from .selftest import selftest

        return selftest
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
