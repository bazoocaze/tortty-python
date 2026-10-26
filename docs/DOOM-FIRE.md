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

Uma execução, grade padrão (janela de 980x640, fonte de 13 pontos → 70×21,
1470 células), `--fps 0`, **um terminal de cada vez** (rodar os dois juntos
contamina o número):

| | fps | MB/s de escapes | bytes/frame |
|---|---|---|---|
| bzmux | 8,2 | 0,5 | ~55 KB |
| kitty | 275,9 | 15,8 | ~57 KB |

O bzmux fica com **98% de um core**: ~122 ms por frame de 1470 células. O kitty
faz o mesmo em ~3,6 ms. A distância é de **34x**.

Este número é o **depois do P9** (desenho por Pango), da fonte em pontos e do
bug 13: o desenho subiu de 12,8 para 22,7 ms por frame e a vazão caiu de 0,6
para 0,5 MB/s. Parte da subida é shaping + fallback de fonte e parte é tamanho
de glifo — até o bug 13 o texto era desenhado a 96 dpi (glifo de 10×22 px) com
a grade a 130 dpi, ou seja os números anteriores a 2026-10-25 mediam **menos
pixels pintados** por célula. Compare fps daqui pra frente, não com os de trás.

O fps depende da grade (célula maior = menos frames por segundo com a mesma
vazão); **MB/s é o número que compara**. A grade do kitty sai 68×19, não 68×20 —
arredondamento de célula dele, e a diferença de bytes/frame é essa.

O 0,5 MB/s fica *abaixo* do 0,7–1,9 MiB/s de "parse + grade" do README, e boa
parte da diferença é o desenho: com o desenho desligado (seção abaixo) o mesmo
fogo dá 1,0 MB/s, dentro daquela faixa. O número do README mede um despejo de
texto uniforme (escape curto, poucos runs); este mede uma tela que troca de cor
em toda célula, que é o pior caso também do parse.

### Onde o tempo vai

`PYTERM_PROF=1` (ver abaixo) decompõe, 36,5 s de fogo a 70×21 (300 frames):
**parse 48%** (4,2 ms por leitura, 4102 leituras) e **desenho 52%** (22,7 ms por
frame, ~22 draws/s). Desenho roda ~22x/s mas só 8,2 frames/s completos chegam à
tela: o parse não acompanha.

O desenho custa caro pelo número de *runs* de cor, não de células: 37 tons por
linha fazem quase toda célula ser um run próprio, e o custo por célula sai
~11 µs — contra ~1 µs do caso uniforme que o README mede (~2 ms / 1920 células).
Medir desenho com tela de uma cor subestima o pior caso em 10x.

### A escada: IO, parse e desenho (2026-10-26)

Duas sondas isolam as etapas: `PYTERM_NODRAW=1` desliga o desenho
(`request_draw` vira no-op) e `PYTERM_NOPARSE=1` lê o pty e descarta os bytes
(sem decode, sem parse, sem grade). Mesma carga, 300 frames:

| etapa ligada | fps | MB/s | onde o tempo vai |
|---|---|---|---|
| geração pura, fora do terminal (80×24) | 256,5 | 18,5 | é o teto do gerador |
| só read do pty (NOPARSE+NODRAW) | 249 / 242 | 14,0 / 13,6 | pty 0,06 ms/leitura: 138 ms em 1,2 s = 11% |
| read + parse → grade (NODRAW) | 17,2 | 1,0 | pty 4,17 ms/leitura: 17,1 s de 17,4 s = 99% |
| + desenho (normal) | 8,2 | 0,5 | parse 48% + desenho 52% |

Leitura da escada (cada linha é o custo da etapa que entrou):

- **O read do pty é quase grátis**: sem parse o bzmux faz 249 fps contra 256 do
gerador puro — acompanha o filho, perdendo ~3%. 89% do tempo o app está
*esperando* o doomfire escrever, não trabalhando.
- **O parse custa 14x** (249 → 17,2 fps, 0,06 → 4,17 ms por leitura): é o único
bloco grande do caminho de input. Com 38 bytes de escape por célula, ~39 µs de
parse por célula.
- **O desenho custa 2x** (17,2 → 8,2): é a segunda metade, não a primeira. A
imagem "parse barato, desenho caro" era artefato de dividir 55 KB por 4,2 ms.
- O 1,0 MB/s de "parse + grade" citado no README (despejo uniforme, 0,7–1,9)
cai no mesmo lugar: o teto do parse no pior caso é ~1,0 MB/s, porque o pty
entrega ~4 KB por read (4101 reads para 16,8 MB), não 64 KB.

**Por que o número vale (buffering do pty)** — o teste mede o mínimo entre o que
o filho produz e o que o emulador consome, e isso foi verificado, não suposto:

