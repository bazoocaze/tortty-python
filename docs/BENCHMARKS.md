# Benchmarks and measurement

The only doc with throughput, drawing, parse and footprint numbers — with date
and governor. The other docs state the fact in one sentence and link here.

- Main load: doom-fire (`tools/doomfire.py`, P16) — synthetic worst case, the
  headline number.
- Real load: `dmesg`, with and without color.
- Ladder and decompositions: IO, parse and drawing separated, with probes and
  profile.
- Footprint: app memory and the weight of installing the graphical stack.
- Comparison protocol and measurement pitfalls.

## Conventions

- Format for agent: title, list item, `code` and fence for command.
  Table only for tabular data (measurement with columns), never decorative.
- Concise: each section answers one question, and a fact has one home inside
  here too. Repeated reading in two sections is divergence waiting to happen:
  the other section cites in five words and points. Narrative of attempt stays in
  HISTORY. The exception is the measurement condition (date, governor, grid,
  command), which repeats in each table. A new measurement updates the number; it
  does not get a conclusion paragraph.
- No bold for emphasis and no italics: here there is no risk to flag, and the
  number with its condition is already the highlight.
- One quantity per item: the number, the condition (date, governor, grid,
  command) and the reading in the same list.
- Number only here: throughput, drawing, parse and footprint live in this file;
  the other docs cite in one sentence and link.
- A number without a condition is worthless: date, governor and CPU frequency,
  the grid (cols x lines) and the exact command.
- Comparison requires the same grid and the same font; a number from another
  configuration does not enter the same table.
- Explicit unit: fps, MB/s, bytes/frame, µs/cell, ms per `draw` or `pty` call.
- An estimate is said to be an estimate, with how it was obtained; no rounded
  number presented as a measurement.
- A measurement pitfall goes to "Pitfalls"; a tool or session one, to
  [DEBUG.md](DEBUG.md); dated narrative of an item, to
  [HISTORY.md](HISTORY.md).

## Main load: doom-fire

- The hot path is parser → grid → grouping by color → drawing in cairo.
- To measure throughput neither `seq 1 100000` (a single color) nor `vim` (few
  cells per frame) works: the worst case is the whole screen changing color on
  every frame.
- Doom-fire (PSX port: intensity buffer 0..36 propagated bottom-up with decay,
  palette of 37 shades) is that, and it is synthetic: no real app, no network.
- Drawn in half-block (`▀`, two pixels per cell) with truecolor fg and bg per
  cell, without grouping: each cell costs two escapes of 16 to 19 bytes.

### How to run

```
./bench.sh                       # the whole ladder, 300 frames (~20 s)
./bench.sh --frames 1200         # the reference protocol
./bench.sh --cols 70 --rows 21   # another grid (the one from 2026-10-27)
./bench.sh --xvfb                # only the virtual display
./bench.sh --sem-xvfb            # only the current display
python3 tools/doomfire.py                      # 30 fps until Ctrl+C
python3 tools/doomfire.py --fps 0 --frames 1200 --stats-to /tmp/x.txt
```

- `--fps N` — fixed pace; `0` lets go and the terminal is what limits.
- `--frames N` — stops after N frames; `0` (default) goes until Ctrl+C.
- `--stats-to FILE` — statistics to a file (`-`, default, goes to stderr).
- `--fps 0 --stats-to` is the measurement mode: the fps reached is the terminal
  throughput, and the file avoids depending on reading the screen.
- Grid = terminal size (`cols × lines`, buffer of `cols × 2·lines`
  pixels); the tool does not resize.
- `bench.sh` runs the ladder (full, `NODRAW`, `NOPARSE+NODRAW`) **twice**, on the
  current display and on a private Xvfb that it starts and kills itself, plus the
  isolated generator: seven lines. It prints fps, MB/s, bytes/frame, `draw ms/call`,
  `pty ms/call` and the CPU frequency per step. It stores no number: the
  reference ones are the ones here.
- The two displays are the point: the real X of the desktop uses glamor and Xvfb
  paints into the pixmap, so the same grid costs 3.4x more drawing on `:0`.
  Measuring both in the same run separates what is code from what is server — and
  a value alone, without the display noted, compares with nothing.
