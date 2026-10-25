"""Autochetcagem do parser: `python3 pyterm.py --selftest`.

Roda sem display e sem PyGObject: só importa `term`, `palette` e `mouse`,
nunca `window`/`gui`.
"""

from . import kitty_kbd, mouse
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

    # -- kitty keyboard (P5): o essencial do CSI-u ---------------------
    enc = kitty_kbd.encode
    check("kitty: 'a' sem flags vira legado", enc(0x61, 0, 0, 0, 0, 0), None)
    check("kitty: Enter com disambiguate", enc(0xff0d, 0, 0, 0, 0, 1),
          "\x1b[13u")
    check("kitty: Ctrl+a", enc(0x61, 0, 0, 1, 0, 1), "\x1b[97;5u")
    check("kitty: Ctrl+Shift+a", enc(0x61, 1, 0, 1, 0, 1), "\x1b[97;6u")
    check("kitty: Shift+Up (legado com mods)", enc(0xff52, 1, 0, 0, 0, 1),
          "\x1b[1;2A")
    check("kitty: 'a' com report all", enc(0x61, 0, 0, 0, 0, 8), "\x1b[97u")
    check("kitty: release com event types",
          enc(0x61, 0, 0, 1, 0, 3, event=kitty_kbd.RELEASE), "\x1b[97;5:3u")

    t = Term()
    t.feed("\x1b[>1u\x1b[=2;2u")
    check("kitty: flags somam", (t.kbd_flags, t.kbd_stack), (3, [0]))
    t.feed("\x1b[<u")
    check("kitty: pop volta", t.kbd_flags, 0)

    # -- reflow (P3): re-quebra mantendo a linha lógica ---------------
    t = Term(cols=20, rows=4)
    text = "0123456789" * 4
    t.feed(text)
    t.resize(10, 4)
    joined = "".join("".join(c[0] for c in r) for r in t.grid).rstrip()
    check("reflow estreita (1 linha -> 4)", (joined, (t.cx, t.cy)),
          (text, (9, 3)))
    t.resize(20, 4)
    joined = "".join("".join(c[0] for c in r) for r in t.grid).rstrip()
    check("reflow alarga (4 -> 1)", (joined, (t.cx, t.cy)), (text, (19, 1)))

    # -- histórico: a visão desliza sobre scrollback + grade ----------
    t = Term(cols=10, rows=3)
    t.feed("a\r\nb\r\nc\r\nd\r\ne\r\n")
    rows_of = lambda rs: ["".join(c[0] for c in r).rstrip() for r in rs]
    check("histórico off=0 (vivo)", rows_of(t.visible_rows(0)), ["d", "e", ""])
    check("histórico off=1", rows_of(t.visible_rows(1)), ["c", "d", "e"])

    # -- mouse (?1000/?1002/?1006) e seleção -------------------------
    t = Term()
    t.feed("\x1b[?1002h\x1b[?1006h")
    check("mouse modo dragg + sgr", (t.mouse_mode, t.mouse_sgr), (2, True))

    check("SGR press", mouse.encode(mouse.LEFT, 0, 0, True, sgr=True),
          "\x1b[<0;1;1M")
    check("SGR release", mouse.encode(mouse.LEFT, 4, 2, False, sgr=True),
          "\x1b[<0;5;3m")
    check("X10 press", mouse.encode(mouse.LEFT, 0, 0, True),
          "\x1b[M" + chr(32) + chr(33) + chr(33))

    t = Term()
    t.feed("abc\r\ndef\r\nghi")
    check("seleção multi-linha", t.selection_text((0, 1), (1, 1)), "bc\nde")
    check("seleção invertida", t.selection_text((1, 1), (0, 1)), "bc\nde")

    if fails:
        print(f"SELFTEST FAIL ({len(fails)}):")
        for f in fails:
            print("  FAIL:", f)
        return 1
    print("SELFTEST OK")
    return 0
