"""core — as partes do bzmux, separadas por responsabilidade.

    palette.py   célula, paleta xterm-256, charset DEC        (puro dado)
    term.py      grade, cursor, parser VT                     (sem GTK)
    keys.py      keyval do X11 -> bytes do terminal            (pura)
    gui.py       import único de Gtk/Gdk/GLib/cairo           (só glue)
    view.py      uma sessão: pty, desenho, input              (só GTK)
    window.py    a janela: abas (Notebook) e atalhos globais   (só GTK)
    selftest.py  14 checks do parser, sem janela              (sem GTK)
    cli.py       argv e arranque                              (liga tudo)

Dependência: `term`/`palette` não conhecem `window`. Assim o parser roda em
máquina sem PyGObject (`python3 bzmux.py --selftest`) e a janela pode ser
trocada sem tocar no núcleo.

MIT (ver LICENSE).
"""

__all__ = ["Term", "BzmuxWindow", "selftest"]


def __getattr__(name):
    """Import preguiçoso: `core.Term` não puxa o Gtk."""
    if name == "Term":
        from .term import Term
        return Term
    if name == "BzmuxWindow":
        from .window import BzmuxWindow
        return BzmuxWindow
    if name == "selftest":
        from .selftest import selftest
        return selftest
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