- The condition is pinned by the **grid**, not by the window: `tools/benchrun.py`
  starts the app with the socket, adjusts with `resize` until `cols×rows` matches
  the target, checks it, and only then types the load into the pty; different grid
  = step without a number (code 3), never a number from another condition. The
  default is **61×18 with font 13** (the window that fits without being
  maximized); `--cols/--rows/--font-size` change it, and the grid used comes out in
  the table footer.
- The grid does not come from the pixels: cell = font × dpi, and dpi is the
  session's `Xft.dpi` (`130` on the author's desktop, `96` without the resource).
  The same 980x640 window is 70×21 at 130 and 98×27 at 96 — that is why the target
  is in cells.
- Do not type the load before the window settles: with `--cmd` the child can
  measure the default 80×24 (the first `TIOCSWINSZ` arrives later) and the number
  becomes one from another grid. That is why `benchrun.py` writes to the pty only
  after `state` confirms the target.

### The machine's number today

Condition: the first three steps of `bench.sh`, 1200 frames, font 13,
`schedutil` at 4.25–4.29 GHz, 2026-11-01, one terminal at a time.

| display | grid | fps | MB/s | bytes/frame | `draw` |
|---|---|---|---|---|---|
| `:0` (X with glamor) | 61×18 | 113.9 | 4.9 | 42.8 KB | 13.9 ms |
| Xvfb `:96` (without glamor) | 61×18 | 129.2 | 5.5 | 42.3 KB | 4.2 ms |
| `:0` (X with glamor) | 70×21 | 53.0 | 3.0 | 57.0 KB | 20.6 ms |
| Xvfb `:96` (without glamor) | 70×21 | 111.4 | 6.3 | 56.7 KB | 5.8 ms |

- The same code, the same grid and almost the same pixel area: 4.2 ms on Xvfb and
  13.9 ms on real X (61×18), 5.8 versus 20.6 ms (70×21). The difference is the
  server path — `:0` uses `modesetting` + `glamoregl`, where every cairo fill
  becomes GL work; Xvfb paints straight into the pixmap.
- A benchmark number, therefore, is a property of the **display** as much as of
  the code: compare only within the same display, and note which one.
- The `draw` timer covers ~40% of the frame (8.3 ms of 18.9 ms at 70×21); the
  rest is flush and painting on the server side, outside `on_draw`.
- fps is not linear in the number of cells because each drawing covers several
  generator frames (2.5 at 70×21, 3.8 at 61×18): the terminal paints the newest
  state and discards the intermediate ones.
- The 2026-10-27 reference below (110–122 fps at 70×21) is from another moment
  of this machine: it is not a re-measurement, and the `bench.sh` default today is
  61×18.

### The number

Condition: grid 70×21 (1,470 cells), 13-point font (the default of that time,
today the default is 12), `--fps 0 --frames 1200`,
one terminal at a time, 3 shots of each on 2026-10-27, `schedutil` with turbo at
4.29 GHz.

| | fps | MB/s of escapes | bytes/frame |
|---|---|---|---|
| tortty-python | 110.4–122.6 | 6.2–6.9 | ~56 KB |
| kitty 0.48.2 | 675.8–714.2 | 38.5–40.7 | ~56 KB |

- Distance of ~6x (5.6–6.6x shot by shot): tortty-python spends ~7.7 ms per frame of
  1470 cells and kitty ~1.4 ms — 5.2 µs versus 1 µs per cell.
- After P34 (2026-10-31) the default became 12 points and the 980x640 window
  became 75×22; `font_family`, `font_size` and `window_padding_width` change the
  cell. The numbers above are not a re-measurement of the new default: to compare,
  `font_size 13` in the config and font/size/padding recorded in the protocol.
- The old kitty number (275.9 fps / 15.8 MB/s, grid 68×19) is from another
  condition of this machine (low CPU) and does not compare: the same version does
  2.5x more today just with turbo. Re-measure both in the same session, with the
  same window and the frequency recorded.
- The effective frequency decides the number: the same code gave 107–121 fps with
  turbo at 4.3 GHz and 59–64 fps with the CPU at ~1.5 GHz (`draw` of 8.5 ms versus
  22 ms); with `powersave` the measurements gave 3–5x less than `schedutil`. The
  control through the isolated generator is in "Resolved anomaly".
