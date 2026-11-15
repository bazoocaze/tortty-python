"""The shortcut table: `map`/`unmap` chords and the actions they run.

Pure (no gi), so the parsing and the table can be checked without a display;
window.py turns a chord into a Gdk keyval and runs the action.

The defaults are `map` lines, written the same way the owner writes them, and
they live in the shipped configuration file — deleting one frees the chord.
"""

CHORD_MODS = ("ctrl", "shift", "alt", "super")

# Actions the table may name, with the argument shape each one takes.
ACTIONS = {
    "copy": None,
    "paste": None,
    "new_tab": None,
    "close_tab": None,
    "new_workspace": None,
    "close_workspace": None,
    "prev_prompt": None,
    "next_prompt": None,
    "search": None,
    "open_config": None,
    "scroll_page_up": None,
    "scroll_page_down": None,
    "scroll_top": None,
    "scroll_bottom": None,
    "ws_prev": None,
    "ws_next": None,
    "select_tab": int,
    "select_workspace": int,
}

# The default table: one chord per line, in the syntax the owner writes.
DEFAULTS = [
    "map ctrl+shift+c copy",
    "map ctrl+shift+v paste",
    "map ctrl+shift+t new_tab",
    "map ctrl+shift+w close_tab",
    "map ctrl+shift+n new_workspace",
    "map ctrl+shift+q close_workspace",
    "map ctrl+shift+f2 open_config",
    "map ctrl+shift+f search",
    "map ctrl+shift+up prev_prompt",
    "map ctrl+shift+down next_prompt",
    "map shift+page_up scroll_page_up",
    "map shift+page_down scroll_page_down",
    "map shift+home scroll_top",
    "map shift+end scroll_bottom",
    "map super+n new_workspace",
    "map super+q close_workspace",
    "map super+up ws_prev",
    "map super+down ws_next",
]
DEFAULTS += ["map alt+%d select_tab %d" % (n, 10 if n == 0 else n) for n in range(10)]
DEFAULTS += ["map ctrl+shift+%d select_workspace %d" % (n, 10 if n == 0 else n) for n in range(10)]
DEFAULTS += ["map super+%d select_workspace %d" % (n, 10 if n == 0 else n) for n in range(10)]


def parse_chord(text):
    """`ctrl+shift+y` -> (tecla, modificadores); None quando não é um acorde."""
    partes = [p.strip().lower() for p in text.split("+")]
    if not partes or not partes[-1] or partes[-1] in CHORD_MODS:
        return None
    mods = set()
    for p in partes[:-1]:
        if p not in CHORD_MODS:
            return None  # `ctrl+foo+y` não é acorde: é erro de digitação
        mods.add(p)
    if partes[-1] == "plus" and mods:  # `ctrl+plus` não é ambíguo assim
        return ("plus", frozenset(mods))
    return (partes[-1], frozenset(mods))


def parse_map(value):
    """`ctrl+shift+y new_tab` -> (acorde, ação, argumento); str de erro se não."""
    campos = value.split()
    if not campos:
        return "needs a chord and an action"
    if len(campos) > 3:
        return "too many fields: %s" % value
    chord = parse_chord(campos[0])
    if chord is None:
        return "not a chord: %s" % campos[0]
    if len(campos) < 2:
        return "needs an action after the chord"
    acao = campos[1]
    if acao not in ACTIONS:
        return "unknown action: %s" % acao
    arg = None
    if ACTIONS[acao] is int:
        if len(campos) < 3 or not campos[2].isdigit():
            return "%s needs a number" % acao
        arg = int(campos[2])
        if not 1 <= arg <= 10:
            return "%s takes 1..10" % acao
    elif len(campos) == 3:
        return "%s takes no number" % acao
    return (chord, acao, arg)


def check_map(value):
    """CHECKS entry of the `map` key: the error string, or None.

    A normalized `unmap CHORD` line also arrives here: it is the same table.
    """
    if value.startswith("unmap"):
        return check_unmap(value[5:].strip())
    if value.startswith("map"):
        value = value[3:].strip()
    parsed = parse_map(value)
    return parsed if isinstance(parsed, str) else None


def check_unmap(value):
    """CHECKS entry of the `unmap` key: only a chord, nothing else."""
    campos = value.split()
    if len(campos) != 1:
        return "unmap takes one chord"
    return None if parse_chord(campos[0]) else "not a chord: %s" % campos[0]


class Bindings:
    """Chord -> (action, argument), built from the default table and the config."""

    __slots__ = ("table",)

    def __init__(self, lines=()):
        self.table = {}
        for line in DEFAULTS:
            self._apply(line)
        for line in lines:
            self._apply(line)

    def _apply(self, line):
        """One `map`/`unmap` line; a bad one is ignored (the config already said so)."""
        campos = line.split()
        if not campos:
            return
        if campos[0] == "unmap" and len(campos) >= 2:
            chord = parse_chord(campos[1])
            if chord is not None:
                self.table.pop(chord, None)
            return
        if campos[0] != "map":
            return
        parsed = parse_map(line[3:].strip())
        if isinstance(parsed, tuple):
            chord, acao, arg = parsed
            self.table[chord] = (acao, arg)

    def get(self, key, mods):
        """The action bound to a chord, or None."""
        return self.table.get((key, frozenset(mods)))

    def chords(self):
        """Every bound chord, for the tooltip/dump and for the checks."""
        return sorted(
            (("+".join(sorted(mods)) + "+" if mods else "") + key) for key, mods in self.table
        )
