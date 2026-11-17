#!/usr/bin/env bash
# install.sh — installs tortty-python for the current user, never with root.
#
# The app needs the distro's PyGObject (gi) and GTK 3, which pip cannot provide
# and which only the distro's package manager installs. So this script does the
# part that needs no privilege (pipx venv, desktop shortcut) and, when a system
# package is missing, it stops and prints the elevated command for the distro it
# detected. It never calls sudo.
#
# Usage (no clone needed, the URL is stable and its content is the release's):
#   curl -fsSL https://github.com/bazoocaze/tortty-python/releases/latest/download/install.sh | bash
#   curl -fsSL https://github.com/bazoocaze/tortty-python/releases/latest/download/install.sh | bash -s -- --check
#   curl -fsSL https://raw.githubusercontent.com/bazoocaze/tortty-python/main/install.sh | bash
#
# Usage (from a clone: installs the tree you have, no download):
#   ./install.sh              installs (asks for nothing; stops if a dep is missing)
#   ./install.sh --check      inventory only: what is there, what is missing
#   ./install.sh --dry-run    prints each command instead of running it
#   ./install.sh --uninstall  removes it with pipx
#   ./install.sh --version vX installs a specific release instead of the latest
#   ./install.sh --force      reinstalls when the same version is already there
#   ./install.sh --no-shortcut  skips the desktop entry
#
# Exit codes: 0 ok, 3 a system dependency is missing, 4 no pipx/uv, 5 install
# failed, 6 cannot download. A wrapper can react without parsing the text.
#
# MIT (see LICENSE).
set -euo pipefail

OWNER=bazoocaze
REPO_NAME=tortty-python
REPO_URL="https://github.com/$OWNER/$REPO_NAME"
PKG=tortty-python     # pipx package name
EXE=tortty-python     # console script installed in PATH
OLD_PKG=pybzmux        # package from the previous name, removed by this installer
OLD_EXE=pybzmux        # console script from the previous name
# The release tool substitutes this with the tag it is publishing, so a script
# taken from /releases/latest/download/ knows exactly which version it came from.
VERSION="${TORTTY_VERSION:-@VERSION@}"

say()  { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
die()  { warn "tortty-python: $*"; exit "${2:-1}"; }
# Piped in, there is no file to point at: bash reports "" / "bash" / "main".
self_name() {
    local s="${BASH_SOURCE[0]:-}"
    if [ -n "$s" ] && [ -f "$s" ]; then printf '%s' "$s"; else printf 'this installer'; fi
}
has_pipx() { command -v pipx >/dev/null 2>&1 || command -v uvx >/dev/null 2>&1; }

DRY=0; CHECK=0; SHORTCUT=1; FORCE=0; MODE=install; WANT_TAG=0
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)     DRY=1 ;;
        --check)       CHECK=1 ;;
        --no-shortcut) SHORTCUT=0 ;;
        --shortcut)    SHORTCUT=1 ;;
        --force)       FORCE=1 ;;
        --uninstall)   MODE=uninstall ;;
        --version)     VERSION="${2:-}"; WANT_TAG=1; shift || die "--version needs a tag (e.g. v0.0.40)" ;;
        --version=*)   VERSION="${1#*=}"; WANT_TAG=1 ;;
        --no-deps)     warn "== --no-deps is gone: this installer never installs system packages" ;;
        -h|--help)     awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) die "invalid option: $1 (see -h)" ;;
    esac
    shift
done

run() {
    if [ "$DRY" = 1 ]; then say "+ $*"; else "$@"; fi
}

