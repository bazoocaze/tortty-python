# TorTTY-Python — features

What works today. What is not done and why: [LIMITATIONS.md](LIMITATIONS.md);
pending: [BACKLOG.md](BACKLOG.md); dated record: [HISTORY.md](HISTORY.md).

- **Real pty** with a `forkpty`-equivalent (`pty.fork`), resize through
  `TIOCSWINSZ`.
- **VT parser** with ground/esc/csi/osc states, SGR (the colors and the styles
  have their own bullets below), cursor
  (`CUP`/`CUU`/`CUD`/`CUF`/`CUB`/`CNL`/`CPL`/`CHA`),
  erasing (`ED`/`EL`/`ECH`, and `CSI 3J` throws the scrollback away — in the
  main buffer; on the alternate screen it clears that screen only), line and
  character insertion/removal
  (`IL`/`DL`/`ICH`/`DCH`), scroll region (`DECSTBM`), save/restore
  (`DECSC`/`DECRC`, `CSI s`/`u`), `DECAWM`, cursor on/off (`?25`) and the
  app's own cursor shape/blink (`DECSCUSR`, `CSI Ps SP q`),
  **alt-screen** (`?1047`/`?1049`), DEC charset (`ESC ( 0`) for box drawing,
  title through `OSC 0/2`, `OSC 7` (the shell's cwd, which the tab label
  follows), `DA`/`DA2`/`CPR`/`DECRQM` replies back to the child, the cell size
  and the text area in characters (`CSI 16 t`/`18 t`, which `pi` and `nvim`
  ask for at startup),
  **drawing transaction** (`?2026`, synchronized output: the frame only goes out
  at the close of the transaction).
- **Italic and underline styles** (`3`/`23`, `4`/`4:n`/`21`/`24`): single,
  double, curly, dotted and dashed underline, drawn by style (not a fake color),
  and italic from the real face — `bat`/`diff` with italic work.
- **Strikethrough and overline** (`9`/`29`, `53`/`55`): the line crosses the
  cell at half height and the overline sits on the top edge, both in the text
  color — the struck line `git diff` and `bat` draw shows up.
- **Faint and hidden** (`2`/`8`, and `22` clears both intensities): faint draws
  halfway to the background, hidden drops the glyph — background and
  decoration stay.
- **Combining marks glue to the cell before** (`e` + acute, emoji + VS16): the
  mark joins the previous cell instead of taking one of its own, so the line
  stops shifting a column right. A per-string cache keeps the check out of the
  fast path.
- **Blink** (`5`/`6`, and `25` stops it): the cell alternates visible/hidden
  with a timer of its own that runs only while a visible cell blinks — `6`
  shares the rhythm of `5`, as xterm does.
- **Title stack** (`CSI 22 t` pushes, `23 t` gives back, cap of 16): `vim`,
  `less` and `screen` push the title on entry and pop on exit, so the tab label
  comes back to where it was instead of staying on the app's title.
- **Real tab stops** (`HTS`/`ESC H` sets, `TBC`/`CSI g` clears one or all,
  `CHT`/`CSI I` and `CBT`/`CSI Z` walk `n` of them): `HT` follows the stops
  instead of a fixed step of 8. The resize re-seeds them every 8.
- **Screen scroll** (`CSI S`/`CSI T`, SU/SD) and `REP` (`CSI b`, repeats the
  last printed character); `DECKPAM`/`DECKPNM` and the `?66` query are answered.
- **`LNM`** (`CSI 20 h`/`l`): with it a `LF` also returns to column 0, which is
  what a program that sends only `\n` expects (without it the output is a
  staircase). Answered by `DECRQM`.
- **`DECSTR`** (`CSI ! p`, soft reset): attributes, colours, cursor visible,
  `DECCKM`, keypad, origin and the scroll region go back to the defaults
  without touching the screen or the history.
- **`F13`–`F24`** arrive as `F1`–`F12` with Shift (`kf13=\E[1;2P` in xterm's
  terminfo), which is what those keys are on a PC keyboard.
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
  how you copy an old excerpt. Being **one line** from the end is live again on
  the next output (there is nothing to read there). An `↑N` in the corner shows
  how far back you went;
  the app's cursor is not drawn in the scrollback. The history belongs to the
  main buffer and **survives an app in full screen** (`mc`, `vim`, `less`):
  scrolling up after leaving it still shows what came before. A **scrollbar** of
  8 px
  sits over the last column while there is scrollback (proportional thumb,
  translucent, brighter while the pointer is over it): clicking on the track
  jumps, dragging walks the history. It does
  not exist in alt-screen (the app owns the screen; the kept history is not slid
  while it runs) and it answers before the
  mouse report, so it works inside `mc` and `vim`.
