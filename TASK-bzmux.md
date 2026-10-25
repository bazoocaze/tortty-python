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

P9 (ligaduras/shaping) e P10 (fallback de fonte) — caem juntos na migração para
Pango, e são os dois últimos. O P10 já aparece no `pi` (as barras `bh/P/X` são
glifos que a fonte não tem). O doom-fire (P16, feito) deixou a linha de base do
antes/depois do P9: 0,6 MB/s contra 15,9 MB/s do kitty (26x) na mesma grade
68×20, com parse em 61% do tempo e desenho em 37% (12,8 ms por frame de 1360
células). Detalhe, protocolo e armadilhas em
[`docs/DOOM-FIRE.md`](docs/DOOM-FIRE.md); o backlog em
[`docs/BACKLOG.md`](docs/BACKLOG.md).

## Documentos

O índice dos documentos e a regra de onde cada fato mora estão no
[`AGENTS.md`](AGENTS.md).
