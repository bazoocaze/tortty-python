# TASK-bzmux — status

Status (2026-10-26): experimento funcional. Roda shell, `mc` e `vim`; tem mouse
com seleção/cópia, histórico com wheel, reflow, truecolor, protocolos de teclado
e de imagens do kitty, bracketed paste, abas e workspaces. O que funciona, os
limites de propósito e o resultado da medição estão no `README.md`; não é
produto nem caminho de produção.

Verificado nesta data: `./run-tests.sh` (bateria sem display) e a interação à
mão com `tools/xtest.py`.

## Por onde retomar

```sh
./run-tests.sh                              # bateria, sem display
./debug.sh --cmd 'mc -d /usr/share'         # abre com log em /tmp/bzmux.log
```

Nada pela metade: árvore limpa, tudo commitado.

## Fila

Vazia: P1–P18 concluídos (o P9/P10, o último par, saiu com o desenho por Pango —
custo medido no [`docs/HISTORY.md`](docs/HISTORY.md) e a linha de base nova no
[`docs/DOOM-FIRE.md`](docs/DOOM-FIRE.md): bzmux 0,5 MB/s contra 15,9 MB/s do
kitty, 32x, com desenho em 41% e parse em 57%).

O que não é item de backlog, e sim limite registrado — caractere largo sem
`wcwidth`, protocolo de teclado do kitty parcial, sequência não interpretada,
sem configuração/tema, vazão ~30x menor que nativo — está em
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md), com a razão de cada um. Antes de tratar algo
como falta, checar lá: pode ser decisão.

## Documentos

O índice dos documentos e a regra de onde cada fato mora estão no
[`AGENTS.md`](AGENTS.md).