- **Keyboard**: letters (including UTF-8), arrows, Home/End, PgUp/PgDn,
  Insert/Delete, F1–F24, Ctrl+letter, Alt+letter, Shift+Tab. It respects
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
- **Shortcut table** (`map`/`unmap`, `P95`): nineteen actions bound to chords in
  the configuration file, the defaults written as `map` lines in the embedded
  file itself — `map ctrl+shift+y new_tab` re-binds, `unmap ctrl+shift+w` frees
  the key for the program. A reload applies it with no restart. Details in
  [CONFIG.md](CONFIG.md).
- **Command line over the file** (`P98`): `--font-family`, `--font-size` and
  `--scrollback` win over the configuration file and the built-in defaults, and
  `--cols`/`--rows` keep pinning the grid; a value out of range is a usage error
  (exit 2), not a silent default.
- **Configuration file** (kitty key/value, in
  `$XDG_CONFIG_HOME/tortty-python/tortty-python.conf`, always merged over the
  default embedded in the package): font family and size (points), `ligatures`,
  `cursor_shape`/`cursor_blink`, the 19 palette colors, `scrollback`,
  `window_padding_width`, `bell` (`none`/`visual`/`audible`), `copy_on_select`,
  `bold_as_bright`, `letter_spacing`, the eight chrome colors (`chrome_bg`,
  `chrome_fg` and the rest — sidebar, tabs and cards), `restore_state`, `shell`
  and `debug_log`. The keys and their ranges live in
  `tortty_python/config.py`, the default values in
  `tortty_python/data/tortty-python.conf`.
- **`Ctrl+Shift+F2` opens that file in `vim`**, in a new tab, with the window
  still open behind it. The file is watched: saving applies the configuration to
  every tab on the spot (font, padding, cursor, colors, scrollback), and a file
  that does not validate changes nothing — the toast shows the error instead.
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
  centers and positions), each chunk decoded on its own (chafa and `icat` pad
  every chunk). `kitten icat` works, including `--place` and `--scale-up`, and
  so does `chafa -f kitty`; it detects through `a=q` + `DA` + `CSI 14 t` and
  transmits in stream or compressed. An image that hangs off an edge is clipped
  as in kitty (icat scrolls it past row 0 on purpose). Erasing the cells takes
  the picture (`ED`/`EL`/`ECH`), and the alternate screen has its own set, so
  `mc`/`vim` cover the image and give it back on the way out. Images scroll along
  with the text **including into the scrollback**: `Shift+PgUp`/wheel bring the image back on the right
  line (the placement lives in the grid and may have a negative line, as in kitty)
  and they are drawn on top of the cells.
- **Image animation** (`a=f`/`a=a`, `P92`): `a=f` adds a frame to an existing
  image (`z=` is its gap), `a=a` starts it (`s=` 1 stop / 2 run / 3 loop, `v=`
  how many loops). Frames are whole bitmaps converted to ARGB32 once, and the
  view runs one lazy timer only while something is animating.
- **A picture by file or shared memory** (`t=f`/`t=t`/`t=s`, `P96`): the payload
  is a path, not pixels, so `icat --place` and anything that already has the
  bytes on disk skip the base64 round trip. `t=s` resolves to `/dev/shm/<name>`,
  `t=t` is the terminal's to delete once read, `a=q` only answers OK after the
  file was really read, and the ceiling is 32 MB. The pure layer never opens a
  file: `view.py` hands it a reader, the same shape as the `measure` hook.
- **Sixel** (`DCS P1;P2;P3;q`, `tortty_python/graphics.py`): `decode_sixel`
  reads the stream into an ARGB32 bitmap — `#` colours (RGB in %, HLS), 6-row
  bands, `!` repetition, `$`/`-`, the `"` raster for the size. The bitmap enters
  as `fmt 101`, which `view.py` hands to cairo **with no per-pixel copy** of the
  RGBA path; a pixel the stream never sets stays transparent.
