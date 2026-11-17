#!/bin/sh
# release-check.sh — validates a release through its own channel, in a container:
# what a stranger gets when they paste the install command.
#
#   tools/release-check.sh                 # the latest published release
#   tools/release-check.sh --tag v0.0.44   # a pinned published tag
#   tools/release-check.sh --dist dist     # local artifacts, before publishing
#   tools/release-check.sh --rebuild       # rebuild both images (apt runs again)
#   tools/release-check.sh --keep          # keep the generated harness
#
# What it proves, and nothing else does:
#
#   1. the assets exist, the install.sh carries no @VERSION@ left and names its
#      own tag, and SHA256SUMS matches the wheel;
#   2. the wheel METADATA version equals the tag the install.sh names;
#   3. on an image without gi the diagnosis exits 3 and prints the distro
#      command — the package list it prints is the one baked into the ready
#      image, so the suggestion is exercised, not just read;
#   4. install, then install again over the venv it just built (the reinstall
#      that 0.0.43 broke): base=/usr and `import gi` must hold both times;
#   5. the desktop entry and the icon land, the window opens under Xvfb and
#      paints, the debug socket answers the grid size, ctrl+shift+t adds a tab
#      and the screen text is readable;
#   6. --uninstall removes venv and shortcut and a fresh install comes back.
#
# --dist takes the artifacts from a directory instead of the network: the same
# install.sh runs with TORTTY_RELEASE_BASE pointing at a local HTTP server, so a
# release is exercised before it is published (that is what tools/release.sh
# calls, and what keeps a broken installer from ever reaching a tag).
#
# Two images are built once and reused, so a rerun spends no apt: only the
# install.sh (17 KB) and the wheel (165 KB) per pass. Needs docker.
#
# Exit codes: 0 all passed, 1 a check failed, 2 usage or docker missing.
set -u

SELF=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
ROOT=$(cd "$(dirname "$SELF")/.." && pwd)
REPO_URL=https://github.com/bazoocaze/tortty-python
TAG=
DIST=
REBUILD=0
KEEP=0

usage() { sed -n '2,38p' "$SELF" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --tag) TAG=${2:-}; [ -n "$TAG" ] || { echo "--tag needs a value (v0.0.44)" >&2; exit 2; }; shift 2 ;;
        --tag=*) TAG=${1#*=}; shift ;;
        --dist) DIST=${2:-}; [ -n "$DIST" ] || { echo "--dist needs a directory" >&2; exit 2; }; shift 2 ;;
        --dist=*) DIST=${1#*=}; shift ;;
        --rebuild) REBUILD=1; shift ;;
        --keep) KEEP=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "release-check: unknown option $1 (see -h)" >&2; exit 2 ;;
    esac
done

command -v docker >/dev/null 2>&1 || {
    echo "release-check: docker is missing; this check runs the release in a container" >&2
    exit 2
}

if [ -n "$DIST" ]; then
    [ -d "$DIST" ] || { echo "release-check: no such directory: $DIST" >&2; exit 2; }
    DIST=$(cd "$DIST" && pwd)
    for f in install.sh tortty-python.whl SHA256SUMS; do
        [ -f "$DIST/$f" ] || { echo "release-check: $DIST/$f is missing" >&2; exit 2; }
    done
    SRC=dist
    EXPECT=$(sed -n 's/^VERSION="${TORTTY_VERSION:-v\{0,1\}\([0-9.]*\)}".*/\1/p' "$DIST/install.sh" | head -1)
    [ -n "$EXPECT" ] && [ -n "$TAG" ] && [ "${TAG#v}" != "$EXPECT" ] && {
        echo "release-check: dist/install.sh names v$EXPECT but --tag is $TAG" >&2; exit 2; }
    [ -n "$EXPECT" ] && TAG="v$EXPECT"
