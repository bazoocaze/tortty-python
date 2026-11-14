"""Mouse: encode a window event in the protocol the app expects.

Pure (ints and str only): it does not import Gtk, so it is testable without a
display. Who knows whether the app asked for the mouse is `Term`
(`?1000`/`?1002`/`?1003`/`?1006`); only the byte format lives here.

xterm protocol:

    1000  button press/release
    1002  + motion with a button held down
    1003  + motion with no button
    1006  SGR: `CSI < b ; x ; y M` (press) / `m` (release), 1-based decimal
          coordinates — no 223 limit as in the old protocol
    1016  the same shape as 1006, with the coordinates in PIXELS from the
          origin of the grid (the caller that passes col/row fills in pixels)
    1015  urxvt: `CSI b ; x ; y M`, the button in decimal with the X10 +32 and
          1-based coordinates; release is still button 3
    1005  UTF-8: `CSI M` + (b+32) and x+32/y+32 as UTF-8 code points — no 223
          limit as in the old protocol
    plain (no 1006): `CSI M` + 3 bytes (b+32, x+32, y+32); release is always
          "button 3" and a coordinate above 223 does not fit in the byte.

    With more than one form on the SGR wins (P69): it is the one with no
    coordinate limit, and 1015 is the one xterm itself discourages.
"""

# botões no protocolo (não é o número do botão do Gdk)
LEFT, MIDDLE, RIGHT = 0, 1, 2
RELEASE = 3
WHEEL_UP, WHEEL_DOWN, WHEEL_LEFT, WHEEL_RIGHT = 64, 65, 66, 67
BACK, FORWARD = 128, 129
WHEELS = (WHEEL_UP, WHEEL_DOWN, WHEEL_LEFT, WHEEL_RIGHT)


class Notches:
    """Fração de rolagem acumulada até virar um detente (P48).

    O detente do mouse chega inteiro; o touchpad manda frações que só valem
    quando completam uma unidade. Mudar de direção descarta o resto: o dedo
    virou e a fração do caminho anterior não é intenção.
    """

    def __init__(self):
        self._frac = 0.0

    def add(self, delta, unit=1.0):
        """Soma `delta` (com sinal) e devolve os detentes completados (0, ±1…)."""
        if not delta:
            return 0
        if self._frac and (delta > 0) != (self._frac > 0):
            self._frac = 0.0
        self._frac += delta
        n = int(self._frac / unit)
        if n:
            self._frac -= n * unit
        return n

    def reset(self):
        """Descarta a fração pendente (ex.: chegou um detente inteiro)."""
        self._frac = 0.0


# bits de modificador no código do botão
MOD_SHIFT, MOD_ALT, MOD_CTRL = 4, 8, 16
MOD_MOTION = 32

# número do botão do Gdk -> botão do protocolo
GDK_BUTTONS = {1: LEFT, 2: MIDDLE, 3: RIGHT, 8: BACK, 9: FORWARD}
GDK_WHEEL = {4: WHEEL_UP, 5: WHEEL_DOWN, 6: WHEEL_LEFT, 7: WHEEL_RIGHT}


def mods_from_state(shift, alt, ctrl):
    """Monta os bits de modificador do protocolo."""
    return (MOD_SHIFT if shift else 0) | (MOD_ALT if alt else 0) | (MOD_CTRL if ctrl else 0)


def _utf8(cp):
    """Code point -> bytes UTF-8 (a coordenada estendida do ?1005)."""
    return chr(cp).encode("utf-8").decode("latin-1")


def encode(
    button,
    col,
    row,
    pressed=True,
    sgr=False,
    mods=0,
    motion=False,
    pixels=False,
    urxvt=False,
    utf8=False,
):
    """Codifica um evento. `col`/`row` são 0-based (viram 1-based aqui).

    `pixels` (?1016): `col`/`row` chegam em pixels e a forma é a SGR — não
    existe protocolo antigo de pixel para onde cair (P46). Devolve "" quando o
    evento não deve ser mandado (release de wheel no protocolo antigo).
    """
    sgr = sgr or pixels
    mods &= MOD_SHIFT | MOD_ALT | MOD_CTRL
    if not pressed and not sgr and button in WHEELS:
        return ""  # wheel no protocolo antigo é só press
    b = button | mods
    if motion:
        b |= MOD_MOTION
    if sgr:
        return "\x1b[<%d;%d;%d%s" % (
            b,
            col + 1,
            row + 1,
            "M" if pressed else "m",
        )
    # protocolo antigo: release é sempre 3 (o app sabe qual botão pelo
    # press anterior) e cada coordenada é um byte 32..255
    if not pressed:
        b = RELEASE | mods
    if urxvt:
        # P69: mesmo código de botão do X10, só que em decimal
        return "\x1b[%d;%d;%dM" % (b + 32, col + 1, row + 1)
    if utf8:
        # P69: coordenadas como code points UTF-8 (sem o teto de 223)
        return "\x1b[M" + chr(32 + b) + _utf8(col + 1 + 32) + _utf8(row + 1 + 32)
    x = min(col, 222) + 33
    y = min(row, 222) + 33
    return "\x1b[M" + chr(32 + b) + chr(x) + chr(y)
