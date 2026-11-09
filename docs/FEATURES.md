# TorTTY-Python — features

What works today. What is not done and why: [LIMITATIONS.md](LIMITATIONS.md);
pending: [BACKLOG.md](BACKLOG.md); dated record: [HISTORY.md](HISTORY.md).

- **Real pty** with a `forkpty`-equivalent (`pty.fork`), resize through
  `TIOCSWINSZ`.
- **VT parser** with ground/esc/csi/osc states, SGR (16 colors, 256 and
  real 24-bit truecolor, bold, italic and underline styles), cursor (`CUP`/`CUU`/`CUD`/`CUF`/`CUB`/`CNL`/`CPL`/`CHA`),
  erasing (`ED`/`EL`/`ECH`), line and character insertion/removal
  (`IL`/`DL`/`ICH`/`DCH`), scroll region (`DECSTBM`), save/restore
  (`DECSC`/`DECRC`, `CSI s`/`u`), `DECAWM`, cursor on/off (`?25`),
  **alt-screen** (`?1047`/`?1049`), DEC charset (`ESC ( 0`) for box drawing,
  title through `OSC 0/2`, `OSC 7` (the shell's cwd, which the tab label
  follows), `DA`/`DA2`/`CPR`/`DECRQM` replies back to the child,
  **drawing transaction** (`?2026`, synchronized output: the frame only goes out
  at the close of the transaction).
- **Italic and underline styles** (`3`/`23`, `4`/`4:n`/`21`/`24`): single,
  double, curly, dotted and dashed underline, drawn by style (not a fake color),
  and italic from the real face — `bat`/`diff` with italic work.
- **Scrollback** of 1000 lines in the main buffer (`scrollback` option), **with a
  scrollback view**: `Shift+PgUp`/`PgDn` (and `Shift+Home`/`End`) slide the view,
  the **wheel** scrolls the viewport — without talking to the app when it did not
  ask for mouse, and sending `64`/`65` when it did. The touchpad works too: the
  smooth travel accumulates until it completes a detent and a direction change
  drops the remainder. Over the **tab bar** the wheel cycles tabs (wrapping) and
  over the **sidebar** it walks the workspace cards. It goes back to live on
  typing, on pasting with the middle button, on clicking when the app asked for
  mouse and on scrolling to the end — and **not** because the child wrote: the
  view stays anchored on the line being read while the app keeps writing.
  Clicking and dragging in the scrollback does **not** go back to live: that is
  how you copy an old excerpt. An `↑N` in the corner shows how far back you went;
  the app's cursor is not drawn in the scrollback. A **scrollbar** of 8 px
  sits over the last column while there is scrollback (proportional thumb,
  translucent): clicking on the track jumps, dragging walks the history. It does
  not exist in alt-screen (there is nothing to scroll) and it answers before the
  mouse report, so it works inside `mc` and `vim`.
- **Keyboard**: letters (including UTF-8), arrows, Home/End, PgUp/PgDn,
  Insert/Delete, F1–F12, Ctrl+letter, Alt+letter, Shift+Tab. It respects
  **DECCKM (`?1`)**: with application mode on (which `mc`, `vim` and `less`
  do in full screen) the arrows become `\EOA`..`\EOD`, as in the xterm
  terminfo — without that `mc` ignored the arrows.
- **Only a printable character becomes a byte**: modifier and function keyvals
  stay in `0xff00-0xffff` (`Shift_L`=0xffe1, `Control_L`=0xffe3, `Alt_L`=0xffe9,
  `Super_L`=0xffeb, `Caps_Lock`=0xffe5, `Menu`=0xff67). Without that filter each
  one of those keys became a character with no glyph (the "little box" on screen).
