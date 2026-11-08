#!/bin/sh
# debug.sh — abre/fecha o tortty-python durante o desenvolvimento, sem deixar
# instâncias órfãs. Para só rodar o terminal e ver funcionando, use o run.sh.
#
# Existe porque `pkill -f tortty-python` mata o próprio shell de quem chama (o
# padrão casa com a linha de comando) e já deixou janelas duplicadas abertas.
# Aqui o controle é por PID file: só mata o processo que NÓS subimos, e o log
# fica em /tmp/tortty-python.log em vez de se perder. O app em si é sempre subido pelo
# run.sh, que é quem escolhe o interpretador.
#
# Uso:
#   ./debug.sh                 abre em background (log em /tmp/tortty-python.log)
#   ./debug.sh --fg            foreground (vê os erros na hora)
#   ./debug.sh --kill          fecha a instância aberta por este runner
#   ./debug.sh --status        diz se há instância e qual o PID
#   ./debug.sh ARGS            o resto vai para o app (--cmd, --quit-after,
#                              --dump-to); veja ./run.sh --help
#
# MIT (ver LICENSE).
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
PIDFILE=/tmp/tortty-python.pid
LOG=/tmp/tortty-python.log

is_ours() {
    # o PID existe E ainda é um tortty-python? (protege contra PID reciclado). As duas
    # formas válidas: `python -m tortty_python` (run.sh) e o script do console
    # (`/.../bin/tortty-python`, do pipx). O `.py` no fim não casa, de propósito.
    [ -n "${1:-}" ] || return 1
    [ -d "/proc/$1" ] || return 1
    _cmd=$(tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null)
    case " $_cmd" in
        *" -m tortty_python "*) return 0 ;;
        *"/tortty-python "*) return 0 ;;
    esac
    return 1
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
            echo "fechou tortty-python anterior (pid $pid)"
        fi
        rm -f "$PIDFILE"
    fi
}

MODE=bg
while [ $# -gt 0 ]; do
    case "$1" in
        --fg) MODE=fg; shift ;;
        --kill) MODE=kill; shift ;;
        --status) MODE=status; shift ;;
        -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) break ;;
    esac
done

case "$MODE" in
    kill)
        kill_previous
        echo "tortty-python fechado"
        exit 0
        ;;
    status)
        if is_ours "$(cat "$PIDFILE" 2>/dev/null)"; then
            echo "tortty-python rodando (pid $(cat "$PIDFILE"))"
        else
            echo "tortty-python não está rodando"
        fi
        exit 0
        ;;
esac

kill_previous

if [ "$MODE" = fg ]; then
    exec "$HERE/run.sh" "$@"
fi

: > "$LOG"
setsid nohup "$HERE/run.sh" "$@" >>"$LOG" 2>&1 &
pid=$!
echo "$pid" > "$PIDFILE"
sleep 0.6
if is_ours "$pid"; then
    echo "tortty-python aberto (pid $pid), log em $LOG"
else
    echo "tortty-python FALHOU ao subir; log:" >&2
    tail -20 "$LOG" >&2
    rm -f "$PIDFILE"
    exit 1
fi