- fps depends on the grid (bigger cell = fewer frames with the same throughput);
  MB/s is the number that compares. With 300 frames the window grows in the middle
  of the count and the fps comes out 10–20% higher, hence the 1200 of the protocol.
- The 6.1–6.9 MB/s are above the 0.7–1.9 MiB/s of "parse + grid" in the README
  because here drawing is on (off, the same fire gives 10.8–11.1 MB/s):
  the README measures uniform dump, here the screen changes color in every cell.
- This number is the after of P9 (drawing through Pango), of the font in points and
  of bug 13: the drawing went from 12.8 to 22.7 ms per frame and the throughput
  fell from 0.6 to 0.5 MB/s. Part is shaping and font fallback, part is glyph
  size — until bug 13 the text was drawn at 96 dpi (10×22 px glyph) with the grid
  at 130 dpi, that is, measurements before 2026-10-25 painted fewer pixels per
  cell. Compare fps from here on.

### Where the time goes

- `PYTERM_PROF=1`, 1200 frames at 70×21, 113.5 fps / 6.5 MB/s: parse 44% and
  drawing 34% (the rest is the generator waiting). With the CPU low the order
  inverts (drawing 49%, parse 25%): drawing is more sensitive to frequency than
  parse.
- Drawing runs ~40x/s and the whole fire at ~110 frames/s: drawing is coalesced to
  ~22–40 draws/s (ceiling of one every 16 ms), and drawing less is what lets the
  parse breathe.
- Drawing costs by the number of color runs, not of cells: 37 shades per line make
  almost every cell its own run. With turbo, ~5 µs per cell (7.9 ms per frame of
  1470 cells) versus ~1 µs in the uniform case (~1.45 ms per 1470
  cells, drawing of `seq`, 445 draws). Measuring drawing with a single-color screen
  underestimates the worst case by ~5x (it was 15x with the CPU low).

## Drawing decomposition (2026-10-27)

- Measured in `_on_draw` with temporary instrumentation per section
  (`perf_counter` around each stretch of the loop; it did not stay in the code),
  doom-fire of 600 frames at 70×21, grid pinned with `PYTERM_GEOM`, turbo at
  4.29 GHz.
- Columns before and after P24/P25 (color as cached float,
  `show_layout_line`), same methodology and same CPU: "before" is a historical
  reference, "after" is what the code does today.

| `_on_draw` step | before µs/run | after µs/run | % today |
|---|---|---|---|
| grouping a run (`while j` comparing fg/bg/flags/selection) | 0.27 | 0.26 | 5% |
| color: 2× `cell_rgb` (lookup + 6 divisions → float cache) | 0.69 | 0.37 | 6% |
| state + background: 2× `set_source_rgb` + `rectangle` + `fill` | 2.32 (0.99+1.33) | 1.56 | 27% |
| text: `"".join` of the run + `dict.get` of the layout cache | 1.00 | 0.93 | 16% |
| `cr.move_to` + `show_layout` → `show_layout_line` | 2.83 | 2.44 | 43% |
| sum of the sections | 7.11 | 5.71 | 5.0 µs/cell |
| `draw` without instrumentation | 7.76 ms | 6.54 ms (-16%) | |

- The rest of the draw (metrics, the `cr.paint()` that clears, cursor, sub-cell)
  stays at ~0.6 ms, and the net gain is +4.8% fps (110.7 → 116.0): drawing is
  ~34% of the time, so cutting 16% of it yields ~5% in throughput.
- That is ~1323 runs per draw for 1470 cells (1.13 cell/run): the fire changes the
  color of almost every cell, so grouping has nothing to gather (the grouping loop
  is only 4%). Almost every run paints background (`bgpaint` = 99.99% of runs).
- Instrumentation is expensive here: 6 `perf_counter` per run inflate the draw
  from 8.1 to ~9.5 ms (17%) and fps falls from ~110 to ~100. That is why the
  `ms/draw` above is larger than the one from `PYTERM_PROF`: with instrumentation
  compare proportions, never the total.
- The same decomposition with the CPU at ~1.5 GHz (the first measurement, 500
  frames, 59.8 fps): 18.5 µs/run and 23.3 ms/draw, same proportions
  (`show_layout` 41%, color+background 37%, text 12%, grouping 9.6%). Turbo reduces
  everything by ~2.6x and does not change the order of attack.
