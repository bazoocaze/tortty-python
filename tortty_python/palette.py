"""Cell, colour palette and the special DEC charset.

A cell is [char, fg, bg, flags]: fg/bg are an xterm index (0-255, 256=default
fg, 257=default bg) or, in truecolor, the RGB marked in bit 24 (see
`rgb()`/`cell_rgb()`); flags is a bitmask (BOLD/UL/INV/ITALIC, plus the
underline style). A cell with an OSC 8 hyperlink carries a fifth field with the
index of the URI in `Term.links` — only that, so the hot path pays nothing.

Pure data: no GTK and no session state, so this can be imported by a parser
test on a machine without PyGObject.
"""

# ---------------------------------------------------------------- grade ---

# célula: [char, fg, bg, flags]  (fg/bg: 0-15, 256=default fg, 257=default bg)
# flags: 1=bold 2=underline 4=inverse 8=italic (bits 4-6 guardam o estilo do
# sublinhado, então o riscado e a sobrelinha vão acima deles)
DEF_FG, DEF_BG = 256, 257
BOLD, UL, INV, ITALIC = 1, 2, 4, 8
STRIKE, OVERLINE = 128, 256  # SGR 9 e SGR 53 (P54)
DIM, HIDDEN = 512, 1024  # SGR 2 (faint) e SGR 8 (P64)
BLINK = 2048  # SGR 5 e 6 (P66)

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

_HEX = "0123456789abcdefABCDEF"


def parse_color(s):
    """`#RGB`/`#RRGGBB` -> int RGB; None se não for cor (chaves da config, P49)."""
    if not s.startswith("#"):
        return None
    h = s[1:]
    if len(h) == 3 and all(c in _HEX for c in h):
        return int(h[0] * 2 + h[1] * 2 + h[2] * 2, 16)
    if len(h) == 6 and all(c in _HEX for c in h):
        return int(h, 16)
    return None


def parse_osc_color(s):
    """Cor de `OSC 4/10`: `#RRGGBB` ou `rgb:r/g/b` (1/2/4 dígitos); None se inválida."""
    s = s.strip()
    if s.startswith("#"):
        return parse_color(s)
    if not s.startswith("rgb:"):
        return None
    partes = s[4:].split("/")
    if len(partes) != 3:
        return None
    vals = []
    for p in partes:
        # 1/2 dígitos = valor cru; 4 = byte duplicado (ffff = ff), como o xterm
        if len(p) in (1, 2, 4) and all(c in _HEX for c in p):
            vals.append(int(p[:2], 16))
        else:
            return None
    r, g, b = vals
    return (r << 16) | (g << 8) | b


def int_rgb(v):
    """Inteiro `0xRRGGBB` -> tupla (r, g, b)."""
    return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)


class Theme:
    """Cores do terminal (P49): as 16 ANSI, o default fg/bg e o cursor.

    A configuração semeia a base (`apply_colors`); `OSC 4`/`OSC 10-12`
    sobrescrevem por aba, como no Rust — o theme mora no próprio `Term`. O
    cache de floats é por instância: uma aba com cor custom não serve a outra.
    """

    def __init__(self):
        self.pal16 = list(PALETTE)
        self.osc4 = {}  # idx -> (r, g, b), escrito pelo `OSC 4` desta aba
        self.fg = FG_DEFAULT
        self.bg = BG_DEFAULT
        self.cursor = None  # None = mesma cor da frente
        # o que a configuração disse: o que `OSC 110/111/112` volta a ser
        self.base_fg, self.base_bg, self.base_cursor = self.fg, self.bg, None
        self._cache = {}

    def apply_colors(self, colors):
        """Base da configuração (dict parcial das 19 chaves; ausente = padrão)."""
        self.pal16 = list(PALETTE)
        for i in range(16):
            v = colors.get("color%d" % i)
            if v is not None:
                self.pal16[i] = int_rgb(v)
        self.fg = int_rgb(colors["foreground"]) if "foreground" in colors else FG_DEFAULT
        self.bg = int_rgb(colors["background"]) if "background" in colors else BG_DEFAULT
        v = colors.get("cursor_color")
        self.cursor = int_rgb(v) if v is not None else None
        self.base_fg, self.base_bg, self.base_cursor = self.fg, self.bg, self.cursor
        self._cache.clear()

    def color(self, idx):
        """RGB (r, g, b) do índice 0..15, com o `OSC 4` por cima."""
        return self.osc4.get(idx, self.pal16[idx])

    def set_osc4(self, idx, rgbv):
        """`OSC 4;índice;cor` define a entrada desta aba."""
        self.osc4[idx] = rgbv
        self._cache.clear()

    def reset_osc4(self, idxs=None):
        """`OSC 104`: volta as entradas para a base da configuração (None = todas)."""
        if idxs is None:
            self.osc4.clear()
        else:
            for i in idxs:
                self.osc4.pop(i, None)
        self._cache.clear()

    def set_color(self, which, rgbv):
        """`OSC 10/11/12`: define frente, fundo ou cursor."""
        if which == 10:
            self.fg = rgbv
        elif which == 11:
            self.bg = rgbv
        else:
            self.cursor = rgbv
        self._cache.clear()

    def reset_color(self, which):
        """`OSC 110/111/112`: volta para o valor da configuração (a base)."""
        if which == 10:
            self.fg = self.base_fg
        elif which == 11:
            self.bg = self.base_bg
        else:
            self.cursor = self.base_cursor
        self._cache.clear()

    def rgb_f(self, c):
        """Cor da célula em floats 0..1, com a paleta desta aba (o cairo pede float)."""
        v = self._cache.get(c)
        if v is None:
            if c == DEF_FG:
                v = tuple(x / 255 for x in self.fg)
            elif c == DEF_BG:
                v = tuple(x / 255 for x in self.bg)
            elif c & TC:
                v = (
                    ((c >> 16) & 0xFF) / 255,
                    ((c >> 8) & 0xFF) / 255,
                    (c & 0xFF) / 255,
                )
            elif c < 16:
                v = tuple(x / 255 for x in self.color(c))
            else:
                v = _PAL_F[c]
            if len(self._cache) > 4096:
                self._cache.clear()
            self._cache[c] = v
        return v

    def cursor_f(self):
        """Cor do cursor em floats: `cursor_color` (config/OSC 12), senão a frente."""
        r, g, b = self.cursor if self.cursor is not None else self.fg
        return (r / 255, g / 255, b / 255)


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
