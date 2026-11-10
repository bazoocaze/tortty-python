# TorTTY-Python — history

Concise history of past activities. Maximum of 10 lines per activity.

### P1 — Mouse (report to apps + selection/copy) — **done**

`?1000`/`?1002`/`?1003` (click / drag / motion), `?1006` (SGR),
`?1004` (focus sends `CSI I` / `CSI O`), encoding in `core/mouse.py`
(pure, testable without display). Outside the mouse modes the window does
local selection by dragging: video reverse, `Ctrl+Shift+C` copies (selection or
viewport), `Ctrl+Shift+V` pastes, the middle button pastes PRIMARY.
`Ctrl+Shift+C/V` are intercepted before the keyboard — otherwise `Ctrl+Shift+C`
became the same `^C` as `Ctrl+C` and killed the process.

Bug found along the way (and fixed): the inversion was done on the color
**indices** and only then converted to RGB. `DEF_FG`/`DEF_BG` are sentinels
(256/257), not indices, so `256 - 256 % 256 = 0` became black and
`257 % 256 = 1` became **red**: selecting default text came out red-on-black,
and `\e[7m` likewise. Fix: convert to RGB first, invert after.

Verified with synthetic XTest (`tools/xtest.py`): click →
`\e[<0;5;4M`/`m`, drag → `\e[<32;12;6M`, wheel → `\e[<65;31;11M`;
selection + `Ctrl+Shift+C` + `Ctrl+Shift+V` into a `cat` returned the right
text, and a screenshot confirmed the highlight.

Missing (left for later): double-click by word, rectangular selection.

### P2 — Scrollback screen (scroll the history) + scroll with the mouse — **done**

`Term.visible_rows(off)` returns the window of `rows` lines over
`scrollback + grid` without touching the cursor or what the app wrote; the
window uses `off = view_off` in the drawing, in the copy and in the dump.

- `Shift+PgUp`/`PgDn` (one page), `Shift+Home`/`End` (everything), **wheel**
  (3 lines per notch).
- Back to live on typing, on clicking and when the child writes.
- Wheel without an app in mouse mode scrolls the view; with an app in mouse
  mode it sends `64`/`65` (`CSI < b ; x ; y M`/`m`) — but **if the view is in
  the scrollback the wheel stays in the scrollback**, otherwise the app "stole"
  the scroll exactly when the user was reading.
- `↑N` indicator in the top right corner; the app cursor is not drawn in the
  scrollback (the view cursor is separate, on purpose).

Bug found along the way: **pressing Shift reset the scrollback**. Shift arrives
as a key event before the real key, and "any key goes back to live" zeroed the
view — so `Shift+PgUp` went back to live and restarted from `off`=0, although it
accumulated correctly in the counter (`6 + 21` stayed 21). Fix:
`keys.is_modifier()` — a pure modifier does not leave the scrollback.

Verified: `seq 1 60`, 2 wheel notches + `Shift+PgUp` → `↑27`, top at line 13;
typing `a` went back to live (dump confirms).

### P3 — Reflow on resize — **done**

The logical line is now traceable: `Term.row_wrapped[i]` (and `sb_wrapped`,
parallel to the scrollback) marks a *soft wrap* — the line filled up and
continues on the one below, unlike a real `\n`. `put()` sets the flag when it
overflows the last column; `scroll_up`, `IL`/`DL`, `ED 3` and `?1049` keep the
lists in sync.

`_reflow(cols, rows)` joins the logical lines of `scrollback + grid`, cuts at
the new width, puts the cursor back on the equivalent cell (offset inside the
logical line, not `(cx, cy)`) and splits the result: what is left over on top
goes to the scrollback, what is missing at the bottom is filled. Widening
**pulls back** lines that were in the scrollback — that is what makes 100
characters become a single line again. Alt-screen stays on cropping
(`_resize_crop`): `mc`/`vim` redraw everything on SIGWINCH.

Bug found (the one that almost ruined it): without **cutting the trailing white
space** of the logical line, a 3-character line on a 68-column screen rewraps
into two (the second one with only spaces) and the content shows up
**interleaved with empty lines** when narrowing — I saw this with `seq 1 200` at
36 columns. Fix: cut truly empty cells (space with default bg), preserve
colored background, and never cut before the cursor column. I also had to stop
overwriting the cursor on every chunk: only the first chunk that contains the
offset wins (otherwise the cursor jumped to the last chunk of the line).

Verified: a 400-character line at 1000x700 → 4 lines; at 300x300 → 14
lines (13×30 + 10), contiguous; `seq 1 200` narrowed to 36 columns keeps
191..200 without holes; `--selftest` covers 1→4 and 4→1 with the cursor.

### P4 — Real truecolor — **done**

The RGB lives in the **cell itself**, with no allocated color table and no
tuple: the palette index is still a small `int` (0-255) or a sentinel (256/257),
and truecolor becomes an `int` marked in **bit 24** — `TC | r<<16 | g<<8 | b`
(`palette.rgb()` / `cell_rgb()`). That way the 256-color path pays nothing (no
`dict` per cell, no LRU) and the cell does not get fatter: the `int` of a
`#123456` is 0x1123456, which in CPython takes the same as 196.

SGR: `38;2;r;g;b`, `48;2;r;g;b` and the **form with `:`** (`38:2::r:g:b`,
`38:2:0:r:g:b`, `48:5:196`). The empty subparameter is the omitted color space,
and position matters: the parser keeps the group as a tuple (only for the final
`m`) and `sgr()` flattens it with `_sgr_subparams()` — filtering the empties
would change the meaning of `48:5::196`.

The drawing resolves the color before inverting (`cell_rgb`), so inverse/selection
keep swapping RGB, and grouping into runs keeps comparing `int`
(truecolor cells of distinct colors do not group, as it should be).

Verified in `--selftest` (fg/bg in the cell, round trip, `:` form, 256
colors not becoming RGB, reset, survives reflow) and pixel by pixel with
`vim -c 'set termguicolors'`:
`hi Normal guibg=#123456 guifg=#ffcc00` → background `(18,52,86)` and glyph
`(255,204,0)` exact in the capture. `38;2` no longer goes through `_nearest`.

Out of scope (documented): `58;2` (underline color) — we do not even draw a
colored underline.

### P5 — Kitty keyboard protocol — **done**

`core/kitty_kbd.py` (pure, no Gtk) + state in `Term`
(`kbd_flags`/`kbd_stack`). Protocol: `CSI > flags u` push, `CSI < n u` pop,
`CSI = flags ; mode u` (1 replaces, 2 adds, 3 removes) and `CSI ? u` →
answers `CSI ?<flags>u`.

Encoding mirrored on kitty's `encode_key()`/`encode_function_key()`
(its `key_encoding.c`, which was the reference):

- `disambiguate` (1): Esc/Enter/Tab/Backspace become `CSI 27u`/`13u`/`9u`/`127u`;
  Ctrl/Alt/Super+key become `CSI code ; mods u`; arrows/F1–F12 with a
  modifier become `CSI 1 ; mods A` etc.
- `report event types` (2): suffix `:1`/`:2`/`:3`; the window starts listening
  to `key-release-event`.
- `report all keys as escape codes` (8) and `report associated text` (16).
- Outside those cases, it falls back to the legacy path (`\x1bOA`, `\x03`, plain
  text) — which is exactly what kitty does, so typing keeps working.

A detail that only showed up in the reference: the modifier field is
`1 + shift + 2*alt + 4*ctrl + 8*super`, and F3 is the only F key that uses a
number (13) instead of a letter (`CSI 13~`), because `CSI 1;mR` would collide
with the cursor position report.

Out of scope (documented in the README): flag 4 (`report alternate keys` — it
would require the alternate keysym, which Gdk does not give for free), repeat
distinguished from press (Gdk repeats as key-press) and the keypad mode.

Verified end to end with a child that turns on `CSI >3u` and prints what it
receives: Ctrl+a → `\e[97;5u` + `\e[97;5:3u`, Enter → `\e[13u` + `\e[13;1:3u`,
Shift+Up → `\e[1;2A` + `\e[1;2:3A`, and typing `x` is still `x`.

### P6 — Graphics protocol (kitty) — **done**

`graphics.py` pure (parse, decoding and placements) and drawing in `TermView`;
APC `ESC _ G` in the `Term` parser. Covers the actions and formats of the
protocol that `icat` uses — including `o=z` (zlib payload) and `X=`/`Y=`, which
is what `--place` sends after scaling on its own.

Decision: the placement stores the line of the GRID, not of the screen. It can
go negative and into the scrollback, and the drawing adds `view_off`, so
`Shift+PgUp`/wheel show the image in the right position (`drop_above()` and the
reflow prune what is gone for good). Discarded: making the image follow the
reflow line by line — it stays on the screen line, as in kitty (it is in
LIMITATIONS.md).

Bugs along the way: the `a=q` probe is about capability, not an image query
(`icat` uses it as a handshake and only proceeds on `OK`); `m=1` cannot be
accumulated in the control dictionary, otherwise the transmission never ends;
and the `CSI * x` (DECSACE) that `icat` sends before drawing fell through with
the `*` as final byte, leaving a stray "x" per image — fix: accept intermediates
0x20–0x2f.

Verified: PNG 160x90 in 2 chunks, raw RGBA 40x20 and the five-image demo in the
right places (screenshot), scrolling keeping up, and a real `kitten icat`
exiting with code 0; the same script runs the same in kitty.

### P7 — Bracketed paste — **done**

`?2004` in `set_mode` together with `?1000/?1006/?1004` → `Term.bracketed_paste`.
The paste policy lives in the `Term` (`paste_payload()`), not in the window: with
the mode on the text goes between `ESC[200~` and `ESC[201~`, otherwise it goes
raw. That way `--selftest` covers the behavior without display, and the pty
receives **text**, never a sequence that the terminal parser would interpret (it
is the safety point: what was pasted does not become a key).