- Where to attack: (1) Pango, 40% — the layout already comes from the
  `(text, bold)` cache, so the cost is `show_layout` emitting ~1 glyph per run;
  measure `cr.show_glyphs`/`cr.show_text` against it before touching it;
  (2) background + state, 33% — 4 context calls per run; caching the color (float
  tuple per palette index avoids 12 divisions per run) helps, but the
  `rectangle`+`fill` pair per cell is intrinsic to per-cell color.
- Method pitfall: `cProfile` inflates whoever makes many Python calls. `join`
  showed up with 21% in the profile and 12% in the real measurement, and the app
  fell from 59.8 to 5.6 fps. The mechanism (it does not see `gi.FunctionInfo`) is
  in [DEBUG.md](DEBUG.md).

## Alternating background and glyph costs the frame (2026-11-01)

- Measured with the socket's `prof` verb and `tools/benchrun.py`, doom-fire at
  61x18 on the real display, suppressing one stretch of `_on_draw` at a time
  (temporary patch, it did not stay in the code):

| loop variant | draw |
|---|---|
| full (fill + glyph per run, alternating) | 13.03 ms |
| without the background `cr.paint()` | 12.97 ms |
| without the background `fill`s | 3.03 ms |
| without `show_layout_line` | 2.61 ms |
| without both | 2.88 ms |

- The two sides do not add up: removing either one drops the cost to ~2.7
  ms, so what is expensive is the **alternation** (X changes state per operation),
  not the sum of the operations. Grouping solves it: two passes per frame (all
  backgrounds, then all text) take the same frame from 13.0 to 7.9 ms.
- Real cost outside the worst case: 18 lines of text with 8 colors and default
  background cost ~0.93 ms per full frame; one character changed on a line costs
  0.81 ms.
- `cProfile` lied again: it pointed `cell_rgb_f` (368 thousand calls) as a big
  target, and pruning that yielded 2% — the pitfall of the "Where the time goes"
  section holds for any count of small calls.

## The ladder: IO, parse and drawing (2026-10-26)

- `PYTERM_NODRAW=1` turns drawing off (`request_draw` becomes a no-op) and
  `PYTERM_NOPARSE=1` reads the pty and discards the bytes (no decode, no parse, no
  grid).
- Same load, 300 frames, one line per step, grid pinned by
  `PYTERM_GEOM=980x640`. The `schedutil` lines are from 2026-10-27; the P20 ones
  were measured with `powersave` (old fps in parentheses where it exists).

| step on | fps | MB/s | where the time goes |
|---|---|---|---|
| pure generation, outside the terminal (80×24) | 756–771 | 55 | it is the generator ceiling (turbo) |
| pty read only (NOPARSE+NODRAW) | 629–635 | 35 | IO is not the limit (turbo) |
| read + parse → grid (NODRAW), before P20 | 17.2 | 1.0 | powersave; pty 4.17 ms/read = 99% |
| read + parse → grid (NODRAW), after P20 | 192–198 | 11 | turbo; pty 0.27 ms/read (low CPU: 156 / 8.8) |
| + drawing (normal), before P20 | 8.2 | 0.5 | powersave; parse 48% + drawing 52% |
| + drawing (normal), today | 110–123 | 6.2–6.9 | turbo; parse 45% + drawing 31% (low CPU: 60 / 3.4) |

- Different benches do not compare: the same NOPARSE gave 14 MB/s with
  `powersave`, 25–33 with `schedutil` on low CPU and 41 with turbo.

Cost of the step that came in:

- pty read is nearly free (448–582 fps against 742 of the pure generator): IO costs
  some 25–40% of the generator time and is not the limit.
- parse costs ~3.5x. With 38 bytes of escape per cell it is the most expensive
  block of the input after drawing — but it was already 14x before P20.
- drawing costs ~2.5x: with the fast parser, it became the biggest slice (49% of
  the prof).
- The ceiling measured today, with this load, is 8.5 MB/s; the README number is
  from another bench (see "The number").

### pty buffering (why the number is valid)

- The test measures the minimum between what the child produces and what the
  emulator consumes, and that was verified, not assumed.
