# TorTTY-Python — backlog (pending)

Current and future activities. Id `P<n>`.
Completed activities do not stay here; they must go to `HISTORY.md`.

P26 — Drawing: `cr.show_glyphs` with precomputed glyphs. **Experiment, not a
commitment.** It is the only path that really attacks the emission cost:
2.43 → 0.76 µs (-69%, ~24% of the drawing). The price is leaving Pango: no font
fallback, no bold attrs and no widget resolution (the app uses 130 dpi).
Measured: 440–958 different bytes out of 56,000 in a cell ~0.8% of the bytes)
and optimal `dy` equal to Pango's. The faithful path (extract the glyphs *from*
Pango and call `show_glyphs`) **does not exist in pygobject**:
`GlyphString.glyphs` blows up "Stack overflow protection" and returns `[]`. If
you try it, the drawing must choose per run (ASCII without `.notdef` → cairo;
otherwise Pango) and the validation is pixel comparison, not fps.

P38 — Alternative runtime: PyPy and Cython on the hot path. **Experiment, not a
commitment.** Request: can the project be measured under PyPy and under Cython?
Not the whole app: `gi` is only imported in `tortty_python/gui.py`, but view and window
go through it, and PyGObject does not run on PyPy (`cpyext` does not cover the C
API it uses) — the window does not come up. What can be measured is the pure hot
path (`palette`, `term`, `graphics`, `kitty_kbd`, `mouse`): feed N MB into `Term`
and compare parse+grid MB/s with CPython, which is the ruler of the
[BENCHMARKS.md](BENCHMARKS.md). Cython is viable on the same subset (none of
those modules imports `gi`), at the price of a build step per Python version in
`install.sh`/pipx and of typing the hot loops — compiling without C types yields
little. It fits in the same measurement: mypyc (requires annotating the code)
and Nuitka. Today `pypy3` and `cython` are not installed.

P39 — Splits: more than one terminal in the same view. **Feature.** Request:
split the view into several terminals. Cost raised for free in the conversation
(2026-11-01, Xvfb, font 13, text scene with 8 colors): per frame there is a
fixed ~0.4 ms plus ~0.5 µs per cell — 61x18 gives 0.99 ms, 31x18 gives 0.68 ms,
16x9 gives 0.49 ms, so drawing N splits in the same widget costs practically the
same as today's full screen, and one widget per split pays the fixed cost once
per split. Memory is what really scales: 90 KB per screen and **~5 MB per
terminal** with `scrollback` 1000 (84 B per cell). There is no thread in the
project: each split is one more pty stream on the same drawing thread (like N
tabs today, but with draw together). What to decide at execution time: one
widget with damage per region vs. widget per split, shared layout cache and font
metrics, blink only on the visible one, and the practical ceiling of splits —
which comes from memory, not from the frame.

P30 — Graphical portability: running on Linux, Windows and macOS. **Open**
(reviewed on 2026-11-01): neither Python nor cairo/Pango are identity — they
were an initial choice. Points at stake, only recorded (they are not
requirements): target OS, target features (splits, attention notice, CLI),
throughput/latency, install form. The study, the blocks in the code and the cost
of each route (conda, Qt, FFI) are in [PORTABILITY.md](PORTABILITY.md); none of
it is decided.

P33 — Configuration file: **v1 implemented** (2026-10-29), real use is missing.
The scope decision was "start with `shell` only": no colors, font or shortcuts.
What exists:

- `tortty_python/config.py` pure (no `gi`): parse of the kitty format (`chave valor`,
  `#` comments to the end of the line, leading/trailing space, repeated key the
  last one wins), validation per key and merge **always** with the default;
- default embedded in `tortty_python/data/tortty-python.conf` (goes in the wheel like
  the icon);
- user file at `$XDG_CONFIG_HOME/tortty-python/tortty-python.conf`, and `-c FILE` /
  `--config FILE` changes only that path (the merge with the default continues);
- `shell` (empty in the default) becomes the command of each new tab; `--cmd`
  wins. Empty inherits the environment's `$SHELL`, and the `$SHELL` handed to
  the child is always the shell that actually runs (before, the inherited one
  stayed, even with another one configured);
- auto-reload via `Gio.FileMonitor` with a 250 ms debounce; on reload, an error
  keeps the previous configuration (nothing changes) and the error goes to a
  10 s toast at the base of the window (Android style, `Gtk.Revealer` + `#toast`
  in `style.py`);
- `Ctrl+Shift+F2` opens the user file in `vim`, in a new tab.

Font, cursor, scrollback, padding, bell and copy have already landed (P34,
completed). What remains for later: palette (`color0..15`, `foreground`,
`background`, `cursor`, with `#rrggbb` in the kitty format) and shortcut
remapping.

Two bugs found on the way, recorded in `docs/HISTORY.md`: `Gio.FileMonitor` was
collected by the GC (without a kept reference the reload never fired) and
`no_show_all` blocks even the `show_all()` called directly on the widget (the
toast box stayed invisible).

The other items are completed: history and bugs in [HISTORY.md](HISTORY.md),
tools and pitfalls in [DEBUG.md](DEBUG.md).

What remains is a known limitation, not an item — wide character (CJK/emoji)
occupying a single cell, partial kitty keyboard protocol, uninterpreted
sequences, no configurable chrome (`style.py`) — all in
[LIMITATIONS.md](LIMITATIONS.md).

P50 — Session restore: the workspaces, the tabs and the cwd of each shell come
back on the next run. **Feature.** Request: closing the window today loses the
layout ([LIMITATIONS.md](LIMITATIONS.md)); `state.py` already stores the
geometry in XDG_STATE_HOME and P47 delivered the cwd source (`OSC 7` + the
spawn directory). Same scope as the Rust: layout comes back, the content does
not (a fresh shell per tab, no scrollback), and `PYTERM_GEOM` (the measurement
protocol) neither restores nor saves.

P51 — Render gate on Xvfb: draw known content, capture and compare pixels.
**Tooling.** Request: the Rust has `tools/render-check.sh` and this project has
no automatic check that the window paints (a drawing regression only shows up
to the eye). Same battery: window paints (content changed ⇒ pixel changed),
colors come out right (`SGR 41/42`), the text lands in the requested cell, a
still screen does not repaint differently, and each grid line falls in its own
pixel band. `tools/pixel.py` already reads the PNG; what is missing is the
runner. Not a test suite replacement: it needs a display (Xvfb) and stays in
`tools/`.
