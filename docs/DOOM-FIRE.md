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

Uma execução, grade de 51 colunas, `--fps 0`, **um terminal de cada vez** (rodar
os dois juntos contamina o número):

| | fps | MB/s de escapes | bytes/frame |
|---|---|---|---|
| bzmux | 16,2 | 0,6 | ~38 KB |
| kitty | 412,6 | 15,6 | ~38 KB |

O bzmux fica com **100% de um core**: ~62 ms por frame de ~1020 células. O kitty
faz o mesmo em ~2,4 ms.

O 0,6 MB/s é o dobro *abaixo* do 0,7–1,9 MiB/s de "parse + grade" do README, e a
diferença é exatamente o desenho: o número do README mede um despejo de texto
uniforme, este mede uma tela que troca de cor em toda célula.

### Onde o tempo vai

`PYTERM_PROF=1` (ver abaixo) decompõe, 150 frames: **parse 63%** (4,2 ms por
leitura de 64 KiB) e **desenho 34%** (11,2 ms por frame, ~30 draws/s).

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
    # prof: pty 1396x 4.21ms/call (5884ms) | draw 280x 11.20ms/call (3137ms)

Sem a variável o código não faz nada (só o `if not _PROF` na entrada).

## Protocolo (para comparar dois terminais)

0. **um de cada vez** — dois terminais desenhando ao mesmo tempo disputam CPU
   e os dois números saem piores;
1. mesmas colunas e mesmas linhas nos dois (no kitty:
   `kitty --override remember_window_size=no --override initial_window_width=51c
   --override initial_window_height=20c -e ...`; a janela do bzmux é 680 px, o
   que dá 51×20 com a lateral visível);
2. `--fps 0 --frames 1200 --stats-to ARQ` nos dois;
3. comparar fps e MB/s (o bytes/frame varia um pouco com o tamanho do escape).

## Como saber que está desenhando

Dump do bzmux (`kill -USR1 $(cat /tmp/bzmux.pid)`) traz `▀` em todas as linhas
da viewport (1020 células em 51×20). Isso prova que o parser está recebendo —
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
