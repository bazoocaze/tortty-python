# TorTTY-Python — history

Concise history of past activities. Maximum of 5 lines per activity.

### P1 — Mouse (report to apps + selection/copy) — **done**

`?1000`/`?1002`/`?1003`, `?1006` (SGR), `?1004` (focus) in `core/mouse.py` (pure).
Outside the mouse modes the window selects by dragging: `Ctrl+Shift+C` copies,
middle pastes PRIMARY — `Ctrl+Shift+C/V` intercepted before the keyboard, else
they became `^C` and killed the process. Bug: inversion ran on color indices and
the `256`/`257` sentinels turned black/red — RGB first, invert after. XTest.

### P2 — Scrollback screen (scroll the history) + scroll with the mouse — **done**

`Term.visible_rows(off)` windows `rows` lines over scrollback + grid; the draw,
the copy and the dump use it. `Shift+PgUp/PgDn/Home/End` + wheel (3/notch), back
to live on typing, click or output; with an app in mouse mode the wheel reports
but inside the scrollback it scrolls the view (or the app would steal it). Bug:
pressing Shift reset it — a pure modifier does not leave (`keys.is_modifier`).

### P3 — Reflow on resize — **done**

`row_wrapped`/`sb_wrapped` mark soft wraps; `_reflow(cols, rows)` rebuilds the logical
lines of scrollback + grid at the new width, restores the cursor by offset inside the
line and splits the result (widening pulls back); alt-screen stays on cropping. Bug:
trailing whitespace must be cut, or narrowing interleaves content with empty lines; only
the first chunk holding the offset sets the cursor. `--selftest`: 1→4 and 4→1.

### P4 — Real truecolor — **done**

Truecolor is an int flagged in bit 24 (`TC | r<<16 | g<<8 | b`) — no color table,
no dict per cell, same footprint as an index. SGR `38;2`/`48;2` with `;` and with
the `:` forms; the parser keeps the group as a tuple and `sgr()` flattens it.
Verified in `--selftest` and pixel by pixel with `vim termguicolors` (`#123456` →
(18,52,86) exact). Out of scope: `58;2` — no colored underline is drawn.

### P5 — Kitty keyboard protocol — **done**

`core/kitty_kbd.py` (pure) + state in `Term`; push/pop/query of flags, encoding
mirrored on kitty's `encode_key`: disambiguate (1), event types (2, listening to
`key-release-event`), all-keys (8), associated text (16), legacy path outside.
From the reference: modifier = `1 + shift + 2*alt + 4*ctrl + 8*super`, F3 is
`CSI 13~`. Out of scope: flag 4, repeat (Gdk repeats as press), keypad. By child.

### P6 — Graphics protocol (kitty) — **done**

`graphics.py` pure + APC `ESC _ G` in the parser; the actions and formats `icat`
uses, including `o=zlib` and `X=`/`Y=`. The placement stores the GRID line (may
go into the scrollback; the drawing adds `view_off`); following the reflow was
discarded (LIMITATIONS). Bugs: `a=q` is a capability handshake, `m=1` cannot
accumulate, `CSI * x` needed intermediates 0x20–0x2f. Verified with `kitten icat`.

### P7 — Bracketed paste — **done**

`?2004` → `Term.paste_payload()`: brackets the text with the mode on, raw
otherwise — the pty always receives TEXT, never a sequence. Bug behind the
"Enter on paste": `copy()` added `\n` always; the kitty rule joins only BETWEEN
lines, and the `+=` went out. Verified in `--selftest` and with a child dumping
bytes: copying "echo a" does not execute. Not kitty's `strip_trailing_newlines`.

### P8 — Close the window when the shell ends — **done**

The trigger is `waitpid` via `GLib.child_watch_add`, not the pty EOF — on Linux
the master gives EIO, which the old code swallowed and `Ctrl+D` left the window
open. Drain the pty before closing (64 reads cap), non-zero exit to stderr,
`killpg(SIGHUP)` on close. Gotcha: disposition is inherited — the fork child
restores SIGHUP/SIGPIPE/SIGINT/SIGQUIT/SIGTERM to `SIG_DFL`. Verified by hand.

### P9 — Ligatures and shaping — **done**

From `cairo.show_text` (no shaping) to Pango: one `Layout` per run, cache by
`(text, bold)` cap 800 — without it the drawing doubles (doom-fire 12.8 → 30.5
ms/frame, 15.2 with cache). Amendment: `font_size` is in POINTS — with
`Xft.dpi: 130` that is why kitty's 13 looked bigger than our 16; the same window
gives the same grid (70×21). Metric from the widget's context ([DEBUG.md](DEBUG.md)).

### P10 — Font fallback (emoji/CJK) — **done**

Came with P9: fontconfig finds the font with the glyph, so CJK and color emoji
draw with no extra code. Verified with `printf '\u4e2d\u6587 \U0001F600'`. Limit
that stays: the grid has no `wcwidth` — a wide char takes one squeezed cell and
apps counting double columns come out misaligned; fixing it touches the cell
model (LIMITATIONS.md).

### P11 — Tabs — **done**

`Ctrl+Shift+T` opens, `Alt+1..9` selects, `Ctrl+Shift+W` closes, last tab closes
the window. Structural: `TermView` extracted with the session state; the window
keeps the notebook and the global shortcuts (`Alt+N` there, else the child gets
the key); the label is the OSC title or the cwd (`/proc`); `child_watch_add`
closes the tab. Four GTK pitfalls in [DEBUG.md](DEBUG.md). XTest, not `--selftest`.

### P12 — Workspaces — **done**

`Gtk.Stack` with one `Gtk.Notebook` per page (each workspace keeps its own
selected tab); sidebar card 170 px, shown with 2+; `Ctrl+Shift+1..9`/`N`/`Q`,
middle click closes, double renames. `Ctrl+N` discarded on purpose (`C-n` is
readline/emacs next line — do not "fix" it later). A hidden page gets no
`size-allocate`: switching must force the recalculation. XTest + `xprop`, no check.

### P13 — Interface style system — **done**

`style.py` is the only source of chrome color: tokens, `css()` built from them,
`contrast()` in relative sRGB (WCAG) — pure, so `style_contrast` requires
≥ 4.5:1 on the four text/background pairs and checks the CSS uses the tokens.
Verified with capture + `tools/pixel.py`: black sidebar/cards, dark green active,
white name (15.9:1 on the day), light green second line (6.1:1).

### P14 — Sidebar width does not stay fixed — **done**

`set_size_request` is a minimum, not a width: the labels published their text
width (234 px sidebar; 1062 px window and 121 columns with a long title). The
recipe: `ellipsize(END)` + `max_width_chars(1)` + `single_line_mode` +
`pack_start(..., fill)`; tab label the same with `TAB_TITLE_CHARS = 20`, full
text to the tooltip. Measured: grid stopped oscillating 73↔121 — constant 51/680.

### P15 — `pi` screen stabilized messy — **done**

The `\r\n` of a line filling the width advanced TWO lines: `put()` ran the
pending wrap BEFORE `\r`/`\n`/`\b`/`\t`, so the LF paid both. Fix: control first,
wrap after (check `wrap_and_control`). What closed it: `PYTERM_RAWLOG` replayed
without display — grid vs `pyte` went from 38/45 different lines to 0. False
leads kept: `CSI 16t`/`OSC 10/11/4` answers were not it; running both at once.

