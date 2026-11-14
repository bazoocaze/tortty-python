# TorTTY-Python — limits

Accepted or still unresolved limitations. Planned work lives in `BACKLOG.md`
(`P<n>`). A limitation already overcome leaves here and goes to `HISTORY.md`
(through a `BACKLOG` activity).

## Performance (the cost of the path in Python)

- **Throughput of a few MB/s, several times below kitty on the same load** —
  it is not a bug, it is the measurement, and the pair (with date, governor,
  frequency and the ladder that decomposes it) is in
  [`BENCHMARKS.md`](BENCHMARKS.md). After P20–P22 the pty IO stopped
  being the bottleneck; what is left is the **parse in Python** and the
  **drawing**, in that order.
- **Interaction does not suffer**: a key costs microseconds; the limit only
  shows up under volume (cat of a big log, seq 100000, scroll of massive output).
- **One core per active session**: under continuous dumping tortty-python saturates
  one core. The drawing is coalesced at ~16 ms (60 Hz) on purpose, so the parse
  does not starve.
- **The metadata makes no performance claim**: the package description says what
  the app has (tabs, workspaces, images), not "light" nor "fast". Light is true
  in **footprint** (the number is in [`BENCHMARKS.md`](BENCHMARKS.md)) and false
  in throughput, which is the limit above; a speed claim would become a promise
  that the ruler itself refutes.

## Cell model and text

- **No `wcwidth`**: a wide character (CJK, emoji) takes **one** cell. The glyph
  is drawn at the cell width: an app that counts double columns (CJK table,
  `vim` with wide chars) comes out misaligned. Fixing it means a continuation
  flag per cell (the packed value keeps two spare bits for it) and a cell that
  spans two columns in the parser, the reflow and the drawing.
- **No cell combining for a complex grapheme**: each cell carries one
  character, and a mark emitted separately by an app now glues to the cell
  before it (`e` + acute is one cell). Marks below a base cell at the start of
  the line still get a cell of their own, and a grapheme that needs **two base
  characters** (a Hangul jamo sequence, a ZWJ emoji) is shaped only inside the
  cell it lands in.
