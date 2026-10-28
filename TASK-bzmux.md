# TASK-bzmux — status

Status (2026-10-27): aplicação real, em uso diário. Roda shell, `mc` e `vim`;
tem mouse com seleção/cópia, histórico com wheel, reflow, truecolor, protocolos
de teclado e de imagens do kitty, bracketed paste, abas e workspaces. O que
funciona, os limites de propósito e o resultado da medição estão no `README.md`;
não é produto distribuído: sem empacotamento, release nem suporte.

Verificado nesta data: `./run-tests.sh` (bateria sem display) e a interação à
mão com `tools/xtest.py`.

## Por onde retomar

```sh
./run-tests.sh                              # bateria, sem display
./debug.sh --cmd 'mc -d /usr/share'         # abre com log em /tmp/bzmux.log
```

Nada pela metade: árvore limpa, tudo commitado.

**Próximo alvo: o desenho.** O barato já foi feito (P24/P25: cor em float
cacheada e `show_layout_line`, `draw` 7,76 → 6,54 ms, pixels idênticos). O que
sobra está medido e no [`docs/BACKLOG.md`](docs/BACKLOG.md): P26 é o único que
ataca de verdade a emissão (`cr.show_glyphs`, 2,43 → 0,76 µs/run) e o preço é
sair do Pango — experimento com validação por pixel, não compromisso; P27
(dirty-rect / linha em surface) é estrutural e o doom-fire não mede. A
decomposição por etapa e o método estão em
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) (seção "Decomposição do desenho").
O P19 (telas reescritas dentro do `pi`) segue aberto e independente.

## Fila

P19 aberto: dentro do `pi`, a cada algumas etapas do turno a tela reescreve
várias telas de uma vez (investigação e sonda em
[`docs/BACKLOG.md`](docs/BACKLOG.md)).

P1–P23 concluídos — o último par (P9/P10,
desenho por Pango) com custo no [`docs/HISTORY.md`](docs/HISTORY.md) e a linha de
base e o número único em [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) (o desenho é
hoje a maior fatia do tempo).

O P20 (fast path de escape no parser) mexeu nessa decomposição: sem parse
(`PYTERM_NOPARSE=1`) o mesmo fogo chega perto do kitty (35 contra 40 MB/s) — o
que separa os dois hoje é o parser em Python, mais o desenho, não o IO. Com o fast path, o parse+grade ficou ~5x mais rápido; o P21 (linha em
branco compartilhada no scroll) cortou a rolagem de 38,4 para 10,9 µs/linha, e
o P22 (cache de parâmetros de CSI) levou o `dmesg` com cor de 2,0x para 2,4x
(165 → 43 ms sem cor, 189 → 79 ms com cor).
A "anomalia de desenho" que apareceu antes era o governor **`powersave`**, não
energia nem código (com `schedutil` o gerador isolado triplicou de fps). Próximo
alvo natural é o desenho — ver [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

O que não é item de backlog, e sim limite registrado — caractere largo sem
`wcwidth`, protocolo de teclado do kitty parcial, sequência não interpretada,
sem configuração/tema, vazão ~30x menor que nativo — está em
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md), com a razão de cada um. Antes de tratar algo
como falta, checar lá: pode ser decisão.

## Documentos

O índice dos documentos e a regra de onde cada fato mora estão no
[`AGENTS.md`](AGENTS.md).
