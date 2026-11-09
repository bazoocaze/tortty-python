# TorTTY-Python

TorTTY-Python: a terminal emulator in Python. This project is an experimental implementation created from the main TorTTY version (in Rust). The goal of the Python version is to evaluate the behavior of the main version's current and future features, as well as to analyze performance.

A terminal in pure Python: pty + VT parser + grid + drawing with cairo + Pango.
It was born as an experiment to measure the cost of the hot path in Python and
became a real daily-use application: shell, mc and vim; mouse with
selection/copy, scrollback with the wheel, reflow, truecolor, kitty keyboard and
image protocols, bracketed paste, tabs and workspaces. Measurement remains the
yardstick (docs/BENCHMARKS.md); what is not done and why: docs/LIMITATIONS.md.
This file is convention; content moves elsewhere by type (see Documentation).

## Documentation

Split by content type — each fact lives in one place only, do not duplicate.
All are written for agent reading; only README.md is for humans.

- AGENTS.md (this one) — conventions, architecture, scripts, tools.
- docs/BACKLOG.md — pending backlog and the queue rules (record,
  close, where things that are not items go).
- docs/LIMITATIONS.md — what is not done and why (accepted decision/limit, not
  queue). Before implementing something "obvious", check here: it may be a
  decision.
- docs/HISTORY.md — completed backlog, fixed bugs and the git
  note: dated narrative only (the record of the day, not current reading), with
  the writing rules at the top of the file itself.
- docs/DEBUG.md — operational manual: what can hang the graphical session,
  manual test tools, verification with a window, `PYTERM_*` probes and
  implementation pitfalls (GTK/cairo/Pango/parser). **Read before running a
  tool with a display**; a new pitfall goes here, not in HISTORY.
- docs/PORTABILITY.md — study of P30 (Linux/Windows/macOS): what is
  platform today, blockers in the code, routes and cost; decision pending.
- docs/BENCHMARKS.md — benchmarks and measurement and **the only place with
  throughput/drawing/parse/footprint numbers**: the doom-fire load (headline),
  the real `dmesg`, the ladder and the decompositions, the footprint (app PSS
  and graphical stack disk), the comparison protocol and the pitfalls
  (includes the governor). The other docs cite the fact and link; they do not
  repeat values.
- docs/FEATURES.md — what works today: the feature list (the README points
  here).
- README.md — view for humans: how to run, install, environment, configuration,
  limits, measurement, license.

Each file above is indexed in one line (what it is, when to use it); the detail
lives in it, not here.

Queue rules (record, closing, where things that are not items go) are at the
top of docs/BACKLOG.md.

**A measurement number lives in one place only: docs/BENCHMARKS.md** (with date
and CPU governor). The other docs cite the fact in one sentence and link — they
do not repeat values. Repeating a number in five files only produces divergence:
each re-measurement became a hunt to find the copies. Exceptions: the README.md
keeps the doom-fire line in the comparison table (it is the headline for
humans, a pair of numbers), the HISTORY.md records the number of the day an item
was closed (dated record, never current reading) and the AGENTS.md may cite an
example value when explaining a probe.

## Architecture

The tortty_python/ package installs the `tortty-python` command and also runs as
`python -m tortty_python`; no loose file at the root. The code:

- run.sh — runs the app (quick test; picks the python)
- run-tests.sh — runs the lint and the test battery
- install.sh — installer (Linux)
- tools/debug.sh — development: background, log, --kill/--status
- tools/bench.sh — doom-fire ladder: measures on the current display and on its
  own Xvfb
- tools/benchrun.py — one rung of the ladder: locks the grid through the
  socket, types the load and prints the result
- tortty_python/__main__.py — python -m tortty_python (calls cli.run)
- tortty_python/__init__.py — facade with lazy import (tortty_python.Term does not pull Gtk)
- tortty_python/palette.py — cell [char, fg, bg, flags], xterm-256 palette (int and
  float), the per-tab Theme (P49: config colors + OSC 4/10-12), DEC charset
