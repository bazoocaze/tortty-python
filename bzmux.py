#!/usr/bin/env python3
"""bzmux — terminal mínimo em Python puro (experimento).

Propósito: sentir na pele o custo do caminho quente (parse VT + grade +
desenho) em Python, comparado ao núcleo C do kitty. Roda shell de verdade
e aguenta o `mc` — devagar, e esse é o ponto.

Uso:
    python3 bzmux.py [--cmd 'comando'] [--quit-after SEG] [--selftest]
                      [--dump-to ARQ]

Este arquivo é só o ponto de entrada. O código está em `core/`: ver o mapa em
README.md ou em AGENTS.md.

Só depende de PyGObject (Gtk3) + pycairo, que já existem no sistema — e
`--selftest` nem disso: só importa `term.py`.
MIT (ver LICENSE): código original, não derivado do kitty, e não usa nada do
núcleo dele.
"""

import sys

from core.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
