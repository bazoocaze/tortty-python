#!/bin/sh
# bench.sh — roda a escada do doom-fire e imprime fps, MB/s, bytes/frame e os
# tempos de desenho e de pty numa tabela. Com o padrão (~300 frames) leva uns
# 10 s no total; a janela abre e fecha quatro vezes, uma etapa por vez.
#
# Uso: ./bench.sh [--frames N] [-h]
#
# Precisa de display (abre a janela). Não rode com outro bzmux desenhando: dois
# terminais disputando CPU e compositor contaminam o número. Protocolo,
# armadilhas e os números de referência ficam em docs/BENCHMARKS.md — este
# script só produz a medição, não guarda valor.
#
# MIT (ver LICENSE).
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
FRAMES=300

while [ $# -gt 0 ]; do
    case "$1" in
        --frames)
            [ $# -ge 2 ] || { echo "falta o valor de --frames" >&2; exit 2; }
            FRAMES=$2; shift 2 ;;
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

PIDFILE=/tmp/bzmux.pid
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
    echo "aviso: já há um bzmux rodando (debug.sh); dois desenhando contaminam" >&2
fi

GOV=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true)
case "$GOV" in
    powersave|conservative)
        echo "aviso: governor '$GOV' mede 2-5x menos que schedutil/performance" >&2 ;;
esac
[ -n "$GOV" ] || GOV="?"

# Uma etapa: sobe o app com PYTERM_PROF, espera o doomfire escrever o stats e
# fecha com SIGTERM (o handler grava o prof e o dump no fim).
stage() {
    _slug=$1; _label=$2; shift 2
    _out=/tmp/bzmux-bench-$_slug.txt
    _log=/tmp/bzmux-bench-$_slug.log
    rm -f "$_out" "$_log"
    _freq=/tmp/bzmux-bench-$_slug.freq
    rm -f "$_freq"
    ( while kill -0 "$$" 2>/dev/null; do
          cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null >> "$_freq"
          sleep 0.2
      done ) &
    _sampler=$!
    env "$@" PYTERM_PROF=1 "$HERE/run.sh" \
        --cmd "python3 $HERE/tools/doomfire.py --fps 0 --frames $FRAMES --stats-to $_out" \
        >"$_log" 2>&1 &
    _pid=$!
    _i=0
    while [ ! -s "$_out" ]; do
        kill -0 "$_pid" 2>/dev/null || break
        _i=$((_i + 1))
        [ "$_i" -gt $((FRAMES / 2 + 60)) ] && break
        sleep 0.2
    done
    kill -TERM "$_pid" 2>/dev/null
    wait "$_pid" 2>/dev/null
    kill "$_sampler" 2>/dev/null

    _fps=$(sed -n 's/^fps  *\([0-9.]*\)$/\1/p' "$_out" | tail -1)
    _mbs=$(sed -n 's/.*(\([0-9.]*\) MB\/s).*/\1/p' "$_out" | tail -1)
    _bpf=$(sed -n 's/^bytes\/frame *\([0-9]*\)$/\1/p' "$_out" | tail -1)
    _grade=$(sed -n 's/^grade  *\([0-9]*x[0-9]*\).*/\1/p' "$_out" | tail -1)
    _draw=$(sed -n 's/.*draw [0-9]*x \([0-9.]*\)ms.*/\1/p' "$_log" | tail -1)
    _pty=$(sed -n 's/.*pty [0-9]*x \([0-9.]*\)ms.*/\1/p' "$_log" | tail -1)
    [ -n "$_fps" ] || _fps="-"
    [ -n "$_mbs" ] || _mbs="-"
    [ -n "$_bpf" ] || _bpf="-"
    [ -n "$_draw" ] || _draw="-"
    [ -n "$_pty" ] || _pty="-"
    _ghz=$(awk '{s += $1; n++; if ($1 > m) m = $1}
                 END {if (n) printf "%.2f/%.2f", s / n / 1e6, m / 1e6; else printf "-"}' \
                "$_freq" 2>/dev/null)
    [ -n "$_ghz" ] || _ghz="-"
    printf "%-26s %7s %7s %12s %10s %9s %13s\n" \
        "$_label" "$_fps" "$_mbs" "$_bpf" "$_draw" "$_pty" "$_ghz"
    if [ "$_fps" = "-" ]; then
        echo "  (a etapa não produziu stats; fim do log:)" >&2
        tail -3 "$_log" >&2 2>/dev/null
    fi
    [ -n "$_grade" ] && GRADE=$_grade
    return 0
}

GRADE="?"
echo "bzmux bench — doom-fire, $FRAMES frames ($(date '+%Y-%m-%d %H:%M'))"
printf '%-26s %7s %7s %12s %10s %9s %7s\n' \
    "etapa" "fps" "MB/s" "bytes/frame" "draw ms" "pty ms" "GHz méd/pico"
stage full "full (IO+parse+draw)"
stage nodraw "NODRAW (IO+parse)" PYTERM_NODRAW=1
stage noparse "NOPARSE+NODRAW (IO)" PYTERM_NOPARSE=1 PYTERM_NODRAW=1

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
echo "governor: $GOV | grade: $GRADE | referência e protocolo: docs/BENCHMARKS.md"
