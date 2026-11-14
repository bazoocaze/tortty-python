"""Kitty keyboard protocol: X11 keyval -> `CSI ... u`.

Pure (ints and str, no Gtk): the decision of *when* to use it belongs to `Term`,
which holds the flags (`kbd_flags`); only the encoding lives here. It mirrors
kitty's `encode_key()`/`encode_function_key()` (`key_encoding.c`), the reference
that actually matters.

Flags (bitmask, stackable through `CSI > flags u`):

    1   disambiguate — esc, enter, tab, backspace and any key with Ctrl/Alt/Super
        come out as `CSI code ; mods u` instead of the control byte
    2   report event types — adds `:1`/`:2`/`:3` (press/repeat/release)
    8   report all keys as escape codes — everything becomes `CSI ... u`, typing
        `a` included
    16  report associated text — `CSI code ; mods ; text u`
    4   report alternate keys — NOT implemented (it needs the alternate keysym,
        which Gdk does not give away for free)

Whatever the new encoding does not cover falls to the legacy path of `keys.py`
(`\x1bOA`, `\x03`, plain text...) — and that is how kitty does it as well.
"""

# teclas funcionais: keyval do X11 -> (número do CSI, trailer)
KEY_ESC, KEY_ENTER, KEY_TAB, KEY_BACKSPACE = 0xFF1B, 0xFF0D, 0xFF09, 0xFF08
FUNCTIONAL = {
    KEY_ESC: (27, "u"),
    KEY_ENTER: (13, "u"),
    KEY_TAB: (9, "u"),
    KEY_BACKSPACE: (127, "u"),
    0xFF63: (2, "~"),  # Insert
    0xFFFF: (3, "~"),  # Delete
    0xFF51: (1, "D"),
    0xFF53: (1, "C"),
    0xFF52: (1, "A"),
    0xFF54: (1, "B"),
    0xFF55: (5, "~"),
    0xFF56: (6, "~"),
    0xFF50: (1, "H"),
    0xFF57: (1, "F"),
    0xFFBE: (1, "P"),
    0xFFBF: (1, "Q"),
    0xFFC0: (13, "~"),
    0xFFC1: (1, "S"),
    0xFFC2: (15, "~"),
    0xFFC3: (17, "~"),
    0xFFC4: (18, "~"),
    0xFFC5: (19, "~"),
    0xFFC6: (20, "~"),
    0xFFC7: (21, "~"),
    0xFFC8: (23, "~"),
    0xFFC9: (24, "~"),
}

PRESS, REPEAT, RELEASE = 1, 2, 3


def _mods(shift, alt, ctrl, super_):
    # valor do campo de modificadores: 1 = nenhum, +1 shift, +2 alt, +4 ctrl
    return 1 + (1 if shift else 0) + (2 if alt else 0) + (4 if ctrl else 0) + (8 if super_ else 0)


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
            out += "1"  # sem modificador o campo tem que existir
    if actions:
        out += ":%d" % actions
    if text:
        out += ";" + ":".join(str(ord(c)) for c in text)
    return out + trailer


def _codepoint(kv):
    """keyval -> codepoint unicode (ou None se não for caractere)."""
    if 0x20 <= kv <= 0x7E or 0xA0 <= kv <= 0xFF:
        return kv
    if kv >= 0x01000000:
        return kv & 0xFFFFFF
    return None


def encode(kv, shift, alt, ctrl, super_, flags, event=PRESS, text=""):
    """Devolve a sequência, None para o caminho legado, ou "" para não mandar nada."""
    seq = _encode(kv, shift, alt, ctrl, super_, flags, event, text)
    if seq is None and event == RELEASE and flags & 2:
        # Release não tem forma legada (o legado é só "a tecla saiu"): sem
        # sequência do kitty, não sai nada. Sem isto o `encode_key` caía no
        # caminho legado e mandava o texto de novo — tecla dobrada no `pi`,
        # que liga a flag 2 (P18).
        return ""
    return seq


def _encode(kv, shift, alt, ctrl, super_, flags, event=PRESS, text=""):
    dis = flags & 1
    ev_types = flags & 2
    report_all = flags & 8
    embed_text = flags & 16
    if event == RELEASE and not ev_types:
        return None  # sem a flag 2 não existe release
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
            return None  # ESC, \r, \t, \x7f clássicos
        return _csi(num, mods, trailer, event if ev_types else None, text_field)

    cp = _codepoint(kv)
    if cp is None:
        return None
    if ctrl and 0x41 <= kv <= 0x5A:
        cp = kv + 32  # Ctrl+Shift+a reporta a tecla base 'a'
    if mods == 2 and not report_all:
        # Shift+letra continua sendo texto puro (o Gdk já entrega o maiúsculo)
        return None
    if mods == 1 and not report_all:
        return None  # texto puro: caminho legado
    if not (dis or report_all):
        return None  # mods sem disambiguate: xterm clássico
    return _csi(cp, mods, "u", event if ev_types else None, text_field)
