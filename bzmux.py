#!/usr/bin/env python3
"""bzmux — terminal em Python puro.

pty + parser VT + grade + cairo/Pango, sem C. Nasceu para medir o custo do
caminho quente em Python comparado ao núcleo C do kitty; hoje roda shell, `mc`
e `vim` no dia a dia. A medição e o protocolo ficam em docs/BENCHMARKS.md.

Uso:
    python3 bzmux.py [--cmd 'comando'] [--quit-after SEG] [--selftest]
                      [--dump-to ARQ]

Este arquivo é só o ponto de entrada. O código está em `core/`: ver o mapa em
README.md ou em AGENTS.md.

Só depende de PyGObject (Gtk3) + pycairo, que já existem no sistema — e
`--selftest` nem disso: não toca em `gui.py`, então roda sem gi/cairo.
MIT (ver LICENSE): código original, não derivado do kitty, e não usa nada do
núcleo dele.
"""

import sys

from core.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