- O master é **não-bloqueante** (`os.set_blocking(fd, False)` no spawn);
`os.read` levanta `BlockingIOError` em vez de travar a UI. O `PYTERM_PROF=1`
agora conta `eagain` e `bytes`.
- **Bytes lidos == bytes escritos**: 16,82 MB lidos contra 16,8 MB escritos nos
dois modos (só-read e com parse). Não sobra byte no buffer do kernel.
- **`eagain 0`** em todas as rodadas, inclusive 5 s de pty ocioso (`sleep 5`),
quando `on_pty` não é chamado nenhuma vez: o watch é level-triggered e só
dispara com dado. Não há giro nem exceção por segundo.
- O buffer do pty (kernel, dezenas de KB) é transitório e é o que dá
**backpressure**: com o parser lento o filho espera, então o 1,0 MB/s é a taxa
do emulador, não a do buffer. Read médio de ~4 KB não é acúmulo: é o watch
disparando assim que chega qualquer coisa.

### Decomposição do parse (por que 35 µs/célula)

Frame real do doomfire (70×21, 34 B/célula: 2 SGR truecolor de 19 B + `▀`),
alimentado direto no `Term` sem GTK, melhor de 300 rodadas — mesma ordem da
medição de ponta (38,8 µs/célula):

| etapa | onde | µs/célula |
|---|---|---|
| `decoder.decode` UTF-8 incremental | view.py:242 | 0,11 |
| `for ch in text` + máquina de estados (ground) | term.py `feed` | 0,15 |
| `put`: `grid[cy][cx] = [ch, fg, bg, flags]`, autowrap, charset | term.py `put` | 0,97 |
| acumular CSI char a char (`self.csi += ch`) | term.py (estado csi) | ~2,9 por escape de 19 B |
| fechar o CSI: strip de intermediário, prefixo `?<>=`, `split(';')`, `strip()`, `int()` por token, listas `parts` + `nums` | term.py `feed` | ~5 por escape (`split`+`int` = 2,66) |
| `sgr`: `flatten` de subparâmetros (`isinstance`), loop, setar fg/bg/flags | term.py `sgr` | ~8 por escape |
| `newline`/`scroll_up`: `pop(0)`+`append`+`blank_row`+`sb_wrapped` | term.py | 14 µs/linha (0,2 por célula) |
| **total** | | **35,0** |

Leitura: **SGR truecolor é 91% do parse** (32 de 35). `put` e o laço de
caracteres somam 1,1; decode UTF-8 0,11 (0,3%). Escape não é grátis mesmo sem
cor: `CSI 10;10 H` de 8 B custa 8 µs, ou ~1 µs por byte de escape contra ~15 ns
por byte de texto puro. O gargalo não é iterar caracteres, é **o custo fixo de
fechar e interpretar cada CSI**.

### Opções de otimização (prototipadas, µs/célula no mesmo frame)

| opção | como | µs/célula | ganho |
|---|---|---|---|
| atual | char a char, `csi` string, `split`+`int`, `sgr` | 35,0 | — |
| B | `find("\x1b")` + split manual, runs de texto por slice | 10,05 | 3,5x |
| A | regex `\x1b\[(3\|4)8;2;r;g;bm` + runs por slice | 6,83 | 5,1x |
| **C** | `find` + fim por `find("m")` + **cache de escape→cor** | **3,81** | **9,2x** |

Os protótipos medem só o caminho feliz (wrap simples, sem reflow/charset/outros
CSI), então o ganho real é menor — mas a ordem de grandeza é essa. Por que C
ganha: `regex.search` custa ~1,1 µs por escape e `int()`+`groups()` ~2,2; no
doomfire só há 37 tons, então `dict[escape] → (r,g,b)` (~0,05 µs) mata os dois.
Decomposto: search 2,25 + groups/int 4,42 ≈ 6,7 dos 6,83 de A; alocar a célula
custa 0,41.

Ordem de ataque, do que rende mais:

1. **Fast path do SGR/CUP** (opção C): no estado ground, achar o próximo ESC com
`find`, o fim do CSI com `find("m")`/`find` do final, e resolver o escape por
**cache dict** (`bytes → (fg,bg)` ou o efeito já aplicado). Só cai no parser
completo quando o escape não está no cache. Corta 32 dos 35 µs.
2. **Texto por runs, não por char**: entre escapes, `str.find`/slice e
`row[cx:cx+k] = [[c, fg, bg, fl] for c in run]`. Reduz `put` de 0,97 e o laço
de 0,15; no despejo uniforme (caso do README, 0,7–1,9 MiB/s) isso é o que
importa mais que o SGR.
3. **`csi_dispatch` em uma passada**: sem `parts`+`nums`, sem `strip()` quando
não há intermediário, `params` direto no `sgr` quando não houver tupla. Ganho
pequeno (~1 µs/escape) e barato de fazer.
4. **`deque` no `scrollback`**: `pop(0)`/`append` com teto de 1000 é O(1000) por
linha; 14 µs/linha cai para ~2. Relevante só sob rolagem, e mexe no reflow
(indexação por posição).
5. **Não ajuda**: decode UTF-8 (0,11), `put` isolado (0,97), cache de layout do
Pango (é do desenho).