# -- what the machine has ------------------------------------------------------
# The venv has to be built on the interpreter that sees the distro's gi: pip
# cannot install PyGObject in a way that reaches GTK 3.
MISSING=()
gi_python() {
    local p
    for p in "$@"; do
        case "$p" in
            */*) [ -x "$p" ] || continue ;;
            *)   p=$(command -v "$p" 2>/dev/null) || continue ;;
        esac
        "$p" -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk, Pango; import cairo' \
            2>/dev/null && { printf '%s' "$p"; return 0; }
    done
    return 1
}

have_gtk() { gi_python python3 python3.12 python3.11 python3.10 /usr/bin/python3 >/dev/null; }

# The elevated command for the package manager this machine actually has; the
# user runs it, this script never does.
dep_hint() {
    local pm
    for pm in apt-get dnf pacman zypper; do
        command -v "$pm" >/dev/null 2>&1 || continue
        case "$pm" in
            apt-get) say "  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0" ;;
            dnf)     say "  sudo dnf install python3-gobject python3-cairo gtk3" ;;
            pacman)  say "  sudo pacman -S python-gobject python-cairo gtk3" ;;
            zypper)  say "  sudo zypper install python3-gobject python3-cairo gtk3" ;;
        esac
        return 0
    done
    say "  (package manager not recognised) install PyGObject 3, GTK 3 and pycairo"
}

missing_report() {
    local what="ies"
    [ "${#MISSING[@]}" = 1 ] && what="y"
    warn "tortty-python: cannot install yet — missing dependenc$what:"
    local m
    for m in "${MISSING[@]}"; do warn "  - $m"; done
    warn
    warn "install them and run this again (this script never uses sudo):"
    have_gtk || dep_hint >&2
    has_pipx || pipx_hint >&2
    warn
    warn "to see the whole inventory first: $(self_name) --check"
}

inventory() {
    MISSING=()
    local py
    if py=$(gi_python python3 python3.12 python3.11 python3.10 /usr/bin/python3); then
        say "ok    $py ($("$py" -V 2>&1)) with PyGObject, GTK 3, Pango and pycairo"
    else
        MISSING+=("PyGObject (gi) with GTK 3, Pango and pycairo")
    fi
    if command -v pipx >/dev/null 2>&1; then
        say "ok    pipx ($(command -v pipx))"
    elif command -v uvx >/dev/null 2>&1; then
        say "ok    uvx (pipx is absent; uvx pipx runs without installing anything)"
    else
        MISSING+=("pipx or uv (the venv that holds the app)")
    fi
}

# -- pipx ----------------------------------------------------------------------
# System pipx first. Without it, "uvx pipx" runs pipx from uv's cache: nothing is
# installed system-wide, and the --python below compensates for uv's interpreter.
PIPX=()
pick_pipx() {
    [ -n "${PIPX[0]:-}" ] && return 0
    if command -v pipx >/dev/null 2>&1; then
        PIPX=(pipx); return 0
    fi
    if command -v uvx >/dev/null 2>&1; then
        say "== pipx not found; using 'uvx pipx' (nothing is installed system-wide)"
        PIPX=(uvx --from pipx pipx); return 0
    fi
    return 1
}

pipx_hint() {
    local pm
    for pm in apt-get dnf pacman zypper; do
        command -v "$pm" >/dev/null 2>&1 || continue
        case "$pm" in
            apt-get) say "  sudo apt install pipx" ;;
            dnf)     say "  sudo dnf install pipx" ;;
            pacman)  say "  sudo pacman -S python-pipx" ;;
            zypper)  say "  sudo zypper install python3-pipx" ;;
        esac
        break
    done
    say "  uv (no root):  curl -LsSf https://astral.sh/uv/install.sh | sh"
}

no_pipx_report() {
    warn "tortty-python: pipx and uv are both missing — that is where the app's own venv lives."
    warn
    warn "install one of them:"
    pipx_hint >&2
    warn
    warn "then run this again."
}

# -- remove the old name's leftovers ------------------------------------------
# Runs before install: the old package also exposed the app as pybzmux, and its
# uninstall would delete the link the new install just created.
drop_old_pkg() {
    [ "$OLD_PKG" = "$PKG" ] && return 0
    if [ "$DRY" = 1 ]; then say "+ ${PIPX[*]} uninstall $OLD_PKG  (if present)"; return 0; fi
    "${PIPX[@]}" uninstall "$OLD_PKG" >/dev/null 2>&1 \
        && say "== removed the old package: $OLD_PKG" || true
}

# $1 is the path "command -v $OLD_EXE" gave before this run. An $OLD_EXE that did
# not come from pipx stays: it may be a dev venv link.
drop_old_exe() {
    local old="${1:-}" target=""
    [ -n "$old" ] || return 0
    [ "$old" = "$(command -v "$EXE" 2>/dev/null)" ] && return 0
    [ -e "$old" ] || return 0
    [ -L "$old" ] && target=$(readlink -f "$old" 2>/dev/null || readlink "$old")
    case "$old$target" in
        *pipx*"$OLD_PKG"*|*pipx*"$PKG"*)
            run rm -f "$old"
            say "== removed the old command: $old (it is $EXE now)" ;;
    esac
}

# -- the wheel of one release -------------------------------------------------
# Assets are published under fixed names (tortty-python.whl, SHA256SUMS), so the
# URL is the same for every release; the version lives in the tag path.
release_base() {
    # test hook: a local directory served over http mimics a release
    if [ -n "${TORTTY_RELEASE_BASE:-}" ]; then printf '%s' "$TORTTY_RELEASE_BASE"; return 0; fi
    case "${VERSION:-}" in
        v[0-9]*)         printf '%s/releases/download/%s' "$REPO_URL" "$VERSION" ;;
        # the placeholder is what the repo file carries before a release
        # substitutes it: taken from main, it means "the latest release"
        ""|'@VERSION@')  printf '%s/releases/latest/download' "$REPO_URL" ;;
        *)               die "invalid version '$VERSION' (expected a tag such as v0.0.40)" ;;
    esac
}

# A private repository answers 404 to an anonymous request for its assets. The
# token comes from $TORTTY_TOKEN or from gh, and it only ever goes to github.com.
release_token() {
    if [ -n "${TORTTY_TOKEN:-}" ]; then printf '%s' "$TORTTY_TOKEN"; return 0; fi
    command -v gh >/dev/null 2>&1 || return 0
    gh auth token 2>/dev/null || true
}

_dl() {  # _dl URL DEST [TOKEN]
    if command -v curl >/dev/null 2>&1; then
        if [ -n "${3:-}" ]; then curl -fsSL --retry 3 -H "Authorization: Bearer $3" -o "$2" "$1"
        else curl -fsSL --retry 3 -o "$2" "$1"; fi
    elif command -v wget >/dev/null 2>&1; then
        if [ -n "${3:-}" ]; then wget -qO "$2" --header="Authorization: Bearer $3" "$1"
        else wget -qO "$2" "$1"; fi
    else
        die "curl or wget is needed to download the release" 6
    fi
}

fetch() {  # fetch URL DEST
    _dl "$1" "$2" && return 0
    local tok
    tok=$(release_token)
    [ -n "$tok" ] || die "cannot download $1 (private release? set TORTTY_TOKEN or log in with gh)" 6
    case "$1" in
        https://github.com/*) _dl "$1" "$2" "$tok" ;;
        *) die "cannot download $1" 6 ;;
    esac
}

# Downloads the wheel into $1, checks it against the release's SHA256SUMS and
# leaves WHEEL_FILE pointing at the file, renamed to what pipx expects.
# Verification matters here: a pipe into bash has no undo, so at least the
# artifact that ends up inside a venv is the one the release signed.
download_wheel() {
    local dir=$1 base sums want got
    base=$(release_base)
    say "== release: $base"
    fetch "$base/SHA256SUMS" "$dir/SHA256SUMS" \
        || die "cannot download $base/SHA256SUMS (private release? TORTTY_TOKEN or gh login)" 6
    fetch "$base/$PKG.whl" "$dir/$PKG.whl" \
        || die "cannot download $base/$PKG.whl (private release? TORTTY_TOKEN or gh login)" 6
    want=$(awk -v f="$PKG.whl" '$2==f || $2=="*"f {print $1}' "$dir/SHA256SUMS")
    [ -n "$want" ] || die "SHA256SUMS has no entry for $PKG.whl" 6
    if command -v sha256sum >/dev/null 2>&1; then
        got=$(sha256sum "$dir/$PKG.whl" | awk '{print $1}')
    else
        got=$(shasum -a 256 "$dir/$PKG.whl" | awk '{print $1}')
    fi
    [ "$want" = "$got" ] || die "checksum mismatch for $PKG.whl: expected $want, got $got" 6
    say "== checksum ok: ${want%"${want#????????}"}…"
    # pipx (and uv under it) parse the file name, so the fixed name has to go
    # back to the canonical one before it reaches a venv
    local ver
    ver=$(wheel_version "$dir/$PKG.whl") || die "cannot read the version inside $PKG.whl" 6
    mv "$dir/$PKG.whl" "$dir/tortty_python-$ver-py3-none-any.whl"
    WHEEL_FILE="$dir/tortty_python-$ver-py3-none-any.whl"
}

wheel_version() {  # the version the wheel itself declares, not the tag's guess
    "$PY" - "$1" <<'EOF'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    name = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
    for line in z.read(name).decode().splitlines():
        if line.startswith("Version: "):
            print(line[9:].strip())
            break
EOF
}

# Where pipx puts the console script. A fresh machine has no ~/.local/bin in PATH
# yet, so calling the app by name would fail right after a successful install.
bin_dir() {
    "${PIPX[@]}" environment --value PIPX_BIN_DIR 2>/dev/null || printf '%s' "$HOME/.local/bin"
}

# -- install -------------------------------------------------------------------
install() {
    [ "$(uname -s)" = "Linux" ] || die "Linux only for now (Windows/macOS: see docs/BACKLOG.md, P30)"

    inventory
    if [ "$CHECK" = 1 ]; then
        if [ -n "${MISSING[*]:-}" ]; then
            missing_report
            exit 3
        fi
        say
        say "ok    everything this installer needs is here"
        return 0
    fi

    # Nothing is installed when an import the app cannot live without is
    # missing: the binary would be born broken.
    have_gtk || { missing_report; exit 3; }

    pick_pipx || { no_pipx_report; exit 4; }
    local PY
    PY=$(gi_python python3 python3.12 python3.11 python3.10 /usr/bin/python3) \
        || { missing_report; exit 3; }
    say "== python with gi: $PY"

    local old_exe spec tmp=""
    old_exe=$(command -v "$OLD_EXE" 2>/dev/null) || old_exe=""
    if spec=$(local_tree); then
        say "== installing the local tree: $spec"
    else
        tmp=$(mktemp -d)
        download_wheel "$tmp"
        spec="$WHEEL_FILE"
    fi

    drop_old_pkg
    # --force only when a venv already exists: pipx ignores --python when it is
    # given, and a fresh venv has to be built on the python that sees gi. With a
    # venv in place, keeping it is the point (and pipx demands --force to replace
    # the same version).
    installed_now() { "${PIPX[@]}" list --short 2>/dev/null | awk '{print $1}' | grep -qx "$PKG"; }
    if installed_now; then
        run "${PIPX[@]}" install --force --system-site-packages "$spec"
    else
        run "${PIPX[@]}" install --system-site-packages --python "$PY" "$spec"
    fi

    if [ "$DRY" = 1 ]; then
        say "+ $EXE --selftest"
        drop_old_exe "$old_exe"
        [ -n "$tmp" ] && say "+ rm -rf $tmp"
        return 0
    fi
    local BIN
    BIN=$(bin_dir)
    [ -x "$BIN/$EXE" ] || die "pipx finished, but $BIN/$EXE is not there" 5
    if ! command -v "$EXE" >/dev/null 2>&1; then
        warn "== note: $BIN is not in PATH yet — open a new shell, or run: pipx ensurepath"
    fi
    say "== verification"
    if ! "$BIN/$EXE" --selftest | tail -1; then
        warn "tortty-python: the installed app does not start — the venv most likely"
        warn "was built on a python that does not see gi. Recreate it with:"
        warn "  ${PIPX[*]} reinstall $PKG --python $PY"
        exit 5
    fi

    drop_old_exe "$old_exe"
    [ -n "$tmp" ] && rm -rf "$tmp"

    if [ "$SHORTCUT" = 1 ]; then
        say "== desktop entry"
        run "$BIN/$EXE" --install-shortcut
    fi

    say
    say "done: run '$EXE' (to update, run this installer again)"
}

# The tree this script lives in, when it is a tortty-python checkout: a dev
# running ./install.sh installs what they are editing, not a release.
local_tree() {
    local here src="${BASH_SOURCE[0]:-}"
    [ -n "$src" ] || return 1  # piped in: the release is what was asked for
    [ "$WANT_TAG" = 0 ] || return 1  # --version: the tag wins over the tree
    here=$(cd "$(dirname "$src")" 2>/dev/null && pwd) || return 1
    [ -f "$here/pyproject.toml" ] || return 1
    grep -q '^name = "tortty-python"' "$here/pyproject.toml" || return 1
    printf '%s' "$here"
}

uninstall() {
    local old_exe BIN
    old_exe=$(command -v "$OLD_EXE" 2>/dev/null) || old_exe=""
    pick_pipx || { no_pipx_report; exit 4; }
    BIN=$(bin_dir)
    # The shortcut goes first: after the pipx uninstall the command is gone.
    if [ -x "$BIN/$EXE" ]; then
        run "$BIN/$EXE" --remove-shortcut || true
    elif [ -x "$BIN/$OLD_EXE" ]; then
        run "$BIN/$OLD_EXE" --remove-shortcut || true
    fi
    run "${PIPX[@]}" uninstall "$PKG"
    drop_old_pkg
    drop_old_exe "$old_exe"
}

case "$MODE" in
    install)   install ;;
    uninstall) uninstall ;;
esac