- The master is non-blocking (`os.set_blocking(fd, False)` at spawn): `os.read`
  raises `BlockingIOError` instead of freezing the UI; `PYTERM_PROF=1` counts
  `eagain` and bytes.
- Bytes read == bytes written: 16.82 MB against 16.8 MB in both modes
  (read-only and with parse). No byte is left in the kernel buffer.
- `eagain 0` in every round, including 5 s of idle pty (`sleep 5`), when
  `on_pty` is not called a single time: the watch is level-triggered and only
  fires with data. There is no spin nor exception per second.
- The pty buffer (kernel, tens of KB) is transitory and is what gives
  backpressure: with the slow parser the child waits, so 1.0 MB/s is the emulator
  rate, not the buffer's. Average read of ~4 KB is not accumulation: it is the
  watch firing as soon as anything arrives.

## Parse decomposition (why 35 µs/cell)

- Real doomfire frame (70×21, 34 B/cell: 2 truecolor SGR of 19 B + `▀`),
  fed straight into `Term`, without GTK, best of 300 rounds — same order as the
  end-to-end measurement (38.8 µs/cell).

| step | where | µs/cell |
|---|---|---|
| `decoder.decode` incremental UTF-8 | view.py:242 | 0.11 |
| `for ch in text` + state machine (ground) | term.py `feed` | 0.15 |
| `put`: `grid[cy][cx] = [ch, fg, bg, flags]`, autowrap, charset | term.py `put` | 0.97 |
| accumulating CSI char by char (`self.csi += ch`) | term.py (csi state) | ~2.9 per 19 B escape |
| closing the CSI: intermediate strip, `?<>=` prefix, `split(';')`, `strip()`, `int()` per token, `parts` + `nums` lists | term.py `feed` | ~5 per escape (`split`+`int` = 2.66) |
| `sgr`: `flatten` of subparameters (`isinstance`), loop, set fg/bg/flags | term.py `sgr` | ~8 per escape |
| `newline`/`scroll_up`: `pop(0)`+`append`+`blank_row`+`sb_wrapped` | term.py | 14 µs/line (0.2 per cell) |
| total | | 35.0 |

- truecolor SGR is 91% of the parse (32 of 35). `put` and the character loop add up
  to 1.1; UTF-8 decode 0.11 (0.3%).
- Escape is not free even without color: an 8 B `CSI 10;10 H` costs 8 µs, or ~1 µs
  per escape byte against ~15 ns per plain text byte.
- The bottleneck is not iterating characters, it is the fixed cost of closing and
  interpreting each CSI.

## Optimization options (prototyped, µs/cell on the same frame)

| option | how | µs/cell | gain |
|---|---|---|---|
| current (before P20) | char by char, `csi` string, `split`+`int`, `sgr` | 35.0 | — |
| B | `find("\x1b")` + manual split, text runs by slice | 10.05 | 3.5x |
| A | regex `\x1b\[(3\|4)8;2;r;g;bm` + runs by slice | 6.83 | 5.1x |
| C (done in P20) | `find` + end by `find("m")` + escape→color cache | 5.49 measured in the app | 5.8x |

- Prototypes measure only the happy path (simple wrap, no reflow/charset/other
  CSI). Option C went into the code in P20: 32.0 → 5.49 µs/cell = 5.8x (plain text
  0.99 → 0.21 = 4.7x), with the slow parser as fallback for everything that is not
  text or truecolor SGR.
- Why C wins: `regex.search` costs ~1.1 µs per escape and `int()`+`groups()`
  ~2.2; in doomfire there are only 37 shades, so `dict[escape] → (r,g,b)` (~0.05 µs)
  kills both.

Order of attack, from what yields the most:

- SGR/CUP fast path (option C): done in P20, 5.8x.
- Text by runs, not by char: done together in P20 (0.99 → 0.21 µs/cell in the
  uniform dump). What remains is a dump of plain text with other C0 in the middle.
- `csi_dispatch` in one pass: no `parts`+`nums`, no `strip()` when there is no
  intermediate, `params` straight into `sgr` when there is no tuple. Now this only
  affects escape outside the pattern (cache miss); small and cheap gain.