- tortty_python/term.py — grid, cursor, VT parser; does not know GTK
- tortty_python/keys.py — X11 keyval -> child bytes (dead keys, DECCKM)
- tortty_python/kitty_kbd.py — kitty keyboard protocol (CSI ... u)
- tortty_python/mouse.py — mouse protocol (SGR and the old one) — pure
- tortty_python/graphics.py — kitty image protocol (APC G) — pure
- tortty_python/gui.py — the only import of Gtk/Gdk/GLib/Pango/PangoCairo/cairo
- tortty_python/style.py — chrome color tokens + generated CSS + contrast (pure)
- tortty_python/view.py — TermView: one session (pty, cairo + Pango, events)
- tortty_python/window.py — Workspace + TorttyWindow (tabs, sidebar, global shortcuts)
- tortty_python/checks.py — the battery: pure asserts, no display
- tortty_python/selftest.py — dependency-free runner for --selftest
- tortty_python/cli.py — argv and startup (and the console script entry point)
- tortty_python/shortcut.py — system shortcut (.desktop + icon); pure, before gi
- tortty_python/state.py — window geometry between runs (JSON in XDG_STATE_HOME)
- tortty_python/config.py — configuration (kitty key/value); pure, merge w/ default
- tortty_python/debugsock.py — Unix introspection socket (P35): pure dispatch + GLib
  glue; only with `--debug-socket`, verbs in docs/DEBUG.md
- tortty_python/data/ — tortty-python.svg (icon) and tortty-python.conf (embedded
  default options)
- tests/ — pytest runner for tortty_python/checks.py
- tools/xtest.py, tools/pixel.py — manual test, requires X11
- tools/doomfire.py — measurement load, not a test
- tools/uploadbench.py — drawing microbench: N cairo operations against 1
  upload/composition per frame

What sustains this split: the --selftest path imports only palette, term
(which pulls graphics), kitty_kbd and mouse, and none of them pulls gi/cairo —
that is what lets the checks run without a display and without GTK (keys stays
out: it uses the Gdk keyval constants). Each tab has its own Term; the window
only orchestrates, with no session state.

Inside the two largest: term.py has feed (state machine, with a text fast path
and truecolor SGR in ground and the slow parser as fallback), put/chars,
csi_dispatch/sgr/set_mode and child_out (responses to the child, drained by the
host); view.py has spawn/on_pty (io_add_watch on the master), on_resize
(size-allocate → Term.resize + TIOCSWINSZ + SIGWINCH), on_draw, on_key,
mouse/selection and view_off; window.py has Workspace (Gtk.Notebook + sidebar
card) and TorttyWindow (Gtk.Stack + global shortcuts + dump/quit-after/SIGUSR1).

A cell is a list [char, fg, bg, flags]: fg/bg as an xterm index (0-255,
256=default fg, 257=default bg), flags bitmask (bold/underline/inverse). The
drawing groups neighboring cells of equal attributes into a single run and each
run becomes a Pango.Layout cached by (text, bold): grouping brought the uniform
frame of 1920 cells to ~2 ms, and Pango charged ~20% on a frame of 1360 cells
with 37 colors (numbers in docs/HISTORY.md, P9).

Not a goal: cloning kitty/gtkterm or deriving from their C core — nothing here
comes from them. The experiment showed that a whole terminal can be done in
Python, and that is how it is used; that is a result, not a quota: language and
graphical stack are an initial choice, revisable by requirement
(see [docs/PORTABILITY.md](docs/PORTABILITY.md)).

## Configuration

Key/value in kitty format (`#` comments). The user file is
$XDG_CONFIG_HOME/tortty-python/tortty-python.conf (the -c FILE switches it) and
is always merged over the default embedded in tortty_python/data/tortty-python.conf.

- Valid keys and ranges live in tortty_python/config.py (CHECKS); the default values,
  in tortty_python/data/tortty-python.conf. The ones that most change day to day: font_size (in
  points, not px), scrollback, cursor_shape.
- Empty `shell` (the default) inherits the environment `$SHELL`;
  `config.tab_command` decides (tab command, child `$SHELL`) and `--cmd` does
  not touch `$SHELL`.
- `debug_log` (default /tmp/tortty-python.debug.log, `off` disables it; `--debug-log
  FILE` wins over the configuration) is the JSONL log of `?2026` — events,
  fields and usage in docs/DEBUG.md.
- Editing with the app open applies immediately. Error is per line: on the
  initial load what validated holds (the toast shows the first error), on
  reload nothing changes.

