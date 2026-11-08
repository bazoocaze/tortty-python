# TorTTY-Python — graphical portability (P30)

Open study: running on Linux, Windows and macOS. Item in the queue:
[BACKLOG.md](BACKLOG.md). Platform limits already accepted:
[LIMITATIONS.md](LIMITATIONS.md). Footprint of the two stacks, PSS and disk:
[BENCHMARKS.md](BENCHMARKS.md).

A fact dated here is a snapshot of that day, not current reading: what changed
since then is noted in the text itself.

## What it is

The app declares no dependency at all in `pyproject.toml`, but it has a
**system** dependency (GTK3 + Pango + cairo + PyGObject): on Linux it is free
in marginal terms, because the desktop already pays for it, and expensive on
the other two. This article keeps the data gathered and the cost of each route.

## What is platform today

`on_draw` (`view.py`) receives a cairo_t from the `Gtk.DrawingArea` and
does everything with cairo + Pango: `cr.paint`, runs, `PangoCairo.create_layout`,
`show_layout`. No X11/Win32/Quartz call — the hot path is
portable, and it is what BENCHMARKS measures. The platform dependency is in
~10 window primitives: `DrawingArea`, `add_events`, the `draw` signal,
`Gtk.Clipboard`, `Notebook`/`Stack` in the chrome, CSS via `StyleContext`.
`gui.py` is the only import. The architecture already has the seam; what is
missing is the port existing.

## Concrete blockers in the current code (order of severity)

1. `gui.py` — `gi.require_version("GdkX11", "3.0")` is **outside** the try.
   Without the GdkX11 typelib (mac quartz, Windows win32) the import blows up
   before the fallback that already exists on the next line. One-line fix.
2. `view.py` — wheel only handles `ScrollDirection.UP/DOWN/LEFT/RIGHT`;
   mac trackpad and Windows precision touchpad arrive as
   `SCROLL_SMOOTH` with delta → `btn is None` → scrollback does not scroll.
3. `view.py` — middle button and copy use `SELECTION_PRIMARY`, which does not
   exist outside X11 (silent degradation, needs to fall back to CLIPBOARD).
4. `view.py` — "Monospace" family hardcoded (better: table per OS);
   `get_scale_factor()` is never read (Retina 2x, Windows 150%). The metric is
   measured from Pango, so the grid adapts — the test is the advance × cell pair
   that the socket `state` returns
   (advance x cell x res x cols) run on each OS, the same one that caught bug 13.

## Verified facts (2026-10-28)

- PyGObject **has no wheel anywhere**: PyPI publishes only sdist
  (3.58.1). `pip install pygobject` = compiling against headers, always.
- pycairo 1.29.2: win32/win_amd64/win_arm64 wheels and **zero for macOS**
  (sdist).
- conda-forge covers the whole matrix: gtk3 3.24.52, pango 1.58.2, pygobject
  3.58.1, pycairo 1.29.2, gdk-pixbuf 2.44.8 for linux-64, osx-64, osx-arm64,
  win-64. Pango will never be pip-installable.
- PySide6-Essentials 6.12: manylinux_2_34 wheels (x86_64/aarch64), win_amd64/
  arm64, macosx_14_0 universal2. Floors: glibc 2.34+, macOS 14 (6.10 = 13,
  6.8.3 = 12), Python >= 3.10. Size: 82 MB (win), 84 MB (linux), 116 MB
  (mac) of wheel; 244 MB installed (measured). PyQt6 is GPL — out.
- **Qt6 on Linux still has a system dependency**: without `libxcb-cursor0` the
  xcb plugin does not load ("Could not load the Qt platform plugin xcb");
  reproduced on this machine. That is, "pip and it runs" is true on
  Windows/mac, and almost-true on Linux (X11 needs that package; Wayland does
  not).

## Dependency cost on both sides

The footprint numbers (disk of the stack and app PSS on both routes) live in
[`BENCHMARKS.md`](BENCHMARKS.md), footprint section — only the conclusion stays
here: on Windows/mac Qt **is not heavier** than carrying GTK over there (the
closure of GTK via conda is of a similar order of magnitude); the difference is
who manages it. On Linux GTK wins by construction, because the desktop already
has it loaded.

## Route A — do not change lib, change the manager (conda-forge)

An `environment.yml`, `run.sh` stops choosing between venv and system python.
Code cost: the 4 blockers above. Real cost: ~350-400 MB of environment, GTK
look on the three platforms (the chrome always looks like the OS theme) and
`uv tool install` becomes impossible.

## Route B — swap GTK3 for Qt/PySide6

The only one that gives pip installation and a uniform look. What does **not**
change: `term.py`, `palette.py`, `mouse.py`, `kitty_kbd.py`, `graphics.py`,
`style.py` and the checks. What changes: `view.py` (draw/events/clipboard) and
`window.py` (tabs/workspaces), plus `keys.py` (key constants). Equivalences
mapped: metric = `QFontMetricsF.horizontalAdvance("M")` + `height()`; the
`letter_spacing` trick has a direct counterpart in
`QFont.setLetterSpacing(AbsoluteSpacing, cw - advance)`; `pixelDelta` solves
the smooth wheel for free; HiDPI is Qt's; chrome drawn in `paintEvent` stays
identical on all three (kills the "chrome"). The packaging that was missing
(`[build-system]`, `[project.scripts]`) was done in P31; what still stands
against `uv tool install` is the system dependency, which it does not accept
(see below). `--selftest` and `-h` have to keep running without importing Qt
(same late-import discipline as `cli.py`).

