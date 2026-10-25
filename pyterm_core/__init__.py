"""pyterm_core — as partes do pyterm, separadas por responsabilidade.

    palette.py   célula, paleta xterm-256, charset DEC        (puro dado)
    term.py      grade, cursor, parser VT                     (sem GTK)
    keys.py      keyval do X11 -> bytes do terminal            (pura)
    gui.py       import único de Gtk/Gdk/GLib/cairo           (só glue)
    window.py    janela GTK: pty, desenho, eventos            (só GTK)
    selftest.py  14 checks do parser, sem janela              (sem GTK)
    cli.py       argv e arranque                              (liga tudo)

Dependência: `term`/`palette` não conhecem `window`. Assim o parser roda em
máquina sem PyGObject (`python3 pyterm.py --selftest`) e a janela pode ser
trocada sem tocar no núcleo.

MIT (ver LICENSE).
"""

__all__ = ["Term", "PyTermWindow", "selftest"]


def __getattr__(name):
    """Import preguiçoso: `pyterm_core.Term` não puxa o Gtk."""
    if name == "Term":
        from .term import Term
        return Term
    if name == "PyTermWindow":
        from .window import PyTermWindow
        return PyTermWindow
    if name == "selftest":
        from .selftest import selftest
        return selftest
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
