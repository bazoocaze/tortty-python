"""Autochetcagem do parser: `python3 pyterm.py --selftest`.

Roda sem display e sem PyGObject: só importa `term`, nunca `window`.
"""

from .palette import DEF_FG
from .term import Term


def selftest():
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: obtido {got!r}, esperado {want!r}")
        else:
            print(f"  ok: {name}")

    t = Term()
    t.feed("oi")
    check("texto", t.row_text(0)[:2], "oi")
    check("cursor", (t.cx, t.cy), (2, 0))

    t = Term()
    t.feed("\x1b[31mX\x1b[0mY")
    check("SGR fg", (t.grid[0][0][1], t.grid[0][1][1]), (1, DEF_FG))

    t = Term()
    t.feed("\x1b[2;5H*\x1b[1;1H#")
    check("CUP", (t.grid[1][4][0], t.grid[0][0][0]), ("*", "#"))

    t = Term()
    t.feed("abc\x1b[2K")
    check("EL 2", t.row_text(0)[:3], "   ")
    t.feed("abc\x1b[2Jx")
    check("ED 2", (t.row_text(0)[0], (t.cx, t.cy)), ("x", (1, 0)))

    t = Term()
    t.feed("\x1b[?1049hALT\x1b[?1049l")
    check("altscreen volta", t.row_text(0)[:3], "   ")
    t2 = Term()
    t2.feed("\x1b[?1049hALT")
    check("altscreen mostra", t2.row_text(0)[:3], "ALT")

    t = Term()
    t2 = t
    for _ in range(30):
        t.feed("l\n")
    check("scroll", (len(t.scrollback) > 0, t.cy), (True, 23))

    t = Term()
    t.feed("\x1b(0qqqq\x1b(B")
    check("DEC linha", t.row_text(0)[:4], "────")

    t = Term()
    t.feed("\x1b[c")
    check("DA responde", bytes(t.child_out), b"\x1b[?62c")
    t.child_out = bytearray()
    t.feed("\x1b[5;9H\x1b[6n")
    check("DSR/CPR", bytes(t.child_out), b"\x1b[5;9R")

    t = Term()
    t.feed("\x1b[3;10r")
    check("scroll region", (t.top, t.bottom), (2, 9))

    t = Term()
    t.feed("\x1b]0;titulo\x07")
    check("OSC título", t.title, "titulo")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}):")
        for f in fails:
            print("  FAIL:", f)
        return 1
    print("SELFTEST OK")
    return 0