- **Dead keys** (`´ \` ^ ~ ¨ ¸`): keeps the mark and composes with the following
  letter through NFC (`~`+`a` → `ã`); dead key + space emits the isolated
  character (`~`, `^`, `` ` ``...), the X11 convention.
- **256 colors** (`TERM=xterm-256color`): full xterm palette (16 base +
  6×6×6 cube + 24 grays).
- **24-bit truecolor** (`38;2;r;g;b`/`48;2;…`, and the form with `:`): the RGB
  stays in the cell marked in bit 24, with no allocated color table — `vim` with
  `termguicolors`, `bat`, gradients in text come out with the exact color.
- **Configurable palette** (19 keys: `foreground`, `background`,
  `cursor_color`, `color0..15`, in `#RGB`/`#RRGGBB`): the factory values are
  the classic xterm palette (mc, htop and `ls --color` were calibrated on it),
  and the file that ships with the program documents all of them. `OSC 4`
  redefines an entry **of that tab's own palette** (0..15), `OSC 10/11/12` set
  foreground, background and cursor, and `104`/`110`/`111`/`112` go back to the
  configured value.
- **Drawing** with cairo + Pango: runs grouped by attributes, bold,
  underline, inverse, block cursor, real shaping (connected Arabic,
  combinations) and font fallback (CJK, color emoji).
- **Ligatures** (`ligatures` option: off, standard, all): Pango `font-features`
  (`liga`/`calt`, plus `dlig` in `all`) applied per run, so a code font's `->`
  and `!=` come out joined while script shaping is untouched.
- **Kitty keyboard protocol** (`tortty_python/kitty_kbd.py`): `CSI > flags u`
  (push), `CSI < n u` (pop), `CSI = flags ; mode u` (set/add/remove) and
  `CSI ? u` (query). With `disambiguate`, Esc/Enter/Tab/Backspace and
  Ctrl/Alt/Super+key come out as `CSI code ; mods u`, so `Ctrl+Shift+letter`
  stops being confused with `Ctrl+letter`; `report event types` adds
  `:1`/`:2`/`:3`; `report all keys as escape codes` sends everything as CSI-u;
  `report associated text` (`16`) appends the key's text.
- **Kitty graphics protocol** (`tortty_python/graphics.py`): APC `G` with
  `a=t`/`a=T`/`a=p`/`a=d`/`a=q`, `f=24` (RGB), `f=32` (RGBA) and `f=100` (PNG),
  image in chunks (`m=1`), `i`/`c`/`r`/`C=1`/`q`, `o=z` compression (zlib) and
  the `X=`/`Y=` offsets in pixels inside the cell (that is how `icat`
  centers and positions). `kitten icat` works entirely, including
  `--place` and `--scale-up` (it detects through `a=q` + `DA`, transmits in stream or
  compressed and draws). Images scroll along with the text **including into
  the scrollback**: `Shift+PgUp`/wheel bring the image back on the right
  line (the placement lives in the grid and may have a negative line, as in kitty)
  and they are drawn on top of the cells.
- **Bracketed paste** (`?2004`): when the app asks, `Ctrl+Shift+V`/the middle
  button send the text between `ESC[200~` and `ESC[201~` — readline/vim know it
  is a paste and do not run each line. Pasting a line copied with the mouse no
  longer gets one more `\n` at the end (that was what made the command run by
  itself).
- **Tabs** (`Gtk.Notebook`): `Ctrl+Shift+T` opens, `Ctrl+Shift+W` closes, `Alt+1`
  … `Alt+9` selects (`Alt+0` = the 10th), middle click on the label closes. The
  label is the app title (OSC 0/2) or, without OSC, the session's **cwd** —
  which follows `OSC 7`, so `cd` moves the label; a new
  tab inherits the current one's cwd through `/proc/<pid>/cwd` (and `OSC 7`
  when `/proc` has no answer), and each tab has
  its own `Term`, scrollback, selection and pty (`P8` became per tab: the last
  one closes the window).
