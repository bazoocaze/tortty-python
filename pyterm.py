#!/usr/bin/env python3
"""pyterm — terminal mínimo em Python puro (experimento).

Propósito: sentir na pele o custo do caminho quente (parse VT + grade +
desenho) em Python, comparado ao núcleo C do gtkterm. Roda shell de verdade
e aguenta o `mc` — devagar, e esse é o ponto.

Uso:
    python3 pyterm.py [--cmd 'comando'] [--quit-after SEG] [--selftest]
                      [--dump-to ARQ]

Este arquivo é só o ponto de entrada. O código está em `pyterm_core/`:
`term.py` (grade + parser, sem GTK), `keys.py` (teclado), `window.py` (janela
GTK, pty, cairo), `palette.py` (cores), `selftest.py`, `cli.py`, `gui.py`.

Só depende de PyGObject (Gtk3) + pycairo, que já existem no sistema — e
`--selftest` nem disso: só importa `term.py`.
MIT (ver LICENSE). O native-port/ é GPL-3.0-only por derivar do kitty; este
arquivo é código original e não usa nada do núcleo.
"""

import sys

from pyterm_core.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
