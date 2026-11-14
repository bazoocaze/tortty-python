# Configuration

One file, kitty format: **one option per line**, `key value`, leading and
trailing space ignored and `#` commenting to the end of the line — except when
the `#` **opens** the value, which is what makes `foreground #e6e6e6` a colour
and not a comment. A repeated key: the last one wins.

```sh
~/.config/tortty-python/tortty-python.conf     # or $XDG_CONFIG_HOME/...
tortty-python -c /tmp/my.conf                  # another file
```

You do not need to create it: **the defaults are built in** in
`tortty_python/data/tortty-python.conf` (shipped inside the package, readable as
any configuration) and your file goes on top of it, key by key — `-c` only
changes the path of *your* file, the base still applies. `FALLBACK` in
`tortty_python/config.py` is the safety net for a broken package and the list of
known keys; a check (`config_options`) keeps the two in sync, so this page,
the file and the code cannot drift apart silently.

`Ctrl+Shift+F2` opens this file (the user one) in `vim`, in a new tab, with the
window still open behind it. Saving applies it to every tab on the spot: font,
padding, cursor, colours, scrollback and chrome. `--version` prints the version;
the other command line options are in `tortty-python -h` and they win over the
file (`--cmd`, `--debug-log`, `--cols`/`--rows`).

## Keys

| key | default | what it does |
|---|---|---|
| `shell` | empty | program of each new tab; empty = the environment's `$SHELL`, and `/bin/bash` if there is none. A bare name is searched in `PATH`, anything with a `/` must be executable. `--cmd` wins and does **not** change the child's `$SHELL` |
| `font_family` | `Monospace` | font family; monospaced only (the cell is the advance of "M", a proportional font misses the grid). A family that does not exist falls back to Pango's, without error |
| `font_size` | `12` | size in **points** (4..30, float is fine: `12.5`); Pango converts through the DPI, so a HiDPI screen is right on its own |
| `ligatures` | `standard` | `off`, `standard` (`liga`/`calt`: `fi`, `->`, `!=`) or `all` (`standard` + discretionary `dlig`). Only shows up in a font that has them (Fira Code, JetBrains Mono); it does not merge cells — the cell is still one character |
| `letter_spacing` | `0` | extra space between characters in px (0..20): the cell grows with it, the text stays on the grid |
| `cursor_shape` | `block` | `block`, `beam` or `underline`; a `CSI 6 q` from an app wins while it lasts |
| `cursor_blink` | `off` | blinking cursor (530 ms per phase); a key or a paste lights it immediately. `CSI 6 q` can ask for the other |
| `scrollback` | `1000` | history lines above the screen (1..10000). A line costs ~50 B per column, so 10000 at 200 columns is ~100 MB; `0` used to turn the history off in silence, today it is an error |
| `window_padding_width` | `0` | margin in px around the grid (0..200); the mouse click still lands on the right cell |
| `bell` | `none` | BEL: `none`, `visual` (marks the tab) or `audible` |
| `copy_on_select` | `off` | the mouse selection goes to the clipboard without `Ctrl+Shift+C` |
| `bold_as_bright` | `off` | SGR 1 on the eight low colours (`0`–`7`) draws the bright half (`8`–`15`) — xterm's `boldColors`; off by default, because the palette is the owner's and a theme may give the low half its own meaning |
| `restore_state` | `layout` | what the next run inherits: `none` (one clean tab; nothing of the session is written, the geometry included), `layout` (the workspaces, the tabs in order, the cwd of each shell, the front where it was) or `content` (the layout **and** what each tab had on screen and in the history — a photograph, not the process: the shell starts again in the same directory). `PYTERM_GEOM` disables the restore, and `--cols`/`--rows` pin the grid and skip it |
| `debug_log` | `/tmp/tortty-python.debug.log` | JSONL diagnostic log of the `?2026` x scroll events; `off` turns it off. `--debug-log FILE` wins. Events and usage: `docs/DEBUG.md` |
| `foreground` | `#d6d6d6` | text colour (`#rrggbb` or `#rgb`) |
| `background` | `#000000` | background colour |
| `cursor_color` | `#d6d6d6` | cursor colour |
| `color0` … `color15` | see the file | ANSI palette; the rest of the 256 palette (cube and greys) is computed |

### Chrome (`chrome_`)

The window's interface — sidebar, tabs and cards — has its own tokens, separate
from the terminal palette above (`foreground`/`background`/`colorN` do not touch
it). The code has no loose hex: the tokens live in `tortty_python/style.py` and
the defaults here come from there.

| key | default | what it colours |
|---|---|---|
| `chrome_bg` | `#000000` | tab bar, sidebar, card background |
| `chrome_hover_bg` | `#141414` | card under the mouse |
| `chrome_fg` | `#e0e0e0` | text of the cards and tabs |
| `chrome_info_fg` | `#8a8a8a` | the dim info line (title, cwd) |
| `chrome_accent_bg` | `#1f4d2e` | active tab and active card (green) |
| `chrome_accent_fg` | `#ffffff` | text on top of the accent |
| `chrome_accent_info_fg` | `#cfe3d5` | dim info on top of the accent |
| `chrome_sep` | `#333333` | separator between tabs |

## Values

A boolean accepts `on/yes/true/1` and `off/no/false/0`. A colour is `#RGB` or
`#RRGGBB` and an **empty colour is an error** (there is no "no colour"). An
enum is case-insensitive. A number out of range is an error, not a clamp.

The colour default is the **classic xterm palette** (black background, blue
`#0000ee`). It is not laziness: `mc`, `htop`, `ls --color` and `git diff` were
calibrated on it, and swapping it for a "pretty" theme changes the meaning of
the colours the program picked — `mc` blue becomes something else.

## An error is per line

- **initial load**: what validated holds; the invalid key keeps the default and
  the message carries the line number
  (`line 1: font_size is not a number: abc`). The toast at the bottom of the
  window shows the first error;
- **reload** (editing the file with the app open): **any** error keeps the
  configuration that was already in effect and changes nothing. Half a
  configuration is worse than none.

An unknown key is an error, it is not silently ignored. A **repeated** key is a
warning (`line 4: font_size repeated, this one wins (line 1 ignored)`) — the
last one wins.

## Colours change at run time

A program can query (`OSC 4;N;?`, `OSC 10;?`, `OSC 11;?`) and **change**
(`OSC 4;N;colour`, `OSC 10`, `OSC 11`, `OSC 12`, and the resets
`104`/`110`/`111`/`112`) the colours. The theme belongs to the tab, so two tabs
can show different colours at the same time. Editing the file re-seeds the base
from the configuration; what the program asked for stays on top until the
program itself resets it (or the tab closes).

## Not here (yet)

- **Shortcuts are not remappable**: there is no `map`/`unmap`. The chord table
  is in the code and the reason is in `docs/LIMITATIONS.md`;
- **no `include`** of another file — one file, merged over the base;
- **no per-option command line override**: the options of `tortty-python -h`
  are the ones listed above, not one per key.

## When this page is wrong

Three things can go stale, in order of probability: the ranges (they live in
`tortty_python/config.py` as `FONT_MIN`, `SCROLLBACK_MAX`, `PADDING_MAX`,
`LETTER_SPACING_MAX`), the enum values (`CURSOR_SHAPES`, `LIGATURES`, `BELLS`,
`RESTORE_STATES`) and the defaults (the `.conf` above). The check
`config_options` already fails when the file and `FALLBACK` disagree; a key that
exists here and not in `KNOWN` is an error the moment someone types it.