- **Ligature depends on the installed font**: shaping exists (Pango) and both
  the family (`font_family`) and the ligature mode (`ligatures`: off, standard,
  all) are configurable, but the machine's default Monospace (DejaVu) has
  almost no ligature — whoever wants it needs a Fira Code or JetBrains
  installed and to pick it. `font_size` is in **points** (terminal convention,
  converted by the display's DPI), not pixels.

## VT parser (what is not interpreted)

- **Partial SGR**: implements 0, 1, 2 (faint), 3, 4 (with `4:n`), 5/6 (blink),
  7, 8 (hidden), 9/29 (strikethrough), 21, 22, 23, 24, 25, 27, 30–37, 39, 40–47,
  49, 53/55 (overline), 90–97, 100–107, 38/48 (256 and truecolor). **Does not**
  implement 58/59 (underline color, which the Rust draws).
- **No special margins**: `DECSTBM` (scroll region) and `? 6` (origin mode)
  work, but `? 3` (80/132) and `DECDHL`/`DECDWL` (double line) do not.
- **Tab stops are re-seeded on resize**: `HTS`, `TBC`, `CHT` and `CBT` are
  real, but a resize puts the stops back every 8 instead of preserving what the
  app set — the Rust choice too.
- **The keypad application mode is state only**: `DECKPAM`/`DECKPNM` (`ESC =` /
  `ESC >`) and the `?66` query are answered, but the keypad keys send the same
  bytes either way — same decision as the Rust.

## OSC (what is not served)

- **`OSC 8` ignores most of the parameters**: `id=` groups cells into one link
  (the underline follows the group); the rest of the `key=value` list is
  accepted and discarded.
- **`OSC 7` is a fallback, not the source**: the cwd of a new tab comes from
  `/proc` (last descendant) and only then from the sequence, which needs a
  shell that emits it — the app does not ship shell integration. **No `OSC
  133`** (prompt marks).
- **Notifications go to the daemon only when the window is behind**: `OSC 9`
  and `777;notify` reach `org.freedesktop.Notifications` when the window is not
  active (and stay silent when there is no daemon); there is no per-app
  configuration of urgency or category, and the `9;4` progress reaches only the
  tab label (no taskbar entry).

## Mouse and selection

- **A block does not survive a resize by its columns**: the corners are
  carried like a linear selection, so a reflow moves the rectangle with the
  characters instead of re-deriving the column range.
- **No search in the scrollback**.
- **Selection does not survive a resize nor a reflow**: anchor and tip are
  grid coordinates.

## Keyboard

- **Partial kitty protocol**: no `report alternate keys` (flag 4 — Gdk
  does not deliver the alternate keysym directly) and no repeat distinguished
  from press (Gdk repeats as key-press).
- **Non-US layouts**: the keyval→bytes translation is by table; text comes from
  Gdk's `ev.string` when it exists, but shortcuts with dead keys and an exotic
  layout depend on what Gdk delivers.
- **Freezing the output (`Ctrl+S`/`Ctrl+Q`) is the tty's, not the terminal's**:
  whoever stops and resumes byte delivery is the kernel's *line discipline*
  (`IXON` in termios). The app only delivers `0x13`/`0x11` to the child — and
  that is why it does not work in an app in raw mode (`vim`, `mc`, `pi`): they
  clear `IXON`, and every terminal behaves that way. A "pause" of ours (stop
  reading the pty) would change the semantics and is not done.

## Graphics (image protocol)

- **No animation and no z-index**: `a=f`/`a=a` are ignored, `z=` does not exist;
  the image goes in arrival order, above the text and below the cursor.
- **No external data source**: `t=f` (file), `t=t` (temp file) and `t=s`
  (shared memory) are not read — the image has to come in the base64 escape.
- **No optimized `f=100` beyond PNG**: PNG is read directly by cairo; raw RGBA
  goes through a copy because of the stride.
- **No sixel and no iTerm2 inline images**: only the kitty protocol.

## Reflow and scrollback

- **Reflow only in the main buffer**: in alt-screen (`mc`, `vim`) the resize
  crops/pads on purpose — whoever is in full screen redraws itself
  on SIGWINCH, and re-wrapping over what it wrote would get in the way.
- **The scrollback returns to live only by an action or by being one line from
  the end**: after scrolling, the view stays anchored at the line where you
  stopped reading until an action of yours (scroll to the end, a key, the app
  clearing the scrollback with `CSI 3J`) or until new output while the view sits
  **one line** from the end (there is nothing to read there). Discarded by
  decision: return by time (5 s without scrolling measures the wrong thing:
  reading is silent, and an app that writes every 1 s would tear the user away
  as soon as the deadline expired).

## Interface

- **Window position is only remembered on X11**: on Wayland the client does not
  choose where the window sits, so the state file stores only size and
  maximized. It is not a lack of code, it is the protocol.
- **Shortcuts are not remappable**: the configuration file covers font, size,
  cursor, scrollback, padding, bell, copy, the 19 terminal colors
  (`foreground`, `background`, `cursor_color`, `color0..15`, plus `OSC 4/10-12`
  at runtime) and, since P75, the eight chrome colors (`chrome_bg`,
  `chrome_fg`, hover, accent and separator). What remains fixed in the code is
  the shortcut table.
- **No copy/scrollback mode**: no text editor over the scrollback.

## Scope (decision, not lack)

- **Not a distributed product**: it was born as an experiment to measure the
  cost of the hot path in Python and became a real application for daily use. It
  has an installable package (`pipx` or `install.sh`, item P31), but no release,
  PyPI, installer for another platform, semantic versioning nor support.
- **Linux only, with the system GTK3**: PyGObject and cairo come from the distro
  and the chrome is GTK3 — macOS and Windows would require carrying the whole
  stack, which is the P30 study in [PORTABILITY.md](PORTABILITY.md). It is not
  portability promised for later; it is where it runs.
- **Pure Python is a decision, not a pending item**: the experiment asked
  whether it was possible to make a whole terminal in Python and the answer was
  yes — it is used daily like this. The throughput ceiling (the pair against
  kitty is in [`BENCHMARKS.md`](BENCHMARKS.md)) is the accepted price, and it is
  attacked by optimizing the path in Python (parse, drawing), not by rewriting
  in C.
- **Native core (C or Rust) does not enter**: it was tried before, in the
  sibling experiment that embeds the kitty core as a C lib: ~4.9 thousand lines
  of hand-written C and 68 commits in 6 days, and the expensive bugs were of the
  **boundary**, not of VT — the key going twice to the pty when merging the
  instrumentation, and the one-frame delay that passed as "not the app's" and
  cost two days to find, with false metrics of up to 1.6 s created by the
  instrument itself. The same app in Python came out in ~3.5 thousand lines,
  faster and with more scope. Crossing the boundary (ABI, duplicated state,
  debugging in two languages, a test that requires a build) charges more than
  the piece of code it avoids. If throughput becomes a priority, the route is to
  optimize the Python (P26/P27) or rewrite the core in the same repository and
  in the same language — not to glue someone else's core.
- **One user, one machine**: no session multiplexing, server, or reconnection.
