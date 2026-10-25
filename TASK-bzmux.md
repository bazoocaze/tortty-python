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

P9 (ligaduras/shaping) e P10 (fallback de fonte) — na prática caem juntos na
migração para Pango. P14 (largura da lateral que não fica fixa) vem antes do
P15 (tela bagunçada ao subir o `pi`), que provavelmente é consequência do P14.
Detalhe em [`docs/BACKLOG.md`](docs/BACKLOG.md).

## Documentos

O índice dos documentos e a regra de onde cada fato mora estão no
[`AGENTS.md`](AGENTS.md).
