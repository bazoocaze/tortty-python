#!/bin/sh
# run.sh — roda o tortty-python aqui, para testar rápido. Passa os argumentos para o
# app e sai com o código dele; nada de instância em background.
#
# É o script para rodar o terminal à mão. Durante o desenvolvimento
# o caminho é o debug.sh: ele sobe por este script (mesmo interpretador), mas
# com log em /tmp/tortty-python.log, PID file, --kill e --status.
#
# Uso: ./run.sh [--cmd CMD] [--quit-after SEG] [--dump-to ARQ] [-h]
#
# MIT (ver LICENSE).
set -u

HERE=$(cd "$(dirname "$0")" && pwd)

# O app roda no python do venv do uv quando ele enxerga o PyGObject; senão cai
# para o python do sistema (o gi do venv só aparece se ele foi criado com
# --system-site-packages, porque o PyGObject vem da distro).
PY=python3
if [ -x "$HERE/.venv/bin/python" ]; then
    if "$HERE/.venv/bin/python" -c 'import gi' 2>/dev/null; then
        PY=$HERE/.venv/bin/python
    else
        echo "aviso: .venv não vê o PyGObject; recrie com" >&2
        echo "  uv venv --system-site-packages && uv sync" >&2
        echo "usando o python do sistema por enquanto" >&2
    fi
fi

# O app é um pacote (`python -m tortty-python`), então o repositório precisa estar no
# sys.path. Usar PYTHONPATH em vez de `cd "$HERE"` de propósito: o shell que o
# app abre herda o diretório de quem chamou o run.sh.
PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

exec "$PY" -m tortty-python "$@"
