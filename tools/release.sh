#!/usr/bin/env bash
# release.sh — publishes the version in tortty_python/__init__.py as a GitHub release.
#
# The owner says "make release"; this is what that means, in order: the tree is
# clean and pushed, the battery passes, the wheel is built, and one release is
# created with fixed asset names, so the install URL never changes:
#
#   https://github.com/bazoocaze/tortty-python/releases/latest/download/install.sh
#   https://github.com/bazoocaze/tortty-python/releases/latest/download/tortty-python.whl
#   https://github.com/bazoocaze/tortty-python/releases/latest/download/SHA256SUMS
#
# The tag comes from __version__ (never typed by hand), so tag and package can
# not diverge; if that version is already released, the script stops and the fix
# is a version bump, not a flag. install.sh is published with @VERSION@ replaced
# by the tag it belongs to, so the script downloaded from /latest/ installs
# exactly the release it came from.
#
# Usage:
#   tools/release.sh                 releases the current __version__
#   tools/release.sh --dry-run       shows every step, publishes nothing
#   tools/release.sh --notes FILE    release notes from FILE (default: generated)
#   tools/release.sh --skip-tests    skips ./run-tests.sh (do not: it is the gate)
#
# Only the owner runs this (it pushes a tag and creates the release).
#
# MIT (see LICENSE).
set -euo pipefail

# $0 can be a bare name ("bash release.sh"): resolve it before any cd, or the
# help below cannot read its own header.
SELF=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
HERE=$(cd "$(dirname "$SELF")/.." && pwd)
cd "$HERE" || exit 1

PKG=tortty-python
REMOTE=origin
BRANCH=main
DRY=0; NOTES=""; TESTS=1
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)    DRY=1 ;;
        --notes)      NOTES="${2:-}"; shift || { echo "--notes needs a file" >&2; exit 2; } ;;
        --notes=*)    NOTES="${1#*=}" ;;
        --skip-tests) TESTS=0 ;;
        -h|--help)    awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$SELF"; exit 0 ;;
        *) echo "release: unknown option $1 (see -h)" >&2; exit 2 ;;
    esac
    shift
done

say()  { printf '%s\n' "$*"; }
die()  { printf 'release: %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then say "+ $*"; else "$@"; fi; }

VER=$(python3 -c 'import re,sys; print(re.search(r"__version__ = \"([^\"]+)\"", open("tortty_python/__init__.py").read()).group(1))')
TAG="v$VER"
say "== version $VER -> tag $TAG"

# -- preconditions -------------------------------------------------------------
[ -z "$(git status --porcelain --untracked-files=no)" ] || die "the working tree has uncommitted changes"
git fetch --quiet "$REMOTE" "$BRANCH"
[ "$(git rev-parse HEAD)" = "$(git rev-parse "$REMOTE/$BRANCH")" ] \
    || die "HEAD is not $REMOTE/$BRANCH: commit and push first"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
    die "tag $TAG already exists: bump the version first"
fi
grep -q '@VERSION@' install.sh || die "install.sh lost its @VERSION@ placeholder"
grep -q "^## \[$TAG\]" docs/HISTORY.md 2>/dev/null || say "   (no $TAG heading in docs/HISTORY.md; the notes come from git)"

# -- the gate ------------------------------------------------------------------
if [ "$TESTS" = 1 ]; then
    say "== battery"
    run ./run-tests.sh
else
    say "== battery SKIPPED (--skip-tests)"
fi

# -- build + assets ------------------------------------------------------------
say "== build"
run rm -rf dist
run uv build
WHL=$(ls dist/tortty_python-"$VER"-*.whl 2>/dev/null | head -1 || true)
SDIST=$(ls dist/tortty_python-"$VER".tar.gz 2>/dev/null | head -1 || true)
[ -n "$WHL" ] && [ -n "$SDIST" ] || die "uv build did not produce $VER artifacts (see dist/)"

# Fixed names are the whole point: /releases/latest/download/ only works when the
# asset name does not change from release to release.
say "== assets"
run cp "$WHL" dist/$PKG.whl
if [ "$DRY" = 1 ]; then
    say "+ sed s|@VERSION@|$TAG|g install.sh > dist/install.sh"
else
    sed "s|@VERSION@|$TAG|g" install.sh > dist/install.sh
    chmod +x dist/install.sh
fi
if [ "$DRY" = 1 ]; then
    say "+ (cd dist && sha256sum $PKG.whl > SHA256SUMS)"
else
    (cd dist && sha256sum "$PKG.whl" > SHA256SUMS)
    say "   sha256 $(cut -d' ' -f1 dist/SHA256SUMS)"
fi

# -- publish -------------------------------------------------------------------
say "== tag and release"
run git tag -a "$TAG" -m "$PKG $VER"
run git push "$REMOTE" "$TAG"
if [ -n "$NOTES" ]; then
    [ -f "$NOTES" ] || die "notes file not found: $NOTES"
    run gh release create "$TAG" --title "$PKG $VER" --notes-file "$NOTES" \
        "dist/$PKG.whl" dist/SHA256SUMS dist/install.sh "$WHL" "$SDIST"
else
    run gh release create "$TAG" --title "$PKG $VER" --generate-notes \
        "dist/$PKG.whl" dist/SHA256SUMS dist/install.sh "$WHL" "$SDIST"
fi

say
if [ "$DRY" = 1 ]; then say "dry run: nothing published (would be $TAG)"; else say "released $TAG"; fi
say "  install:  curl -fsSL https://github.com/bazoocaze/$PKG/releases/latest/download/install.sh | bash"
say "  check:    curl -fsSL https://github.com/bazoocaze/$PKG/releases/latest/download/install.sh | bash -s -- --check"