- **iTerm2 inline images** (`OSC 1337;File=`, `tortty_python/graphics.py`):
  `inline=1` draws at the cursor, `width`/`height` in cells, `px` or `%` of the
  screen, `preserveAspectRatio` fills the missing side and the cursor moves down
  the rows used. The payload may be PNG, TIFF or JPEG — `GdkPixbuf` decodes it
  (`chafa -f iterm` sends TIFF), and without `width`/`height` the size comes from
  the image itself (`imgcat` sends only the `File=`). It is the same placement as
  kitty, so it scrolls, goes away with `ED`/`EL` and waits for the alt screen.
- **Bracketed paste** (`?2004`): when the app asks, `Ctrl+Shift+V`/the middle
  button send the text between `ESC[200~` and `ESC[201~` — readline/vim know it
  is a paste and do not run each line. Pasting a line copied with the mouse no
  longer gets one more `\n` at the end (that was what made the command run by
  itself).
- **Tabs** (`Gtk.Notebook`): `Ctrl+Shift+T` opens, `Ctrl+Shift+W` closes, `Alt+1`
  … `Alt+9` selects (`Alt+0` = the 10th), middle click on the label closes and
  dragging the tab reorders it — and the order you left is the order that
  counts: it is what `Alt+N`, the sidebar card and `restore_state` follow. The
  label is the app title (OSC 0/2) or,
  without OSC, the session's **cwd** — which follows `OSC 7`, so `cd` moves the
  label; a new tab inherits the current one's cwd through `/proc/<pid>/cwd` (and
  `OSC 7` when `/proc` has no answer), and each tab has its own `Term`,
  scrollback, selection and pty (`P8` became per tab: the last one closes the
  window).
- **Workspaces** (cmux-like): each with its own set of tabs, in a sidebar
  on the left that only appears with 2+ workspaces. `Ctrl+Shift+N`/`Super+N`
  creates, `Ctrl+Shift+1`…`9`/`Super+1`…`9` selects, `Ctrl+Shift+Q`/`Super+Q`
  closes the current workspace with all tabs (or middle click on the card);
  **double click** on the card renames it (empty = back to showing the title).
  `Super+Shift+Up/Down` carries the current workspace up or down that sidebar
  (`P97`), so the order you work in is the order the session keeps.
  `Super+q` on
  the last workspace quits the program. If your WM uses `Super+digit` (on GNOME
  the dash does), use the `Ctrl+Shift` variant. The card
  shows `1  <name>` or, when never renamed, `1  <title>`; below it, the active
  tab, without the count. Closing the last
  tab closes the workspace; closing the last workspace closes the program.
- **Prompt marks** (`OSC 133;A|B|C|D[;status]`, `P93`): the shell says where the
  prompt starts, where the command does and where the output does, and the marks
  live on absolute lines, so scrolling and output do not move them (capped at
  512 per tab; one whose line left the history is dropped). `Ctrl+Shift+Up/Down`
  puts the previous/next prompt on the first row.
- **Notifications** (`OSC 9`, `777;notify`): on the tab in front it is an 8 s
  toast; on a background tab it is a **badge on the label** that has no timer
  (a bell flash would be gone before anyone looked) and a `•` on the workspace
  card; visiting the tab acknowledges it. The window also asks for urgency,
  and when it is **not in front** the notice also goes to the desktop daemon
  (`org.freedesktop.Notifications`, D-Bus, silent when there is none).
  `9;4;state[;%]` (the mintty/ConEmu progress bar) becomes a prefix on the tab
  label — `50% · `, `! · ` on error, `… · ` without pct — never a toast (a busy
  TUI repeats it at 1 Hz).
- **App clipboard** (`OSC 52`): a base64 payload from the app lands in the
  system clipboard (CLIPBOARD, or PRIMARY with `p`/`s`) the way the mouse
  selection does; a query answers with an empty payload, because the content
  lives in the Gtk clipboard, not in the pure `Term`.
- **Closes when the shell ends**: `GLib.child_watch_add` reaps the child (no
  zombie) and closes the window on `Ctrl+D`/`exit`; before closing it drains what
  is left in the pty (otherwise the last screen disappears) and sends `SIGHUP` to
  the child's group (background jobs do not stay orphaned).
