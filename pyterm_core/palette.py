"""Célula, paleta de cores e o charset DEC especial.

Célula é [char, fg, bg, flags]: fg/bg são índice xterm (0-255, 256=fg
default, 257=bg default) e flags é bitmask (BOLD/UL/INV).

Puro dado: sem GTK e sem estado de sessão, então isto pode ser importado por
um teste de parser em máquina sem PyGObject.
"""

# ---------------------------------------------------------------- grade ---

# célula: [char, fg, bg, flags]  (fg/bg: 0-15, 256=default fg, 257=default bg)
# flags: 1=bold 2=underline 4=inverse
DEF_FG, DEF_BG = 256, 257
BOLD, UL, INV = 1, 2, 4

PALETTE = [
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
    (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
    (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
]
def _build_256():
    pal = list(PALETTE)
    steps = [0, 95, 135, 175, 215, 255]
    for r in steps:
        for g in steps:
            for b in steps:
                pal.append((r, g, b))
    for i in range(24):
        v = 8 + i * 10
        pal.append((v, v, v))
    return pal


PALETTE256 = _build_256()

BG_DEFAULT = (0, 0, 0)
FG_DEFAULT = (214, 214, 214)

# DEC special graphics (ESC ( 0): tecla -> unicode
DEC_SPECIAL = {
    "`": "◆", "a": "▒", "f": "°", "g": "±", "j": "┘", "k": "┐",
    "l": "┌", "m": "└", "n": "┼", "o": "‾", "p": "‾", "q": "─",
    "r": "‾", "s": "_", "t": "├", "u": "┤", "v": "┴", "w": "┬",
    "x": "│", "y": "≤", "z": "≥", "{": "π", "|": "≠", "}": "£",
    "~": "•", "0": "█", ",": "←", "+": "→", ".": "↓", "-": "↑",
    "/": "↓", "h": "␤",
}
