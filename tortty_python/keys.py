"""Keyboard: X11 keyval -> the bytes the terminal sends to the child.

The translation lives here, not the state: `encode_key` is pure (it takes the
pending dead key and returns the new one), so it is testable without real GTK.
"""

import unicodedata

from . import kitty_kbd
from .gui import Gdk

# Dead keys do X11: keysym -> marca combinante.
DEAD_MARKS = {
    0xFE50: 0x0300,
    0xFE51: 0x0301,
    0xFE52: 0x0302,
    0xFE53: 0x0303,
    0xFE54: 0x0304,
    0xFE55: 0x0306,
    0xFE56: 0x0307,
    0xFE57: 0x0308,
    0xFE58: 0x030A,
    0xFE59: 0x030B,
    0xFE5A: 0x030C,
    0xFE5B: 0x0327,
    0xFE5C: 0x0328,
}
# dead key + espaço: o caractere espaçado (convenção X11)
DEAD_STANDALONE = {
    0x0300: "`",
    0x0301: "'",
    0x0302: "^",
    0x0303: "~",
    0x0304: "¯",
    0x0306: "˘",
    0x0307: "˙",
    0x0308: '"',
    0x030A: "˚",
    0x030B: "˝",
    0x030C: "ˇ",
    0x0327: "¸",
    0x0328: "˛",
}

# teclas "simples": keyval -> sequência (modo normal, sem DECCKM)
SIMPLE = {
    Gdk.KEY_Return: "\r",
    Gdk.KEY_KP_Enter: "\r",
    Gdk.KEY_BackSpace: "\x7f",
    Gdk.KEY_Tab: "\t",
    Gdk.KEY_Escape: "\x1b",
    Gdk.KEY_Up: "\x1b[A",
    Gdk.KEY_Down: "\x1b[B",
    Gdk.KEY_Right: "\x1b[C",
    Gdk.KEY_Left: "\x1b[D",
    Gdk.KEY_Home: "\x1b[H",
    Gdk.KEY_End: "\x1b[F",
    Gdk.KEY_Insert: "\x1b[2~",
    Gdk.KEY_Delete: "\x1b[3~",
    Gdk.KEY_Page_Up: "\x1b[5~",
    Gdk.KEY_Page_Down: "\x1b[6~",
    Gdk.KEY_F1: "\x1bOP",
    Gdk.KEY_F2: "\x1bOQ",
    Gdk.KEY_F3: "\x1bOR",
    Gdk.KEY_F4: "\x1bOS",
    Gdk.KEY_F5: "\x1b[15~",
    Gdk.KEY_F6: "\x1b[17~",
    Gdk.KEY_F7: "\x1b[18~",
    Gdk.KEY_F8: "\x1b[19~",
    Gdk.KEY_F9: "\x1b[20~",
    Gdk.KEY_F10: "\x1b[21~",
    Gdk.KEY_F11: "\x1b[23~",
    Gdk.KEY_F12: "\x1b[24~",
}

# F13..F24 -> F1..F12 (P60): tabela explícita, porque um erro de aritmética de
# keyval só apareceria na tecla e o Shift já entra como modificador.
F_KEY_SHIFT = {
    Gdk.KEY_F13: Gdk.KEY_F1,
    Gdk.KEY_F14: Gdk.KEY_F2,
    Gdk.KEY_F15: Gdk.KEY_F3,
    Gdk.KEY_F16: Gdk.KEY_F4,
    Gdk.KEY_F17: Gdk.KEY_F5,
    Gdk.KEY_F18: Gdk.KEY_F6,
    Gdk.KEY_F19: Gdk.KEY_F7,
    Gdk.KEY_F20: Gdk.KEY_F8,
    Gdk.KEY_F21: Gdk.KEY_F9,
    Gdk.KEY_F22: Gdk.KEY_F10,
    Gdk.KEY_F23: Gdk.KEY_F11,
    Gdk.KEY_F24: Gdk.KEY_F12,
}

# DECCKM (?1) ligado: setas, Home e End em modo aplicação (\EOA..\EOD).
# É o que o terminfo de xterm chama de "aplicação" e o que mc/vim/less ligam.
APP_CURSOR = {
    Gdk.KEY_Up: "\x1bOA",
    Gdk.KEY_Down: "\x1bOB",
    Gdk.KEY_Right: "\x1bOC",
    Gdk.KEY_Left: "\x1bOD",
    Gdk.KEY_Home: "\x1bOH",
    Gdk.KEY_End: "\x1bOF",
}