## Conventions

- Version: bump the patch (`0.0.1` -> `0.0.2`) in `tortty_python/__init__.py`
  when **closing a backlog item** — the commit that closes the item carries the
  bump, not every commit. A docs, test or one-off adjustment commit does not
  bump. It is the single source: `pyproject.toml` reads from there (hatch) and
  `--version` shows it.
- Texts, descriptions and comments concise and in English.
- Filenames and symbols in the code (functions, variables, classes, constants)
  in English.
- Docstrings and comments in the code: at most one line.
- Data with named fields (NamedTuple/dataclass), not raw tuples: position
  does not say what it is, the name does.
- Format designed for agents, does not need to be pleasant for humans.
- Interface color only in tortty_python/style.py (tokens + generated CSS); no loose hex
  in the code. Terminal cell color is palette.py — do not mix the two.
- Do not update the documentation on every code iteration. When the user
  finishes an iteration, mention discreetly that the doc is pending; the
  decision to sync is theirs.
- Avoid backticks.
- Style comes from `ruff format` (line-length 88), not manual alignment; the
  lint is `ruff check` with E, F, I, W. Do not choose hand-format over the
  formatter: `./run-tests.sh` fails if the file is not formatted.
- Commits: conventional commits, maximum of 3 lines.

## Tests

- Few tests, in the most important parts: parser, protocols and everything that
  has already broken once (regression is worth more than coverage).
- No exhaustive suite: no case matrix per parameter combination, no test that
  only rewrites the code in the form of an assertion, no chasing coverage.
- One fixed bug = one check, when possible; not a battery around it.
- Areas covered today: parser, SGR/EL/ED, alt-screen and scroll, charset and
  responses (DA/CPR), CSI with intermediate, CLI, kitty keyboard, graphics,
  reflow, scrollback, mouse, selection, paste, truecolor, style contrast,
  italic and underline styles, click picks (word/logical line), hyperlinks.
- Cheap test to run: one command (./run-tests.sh), no display. The checks
  live in tortty_python/checks.py and have two runners: pytest and
  python3 -m tortty_python --selftest (no dependencies, useful to prove that the test
  path does not pull gi). What needs X11 stays as a manual command in Scripts
  and tools, it does not become infrastructure.
- tools/doomfire.py — measurement load, not a test: doom-fire in truecolor
  half-block (fg and bg per cell, worst case), with no X dependency.
  python3 tools/doomfire.py --fps 0 --frames 1200 --stats-to FILE prints fps and
  MB/s on the output, so two terminals can be compared on the same grid. Why,
  results and protocol: docs/BENCHMARKS.md. The diagnostic probes
  (`PYTERM_PROF/NODRAW/NOPARSE/GEOM/GEOMLOG/SCROLLLOG`) are in the
  docs/DEBUG.md table; the ladder with the numbers stays in docs/BENCHMARKS.md.
- tools/ is manual, not a suite: xtest.py and pixel.py need a display and are
  called by hand during verification. The test command is ./run-tests.sh.
- Measurement is not a test: the numbers come from a real run. `tools/bench.sh` only
  runs the protocol and prints the result; no value is stored in the code.

## Scripts and tools

Usage, options and the reason for each script are in its header — read before
running. Only which one to use fits here.

- ./install.sh — Linux installer: distro deps, pipx, --selftest at the end.
- ./run.sh — runs the app here, in the foreground; picks the python (uv venv
  when it sees gi, otherwise the system one).
- ./run-tests.sh — lint + selftest + pytest, no display.
- tools/debug.sh — development: background with log, --kill/--status by PID file
  (never pkill -f tortty_python: the pattern also matches `tortty-python` and
  kills the shell of the
  caller). It starts the app through ./run.sh, so the interpreter choice stays
  in one place.
- tools/bench.sh — doom-fire ladder; locks the grid through the socket, measures
  on the current display and on its own Xvfb and does not store a number.
- tortty-python, python3 -m tortty_python, uv run python -m tortty_python — the app (options:
  tortty-python -h).
- uv run pytest -q, uv run ruff check ., uv run ruff format . — battery and lint
  through the uv venv.

Manual test and verification with a window: docs/DEBUG.md.
