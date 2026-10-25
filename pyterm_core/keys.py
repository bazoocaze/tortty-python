"""Teclado: keyval do X11 -> bytes que o terminal manda pro filho.

Aqui mora a tradução, não o estado: `encode_key` é pura (recebe o dead key
pendente e devolve o novo), então dá para testar sem GTK de verdade.
"""

import unicodedata

from .gui import Gdk

# Dead keys do X11: keysym -> marca combinante.
DEAD_MARKS = {
    0xfe50: 0x0300, 0xfe51: 0x0301, 0xfe52: 0x0302, 0xfe53: 0x0303,
    0xfe54: 0x0304, 0xfe55: 0x0306, 0xfe56: 0x0307, 0xfe57: 0x0308,
    0xfe58: 0x030a, 0xfe59: 0x030b, 0xfe5a: 0x030c, 0xfe5b: 0x0327,
    0xfe5c: 0x0328,
}
# dead key + espaço: o caractere espaçado (convenção X11)
DEAD_STANDALONE = {
    0x0300: "`", 0x0301: "'", 0x0302: "^", 0x0303: "~", 0x0304: "¯",
    0x0306: "˘", 0x0307: "˙", 0x0308: '"', 0x030a: "˚", 0x030b: "˝",
    0x030c: "ˇ", 0x0327: "¸", 0x0328: "˛",
}

# teclas "simples": keyval -> sequência (modo normal, sem DECCKM)
SIMPLE = {
    Gdk.KEY_Return: "\r", Gdk.KEY_KP_Enter: "\r",
    Gdk.KEY_BackSpace: "\x7f", Gdk.KEY_Tab: "\t",
    Gdk.KEY_Escape: "\x1b",
    Gdk.KEY_Up: "\x1b[A", Gdk.KEY_Down: "\x1b[B",
    Gdk.KEY_Right: "\x1b[C", Gdk.KEY_Left: "\x1b[D",
    Gdk.KEY_Home: "\x1b[H", Gdk.KEY_End: "\x1b[F",
    Gdk.KEY_Insert: "\x1b[2~", Gdk.KEY_Delete: "\x1b[3~",
    Gdk.KEY_Page_Up: "\x1b[5~", Gdk.KEY_Page_Down: "\x1b[6~",
    Gdk.KEY_F1: "\x1bOP", Gdk.KEY_F2: "\x1bOQ",
    Gdk.KEY_F3: "\x1bOR", Gdk.KEY_F4: "\x1bOS",
    Gdk.KEY_F5: "\x1b[15~", Gdk.KEY_F6: "\x1b[17~",
    Gdk.KEY_F7: "\x1b[18~", Gdk.KEY_F8: "\x1b[19~",
    Gdk.KEY_F9: "\x1b[20~", Gdk.KEY_F10: "\x1b[21~",
    Gdk.KEY_F11: "\x1b[23~", Gdk.KEY_F12: "\x1b[24~",
}

# DECCKM (?1) ligado: setas, Home e End em modo aplicação (\EOA..\EOD).
# É o que o terminfo de xterm chama de "aplicação" e o que mc/vim/less ligam.
APP_CURSOR = {
    Gdk.KEY_Up: "\x1bOA", Gdk.KEY_Down: "\x1bOB",
    Gdk.KEY_Right: "\x1bOC", Gdk.KEY_Left: "\x1bOD",
    Gdk.KEY_Home: "\x1bOH", Gdk.KEY_End: "\x1bOF",
}


def encode_key(kv, state, dead_mark=0, app_cursor=False):
    """Traduz uma tecla.

    Devolve `(out, dead_mark, handled)`:
      out        bytes (str) a mandar pro filho, ou None
      dead_mark  marca combinante ainda pendente (0 = nenhuma)
      handled    True se o evento foi consumido (mesmo sem mandar nada)
    """
    ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
    alt = bool(state & Gdk.ModifierType.MOD1_MASK)
    shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
    out = None

    if kv == Gdk.KEY_ISO_Left_Tab:
        out = "\x1b[Z"
    elif kv in SIMPLE:
        out = SIMPLE[kv]
        if app_cursor:
            out = APP_CURSOR.get(kv, out)
        if kv == Gdk.KEY_Tab and shift:
            out = "\x1b[Z"
    elif ctrl and Gdk.KEY_a <= kv <= Gdk.KEY_z:
        out = chr(kv & 0x1f)
    elif ctrl and Gdk.KEY_A <= kv <= Gdk.KEY_Z:
        out = chr((kv + 32) & 0x1f)
    elif ctrl and kv in (Gdk.KEY_space, Gdk.KEY_2):
        out = "\x00"
    elif ctrl and kv == Gdk.KEY_minus:
        out = "\x1f"
    elif kv in DEAD_MARKS and not (ctrl or alt):
        # dead key: guarda a marca e não manda nada agora
        return None, DEAD_MARKS[kv], True
    else:
        # SÓ caractere imprimível vira byte. Keyval de modificador e de
        # tecla de função fica na faixa 0xff00-0xffff (Shift_L=0xffe1,
        # Control_L=0xffe3, Alt_L=0xffe9, Super_L=0xffeb, Caps_Lock=0xffe5,
        # Menu=0xff67); sem este filtro cada uma virava um caractere sem
        # glifo (a "caixinha" na tela).
        s = ""
        if kv >= 0x01000000:                    # unicode direto
            try:
                s = chr(kv & 0xFFFFFF)
            except ValueError:
                s = ""
        elif 0x20 <= kv <= 0x7e or 0xa0 <= kv <= 0xff:
            s = chr(kv)                          # latin-1 imprimível
        if not s or ctrl:
            return None, dead_mark, False
        if dead_mark:
            mark, dead_mark = dead_mark, 0
            if s == " ":
                out = DEAD_STANDALONE.get(mark, " ")
            else:
                comp = unicodedata.normalize("NFC", s + chr(mark))
                out = comp if len(comp) == 1 else s
            if alt:
                out = "\x1b" + out
        else:
            out = ("\x1b" + s) if alt else s

    if out:
        return out, dead_mark, True
    return None, dead_mark, False
