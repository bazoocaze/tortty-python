"""Protocolo de teclado do kitty: keyval do X11 -> `CSI ... u`.

Puro (ints e str, sem Gtk): a decisão de *quando* usar é do `Term`, que guarda
as flags (`kbd_flags`); aqui só mora a codificação. Espelha o
`encode_key()`/`encode_function_key()` do kitty (`repos/kitty/kitty/
key_encoding.c`), que é a referência de verdade.

Flags (bitmask, empilháveis por `CSI > flags u`):

    1   disambiguate — esc, enter, tab, backspace e tecla com Ctrl/Alt/Super
        saem como `CSI codigo ; mods u` em vez do byte de controle
    2   report event types — acrescenta `:1`/`:2`/`:3` (press/repeat/release)
    8   report all keys as escape codes — tudo vira `CSI ... u`, inclusive
        digitar `a`
    16  report associated text — `CSI codigo ; mods ; texto u`
    4   report alternate keys — NÃO implementado (exige o keysym alternativo,
        que o Gdk não dá de graça)

O que fica de fora do encoding novo cai no caminho legado do `keys.py`
(`\x1bOA`, `\x03`, texto puro...) — e é assim no kitty também.
"""

# teclas funcionais: keyval do X11 -> (número do CSI, trailer)
KEY_ESC, KEY_ENTER, KEY_TAB, KEY_BACKSPACE = 0xff1b, 0xff0d, 0xff09, 0xff08
FUNCTIONAL = {
    KEY_ESC: (27, "u"), KEY_ENTER: (13, "u"), KEY_TAB: (9, "u"),
    KEY_BACKSPACE: (127, "u"),
    0xff63: (2, "~"),    # Insert
    0xffff: (3, "~"),    # Delete
    0xff51: (1, "D"), 0xff53: (1, "C"), 0xff52: (1, "A"), 0xff54: (1, "B"),
    0xff55: (5, "~"), 0xff56: (6, "~"),
    0xff50: (1, "H"), 0xff57: (1, "F"),
    0xffbe: (1, "P"), 0xffbf: (1, "Q"), 0xffc0: (13, "~"), 0xffc1: (1, "S"),
    0xffc2: (15, "~"), 0xffc3: (17, "~"), 0xffc4: (18, "~"),
    0xffc5: (19, "~"), 0xffc6: (20, "~"), 0xffc7: (21, "~"),
    0xffc8: (23, "~"), 0xffc9: (24, "~"),
}

PRESS, REPEAT, RELEASE = 1, 2, 3


def _mods(shift, alt, ctrl, super_):
    # valor do campo de modificadores: 1 = nenhum, +1 shift, +2 alt, +4 ctrl
    return 1 + (1 if shift else 0) + (2 if alt else 0) + \
        (4 if ctrl else 0) + (8 if super_ else 0)


def _csi(key, mods, trailer, event=None, text=""):
    """Monta `CSI key ; mods[:evento] [;texto] trailer`."""
    actions = event if event not in (None, PRESS) else None
    out = "\x1b["
    if key != 1 or mods != 1 or actions or text:
        out += str(key)
    if mods != 1 or actions:
        out += ";"
        if mods != 1:
            out += str(mods)
        elif actions:
            out += "1"          # sem modificador o campo tem que existir
    if actions:
        out += ":%d" % actions
    if text:
        out += ";" + ":".join(str(ord(c)) for c in text)
    return out + trailer


def _codepoint(kv):
    """keyval -> codepoint unicode (ou None se não for caractere)."""
    if 0x20 <= kv <= 0x7e or 0xa0 <= kv <= 0xff:
        return kv
    if kv >= 0x01000000:
        return kv & 0xFFFFFF
    return None


def encode(kv, shift, alt, ctrl, super_, flags, event=PRESS, text=""):
    """Devolve a sequência do protocolo, ou None para usar o caminho legado."""
    dis = flags & 1
    ev_types = flags & 2
    report_all = flags & 8
    embed_text = flags & 16
    if event == RELEASE and not ev_types:
        return None                     # sem a flag 2 não existe release
    mods = _mods(shift, alt, ctrl, super_)
    text_field = text if (embed_text and text) else ""

    if kv in FUNCTIONAL:
        num, trailer = FUNCTIONAL[kv]
        special = kv in (KEY_ESC, KEY_ENTER, KEY_TAB, KEY_BACKSPACE)
        if not special and mods == 1 and not report_all:
            # setas, Home/End, F1-F12 sem modificador: o legado já faz certo
            # (inclusive DECCKM), e é o que o kitty manda com `disambiguate`
            return None
        if special and mods == 1 and not (dis or report_all):
            return None                 # ESC, \r, \t, \x7f clássicos
        return _csi(num, mods, trailer,
                    event if ev_types else None, text_field)

    cp = _codepoint(kv)
    if cp is None:
        return None
    if ctrl and 0x41 <= kv <= 0x5a:
        cp = kv + 32                   # Ctrl+Shift+a reporta a tecla base 'a'
    if mods == 2 and not report_all:
        # Shift+letra continua sendo texto puro (o Gdk já entrega o maiúsculo)
        return None
    if mods == 1 and not report_all:
        return None                     # texto puro: caminho legado
    if not (dis or report_all):
        return None                     # mods sem disambiguate: xterm clássico
    return _csi(cp, mods, "u", event if ev_types else None, text_field)
