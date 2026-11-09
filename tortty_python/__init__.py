"""tortty_python — as partes do terminal, separadas por responsabilidade.

    palette.py   célula, paleta xterm-256, charset DEC        (puro dado)
    term.py      grade, cursor, parser VT                     (sem GTK)
    keys.py      keyval do X11 -> bytes do terminal           (sem GTK*)
    kitty_kbd.py protocolo de teclado do kitty (CSI ... u)    (puro)
    mouse.py     protocolo de mouse (SGR e o antigo)          (puro)
    graphics.py  protocolo de imagens do kitty (APC G)         (puro)
    gui.py       import único de Gtk/Gdk/GLib/Pango/cairo     (só glue)
    view.py      uma sessão: pty, desenho, input               (só GTK)
    window.py    a janela: abas, lateral, atalhos globais      (só GTK)
    checks.py    a bateria de testes, sem janela              (sem GTK)
    selftest.py  runner sem dependências (--selftest)         (sem GTK)
    cli.py       argv e arranque                              (liga tudo)

* keys usa as constantes de keyval do Gdk, mas não importa Gtk.

Dependência: `term`/`palette` não conhecem `window`. Assim o parser roda em
máquina sem PyGObject (`python3 -m tortty_python --selftest`) e a janela pode ser
trocada sem tocar no núcleo.

MIT (ver LICENSE).
"""

# Fonte única da versão: o pyproject lê daqui (hatch) e o `--version` mostra.
# O patch sobe ao fechar um item de backlog, não a cada commit.
__version__ = "0.0.10"

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
