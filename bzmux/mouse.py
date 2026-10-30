"""Mouse: codificar um evento da janela no protocolo que o app espera.

Puro (só ints e str): não importa Gtk, então dá para testar sem display.
Quem sabe se o app pediu mouse é o `Term` (`?1000`/`?1002`/`?1003`/`?1006`);
aqui só mora o formato dos bytes.

Protocolo xterm:

    1000  press/release de botão
    1002  + movimento com botão apertado
    1003  + movimento sem botão
    1006  SGR: `CSI < b ; x ; y M` (press) / `m` (release), coordenadas
          1-based em decimal — sem o limite de 223 do protocolo antigo
    normal (sem 1006): `CSI M` + 3 bytes (b+32, x+32, y+32); release é
          sempre "botão 3" e coordenada acima de 223 não cabe no byte.
"""

# botões no protocolo (não é o número do botão do Gdk)
LEFT, MIDDLE, RIGHT = 0, 1, 2
RELEASE = 3
WHEEL_UP, WHEEL_DOWN, WHEEL_LEFT, WHEEL_RIGHT = 64, 65, 66, 67
BACK, FORWARD = 128, 129
WHEELS = (WHEEL_UP, WHEEL_DOWN, WHEEL_LEFT, WHEEL_RIGHT)

# bits de modificador no código do botão
MOD_SHIFT, MOD_ALT, MOD_CTRL = 4, 8, 16
MOD_MOTION = 32

# número do botão do Gdk -> botão do protocolo
GDK_BUTTONS = {1: LEFT, 2: MIDDLE, 3: RIGHT, 8: BACK, 9: FORWARD}
GDK_WHEEL = {4: WHEEL_UP, 5: WHEEL_DOWN, 6: WHEEL_LEFT, 7: WHEEL_RIGHT}


def mods_from_state(shift, alt, ctrl):
    """Monta os bits de modificador do protocolo."""
    return (MOD_SHIFT if shift else 0) | (MOD_ALT if alt else 0) | (MOD_CTRL if ctrl else 0)


def encode(button, col, row, pressed=True, sgr=False, mods=0, motion=False):
    """Codifica um evento. `col`/`row` são 0-based (viram 1-based aqui).

    Devolve "" quando o evento não deve ser mandado (release de wheel no
    protocolo antigo, que não existe lá).
    """
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
    x = min(col, 222) + 33
    y = min(row, 222) + 33
    return "\x1b[M" + chr(32 + b) + chr(x) + chr(y)
