#!/bin/sh
# bench.sh — roda a escada do doom-fire e imprime fps, MB/s, bytes/frame e os
# tempos de desenho e de pty numa tabela, em dois displays: o atual e um Xvfb
# privado. Com o padrão (~300 frames) leva uns 20 s no total; a janela abre e
# fecha seis vezes, uma etapa por vez.
#
# Uso (da raiz do repositório):
#   ./tools/bench.sh [--frames N] [--cols C] [--rows R] [--font-size P] [--xvfb] [-h]
#
# A condição é travada pelo GRID (padrão 61x18, fonte 13 — a janela que sobra
# sem estar maximizada), não pela janela em pixels: quem faz isso é o
# tools/benchrun.py — ele sobe o app com o socket, pede o grid ao próprio app,
# ajusta com `resize` até bater, confere e só então digita o doomfire no pty. Se
# o grid não bater, a etapa falha e nada é impresso: número de outra condição
# não entra na tabela. O porquê está no cabeçalho do benchrun.py e em
# docs/BENCHMARKS.md.
#
# Os dois displays entram de propósito, sem argumento: o número do X real
# depende do caminho do servidor (o :0 do desktop usa glamor, onde cada
# preenchimento do cairo vira trabalho de GL) e o do Xvfb não — medir os dois na
# mesma execução é o que mostra quanto é código e quanto é servidor. O display
# de cada linha sai na tabela. `--xvfb` mede só o virtual (útil sem display real
# ou para comparar com os números históricos); `--sem-xvfb` mede só o atual.
#
# Roda no display atual: feche o que estiver desenhando, dois terminais
# disputando CPU contaminam. O Xvfb sobe sozinho num display livre (:99..:129),
# 1600x1000, sem WM, compositor ou outro cliente — e é morto no fim.
# Protocolo, armadilhas e os números de referência: docs/BENCHMARKS.md — este
# script só produz a medição, não guarda valor.
#
# MIT (ver LICENSE).
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
FRAMES=300
COLS=61
ROWS=18
FONT=13
QUER_REAL=1
QUER_XVFB=1
XVFB_PID=""
XVFB_DISPLAY=""
XVFB_W=${XVFB_W:-1600}
XVFB_H=${XVFB_H:-1000}

while [ $# -gt 0 ]; do
    case "$1" in
        --frames)
            [ $# -ge 2 ] || { echo "falta o valor de --frames" >&2; exit 2; }
            FRAMES=$2; shift 2 ;;
        --cols)
            [ $# -ge 2 ] || { echo "falta o valor de --cols" >&2; exit 2; }
            COLS=$2; shift 2 ;;
        --rows)
            [ $# -ge 2 ] || { echo "falta o valor de --rows" >&2; exit 2; }
            ROWS=$2; shift 2 ;;
        --font-size)
            [ $# -ge 2 ] || { echo "falta o valor de --font-size" >&2; exit 2; }
            FONT=$2; shift 2 ;;
        --xvfb) QUER_REAL=0; QUER_XVFB=1; shift ;;
        --sem-xvfb) QUER_XVFB=0; shift ;;
        -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) echo "opção desconhecida: $1" >&2; exit 2 ;;
    esac
done

case "$FRAMES" in
    ''|*[!0-9]*|0) echo "--frames precisa de um inteiro > 0" >&2; exit 2 ;;
esac

if [ "$QUER_REAL" = 1 ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    echo "sem display real: medindo só no Xvfb (use --xvfb para calar este aviso)" >&2
    QUER_REAL=0
    QUER_XVFB=1
fi

GOV=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true)
case "$GOV" in
    powersave|conservative)
        echo "aviso: governor '$GOV' mede 2-5x menos que schedutil/performance" >&2 ;;
esac
[ -n "$GOV" ] || GOV="?"

encerra_xvfb() {
    if [ -n "$XVFB_PID" ]; then
        kill "$XVFB_PID" 2>/dev/null
        XVFB_PID=""
    fi
}
trap 'encerra_xvfb' EXIT INT TERM

# Sobe um Xvfb num display livre e deixa DISPLAY apontando para ele.
sobe_xvfb() {
    command -v Xvfb >/dev/null 2>&1 || return 1
    n=99
    while [ "$n" -lt 130 ]; do
        if [ ! -e "/tmp/.X$n-lock" ] && [ ! -e "/tmp/.X11-unix/X$n" ]; then
            break
        fi
        n=$((n + 1))
    done
    [ "$n" -lt 130 ] || return 1
    Xvfb ":$n" -screen 0 "${XVFB_W}x${XVFB_H}x24" -nolisten tcp >/dev/null 2>&1 &
    XVFB_PID=$!
    XVFB_DISPLAY=":$n"
    # Só mede depois que o socket do X existe: sem isso o GTK sai antes.
    i=0
    while [ ! -e "/tmp/.X11-unix/X$n" ]; do
        i=$((i + 1))
        if [ "$i" -gt 50 ] || ! kill -0 "$XVFB_PID" 2>/dev/null; then
            encerra_xvfb
            return 1
        fi
        sleep 0.1
    done
    DISPLAY="$XVFB_DISPLAY"
    export DISPLAY
    return 0
}

