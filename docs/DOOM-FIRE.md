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

Uma execução, grade de 68 colunas (a padrão hoje: 68×20, 1360 células),
`--fps 0`, **um terminal de cada vez** (rodar os dois juntos contamina o número):

| | fps | MB/s de escapes | bytes/frame |
|---|---|---|---|
| bzmux | 11,0 | 0,5 | ~49 KB |
| kitty | 314,2 | 15,9 | ~50 KB |

O bzmux fica com **98% de um core**: ~91 ms por frame de 1360 células. O kitty
faz o mesmo em ~3,2 ms. A distância é de **32x**.

Este número é o **depois do P9** (desenho por Pango): o desenho subiu de 12,8
para ~15,4 ms por frame e a vazão caiu de 0,6 para 0,5 MB/s. É o preço de
shaping + fallback de fonte; o antes/depois está no HISTORY, item P9.

O fps depende da grade (célula maior = menos frames por segundo com a mesma
vazão); **MB/s é o número que compara**. A grade do kitty sai 68×19, não 68×20 —
arredondamento de célula dele, e a diferença de bytes/frame é essa.

O 0,5 MB/s fica *abaixo* do 0,7–1,9 MiB/s de "parse + grade" do README, e a
diferença é exatamente o desenho: o número do README mede um despejo de texto
uniforme, este mede uma tela que troca de cor em toda célula.

### Onde o tempo vai

`PYTERM_PROF=1` (ver abaixo) decompõe, 8 s de fogo a 68×20: **parse 57%** (4,3 ms
por leitura, ~1065 leituras) e **desenho 41%** (15,4 ms por frame, ~27 draws/s).
Desenho roda ~27x/s mas só 11 frames/s completos chegam à tela: o parse não
acompanha.

O desenho custa caro pelo número de *runs* de cor, não de células: 37 tons por
linha fazem quase toda célula ser um run próprio, e o custo por célula sai
~11 µs — contra ~1 µs do caso uniforme que o README mede (~2 ms / 1920 células).
Medir desenho com tela de uma cor subestima o pior caso em 10x.

### A primeira medição era inválida

Deu 24,6 fps / 1,0 MB/s e **estava errada**: a tela estava congelada por um bug
de prioridade do GLib (bug 12 do HISTORY), então aquilo media só parse. Vale
como regra: número de vazão só significa alguma coisa depois de conferir que a
tela muda — é o teste de três capturas abaixo.

## Perfil do bzmux

`PYTERM_PROF=1` liga contadores no `TermView` (`core/view.py`): tempo e número
de chamadas de `on_pty` (parse) e `on_draw` (desenho), impressos no stderr
(portanto no `/tmp/bzmux.log` do `debug.sh`) quando a sessão fecha:

    PYTERM_PROF=1 ./debug.sh --cmd 'python3 tools/doomfire.py --fps 0' \
        --quit-after 30
    grep prof: /tmp/bzmux.log
    # prof: draw 230x 12.83ms/call (2950ms) | pty 1144x 4.29ms/call (4902ms)

Sem a variável o código não faz nada (só o `if not _PROF` na entrada).

## Protocolo (para comparar dois terminais)

0. **um de cada vez** — dois terminais desenhando ao mesmo tempo disputam CPU
   e os dois números saem piores;
1. mesmas colunas e mesmas linhas nos dois (no kitty:
   `kitty --override remember_window_size=no --override initial_window_width=68c
   --override initial_window_height=20c -e ...`; a janela do bzmux é 680 px, o
   que dá 68×20 com um workspace só e 51×20 com dois — abrir ou fechar a lateral
   muda a grade e o fps, então compare com a mesma quantidade de workspaces);
2. `--fps 0 --frames 1200 --stats-to ARQ` nos dois;
3. comparar fps e MB/s (o bytes/frame varia um pouco com o tamanho do escape).

## Como saber que está desenhando

Dump do bzmux (`kill -USR1 $(cat /tmp/bzmux.pid)`) traz `▀` em todas as linhas
da viewport (1360 células em 68×20). Isso prova que o parser está recebendo —
**não** prova que a tela está mudando. O teste que prova são duas capturas com
~1,5 s de intervalo e comparação de pixels:

    import -window $(python3 tools/xtest.py id) /tmp/a.png; sleep 2
    import -window $(python3 tools/xtest.py id) /tmp/b.png
    # comparar as áreas: 0 pixels diferentes = tela congelada

Foi assim que se achou o bug 12 (três capturas idênticas com 0,3 MB/s correndo).

## Armadilhas

- **Fonte sem `▀`**: a célula ainda tem bg e fg, então o fogo aparece como
  faixas de cor mesmo sem o glifo; se nem as faixas aparecem, o problema não é o
  glifo.
- **`render` não emite `\r\n`**: cada linha sai com exatamente `cols`
  meias-células e a quebra é mole (autowrap), quem decide a próxima linha é o
  emulador. Grade em diagonal = quebra errada — foi assim que se viu o bug do
  P15 (controle depois de linha cheia avançando duas linhas).
- **SGR na saída**: sem `\033[0m` as estatísticas herdam a última cor do fogo
  (texto com fundo amarelo). Já corrigido no tool.
- **SIGTERM no meio**: sem handler a tela fica no alt-screen. Já corrigido
  (`finally` restaura pincel, cursor e tela).
- **Medir com `--fps 30` e achar que é a vazão**: com ritmo fixo o tool dorme, e
  o fps medido é o alvo, não o limite do terminal.
- **Janela do bzmux não é a grade**: `size_request` da lateral e a barra de abas
  comem largura; a grade é o que o dump diz (`=== viewport CxR ===`).

## Para que serve

A carga existe para medir mudança no caminho quente: rodar esta mesma carga
antes e depois da mudança, na mesma grade, e comparar com a linha de base
acima. Foi assim que o P9 (desenho por Pango) foi avaliado — desenho de 12,8
para 15,4 ms por frame, com e sem cache de layout (30,5 sem cache). O número
vivo desta tabela muda quando o desenho muda; o registro do antes/depois fica no
HISTORY.
