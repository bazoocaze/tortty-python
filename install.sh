#!/usr/bin/env bash
# install.sh — instala o bzmux na máquina (o caminho "uma linha").
#
# O app usa o PyGObject do sistema, então o instalador: confere/instala as
# dependências da distro, acha o python3 que enxerga o gi, garante o pipx e
# instala por ele com --system-site-packages. No fim roda o --selftest.
#
# Uso (do repositório clonado — caminho recomendado):
#   ./install.sh              instala (pede sudo só se faltar dependência)
#   ./install.sh --uninstall  remove pelo pipx
#   ./install.sh --dry-run    mostra cada comando e não executa nada
#   ./install.sh --no-deps    não instala pacotes do sistema
#   ./install.sh --no-shortcut  não cria o atalho no menu do sistema
#
# Uso (sem clonar; o repo é privado, então precisa de gh autenticado):
#   gh api -H "Accept: application/vnd.github.raw" \
#       /repos/bazoocaze/pybzmux/contents/install.sh | bash
#
# Depois que o repositório for público, o clássico passa a valer:
#   curl -fsSL https://raw.githubusercontent.com/bazoocaze/pybzmux/main/install.sh | bash
# (leia antes: `curl -fsSL ... | less` — pipe para shell não tem desfazer)
#
# MIT (ver LICENSE).
set -euo pipefail

REPO=${BZMU_GIT_URL:-git+ssh://git@github.com/bazoocaze/pybzmux.git}
PKG=bzmux

say()  { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
die()  { warn "bzmux: $*"; exit 1; }

DRY=0; DEPS=1; SHORTCUT=1; MODE=install
for a in "$@"; do
    case "$a" in
        --dry-run)   DRY=1 ;;
        --no-deps)   DEPS=0 ;;
        --shortcut)  SHORTCUT=1 ;;
        --no-shortcut) SHORTCUT=0 ;;
        --uninstall) MODE=uninstall ;;
        -h|--help)   awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) die "opção inválida: $a (use -h)" ;;
    esac
done

run() {
    if [ "$DRY" = 1 ]; then say "+ $*"; else "$@"; fi
}

# -- qual python3 enxerga o gi + cairo ----------------------------------------
gi_python() {
    local p
    for p in "$@"; do
        case "$p" in
            */*) [ -x "$p" ] || continue ;;
            *)   p=$(command -v "$p" 2>/dev/null) || continue ;;
        esac
        "$p" -c 'import gi, cairo' 2>/dev/null && { printf '%s' "$p"; return 0; }
    done
    return 1
}

# -- pacotes do sistema por gerenciador -------------------------------------
pm_install() {
    local pm
    for pm in apt-get dnf pacman zypper; do command -v "$pm" >/dev/null 2>&1 && break; done
    command -v "$pm" >/dev/null 2>&1 || { warn "gerenciador de pacotes não reconhecido"; return 1; }

    local SUDO=""
    [ "$(id -u)" = 0 ] || { command -v sudo >/dev/null 2>&1 && SUDO="sudo" || { warn "sem sudo e sem root"; return 1; }; }

    case "$pm" in
        apt-get) run $SUDO apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 git pipx ;;
        dnf)     run $SUDO dnf install -y python3-gobject python3-cairo gtk3 git pipx ;;
        pacman)  run $SUDO pacman -Sy --needed --noconfirm python-gobject python-cairo gtk3 git python-pipx ;;
        zypper)  run $SUDO zypper --non-interactive install python3-gobject python3-cairo gtk3 git pipx ;;
    esac
}

# -- instalacao -------------------------------------------------------------
install() {
    [ "$(uname -s)" = "Linux" ] || die "só Linux por enquanto (Windows/macOS: ver docs/BACKLOG.md, P30)"

    local here="" spec="$REPO"
    here=$(cd "$(dirname "${BASH_SOURCE[0]:-/dev/null}")" 2>/dev/null && pwd) || here=""
    if [ -n "$here" ] && [ -f "$here/pyproject.toml" ] && grep -q '^name = "bzmux"' "$here/pyproject.toml"; then
        spec="$here"
        say "== instalando da árvore local: $here"
    else
        say "== instalando de $REPO"
    fi

    # deps: pycairo/gi/gtk3 do sistema
    if [ "$DEPS" = 1 ] && ! gi_python python3 >/dev/null; then
        say "== dependências do sistema ausentes; instalando com o gerenciador"
        pm_install || die "instale à mão: python3-gi python3-gi-cairo gir1.2-gtk-3.0"
    fi
    PY=$(gi_python python3 /usr/bin/python3 /usr/bin/python3.*) \
        || die "nenhum python3 com PyGObject+pycairo (apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0)"
    say "== python com gi: $PY"

    if [ "$spec" = "$REPO" ]; then
        command -v git >/dev/null 2>&1 || die "git é necessário para instalar do repositório"
        git ls-remote "$REPO" >/dev/null 2>&1 \
            || die "sem acesso a $REPO — o repositório é privado, configure a chave ssh (ou use um clone local)"
    fi

    if ! command -v pipx >/dev/null 2>&1; then
        say "== pipx não encontrado; instalando"
        pm_install || die "instale o pipx (apt install pipx) e rode de novo"
        if [ "$DRY" = 0 ]; then
            command -v pipx >/dev/null 2>&1 \
                || die "pipx continua fora do PATH; abra um shell novo e rode de novo"
        fi
    fi

    # --force: reexecutar atualiza (a versão no pyproject é fixa)
    run pipx install --force --system-site-packages --python "$PY" "$spec"

    if [ "$DRY" = 1 ]; then say "+ bzmux --selftest"; return 0; fi
    command -v "$PKG" >/dev/null 2>&1 || die "instalou, mas '$PKG' não está no PATH: adicione ~/.local/bin"
    say "== verificação"
    "$PKG" --selftest | tail -1

    if [ "$SHORTCUT" = 1 ]; then
        say "== atalho no menu do sistema"
        run "$PKG" --install-shortcut
    fi

    say
    say "pronto: rode '$PKG' (atualizar: rode este instalador de novo)"
}

uninstall() {
    # o atalho sai antes: depois do pipx uninstall o comando não existe mais
    if command -v "$PKG" >/dev/null 2>&1; then
        run "$PKG" --remove-shortcut || true
    fi
    command -v pipx >/dev/null 2>&1 || die "pipx não encontrado; a instalação já não existe"
    run pipx uninstall "$PKG"
}

case "$MODE" in
    install)   install ;;
    uninstall) uninstall ;;
esac