**The bug that came along with it (and was the cause of the "Enter" on paste):**
`copy()` did `text += "\n"` **always**, so copying `abcdef` with the mouse put
`abcdef\n` in the clipboard and the paste ran the command. The kitty rule is to
join the lines with `\n` only BETWEEN them (`add_trailing_newline = insert_newlines
&& !is_last_line` in `text_for_range`): the end of line only goes in when the
drag reaches column 0 of the next line, because then the last line of the
selection is empty. The `+= "\n"` was removed.

Verified in `--selftest` (both `paste_payload` modes, selection without
newline) and end to end with a child that turns on `?2004` and dumps the bytes:

```
mode off      → got: b'abcdef\x04'
mode on       → got: b'\x1b[200~abcdef\x1b[201~\x04'
bash 5.2      → copying "echo a" and pasting does NOT execute; Enter executes
```

Not implemented on purpose: kitty's `strip_trailing_newlines` (removing a
trailing `\n` on paste) — it changes the behavior of whoever pastes multiline
on purpose.

### P8 — Close the window when the shell ends — **done**

The trigger is **`waitpid`**, not the pty EOF: `GLib.child_watch_add(pid)` reaps
the child and delivers the status. On Linux the master returns **EIO** (not
`b""`) when the last slave closes, and the old `on_pty` swallowed that `OSError`
and simply removed the watch — that is why `Ctrl+D` left the window open
forever.

- **No zombie**: `child_watch_add` is the one that reaps (the GLib does the
  `waitpid`); the tortty_python code does not call `waitpid` again.
- **Drain before closing**: `_drain_pty()` reads until `EAGAIN` (the fd is
  non-blocking) with a cap of 64 reads, feeding the `Term` — otherwise
  `dump()`/the last screen came out without the shell's goodbye.
- **Exit code**: non-zero goes to stderr (`tortty-python: shell exited with code 3`),
  which `debug.sh` stores in `/tmp/tortty-python.log`.
- **Hangup**: `os.killpg(child_pid, SIGHUP)` on closing (the `pty.fork` made the
  child a session leader), so background jobs do not stay orphaned holding the
  pty.
- **The reverse order also holds**: `EIO` before the `waitpid` → wait for the
  status; `waitpid` before the `EIO` → drain and close.

Gotcha that made the hangup "not work": **signal disposition is inherited**.
`debug.sh` starts with `nohup` (SIGHUP = ignored) and Python ignores SIGPIPE —
the child inherited both. Result: `killpg(SIGHUP)` killed nobody (the `sleep`
showed up with `SigIgn: 01001007`) and `seq 1 100000 | head -3` did not stop on
the broken pipe. Fix: in the `pty.fork` child, before the `exec`, `SIGHUP`/
`SIGPIPE`/`SIGINT`/`SIGQUIT`/`SIGTERM` go back to `SIG_DFL`.

Verified: `--cmd 'exit 3'` closes and logs code 3; `Ctrl+D` in an interactive
`bash` closes; `sleep 120 & ... exit` closes and the job dies on the SIGHUP;
`seq 1 100000 | head -3` finishes right away; `--quit-after 2` keeps closing;
closing the window through the WM kills the child (the master closes → kernel
SIGHUP on the foreground group).

### P9 — Ligatures and shaping — **done**

The drawing was `cairo.show_text` (toy API): no shaping, so no ligature came
out, Arabic did not join and a combining mark separated from the body of the
letter. Migrated to Pango, with one `Pango.Layout` per draw reused on every run.

- Layout cache by `(text, bold)`, cap of 800: `set_text` is the expensive part
  and a run repeats a lot — without the cache the drawing doubles (numbers
  below).
- Metrics come from the same layout that draws (advance of "M" and
  `get_pixel_size`); mixing cairo and Pango misaligns the grid. Underline stays
  a cairo rectangle, which does not depend on font metrics.

Cost of shaping with the doom-fire (68×20): 12.8 ms/frame before, 30.5 without
cache, 15.2–15.6 with cache — ~20% of the frame with cache, 2.4x without. All
three predate bug 13 (drawing at 96 dpi): they are valid among themselves, not
against [BENCHMARKS.md](BENCHMARKS.md).

Amendment: the font became **points**, not pixels. `font_size` came from cairo,
where size is a user unit; but every terminal exposes points, and the difference
is DPI — with `Xft.dpi: 130`, 13 pt = 23.5 px against 16 px, and that is why the
"13" of kitty looked bigger than the "16" here. With points, tortty-python and kitty give
the same grid for the same window (70×21 in 980×640). The metric has to come from
the Pango context of the widget, not from a loose surface ([DEBUG.md](DEBUG.md)).

### P10 — Font fallback (emoji/CJK) — **done**

It came down together with P9: fontconfig finds the font that has the glyph, so
CJK and color emoji now draw with no extra code. Verified on screen with
`printf '\u4e2d\u6587 \U0001F600'` in tortty-python.

Limit that stays (and is not a bug of the fallback): the grid **has no
`wcwidth`**, so a wide character takes a single cell and the glyph is squeezed/
overflowing inside it. An app that counts double columns (CJK table) comes out
misaligned; solving that means touching the cell model, not the drawing.

### P11 — Tabs — **done**

`Ctrl+Shift+T` opens a tab, `Alt+1..9` (`Alt+0` = the 10th) selects, `Ctrl+Shift+W`
closes; closing the last one closes the window.

- Structural decision: extract `TermView(Gtk.DrawingArea)` with the session state
  (pty, decoder, selection, `view_off`, image cache) and leave the window with the
  `Gtk.Notebook` plus the global shortcuts. `Term` still has no GTK. `Alt+N` is
  handled in the window, otherwise the child gets the key first.
- The label is the OSC 0/2 title or the cwd of the session (`readlink
  /proc/<pid>/cwd`, without depending on OSC 7): without OSC all tabs would be
  "TorTTY (Python)", and `Alt+N` already numbers them — hence no numeric prefix.
- The `child_watch_add` of P8 now closes the **tab**, and the aggregation "last
  tab → window" lives in a single place.

Four silent pitfalls (a new page starts hidden and `set_current_page` is
ignored; `grab_focus` inside `switch-page` does not take; `sh -c` does not exec,
the cwd is in the grandchild; `EventBox` without `add_events` has an empty mask
and `set_tab_label_text` swaps the widget): fix in [DEBUG.md](DEBUG.md).

Test by XTest (create, switch, type in each tab, middle click) and
`_NET_WM_NAME` for the title. `--selftest` does not cover it — it is a GTK layer.

### P12 — Workspaces — **done**

A workspace is a set of tabs with a card on the sidebar: `1  <active tab title>`,
fixed width (170 px), and the sidebar only shows up with 2+ workspaces.
`Ctrl+Shift+1..9` selects (`0` = the 10th), `Ctrl+Shift+N` creates, `Ctrl+Shift+Q`
or a middle click on the card close it, a double click renames it in place.
Closing the last tab closes the workspace; the last one, the window.

- `Gtk.Stack` with one `Gtk.Notebook` per page, not page switching of a single
  notebook: each workspace keeps its own selected tab, order and titles, and
  switching is one call.
- `Ctrl+N` was discarded on purpose: `C-n` is next line in readline,
  autocomplete in vim and next-line in emacs. cmux uses `Ctrl+N` because it is
  not *a* terminal. Do not "fix" it to `Ctrl+N` later.
- A hidden tab does not get `size-allocate`: when switching workspaces you have
  to force the recalculation of the view that appeared, otherwise `cols`/`rows`
  and the `Term` `SIGWINCH` stay old. The sidebar costs ~14 columns and every
  resize rewraps the buffer (reflow of P3).
- Keyboard, focus and widget pitfalls: [DEBUG.md](DEBUG.md).

Test by XTest and `xprop`: create, switch, rename, close by shortcut and by
middle click, and check that `Ctrl+Shift+T` opens a tab in the current
workspace. `--selftest` does not cover it.

### P13 — Interface style system — **done**

Request: black sidebar, selected workspace in dark green and light text. What
existed was the system theme painting everything, with a loose hex on the card.

Decision: `style.py` is the only source of chrome color — tokens (background,
text, hover and selected), `css()` building the text from them and `contrast()`
in relative sRGB (WCAG). Pure, so the check runs in `--selftest`; the terminal
palette stays separate, cell and chrome do not mix.

The check measures contrast, not taste — `style_contrast` requires >= 4.5:1 on
the four text/background pairs (normal and selected) and checks that the CSS uses
the tokens, so as not to have a hand copy again.

Verified with a capture and `tools/pixel.py`: sidebar and normal card in black,
active in dark green and hover in dark gray, name of the active one in white and
the second line in light green; on the day, 15.9:1 on the name and 6.1:1 on the
information.

### P14 — Sidebar width does not stay fixed — **done**

`SIDEBAR_W` is 170, but measured in a capture of P13 the sidebar opened with
**234 px** and the tab bar started at x=234. `set_size_request` is a minimum, not
a width: the card text (`1 workspace`, active tab title) is what gave the width.

Two properties of `Gtk.Label` get in the way, and they are different:

- **the minimum** — a `Label` without `ellipsize` publishes the text width as
  minimum, and the `ListBox` grows along;
- **the natural** — with the minimum fixed (only `ellipsize`), the `pack_start`
  with `expand=False` still gives the child the *natural* width, which is still
  the text one: measured 454 px of sidebar, 22 grid columns.

The recipe that closes both: `ellipsize(END)` + `max_width_chars(1)` +
`set_single_line_mode(True)` and `pack_start(label, False, True, 0)` (the `fill`
makes the label take the 170 px and truncate inside them).