Ressalva de prioridade: com o desenho em 22,7–98 ms/frame, otimizar o parse só
aparece na vazão quando o desenho também cair — hoje os dois são da mesma ordem
(ver escada acima).

**Anomalia em aberto**: nesta sessão o desenho não reproduziu os 22,7 ms/frame
da tabela de cima — deu 47,7 ms em rodadas de 60 frames (47,70 e 47,71,
repetível ao centésimo) e 97,8 ms na de 300. O ambiente era o mesmo
(`PYTERM_DIAG`: avanço 14,0, célula 14×28, res 130, 70 colunas) e a máquina
estava ociosa (load 1,8 em 16 núcleos). Ou a linha de base do desenho mudou por
fator externo (compositor/Xorg), ou o custo cresce com a duração da rodada; nos
dois casos, **re-medir o desenho antes de comparar qualquer mudança nele**.

    PYTERM_NOPARSE=1 PYTERM_NODRAW=1 PYTERM_PROF=1 ./run.sh --cmd 'python3 \
        tools/doomfire.py --fps 0 --frames 300 --stats-to /tmp/df.txt'
    # prof: draw 1x 3.4ms/call | pty 2134x 0.06ms/call (137ms)

### A primeira medição era inválida

Deu 24,6 fps / 1,0 MB/s e **estava errada**: a tela estava congelada por um bug
de prioridade do GLib (bug 12 do HISTORY), então aquilo media só parse. Vale
como regra: número de vazão só significa alguma coisa depois de conferir que a
tela muda — é o teste de três capturas abaixo.

## Perfil do bzmux

`PYTERM_PROF=1` liga contadores no `TermView` (`core/view.py`): tempo e número
de chamadas de `on_pty` (parse) e `on_draw` (desenho), impressos no stderr
(portanto no `/tmp/bzmux.log` do `debug.sh`) quando a sessão fecha:

    PYTERM_PROF=1 ./debug.sh --cmd 'python3 tools/doomfire.py --fps 0 \
        --frames 300 --stats-to /tmp/df.txt'
    grep prof: /tmp/bzmux.log
    # prof: draw 821x 22.67ms/call (18610ms) | pty 4102x 4.22ms/call (17314ms)

Sem a variável o código não faz nada (só o `if not _PROF` na entrada).
`PYTERM_NODRAW=1` é a sonda que isola o parse: `request_draw` retorna sem
agendar draw, sobrando pty → grade (a escada da seção "A escada: IO, parse e
desenho" acima é essa sonda). `PYTERM_NOPARSE=1` vai um degrau abaixo: lê o pty e
descarta os bytes, sem decode nem grade — mede o teto de IO.
`PYTERM_DIAG=1` é outra sonda, de geometria e não de tempo: no primeiro draw
imprime avanço da fonte, célula da grade, resolução e colunas — os dois têm que
casar, senão o texto não cai nas células (bug 13 do HISTORY).

## Protocolo (para comparar dois terminais)

0. **um de cada vez** — dois terminais desenhando ao mesmo tempo disputam CPU
   e os dois números saem piores;
1. mesmas colunas e mesmas linhas nos dois — mais fácil pedindo o mesmo tamanho
   de janela em pixels, já que fonte e DPI são as mesmas (no kitty:
   `kitty --override remember_window_size=no --override initial_window_width=980
   --override initial_window_height=640 -e ...`; a janela padrão do bzmux é
   980×640, o que dá 70×21 com um workspace e 57×21 com dois — abrir ou fechar a
   lateral muda a grade e o fps, então compare com a mesma quantidade de
   workspaces);
2. `--fps 0 --frames 1200 --stats-to ARQ` nos dois;
3. comparar fps e MB/s (o bytes/frame varia um pouco com o tamanho do escape).

## Como saber que está desenhando

Dump do bzmux (`kill -USR1 $(cat /tmp/bzmux.pid)`) traz `▀` em todas as linhas
da viewport (1470 células em 70×21). Isso prova que o parser está recebendo —
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
para 15,4 ms por frame, com e sem cache de layout (30,5 sem cache). Aqueles
números são **anteriores ao bug 13** (desenho a 96 dpi, glifo menor): valem como
comparação entre si, não contra a tabela de cima. O número vivo desta tabela muda
quando o desenho muda; o registro do antes/depois fica no HISTORY.
