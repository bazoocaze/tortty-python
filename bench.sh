#!/bin/sh
# bench.sh — roda a escada do doom-fire e imprime fps, MB/s, bytes/frame e os
# tempos de desenho e de pty numa tabela. Com o padrão (~300 frames) leva uns
# 10 s no total; a janela abre e fecha quatro vezes, uma etapa por vez.
#
# Uso: ./bench.sh [--frames N] [--cols C] [--rows R] [--font-size P] [-h]
#
# A condição é travada pelo GRID (padrão 61x18, fonte 13 — a janela que sobra
# sem estar maximizada), não pela janela em pixels —
# quem faz isso é o tools/benchrun.py: ele sobe o app com o socket, pede o grid
# ao próprio app, ajusta com `resize` até bater, confere e só então digita o
# doomfire no pty. Se o grid não bater, a etapa falha e nada é impresso: número
# de outra condição não entra na tabela. O porquê está no cabeçalho do
# benchrun.py e em docs/BENCHMARKS.md.
#
# Roda no display atual (precisa de display: a medição desenha de verdade).
# Feche o que estiver desenhando: dois terminais disputando CPU contaminam.
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
        -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) echo "opção desconhecida: $1" >&2; exit 2 ;;
    esac
done

case "$FRAMES" in
    ''|*[!0-9]*|0) echo "--frames precisa de um inteiro > 0" >&2; exit 2 ;;
esac

[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || {
    echo "sem display: abra numa sessão gráfica (a medição desenha de verdade)" >&2
    exit 1
}

GOV=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true)
case "$GOV" in
    powersave|conservative)
        echo "aviso: governor '$GOV' mede 2-5x menos que schedutil/performance" >&2 ;;
esac
[ -n "$GOV" ] || GOV="?"

# Uma etapa: o benchrun.py sobe o app, trava o grid, digita a carga e fecha.
# Argumentos extras são repassados a ele (--env K=V para as sondas).
stage() {
    _slug=$1; _label=$2; shift 2
    _err=/tmp/bzmux-bench-$_slug.err
    rm -f "$_err"
    if ! _txt=$(python3 "$HERE/tools/benchrun.py" --frames "$FRAMES" \
            --cols "$COLS" --rows "$ROWS" --font-size "$FONT" \
            --stats "/tmp/bzmux-bench-$_slug.txt" "$@" 2>"$_err"); then
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

GRADE="?"
echo "bzmux bench — doom-fire, $FRAMES frames ($(date '+%Y-%m-%d %H:%M'))"
printf '%-26s %7s %7s %12s %10s %9s %7s\n' \
    "etapa" "fps" "MB/s" "bytes/frame" "draw ms" "pty ms" "GHz méd/pico"
stage full "full (IO+parse+draw)"
stage nodraw "NODRAW (IO+parse)" --env PYTERM_NODRAW=1
stage noparse "NOPARSE+NODRAW (IO)" --env PYTERM_NOPARSE=1 --env PYTERM_NODRAW=1

# O gerador isolado não abre terminal: mede o teto do próprio gerador.
_out=/tmp/bzmux-bench-gen.txt
rm -f "$_out"
python3 "$HERE/tools/doomfire.py" --fps 0 --frames "$FRAMES" --stats-to "$_out" \
    >/dev/null 2>&1
printf "%-26s %7s %7s %12s %10s %9s %13s\n" "gerador isolado" \
    "$(sed -n 's/^fps  *\([0-9.]*\)$/\1/p' "$_out" | tail -1)" \
    "$(sed -n 's/.*(\([0-9.]*\) MB\/s).*/\1/p' "$_out" | tail -1)" \
    "$(sed -n 's/^bytes\/frame *\([0-9]*\)$/\1/p' "$_out" | tail -1)" "-" "-" "-"

echo
echo "governor: $GOV | grade: $GRADE (alvo ${COLS}x$ROWS, fonte $FONT) | display: ${DISPLAY:-${WAYLAND_DISPLAY:-?}}"
echo "protocolo e números de referência: docs/BENCHMARKS.md"