else
    SRC=url
    if [ -n "$TAG" ]; then
        BASE_URL="$REPO_URL/releases/download/$TAG"
        EXPECT=${TAG#v}
    else
        BASE_URL="$REPO_URL/releases/latest/download"
        EXPECT=
    fi
fi

BASE_IMG=tortty-python-relcheck:base
READY_IMG=tortty-python-relcheck:ready
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tortty-release-check.XXXXXX")
[ "$KEEP" -eq 1 ] || trap 'rm -rf "$WORK"' EXIT INT TERM

echo "== release-check: $REPO_URL ${TAG:-latest} ${DIST:+(local artifacts)}"

# --- the harness --------------------------------------------------------------
# Both images keep /var/lib/apt/lists, so nothing after the first build needs
# apt-get update; the ready image installs exactly the list the diagnosis
# prints on Ubuntu, which is what makes check 3 mean something.
cat >"$WORK/Dockerfile" <<'DOCKERFILE'
FROM ubuntu:24.04 AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates python3
FROM base AS ready
RUN apt-get install -y --no-install-recommends \
        python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
        pipx xvfb xdotool x11-utils imagemagick fonts-dejavu-core
DOCKERFILE

cat >"$WORK/lib.sh" <<'LIB'
# Sourced by both passes: where the assets come from, and how they are fetched.
# In dist mode the real install.sh runs against a local HTTP server, so the URL
# building, the checksum check and the wheel naming are the same code paths.
fails=0
ok()  { printf 'ok    %s\n' "$*"; }
fail(){ printf 'FAIL  %s\n' "$*"; fails=$((fails + 1)); }
info(){ printf '      %s\n' "$*"; }

serve_dist() {
    python3 -m http.server 8099 --bind 127.0.0.1 --directory /dist >/tmp/http.log 2>&1 &
    echo $! >/tmp/http.pid
    sleep 1
    export TORTTY_RELEASE_BASE=http://127.0.0.1:8099
    cp /dist/install.sh /tmp/i.sh
}
fetch_assets() {   # wheel and SHA256SUMS into /tmp
    if [ "${SRC:-url}" = dist ]; then
        cp /dist/tortty-python.whl /tmp/w.whl
        cp /dist/SHA256SUMS /tmp/SHA256SUMS
    else
        curl -fsSL "$BASE_URL/tortty-python.whl" -o /tmp/w.whl
        curl -fsSL "$BASE_URL/SHA256SUMS" -o /tmp/SHA256SUMS
    fi
}
wheel_version() {
    python3 - <<'PYEOF'
import re, zipfile
z = zipfile.ZipFile("/tmp/w.whl")
m = [n for n in z.namelist() if n.endswith("METADATA")][0]
print(re.search(r"^Version: (.+)$", z.read(m).decode(), re.M).group(1))
PYEOF
}
LIB

cat >"$WORK/check.sh" <<'CHECK'
#!/bin/sh
# Runs on the base image (no gi, no pipx): assets and the diagnosis.
set -u
. /lib.sh

if [ "${SRC:-url}" = dist ]; then
    serve_dist
    ok "local artifacts served at $TORTTY_RELEASE_BASE ($(ls /dist | tr '\n' ' '))"
else
    code=$(curl -s -o /dev/null -w '%{http_code}' -L "$BASE_URL/install.sh")
    [ "$code" = 200 ] && ok "install.sh answers 200 at ${BASE_URL##*/releases/}" \
        || fail "install.sh http=$code"
    curl -fsSL "$BASE_URL/install.sh" -o /tmp/i.sh && ok "install.sh downloaded" \
        || fail "install.sh download"
fi
[ -s /tmp/i.sh ] && ok "install.sh is $(wc -c </tmp/i.sh) bytes" || fail "install.sh is empty"
[ "$(grep -c '@VERSION@' /tmp/i.sh)" = 0 ] \
    && ok "the install.sh carries no @VERSION@ placeholder" || fail "@VERSION@ is still in it"
v=$(sed -n 's/^VERSION="${TORTTY_VERSION:-v\{0,1\}\([0-9.]*\)}".*/\1/p' /tmp/i.sh | head -1)
[ -n "$v" ] && ok "it names its own version (v$v)" || fail "cannot read VERSION from install.sh"
[ -n "${EXPECT:-}" ] && { [ "$v" = "$EXPECT" ] && ok "v$v is the version expected" \
    || fail "install.sh says v$v, expected v$EXPECT"; }

fetch_assets && ok "wheel and SHA256SUMS fetched ($(wc -c </tmp/w.whl) bytes)" \
    || fail "cannot fetch the wheel or SHA256SUMS"
( cd /tmp && sed 's|tortty-python.whl|w.whl|' SHA256SUMS > sums2 && sha256sum -c sums2 >/dev/null 2>&1 ) \
    && ok "SHA256SUMS matches the wheel" || fail "wheel checksum does not match SHA256SUMS"
wv=$(wheel_version)
[ "$wv" = "$v" ] && ok "wheel METADATA says v$wv, install.sh says v$v" \
    || fail "METADATA says $wv, install.sh says $v"

python3 -c 'import gi' 2>/dev/null && fail "the base image already has gi; the diagnosis test is void" \
    || ok "the base image really has no gi (the stranger's case)"

bash /tmp/i.sh --check >/tmp/check.txt 2>&1; rc=$?
[ "$rc" = 3 ] && ok "--check exits 3 (a system dependency is missing)" \
    || fail "--check exits $rc, expected 3"
line=$(grep -o 'apt install .*' /tmp/check.txt | head -1)
[ -n "$line" ] && ok "the diagnosis prints the distro command: $line" \
    || fail "no package manager command printed"
grep -qi pipx /tmp/check.txt && ok "the diagnosis also names pipx" || fail "pipx is not mentioned"

echo "== check: $fails failure(s)"
[ "$fails" = 0 ]
CHECK

cat >"$WORK/flow.sh" <<'FLOW'
#!/bin/sh
# Runs on the ready image: install twice, the window, the socket, uninstall,
# install again. No apt here.
set -u
. /lib.sh
V=/root/.local/share/pipx/venvs/tortty-python
DESK=/root/.local/share/applications/tortty-python.desktop
SOCK=/tmp/t.sock

sockq() {   # one request, one line back
    python3 - "$1" <<'PYEOF'
import socket, sys
s = socket.socket(socket.AF_UNIX)
s.connect("/tmp/t.sock")
s.sendall((sys.argv[1] + "\n").encode())
print(s.recv(1 << 16).decode().strip())
PYEOF
}
field() {   # field <json> <key>: the socket indents its JSON, so parse it
    python3 - "$1" "$2" <<'PYEOF'
import json, re, sys
d = json.loads(re.sub(r"^[^ {[]*", "", sys.argv[1], count=1))
v = d.get(sys.argv[2])
if v is None and sys.argv[2] == "tabs":
    v = len(d.get("tab_order") or [])
print(v)
PYEOF
}

if [ "${SRC:-url}" = dist ]; then serve_dist; else curl -fsSL "$BASE_URL/install.sh" -o /tmp/i.sh; fi
[ -s /tmp/i.sh ] || { echo "no install.sh"; exit 1; }
v=$(sed -n 's/^VERSION="${TORTTY_VERSION:-v\{0,1\}\([0-9.]*\)}".*/\1/p' /tmp/i.sh | head -1)

for n in 1 2; do
    bash /tmp/i.sh >"/tmp/inst$n.txt" 2>&1; rc=$?
    base=$("$V/bin/python" -c 'import sys;print(sys.base_prefix)' 2>/dev/null || echo '?')
    gio=$("$V/bin/python" -c 'import gi;print(1)' 2>/dev/null || echo 0)
    ver=$("$V/bin/python" -c 'import tortty_python;print(tortty_python.__version__)' 2>/dev/null || echo '?')
    sel=$(grep -o 'SELFTEST OK ([0-9]* checks)' "/tmp/inst$n.txt" | tail -1)
    what="install #$n"; [ "$n" = 2 ] && what="install #2 (over the venv #1 built)"
    if [ "$rc" = 0 ] && [ "$base" = /usr ] && [ "$gio" = 1 ] && [ "$ver" = "$v" ]; then
        ok "$what: rc=0 base=$base gi=ok v$ver $sel"
    else
        fail "$what: rc=$rc base=$base gi=$gio v$ver [$sel]"
    fi
done

[ -f "$DESK" ] && ok "desktop entry: $(awk -F= '/^Exec=/{print $2}' "$DESK")" || fail "no desktop entry"
icon=$(find /root/.local/share/icons -name 'tortty-python.*' | head -1)
[ -n "$icon" ] && ok "icon: ${icon##*/icons/}" || fail "no icon"

Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
xvfb=$!
sleep 3
rm -rf /root/.local/state/tortty-python
DISPLAY=:99 setsid /root/.local/bin/tortty-python --debug-socket "$SOCK" >/tmp/app.log 2>&1 &
sleep 8
if ps -eo args | grep -q '[p]ipx/venvs/tortty-python/bin/python'; then
    ok "the process stays up under Xvfb"
else
    fail "the process did not survive: $(tail -2 /tmp/app.log | tr '\n' ' ')"
fi
win=
for w in $(DISPLAY=:99 xdotool search --class tortty-python 2>/dev/null); do
    wh=$(DISPLAY=:99 xdotool getwindowgeometry --shell "$w" | awk -F= '/^WIDTH/{print $2}')
    [ "${wh:-0}" -gt 100 ] && win=$w
done
if [ -n "$win" ]; then
    geo=$(DISPLAY=:99 xdotool getwindowgeometry --shell "$win" | awk -F= '/WIDTH|HEIGHT/{printf "%sx", $2}')
    ok "window mapped: ${geo%x}"
    DISPLAY=:99 import -window "$win" /tmp/shot.png 2>/dev/null
    sd=$(identify -format '%[fx:standard_deviation]' /tmp/shot.png 2>/dev/null || echo 0)
    if awk -v s="$sd" 'BEGIN{exit !(s > 0.001)}'; then
        ok "the window paints ($(wc -c </tmp/shot.png) bytes, deviation $sd)"
    else
        fail "the capture is uniform (deviation $sd): black window"
    fi
else
    fail "no window wider than 100px: $(tail -2 /tmp/app.log | tr '\n' ' ')"
fi

if [ -S "$SOCK" ]; then
    st=$(sockq '{"cmd":"state"}')
    cols=$(field "$st" cols 2>/dev/null); rows=$(field "$st" rows 2>/dev/null)
    tabs=$(field "$st" tabs 2>/dev/null)
    [ -n "${cols:-}" ] && [ -n "${rows:-}" ] && ok "socket answers: grid ${cols}x${rows}, tabs=$tabs" \
        || fail "socket did not answer: $(printf '%s' "$st" | head -c 120)"
    sockq '{"cmd":"keys","data":"ctrl+shift+t"}' >/dev/null
    sleep 1
    tabs2=$(field "$(sockq '{"cmd":"state"}')" tabs 2>/dev/null)
    [ "${tabs2:-0}" -gt "${tabs:-0}" ] 2>/dev/null \
        && ok "ctrl+shift+t opened a tab ($tabs -> $tabs2)" \
        || fail "ctrl+shift+t did not open a tab ($tabs -> $tabs2)"
    scr=$(sockq '{"cmd":"text","where":"screen"}')
    printf '%s' "$scr" | grep -q '"' && ok "the screen text is readable ($(printf '%s' "$scr" | wc -c) bytes)" \
        || fail "the screen text is not readable"
else
    fail "the debug socket did not appear"
fi

pkill -f 'pipx/venvs/tortty-python/bin/python' 2>/dev/null
sleep 1
kill "$xvfb" 2>/dev/null
wait "$xvfb" 2>/dev/null

bash /tmp/i.sh --uninstall >/tmp/un.txt 2>&1; rc=$?
[ "$rc" = 0 ] && ok "--uninstall exits 0" || fail "--uninstall exits $rc"
[ ! -d "$V" ] && ok "the venv is gone" || fail "the venv survived"
[ ! -f "$DESK" ] && ok "the shortcut is gone" || fail "the shortcut survived"

bash /tmp/i.sh >/tmp/inst3.txt 2>&1; rc=$?
ver=$("$V/bin/python" -c 'import tortty_python;print(tortty_python.__version__)' 2>/dev/null || echo '?')
[ "$rc" = 0 ] && [ "$ver" = "$v" ] && ok "install after uninstall: v$ver" \
    || fail "reinstall failed: rc=$rc v$ver"

echo "== flow: $fails failure(s)"
[ "$fails" = 0 ]
FLOW

# --- images -------------------------------------------------------------------
build() {   # build <target> <image>
    if [ "$REBUILD" -eq 0 ] && docker image inspect "$2" >/dev/null 2>&1; then
        echo "   image $2 cached (--rebuild to refresh)"
        return 0
    fi
    echo "   building $2 (apt runs here, once)"
    docker build -q --target "$1" -t "$2" "$WORK" >/dev/null || return 1
}

build base "$BASE_IMG" || { echo "release-check: base image build failed" >&2; exit 2; }
build ready "$READY_IMG" || { echo "release-check: ready image build failed" >&2; exit 2; }

# --- the two passes -----------------------------------------------------------
run_pass() {   # run_pass <check|flow> <image> <script>
    if [ "$SRC" = dist ]; then
        docker run --rm -e SRC=dist -e EXPECT="$EXPECT" -v "$DIST:/dist:ro" \
            -v "$WORK/lib.sh:/lib.sh:ro" -v "$WORK/$3:/$3:ro" "$2" bash "/$3"
    else
        docker run --rm -e SRC=url -e BASE_URL="$BASE_URL" -e EXPECT="$EXPECT" \
            -v "$WORK/lib.sh:/lib.sh:ro" -v "$WORK/$3:/$3:ro" "$2" bash "/$3"
    fi
}

echo "== assets and diagnosis (image without gi)"
run_pass check "$BASE_IMG" check.sh
check_rc=$?
echo "== install, window and socket (image with gi)"
run_pass flow "$READY_IMG" flow.sh
flow_rc=$?

if [ "$check_rc" = 0 ] && [ "$flow_rc" = 0 ]; then
    echo "PASSED  ${TAG:-latest}${DIST:+ (local artifacts)}: installs, opens and uninstalls"
    [ "$KEEP" -eq 1 ] && echo "harness kept in $WORK"
    exit 0
fi
echo "FAILED  ${TAG:-latest}${DIST:+ (local artifacts)}: check=$check_rc flow=$flow_rc (harness in $WORK)"
trap - EXIT INT TERM
exit 1
