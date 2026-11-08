# TorTTY-Python

Minimal functional port of the TorTTY terminal (in Rust) to **Python**. This project is an experimental implementation created from the main TorTTY version: the goal of the Python version is to evaluate the behavior of the main version's current and future features, as well as to analyze performance.

A real terminal (pty + VT parse + grid + cairo) written in **pure Python**,
with no C and no compilation. It was born as an experiment to answer a question
— *could you build a whole terminal in Python?* — and the answer was **yes**:
it is a real application, used every day, and measurement remains the yardstick.
It is not a distributed product: no release and no support (installing on the
machine is one pipx line, in [How to run](#how-to-run)) — what is not done is in
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md). The pending backlog is in
[`docs/BACKLOG.md`](docs/BACKLOG.md); what has already been done, the fixed bugs
and the testing pitfalls are in [`docs/HISTORY.md`](docs/HISTORY.md).

## How to run

```sh
./run.sh                      # opens here, to test (errors show up right away)
./run.sh --cmd 'mc'           # initial command
./run-tests.sh                # ruff + tests, no window
uv run pytest -q              # just the pytest part
uv run ruff check .           # just the lint
uv run ruff format .          # formats (does not run in run-tests)
python3 -m bzmux --selftest   # the same checks, without depending on pytest
python3 -m bzmux --help       # options, without opening a window
python3 -m bzmux --version    # version (the same one in bzmux/__init__.py)
./bench.sh                    # measures throughput (doom-fire), ~10 s
```

## Installing on the machine (pipx, straight from GitHub)

`pybzmux` uses the system
PyGObject, so the isolated venv needs to **see** the distro's Gtk3 — that is
what `install.sh` solves (distro dependencies, the `python3` that sees
`gi`, pipx and the installation). The installed command is `pybzmux`; the name
`bzmux` stays with the Rust version of the project.

```sh
./install.sh               # from the clone: installs, verifies and says what to do
./install.sh --dry-run     # shows each command without running it
./install.sh --uninstall   # removes it through pipx
```

If `pipx` is not installed, the script uses `uvx pipx` instead of asking for
`sudo apt install` (the tool's venv is created with the system python, so
`gi` stays visible).

The installer also creates the shortcut in the system menu (`~/.local/share/applications`
+ icon under `hicolor`, respecting `XDG_DATA_HOME`): `--no-shortcut` skips that
part, and whoever installed before runs `pybzmux --install-shortcut` once. The
shortcut is `pybzmux.desktop` + `pybzmux.svg`: installing or removing the pybzmux
shortcut never touches `bzmux.desktop`/`bzmux.svg`, which belong to the Rust
bzmux. The window's `WM_CLASS` is fixed at startup (`Bzmux`), so the shortcut
finds the window both when installed and through `python3 -m bzmux`.

Without cloning — the repository is **private**, so the classic `curl | bash`
does not work yet (raw gives 404 without authentication). The authenticated
equivalent is:

```sh
gh api -H "Accept: application/vnd.github.raw" \
    /repos/bazoocaze/pybzmux/contents/install.sh | bash
```

Once the repository is public, the classic one starts to apply:

```sh
curl -fsSL https://raw.githubusercontent.com/bazoocaze/pybzmux/main/install.sh | bash
```

And the step by step by hand, which is what the script does underneath:

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0   # Linux (deb)
pipx install --system-site-packages \
    "git+ssh://git@github.com:bazoocaze/pybzmux.git"           # command `pybzmux`
pybzmux --selftest && pybzmux                                   # checks and opens
```

The repository is private, which is why the URL is `git+ssh` (it uses your key;
`https` would require a token). The version in pyproject is pinned, so a new
commit does not show up in `pipx upgrade`: to update, run the installer again
(it uses `--force`). Without `--system-site-packages` the app exits with a
message saying what to install, instead of a traceback (`pybzmux --selftest`
works anyway, without gi and without display).

`./bench.sh` prints fps, MB/s, drawing/parse cost and the CPU frequency per
stage; how to read the numbers and the protocol are in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

## Environment (uv)

The project is a uv environment (pyproject.toml + uv.lock) and **the app runs on
the venv's python**. The venv is created on top of the system python with
`--system-site-packages`: that is how it sees the distro's PyGObject (gi), which
is not installed by pip without suffering. `python-preference = system`
guarantees the same python version.

```sh
uv venv --system-site-packages   # once (uv sync does not pass this flag)
uv sync                          # pytest + ruff
uv run pytest -q                 # tests
uv run ruff check .              # lint (E, F, I, W)
uv run ruff format .             # formats
uv sync --extra tools            # + python-xlib (the tools run with python3)
./run.sh                         # app running on .venv/bin/python
```

`run.sh` picks the interpreter: `.venv/bin/python` when it imports `gi`,
otherwise the system `python3` — with a warning saying how to recreate the venv.
To run it by hand: `uv run python -m bzmux`.

## Configuration

One file in the kitty format (`key value`, `#` comments), at
`~/.config/bzmux/bzmux.conf` (or whatever `-c FILE` points to). What you do not
write comes from the default embedded in the program
(`bzmux/data/bzmux.conf`) — your file is **merged** on top of it, it does not
replace it.

```sh
./run.sh -c /tmp/my.conf      # uses another file (merge with the default)
```

The options (and the factory values):

```
shell                      # program of each new tab; empty = the environment's $SHELL
font_family Monospace      # monospaced family only
font_size 12               # in POINTS (Pango converts through the DPI)
cursor_shape block         # block, beam or underline
cursor_blink off           # on/off; an app that requests a cursor (CSI 6 q) rules
scrollback 1000            # scrollback lines
window_padding_width 0     # margin around the grid, in px
bell none                  # none, visual (marks the tab) or audible
copy_on_select off         # mouse selection already goes to the clipboard
debug_log /tmp/bzmux.debug.log  # debug JSONL log; off turns it off
```

Editing the file with the app open applies right away. Error is per line: at
startup, what is valid applies and the key with a problem stays at the default (a
10 s notice at the bottom of the window shows the first error); when saving with
the app open, any error keeps the configuration that was already in force —
nothing changes. `Ctrl+Shift+F2` opens your file in `vim`, in a new tab.

## What works

- **Real pty** with a `forkpty`-equivalent (`pty.fork`), resize through
  `TIOCSWINSZ`.
- **VT parser** with ground/esc/csi/osc states, SGR (16 colors, 256 and
  real 24-bit truecolor), cursor (`CUP`/`CUU`/`CUD`/`CUF`/`CUB`/`CNL`/`CPL`/`CHA`),
  erasing (`ED`/`EL`/`ECH`), line and character insertion/removal
  (`IL`/`DL`/`ICH`/`DCH`), scroll region (`DECSTBM`), save/restore
  (`DECSC`/`DECRC`, `CSI s`/`u`), `DECAWM`, cursor on/off (`?25`),
  **alt-screen** (`?1047`/`?1049`), DEC charset (`ESC ( 0`) for box drawing,
  title through `OSC 0/2`, `DA`/`DA2`/`CPR`/`DECRQM` replies back to the child,
  **drawing transaction** (`?2026`, synchronized output: the frame only goes out
  at the close of the transaction).
- **Scrollback** of 1000 lines in the main buffer (`scrollback` option), **with a
  scrollback view**: `Shift+PgUp`/`PgDn` (and `Shift+Home`/`End`) slide the view,
  the **wheel** scrolls the viewport — without talking to the app when it did not
  ask for mouse, and sending `64`/`65` when it did. It goes back to live on
  typing, on pasting with the middle button, on clicking when the app asked for
  mouse and on scrolling to the end — and **not** because the child wrote: the
  view stays anchored on the line being read while the app keeps writing.
  Clicking and dragging in the scrollback does **not** go back to live: that is
  how you copy an old excerpt. An `↑N` in the corner shows how far back you went;
  the app's cursor is not drawn in the scrollback.
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
- **Drawing** with cairo + Pango: runs grouped by attributes, bold,
  underline, inverse, block cursor, real shaping (connected Arabic,
  combinations) and font fallback (CJK, color emoji).
- **Kitty keyboard protocol** (`bzmux/kitty_kbd.py`): `CSI > flags u`
  (push), `CSI < n u` (pop), `CSI = flags ; mode u` (set/add/remove) and
  `CSI ? u` (query). With `disambiguate`, Esc/Enter/Tab/Backspace and
  Ctrl/Alt/Super+key come out as `CSI code ; mods u`, so `Ctrl+Shift+letter`
  stops being confused with `Ctrl+letter`; `report event types` adds
  `:1`/`:2`/`:3`; `report all keys as escape codes` sends everything as CSI-u;
  `report associated text` (`16`) appends the key's text.
- **Kitty graphics protocol** (`bzmux/graphics.py`): APC `G` with
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
  label is the app title (OSC 0/2) or, without OSC, the session's **cwd**; a new
  tab inherits the current one's cwd through `/proc/<pid>/cwd`, and each tab has
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
- **Closes when the shell ends**: `GLib.child_watch_add` reaps the child (no
  zombie) and closes the window on `Ctrl+D`/`exit`; before closing it drains what
  is left in the pty (otherwise the last screen disappears) and sends `SIGHUP` to
  the child's group (background jobs do not stay orphaned).
- **Remembered geometry**: position, size and maximized stay in
  `~/.local/state/bzmux/window.json` (`XDG_STATE_HOME`) and come back on the next
  run. If the monitor is gone or the file is junk, the window opens at the
  default; with `PYTERM_GEOM` the measurement protocol rules (it neither restores
  nor saves). On Wayland only maximized is remembered: window position does not
  exist there.
- **Dark chrome** (`bzmux/style.py`): the interface colors (workspace sidebar,
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
  drag, `?1003` movement, `?1006` SGR coordinates, `?1004` focus), and outside
  those modes it does **local selection** by dragging — and it becomes a copy:
  `Ctrl+Shift+C` copies (selection or viewport), `Ctrl+Shift+V` pastes, and the
  **middle button** pastes PRIMARY (X11 convention). The selection is reverse
  video. A click in `mc`/`vim` arrives as `CSI < b ; x ; y M/m`.

Tested with `ls --color`, `mc` (panels, frames, key bar, colors,
arrows and resize 68x22 → 110x36 → 70x21 with no leftovers) and `vim`/`less`
(alt-screen).

## Known limits

Full list, with the reason for each one and what breaks in practice, in
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md). In summary: selection only by cell
(no word/block), graphics without animation/z-index, wide character occupying
a single cell (no `wcwidth`), partial kitty keyboard protocol, no search
in the scrollback and no configurable theme/palette. They are choices — none of
them is a consequence of being Python, and the ones that annoy in use become
backlog items.

## License

**MIT** (see `LICENSE`). `pybzmux` is original code, without a line of
kitty, so its license is not dictated by the core: it only imports `pty`,
`termios`, `unicodedata`, `gi` (Gtk3, LGPL-2.1+) and `pycairo` (LGPL/MPL).
Being in the same repository does not contaminate — separate files, with no
linking or import. The C side, which stayed in the other repository, remains
GPL-3.0-only because it derives from kitty.
