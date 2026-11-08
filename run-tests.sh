#!/bin/sh
# run-tests.sh — roda a bateria de testes e o lint. Não precisa de display.
#
# Os mesmos checks (tortty_python/checks.py) passam por dois runners: o --selftest, que
# não depende de nada, e o pytest. Rodar os dois é de propósito: se o caminho
# dos testes passar a puxar gi/cairo, o --selftest quebra e o pytest não.
#
# O ruff roda em dois modos: `check` (E, F, I, W) e `format --check`, que só
# verifica — quem formata é `ruff format .`, à mão, quando quiser.
#
# Uso:
#   ./run-tests.sh                 lint + selftest + pytest
#   ./run-tests.sh -k graphics -x  argumentos extras vão para o pytest
#   ./run-tests.sh --selftest-only só o runner sem dependências
#   ./run-tests.sh --no-lint       pula o ruff
#
# Sai 0 só se tudo passar.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE" || exit 1

ONLY=0
LINT=1
while [ $# -gt 0 ]; do
    case "$1" in
        --selftest-only) ONLY=1; shift ;;
        --no-lint) LINT=0; shift ;;
        -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) break ;;
    esac
done

fails=0

if [ "$LINT" = 1 ]; then
    echo "== ruff (check + format --check)"
    if command -v uv >/dev/null 2>&1; then
        RUFF="uv run ruff"
    elif command -v ruff >/dev/null 2>&1; then
        RUFF="ruff"
    else
        RUFF=""
        echo "ruff ausente: rode 'uv sync' (lint pulado)" >&2
    fi
    if [ -n "$RUFF" ]; then
        $RUFF check tortty_python tools tests || fails=1
        $RUFF format --check tortty_python tools tests || fails=1
    fi
    echo
fi

echo "== selftest (sem dependências, sem display)"
python3 -m tortty_python --selftest || fails=1

if [ "$ONLY" = 0 ]; then
    echo
    echo "== pytest"
    if command -v uv >/dev/null 2>&1; then
        uv run pytest -q "$@" || fails=1
    elif python3 -c 'import pytest' 2>/dev/null; then
        python3 -m pytest -q "$@" || fails=1
    else
        echo "pytest ausente: rode 'uv sync' (só o selftest rodou)" >&2
    fi
fi

echo
if [ "$fails" = 0 ]; then
    echo "TESTES OK"
else
    echo "TESTES FALHARAM" >&2
fi
exit "$fails"
