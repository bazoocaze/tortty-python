"""Célula, paleta de cores e o charset DEC especial.

Célula é [char, fg, bg, flags]: fg/bg são índice xterm (0-255, 256=fg
default, 257=bg default) ou, no truecolor, o RGB marcado no bit 24 (ver
`rgb()`/`cell_rgb()`); flags é bitmask (BOLD/UL/INV/ITALIC, mais o estilo do
sublinhado). Uma célula com hyperlink OSC 8 carrega um quinto campo com o
índice do URI em `Term.links` — só ele, para o caminho quente não pagar nada.

Puro dado: sem GTK e sem estado de sessão, então isto pode ser importado por
um teste de parser em máquina sem PyGObject.
"""

# ---------------------------------------------------------------- grade ---

# célula: [char, fg, bg, flags]  (fg/bg: 0-15, 256=default fg, 257=default bg)
# flags: 1=bold 2=underline 4=inverse 8=italic
DEF_FG, DEF_BG = 256, 257
BOLD, UL, INV, ITALIC = 1, 2, 4, 8

# Estilo do sublinhado (SGR 4:n) nos bits 4-6: 0 simples, 1 duplo, 2 curvo,
# 3 pontilhado, 4 tracejado. `UL` continua dizendo só "tem sublinhado".
UL_SHIFT = 4
UL_MASK = 7 << UL_SHIFT
UL_SINGLE, UL_DOUBLE, UL_CURLY, UL_DOTTED, UL_DASHED = 0, 1, 2, 3, 4


def ul_off(flags):
    """Flags sem sublinhado nem estilo (SGR 24)."""
    return flags & ~(UL | UL_MASK)


def ul_on(flags, style=UL_SINGLE):
    """Flags com sublinhado no estilo dado (SGR 4 e SGR 4:n)."""
    return (flags & ~UL_MASK) | UL | (style << UL_SHIFT)


def ul_style(flags):
    """Estilo do sublinhado da célula (só tem sentido com `flags & UL`)."""
    return (flags >> UL_SHIFT) & 7


# Truecolor (P4): o RGB mora na própria célula, sem tabela de cores alocadas.
# O bit 24 marca "isto é RGB" — os índices de paleta (0-255) e as sentinelas
# (256/257, que nem chegam no bit 24) continuam sendo ints pequenos, então o
# caminho de 256 cores não paga nada e a célula não vira tupla.
TC = 0x1000000


def rgb(r, g, b):
    """Cor de célula a partir de RGB (0-255 cada)."""
    return TC | ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)


def cell_rgb(c, default):
    """RGB da cor de uma célula: sentinela default, índice de paleta ou TC."""
    if c == DEF_FG or c == DEF_BG:
        return default
    if c & TC:
        return ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)
    return PALETTE256[c]


PALETTE = [
    (0, 0, 0),
    (205, 0, 0),
    (0, 205, 0),
    (205, 205, 0),
    (0, 0, 238),
    (205, 0, 205),
    (0, 205, 205),
    (229, 229, 229),
    (127, 127, 127),
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (92, 92, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
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
_PAL_F = [tuple(c / 255 for c in rgb) for rgb in PALETTE256]

BG_DEFAULT = (0, 0, 0)
FG_DEFAULT = (214, 214, 214)

# Desenho: as mesmas cores em float 0..1 (o cairo pede float), cacheadas para
# não refazer divisão nem alocar lista por run. Teto porque o truecolor pode
# gerar valores sem fim; as tuplas são compartilhadas, então `is` compara cor.
_FG_F = tuple(c / 255 for c in FG_DEFAULT)
_BG_F = tuple(c / 255 for c in BG_DEFAULT)
_F_CACHE = {}


def cell_rgb_f(c):
    """Cor da célula já em floats 0..1, pronta para `set_source_rgb`."""
    v = _F_CACHE.get(c)
    if v is None:
        if c == DEF_FG:
            v = _FG_F
        elif c == DEF_BG:
            v = _BG_F
        elif c & TC:
            v = (
                ((c >> 16) & 0xFF) / 255,
                ((c >> 8) & 0xFF) / 255,
                (c & 0xFF) / 255,
            )
        else:
            v = _PAL_F[c]
        if len(_F_CACHE) > 4096:
            _F_CACHE.clear()
        _F_CACHE[c] = v
    return v


# DEC special graphics (ESC ( 0): tecla -> unicode
DEC_SPECIAL = {
    "`": "◆",
    "a": "▒",
    "f": "°",
    "g": "±",
    "j": "┘",
    "k": "┐",
    "l": "┌",
    "m": "└",
    "n": "┼",
    "o": "‾",
    "p": "‾",
    "q": "─",
    "r": "‾",
    "s": "_",
    "t": "├",
    "u": "┤",
    "v": "┴",
    "w": "┬",
    "x": "│",
    "y": "≤",
    "z": "≥",
    "{": "π",
    "|": "≠",
    "}": "£",
    "~": "•",
    "0": "█",
    ",": "←",
    "+": "→",
    ".": "↓",
    "-": "↑",
    "/": "↓",
    "h": "␤",
}