- `deque` in the scrollback: discarded by measurement in P21 — `pop(0)` does not
  show up (13.64 / 13.81 / 13.69 µs with 0 / 500 / 1000 lines). The cost was the
  blank line (11.5 of the 13.7 µs, 70 cell lists), solved in P21 with a shared
  cell: 13.7 → 3.27 µs/line and 38.4 → 10.9 µs/line in the scroll of 20,000
  lines.
- Does not help: UTF-8 decode (0.11), isolated `put` (0.97).
- Priority caveat: with drawing at 22.7–98 ms/frame, optimizing the parse only
  shows in throughput when drawing also falls; after P20 drawing is 71–87% of the
  time.

## Real load: `dmesg` (2026-10-26)

- The case that motivated P20: `Term` fed with the system `dmesg` (1,319 lines),
  100×40, without GTK.

| payload | old | P20+P21 | with P22 |
|---|---|---|---|
| `dmesg` without color (99.7 KB, 0 escapes) | 164.1 ms | 45.3 ms | 42.6 ms |
| `dmesg --color=always` (122.9 KB, 5172 escapes) | 188.5 ms | 82.2 ms | 78.6 ms |

- Per read of ~4 KB: 7.01 → 1.90 ms (without color).
- Since the parse runs on the GTK thread, this is what freezes the UI when dumping
  the log: the perceived "quick pause" was ~165 ms before and ~43 ms after.
- P22 (CSI parameter cache) takes the color case from 2.0x to 2.4x: the `dmesg`
  SGRs (`1`, `4`, `31`, `0`) are not truecolor and only became cheap when the whole
  CSI started being resolved by the cache, instead of falling into the slow parser
  (HISTORY, P22).

### Resolved anomaly (2026-10-27): it was the governor

- Drawing did not reproduce the 22.7 ms/frame: it gave 47.7 ms in 60 frames, 97.8
  in 300 and 105.1 in 400, always with identical metrics (socket `state`: advance 14.0,
  cell 14×28, res 130, 70 columns).
- Switching `powersave` → `schedutil` gave back 22.12 / 21.70 / 20.97 / 22.18 ms
  in four shots in a row, with throughput going from 10.4 to 59–64 fps.
- `powersave` pinned the CPU at ~1.4 GHz under sustained load; the isolated
  generator fell from 744 to 256 fps in the same switch, which closes the account.
- Measured nuance: drawing of uniform text does not change with the governor
  (1.41 ms with `powersave`, 1.45 ms with `schedutil`, 443–445 draws) — what
  collapses is the expensive path, of ~2000 color runs per frame.
- It was not power: battery and mains gave 10.52 and 10.89 ms in the scroll, within
  the noise.
- Rule: record the governor, compare only within the same governor, distrust
  drawing outside the ~20–22 ms/frame range in this load, and include one shot of
  the isolated generator as control.

```
PYTERM_NOPARSE=1 PYTERM_NODRAW=1 PYTERM_PROF=1 ./run.sh --cmd 'python3 \
    tools/doomfire.py --fps 0 --frames 300 --stats-to /tmp/df.txt'
# prof: draw 1x 3.4ms/call | pty 2134x 0.06ms/call (137ms)
```

## tortty-python profile

- The `PYTERM_*` probes are in [DEBUG.md](DEBUG.md); here only what they produce
  as a number.
- `PYTERM_PROF=1` turns on counters in `TermView` (`tortty_python/view.py`): time and
  number of calls of `on_pty` (parse) and `on_draw` (drawing), on stderr (soon, in
  the `/tmp/tortty-python.log` of `debug.sh`) when the session closes. Without the variable
  the code does nothing (only the `if not _PROF` at the entry).

```
PYTERM_PROF=1 ./debug.sh --cmd 'python3 tools/doomfire.py --fps 0 \
    --frames 300 --stats-to /tmp/df.txt'
grep prof: /tmp/tortty-python.log
# prof: draw 821x 22.67ms/call (18610ms) | pty 4102x 4.22ms/call (17314ms)
```

## Footprint: memory and disk (2026-10-28)

- Weight, not throughput: what it costs to have this installed and running.
  Measured on the very GTK desktop where it runs, with the system `gi`/cairo.