LGPLv3 (PySide6) does not contaminate the project: the code stays MIT, there is
no obligation to open the source, and the concrete requirement is (a) Qt
replaceable — separate dynamic libraries, never a frozen onefile — and (b)
notice + license text alongside the distribution; (c) no GPL-only module (stay
in Essentials) and no PyQt. Anti-tivoization only bites on a sealed device.

## `uv tool install` and pipx (2026-10-28)

At the date of the survey neither worked. P31 solved the packaging
(`pipx install --system-site-packages` is what `install.sh` uses today); what
still holds is the `uv tool` limitation:

- Without `[project.scripts]` the wheel comes out without `entry_points.txt`
  and uv refuses: `No executables are provided by package bzmux; removing
  tool`. And `uv build` **does not fail**: it falls into a legacy setuptools
  and produces a wheel with `top_level = core` (generic name, collides in
  site-packages) and **without `bzmux.py`** — pitfall: it looks packageable and
  is not.
- `uv tool install` creates the tool venv with `system_site_packages`
  **hardcoded to false** (`crates/uv-tool/src/lib.rs`), so `import gi` fails
  inside the tool env. Maintainer position (#13757): *"We don't support using
  system site packages in tools yet"*, with the suggestion
  `uv tool install --with <dep>` — which does not help for PyGObject (sdist).
  Open request: #18303; open PR that writes the flag into the receipt: #18023.
- Workaround used in practice: `uv tool install --python /usr/bin/python3` and
  then `sed -i 's/include-system-site-packages = false/... = true/'
  "$(uv tool dir)/<tool>/pyvenv.cfg"`. Verified here: it starts seeing gi 3.48.2
  and pycairo 1.25.1, and a `uv tool upgrade` preserved the adjustment. It is
  `sed` on an internal uv file — not a path to recommend to a user.
- Real alternatives: `pipx install --system-site-packages` (works today) or a
  manual venv with `uv venv --system-site-packages` + script symlink (the same
  pattern `run.sh` already uses).

Consequence for the decision: Linux's "one command" is pipx or distro/flatpak,
never `uv tool`, as long as the dependency is a system binding. With Qt,
`uv tool install` becomes true without any flag.

## Route C — cairo drawing onto a QImage (discarded for now)

`on_draw` would not change a line: `cairo.ImageSurface.create_for_data` onto the
buffer of a `QImage` (the project already does that for kitty images in
`graphics.py`) and Qt would host window/events/blit. It costs a frame memcpy
(~250 KB on 1920 cells) and **does not solve distribution**: Pango would still
be necessary. It only serves as an intermediate stage of route B.

## Decision (revised on 2026-11-01)

- **Python is an initial choice, not identity.** The experiment proved that a
  whole terminal can be done in Python (that is how the app was born and is
  used); it proved that, not that the language is mandatory. A native core in
  Rust/C is not discarded on principle.
- **cairo + Pango is also an initial choice**, revisable by requirement
  (distribution, GPU, platform).
- Points at stake, only recorded (they are not fixed requirements): target OS;
  target features (splits, attention notice, CLI); throughput/latency; form of
  installing (pip/`uv tool`, no conda). The cmux target is macOS on Ghostty
  (GPU): if that is the target, macOS and accelerated rendering enter the
  conversation and the routes currently out come back into contention.

Consequences that still hold:

- Route A (conda) exists for whoever wants to preserve Pango; route B is the
  path when the target is Windows/macOS, with a thin port (current GTK3 backend
  + Qt backend) to measure the two side by side.
- PyPy (P38) becomes a measurement of the hot path, not an application path:
  without `gi`, only with cffi bindings.
- GPU: cairo draws on the CPU. If accelerated rendering becomes a requirement
  (it is what Ghostty/cmux use), it does not come out of the current stack — it
  is one of the routes to weigh, not a limit already accepted.
- Product target, if it is a cmux clone (vertical tabs, splits, notice when the
  agent asks for attention, CLI): vertical tabs already exist as a workspace
  card, the CLI already is the introspection socket, splits are P39 and the
  notice depends on `OSC 9`/`OSC 777`, not handled today.

If route B happens, BENCHMARKS starts having a number per backend and the
comparison floor gains two new parameters: font family and scale factor
(CoreText/DirectWrite/FreeType rasterization change advance and hinting; the
grid stays correct because it is measured, but the fps are not comparable
between OSes).

Minimum verification on each OS: `--selftest` (no display), the `state` metrics
through `--debug-socket`
(advance x cell x res x cols matching), wheel with trackpad, paste from the
clipboard, selection with the middle button and `./tools/bench.sh` — the last one
only where there is governor/frequency reading (on mac and on Windows it
becomes another protocol, not a line of the current ladder).
