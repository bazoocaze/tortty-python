#!/bin/sh
# run.sh — abre/fecha o bzmux sem deixar instâncias órfãs.
#
# O bzmux é um experimento (terminal mínimo em Python); este runner existe
# porque usar `pkill -f bzmux.py` mata o próprio shell de quem chama (o
# padrão casa com a linha de comando) e já deixou janelas duplicadas abertas.
# Aqui o controle é por PID file: só mata o processo que NÓS subimos.
#
# Uso:
#   ./run.sh                 abre em background (log em /tmp/bzmux.log)
#   ./run.sh --fg            abre em foreground (vê os erros na hora)
#   ./run.sh --kill          fecha a instância aberta por este runner
#   ./run.sh --status        diz se há instância e qual o PID
#   ./run.sh --cmd 'mc'      comando inicial (default: $SHELL)
#   ./run.sh --quit-after N  fecha sozinho depois de N segundos
#   ./run.sh --dump-to ARQ   salva a grade visível ao sair
#
# MIT (ver LICENSE).
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
PIDFILE=/tmp/bzmux.pid
LOG=/tmp/bzmux.log

is_ours() {
    # o PID existe E ainda é um bzmux.py? (protege contra PID reciclado)
    [ -n "${1:-}" ] || return 1
    [ -d "/proc/$1" ] || return 1
    tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null | grep -q 'bzmux\.py'
}

kill_previous() {
    if [ -f "$PIDFILE" ]; then
        pid=$(cat "$PIDFILE" 2>/dev/null || true)
        if is_ours "$pid"; then
            kill "$pid" 2>/dev/null
            for _ in 1 2 3 4 5 6 7 8 9 10; do
                is_ours "$pid" || break
                sleep 0.2
            done
            is_ours "$pid" && kill -9 "$pid" 2>/dev/null
            echo "fechou bzmux anterior (pid $pid)"
        fi
        rm -f "$PIDFILE"
    fi
}

MODE=bg
CMD=${SHELL:-/bin/bash}
QUIT=0
DUMP=""
while [ $# -gt 0 ]; do
    case "$1" in
        --fg) MODE=fg ;;
        --kill) MODE=kill ;;
        --status) MODE=status ;;
        --cmd) shift; CMD=${1:-$CMD} ;;
        --quit-after) shift; QUIT=${1:-0} ;;
        --dump-to) shift; DUMP=${1:-} ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "opção desconhecida: $1" >&2; exit 2 ;;
    esac
    shift
done

case "$MODE" in
    kill)
        kill_previous
        echo "bzmux fechado"
        exit 0
        ;;
    status)
        if [ -f "$PIDFILE" ] && is_ours "$(cat "$PIDFILE" 2>/dev/null)"; then
            echo "bzmux rodando (pid $(cat "$PIDFILE"))"
        else
            echo "bzmux não está rodando"
        fi
        exit 0
        ;;
esac

kill_previous

set -- --cmd "$CMD"
[ "$QUIT" != 0 ] && set -- "$@" --quit-after "$QUIT"
[ -n "$DUMP" ] && set -- "$@" --dump-to "$DUMP"

if [ "$MODE" = fg ]; then
    exec python3 "$HERE/bzmux.py" "$@"
fi

: > "$LOG"
setsid nohup python3 "$HERE/bzmux.py" "$@" >>"$LOG" 2>&1 &
pid=$!
echo "$pid" > "$PIDFILE"
sleep 0.6
if is_ours "$pid"; then
    echo "bzmux aberto (pid $pid), log em $LOG"
else
    echo "bzmux FALHOU ao subir; log:" >&2
    tail -20 "$LOG" >&2
    rm -f "$PIDFILE"
    exit 1
fi
