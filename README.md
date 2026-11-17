# TorTTY-Python

[![tests](https://github.com/bazoocaze/tortty-python/actions/workflows/tests.yml/badge.svg)](https://github.com/bazoocaze/tortty-python/actions/workflows/tests.yml)

Minimal functional port of the TorTTY terminal (in Rust) to **Python**. This project is an experimental implementation created from the main TorTTY version: the goal of the Python version is to evaluate the behavior of the main version's current and future features, as well as to analyze performance.

A real terminal (pty + VT parse + grid + cairo) written in **pure Python**,
with no C and no compilation. It was born as an experiment to answer a question
— *could you build a whole terminal in Python?* — and the answer was **yes**:
it is a real application, used every day, and measurement remains the yardstick.
It is not a supported product: no support, and the releases are snapshots of
what works (installing on the machine is one `curl | bash` line, in
[How to run](#how-to-run)) — what is not done is in
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
python3 -m tortty_python --selftest   # the same checks, without depending on pytest
python3 -m tortty_python --help       # options, without opening a window
python3 -m tortty_python --version    # version (the same one in tortty_python/__init__.py)
./tools/bench.sh              # measures throughput (doom-fire), ~10 s
```

## Installing on the machine (pipx, straight from GitHub)

`tortty-python` uses the system
PyGObject, so the isolated venv needs to **see** the distro's Gtk3 — that is
what `install.sh` navigates (the `python3` that sees `gi`, pipx and the
installation, never the distro packages themselves). The installed command is
`tortty-python`; the name `tortty` stays with the Rust version of the project.

No clone needed — the URL is stable and its content is the release's:

```sh
curl -fsSL https://github.com/bazoocaze/tortty-python/releases/latest/download/install.sh | bash
curl -fsSL https://github.com/bazoocaze/tortty-python/releases/latest/download/install.sh \
    | bash -s -- --check                          # inventory only, changes nothing
```

From a clone, the same script installs the tree you have:

```sh
./install.sh               # installs, verifies and says what to do
./install.sh --check       # what is here, what is missing
./install.sh --dry-run     # shows each command without running it
./install.sh --uninstall   # removes it through pipx
```

The script **never uses sudo**. It does the part that needs no privilege, and
when a distro package is missing (PyGObject, GTK 3) it prints the command for
the distro it detected and exits 3 — you run that one yourself, then run the
installer again. If `pipx` is not installed it uses `uvx pipx`, so nothing is
installed system-wide (the venv is created with the system python, which keeps
`gi` visible).

The installer also creates the shortcut in the system menu (`~/.local/share/applications`
+ icon under `hicolor`, respecting `XDG_DATA_HOME`): `--no-shortcut` skips that
part, and whoever installed before runs `tortty-python --install-shortcut` once. The
shortcut is `tortty-python.desktop` + `tortty-python.svg`: installing or removing
it never touches `tortty.desktop`/`tortty.svg`, which belong to the Rust
version. The window's `WM_CLASS` is fixed at startup (`tortty-python`), so the
shortcut
finds the window both when installed and through `python3 -m tortty_python`.

And the step by step by hand, which is what the script does underneath:

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0   # Linux (deb); you run this, not the script
pipx install --system-site-packages --force \
    https://github.com/bazoocaze/tortty-python/releases/latest/download/tortty-python.whl
tortty-python --selftest && tortty-python                                   # checks and opens
```

Every release publishes `tortty-python.whl`, `SHA256SUMS` and `install.sh` under
fixed names, so those URLs never change; a pin is the same path with
`/releases/download/v0.0.40/`. The installer checks the wheel against
`SHA256SUMS` before it reaches a venv.

The repository is private, which is why the URL is `git+ssh` (it uses your key;
`https` would require a token). The version in pyproject is pinned, so a new
commit does not show up in `pipx upgrade`: to update, run the installer again
(it uses `--force`). Without `--system-site-packages` the app exits with a
message saying what to install, instead of a traceback (`tortty-python --selftest`
works anyway, without gi and without display).

`./tools/bench.sh` prints fps, MB/s, drawing/parse cost and the CPU frequency per
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
To run it by hand: `uv run python -m tortty_python`.

## Configuration

One file in the kitty format (`key value`, `#` comments), at
`~/.config/tortty-python/tortty-python.conf` (or whatever `-c FILE` points to). What you do not
write comes from the default embedded in the program
(`tortty_python/data/tortty-python.conf`) — your file is **merged** on top of it, it does not
replace it.

```sh
./run.sh -c /tmp/my.conf      # uses another file (merge with the default)
```

The common options (and the factory values) — every key, range and error rule
is in [docs/CONFIG.md](docs/CONFIG.md):

```
shell                      # program of each new tab; empty = the environment's $SHELL
font_family Monospace      # monospaced family only
font_size 12               # in POINTS (Pango converts through the DPI)
ligatures standard         # off, standard (liga/calt) or all (+ discretionary)
cursor_shape block         # block, beam or underline
cursor_blink off           # on/off; an app that requests a cursor (CSI 6 q) rules
scrollback 1000            # scrollback lines
window_padding_width 0     # margin around the grid, in px
bell none                  # none, visual (marks the tab) or audible
copy_on_select off         # mouse selection already goes to the clipboard
debug_log /tmp/tortty-python.debug.log  # debug JSONL log; off turns it off
restore_state layout        # none = start clean; layout = workspaces/tabs/cwd
                            # back; content = layout + the screen of each tab
chrome_bg #000000         # chrome colors (sidebar, tabs, cards): background, hover,
chrome_fg #e0e0e0         # text, info line, accent background/text/info, separator
foreground #d6d6d6        # the 19 terminal colors (#RGB/#RRGGBB): foreground,
background #000000        # background, cursor_color and color0..color15 —
cursor_color #d6d6d6      # factory values are the classic xterm palette
color0..color15           # (all of them documented in data/tortty-python.conf)
```

Editing the file with the app open applies right away. Error is per line: at
startup, what is valid applies and the key with a problem stays at the default (a
10 s notice at the bottom of the window shows the first error); when saving with
the app open, any error keeps the configuration that was already in force —
nothing changes. `Ctrl+Shift+F2` opens your file in `vim`, in a new tab.

## Known limits

Full list, with the reason for each one and what breaks in practice, in
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md). In summary: no rectangular
selection, graphics without animation/z-index, wide character occupying a
single cell (no `wcwidth`), partial kitty keyboard protocol, no search in the
scrollback and no shortcut remapping. They are choices — none of them is
a consequence of being Python, and the ones that annoy in use become backlog
items.

## Documentation

- [docs/FEATURES.md](docs/FEATURES.md) — what works today
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md) — what is not done, and why
- [docs/BACKLOG.md](docs/BACKLOG.md) — pending items and the queue rules
- [docs/HISTORY.md](docs/HISTORY.md) — dated record: closed items and fixed bugs
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md) — the only place with measurement numbers
- [docs/DEBUG.md](docs/DEBUG.md) — operational manual: tools, verification with a window, pitfalls
- [docs/PORTABILITY.md](docs/PORTABILITY.md) — Linux/Windows/macOS study (P30)
- [AGENTS.md](AGENTS.md) — conventions, architecture, scripts (written for agents)

## License

**MIT** (see `LICENSE`). `tortty-python` is original code, without a line of
kitty, so its license is not dictated by the core: it only imports `pty`,
`termios`, `unicodedata`, `gi` (Gtk3, LGPL-2.1+) and `pycairo` (LGPL/MPL).
Being in the same repository does not contaminate — separate files, with no
linking or import. The C side, which stayed in the other repository, remains
GPL-3.0-only because it derives from kitty.
