# TorTTY-Python — development: tooling, verification and pitfalls

Operational manual: read the first section before running any tool in the
graphical session.

Directives: title, item, `code`, fence for a command sequence. One item = one
pitfall (symptom + how to avoid it). Bold only in "Real session". Backtick only
when truly relevant. No table, italics, date or measurement number.

## Real session: what can hang everything

- **`tools/xtest.py` injects into the X in use:** real pointer and buttons
  (XTest). Every `ButtonPress` opens an implicit grab that only closes on
  `ButtonRelease`: dying between the two leaves the button pressed, the cursor
  becomes the one of whoever holds the grab and the desktop looks hung. `drag`
  (press + ~8 movements + release) is the worst case; `click`/`dclick`/`wheel`,
  same thing in a smaller window.
- **Unlock:** `xdotool mouseup 1` (and `2 3 4 5` if the press was another one).
  Orphan holding the grab: `pgrep -af "xtest.py|import"`, kill, repeat.
- **Rule:** xtest only with the session available and when a display is
  needed, never a routine `drag`, never without release. To automate:
  Xvfb/Xephyr (virtual pointer, nothing of the user's to hang).
- **`xdotool windowactivate` steals the person's focus.** Do not use it to
  check.
- **`import` without `-window`** puts the cursor on a crosshair and grabs the
  pointer until the selection click: another way to hang. Always
  `import -window ID`.
- **Window ID never fixed:** the app restarts and the ID changes (`Resource
  temporarily unavailable` in `import`). Resolve it on the spot: `state` from
  the socket returns the `xid`, or `tools/xtest.py id` without a socket.
- **`pkill -f tortty_python` kills your own shell** (the pattern matches the
  command line, and `tortty-python` too). Use `./tools/debug.sh --kill`, which checks
  the PID file
  against `/proc/<pid>/cmdline`.
- **`wmctrl -r 'TorTTY (Python)'` fails** when the app changes the title via OSC (mc
  does). Find the window by `_NET_WM_PID` against the runner's PID.
- **Injected `<Caps_Lock>` turns the lock on for real:** the next test comes
  out in uppercase. Turn it off with another one and check with `xset q`.

## Manual test tooling

In `tools/`, with the system python3 (`python3-xlib` 0.33 and gi installed).

- `tools/xtest.py SUBCOMMAND` — `id`, `geometry`, `activate`, `move`, `click`,
  `dclick`, `wheel`, `drag`, `key`, `type`. `type` accepts
  `/ - . , ; = { } [ ] | ~ ?` and uppercase.
- `tools/pixel.py` — PNG pixel color: `tools/pixel.py shot.png 400,200`,
  `--scan X` (sample per 19 px band), `--row Y`. Checks drawing in a capture
  (`import -window`). For scripted checks it also has `--expect x,y=rrggbb`,
  `--find rrggbb` (first point with the color) and `--diff A B --max N
  [--region x,y,w,h]` (pixel count that differs; exits 1 above the maximum).
- `tools/render-check.sh` — the render gate: isolated Xvfb, fixed colors, draws
  known content, captures and compares. `--keep` keeps the captures
  in `/tmp/tortty-render`, `--display :77` picks the display. It is not part of
  `./run-tests.sh`: it needs a display. To prove the gate still bites, break the
  drawing on purpose (e.g. `y * ch * 2` in the line painter) and watch the
  cell-text and line-band checks fail.
- xdotool (`1:3.20160805`): `search --pid`, `type`, `key`,
  `mousemove --window`, `click --repeat 2`, `mouseup`. Same coordinates as
  xtest.
- `tools/ybands.py A.png B.png [--min N]` — *where* two captures differ: prints
  the `y` ranges (and each one's `x` range and pixel count). Use it instead of
  computing `row * cell height` by hand: a probe hover that lands on the wrong
  row looks like a broken feature. `--min` ignores a band whose lines have fewer
  than N differing pixels (anti-aliasing noise).
- `tools/notifyd.py FILE` — fake `org.freedesktop.Notifications` on a private
  session bus (`dbus-run-session -- ...`); writes `<summary> | <body>` per
  `Notify`. The app only calls it when the window is **not** active, so give the
  focus away first (see the pitfalls).

- A coordinate is relative to the window and the grid does not start at (0,0):
  sidebar (170 px, `SIDEBAR_W`) + tab (~28 px) put the session at `y≈58`. `y=8`
  is the tab bar — dragging there reorders the tab.
- xwininfo "Absolute upper-left" is the client origin (the one used to
  inject); `Position` from `xdotool getwindowgeometry` is the WM frame (11/40 px
  here). Confusing the two shifts every click.
- Window by `_NET_WM_PID`: take the largest visible one. GTK creates 10x10
  helpers with the same PID; the first one that shows up returns 10x10 and
  `BadMatch` in `set_input_focus`.
- `import -window root -crop` with a xwininfo geometry requires the window
  active first; otherwise it captures whatever is on top.
- `~`, `^` and `` ` `` are dead keys on ABNT2: `type '~nome'` types `~` and the
  `n` composes `ǹ` — correct behavior (NFC), not a tool failure. Literal
  tilde: a space afterwards.
- `.n  Name` and names truncated with `~` in mc are mc's (raw bytes: it writes
  `.n  Name` and truncates by panel width), not rendering's.

## Verification with a window

```
./tools/debug.sh --debug-socket auto              # log to /tmp/tortty-python.log + socket
printf '{"cmd": "text"}\n' | nc -N -U /run/user/$UID/tortty-python-*.sock  # the screen
python3 tools/xtest.py key ctrl+shift+n     # new workspace (the app consumes it)
python3 tools/xtest.py dclick 60 28         # double click on card 1
```

A test script ends with `{"cmd": "quit"}` instead of `sleep` +
`--quit-after` + `--kill`: wait for the answer that matters (`state` with
`scrolled` > 0, for example) and close. Typing text is `{"cmd": "write",
"data": "seq 1 200\r"}` — no display, focus or grab risk.

- Whoever reads the screen is `text` with `where` = `view` (what the screen
  shows, with `view_off`), `screen` (live grid) or `history` (scrollback by
  absolute line). The `SIGUSR1` dump and `--dump-to` still exist for when there
  is no socket, and they are of the LIVE grid: checking scroll by them gives a
  false negative (the offset only shows up in the `(scrollback +N)` header).
- Pixel still requires a capture: `state` returns the window `xid`, so
  `import -window $(...)` no longer depends on hunting the ID through
  `_NET_WM_PID`.
- For "does it still draw?" the answer is not a picture to look at:
  `./tools/render-check.sh` opens its own Xvfb with fixed colors and says
  PASSED/FAILED. Run it after touching the drawing code — a
  silent regression there only shows up to the eye otherwise.
- A hidden `Gtk.Notebook` page is not reallocated: it keeps the old
  `size-allocate` (sidebar open narrows 75 to 62 columns only in the visible
  one) and fixes itself when mapped (`on_resize` →
  `TIOCSWINSZ`/`SIGWINCH`). Different widths in the dump are that.
- The app runs in the uv venv (system PyGObject via `--system-site-packages`).
- Manual check of the picks and of the hyperlinks, in the app itself, without
  any tool: the line below prints an OSC 8 link with a BEL terminator. Double
  click must take one word (a path comes out whole), triple click the whole
  logical line, `Ctrl` must underline the links and `Ctrl+click` open the URI
  (put a fake `xdg-open` first in the `PATH` to see the argument instead of
  opening a browser).
  ```
  printf '\e]8;;https://example.com\e\\example\e]8;;\e\\\n'
  ```

## App probes (`PYTERM_*`)

Environment variable at run time (no code change):

- `PROF=1` — on close, parse cost (`on_pty`) and drawing cost (`on_draw`),
  bytes read and eagain.
- `NODRAW=1` — no drawing (leaves pty → grid).
- `NOPARSE=1` — reads the pty and discards it (isolates the IO).
- `GEOM=980x640` — locks the window size (otherwise the WM opens 80x24).
- `GEOMLOG=1` — every configure: client, frame and frame extents.
- `SCROLLLOG=FILE` — chunk that scrolls more than half a screen (jump/top/
  bottom/alt-screen + raw bytes).

`PROF` decomposes throughput, `NODRAW`/`NOPARSE` cut one side off. Ladder and
numbers: docs/BENCHMARKS.md. Advance × cell (the pair from HISTORY bug 13:
diverging means a grid measured at one resolution and drawn at another) comes
in the socket `state`, with `advance`, `cell`, `dpi` and `padding`; the loaded
configuration too (`config`, `errors`), in place of the old `CONFLOG`.

## Measurement (doom-fire)

- A benchmark number is compared by **grid**, not by window: the cell is font ×
  `Xft.dpi` (130 on the author's desktop, 96 without the feature), so the same
  window gives 70×21 or 98×27. Aim in cells, and the grid comes from `state`
  (`cols`, `rows`, `cell`, `dpi`).
- `--cmd` with the load measures the wrong grid: the child is born before the
  first `TIOCSWINSZ` and may see the 80×24 default. Writing the load into the
  pty after `state` confirms the target is what removes the race.
- The display enters the number: the desktop's real X (glamor) draws ~3x more
  expensively than an Xvfb on the same grid. `./tools/bench.sh --xvfb` measures on the
  virtual one.
- Geometry saved from a previous run (`window.json`, including `max`) changes
  the test grid: a throwaway `XDG_STATE_HOME` isolates it. `tools/benchrun.py`
  already does the three things.

## `?2026` log (option `debug_log`)

One JSONL line per event, with local `ts` in ms:

- `debug_log /tmp/tortty-python.debug.log` in the configuration (default); `off` turns
  it off; `--debug-log FILE` on the command line beats the configuration; reload
  applies.
- `2026` — `sync_output` transition, with `on`, `v`, `pin`, `sb`, `scr`,
  `gen`; at close it carries `ms` (region duration, `time.monotonic`).
- `draw` — drawing that escaped with the region open (`v`, `pin`, `sb`, `scr`).
- `pos` — `view_off` changed inside the region (`v0`, `v1`, `pin`, ...).
- `wheel` — wheel inside the region (`d`, `v0`, `v1`, `pin`).
- `ms > 200` with a `draw` is the ceiling doing its job, not an escaped frame;
  `pos` inside a region is what HISTORY.md bug 22 described.
- In testing, always `--debug-log /tmp/outro-nome.log`: the default file is the
  user's session one and mixing the two erases their evidence.

## Introspection socket (`--debug-socket`)

Tool for the agent, off by default: `--debug-socket FILE`, or `auto` = file with
the pid in `$XDG_RUNTIME_DIR`. File at `0600` and only the same uid connects;
when it opens, the window shows a security warning toast with the socket path.

- One JSON request per line, one JSON response per line; the same connection
  accepts several requests in a row.
- `{"cmd": "state"}` — pid, window `xid`, grid, cursor, title, `notifs`
  (`OSC 9`/`777` in the tab in front) and `notif_pending` (badges waiting for a
  visit), `view_off`,
  `pin`, `sync`, `scrolled`, `scrollback`, tabs, workspaces, configuration,
  errors, `focus` (class and name of the widget holding the keyboard focus — the
  terminal only receives keys with the focus on the view), and the grid metrics (`advance`, `cell`, `dpi`, `padding`, `font`,
  `font_size`). Note that `title` is the app's `OSC 0/2`, not the window title
  (that one is the label, `WM_NAME`).
- `{"cmd": "text", "where": "view", "start": 0, "count": 40}` — `view` is what
  the screen shows (follows `view_off`), `screen` is the live grid (what the
  `SIGUSR1` dump shows) and `history` indexes the scrollback by absolute line,
  0 = the oldest.
- `{"cmd": "write", "data": "seq 1 200\r"}` — raw bytes into the pty, as if
  typed; a key the app consumes (PgUp, shortcuts) does not reach the child
  through here.
- `{"cmd": "keys", "data": "ctrl+shift+p"}` — key through the app's path
  (shortcut, `shift+PgUp`, encoder for the child), not through the pty; accepts
  a list. X keysym name (`Page_Up`, `F2`, `Return`) plus the shortcuts `PgUp`,
  `PgDn`, `Esc`, `Enter`, `Del`, `BS`, `Ins`; modifiers `ctrl`, `shift`, `alt`,
  `super`. An unknown key is an error, not silence.
- `{"cmd": "drop", "path": "/tmp/a b.txt"}` — the same thing a file dropped on
  the window does (quoted path into the child as a paste), without needing an
  XDND source. Same function as the real drop.
- `{"cmd": "sel"}` — the selection as `{"text": ..., "block": true|false}`,
  without copying to the clipboard. `block` is the Alt+drag rectangle.
- `{"cmd": "resize", "cols": 100, "rows": 34}` — resizes the WINDOW and lets
  the normal path happen (allocation, `TIOCSWINSZ`, `SIGWINCH`); the result
  comes out in the next `state`.
- `{"cmd": "prof", "on": true}` — turns on cost measurement at run time; without
  `on` it only returns the accumulated counters (pty, draw, bytes, eagain).
- `{"cmd": "log", "value": "/tmp/x.log"}` — turns on, switches or turns off
  (`off`) `debug_log` at run time.
- `{"cmd": "quit"}` — closes the app; the destroy goes in an idle so the
  response leaves first (doing it directly closes the socket in the middle of
  the request).
- The client closes the connection, not the server: it stays open to receive
  more requests. Without `nc -N` (or `-q 0`) the command hangs waiting for the
  connection to end; client EOF ends it on the app side.
- An invalid request answers `{"ok": false, "err": ...}`; the dispatch is pure
  and the `debug_socket` check covers it with a fake target.

## Implementation pitfalls
- **The DCS head decides everything.** `DCS P1;P2;P3;q` is sixel; the body is
  buffered up to the cap and decoded at the terminator. Anything else
  (`>|XTVERSION`, `1$r...`) is spotted in the first 8 bytes (`_SIXEL_PREFIX`) and
  dropped at once, so a big non-sixel DCS costs nothing (P83). Probe:
  `chafa -f sixel IMG` must draw and leave the line below it free for the next
  text — the cursor moves below the image.
- **A new image format should pick a `fmt` that avoids the RGBA copy.**
  `surface_from_image` converts RGB/RGBA with a numpy-free Python loop
  (~1 s per megapixel), so sixel produces ARGB32 straight into `fmt 101` (P83).
- **The pure graphics layer cannot decode anything.** `graphics.py` knows only
  the PNG header, so an image with no `width`/`height` needs a pixel size from
  outside: `view.py` injects `term.graphics.measure` (P90). Keep that in mind if
  a second front end ever exists — unset means "draw nothing", not "crash".
- **OSC/APC bodies have a ceiling (16 MB) and are dropped after it** (P88). A
  probe with a 20 MB body shows the parser still healthy and the screen clean;
  if a real client ever needs more, raise `OSC_MAX` in `term.py` — do not go
  back to `str +=` (that was P89).
- **A large OSC/APC must not be built with `str +=`.** Per character it is
  O(n²): chafa at a wide window sends ~1.3 MB of base64 for one image and the
  loop froze for 25 s, with the pty full and chafa blocked writing (P89). The
  parser collects chunks in a list and joins at the terminator; the check
  `huge_osc_is_linear` compares 100 KB against 400 KB (4x linear, 16x
  quadratic), which does not depend on machine speed.
- **The inline image payload is not necessarily PNG.** `chafa -f iterm` sends
  **TIFF** (magic `II*`), and `cairo.ImageSurface.create_from_png` refuses it:
  `surface_from_image` keeps cairo for PNG and hands everything else to
  `GdkPixbuf.PixbufLoader` (P84). Probe: `python3 tools/pixel.py` over the
  capture, or `chafa -f iterm IMG` and look; the 4-quadrant PNG
  (32x14 cells, 112 px halves) proves the geometry.
- **A child reads the cell size once, at startup** (`TIOCGWINSZ`, what chafa
  uses): a fresh pty reports 0x0 px and the fallback is an 8x8 cell, so the
  picture comes out squashed. The winsize is sent right after `pty.fork` and
  `metrics()` is called before the fork, because loading the font there is what
  used to let the child read first (P87). Probe: run chafa with no `sleep` and
  measure the image width against the placement `cols * cw`.
- **The image is drawn above the text, so a stale placement survives every
  repaint.** An app that paints over without the alternate screen (`mc`) leaves
  the picture visible in each blank cell unless `ED`/`EL`/`ECH` drop the
  placements they cover (P86). Probe: `chafa -f kitty IMG; sleep 3; clear` in the
  tab must leave no picture.
- **A chunked kitty image is base64 per chunk, padding included.** chafa and
  `kitten icat` close every `m=1` chunk with `=`; decoding the joined string
  makes `binascii` stop at the first padding, the image arrives short and the
  terminal answers `EINVAL:size` (P80). Decode each chunk and add the bytes.
  `chafa -f kitty --size 60x25 IMG` inside the app is the quick probe.
- **An image may start above row 0.** `icat` places a tall image and scrolls the
  grid to make room, so the placement lands negative; the draw must clip, never
  skip on `row < 0`, or the picture disappears with the grid correct (P85).
- **`icat` asks `CSI 14 t` (text area in pixels) before anything else** and gives
  up with "Terminal does not support reporting screen sizes in pixels" if the
  answer is missing or late — on a cold start it can time out; run it again.
  `EINVAL:size` in reply to an `a=T` is the chunked-decode trap above.
- **Sixel payload on screen** means the parser lost the dcs state (P81), not
  that the decoder is missing: `chafa -f sixel IMG` draws since P83. A sixel
  that is consumed but does not draw is caught by the head sniff below.
- A click on a tab label takes the keyboard focus away from the terminal: the
  `EventBox` of the label returns `False` on button 1 so the press reaches the
  notebook's default handler (which is what lets a tab be dragged), and that
  handler grabs the focus to the `GtkNotebook` — where every key is eaten by the
  tab navigation. A single click is enough, and the symptom is a terminal that
  answers nothing until a Tab key walks the focus back (or a tab switch, through
  `_focus_idle`). The fix cannot grab the focus inside the handler, because the
  default one runs after it: `GLib.idle_add(self._focus_idle, view)`. To see it,
  ask the socket for `state.focus` before and after the click (P78).
- The drawing is in two passes (backgrounds, then text) on purpose:
  alternating `fill` and `show_layout_line` per run costs ~2x the whole frame.
  Do not "simplify" it back into a single loop. And the second pass must read
  the **row it is drawing**: the run-building pass leaves `chs`/`congelada`
  holding the last row it built, so reusing them in the text pass draws another
  line's characters — bg right, text wrong, invisible to every headless check
  and caught only by the render gate.
- Drawing damage: `Term.take_damage()` is the only source of what the view
  repaints. A new path that writes a cell without `touch(y)` (or without
  `touch_all()`, if it moves lines) does not show up on screen until something
  scrolls — the bug looks like a parse one.
- The `_on_draw` loop filters by `cr.clip_extents()`; that is what makes a
  one-character spinner cost one line instead of the frame. Removing the filter
  (or swapping `queue_draw_area` for `queue_draw`) brings back the 13 ms
  without changing a pixel.
- `Gtk.Clipboard.store()` runs a nested loop in the X server, and the **same**
  button press comes back to the widget (same `ev.time`, same coordinate). A
  click counter that trusts the events sees a double click as a triple: discard
  the repeated press before counting (`view._press_time`/`_press_xy`).
- A cell with a hyperlink has a **fifth** field (`[ch, fg, bg, flags, link]`)
  and a cell without has four: unpack `cell[0]`..`cell[3]`, never
  `a, b, c, d = cell` (that `ValueError` killed the draw as soon as a link
  appeared).

- `show_all()` undoes `set_visible(False)`: it shows every descendant and a
  widget hidden in the constructor comes back. Controlling it by hand requires
  `set_no_show_all(True)` on it.
- `io_add_watch` without a priority uses `DEFAULT` (0), above drawing: an fd
  always ready at 0 freezes the screen. `PRIORITY_DEFAULT_IDLE` (200) lets the
  redraw (120) through. Same for animation `timeout_add`.
- `background-color` alone does not paint in GTK3: if the theme puts a
  `background-image` on the node, the color is ignored. A solid background
  needs `background-image: none` (that was the bell flash "not working").
- Ligatures are not a font property here: `Pango.attr_font_features_new` goes on
  the run (`AttrList` of the layout), so it has to be reinserted whenever the
  attrs are rebuilt — putting the string in the `FontDescription` does nothing.
- Storing `OSC 7` in the `Term` moves nothing by itself: the label/title are
  only recomputed when the view notices the change, in the same poll that
  already drains the bell.
- A widget only receives scroll if its event mask has it: `SCROLL_MASK` for the
  discrete detent and `SMOOTH_SCROLL_MASK` for the touchpad (the `Gtk.Notebook`
  tab label is an `EventBox`, and it had only `BUTTON_PRESS_MASK`).
- The `#` rule in the configuration: one that **opens** the value is the value
  (`foreground #d6d6d6` is a color, not a comment); one preceded by a space
  comments out the rest of the line. It is the Rust `value_of` — a color key
  parsed as "empty value" means this rule was broken.
- The socket `keys` verb needs a real `hardware_keycode`: `_digit_of`
  (`Alt+1..9`, `Ctrl+Shift+digit`) translates the physical keycode, and 0
  comes back "not ok" — the shortcut died and the digit leaked into the pty.
  `debug_keys` resolves it from the keyval.
- The pty **echo** prints ESC as `^[` (the driver has `ECHOCTL` on), so writing
  `ESC[9m` through the socket does not apply a style on screen — only text the
  CHILD prints goes through the parser. That is why the render gate's strike
  check rides in the `--cmd` instead of a `write`. The fix for `write` probes
  is `stty -echoctl` in the `--cmd` (P67-P76 probes): the same trap also eats
  `OSC 8`/`OSC 9`, which then look "not implemented".
- Writing `\r\n` through the socket advances **two** lines: `ICRNL` turns the
  CR into LF on input and the echo turns both into CRLF. Write `\n` alone, or
  the probe's hover lands on an empty row and the feature looks broken
  (measured with `tools/ybands.py`).
- `restore_state content` (P57) feeds the photo in `TermView.__init__`, **before**
  the child exists: moving it to the first `size-allocate` (where the real grid is
  known) loses the race with the shell's prompt, which arrives through the pty
  watch first and would be buried under the restored picture. The `Term` starts
  80x24, so the photo is fed at that size and the resize reflows it — content is
  preserved (tested), only the marker's row moves.
- Without a WM (Xvfb) the window can still report `is_active()` true, so a path
  that only runs on a background window (`notify_desktop`, P74) never fires:
  give the focus away (`set_input_focus` on `PointerRoot` via Xlib) before
  testing it.
- Tab stops live in `term.tabstops` and the resize re-seeds them every 8 (the
  Rust choice). Seeding them anywhere but in `resize` leaves the main buffer
  with the old list — `len(tabstops) != cols`, and `HT` starts reading past the
  end of the line.
- The pty translates `\n` into `\r\n` on output (`ONLCR`), so a child never
  shows the difference `LNM` makes: to test it the child has to run
  `stty -onlcr` first. Without that, both cases look identical and the test
  proves nothing.
- The debug socket takes keysym names, and the keysym is `F13`/`Page_Up` while
  people type `f13`. The name is tried as given, then capitalised, titled and
  uppercased before giving up.
- `window.json` carries `layout` (P50) next to the geometry, validated on load
  (`state.layout`): hand-editing is safe — anything wrong becomes "one tab as
  always". `restore_state none` erases it on the next close and `PYTERM_GEOM`
  neither reads nor writes it.
- Verifying the wheel with `tools/xtest.py` needs the **client** coordinate: with
  2+ workspaces the sidebar pushes the notebook to x >= 170, so the tab bar is
  no longer where it was on a single workspace. Capture with
  `import -window <xid>` and find the active tab's green band before clicking.
- The `Gtk.Notebook` CSS node `tab` is not the label: a class on the label
  paints only the text and `tab:checked` rules the rest. `label.get_parent()` is
  the Notebook itself; give the label a `set_name` and handle the padding on it
  (P34).
- Page unmapping is the `Gtk.Notebook` dispatch's: the cursor blink depends on
  it (`unmap`/`map`). Swap the container and it runs on every tab again.
- A freshly attached `Gtk.Notebook` page is born hidden and `set_current_page`
  is ignored (`get_current_page()` stays on the previous one): `show_all()` on
  the page and on the label before switching.
- `get_current_page()` inside `switch-page` is still the OLD page (the notebook
  only switches after emitting the signal). Whoever updates card, title or
  label in the handler must use the signal's `page`/`page_num`, otherwise the
  screen runs one action behind.
- `grab_focus()` inside `switch-page` does not take (the page is not mapped yet,
  focus stays on the notebook): schedule with `GLib.idle_add`.
- A focus `GLib.idle_add` steals focus from a `Gtk.Entry`: check `get_focus()`
  first, otherwise the typed name goes to the terminal.
- The instrument for the scrollback surviving an app is `state.scrollback`
  through the socket: start `seq 1 300`, then `vim`/`mc`, and it must stay at
  the same number inside and after (P79). A zero there means something cleared
  the main buffer's history again — `?1049`/`CSI 3J` are the two suspects, and
  the terminal type, not the app, decides whether an app enters the alt screen.
- A photo taken while an app owns the screen (`restore_state content`, P57)
  carries the history plus the **main** screen, not what the app is drawing:
  that is the screen the app gives back on exit, so the restore shows what was
  behind `mc`/`vim`.
- `CSI 3J` erases the scrollback: the absolute scroll anchor dies with it. The
  repaint that clears rewrites the same text, so what counts is the distance
  from live (`Term.hist_gen` marks the clearing, `pinned_view_off` recounts);
  storing the absolute line makes the view jump to the top of the new history.
- `sh -c "<cmd>"` does not exec when the command has an argument: the program
  is a grandchild of the pty and `sh`'s cwd never changes. Inherit the cwd
  through the last descendant (`/proc/<pid>/task/<pid>/children`).
- The `pty.fork` child inherits the whole environment, `SHELL` included: it
  starts lying when the configured shell is another one (or when the config is
  empty and `$SHELL` decides). Export the `SHELL` that `config.tab_command`
  returns — `--cmd` changes the command, not the `SHELL`.
- `Gtk.EventBox` ignores CSS padding for sizing: the background paints, the
  widget does not grow and the text touches the border. Padding goes on the
  inner box (`Gtk.Box`), as in the current `#toast`.
- A `Gtk.EventBox` without `add_events()` has an empty mask
  (`get_events() == 0`) and the click never arrives; and
  `notebook.set_tab_label_text()` swaps the label widget (keep the `Gtk.Label`
  and change its text).
- `Gtk.Box` has no `reorder()`: it is `reorder_child(child, index)`.
- On the `Ctrl+Shift+1` shortcut the keyval arrives as `exclam`/`at`, not as
  `1` (Gdk gives the symbol): map it back or use the keyboard column.
- `queue_resize()` does not reallocate when the widget size does not change:
  with a new font `size-allocate` does not come and the grid keeps the old
  cell. Call `on_resize` directly when applying config.
- Font metrics come from the widget's Pango context (`get_pango_context()`),
  not from a loose `ImageSurface`: point→pixel uses another resolution and the
  grid misaligns.
- cairo `FORMAT_A1` measures font, but `font_extents()` returns 5 values
  (ascent, descent, height, max_x_advance, max_y_advance).
- Pending wrap: the emulator must not count the `\n` after a full line as a
  second break — text up to the last column + `\r\n` is the TUI pattern that
  draws up to the edge.
- A blank row is `[" "] * cols` plus one repeated packed value
  (`array("Q", [_BLANK_V]) * cols`), so it is cheap to make and cheap to fill:
  `row.ch[x] = ch` and `row.pk[x] = _pack(...)` always, never a mutation of a
  shared object (a mark glued onto a shared blank cell corrupted the whole grid
  once). `_bce_row()`/`_blank_cell_raw()` carry the current bg on purpose.
- `row.ch` is a **list** in the live grid and a **str** in the frozen history
  (scrollback): index, slice and `len` behave the same, but `type(row.ch)` is
  how the hot paths decide, and `frozen()` refuses a row with a multichar cell.
  New code that walks rows goes through `row_text`/`cell`/`cell_abs`.
- `lista[-0:]` is the whole list: slicing by a configurable ceiling
  (`[-limit:]`) stops cutting at limit 0. Use `del lista[:len(lista) - n]`.
- `chr(kv)` only exists for `0x20–0x7e`, `0xa0–0xff` and `0x01000000+U`; the
  rest is modifier/function.
- cairo's `create_for_data` does not copy the bytes: the image's `bytearray`
  must stay alive while the surface exists, otherwise the drawing comes out as
  garbage.
- The card's `Gtk.EventBox` has its own window and paints over the `ListBoxRow`,
  hiding the `:selected`: make it transparent in the CSS and paint the
  background on the row.
- A markup attribute (`<span foreground=...>`) beats the CSS and the label does
  not change color on selected: color goes by class, markup only with
  `<small>`.
- `row`, `row:hover` and `row:selected` must be in the CSS: without the explicit
  `:selected` the theme rules, and without `:hover` the card under the mouse
  takes the theme's light highlight.
- A gi binding call per run is expensive and cancels the gain of swapping the
  drawing call: decide at cache entry creation, never per run.
- Layout baseline comes from `get_baseline()`, not from the font ascent: with a
  CJK fallback the layout resolves another baseline and the text rises.
- Selection and scrollback anchor lives on an **absolute** line
  (`scrolled - view_off + row`), never on a screen row: screen coordinates age
  as you scroll and as output arrives. The map generation (`Term.abs_gen`)
  invalidates on reflow, on `CSI 3J` and on the alt-screen buffer switch, but
  **not** on the `scrollback` ceiling trim — there the absolute line stays the
  same (P32/B17).

## Installation (pipx and shell)

- The pipx venv is born with **pipx's own** python: `uvx pipx` installs into a
  3.12 without `gi` and `--system-site-packages` does not save it — it needs
  `--python /usr/bin/python3`. The apt pipx already uses the system one.
- `pipx install --force` and `reinstall` preserve
  `include-system-site-packages` but **ignore** `--python`: changing
  interpreter requires `uninstall` and installing again.
- `git+ssh://…` installs the **commit**, not the working tree: an uncommitted
  change does not reach the test.
- A fixed version in `pyproject` makes `pipx upgrade` miss a new commit; the
  update is `--force`.
- `[ -x python3 ]` tests a file in the cwd, not on the PATH: use `command -v`.
- A function that prints and is used as a condition leaks into stdout:
  `if func; then` gets the wrong value.

## Measurement and profiling

Governor, load and measurement protocol: docs/BENCHMARKS.md. On profiling:

- cProfile does not see `gi.FunctionInfo`: `PangoCairo.show_layout` 20,000 times
  does not show up and the time falls into the caller's self (`_on_draw` at 46%
  of "self" without Pango). A cairo object method (`fill`, `rectangle`) shows
  up; a gi module function does not. It inflates whoever makes many Python
  calls and sinks doom-fire: proportion, `perf_counter` per section; profile,
  only to know which calls exist.
- The first `on_draw` calls cost more (layout, font, context): measure `draw`
  with hundreds of calls or compare by ratio.
- Drawing depends on runs, not on cells: the same count with one color costs a
  fraction of dozens of colors per line; a uniform screen underestimates the
  worst case.
- fps depends on the grid: MB/s stays put and fps drops when the cell grows;
  comparing fps across grids says nothing.
