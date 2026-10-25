# Doom fire — carga de medição

Ferramenta: `tools/doomfire.py`. Item de backlog: P16 (concluído, ver
[HISTORY.md](HISTORY.md)).

## Por que

O caminho quente do bzmux é parser → grade de células → agrupamento por cor →
desenho no cairo. Para medir vazão não serve `seq 1 100000` (uma cor só) nem
`vim` (poucas células por frame): o pior caso é a tela inteira trocando de cor a
cada frame.

O doom-fire (efeito do port de PSX do Doom: buffer de intensidade 0..36
propagado de baixo para cima com decaimento e paleta de 37 tons) é exatamente
isso, e é sintético — não depende de app real nem de rede. Desenhado em
meio-bloco (`▀`, dois pixels por célula) com fg e bg truecolor **por célula**,
sem agrupar nada: cada célula custa dois escapes de 16 a 19 bytes.

## Como rodar

    python3 tools/doomfire.py                      # 30 fps até Ctrl+C
    python3 tools/doomfire.py --fps 0 --frames 1200 --stats-to /tmp/x.txt

| opção | efeito |
|---|---|
| `--fps N` | ritmo fixo; `0` solta a mão e quem limita é o terminal |
| `--frames N` | para depois de N frames; `0` (default) vai até Ctrl+C |
| `--stats-to ARQ` | estatísticas em arquivo (`-`, default, vai em stderr) |

`--fps 0 --stats-to` é o modo de medição: o fps alcançado é a vazão do terminal,
e o arquivo evita depender de ler a tela. Grade = tamanho do terminal
(`cols × lines`, buffer de `cols × 2·lines` pixels); o tool não redimensiona.

## O número

Uma execução, 1200 frames, grade de 51 colunas, `--fps 0` (2026-10-25):

| | fps | MB/s de escapes | bytes/frame |
|---|---|---|---|
| bzmux | 24,6 | 1,0 | ~39 KB |
| kitty | 412,6 | 15,6 | ~38 KB |

O bzmux fica com **100% de um core** durante a medição: ~40 ms por frame de
~1020 células, ou **~39 µs por célula**. O kitty faz o mesmo em ~2 ms.

O 1,0 MB/s casa com o número independente que já estava no README (0,7–1,9 MiB/s
de parse + grade em despejo contínuo) — cargas diferentes, mesma ordem de
grandeza, o que dá confiança de que o doom-fire está medindo o mesmo gargalo.

O que o número **não** diz: onde o tempo vai. O agregado (parse, agrupamento,
cairo) não é decomposto por esta medição; para isso é preciso instrumentar ou
usar perfilador, e o custo de desenho isolado é o que o README mede à parte
(~2 ms por frame de 1920 células).

## Protocolo (para comparar dois terminais)

1. mesmas colunas e mesmas linhas nos dois (no kitty:
   `kitty --override remember_window_size=no --override initial_window_width=51c
   --override initial_window_height=20c -e ...`; a janela do bzmux é 680 px, o
   que dá 51×20 com a lateral visível);
2. `--fps 0 --frames 1200 --stats-to ARQ` nos dois;
3. comparar fps e MB/s (o bytes/frame varia um pouco com o tamanho do escape).

## Como saber que está desenhando

Dump do bzmux (`kill -USR1 $(cat /tmp/bzmux.pid)`) traz `▀` em todas as linhas
da viewport (1020 células em 51×20) e a captura mostra o fogo. Se o dump tiver
`▀` e a tela estiver preta, o problema é no desenho, não no tool.

## Armadilhas

- **Fonte sem `▀`**: a célula ainda tem bg e fg, então o fogo aparece como
  faixas de cor mesmo sem o glifo; se nem as faixas aparecem, o problema não é o
  glifo.
- **SGR na saída**: sem `\033[0m` as estatísticas herdam a última cor do fogo
  (texto com fundo amarelo). Já corrigido no tool.
- **SIGTERM no meio**: sem handler a tela fica no alt-screen. Já corrigido
  (`finally` restaura pincel, cursor e tela).
- **Medir com `--fps 30` e achar que é a vazão**: com ritmo fixo o tool dorme, e
  o fps medido é o alvo, não o limite do terminal.
- **Janela do bzmux não é a grade**: `size_request` da lateral e a barra de abas
  comem largura; a grade é o que o dump diz (`=== viewport CxR ===`).

## Uso futuro

É o antes/depois do P9: trocar `show_text` por `PangoCairo` muda o custo do
frame, que é a medida do experimento. Rodar esta mesma carga antes e depois,
mesma grade e mesmos frames, e comparar com a linha de base acima.