The same problem existed in the `Gtk.Notebook` **tab**, and there it was worse:
the long title became the notebook minimum and the whole window stretched —
measured 1062 px of window and 121 grid columns instead of 680/51.
`scrollable(True)` does not solve it (the minimum still comes from the label).
Fix: the same three properties on the tab label, with `TAB_TITLE_CHARS = 20`
(width in chars because the tab is measured in chars; the sidebar, in turn, is
px, and it is the one that cannot depend on the font).

The whole text went to the tooltip (card and tab): truncating without a tooltip
hides information.

Verification (and the reason for this to exist as an item): a `while` alternating
`printf '\033]2;curto\007'` with a 60-char title made the grid oscillate
between **73 and 121 columns** — 48 columns of resize, SIGWINCH and reflow on
every switch — and the window grew to 1062 px. After: `cols` constant at 51 in
the SIGUSR1 dumps and window at 680, with the long title truncated to "…" on the
card and on the tab (sidebar boundary measured per pixel at x=170, mouse outside
it so `:hover` does not fool the sample).

As a bonus, `Pango` entered `gui.py` (single import point) and the rename
`Entry` got `width_chars(6)` — it also published width.

### P15 — `pi` screen stabilized messy — **done**

Report: open `pi` in tortty-python, wait for startup, and the screen stops incoherent (in
kitty it came out right). What could be seen: the startup warning blocks with the
status line and the `bh/P/X` bar *in the middle of them*, repeated borders and
blank lines between one line and another — "folded" layout.