- **Workspaces** (cmux-like): each with its own set of tabs, in a sidebar
  on the left that only appears with 2+ workspaces. `Ctrl+Shift+N`/`Super+N`
  creates, `Ctrl+Shift+1`…`9`/`Super+1`…`9` selects, `Ctrl+Shift+Q`/`Super+Q`
  closes the current workspace with all tabs (or middle click on the card);
  **double click** on the card renames it (default "workspace N"). `Super+q` on
  the last workspace quits the program. If your WM uses `Super+digit` (on GNOME
  the dash does), use the `Ctrl+Shift` variant. The card
  shows `1  <name>` and, below it, the active tab and the count. Closing the last
  tab closes the workspace; closing the last workspace closes the program.
- **Notifications** (`OSC 9`, `777;notify`): on the tab in front it is an 8 s
  toast; on a background tab it is a **badge on the label** that has no timer
  (a bell flash would be gone before anyone looked) and a `•` on the workspace
  card; visiting the tab acknowledges it. The window also asks for urgency.
  `9;4;state[;%]` (the mintty/ConEmu progress bar) is swallowed — a busy TUI
  repeats it at 1 Hz and would pin the toast forever.
- **Closes when the shell ends**: `GLib.child_watch_add` reaps the child (no
  zombie) and closes the window on `Ctrl+D`/`exit`; before closing it drains what
  is left in the pty (otherwise the last screen disappears) and sends `SIGHUP` to
  the child's group (background jobs do not stay orphaned).
- **Remembered geometry**: position, size and maximized stay in
  `~/.local/state/tortty-python/window.json` (`XDG_STATE_HOME`) and come back on the next
  run. If the monitor is gone or the file is junk, the window opens at the
  default; with `PYTERM_GEOM` the measurement protocol rules (it neither restores
  nor saves). On Wayland only maximized is remembered: window position does not
  exist there.
- **Dark chrome** (`tortty_python/style.py`): the interface colors (workspace sidebar,
  cards) come from a token table and the CSS is generated from it — with no loose
  hex in the code. The sidebar is black, the active workspace sits in a dark
  green with light text, and the contrast (>= 4.5:1) is verified by a check. The
  tab bar is also black: 1 px separates the tabs and the active one uses the same
  green as the active workspace, with the same text color in all tabs. The
  terminal cell palette is another thing and does not mix with this one.
- **Reflow on resize**: lines that wrapped softly are re-wrapped at the new
  width (a long line becomes several when narrowing, goes back to one when
  widening), the cursor stays on the same character and the scrollback is
  reused. Colored bar/status background is not cut along with the white space.
- **Mouse**: reports to the app when it asks (`?1000` click, `?1002`
  drag, `?1003` movement, `?1006` SGR coordinates, `?1016` the same shape with
  pixel coordinates, `?1004` focus), and outside
  those modes it does **local selection** by dragging — and it becomes a copy:
  `Ctrl+Shift+C` copies (selection or viewport), `Ctrl+Shift+V` pastes, and the
  **middle button** pastes PRIMARY (X11 convention). The selection is reverse
  video. A click in `mc`/`vim` arrives as `CSI < b ; x ; y M/m`.
- **Click picks**: dragging selects cell by cell, **double click** selects the
  word (until white space, so a path comes out whole) and **triple click** the
  whole logical line — a line that broke softly is glued back and comes out
  without the trailing space. The pick already goes to PRIMARY (and to
  CLIPBOARD with `copy_on_select`).
- **Hyperlinks** (`OSC 8`): the link travels in the cell (interned URI, an extra
  field only on linked cells). With `Ctrl` held, every link on screen is
  underlined; `Ctrl+click` hands the URI to `xdg-open` — only `http`, `https`,
  `file`, `ftp` and `mailto`, since the URI comes from the child.

Tested with `ls --color`, `mc` (panels, frames, key bar, colors,
arrows and resize 68x22 → 110x36 → 70x21 with no leftovers) and `vim`/`less`
(alt-screen).