# Uma etapa: o benchrun.py sobe o app, trava o grid, digita a carga e fecha.
# Argumentos extras são repassados a ele (--env K=V para as sondas).
stage() {
    _slug=$1; _label=$2; shift 2
    _err=/tmp/tortty-python-bench-$_slug.err
    rm -f "$_err"
    if ! _txt=$(python3 "$HERE/benchrun.py" --frames "$FRAMES" \
            --cols "$COLS" --rows "$ROWS" --font-size "$FONT" \
            --stats "/tmp/tortty-python-bench-$_slug.txt" "$@" 2>"$_err"); then
        echo "  etapa '$_label' sem número: $(tail -1 "$_err")" >&2
        printf "%-26s %7s %7s %12s %10s %9s %7s\n" "$_label" "-" "-" "-" "-" "-" "-"
        return 0
    fi
    _campo() { echo "$_txt" | sed -n "s/^$1  *//p" | head -1; }
    _grade=$(_campo grade)
    if [ "$GRADE" = "?" ]; then
        GRADE=$_grade
    elif [ "$_grade" != "$GRADE" ]; then
        echo "  aviso: grade $_grade != $GRADE; o número não é comparável" >&2
    fi
    printf "%-26s %7s %7s %12s %10s %9s %12s\n" "$_label" \
        "$(_campo fps)" "$(_campo mbs | sed 's/ MB\/s$//')" "$(_campo bpf)" \
        "$(_campo draw)" "$(_campo pty)" "$(_campo ghz)"
    return 0
}

# A escada de três etapas; o prefixo separa as linhas de cada display.
escada() {
    _pre=$1; _tag=$2
    stage "$_tag-full" "${_pre}full (IO+parse+draw)"
    stage "$_tag-nodraw" "${_pre}NODRAW (IO+parse)" --env PYTERM_NODRAW=1
    stage "$_tag-noparse" "${_pre}NOPARSE+NODRAW (IO)" \
        --env PYTERM_NOPARSE=1 --env PYTERM_NODRAW=1
}

GRADE="?"
TELA_REAL="${DISPLAY:-${WAYLAND_DISPLAY:-?}}"
echo "tortty-python bench — doom-fire, $FRAMES frames ($(date '+%Y-%m-%d %H:%M'))"
printf '%-26s %7s %7s %12s %10s %9s %7s\n' \
    "etapa" "fps" "MB/s" "bytes/frame" "draw ms" "pty ms" "GHz méd/pico"

if [ "$QUER_REAL" = 1 ]; then
    escada "" real
fi

TELA_XVFB=""
if [ "$QUER_XVFB" = 1 ]; then
    if sobe_xvfb; then
        TELA_XVFB="$XVFB_DISPLAY (Xvfb ${XVFB_W}x${XVFB_H}, sem WM/glamor)"
        escada "xvfb · " xvfb
        encerra_xvfb
        [ "$QUER_REAL" = 1 ] && export DISPLAY="$TELA_REAL"
    else
        echo "aviso: Xvfb indisponível; medindo só o display atual" >&2
    fi
fi

# O gerador isolado não abre terminal: mede o teto do próprio gerador.
_out=/tmp/tortty-python-bench-gen.txt
rm -f "$_out"
python3 "$HERE/doomfire.py" --fps 0 --frames "$FRAMES" --stats-to "$_out" \
    >/dev/null 2>&1
printf "%-26s %7s %7s %12s %10s %9s %13s\n" "gerador isolado" \
    "$(sed -n 's/^fps  *\([0-9.]*\)$/\1/p' "$_out" | tail -1)" \
    "$(sed -n 's/.*(\([0-9.]*\) MB\/s).*/\1/p' "$_out" | tail -1)" \
    "$(sed -n 's/^bytes\/frame *\([0-9]*\)$/\1/p' "$_out" | tail -1)" "-" "-" "-"

echo
if [ -n "$TELA_XVFB" ]; then
    _tela="$TELA_REAL (real) e $TELA_XVFB"
elif [ "$QUER_REAL" = 1 ]; then
    _tela="$TELA_REAL (real)"
else
    _tela="?"
fi
echo "governor: $GOV | grade: $GRADE (alvo ${COLS}x$ROWS, fonte $FONT) | display: $_tela"
echo "protocolo e números de referência: docs/BENCHMARKS.md"