- **Remembered geometry**: position, size and maximized stay in
  `~/.local/state/tortty-python/window.json` (`XDG_STATE_HOME`) and come back on the next
  run. If the monitor is gone or the file is junk, the window opens at the
  default; with `PYTERM_GEOM` the measurement protocol rules (it neither restores
  nor saves). On Wayland only maximized is remembered: window position does not
  exist there. `--cols N`/`--rows N` pin the grid in columns and rows (the
  window is sized from the live cell metrics) and, like the measurement
  protocol, neither restore nor save the session.
- **One owner of the state** (`P91`): the window that opens the session holds a
  `flock` on `state.lock`, and that is the one that restores, applies the
  remembered geometry and writes. A window that finds the lock taken is a
  **scratch** window: one tab in the directory it was called from, the 980x640
  default, and it never writes. `restore_state none`, `--cmd`, `--cols`/`--rows`
  and `PYTERM_GEOM` never even try, so a probe leaves the hot session untouched.
- **Session restore** (`restore_state layout`, the default): the workspaces with
  their names, the tabs in order and the cwd of each shell come back on the next
  run, with the workspace and the tab that were in front. `restore_state none`
  starts clean; each tab is a fresh shell — the screen and the scrollback do not
  come back. `restore_state content` brings them back too: the screen of each tab
  (history included, colors and links, reflowed to the new width) is redrawn
  above a marker line and the new shell starts below it — a photograph, not a
  process. The state stays in `XDG_STATE_HOME`, and `PYTERM_GEOM` disables this
  restore too.
- **Dark chrome** (`tortty_python/style.py`): the interface colors (workspace sidebar,
  cards) come from a token table and the CSS is generated from it — with no loose
  hex in the code. The sidebar is black, the active workspace sits in a dark
  green with light text, and the contrast (>= 4.5:1) is verified by a check. The
  tab bar is also black: 1 px separates the tabs and the active one uses the same
  green as the active workspace, with the same text color in all tabs. The
  terminal cell palette is another thing and does not mix with this one.
- **Scrollback search** (`Ctrl+Shift+F`, `P94`): a bar on the grid's last row
  takes the query (`[find: query_]`), every match is highlighted in the
  foreground tone and the current one stronger, and `[ 1/3 ]` (or
  `[ no match ]`) sits on the right. `Enter`/`Shift+Enter` (or the arrows) walk
  the matches, wrapping at both ends, and the view jumps so the match lands on
  the first row. Plain text with ASCII case folding.
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
- **Block selection** (**Alt+drag**): the same columns on every row, copied one
  line each — the column of a table, dragged from any corner. A soft-wrapped
  row does not continue into the next one here: a block is cut per row, because
  the point of it is the columns.
- **A file dropped on the window** becomes its path, written into the child
  like a paste: quoted for the shell (single quotes when the path has a space,
  `$`, `*` or a quote of its own) and bracketed when the child asked for
  `?2004`. Nothing else happens — no new tab, no `cd`: the terminal does not
  know what is running.
- **Hyperlinks** (`OSC 8`): the link travels in the cell (interned URI, an extra
  field only on linked cells), and the `id=` of the parameters groups cells into
  **one** link — a link broken over two lines underlines whole. The link **under
  the pointer** is underlined (and
  with `Ctrl` held, every link on screen); `Ctrl+click` hands the URI to
  `xdg-open` — only `http`, `https`,
  `file`, `ftp` and `mailto`, since the URI comes from the child.
- **Mouse, the other encodings**: `?1015` (urxvt, `CSI b;x;yM` with the X10
  button code in decimal) and `?1005` (coordinates as UTF-8, past the 223 of the
  legacy form) beside SGR, which wins when both are on.
- **Origin mode (`?6`)**: cursor addressing relative to the scroll region and
  clamped to it (`CUP`/`VPA` relative, movement stuck inside), answered by
  `DECRQM` and cleared by the soft reset.
- **Context menu**: right click outside the app's mouse mode (terminal, tab or
  sidebar card) opens the actions the shortcuts already do — copy, paste, new
  and close tab, rename, new and close workspace.

Tested with `ls --color`, `mc` (panels, frames, key bar, colors,
arrows and resize 68x22 → 110x36 → 70x21 with no leftovers) and `vim`/`less`
(alt-screen).
