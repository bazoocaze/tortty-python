# TorTTY-Python — backlog (pending)

Current and future activities. Id `P<n>`. A completed activity leaves here and
goes to [HISTORY.md](HISTORY.md); what is not an item — a limit accepted by
decision, a tool and its pitfalls — belongs to [LIMITATIONS.md](LIMITATIONS.md)
and [DEBUG.md](DEBUG.md).

P26 — Drawing: `cr.show_glyphs` with precomputed glyphs. **Experiment, not a
commitment.** It is the only path that really attacks the emission cost:
2.43 → 0.76 µs (-69%, ~24% of the drawing). The price is leaving Pango: no font
fallback, no bold attrs and no widget resolution (the app uses 130 dpi).
Measured: 440–958 different bytes out of 56,000 in a cell (~0.8% of the bytes)
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

P57 — `restore_state content`: the photograph of each tab. **Feature.** The
Rust has the third degree of `restore_state` (P50 implemented `none` and
`layout`): besides the workspaces and the tabs, what each one had on screen and
in the history comes back — the shell starts again in the same directory, the
processes do not. The route there is already settled and it is the route here:
the snapshot is **ANSI**, not a private format (`crates/core/src/snapshot.rs`),
because the reader already exists — the parser. SGR, `OSC 8` links and
soft-wrapped rows go in as bytes, so a snapshot taken in a wide window and
reopened narrow reflows by the same code as a live resize; images, clipboard,
notification and title stay out (a photograph, not a process). One file per
(workspace, tab) in the state directory (`state.save_snapshots`), written on
the way out and fed to a fresh `Term` on the way in. What is missing here is the
emitter: `Term` reads SGR and `OSC 8` but does not write them back, so it is a
`term.py` companion (`snapshot(term) -> bytes`, pure, so `--selftest` covers
it) plus the `state.py` plumbing and the marker the terminal writes to separate
the restored picture from the new run.