### P16 — Doom fire as measurement load — **done**

`tools/doomfire.py`: truecolor half-block fire (fg+bg per cell, nothing groups)
— worst case for parser and drawing; `--fps 0` makes whoever limits be the
terminal. Day-1 record (68×20, cairo): tortty 11.8 fps / 0.6 MB/s vs kitty 314.2
/ 15.9 — live in [BENCHMARKS.md](BENCHMARKS.md). `PYTERM_PROF`: parse 61%,
drawing 37% (per color RUN, ~11 µs vs ~1 µs). First fps (24.6) was invalid (bug 12).

### P17 — Sidebar shows up with a single workspace — **done**

The window's `show_all()` showed the sidebar hidden with one workspace (grid 68
→ 51 columns). Fix: `sidebar.set_no_show_all(True)` — only our
`set_visible(len > 1)` commands it. Verified per pixel and by the dump
(`68x20` with one workspace, `51x20` with two).

### P18 — Doubled keys inside `pi` — **done**

Inside `pi` every key arrived twice: it enables kitty flags `>7u` including 2
(event types), so releases arrive, and `kitty_kbd.encode` returned `None` ("use
legacy") for plain text and unmodified arrows — the release resent the byte.
Rule in one place now: flag 2 + release → kitty sequence or `""`, never `None`
(legacy repeat stays: repetition IS a press). `kitty_keyboard`; live `abcabc`.

### P20 — Escape fast path in the parser — **done**

The bottleneck was closing each escape (91% of 35 µs/cell). `feed` gained a
ground fast path: printable block in one `slice` + `CSI 38;2;r;g;b m` resolved by
`dict[escape] -> color`; the slow parser keeps all other states. Differential
vs the previous parser (14 entries) — 0 divergences. Day: micro 32.0 → 5.49
µs/cell (5.8x), NODRAW 17.2 → 85 fps, `dmesg` 168.3 → 45.7 ms; 4-bit → P22.

### P21 — Shared blank line in the scroll — **done**

Hypothesis wrong and recorded: the `scrollback.pop(0)` does not show up (13.64 /
13.81 / 13.69 µs at cap 0/500/1000) — the cost was `_blank_row()` allocating 70
cell lists (11.5 of 13.7 µs). Fix: module-level `_BLANK_CELL` shared, safe
because nothing mutates a cell in place (writing replaces); the check asserts two
blanks are the same object. Day: scroll 13.7 → 3.27 µs/line (4.2x), cat 3.5x.

### P22 — Cache of CSI parameters — **done**

P20 only sped up truecolor; ordinary colored `dmesg` escapes still paid the slow
parser. Fix: `_csi_parse(body, final)` with a module cache cap 1024, fed by a
regex matching the whole CSI; `csi_dispatch` now takes a tuple (cache-safe) and
`sgr` allocates `flat` only with `:`. Discarded: char indexing cut 5% on `dmesg`
but cost 18% on doom-fire. Day: `dmesg` 164.1 → 42.6 ms (3.8x), color 2.4x; 0 div.

### P23 — Workspace shortcuts with `Super` (2026-10-27)

`Super` as alias of `Ctrl+Shift+N/1..9/Q` (`handle_shortcut` reads `SUPER_MASK`,
digit via `_digit_of` so ABNT2 works). Bug: `select_workspace_index` returning
False fell through to the encoder, and `Super+2` arrives as plain text — the
digit was TYPED INTO THE SHELL; now a workspace digit is consumed even with no
workspace at that index (same for `Ctrl+Shift+9`). By hand; README: WM grabs it.

### P24/P25 — Drawing: float color and `show_layout_line` (2026-10-27)

Drawing was 34% of the time, with 4 context calls and 2 color conversions per run
in ~1323 runs per draw. Color comes cached as float (`cell_rgb_f`) and
`set_source_rgb` is skipped by tuple identity; the cache stores the line and draws
with `show_layout_line` (-17%). Grid pixel-identical vs HEAD (0 cells). Day:
`draw` 7.76 → 6.54 ms (-16%), 110.7 → 116.0 fps (+4.8%, as 34% predicts).

### P31 — Installable package: `pipx install` straight from GitHub (2026-10-28)

`bzmux.py`/`core/` became the installable `tortty_python/` package:
`[project.scripts]` with an argument-less entry (`cli.run` — `console_scripts`
calls without argv), `__main__.py`, `gi` guard on only `ModuleNotFoundError`.
`uv build` did NOT fail on the missing config — legacy setuptools shipped a wheel
with `top_level = core` and no script: acceptance = INSPECTING the wheel. `git+…` = the commit.

### P28 — Mouse selection: 1-char click and anchor in the scroll (2026-10-29)

Both symptoms were screen coordinates: a 1-char click overwrote the PRIMARY
selection, and scrolling left the highlight over other text. Fix (option B): the
selection is born on the DRAG (`DRAG_SLOP = 3` px — Gtk delivers motion on any
tiny shake; the user found the missing slack by hand) and any change of
`view_off` undoes it. Option B was later undone by bug 17. Manual; text in checks.

### P29 — `Alt` did not prefix `ESC` on special keys (2026-10-29)

`Alt+Backspace` deleted 1 char: the `kv in SIMPLE` branch of `encode_key`
ignored `alt` — the ESC prefix existed only for printables. Generic fix in xterm
format: control keys get ESC with Alt (`\x1b\x7f`), CSI/SS3 keys take
`_mod_param` = 1+shift+2*alt+4*ctrl (`\e[1;3A`, `\e[3;3~`), `Ctrl+Alt+letter` =
ESC + control char, `Shift+Tab` keeps `\e[Z`. 16 cases vs xterm, checked by hand.

### P19 — `pi` "rewrote several screens" during the turn (2026-10-29)

Not the parser: three real turns replayed in `Term` and `pyte` came out
identical. The stream (12 MB in `~/dados/temp/p19-evidence-2026-10-29/`) has
~10 thousand repaints each inside a `?2026` transaction and 99% of the reads fall
mid-transaction — with `?2026` ignored, every drawing caught the screen
half-repainted. Done: `?2026` honored (draw at close, 200 ms cap) + DA2/DECRQM fixed; mid-draw 91 → 0.

### P32 — The scrollback did not hold whoever was reading (2026-10-29)

Reading the scrollback, `pi`'s 1 Hz tick yanked the view to the footer: `on_pty`
returned to live on "any output changing the visible screen" (born in bug 14) and
its `_view_signature()` rebuilt all visible cells on every chunk. Fix: absolute
anchor (`Term.anchored_view_off` = distance to the end); the user leaves only by
his own action (scroll to end, real key, `CSI 3J`). Check `scroll_anchor`.

### P34 — Configuration v2: the eight common options (2026-10-31)

The keys: `font_family`, `font_size` (points), `cursor_shape`, `cursor_blink`
(530 ms timer, only the cursor cell of the visible view — N tabs, 1 timer),
`scrollback`, `window_padding_width`, `bell` (was ignored), `copy_on_select`;
`DECSCUSR` wins while it lasts. Error per line: the load applies what validated and
toasts the first `(+N)`; reload all-or-nothing. Toast: pill, 3 shades, 3/10 s, from a mock.

### P35 — Introspection socket for the agent (2026-11-01)

`--debug-socket FILE`: Unix socket, line-based JSON, served on the UI thread
(`io_add_watch`, no thread); `auto` = `$XDG_RUNTIME_DIR/tortty-python-<pid>.sock`,
0600 + `SO_PEERCRED`, orphan removed at boot, security toast with the path.
Verbs: `state` (incl. `view_off`, `pin`, `sync`, `scrolled`), `text`
(view/screen/history), `write`, `log`, `quit`. Discarded TCP/HTTP; check with a fake target.

### P36 — Introspection socket: metrics, `prof`, `resize` and `keys` (2026-11-01)

Extension of P35: `state` gained the grid metrics (`advance`, `cell`, `dpi`,
`font` — replacing `PYTERM_DIAG`/`PYTERM_CONFLOG`), `prof` answers the accumulated
values at runtime, `resize COLSxROWS` resizes the window through the normal path
(allocation → `TIOCSWINSZ` → SIGWINCH, no WM needed), `keys` sends a key through
the app path with aliases (`PgUp`, `Esc`, `Enter`…). Private display; `parse_key`.

### P27 — Drawing: per-line damage instead of the full redraw (2026-11-01)

One character cost a full frame (13.5 ms in 61x18): `queue_draw()` swept
everything. The `Term` marks damage (`dirty`, `dirty_all`), `take_damage()`
answers lines or None; the view swaps in `queue_draw_area` of coalesced dirty
lines, the draw loop filters by `clip_extents`. Discarded: surface cache (5.6 vs
4.0 direct, server 42.6 — pixmap ~10x dearer). Spinner 13.5 → ~1.0 ms; check `draw_damage`.

### P37 — Drawing: cut Python work and group by operation type (2026-11-01)

Python pruning yielded ~2% (13.45 → 13.17 ms; cProfile's 25% was wrong — it
inflates per-call cost). What the measurement showed: the worst case is
alternating `fill` and glyph — backgrounds alone 13.03 → 3.03 ms, text alone →
2.61, together 2.9: the X state change per run costs. Done: TWO PASSES (all
backgrounds, then all text). Doom-fire 13.0 → 7.9 ms, text scene 1.05 → 0.93.

### P40 — SGR italic and underline styles (2026-11-08)

`3`/`23` (real italic face through Pango) and `4`/`4:n`/`21`/`24` (single,
double, curly, dotted, dashed): new `ITALIC` bit, style in three bits so run
grouping stays one comparison, underline drawn per run in cairo (`set_dash`);
Pango cache 2 → 4 slots. `4:n` kept as a tuple — flattening turned `4:3` into
`4;3` ("underline + italic"). Check `sgr_italic_and_underline_styles`.

### P41 — Double click picks the word, triple the logical line (2026-11-08)

`Term.word_span` stops at whitespace only (a whole path on double click),
`Term.logical_line_span` walks the soft-wrap flags up and down and trims the
trailing space; the pick already feeds PRIMARY and CLIPBOARD. Bug in a real
window: a double click behaved as a triple — `Clipboard.store()` runs a nested
X loop and the SAME press came back; a repeated press is discarded before counting.

### P42 — Scrollbar over the last column (2026-11-08)

8 px over the grid, only with scrollback, translucent track (10%) / thumb (55%)
so the text underneath still reads; click on the track jumps, drag walks the
history, the hit test comes before the mouse report (works inside `mc`/`vim`) and
it hides in alt-screen. Verified with the socket `state`: click `view_off` 0 → 28
(max), drag held 21 of 28 while the button was down.

### P43 — OSC 8 hyperlinks (2026-11-08)

`8;params;URI` with the URI interned: the cell carries an int in a lazy fifth
field existing only on linked cells (9.1/8.9 → 9.0/8.8 MB/s, noise). `Ctrl`
underlines every link on screen (pixel diff), `Ctrl+click` hands the URI to
`xdg-open` over the whitelist `http/https/file/ftp/mailto` (fake `xdg-open`
recorded it); `javascript:`/`data:` refused by check.

### P44 — Notifications `OSC 9` / `OSC 777` (2026-11-08)

The core only counts and keeps the text (`notifs`, `notif_text`, cap
`NOTIF_MAX`); the window decides: front tab = 8 s toast, background tab = badge
with NO timer (class `notif`) + `•` on the card + `set_urgency_hint`; visiting
acknowledges. `9;4` swallowed — a busy TUI repeats it at 1 Hz and would pin the
toast. Verified with a window: `notif_pending` 1 → 0 when the tab is visited.

### P45 — `ligatures` in the configuration (2026-11-08)

Key `ligatures` (`off`/`standard`/`all`, default `standard`) maps to a Pango
`font-features` attribute (`liga=0,calt=0` / `liga=1,calt=1` / `+dlig`); it goes
on the RUN, not the font description, so script shaping keeps working whatever
the value, and `apply_config` resets the layout cache (no restart). Verified:
`a -> b != c fi ffl` draws with `ligatures all`.

### P46 — Pixel mouse protocol (`?1016`) (2026-11-08)

`?1016` tracked as a mode (answered by `DECRQM`): the SGR shape with pixel
coordinates, and it decides the shape by itself — there is no legacy pixel
protocol to fall back to. `mouse.encode` gained `pixels=`, `report_mouse`
converts the event position minus the padding, and the cell path did not change.

### P47 — `OSC 7`: the shell's cwd (2026-11-08)

`file://host/path`, `%XX` decoded, control chars out; a payload outside the form
does not erase a known cwd, an empty one clears it. The view polls `term.cwd`
where it already polled the bell, so `cd` moves the tab label and the window
title; it is the fallback for `current_cwd` when `/proc` has no answer. Verified
with a window: `OSC 7` to `/tmp` made WM_NAME read `tmp`.

### P48 — Touchpad wheel and wheel over the tab bar/sidebar (2026-11-08)

`SCROLL_SMOOTH` arrived with `btn is None` and moved nothing — blocker 2 of
[PORTABILITY.md](PORTABILITY.md), which this closes. `mouse.Notches` accumulates
the travel until a detent completes, drops the remainder on direction change
(pure, in checks); a discrete detent resets the fraction. Wheel over the tab bar
cycles from the ACTIVE tab and wraps; over the sidebar, one card. XTest: 3→2→1→3.

### P49 — Configurable palette (2026-11-08)

19 keys with a `Theme` per `Term`: the config seeds the base, `OSC 4` redefines
an entry OF THAT TAB (0..15), `OSC 10/11/12` set fg/bg/cursor and
`104`/`110`–`112` go back to the configured value (the config IS the default
here). Bug of the day: the comment rule ate the value — a `#` that OPENS the value is
the value (Rust `value_of`). Float cache moved into the Theme; `palette_config` guards it.

### P50 — Session restore (2026-11-08)

`restore_state none|layout` (default): workspaces with names, tabs in order, cwd
of each shell and what was in front — the Rust `Layout` shape, same
`window.json`; `state.layout()` validates on load (junk dropped, indices clamped
— pure); `PYTERM_GEOM` keeps out both ways. Tool bug: `debug_keys` sent
`hardware_keycode = 0`, so `Alt+1..9` leaked into the pty — real keycode now.

### P51 — Render gate on Xvfb (2026-11-08)

`tools/render-check.sh`: 5 checks on an isolated Xvfb (window paints; `SGR 41/42`
paint color1/color2 in the cell; text lands where the grid says; still screen
identical; line `r` in band `r`) + `tools/pixel.py` grew the scripted interface
(`--expect`, `--find`, `--diff --max [--region]`). Traps: `PYTERM_GEOM` disables
session restore (the gate cannot inherit it); a toast can expire (grid-only check).

### P52 — Title stack (2026-11-08)

`CSI 22;Ps t` pushes the title, `23;Ps t` gives it back: cap of 16, an empty pop
leaves the title alone (no invention), `Ps > 2` (the icon form) does not touch
the stack — same rules as the Rust. Nothing changed in the view: it polls
`term.title` since P47, so label and window title follow the pop. Verified:
`TITULO-B` pushed over `TITULO-A`, pop restores `TITULO-A`.

### P53 — Real tab stops (2026-11-08)

`term.tabstops` (a bool per column, seeded every 8) replaces the hardcoded
`((cx // 8) + 1) * 8` in `HT`; `HTS` sets, `TBC` clears one/all, `CHT`/`CBT`
walk. The resize RE-SEEDS instead of preserving (as the Rust; preserving would
leave stops beyond the width) — my first version reseeded only in `_resize_crop`
and the check `tabstops[3] is False` caught it. Verified on a window.

### P54 — Strikethrough and overline (2026-11-08)

`SGR 9`/`29` and `53`/`55` are two new flag bits (`STRIKE`, `OVERLINE`), and the
run carries all decoration bits into a single `_deco` call: overline on the top
edge, strike at `y0 + round(h/2)`, underline by style. Verified by pixels: an
88 px band at half height, and the sixth check of `tools/render-check.sh` (added
here) fails if the line moves — proven by drawing it at `y0 + 1` (`4 < 68`).

### P55 — SU/SD and a real `RI` (2026-11-08)

`CSI S`/`CSI T` roll the region by `n` without touching the cursor, and `ESC M`
(RI) at the top of the region now scrolls the region DOWN instead of only moving
the cursor up — the gap was there before (the Rust `reverse_index` calls
`scroll_down`). `scroll_down` is new; `scroll_up` already existed.

### P56 — `REP`, `DECKPAM`/`DECKPNM` and `?66` (2026-11-08)

`REP` (`CSI b`) repeats the last printed character (`last_char`, set by `put`
and `_put_run`; space is the ECMA default before any). `ESC =`/`ESC >` flip a
single `keypad_app` bool, answered by `?66` in DECRQM — the key bytes do not
change (the Rust decision, written down). Verified: `=` + `CSI 5 b` printed six;
`CSI ?66 $p` answered `ESC[?66;1$y`.

### P33 — Configuration: parity with the Rust (2026-11-10)

Parity of the keys, read against `config.rs`: the embedded `.conf` is the source
and the in-code dict only the safety net (`DEFAULTS` → `FALLBACK`);
`defaults_parse_clean` became an assertion (zero errors, every key, same value);
`debug_log` empty = off, an empty COLOR = error. No `map` dialect invented (it is
`M-H` in the Rust, open there). Tuning: `scrollback` 1000. `restore_state content` → P57.

### P58 — `LNM` (2026-11-10)

`CSI 20 h`/`l` sets `term.lnm`: with it the parser's `\n` zeroes the column
before the line advance, so a program sending only `\n` stops drawing a
staircase; `DECRQM` answers `20;1$y`/`20;2$y`. Flag checked only on `\n`. Verified
with a child running `stty -onlcr` (without it the pty turns `\n` into `\r\n` and
the test proves nothing): `ab\nc` gives `ab`/`  c` off, `ab`/`c` on.

### P59 — `DECSTR` (2026-11-10)

`CSI ! p` (soft reset) resets the pen (`fg`, `bg`, `flags`), cursor visible,
`DECCKM`, keypad, the scroll region and the pending wrap — touching neither grid
nor history; the field list is the Rust `soft_reset` (`LNM` and `CSI 6 q` stay
out, as there). Verified by pixels: the cell written before keeps its colour
(`#00cd00`), the one after is the default (`#000000`).

### P60 — `F13`–`F24` (2026-11-10)

They are `F1`–`F12` with Shift on a PC keyboard, which is what xterm's terminfo
says (`kf13=\E[1;2P`): an explicit table (`F_KEY_SHIFT`) translates the keyval
and forces `shift`, and `_special` already built the modifier parameter. Verified
on a window with a `cat -v` child: `f13` arrives as `^[[1;2P`, the same bytes as
`shift+f12`, and `f12` stays `^[[24~`.

### P61 — Block selection (2026-11-10)

`Alt+drag` takes the same columns on every row (`view.sel_block`), copied one
line each by `Term.anchor_block_text` — a soft-wrapped row does not continue
into the next (the point of a block is the columns). The drawing needed a second
predicate: `_in_sel` constrains columns only on the first/last row, `_in_block`
on every row; `copy` and `selection_text` share the choice. 3×3 Alt+drag, `sel` verb.

### P62 — A dropped file becomes its path (2026-11-10)

`drag_dest_set` with URI targets on the window; the first URI's path goes to the
child through `Term.paste_payload`, so `?2004` brackets it. `shell_quoted` is the
Rust rule: pass through when every character is safe, else single quotes with
`'\''` inside. One function serves the XDND event and the socket's `drop` verb
(the Rust has the same). Verified: quoted paths through a real `sh`, drop on `cat -v`.

### P63 — `--cols` / `--rows` (2026-11-10)

They pin the grid: after `show_all` the window is sized from the live cell
metrics plus what sits outside the grid (tab bar, sidebar, padding) measured in
the allocation, so the first pass already lands on the exact grid. Like
`PYTERM_GEOM`, pinning means the session is neither restored nor saved. Verified
with `--cols 100 --rows 24`: `state` reported exactly `100x24`.

### P64 — Five small limits: DECAWM, SGR 2/8, OSC 52, two options (2026-11-10)

`CSI ?7 l` (DECAWM) stops the soft wrap (cursor stays on the last column, the
next character overwrites); `DECSTR` and DECRQM follow. `SGR 2` (faint) and
`SGR 8` (hidden: glyph out, background/decoration kept) joined the flags; `SGR 22`
clears bold+faint. `OSC 52` decodes base64 into the clipboard like the mouse
selection (query answers empty). Config: `bold_as_bright`, `letter_spacing`. Checks 49/6.

### P65 — `OSC 9;4` progress on the tab label + sidebar card text (2026-11-11)

`9;4;state[;%]` (mintty/ConEmu, 0..4) stopped being swallowed: `Term.progress =
(state, pct)` (clamped, bad shape still → `_notify`, 0 clears), delivered on the
`_on_pty` poll like `notifs`; the tab label gained a textual prefix (`50% · `,
`! · ` error, `… · ` no pct) — no color, no toast. Same card, realigned to Rust
`card_lines`: name `""`, no tab count, rename can clear. Checks 50/6.

### P66 — SGR 5/6 blink (cell blink) (2026-11-12)

`BLINK` (2048) on the pen: `5` and `6` share bit and rhythm (as in xterm), `25`
returns to not blinking, `0`/soft reset clear it. The view owns a lazy timer
(`CELL_BLINK_MS` 500): armed only when a draw sees a visible cell in the damage
area, disarmed by a full scan on the tick; off phase = SGR 8. Bug of the day:
without `dirty_all` the tick repainted only the cursor. Checks: `sgr_blink` (51), gate 7/7.

### P67 — Scrollbar hover (2026-11-12)

The strip answers the pointer: `_sb_hover_at` tests the same `scrollbar_rect` the
click uses, `_sb_hover_set` repaints only that strip (`queue_draw_area`), track
0.10 → 0.18 and thumb 0.55 → 0.75. `leave-notify-event` (a new event mask) clears
it — motion does not happen after the pointer leaves. Verified by pixels on Xvfb.

### P68 — Origin mode (`?6`) (2026-11-12)

DEC: with `origin` on, `CUP`/`HVP`/`VPA` are relative to the scroll region
(`row_abs`) and every address is clamped inside it (`cursor_to`); `?6 h`/`?6 l`
send the cursor home, `DECRQM` answers and `DECSTR` clears. Check `origin_mode`.

### P69 — Mouse `?1015` and `?1005` (2026-11-12)

Two encodings beside SGR/legacy: urxvt (`CSI b;x;yM`, the X10 button code in
decimal) and UTF-8 (`CSI M` + the code + x/y as code points, past the 223 limit).
Formats checked against kitty's `mouse.c`; SGR wins when both are on.
Check `mouse_urxvt_and_utf8`.

### P70 — `OSC 8` hover without `Ctrl` (2026-11-12)

The link under the pointer underlines on its own: `on_motion` resolves the URI
only when the cell changes, `_draw_links` filters to that URI unless `Ctrl` is
held (then all of them, as before). The `id=`/parameters stay discarded. Pixels.

### P71 — Context menu (2026-11-12)

Right click outside the app's mouse mode (terminal, tab, sidebar card) pops the
window's `Gtk.Menu` with the actions the shortcuts already have: copy, paste, new
and close tab, rename, new and close workspace. Verified on Xvfb: the menu opens,
`Escape` closes it, and the items really act (`tabs` 1 → 2, `workspaces` 1 → 2).

### P72 — Back to live when one line from the end (2026-11-12)

Scrolling back keeps the anchor (P32), but landing **one line** from the end
made no sense: there is nothing to read there. `scroll_view` and the anchored
recompute in `on_pty` now call `back_to_live` at `off <= 1`. Verified on Xvfb:
the wheel never parks at 1, it goes straight to 0.

### P73 — Combining mark glued to the previous cell (2026-11-12)

`put` appends an `Mn`/`Me` code point to the cell before it (cursor does not
move), so `e` + acute is **one** cell and the line stops shifting right; the
cell full + mark case and VS16 (emoji presentation) included. `_put_run` sends a
run with a mark char by char, decided by a per-string cache — the fast path pays
nothing. Check `combining_marks`.

### P74 — `OSC 9`/`777` also reach the desktop daemon (2026-11-12)

When the window is not active the notice goes to `org.freedesktop.Notifications`
over D-Bus (`notify_desktop`, silent when there is no daemon — we are not a
`Gtk.Application`, so the call is direct). Verified with a fake daemon inside
`dbus-run-session`: it received "Terminal | build terminou".

### P75 — The eight chrome colors in the configuration (2026-11-12)

`style.py` gained `CHROME` (config key -> tokens) and `defaults()`, so the
sidebar/tab/card colors are keys like `chrome_bg` and `chrome_accent_bg` —
`config.FALLBACK` reads its defaults from there, no hex copy. The CSS provider is
now reused and rewritten on reload, so the change applies live. Check
`chrome_config`; pixels on Xvfb confirm both keys.

### P76 — `OSC 8` `id=` groups cells into one link (2026-11-12)

The link is interned by `(uri, id)` and `link_key` returns the `id` (or the URI
when there is none); the hover underline compares keys, so a link broken over two
lines underlines whole. Verified by pixels: hovering the second line lit **both**
lines of the same `id` and left the unrelated link alone. Check `osc8_link_id`.

### P57 — `restore_state content`: the photograph of each tab (2026-11-13)

The snapshot is ANSI (`term.snapshot`), so the reader is the parser already
there: SGR, `OSC 8` and soft wraps go as bytes, and a photo taken wide reopens
narrow through the resize code. One file per (workspace, tab) next to
`window.json`, fed to the fresh `Term` **before** the shell exists; the marker is
`row_chrome`, out of the next photo. Check `snapshot_restore`.

### P77 — Cell layout: packed rows and the frozen history (2026-11-14)

A row became `ch` plus one `array('Q')` packing fg/bg/flags (link array built on
demand), and a row that leaves the screen freezes `ch` into a `str`. Anonymous
memory of a 10000-row history: 78.7 MB to 10.2 MB in ASCII and 128 MB to 15.1 MB
in CJK, while `feed` paid 10% and drawing got faster. Two shapes, so cold paths
read through `row_text`/`cell`/`cell_abs`; numbers in [BENCHMARKS.md](BENCHMARKS.md).

### P80 — Chunked kitty transmission decoded per chunk (2026-11-14)

The base64 of `m=1` chunks was accumulated and decoded once, but chafa and
`kitten icat` pad **every** chunk, so `binascii` stopped at the first `=`; a
320x160 RGBA frame arrived as 512 bytes of 204800 and the terminal answered
`EINVAL:size`. Now each chunk decodes on its own and the bytes add up. The
battery had no chunked case — `graphics_chunked` covers both sender shapes.

### P81 — DCS is consumed, not printed (2026-11-14)

The parser had no dcs state: `ESC P` dropped the introducer and the body went to
the screen, so a sixel image became rows of garbage and `XTVERSION`
(`ESC P+q544e`) printed `+q544e`. DCS is now skipped by a find of the terminator
(256 chars kept for debugging) and ends at BEL or ST. `dcs_is_consumed` feeds
sixel, XTVERSION and a 5 KB body.

### P82 — `CSI 14 t` answers the text area in pixels (2026-11-14)

`kitten icat` asks it before transmitting and gave up with "Terminal does not
support reporting screen sizes in pixels"; 16 and 18 were answered, 14 was not.
Now 14/15 answer `4;h;w`/`5;h;w` and 19 answers `9;rows;cols`, from `cell_size`.

### P85 — An image over the top edge is clipped, not skipped (2026-11-14)

`icat` places a 38-row image on a 37-row screen and scrolls it to row -2; the
draw loop skipped any placement with `vr < 0`, so the picture vanished even
though the grid had 1 image and 1 placement. The loop now skips only what does
not overlap the screen and lets the cairo clip cut the rest, as kitty does.

### P86 — A picture lives in its cells; the alternate screen has its own (2026-11-14)

Reported: `chafa -f kitty` drew the image, `mc` opened and the picture stayed on
every cell `mc` left blank, because `ED`/`EL`/`ECH` erased the cells and kept the
placement. `Graphics.erase` drops what intersects the erased span and `?1049`
gives the alternate buffer its own set; `ED 2` reaches the screen, not the
history. Parity with the Rust TorTTY (B3, 1.0.85).

### P87 — The child reads the cell before the first resize (2026-11-14)

`chafa -f kitty` right after the tab opened drew the image squashed (196 px wide
of the 224 asked): a fresh pty says 0x0 px, so chafa fell back to an 8x8 cell.
The winsize now goes out right after `pty.fork`, and `metrics()` runs **before**
the fork — it loads the font, and that delay was what let the child read first.
6 of 6 runs correct afterwards, 3 of 6 before.

### P84 — iTerm2 inline images (2026-11-14)

`OSC 1337;File=inline=1;width=…;height=…:<base64>` draws at the cursor and moves
it below. It is the same placement object as kitty, so scrolling, `ED`/`EL`, the
alt screen and the history come for free. Units are cells, `px` and `%`;
`GdkPixbuf` decodes the payload, since `chafa -f iterm` sends TIFF and cairo
reads only PNG. A four-quadrant PNG landed 32x14 cells pixel-exact.

### P89 — A big OSC was quadratic: the image took 25 s to appear (2026-11-14)

User report: iTerm2 images did not work. They did arrive; `self.osc += ch` per
character is O(n²), and chafa at a wide window sends ~1.3 MB of base64 — 25 s of
main loop, the pty full, the app looking dead. `osc`/`apc` now collect chunks in
a list and join at the terminator: 1.3 MB from ~25 s to 172 ms, the 100→400 KB
ratio from 18.5x to 4x. `huge_osc_is_linear` asserts the ratio, not a wall time.

### P88 — A ceiling on the OSC/APC body (2026-11-14)

A child that never sends BEL/ST grew the buffers without bound. Now past
`OSC_MAX` (16 MB) the body is still consumed to the terminator and then thrown
away — no text, no image, no reply, parser back to `ground`. A 1.3 MB iTerm2
payload still lands (272 ms) and a 20 MB one costs the parser loop only.

### P90 — An image without a size or a PNG header (2026-11-14)

`chafa` always sends `width`/`height`, so we never saw it: `imgcat` sends only
`File=name=…;size=…;inline=1:`, and a JPEG through it vanished with no message,
because the pure layer only knows `png_size`. `Graphics.measure` is a hook the
GUI layer fills (`view.measure_image`, GdkPixbuf); unset — the `--selftest`
path — behaviour is exactly what it was.

### P83 — Sixel (2026-11-14)

The last image format: `decode_sixel` reads DECSIXEL into ARGB32 (`#` RGB/HLS,
6-row bands, `!`, `$`/`-`, the `"` raster). The parser stopped dropping every
DCS — a head matching `[0-9;]*q` is sixel, XTVERSION/DECRQSS die at the first
non-matching byte. `fmt 101` skips the per-pixel RGBA copy. `chafa -f sixel`
draws, cursor below.

### P91 — One owner of the state (2026-11-15)

Two windows opened together overwrote `window.json` on the way out, and a probe
with `--cmd` clobbered the real session's layout. The owner is the window
holding a `flock` on `state.lock`; a window that finds it taken is scratch (one
tab in the cwd, default geometry, never writes). `--cmd`, `--rows`, `--cols`,
`PYTERM_GEOM` and `restore_state none` never try the lock.

### P92 — Image animation (`a=f`/`a=a`) (2026-11-15)

The kitty protocol's animation was dropped on purpose since P84. Now `a=f` adds
a frame (`z=` gap, `r=` replaces), `a=a` starts it (`s=` 1/2/3, `v=` loops) and
`Image.show_frame` swaps in an ARGB32 built once per frame, so the draw path is
untouched. The view runs one lazy timer with the gap the frame asks for. Frames
are whole bitmaps: a rectangle frame and a PNG frame are refused.

### P93 — Prompt marks (`OSC 133`) and the jump (2026-11-15)

`A`/`B`/`C`/`D[;status]` become marks on absolute lines, capped at 512 and
pruned when their line leaves the history; `Ctrl+Shift+Up/Down` puts the
previous/next prompt on the first row (strictly above / strictly from the top, so
the prompt already in sight is not "next"). Nothing else consumes them yet.

### P94 — Search in the scrollback (`Ctrl+Shift+F`) (2026-11-15)

`find_hits` walks the history and the grid with `str.find` (line absolute, 5000
matches at most); `Search` walks them with a wrap. The bar is `[find: query_]` on
the last row with `[ 1/3 ]` on the right, matches highlighted behind the text,
and the view jumps to the newest. The socket's `keys` verb now fills `ev.string`,
without which it could not type.

### P95 — The shortcut table goes to the config (`map`/`unmap`) (2026-11-15)

Nineteen actions bound to chords, the defaults written as `map` lines in the
embedded file, so the file is the table: `map ctrl+shift+y new_tab`, `unmap
ctrl+shift+w`. `map` is the only accumulating key (`unmap` is normalized into
it). The view stopped handling Ctrl+Shift+C/V and Shift+PgUp/PgDn/Home/End, or
`unmap` would not free the key.

### P96 — A picture by file or shared memory (2026-11-15)

`t=f`, `t=t` and `t=s` were refused: only the base64 escape worked, so anything
that already had the bytes on disk paid the round trip or fell back. The payload
is now a path (`t=s` becomes `/dev/shm/<name>`) read through a `Graphics.load`
hook that `view.py` fills with `media.load`; `t=t` is deleted once read, `a=q`
answers OK only after a real read, and 32 MB is the ceiling.

### P97 — Carrying the workspace up and down the sidebar (2026-11-15)

`ws_move_up`/`ws_move_down` (`Super+Shift+Up/Down`) reorder `self.workspaces`
and the `Gtk.ListBox` rows together, so the sidebar order is the session order —
and the order `restore_state` brings back. Two homes, one move: the check on the
list plus the highlighted card moving one slot is what proves the pair.

### P98 — The command line wins over the file (2026-11-15)

`--font-family`, `--font-size` and `--scrollback` now override the configuration
file, with the same precedence the Rust has (CLI > file > defaults). They go
through the same `CHECKS` as the file, so a value out of range is a usage error
(exit 2) instead of a silent default, and `cli.parse_args` returns a named
`Args` instead of a nine-tuple.

### B39 — The desktop shortcut started nothing (2026-11-17)

The shortcut was correct; the venv behind it was not. `pipx install --force`
keeps the interpreter of the existing venv and ignores `--python`, so the one
here was built on uv's CPython — whose site-packages never include Debian's
`dist-packages`, where `gi` lives. The app printed "missing gi" and exited.
The installer now removes the package and installs a fresh venv with `--python`
(the only way pipx honours it), then checks `import gi` in that venv: the
`--force` branch it had was itself breaking working installs.

### B38 — The installer gave up after a successful install (2026-11-17)

On a machine that never had the app, `~/.local/bin` is not in PATH yet, so the
`command -v` check right after `pipx install` failed and the script exited 5 —
with the app installed, the shortcut missing and no `--selftest`. The binary is
now called by the path pipx reports and the missing PATH is a note, not an error.
The clean-container run also showed the tree's `@VERSION@` placeholder reaching
the download ("invalid version"): taken from main it now means the latest release.

### B37 — Dragging a tab left the app on the old tab (2026-11-15)

Dragging a tab reorders the pages of the `Gtk.Notebook`, but `Workspace.views`
kept the creation order: from then on page 1 showed one tab while the keyboard
focus, `Ctrl+Shift+C` and the saved layout used another. `self.view` now reads
the page widget, the `page-reordered` signal rebuilds the list and
`on_switch_page` uses the view the signal carries, not `views[page_num]`.

### P99 — Stacking order for images (2026-11-15)

`z=` was accepted and thrown away, so an image always went over everything, in
arrival order. Now larger `z` is in front, equal `z` keeps arrival order and a
negative `z` goes **behind the text**: the drawing does two passes over the
placements, one before the glyphs and one after.

### P100 — Tab stops survive the resize (2026-11-15)

A resize re-seeded the stops every 8 and threw away what the app had set with
`HTS`/`TBC`, so a `	` layout broke on every window resize. The list is kept and
extended now: the new columns get the default, the app's stops stay.

### P101 — Sixel sits on the tab background (2026-11-15)

A pixel the sixel stream never set came out transparent and the colour before
the first `#` was black, because the pure decoder had no access to the theme.
`decode_sixel` takes the background now and `Term` passes `theme.bg`, so the
image covers the cells behind it instead of showing them through.

### P102 — Rectangle frames and `a=c` in the image protocol (2026-11-15)

`a=f` refused any frame that did not cover the whole image and `a=c` answered
`EINVAL`. Both are a blit now: the previous frame (or the image bitmap) copied
and the rectangle pasted over it, through the same `blit`/`argb` pair. The
bitmap also got a serial, so the view drops its cached surface when an image
changes — before, a second transmission with the same id kept the old picture.

### P103 — The exit status of the last command on the tab (2026-11-15)

`OSC 133;D;n` was parsed into the mark and then nobody read it. The status now
lands on the tab label as a mark (`✓` zero, `✗n` anything else), colored from
`style.py`, and it survives the next prompt — the point is to see a failure on a
background tab without switching to it. `D` with no number keeps the old value;
`RIS` clears it. It needs a shell that emits `OSC 133`.

### P104 — Copy mode: the keyboard over the scrollback (2026-11-15)

Copying history needed the mouse and a drag that could not leave the screen. Now
`Ctrl+Shift+Space` puts a `CellAnchor` cursor on the scrollback (`hjkl`/arrows
move, `v` marks, `y` copies, `Esc` leaves), the view follows it and the output
stops dragging the text away. It also fixed the copy path: a selection ending at
column 0 of a line brought that line's first character, not just the newline.

### P105 — HPA, the missing final (2026-11-17)

Diffing the two CSI dispatchers, the Rust set turned out to be the Python set plus
one final: `` ` `` (HPA), the same column as `CHA` under another name. It joined the
`G` arm, so `CSI 5` and `CSI 5\`` land on the same column.

### P106 — The link table has a ceiling (2026-11-17)

`OSC 8` grew one entry per distinct URI, so a child inventing a URI per cell grew
it without limit. Now it stops at `LINK_MAX` (4096, the Rust number) and past it
the text is still text, only without a link; a repeated URI keeps reusing its
index, so the ceiling counts distinct URIs.

### P107 — A URI with a control character is not a link (2026-11-17)

Rust drops the control characters of an `OSC 8` URI before storing it, because the
URI ends up in a context menu and in `xdg-open`; here it reached the table as it
came (`http://a\x01b`). Now `_readable` filters C0/DEL/C1, and a URI that was
nothing but control is no link at all.

## Bugs found and fixed (useful history)

All of them were found with measurement, not by reading — the method is worth
recording.

1. **Wrong cell metric (text sliding).** The cell width came from
   `text_extents("M").width` (680/75 ≈ 9.06 px) and the real advance of the font
   was larger, so the columns misaligned and the text overlapped. Fix: width =
   `ceil(x_advance)`, height = `ceil(ascent + descent)`.
2. **`resize` erased the screen.** `Term.resize` recreated the grid in blank; if
   the configure arrived after the first output, the text vanished. Fix: preserve
   by cropping/filling.
3. **`configure-event` did not apply the resize.** The `GtkWindow` signal arrives
   **before** the child is re-allocated, so `get_allocation()` returned the old
   size and `mc` ended up with a broken layout. Fix: `size-allocate` on the
   `DrawingArea`, using the received allocation.
4. **Arrows ignored in `mc`.** `mc`/`vim`/`less` turn on `DECCKM` (`?1`) and start
   expecting `\EOA`..`\EOD` (xterm terminfo application mode); I always sent
   `\E[A`. Fix: track `?1` and swap the shape of the arrows, Home and End.
5. **Modifiers became a character ("tiny box").** `Shift_L`, `Control_L`,
   `Alt_L`, `Super_L`, `Caps_Lock`, `Menu` have keyval in `0xff00–0xffff`, and the
   fallback did `chr(kv)` → a character without a glyph. Fix: only send a
   printable character (latin-1 `0x20–0x7e`/`0xa0–0xff` or unicode `0x01000000+U`).
6. **Dead keys did nothing.** Fix: store the mark and compose by NFC
   (`~`+`a` → `ã`); dead key + space emits the isolated one (`~`, `^`, `` ` ``...).
7. **Black footer under an app with a colored background.** Run backgrounds had
   height `ch`, so the sub-cell leftover (520 − 27×19 = 7 px here) kept the
   default background — with `vim` `guibg=#123456` it showed as a black stripe at
   the bottom. Fix: the leftover strip inherits the background of the last row
   (the right one, of the last column) — capture: `y=512..519` → `(18,52,86)`.
8. **`DA` never answered.** `CSI c` without parameters became `[0]` and the
   condition `not params` failed. Fix: empty body → empty list.
9. **Tabs/workspaces: six silent GTK pitfalls** — new page hidden with
   `set_current_page` ignored, `grab_focus` in `switch-page`, `sh -c` without exec
   (cwd in the grandchild), `EventBox` without a mask, `set_tab_label_text`
   swapping the label widget and `Gtk.Box` without `reorder()`. The six are in
   [DEBUG.md](DEBUG.md), with the fix.

10. **`--help` opened the window.** `parse_args` silently ignored any unknown
    option, so `--help` (and `--nada`) fell into the normal flow and brought the
    app up. Fix: `-h`/`--help` handled before the Gtk import (usage, exit 0); an
    unknown option — or one without a value — became a usage error (stderr,
    exit 2), `parse_args` returns it, covered by `argv_parsing`.

11. **Renaming the workspace left the session deaf.** The rename `Entry` is
    removed on confirm and took the focus with it, and the global shortcuts only
    existed in `TermView.on_key` — any focus outside the session (card, tab bar,
    Entry) killed them. Fix: `finish()` gives the focus back and the window got
    its own `key-press-event` on the same `handle_shortcut` (view first, no double).

12. **Screen froze under continuous dump.** The pty watch at `PRIORITY_DEFAULT`
    (0) beat the GDK redraw (120) on every iteration: the surface kept the last
    frame while the pty burned 0.3 MB/s (3 captures 2 s apart, identical pixels).
    Fix: watch at `PRIORITY_DEFAULT_IDLE` (200) and drawing coalesced at ~16 ms
    (`request_draw`, 60 Hz) — without it dozens of draws per frame fell to 7.9 fps.

13. **Squeezed text and wrong column after the font in points.** The cell was
    measured with the widget context (130 dpi: 14×28 px) but the layouts came
    from the `cr`, without resolution (96 dpi: 10 px advance): 70 `M` took 700 of
    980 px, spaces vanished, wrap seemed wrong (the grid wraps). Fix:
    `context_set_resolution(ctx, dpi)` on EVERY layout. `PYTERM_DIAG=1` born here.

14. **Scrollback unusable inside `pi`: the view went back to the footer.**
    `on_pty` returned to live on ANY output, and `pi` publishes every second,
    forever, 10 invisible bytes (`CSI 1 G` + `CSI ?25 l`) — captured: 24 ticks in
    22 s, 10 B/s; each tick zeroed `view_off`. Fix: store the signature of what is
    visible before `feed`, return to live only if it changes. After: 0 pixel diff.

15. **Scrolling the scrollback got slower the further up.**
    `visible_rows(off)` used `grid[:rows - off]` — a negative slice is the WHOLE
    grid, so with `off > rows` it painted `off` lines (1000 instead of 21 at the
    top). Fix: slice the scrollback directly when `off >= rows`, else the old
    path; always exactly `rows` lines. Measured: top 10.72 → 1.67 ms/draw (6.6x).

16. **Clicking to drag in the scrollback went back to live.**
    `on_button_press` called `back_to_live()` before any branch, so pressing to
    copy an old excerpt selected present-day text. Fix: the view stays where the
    press only arms the local selection (button 1 without `mouse_mode`) and goes
    to live only where the destination is the app (mouse report, middle paste).

17. **The selection did not follow the screen scroll.** Rows were SCREEN rows:
    scrolling left the highlight over other text and the next `copy` read the
    wrong one (P28's mitigation swapped "wrong text" for "lost selection"). Fix:
    absolute anchor (`Term.CellAnchor`, line = `scrolled - view_off + row`); the
    anchor carries `abs_gen` — `CSI 3J`, RIS, reflow invalidate, the cap cut does not. Check `selection_follows_history`.

18. **RIS put the scrollback cap back to 1000.** `Term.reset` recreated the whole
    `Term` and took `scrollback_limit` along, which is configuration and not app
    state: with `scrollback 5`, an `ESC c` started keeping 1000 lines. Fix: read
    the value before the `__init__` and put it back after. Found reviewing bug
    17; `scrollback_and_bell` now sends `RIS` and confirms the cap survives.

19. **The child `$SHELL` was not the shell that ran.** The `sh -c` of the pty
    inherits the environment of whoever opened the app, so `SHELL=/usr/bin/zsh`
    stayed even with `shell /bin/dash` (dash was executing). Fix:
    `config.effective_shell` resolves empty → `$SHELL` → `/bin/bash`, exported as
    `SHELL` in the child. Verified in Xvfb: empty gives zsh, `shell /bin/dash` gives dash.

20. **Scrolling the scrollback and the app repaint threw the view to the top.**
    `pi` redraws with `?2026h` + `2J H 3J` + the buffer: the `3J` zeroed the
    history while the anchor stayed absolute, so each line increased
    `scrolled - anchor` and the clamp rested on the new top. Fix: `hist_gen`
    announces the clearing; the view swaps for `pinned_view_off`. Check `redraw_keeps_history_position`.

21. **Sidebar card one tab switch behind.** `on_switch_page` updated the card
    calling `update_card()`, which reads `notebook.get_current_page()` — inside
    the `switch-page` signal the notebook still answers the OLD page, so card and
    window title showed the previous tab. Fix: `update_card(v)`/`sync_title(v)`
    receive the view the signal delivers. Verified with a probe on three tabs.

22. **App repaint took whoever was reading the scrollback to the top.** With
    `?2026` open, `_on_pty` kept resolving the position against the history being
    rewritten: on `3J` it fell to live and, when the pin expired, the anchor
    escalated to the clamp (the top). Fix: inside the region `view_off` is not
    written (the pin resolves at the close, full buffer). Generator: closes with the same `v`.

23. **`DCH`/`ICH` past the row width grew the row.** `CSI k P` deleted
    `k` cells from the slice but extended by `k` anyway, so the row could end up
    longer than `cols` — and the reflow assumes `len(row) == cols`. Fix: clamp `k`
    to `cols - cx` (which also stops `CSI 999999999 @` from allocating the lot).
24. **The reflow trim ate styled blanks.** The trailing-blank cut looked only at
    the character and the bg, so an underlined space or a space carrying a
    hyperlink was dropped on resize. Fix: cut only a cell that is empty for real
    (space, default bg, no flags, no link). Checks `dch_beyond_row_width` and
    `reflow_keeps_styled_blank`.

25. **A click on a tab label left the keyboard dead.** The label's `EventBox`
    returned `False` on button 1, so the press reached the notebook's default
    handler — which drags the keyboard focus to the `GtkNotebook`, where the tab
    navigation eats every key. The terminal answered nothing until a Tab key (or a
    tab switch, through `_focus_idle`) handed the focus back. Fix:
    `GLib.idle_add(self._focus_idle, view)` on button 1; the grab cannot happen
    inside the handler, the default one runs after it. Verified on Xvfb with
    injected clicks and the new `state.focus` field.

26. **`mc` threw the scrollback away.** Entering the alt screen with `?1049`
    cleared `scrollback` in `set_mode` (`?47`/`?1047` did not): the history was
    gone for good, so `Shift+PgUp` after `mc`/`vim` showed nothing. It is not what
    `?1049` means — it saves the cursor and switches to the alternate buffer,
    which is the one born clean; the primary buffer and its scrollback come back
    on exit. Fix: drop the three `clear()` calls, and `ED 3` issued up there
    (`CSI 3J`) no longer takes the main history, its links and its pictures —
    it clears the alternate screen and nothing else. Check
    `alt_screen_keeps_scrollback`. Parity with the Rust TorTTY, fixed there as
    B63 with the same two guards.

## Documentation note: number in only one place

Until 2026-10-27 the throughput numbers lived repeated in README, LIMITATIONS,
TASK and AGENTS, and the AGENTS.md rule ordered updating them all together. In
practice they diverged on every re-measurement (three rounds of "0.5 → 0.6 → 3.4
MB/s" and copies forgotten at 0.5). The rule changed: **the value lives only in
BENCHMARKS.md** (date + governor); the other docs cite the fact and link. The
README keeps the doom-fire line in the comparative table (headline) and the
HISTORY records the number of the day it closed an item, as a dated record — not
as current reading. Two obsolete lines of the README (parse+grid "0.7–1.9 MiB/s"
and "drawing 1.2 ms") went out along with it: they were from an old bench and now
contradicted the BENCHMARKS.

## Pitfalls (they left here)

The development, graphical session and tool pitfalls used to live in this
section; now they live in [DEBUG.md](DEBUG.md) — a short, operational file, to be
read before running a tool. What is a measurement number stays in
[BENCHMARKS.md](BENCHMARKS.md). This file keeps only the dated narrative.

## Git and repository origin

It was born in the repository of the `kitty` experiment
(`~/dados/workflows/temp/kitty`), in the `pyterm/` folder, with the name
**pyterm**. On 2026-10-25 it became its own repository, `tortty-python`, with the name
**bzmux**. The C/GTK part stayed there (see README.md): it is not compiled or
tested here.

The commits up to the split came through `git subtree split`, which **rewrites
hashes**: those of the origin repository do not exist here nor on GitHub, and the
old messages still say `pyterm`. `520447b` is the rename to `bzmux`.

Full history: `git log --oneline` (the list of hashes is not kept by hand).