# keyvals que são só modificador: apertar Shift não pode, por exemplo, tirar
# o usuário da tela de histórico (o Shift chega como evento de tecla antes da
# tecla de verdade, e "qualquer tecla volta pro vivo" resetava a visão).
MODIFIER_KEYS = frozenset(
    {
        Gdk.KEY_Shift_L,
        Gdk.KEY_Shift_R,
        Gdk.KEY_Control_L,
        Gdk.KEY_Control_R,
        Gdk.KEY_Alt_L,
        Gdk.KEY_Alt_R,
        Gdk.KEY_Meta_L,
        Gdk.KEY_Meta_R,
        Gdk.KEY_Super_L,
        Gdk.KEY_Super_R,
        Gdk.KEY_Hyper_L,
        Gdk.KEY_Hyper_R,
        Gdk.KEY_Caps_Lock,
        Gdk.KEY_Num_Lock,
        Gdk.KEY_ISO_Level3_Shift,
    }
)


def is_modifier(kv):
    return kv in MODIFIER_KEYS


def _mod_param(ctrl, alt, shift):
    """Parâmetro de modificador do xterm: 1 + shift(1) + alt(2) + ctrl(4)."""
    return 1 + (1 if shift else 0) + (2 if alt else 0) + (4 if ctrl else 0)


def _special(seq, ctrl, alt, shift):
    """Sequência de tecla especial com modificadores, no formato do xterm.

    Tecla de controle (\\r, \\x7f, \\t, ESC) só ganha o prefixo ESC do Alt; as
    que já são CSI/SS3 levam o modificador como parâmetro (`\\e[1;3A`,
    `\\e[2;3~`), que é o que xterm, kitty e ghostty mandam.
    """
    if not (ctrl or alt or shift):
        return seq
    mod = _mod_param(ctrl, alt, shift)
    if seq.startswith("\x1b["):
        body = seq[2:]
        if body.endswith("~"):
            return "\x1b[%s;%d~" % (body[:-1], mod)
        return "\x1b[1;%d%s" % (mod, body)
    if seq.startswith("\x1bO"):
        return "\x1b[1;%d%s" % (mod, seq[2:])
    return ("\x1b" + seq) if alt else seq


def encode_key(
    kv,
    state,
    dead_mark=0,
    app_cursor=False,
    kbd_flags=0,
    event=kitty_kbd.PRESS,
    text="",
):
    """Traduz uma tecla.

    Devolve `(out, dead_mark, handled)`:
      out        bytes (str) a mandar pro filho, ou None
      dead_mark  marca combinante ainda pendente (0 = nenhuma)
      handled    True se o evento foi consumido (mesmo sem mandar nada)

    `kbd_flags` é o estado do protocolo de teclado do kitty (?P5): com ele
    ligado, quem decide o formato é `kitty_kbd.encode`; se ela devolver None,
    cai no caminho legado daqui (que é o que o próprio kitty faz).
    """
    ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
    alt = bool(state & Gdk.ModifierType.MOD1_MASK)
    shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
    # F13..F24 são, num teclado de PC, F1..F12 com Shift — é o que o terminfo
    # do xterm diz (`kf13=\E[1;2P`, P60). O Shift entra como modificador e a
    # sequência sai a mesma de F1 com Shift.
    if kv in F_KEY_SHIFT:
        kv, shift = F_KEY_SHIFT[kv], True
    out = None

    if kbd_flags and not dead_mark:
        kitty = kitty_kbd.encode(
            kv,
            shift,
            alt,
            ctrl,
            bool(state & Gdk.ModifierType.SUPER_MASK),
            kbd_flags,
            event,
            text,
        )
        if kitty is not None:
            return kitty, dead_mark, True

    if kv == Gdk.KEY_ISO_Left_Tab:
        out = "\x1b[Z"
    elif kv in SIMPLE:
        out = APP_CURSOR.get(kv, SIMPLE[kv]) if app_cursor else SIMPLE[kv]
        if kv == Gdk.KEY_Tab and shift:
            # Shift+Tab é backtab (\e[Z); o shift já está codificado na forma
            # canônica, então só alt/ctrl entram como parâmetro
            out = "\x1b[Z"
            if alt or ctrl:
                out = "\x1b[1;%dZ" % _mod_param(ctrl, alt, False)
        else:
            out = _special(out, ctrl, alt, shift)
    elif ctrl and Gdk.KEY_a <= kv <= Gdk.KEY_z:
        out = ("\x1b" if alt else "") + chr(kv & 0x1F)
    elif ctrl and Gdk.KEY_A <= kv <= Gdk.KEY_Z:
        out = ("\x1b" if alt else "") + chr((kv + 32) & 0x1F)
    elif ctrl and kv in (Gdk.KEY_space, Gdk.KEY_2):
        out = ("\x1b" if alt else "") + "\x00"
    elif ctrl and kv == Gdk.KEY_minus:
        out = ("\x1b" if alt else "") + "\x1f"
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
        if kv >= 0x01000000:  # unicode direto
            try:
                s = chr(kv & 0xFFFFFF)
            except ValueError:
                s = ""
        elif 0x20 <= kv <= 0x7E or 0xA0 <= kv <= 0xFF:
            s = chr(kv)  # latin-1 imprimível
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