- App running, one session: total PSS ~17 MB, of which ~2 MB are the
  gtk/pango/cairo/freetype/python stack — the rest is page shared with the desktop,
  which already had it loaded.
- Installing the stack where it does not exist (GTK3 + Pango + cairo closure on
  Debian): 210 packages, 346 MB on disk, dominated by fonts (`fonts-noto-core`
  42 MB) and ICU (`libicu74` 36 MB). On a GTK machine this cost is zero, because
  the desktop already paid it.
- Qt route, for comparison (P30, in [PORTABILITY.md](PORTABILITY.md)): PySide6 244 MB
  installed, trivial app with PSS of 50 MB, of which 23 MB are Qt libs. On
  Windows/macOS it is the same order of magnitude of bringing GTK there; on Linux
  GTK wins by construction.
- PyGObject never comes from a wheel: PyPI publishes only sdist (3.58.1), so
  `pip install pygobject` means compiling against headers. It is the fact that makes
  the installer depend on the distro package manager, and not on pip.
- The package metadata makes no performance claim (no "light", no "fast"):
  light is true for footprint and false for throughput. Decision in
  [LIMITATIONS.md](LIMITATIONS.md).

## Protocol (to compare two terminals)

1. One at a time: two terminals drawing at the same time dispute CPU and both
   numbers come out worse.
2. Same columns and same lines in both. In tortty-python, `PYTERM_GEOM=980x640` (without
   that the WM sometimes opens 80×24 and the number changes); in kitty, ask for the
   same pixel size, since font and DPI are the same:

```
kitty --override remember_window_size=no --override initial_window_width=980 \
    --override initial_window_height=640 -e ...
```

- The tortty-python default window is 980×640, which gives 70×21 with one workspace and
  57×21 with two: opening or closing the sidebar changes the grid and the fps, so
  compare with the same number of workspaces.
3. `--fps 0 --frames 1200 --stats-to FILE` in both.
4. Compare fps and MB/s (the bytes/frame varies a bit with the escape size).

## How to know it is drawing

- The dump brings `▀` on every line of the viewport (1470 cells at 70×21): proof
  that the parser receives, not that the screen changes. What proves it is two
  captures ~1.5 s apart:

```
import -window $(python3 tools/xtest.py id) /tmp/a.png; sleep 2
import -window $(python3 tools/xtest.py id) /tmp/b.png
# compare the areas: 0 different pixels = frozen screen
```

- That is how bug 12 was found (three identical captures with 0.3 MB/s running).

## Pitfalls

- A tool or session pitfall (stuck pointer, dump that shows the live grid, finding
  the window) lives in [DEBUG.md](DEBUG.md); the measurement ones stay here.
- The first measurement was invalid: 24.6 fps / 1.0 MB/s with the screen frozen by
  a GLib priority bug (bug 12 of HISTORY), so it was measuring only parse.
  A throughput number only means something after checking that the screen changes.
- Font without `▀`: the cell still has bg and fg, so the fire shows up as color
  bands even without the glyph; if not even the bands appear, the problem is not
  the glyph.
- `render` does not emit `\r\n`: each line comes out with exactly `cols` half-cells
  and the break is soft (autowrap), the emulator decides the next line. Diagonal
  grid = wrong break — that is how the P15 bug was seen (control after a full line
  advancing two lines).
- SGR on output: without `\033[0m` the statistics inherit the last color of the fire
  (text with yellow background). Already fixed in the tool.
- SIGTERM in the middle: without a handler the screen stays in alt-screen. Already
  fixed (`finally` restores pen, cursor and screen).
- Measuring with `--fps 30` and thinking it is the throughput: with a fixed pace the
  tool sleeps, and the measured fps is the target, not the terminal limit.
- tortty-python window is not the grid: the sidebar `size_request` and the tab bar eat
  width; the grid is what the dump says (`=== viewport CxR ===`).

## What it is for

- The load exists to measure change in the hot path: run before and after, on the
  same grid, and compare with the baseline above. That is how P9 (drawing through
  Pango) was evaluated: 12.8 → 15.4 ms per frame, 30.5 without layout cache.
- Numbers before bug 13 enter only among themselves, never against the table above
  (the why is in "The number").
- The live number of the table changes when the drawing changes; the before/after
  stays in HISTORY.