Cause: **the `\r\n` after a line that fills the width advanced TWO lines.**
In `put()`, the pending wrap (`wrap_pending`, the one that marks "this full line
continues on the one below") was executed BEFORE the handling of `\r`, `\n`,
`\b` and `\t`; so the `\r\n` paid the pending wrap + the LF itself. An app that
fills the whole line to the end — pi renders with padding to the last column,
like every Ink renderer — grew one line per line, the screen scrolled without
stopping and the content overlapped.

Fix: control first, wrap after. `\r`/`\n`/`\b`/`\t` zero `wrap_pending` and only
then do what they do; the pending wrap still holds for text (then yes, the line
wraps). New check: `wrap_and_control`.

Verification (it is what closed the diagnosis, after two wrong attempts): with
`PYTERM_RAWLOG` the output of `pi` was recorded and replayed in the `Term`
without display — the mess showed up just the same. Compared with a reference
emulator (`uv pip install pyte`, temporary), our grid went from **38 different
lines out of 45** to **0**, with the same cursor and zero spurious scrollback.
Then, live: window of 140x45, `pi` rendered the same as kitty.

Two false leads, recorded because they cost time: (1) the missing answer to the
`CSI 16t` and `OSC 10/11/4` queries was *not* the cause — implementing the
answers did not change the layout; (2) running both terminals at the same time
contaminates the measurement and the visual comparison. What solved it was
deterministic replay against a reference, not screenshot after screenshot.

### P16 — Doom fire as measurement load — **done**

`tools/doomfire.py`: the effect from the PSX port of Doom (buffer 0..36
propagated from bottom to top with decay, palette of 37 shades) in half-block,
with truecolor fg and bg **per cell**, grouping nothing — the worst case for the
parser and for the drawing, without depending on a real app. `--fps 0` lets go:
whoever limits becomes the terminal, and the fps reached is the measure of its
throughput.

Measured, same grid of 68 columns (68×20, the default since P17), `--fps 0`,
terminals one at a time:

| | fps | MB/s of escapes |
|---|---|---|
| tortty-python | 11.8 | 0.6 |
| kitty | 314.2 | 15.9 |

This is the measurement from the P16 days, with the cairo drawing. Later came P9
(Pango), the font in points (13 pt → 70×21 grid) and bug 13 (which only then
started drawing at the screen resolution); the live number is in
[BENCHMARKS.md](BENCHMARKS.md).

`PYTERM_PROF=1` decomposes the time in tortty-python: **parse 61%** (4.3 ms per read)
and **drawing 37%** (12.8 ms per frame of 1360 cells, ~29 draws/s). The drawing
is expensive here not because of the number of cells, but because of the number
of color *runs*: with 37 shades per line almost every cell is its own run, and
the cost per cell comes out ~11 µs, against ~1 µs of the uniform case that the
README measures. It is the baseline of P9 (Pango changes exactly that cost).

The first measurement (24.6 fps / 1.0 MB/s) was invalid: it was made with the
screen frozen by bug 12, that is, measuring only the parse. The record is kept
because the lesson holds: a throughput number without checking that the screen is
changing does not measure drawing.

Two pitfalls of the script itself, which only showed up running inside tortty-python:
without `SGR 0` on output the statistics inherit the last color of the fire (text
with yellow background), and a SIGTERM in the middle left the screen in
alt-screen — now there is a handler and the `finally` restores brush, cursor and
screen. The handler also allows measuring with `timeout -s TERM 20`, which is how
the quick measurements are made.

### P17 — Sidebar shows up with a single workspace — **done**

With **one** workspace the sidebar already appeared (170 px), although
`new_workspace()` calls `set_visible(len(workspaces) > 1)`. What showed it was
the `show_all()` of the window: it shows all descendants, including the `ListBox`
that had been hidden before. Measured cost: the grid fell from 68 to 51 columns
in the default window (680 px).

Fix: `sidebar.set_no_show_all(True)` — `show_all()` now ignores the sidebar and
only our `set_visible` commands the visibility. Verified per pixel (point of the
sidebar black/taken with 2+ workspaces, no sidebar with 1) and by the dump
(`68x20` with one workspace, `51x20` with two).

### P18 — Doubled keys inside `pi` — **done**

Symptom: typing in `pi` every key went in twice; shell, `vim` and `mc` normal.
Only `pi` turns on the kitty keyboard protocol with `CSI > 7 u`, that is, with
flag **2 = report event types**: the app starts receiving press, repeat and
release.

Cause: the release has no form in the legacy path (there "the key went up" is
just sending the byte again, which would be a second press), but `encode`
returned `None` for the cases where the legacy "already does it right" — plain
text, arrow without modifier. `None` means *use the legacy* in `encode_key`, so
the release fell there and resent the text. `a` came out on the press and again
on the release.

Fix: the rule ended up in a single place, `kitty_kbd.encode` — with flag 2 and
release, either the kitty sequence comes out, or `""` (nothing); never `None`.
`encode_key` still knows nothing about release, and the legacy path does not
change for press or repeat (repeat keeps resending the byte, which is right: in
the legacy repetition *is* a new press).

Verification: check in `kitty_keyboard` (with flags=7, `a` on press and `""` on
release) and live in `pi` — typing `abcabc` and reading the input line: `abcabc`
comes out, not `aabbcc…`.

### P20 — Escape fast path in the parser — **done**

Measured reason: 35 µs/cell of parse in the doom-fire frame, and 91% of that was
the closing of the CSI (`split`/`int`, param lists, `sgr` with `flatten`). The
bottleneck was not iterating characters: it was the fixed cost of closing and
interpreting each escape (~1 µs per escape byte).

Fix: in `Term.feed`, in the `ground` state, consume the prefix that the fast path
understands — printable text in a block (one `slice` on the line) and
`CSI 38;2;r;g;b m`/`48;2;...m` resolved by `dict[escape] -> color` — and give the
rest back to the usual parser, which stayed intact as fallback and owns all
states: an escape outside the pattern (`38;5;N`, `:`, intermediates, `\x1b[H`)
falls into it.

Verification: differential test against the parser of the previous commit (14
entries: doom-fire frame, SGR 4-bit/256/truecolor, `:` sub, charset, `ED`/`EL`,
OSC, RGB outside 0–255, inverse) comparing grid, cursor, colors, flags, pending
wrap, state and scrollback — 0 divergences.

On the day: micro 32.0 → 5.49 µs/cell (5.8x; plain text 4.7x); with
`PYTERM_NODRAW=1`, 17.2 → 85 fps and 1.0 → 4.8 MB/s; real `dmesg` without color
168.3 → 45.7 ms. With color the gain is smaller: the SGR of `dmesg` are not
truecolor and fall into the slow parser — that is what became P22. The number
with drawing looked anomalous and it was the `powersave` governor. Current
reading: BENCHMARKS.md.

### P21 — Shared blank line in the scroll — **done**

Reason: `scroll_up` costs 13.7 µs per line. The initial hypothesis was the
`pop(0)` of the `scrollback` with a cap of 1000 — **wrong**: measured with a
scrollback of 0, 500 and 1000 lines, the cost was 13.64 / 13.81 / 13.69 µs, that
is, the list shift does not show up. The expensive part was creating the blank
line: `_blank_row()` allocated 70 cell lists, 11.5 of the 13.7 µs. `deque` in the
`scrollback` would yield nothing and would still break the reflow slices.

Fix: one module-level blank cell `_BLANK_CELL`, shared — `_blank_row()` becomes
`[_BLANK_CELL] * cols` and `_blank_cell_raw()` returns the same list. It is only
safe because **nothing mutates a cell in place**: writing always replaces
(`row[x] = [ch, fg, bg, fl]`), `erase_*` creates a cell with the current bg
(`blank_cell()`, which keeps allocating) and reflow/resize only read and replace.
Cleaned up along the way a dead expression in `_blank_row`
(`self.bg if False else DEF_BG`).

Verification: check in `wrap_and_control` (two blank cells are the same object
and writing to one does not change the other — in-place mutation would paint the
whole screen), differential against the previous parser in the 14 cases (0
divergences) and `./run-tests.sh` (17 checks).

Gain: scroll 13.7 → 3.27 µs/line (4.2x); scrolling 20000 lines 38.4 →
10.9 µs/line (3.5x, the big-log `cat` case); in the doom-fire 85.0 → 86.6 fps,
because there the parse was already small and the scroll is 21 lines per frame.
The throughput bottleneck is still the drawing.

### P22 — Cache of CSI parameters — **done**

Reason: P20 only sped up truecolor SGR. A log with color (the system `dmesg`:
5172 escapes of `1`/`4`/`31`/`0`) gained 2.0x and not 3.7x, because those escapes
fell into the whole slow parser (`csi += ch`, `split`/`strip`/`int`, `parts`+`nums`
lists) — and they still paid the `find`/`slice` of `_sgr_fast` before falling
there.

Fix: `_csi_parse(body, final) -> (nums, prefix)` and a module-level cache
`(body, final) -> result`, cap of 1024. `_csi_fast` matches the whole CSI in the
buffer with `\x1b\[([0-9;:?]*)([\x40-\x7e])` and applies it from the cache; the
slow parser still owns the grammar and receives what the regex does not match
(CSI split between two feeds, intermediate `0x20-0x2f`, Unicode digit).

Consequences: `csi_dispatch` now receives a **tuple** (immutable — safe for the
cache), so `params == [6]` became `params == (6,)`; and `sgr` only allocates the
`flat` list when there is a subparameter with `:` (before it allocated on every
SGR).

Discarded attempt, with a number: prefix check in `_sgr_fast` (to avoid
`find`/`slice` on a non-truecolor escape) with char indexing cut 5% on the
`dmesg` with color and cost **18% on the doom-fire** (5.46 → 6.47 µs/cell); with
`startswith` it tied. Reverted — truecolor is the path that matters in the
benchmark.

Verification: differential against the previous parser in the 14 cases (0
divergences) and `./run-tests.sh` (17 checks).

Gain: `dmesg` without color 164.1 → 42.6 ms (3.8x); with `--color=always` 188.5 →
78.6 ms (**2.4x**, against 2.0x before P22). In the doom-fire nothing changes
(5.46 µs/cell) — there truecolor was already a fast path. App with
`PYTERM_NODRAW=1`: 86.5 fps / 4.9 MB/s.

### P23 — Workspace shortcuts with `Super` (2026-10-27)

Request: `Super+1`…`9` switches workspace, `Super+N` creates and `Super+Q` ends
the current workspace (with all its tabs). The three behaviors already existed in
`Ctrl+Shift`, so it was an alias, not new logic: `handle_shortcut` started reading
`SUPER_MASK` and a branch `super and not ctrl and not alt` reuses
`new_workspace` / `close_workspace` / `select_workspace_index`. The digit still
comes from `_digit_of(ev)` (it translates the raw keycode, so it works on ABNT2),
and `Ctrl+Shift+*` stays intact.

**Bug that showed up in the test:** `select_workspace_index` returns `False` when
the index does not exist, and the `return` passed that `False` along — the key
fell into the encoder and went to the child. Since `Super+2` arrives as plain
text (`2`, without `Ctrl`), the digit was **typed into the shell** (cursor
10.2 → 11.2 in the dump). Fix: consume the key (`return True`) when the keycode
is a workspace digit, even if there is no workspace at that index. The same
applied to `Ctrl+Shift+9` with nine workspaces (it leaked a `CSI` to the app).

Verification (manual, with display — `Gdk` stays out of the checks by design):
`xtest.py key super+n` creates the second workspace; `super+1`/`super+2` switch
(dump with the current ws and the tab count); `super+q` closes the ws with 3 tabs
at once and the children die (count of `bash --norc` drops); the sidebar
disappears with a single workspace; `ctrl+shift+n` keeps creating. The WM here
has no grab on `Super+1`…`9`/`N`/`Q` (the `xtest` injects into the server and
would go through the grab), but the note stays in the README: if the GNOME dash
captures it, use the `Ctrl+Shift` variant.

### P24/P25 — Drawing: float color and `show_layout_line` (2026-10-27)

Measured reason: with the parser solved (P20–P22), the drawing became the largest
slice after it (34% of the time), with 4 context calls and 2 color conversions per
run in ~1323 runs per draw. Two of them had no reason to cost what they cost.

Fix, with no change in appearance (the grid comes out pixel identical): the color
started coming cached as float 0..1 (`palette.cell_rgb_f`), shared tuples, and
since the same color returns the same tuple one can skip `set_source_rgb` by
comparing identities — which also attacks the case of a monochrome app, where the
color repeats. And the layout cache stores the line, drawing with
`PangoCairo.show_layout_line` instead of `show_layout` (-17% in the micro).

Verification: the battery does not cover drawing (it needs display), so fidelity
was checked by capture in `Xvfb :99` of the new code against HEAD — 0 pixel of
difference in the grid (the 448 left over are the tab title, which changed name).
On the day, `draw` 7.76 → 6.54 ms/call (-16%) and 110.7 → 116.0 fps (+4.8%,
consistent with drawing being 34% of the time). Breakdown by section:
BENCHMARKS.md.

### P31 — Installable package: `pipx install` straight from GitHub (2026-10-28)

The app was `bzmux.py` loose at the root importing `core/`: it ran, it did not
install. Without `[project.scripts]` `pipx`/`uv tool` refused, and `uv build`
**did not fail** — it fell into a legacy setuptools and produced a wheel with
`top_level = core` (generic name, collision in site-packages) and without the
script inside. Hence the acceptance criterion became inspecting the wheel, not
"it built".

- `core/` → `tortty_python/`, with `tortty_python/__main__.py` in place of the root script (which
  would be shadowed by the directory of the same name).
- The entry point is a function **without** arguments (`cli.run`): `console_scripts`
  calls it without argv, and `main(argv)` would demand the list and blow up with
  `TypeError` on the installed command. `main` keeps accepting argv because the
  checks depend on it.
- The `gi` guard only catches `ModuleNotFoundError` of `gi`/`cairo`: an import
  error of ours keeps blowing up, and without PyGObject the output is a two-line
  message instead of a traceback.

What the `git+…` installs is the commit, not the working tree — finding that out
cost a round failing with the old HEAD. `install.sh` wraps the rest (distro deps,
the `python3` that imports `gi` and `cairo`, pipx, `--selftest`), and the
authenticated pipe is `gh api …/contents/install.sh | bash` because a private
repository makes `raw.githubusercontent` answer 404.

pipx pitfalls (the venv is born with the python of pipx itself; `--force` and
`reinstall` ignore `--python`) and the two shell bugs of `install.sh` are in
[DEBUG.md](DEBUG.md).

Verified by the wheel (package + `entry_points.txt` + LICENSE, without `core/`),
`python3 -m tortty_python --selftest` and `-h` without `gi`, an isolated venv showing the
`gi` message, and `pipx install --system-site-packages` from the repository
opening and closing the window with `--quit-after 2`.

### P28 — Mouse selection: 1-char click and anchor in the scroll (2026-10-29)

Two symptoms with the same root: the selection lived in **screen** coordinates
(`y` of `visible_rows()`), not content ones.

1. Clicking a cell (without dragging) created `sel_start = sel_end` and the
   release copied that to PRIMARY — any click overwrote the user's selection with
   1 character and ruined the "paste with the middle button".
2. Scrolling the scrollback kept the highlight on the same physical line, now
   over **other** text; the following `copy()` used the new `view_off` and copied
   the wrong text.

Fix (option B, decided in the item): `scroll_view()` undoes the selection when
`view_off` changes — and the automatic adjustment of `view_off` in `on_pty` (new
output with the scrollback open) does the same. The selection started to be born
on the **drag**: `on_button_press` only stores the cell and the pixel of the
press, and `clear_selection()` clears the previous one; `on_motion` creates the
anchor when the pointer moves more than `DRAG_SLOP = 3` px; `on_button_release`
copies to PRIMARY **only** when there was a drag to another cell. Selecting the
scrollback with the mouse became impossible (the press calls `back_to_live()`) —
an accepted consequence of option B.

Bug along the way: the first version had no drag slack. Holding the button
without moving closed a 1-cell selection, because Gtk delivers `motion` with the
button pressed on any tiny shake. It was the user who saw it, testing by hand.
The slack is measured in **pixels** (3), not cells: `cell_at` already rounds, and
1 cell is too wide (14 px) to separate click from drag.

Verification: manual, with display — click-hold-release on `cat -v` (no reverse on
screen, `xclip -o -selection primary` unchanged), short drag (selection + PRIMARY),
wheel with a live selection (highlight goes away) and a new drag after the wheel
(selects the right text). Pure `selection_text` stays covered in `checks.py`. The
battery does not cover the view state (it needs Gtk).

Option B was undone by B17 (bug 17): the selection became anchored in the content,
so scrolling no longer undoes the highlight.

### P29 — `Alt` did not prefix `ESC` on special keys (2026-10-29)

`Alt+Backspace` deleted **1 character** instead of a word in `zsh`, and the same
applied to `Alt+Tab`, `Alt+arrows`, `Alt+Home/End`, `Alt+F1..F12` and
`Ctrl+Alt+letter`. Cause: in `encode_key()` the `kv in SIMPLE` branch returned the
sequence **without looking at `alt`** — the `ESC` prefix only existed in the
branch of printables and dead keys.

Generic fix, in the xterm format (not an `if` for Backspace):

- control keys (`\r`, `\x7f`, `\t`, ESC) get the `ESC` prefix when there is
  `Alt` — `Alt+Backspace` = `\x1b\x7f` (`^[^?`, zsh's `backward-kill-word`);
- keys that are already CSI/SS3 take the modifier as a **parameter**
  (`\e[1;3A` on `Alt+Up`, `\e[3;3~` on `Alt+Delete`, `\e[15;3~` on
  `Alt+F5`, `\e[1;3P` on `Alt+F1`), with `_mod_param` = 1 + shift(1) +
  alt(2) + ctrl(4);
- `Ctrl+Alt+letter` = `ESC` + the control character;
- preserved: `Shift+Tab` = `\e[Z` (with Alt it becomes `\e[1;3Z`) and DECCKM
  (`\eOA` stays for arrow without modifier, `\e[1;3A` with Alt);
- `Ctrl+Backspace` (without Alt) stays `\x7f`: only `Alt` prefixes `ESC` on the
  control keys.

Verification: table of 16 cases (`Alt+Backspace`, `Backspace`, `Ctrl+Backspace`,
`Alt+Tab`, `Shift+Tab`, `Alt+Shift+Tab`, `Alt+Up`, `Ctrl+Up`, `Up`,
`Alt+Delete`, `Alt+F1`, `Alt+F5`, `Ctrl+Alt+a`, `Alt+a`, `Alt+Escape`,
`Alt+Return`) checked against the xterm expectation, and `Alt+Backspace` tested
in the app by the user (it worked). `keys.py` stays out of `--selftest` for
depending on the Gdk constants; the table was checked by hand with `gi` and did
not become a check.

X11 quirk recorded along the way: injecting keys with `xdotool key alt+F1` is a
pitfall — on MATE that is the shortcut of the **panel menu**, and without focus
on the right window the key opens a system menu instead of testing the app.
Manual keyboard test: `tools/xtest.py key ...` (it fixes the focus by
`_NET_WM_PID`) and avoid the `Mod1` combinations that the WM uses.

### P19 — `pi` "rewrote several screens" during the turn (2026-10-29)

Symptom: every few steps of the turn inside `pi`, the screen jumped several
screens. **It was not the parser.** Three real turns replayed in `Term` and in
`pyte`: identical final screen, equal scrolls (32×32, 79×79) and correct lazy
wrap (a line of exactly 137 columns + `\r\r\n` consumes 1 line, not 2) — `pi`
does not use DECSTBM (`CSI r`), IL/DL (`CSI L/M`), SU/SD (`CSI S/T`) nor
autowrap-off (`?7l`).

What the stream has (1163 scroll entries, 12 MB preserved in
`~/dados/temp/p19-evidence-2026-10-29/`): ~10 thousand repaints, **each one inside
a `?2026` transaction** (synchronized output), and **99% of the pty reads end in
the middle of a transaction** (19058 of 19182 reads of 4095 B). Since the app
ignored `?2026`, every drawing fell with the screen half-repainted: the scroll
existed for real (`pi` goes up 4 lines with `CSI 4A` and writes ~13 per repaint,
ending each one with `\r\r\n`), but nobody was supposed to see the path.

Done:

- `?2026` honored — `Term.sync_output` and the drawing postponed until the
  transaction closes, with a cap of 200 ms for an app that forgets to close (the
  screen does not freeze; the partial state is drawn once);
- two answer errors found in the comparison with kitty: DA2 (`CSI > c`) answered
  in the **DA1** format (`\e[?62c`), leaving the app not knowing who it was
  talking to; and DECRQM (`CSI ? Ps $ p`) was not answered because the parser
  discarded the intermediate — now it answers 1/2/0 for the modes that exist
  (including `?2026`).

Verification: drawings in the middle of a transaction fell from "practically all"
to **0** (app instrumented from outside, generator of 120 repaints: 91 drawings, 0
in the middle, 0 cap overflow); doom-fire throughput intact (112 fps full, 161
NODRAW, 512 IO); suite 19 checks + 19 pytest OK. In real use the filling of 1000
lines on startup stopped "going up in pieces" (checked by the user, already with
the new build — PID started after commit `f918dbe`).

If the jump comes back, the account belongs to `pi`: it writes more lines than it
goes up in each repaint, so the scroll happens in any faithful terminal (`pyte`
scrolls the same). The next suspect is a footer widget changing height in the
middle of the turn.

### P32 — The scrollback did not hold whoever was reading (2026-10-29)

Symptom: reading the scrollback while `pi` wrote slowly, the view went back to the
footer on its own on every line.

Cause: `view.py` went back to live in three cases — key, scrolling to the end and
"any output that changes the content of the visible screen". The third was born in
bug 14 for the 1 Hz tick of `pi` and started charging the price in normal use: the
account by offset and scrollback held the position, but the `if` of the signature
ran before.

Fix: absolute anchor, without content heuristic. `Term.anchored_view_off` measures
the distance between the line that was on top and the end, and the user only
leaves the scrollback by his own action: scrolling to the end, a real key, or the
anchor being destroyed (clearing with `CSI 3J`). Out goes `_view_signature()`,
which built a string of all visible cells on every chunk exactly while one was
reading; for free, the anchor also covers the 1 Hz tick, the 1000-line cap and the
selection.

Discarded: return after 5 s of scroll inactivity (reading is silent, and an app
that writes every 1 s yanks the user when the deadline expires) and sticky bottom
(going back to ≤1 line from the end); both in LIMITATIONS.md.

Verified: check `scroll_anchor` without display, including the cap case with the
10-line drift; in the real app, scrolling 25 lines with the generator writing
slowly kept the same line on top and the selection live, the tick did not move the
offset and a key went back to live (confirmed in use).

### P34 — Configuration v2: the eight common options (2026-10-31)

v1 (P33) already had parse, merge, validation, reload and toast; here came the
keys and the use of each one: `font_family` (Monospace), `font_size` (12 points,
it was 13 fixed in the code), `cursor_shape`, `cursor_blink` (off), `scrollback`
(1000), `window_padding_width` (0), `bell` (none/visual/audible — BEL was
ignored) and `copy_on_select` (off). What is hot (font, padding, cursor) applies
to the open tabs; `shell` only on the next one.

- Blink is a `GLib.timeout_add(530)` that invalidates only the cursor cell, and
  only in the visible view (unmap removes the timer, map hooks it up again): N
  tabs, 1 timer. Two whole draws per second would be expensive and the dirty-rect
  is P27.
- `DECSCUSR` (`CSI 6 q`) wins over the config while it lasts, as in kitty.
- Padding is a translation in the draw, and the sub-cell remainder subtracts
  `2*padding` — without that the last column painted over the margin.
- Two implementation pitfalls stayed in the [DEBUG.md](DEBUG.md): `queue_resize`
  that does not re-allocate with the new font and `lista[-0:]`, which is the whole
  list.

Error became per line, reviewed the same day on request: the initial load applies
what validated (the invalid key stays at the default) and a toast shows the first
error with `(+N)`; the reload stays all-or-nothing and keeps the configuration
that was in effect. The toast only shows up when there is an error.

The toast was designed separately, over a disposable GTK mock (already deleted),
not in the app: pill (radius 14), padding of half the font height measured on the
first show, 4 px accent bar on the left, 1 px border with shadow, title in white
and detail in `#dddddd`, entrance by slide from below. Three shades per severity
(ok/warning/error, each with its bar and border) — the yellow was born from a
repeated key, which before vanished in silence. Duration 3 s on ok and 10 s on the
others, click dismisses, a new toast waits its turn, and on a config error the
click opens the file.

Bugs along the way: the `bell` flash only covered the whole tab after moving the
padding from the `tab` node to the label — and `background-color` alone did not
paint without `background-image: none`. Both are GTK3 pitfalls, in
[DEBUG.md](DEBUG.md).

Verified by the `config_options` and `scrollback_and_bell` checks and by hand: 12
points gives cell 13×27 and 75×22, changing the family re-measured (13×26, 75×23),
padding 20 checked pixel by pixel with the mouse hitting the column, the three
cursor shapes and the blink by capture, `copy_on_select` on the CLIPBOARD and
`scrollback 5` leaving 5 lines.

### P35 — Introspection socket for the agent (2026-11-01)

The agent talked to the app through three bad paths: `PYTERM_*` (only at startup
and it changes the behavior), file (`--dump-to` only on exit, and `/tmp` disputed
between the user session and the test one) and `tools/xtest.py` (needs display,
injects into the real X, has already frozen the desktop with an implicit grab).

Done: `--debug-socket FILE` — Unix socket with line-based JSON, served on the UI
thread (`GLib.io_add_watch`, no new thread), `auto` =
`$XDG_RUNTIME_DIR/tortty-python-<pid>.sock`, file at `0600` and only the same uid connects
(`SO_PEERCRED`); an orphan socket from a dead app is removed at boot. On opening,
a security warning toast shows the socket path (whoever opened it has to know the
door is up). Verbs: `state`
(including `view_off`, `pin`, `sync` and `scrolled`, which the `SIGUSR1` dump does
not show), `text` (`view` = what the screen shows, `screen` = live grid,
`history` = scrollback by absolute line), `write` (raw bytes into the pty), `log`
(turns the `debug_log` on/off at runtime) and `quit`. Off by default, command line
only, no contract to keep.

Discarded: TCP (open port and port discovery with no gain) and HTTP
(framing, headers and status to send one line of JSON).

Verified in a private display: after `write` of `seq 1 200`, `state` returned
`scrolled`/`scrollback` 173 and `history 0` brought the first command; several
requests on the same connection answered in order; `quit` closed the app and
deleted the file; an orphan socket was gone at boot; an invalid request returns
`{"ok": false}` instead of bringing it down. Check `debug_socket` covers the
dispatch with a fake target, without display or socket.

### P36 — Introspection socket: metrics, `prof`, `resize` and `keys` (2026-11-01)

Extension of P35 to take from the environment and from the X what still demanded
a restart or `tools/xtest.py`:

- `state` got the grid metrics (`advance`, `cell`, `dpi`, `padding`,
  `font`, `font_size`) and the `PYTERM_DIAG` probe went away; the advance × cell
  pair from bug 13 became a query at any moment, including after changing the
  font. `PYTERM_CONFLOG` also went away: `config` and `errors` are already in the
  `state`.
- `prof` verb: turns on the cost measurement at runtime and returns the
  accumulated values (pty, draw, bytes, eagain) — before, only the picture at exit
  with `PYTERM_PROF`.
- `resize COLSxROWS` verb: resizes the **window** and lets the normal path happen
  (allocation → `TIOCSWINSZ`/`SIGWINCH`), so reflow and lazy allocation of a hidden
  page no longer demand a WM.
- `keys` verb: key through the app path (window shortcut → encoder), with
  modifiers; `PgUp`/`PgDn`/`Esc`/`Enter`/`Del`/`BS`/`Ins` as aliases
  because the X keysym does not know them (`PgUp` becomes `Page_Up`).

Verified in a private display: `resize` 80x29 → `state` 100x34 in the next cycle;
`shift+PgUp` took `view_off` from 0 to 28 and `shift+Home` to 273 (top);
`ctrl+shift+n`/`ctrl+shift+t`/`ctrl+shift+w` created and closed tab and workspace;
`keys` `a` and `Return` reached the child; an invalid key name answers an error.
Check `debug_socket` covers `parse_key` (aliases, invalid modifier, empty key) and
the new verbs with a fake target.

### P27 — Drawing: per-line damage instead of the full redraw (2026-11-01)

Changing **one** character cost the same as repainting the screen: `on_pty` called
`request_draw` → `queue_draw()` (whole widget) and the `_on_draw` loop swept the 18
lines and the ~1100 runs every time. Measured in the app, 61x18: 13.5 ms per
character of the spinner, equal to the full frame.

Done: the `Term` marks damage — `dirty` (lines with a written cell) and `dirty_all`
(scroll, resize, reflow, RIS, buffer switch, ED) — and `take_damage()` returns the
lines or `None` for "everything". The view swaps `queue_draw()` for
`queue_draw_area()` of the dirty lines (neighbors coalesced into one rectangle) and
the draw loop filters by `cr.clip_extents()`: a line outside the clip is not swept
and a run outside the clip is not even drawn.

Discarded with a number: line cache in surface and dirty-rect per pixmap. In the
microbench `tools/uploadbench.py` (synthetic frame of 1098 cells), a frame in
ImageSurface + 1 `paint` costs 5.6 ms against 4.0 ms of the direct drawing (0.72x),
and a server surface costs 42.6 ms (0.10x) — drawing into a small pixmap comes out
~10x more expensive than in the window; composing the pixmap once it is done costs
0.38 ms, but then the app does not even draw.

Verified: the spinner falls from 13.5 to ~1.0 ms (one line, one run, measured with
the `prof` verb); full-screen doom-fire stays the same (13.45 → 13.75 ms, total
damage every frame); pixel diff after changing one character shows 12x15 px
changed, only the cell. Check `draw_damage` covers the lines per path (write, EL,
ED, ICH/DCH/ECH, scroll, resize, RIS).

### P37 — Drawing: cut Python work and group by operation type (2026-11-01)

The Python pruning of the loop yielded little: `bg_def` hoisted (it was
`cell_rgb_f(DEF_BG)` per run), char of the single-cell run taken from the unpack
instead of slice+join, list comp in the `join`, two layout tables (normal/bold)
instead of a tuple key and clip bounds as whole line/column. Measured in the
doom-fire at 61x18: 13.45 → 13.17 ms, ~2%. The 25% estimate came from `cProfile`,
which inflates cost per Python call — the pitfall was already in BENCHMARKS and was
reconfirmed.

What was worth it was what the measurement showed instead: in the worst case the
cost is not Python, it is **alternating `fill` and glyph**. Suppressing only the
backgrounds: 13.03 → 3.03 ms; suppressing only the `show_layout_line`: 13.03 →
2.61 ms; the two together do not add up (2.9 ms) — what is expensive is the X state
change on every run.

Done: the loop builds the runs of the line and draws in **two passes per frame** —
all the backgrounds, then all the text (and underline). Doom-fire: 13.0 → 7.9 ms;
realistic text scene (18 lines, 8 colors, default background) 1.05 → 0.93 ms; the
single-character spinner 1.07 → 0.81 ms.

Verified with the same probe in both versions: 480 cells with identical background
and the same amount of ink (glyph pixels); difference only in antialiasing, within
the noise that the same version already has between runs (the layout sits in a
cache created with the font options of the first draw, and the socket toast
interferes with captures — use a screen without a toast when comparing).

### P40 — SGR italic and underline styles (2026-11-08)

`3`/`23` (italic from the real face, through Pango) and `4`/`4:n`/`21`/`24`
(single, double, curly, dotted, dashed). `flags` gained bit `ITALIC` and the
style in three bits, so the run grouping keeps working with one comparison;
the underline is drawn per run, at run width, in cairo (`set_dash` for the
dotted and dashed ones). Pango cache went from 2 to 4 slots (bold × italic).

`4:n` is preserved as a tuple during the SGR parse: the old sub-parameter
flattening turned `4:3` into `4;3`, which would read as "underline + italic".
Check `sgr_italic_and_underline_styles` covers exactly that.

### P41 — Double click picks the word, triple the logical line (2026-11-08)

`Term.word_span` stops at white space only, so a whole path comes out on double
click, and a click on a space run selects the run. `Term.logical_line_span`
walks the soft-wrap flags up and down to glue the line back and trims the
trailing space. The pick already goes to PRIMARY and to CLIPBOARD
(`copy_on_select`).

Bug found while verifying with a real window: a double click behaved as a
triple. `Clipboard.store()` runs a nested X loop and the **same press** comes
back to the widget (same time, same coordinate), so the click counter saw three
events out of two clicks; a repeated press is now discarded before the counting.

### P42 — Scrollbar over the last column (2026-11-08)

8 px over the grid, only while there is scrollback, translucent track (10%) and
thumb (55%) so the text underneath still reads. Click on the track jumps,
dragging walks the history; the hit test comes before the mouse report, so it
works inside `mc` and `vim`. Hidden in alt-screen: there is nothing to scroll,
and the bar would invite a click that does nothing. Verified with the socket
verb `state`: click went `view_off` 0 → 28 (the maximum) and a drag held 21 of
28 while the button was down.

### P43 — OSC 8 hyperlinks (2026-11-08)

`8;params;URI` with the URI interned in a table: the cell carries an int in a
lazy **fifth field that only exists on linked cells**, so the hot path did not
change (measured: 9.1/8.9 MB/s before, 9.0/8.8 MB/s after, within the noise).
`Ctrl` underlines every link on screen (169 px changed on a line with links, by
pixel diff); `Ctrl+click` hands the URI to `xdg-open` through the whitelist
`http`/`https`/`file`/`ftp`/`mailto` — verified with a fake `xdg-open` in the
`PATH`, which recorded the URL, and `javascript:`/`data:` are refused by check.

### P44 — Notifications `OSC 9` / `OSC 777` (2026-11-08)

The core only counts and keeps the text (`notifs`, `notif_text`, cap
`NOTIF_MAX`); the window decides, like it already did for the BEL: a
notification on the front tab is an 8 s toast, on a background tab it is a
**badge that has no timer** (class `notif` on the tab label) and a `•` on the
workspace card, plus `set_urgency_hint` on every one of them. Visiting the tab
acknowledges it. `9;4;state[;%]` (the mintty/ConEmu progress bar) is swallowed:
a busy TUI repeats it at 1 Hz and would pin the toast forever.

Verified with a real window: notification on a background tab gave
`notif_pending` 1, closing the tab in front (the other one becomes current)
gave 0 with `notifs` 1.

### P45 — `ligatures` in the configuration (2026-11-08)

Key `ligatures` with `off`/`standard`/`all` (default `standard`), mapped to a
Pango `font-features` attribute — `liga=0,calt=0`, `liga=1,calt=1` and
`liga=1,calt=1,dlig=1`. The attribute goes on the run, not on the font
description, so script shaping (Arabic, Devanagari) keeps working whatever the
value; the layout cache is already keyed by (bold, italic) and is reset by
`apply_config`, so the mode change lands without restarting. Verified with a
window and a real capture: `a -> b != c fi ffl` draws with `ligatures all`.

### P46 — Pixel mouse protocol (`?1016`) (2026-11-08)

`?1016` tracked as a mode (answered by `DECRQM`). It is the SGR shape with the
coordinates in pixels, and it decides the shape by itself: there is no legacy
pixel protocol to fall back to. `mouse.encode` gained `pixels=`, `report_mouse`
converts the event position (minus the padding) when the app asked for it, and
the cell path did not change.

### P47 — `OSC 7`: the shell's cwd (2026-11-08)

`file://host/path`, `%XX` decoded, control chars out; a payload outside the form
does not erase a known cwd and an empty one clears it. The tab label already
fell back to the spawn directory; now it follows the shell: the view polls
`term.cwd` in the same place it already polls the bell, so `cd` moves the label
and the window title. Verified with a window: `OSC 7` to `/tmp` made WM_NAME
read `tmp`. It is the fallback for `current_cwd` when `/proc` has no answer.

### P48 — Touchpad wheel and wheel over the tab bar/sidebar (2026-11-08)

`SCROLL_SMOOTH` arrived with `btn is None` and moved nothing — blocker 2 of
[PORTABILITY.md](PORTABILITY.md), which this closes. `mouse.Notches` accumulates
the travel until a detent completes and drops the remainder on a direction
change (pure, so `checks.py` covers it); a discrete detent resets the fraction,
so a mouse step is never eaten by what the touchpad left pending. The wheel over
the tab bar cycles from the **active** tab (the whole bar is one target, not the
label under the pointer) and wraps; over the sidebar it walks one workspace card
per detent. Verified on a window with XTest: tabs 3→2→1→3, workspaces 2→1 and
back, and the grid wheel still 6 lines per detent pair.

### P49 — Configurable palette (2026-11-08)

19 keys (`foreground`, `background`, `cursor_color`, `color0..15`,
`#RGB`/`#RRGGBB`) with a `Theme` per `Term`: the configuration seeds the base,
`OSC 4` redefines an entry **of that tab** (0..15, like the Rust), `OSC 10/11/12`
set foreground/background/cursor and `104`/`110`/`111`/`112` go back to the
configured value (the configuration IS the default here; the Rust resets to the
built-in one). The bug of the day was in the parse: the comment rule ate the
value — `foreground #d6d6d6` came out as "key with empty value", because a `#`
after a space comments out the rest of the line. The fix is the Rust
`value_of`: a `#` that OPENS the value is the value. The float cache moved from
the module (`cell_rgb_f`, deleted) into the `Theme` — a tab with a custom color
cannot serve another. The embedded file now repeats the palette.py values, and
`palette_config` fails if the two sides ever diverge. Verified with a window:
config background (566,988 px), `OSC 4` on color0 (3,800 px of the new color)
and `OSC 11` (573,096 px) in the capture.

### P50 — Session restore (2026-11-08)

`restore_state` (`none`/`layout`, the default): the workspaces with their
names, the tabs in order, the cwd of each shell (`/proc` → `OSC 7`, else None =
the shell's default) and what was in front — the same `Layout` shape as the
Rust, in the same `window.json`. `state.layout()` validates on load: junk,
out-of-range indices and a cwd that no longer exists are dropped or clamped
(pure, so it lives in `checks.py`). `PYTERM_GEOM` keeps out of it both ways and
`restore_state none` erases the old layout on the next close. One tool bug
found on the way: `debug_keys` sent `hardware_keycode = 0`, so `_digit_of`
returned None and the digit shortcuts (`Alt+1..9`) leaked into the pty — the
socket now resolves a real keycode from the keyval. Verified on a window:
built 2 workspaces (/tmp, /usr, /etc and /var), quit, came back with the front
on /var; the wheel over the sidebar landed on workspace 1 at /etc; `alt+1/2/3`
walked the tabs; and both `PYTERM_GEOM` and `restore_state none` opened fresh.

### P51 — Render gate on Xvfb (2026-11-08)

`tools/render-check.sh`: 5 checks on an isolated Xvfb — the window paints
(content changed ⇒ pixel changed), `SGR 41/42` paint color1/color2 in the cell,
the text lands inside the cell the grid says, two captures of a still screen are
identical, and grid line `r` is painted in band `r`. `tools/pixel.py` grew the
scripted interface (`--expect x,y=rrggbb`, `--find`, `--diff A B --max N
[--region]`). Known trap that shaped the setup: `PYTERM_GEOM` (the measurement
protocol) is what turns the remembered geometry AND the P50 session restore
off — without it the gate would inherit the session of whoever runs it. The
still-screen check is restricted to the grid rectangle because the toast (10 s
for a warning) can expire between two captures. Proven to bite: reverting the
line painter to `y * ch * 2` (the B4 double-spacing bug) fails checks 3 and 5.

### P52 — Title stack (2026-11-08)

`CSI 22;Ps t` pushes the title, `23;Ps t` gives it back: cap of 16, an empty pop
leaves the title alone (no invention), and `Ps > 2` (the icon form) does not
touch the stack — same rules as the Rust. Nothing changed in the view: it
already polls `term.title` since P47, so the label and the window title follow
the pop by themselves. Verified with a window: `TITULO-B` pushed over
`TITULO-A`, and after `23` the state read `TITULO-A` again.

### P53 — Real tab stops (2026-11-08)

`term.tabstops` (a bool per column, seeded every 8) replaces the hardcoded
`((cx // 8) + 1) * 8` in `HT`; `HTS`/`ESC H` sets, `TBC`/`CSI g` clears one (0)
or all (3), `CHT`/`CSI I` and `CBT`/`CSI Z` walk `n` stops. The resize re-seeds
the stops instead of preserving them — the Rust does the same, and preserving
would leave stops beyond the new width. One bug of my own on the way: the reseed
was first written in `_resize_crop` (the alt-screen path only), so the main
buffer kept the old list and `len(tabstops) != cols` after a resize; the check
`t.tabstops[3] is False` after `resize(41, 3)` caught it, and the fix moved the
reseed to `resize` itself. Verified on a window: a stop set at column 4 made
`x<TAB>y` land on index 3, and `CSI 3 g` sent the next tab to the last column.

### P54 — Strikethrough and overline (2026-11-08)

`SGR 9`/`29` and `53`/`55` are two new flag bits (`STRIKE`, `OVERLINE`, above the
underline-style bits) and the run carries `fl & DECO_BITS` (underline + style +
strike + overline) into a single `_deco` call: overline on the top edge, strike
at `y0 + round(h/2)`, then the underline by style. Verified by pixels, not by
eye: the struck run shows a continuous 88 px band at half height, and the sixth
check of `tools/render-check.sh` (added here) fails when the line is drawn
anywhere else — proven by moving it to `y0 + 1` and watching `4 < 68`.

### P55 — SU/SD and a real `RI` (2026-11-08)

`CSI S`/`CSI T` roll the screen by `n` without touching the cursor, and
`ESC M` (RI) at the top of the region now scrolls the region down instead of
only moving the cursor up — that gap was there before, the Rust `reverse_index`
calls `scroll_down`. `scroll_down` is new; `scroll_up` already existed.

### P56 — `REP`, `DECKPAM`/`DECKPNM` and `?66` (2026-11-08)

`REP` (`CSI b`) repeats the last printed character (`last_char`, set by both
`put` and the `_put_run` fast path; space is the ECMA default before the first
one). `ESC =` / `ESC >` flip a single `keypad_app` bool, answered by `?66` in
the `DECRQM` reply — the bytes of the keypad keys do not change, which is the
Rust decision written down in `keypad_app`. Verified on a window: `=` +
`CSI 5 b` printed six of them, and after `ESC =` a `CSI ?66 $p` came back
`ESC[?66;1$y` on the screen.

### P33 — Configuration: parity with the Rust (2026-11-09)

The leftover was written as "the palette and shortcut remapping": the palette
landed in P49, and remapping is `M-H` in the Rust, still open there — a `map`
dialect here would be a second format for the same file, so none was invented.
What closed was the parity of the keys, read against `config.rs`: the embedded
`.conf` is the source and the in-code dict only the safety net (`DEFAULTS` →
`FALLBACK`, as a key added only to the file came back as `unknown key`); the
Rust's `defaults_parse_clean` became an assertion (zero errors, every key, same
value as `FALLBACK`, colors in); `debug_log` empty = **off** and an empty
**colour is an error**. Kept as *tuning*: `scrollback` 1000 (10000 ≈ 168 MB at
84 B/cell), the `debug_log` path default and the `shell` PATH check the Rust
lacks. `restore_state content` left LIMITATIONS (it is a feature) → queued P57.

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
7. **Black footer under an app with a colored background.** The background of
   each run was painted with height `ch` and width `(j-x)*cw`, so the sub-cell
   leftover of the window (almost never `height % ch == 0`, here 520 − 27×19 = 7
   px) kept the default background. With `vim` + `termguicolors`
   (`guibg=#123456`) that showed up as a black stripe at the bottom of the screen.
   Fix: the leftover strip inherits the background of the **last row** (and the one
   on the right, that of the last column) — measured by capture: `y=512..519`
   became `(18,52,86)`. Without a colored app nothing changes, because the last row
   has cells with the default background.
8. **`DA` never answered.** `CSI c` without parameters became `[0]` in the parser
   and the condition `not params` failed. Fix: empty body → empty list.
9. **Tabs/workspaces: six silent GTK pitfalls** — new page hidden with
   `set_current_page` ignored, `grab_focus` in `switch-page`, `sh -c` without exec
   (cwd in the grandchild), `EventBox` without a mask, `set_tab_label_text` swapping
   the label widget and `Gtk.Box` without `reorder()`. The six are in
   [DEBUG.md](DEBUG.md), with the fix.

10. **`--help` opened the window.** `parse_args` silently ignored any unknown
    option, so `bzmux.py --help` (and `--nada`) fell into the normal flow and
    brought the app up. Fix: `-h`/`--help` is handled before the Gtk import
    (prints the usage, exit 0) and an unknown option — or one without a value —
    became a usage error (usage on stderr, exit 2). `parse_args` also started
    returning the error, and the `argv_parsing` check covers both paths.

11. **Renaming the workspace left the session deaf.** The `Gtk.Entry` of the name
    is removed on confirm and takes the focus with it; nothing gave it back, so
    neither typing nor the shortcuts reached anyone. Worse: the global shortcuts
    (`Ctrl+Shift+T/N/W/Q`, `Alt+N`) only existed in the `on_key` of the `TermView`
    — it was enough for the focus to leave the session (click on the sidebar card,
    rename `Entry`, tab bar) and they stopped answering. Fix: `finish()` of the
    rename gives the focus back to the view and the window got its own
    `key-press-event` calling the same `handle_shortcut` (the view handles it
    first and returns `True`, so there is no double handling).

12. **Screen froze under continuous dump.** The pty watch was at
    `GLib.PRIORITY_DEFAULT` (0) and the GDK redraw runs at `GDK_PRIORITY_REDRAW`
    (120): with the pty always ready the read won the dispute on every iteration
    and the drawing never happened — the surface kept the last frame, forever,
    until the app stopped writing. It was seen with the doom-fire (P16): three
    captures 2 s apart, identical pixels, while the pty consumed 0.3 MB/s. Fix:
    pty watch at `PRIORITY_DEFAULT_IDLE` (200, below the redraw) and drawing
    coalesced at ~16 ms (`request_draw`, 60 Hz) — without the coalescing it was
    dozens of draws per frame and the throughput fell to 7.9 fps. Result: the
    screen animates and throughput of 0.6 MB/s (11.8 fps at 68×20, measurement
    with the cairo drawing and before bug 13).

13. **Squeezed text and wrong column after the font in points.** The cell was
    measured with the widget context (130 dpi on screen: 14×28 px) and the text
    was drawn by layouts created from the `cr`, whose context comes **without
    resolution** (96 dpi): 10 px advance per character inside cells of 14.
    Visible result: a run of N characters taking 71% of the width the grid
    reserves (space between words vanishing, box-drawing with a gap, a line of 70
    `M` ending at 700 px out of 980) and wrap seeming to fall on the wrong column,
    because the one that wraps the line is the grid (70 columns), not the drawing.
    Fix: `PangoCairo.context_set_resolution(ctx, dpi)` in **every** layout (the
    frame one and the run cache ones), with the DPI taken from the widget context
    and, if it comes out empty, from `Gdk.Screen.get_resolution()`. Measured
    after: 70 `M` taking 0..979 px, a line of 70 + 10 characters wrapping at 140
    px on the row below (10 exact cells). `PYTERM_DIAG=1` (below) was born here:
    it prints advance, cell, resolution and columns on the first draw — it is what
    separated "wrong metric" from "drawing at another resolution".

14. **Scrollback unusable inside `pi`: the view went back to the footer.** `on_pty`
    returned the view to live on *any* output ("the app is talking, the user is not
    reading the scrollback"), and `pi` publishes **every 1 second, forever**, 10
    invisible bytes: `CSI 1 G` (cursor to column 1) + `CSI ? 25 l` (hides cursor).
    Captured from an idle `pi` with its own pty answering as tortty-python (22 s, 24 ticks,
    11.4 KB, 10 bytes per second exactly). Nothing changes on screen, but each tick
    zeroed the `view_off` — scroll the scrollback and be back in 1 s. Fix: store the
    signature of what is visible (text + fg + bg per cell) before the `feed` and
    only go back to live if it changes; invisible output keeps the position (and
    the view moves along with the scrollback, so as not to slide underneath).
    Measured after, with the same 1 s tick: two captures 3.2 s apart, **0 pixel of
    difference** with the view in the scrollback (before it went back to the footer
    on the first tick); real output still brings it to live. Test pitfall:
    `tools/xtest.py` moves the real pointer of the session — do not go running it
    around on a display in use.

15. **Scrolling the scrollback got slower the further up.** Symptom reported in
    use: wheel up became progressively heavy. Cause in `Term.visible_rows(off)`:
    `scrollback[-off:] + grid[:rows - off]` — with `off > rows` the second term is
    `grid[:negative]`, which returns the **whole** grid (or empty, when the cut
    falls before the beginning), so the total came out `off + len(grid)` instead of
    `rows`. `_on_draw` iterates `len(rows)`, that is, it painted `off` lines — most
    of them off screen, but Pango and the `fill` were charged all the same. With a
    scrollback of 1000 lines and `off=1000`, 1000 lines drawn instead of 21 (~48x
    the cells). Measured in the app with `PYTERM_PROF` (both versions in the same
    load state, 3 runs each): `draw 10.72 / 10.97 / 10.99 ms/call` with the view at
    the top, against `1.67 / 1.63 / 1.65` after the fix — 6.6x. Reference of live
    (`off=0`, 443 draws): `1.41 ms`, so the top of the scrollback stopped costing
    7.7x live and started costing ~1.2x (the residue is the O(off) slicing of
    `visible_rows`, a few µs). Fix: when `off >= rows`, slice the scrollback
    directly (`sb[len(sb)-off : len(sb)-off+rows]`), otherwise the old path (which
    is correct). `visible_rows` always returns exactly `rows` lines. Regression
    check in `history()` (0, 1, rows, rows+1, the whole scrollback). Pitfall: the
    bug only shows up with `off > rows` — testing a 1-line scroll does not catch
    it. The first reading was taken with the notebook on battery (10.52 → 1.78,
    5.9x); the one above, on mains. The direction of the gain did not change.

16. **Clicking to drag in the scrollback went back to live.** Reported in use:
    scrolling up and pressing the left button to copy an old excerpt jumped to the
    footer already on the press, so the drag selected present-day text. Cause:
    `on_button_press` called `back_to_live()` **before any branch**, including on
    button 1 which only arms the local selection. Fix: the view stays where it is
    when the press arms the selection (button 1 without `mouse_mode`) and goes back
    to live only where the destination is the app — mouse report (`mouse_mode`,
    whose coordinate is from the live screen) and middle-button paste. Verified in
    the real app with captures: view at the top (`1`), press+drag → stays at the
    top and PRIMARY receives `1008` (the scrollback line under the drag); with
    `?1000` on the click goes back to live (`1183`), and the middle button too.
    Maintenance pitfall: `scroll_view` calls `clear_selection`, so `back_to_live`
    cannot reappear in `on_motion` (it would erase the drag in progress). No
    automatic check — the decision lives in a GTK handler and needs display; the
    battery does not cover `view.py`.

17. **The selection did not follow the screen scroll.** `sel_start`/`sel_end` kept
    row and column of the **screen**: scrolling (`view_off`, wheel, `Shift+PgUp`)
    moved the text and left the highlight in the same physical position, now over
    other text — and the following `copy` copied the wrong one; the mitigation of
    P28 (undoing the selection on scroll) only swapped "wrong text" for "lost
    selection". Fix: absolute anchor (`Term.CellAnchor`, line =
    `scrolled - view_off + row`), the same account as P32 — the drawing goes back to
    the screen row and the `copy` reads by the anchor, so a selection that left the
    screen keeps holding. The anchor carries the map generation (`Term.abs_gen`):
    `CSI 3J`, RIS, reflow and the alt-screen buffer switch invalidate it, the cut at
    the `scrollback` cap does not. Verified by the `selection_follows_history`
    check (both orders, output at the 1000 cap, death by `CSI 3J` and reflow) and
    with a window in a private display: highlight 3 rows below in the capture and
    `Ctrl+Shift+C` returning the right text after the wheel.

18. **RIS put the scrollback cap back to 1000.** `Term.reset` recreated the whole
    `Term` (`__init__`) and took the `scrollback_limit` along, which is
    configuration and not app state: with `scrollback 5`, an `ESC c` from the
    program started keeping 1000 lines. Fix: read the value before the `__init__`
    and put it back after. Found while reviewing bug 17 (the `reset` changed in that
    fix); the `scrollback_and_bell` check now sends `RIS` and confirms that the cap
    survives.

19. **The child `$SHELL` was not the shell that ran.** The `sh -c` of the pty
    inherits the environment of whoever opened tortty-python, so `SHELL=/usr/bin/zsh` stayed
    in the child even with `shell /bin/dash` in the configuration (and `dash` was
    the one executing). Fix: `config.effective_shell` resolves the chain empty
    config -> `$SHELL` -> `/bin/bash` and returns a path; the view exports that
    value as `SHELL` in the child. Verified in `Xvfb` with `echo $SHELL` in the
    session: empty + `$SHELL=zsh` gives zsh, `shell /bin/dash` gives dash.

20. **Scrolling the scrollback and the app repaint threw the view to the top.**
    `pi` in regular mode redraws with `?2026h` + `2J H 3J` + the whole buffer: the
    `3J` zeroed the scrollback but the scroll anchor stayed absolute, so each
    rewritten line increased `scrolled - anchor` and the clamp at
    `len(scrollback)` rested on the top of the new history. Fix: `Term.hist_gen`
    announces the clearing and the view swaps the anchor for "distance from live"
    (`Term.pinned_view_off`), holding until the distance comes back — whoever
    scrolled keeps reading, without falling to the top nor to live. Verified in the
    `redraw_keeps_history_position` check (the old path gives the top) and in the
    app: `scrollback +9` before and after the repaint.

21. **Sidebar card one tab switch behind.** `on_switch_page` updated the card (tab
    title + count) calling `update_card()`, which reads
    `notebook.get_current_page()` — and inside the `switch-page` signal the
    `Gtk.Notebook` still answers the OLD page: the card and the window title stayed
    showing the previous tab. Fix: `update_card(v)` and `sync_title(v)` receive the
    view that the signal delivers, instead of querying the notebook. Verified with a
    temporary probe on three tabs with distinct OSC titles: each `alt+N` logs the
    title of the NEW tab with `cur=` still on the old one.

22. **App repaint took whoever was reading the scrollback to the top.** With
    `?2026` open, `_on_pty` kept resolving the position against the scrollback that
    was being rewritten: on the `3J` it fell to live (`min(pin, 0) = 0`) and, when
    the pin expired, the absolute anchor escalated on every chunk up to the clamp at
    `len(scrollback)` — the top. Fix: with the region open the `view_off` is not
    written (the pin stored on the `3J` resolves in the chunk of the close, with the
    full buffer) and the wheel inside the region updates the intended distance
    instead of zeroing the pin and creating an anchor. Verified with the generator
    of 3 repaints of 3000 lines and the `debug_log` log: the region closes with the
    same `v` as the opening (15 in the generator, 114 in real use) and no `pos`
    event comes out in the middle; before, the same load ended at `v = 1000`. The
    200 ms cap keeps counting from the opening, so a longer repaint draws the middle
    of the region (1 draw in 249 ms) — which no longer moves the position.

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
