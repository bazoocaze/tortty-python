#!/bin/sh
# run-tests.sh — roda a bateria de testes. Não precisa de display.
#
# Os mesmos checks (bzmux/checks.py) passam por dois runners: o --selftest, que
# não depende de nada, e o pytest. Rodar os dois é de propósito: se o caminho
# dos testes passar a puxar gi/cairo, o --selftest quebra e o pytest não.
#
# Uso:
#   ./run-tests.sh                 selftest + pytest
#   ./run-tests.sh -k graphics -x  argumentos extras vão para o pytest
#   ./run-tests.sh --selftest-only só o runner sem dependências
#
# Sai 0 só se tudo passar.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE" || exit 1

ONLY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --selftest-only) ONLY=1; shift ;;
        -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) break ;;
    esac
done

fails=0

echo "== selftest (sem dependências, sem display)"
python3 -m bzmux --selftest || fails=1

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
