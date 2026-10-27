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
| bzmux | 59,3–63,9 | 3,3–3,6 | ~56 KB |
| kitty | 275,9 | 15,8 | ~57 KB |

O bzmux fica com **98% de um core**: ~17 ms por frame de 1470 células. O kitty
faz o mesmo em ~3,6 ms. A distância é de **~4,6x**.

Re-medido em 2026-10-27 na tomada e com governor **`schedutil`** (400 frames,
70×21, `PYTERM_DIAG`: avanço 14,0 / célula 14×28 / res 130 / 70 colunas), 4
tiros: 59,3 / 59,5 / 63,9 fps e 3,3 / 3,4 / 3,6 MB/s.

**O governor decide o número.** A tabela antiga (8,2 / 0,5) e a primeira
remedição (10,4 / 0,6) foram com **`powersave`**: a CPU ficava em ~1,4 GHz e
não subia, e o mesmo código mede 3–5x menos. Prova independente: o gerador
isolado, que não toca no terminal, fez 256 fps com `powersave` e **744 fps com
`schedutil`**. Medir e comparar sempre com o mesmo governor, e registrar qual.
Os quadros abaixo marcam qual governor estava ativo.

Este número é o **depois do P9** (desenho por Pango), da fonte em pontos e do
bug 13: o desenho subiu de 12,8 para 22,7 ms por frame e a vazão caiu de 0,6
para 0,5 MB/s. Parte da subida é shaping + fallback de fonte e parte é tamanho
de glifo — até o bug 13 o texto era desenhado a 96 dpi (glifo de 10×22 px) com
a grade a 130 dpi, ou seja os números anteriores a 2026-10-25 mediam **menos
pixels pintados** por célula. Compare fps daqui pra frente, não com os de trás.

O fps depende da grade (célula maior = menos frames por segundo com a mesma
vazão); **MB/s é o número que compara**. A grade do kitty sai 68×19, não 68×20 —
arredondamento de célula dele, e a diferença de bytes/frame é essa.

O 3,4 MB/s fica *acima* do 0,7–1,9 MiB/s de "parse + grade" do README, e o
motivo é o desenho ligado: com ele desligado (seção abaixo) o mesmo fogo dá
8,5 MB/s. O número do README mede um despejo de texto uniforme. O número do README mede um despejo de
texto uniforme (escape curto, poucos runs); este mede uma tela que troca de cor
em toda célula, que é o pior caso também do parse.

### Onde o tempo vai

`PYTERM_PROF=1` (ver abaixo) decomposição de referência, medida com `schedutil`
(400 frames, 6,97 s): **desenho 49%** (22,1 ms por draw, 154 draws) e **parse
25%** (0,32 ms por leitura, 5495 leituras); o resto é o gerador. Com
`powersave`, a mesma decomposição dava parse 48% / desenho 52% a 8,2 fps —
números antigos, outra bancada. O desenho é coalescido a ~22 draws/s (o teto é
um a cada 16 ms) para ~60 frames/s de conteúdo: desenhar menos vezes é o que
deixa o parse respirar.

O desenho custa caro pelo número de *runs* de cor, não de células: 37 tons por
linha fazem quase toda célula ser um run próprio. Com `schedutil` o custo é
**~15 µs/célula** (22 ms/frame de 1470 células), contra ~1 µs do caso uniforme
(~1,45 ms / 1470 células, desenho de `seq`, 445 draws). Medir desenho com tela
de uma cor subestima o pior caso em **~15x**.

Decomposição do mesmo frame por `PYTERM_PROF` (400 frames, 6,97 s, schedutil):
**draw 154x 22,12 ms = 3,4 s (49%)**, pty 5495x 0,32 ms = 1,8 s (25%) — o resto
é o gerador. Ou seja, com o parser rápido (P20–P22) o desenho passou a ser a
maior fatia: 22 draws/s enquanto o fogo inteiro roda a ~60 frames/s.

### A escada: IO, parse e desenho (2026-10-26)

Duas sondas isolam as etapas: `PYTERM_NODRAW=1` desliga o desenho
(`request_draw` vira no-op) e `PYTERM_NOPARSE=1` lê o pty e descarta os bytes
(sem decode, sem parse, sem grade). Mesma carga, 300 frames:

| etapa ligada | fps | MB/s | onde o tempo vai |
|---|---|---|---|
| geração pura, fora do terminal (80×24) | **742** | **54** | é o teto do gerador (schedutil) |
| só read do pty (NOPARSE+NODRAW) | **448 / 582** | **25 / 33** | o IO não é o limite (schedutil) |
| read + parse → grade (NODRAW), antes do P20 | 17,2 | 1,0 | powersave; pty 4,17 ms/leitura = 99% |
| read + parse → grade (NODRAW), depois do P20 | **156 / 147** | **8,8 / 8,3** | schedutil; pty 0,72 ms/leitura (powersave: 86,6 / 4,9) |
| + desenho (normal), antes do P20 | 8,2 | 0,5 | powersave; parse 48% + desenho 52% |
| + desenho (normal), hoje | **59,3–63,9** | **3,3–3,6** | schedutil; desenho 49% + parse 25% |

Uma linha por etapa. As duas primeiras e as duas últimas são de 2026-10-27 com
`schedutil`; as do P20 em diante tinham sido medidas com `powersave` (a coluna
de fps antiga aparece entre parênteses onde existe). **Números de bancadas
diferentes não se comparam**: com `powersave` o mesmo NOPARSE dava 14 MB/s, e
com `schedutil` dá 25–33.

Leitura da escada (cada linha é o custo da etapa que entrou):

- **O read do pty é quase grátis** (schedutil): sem parse o bzmux faz 448–582
fps contra 742 do gerador puro — o IO custa uns 25–40% do tempo do gerador e
não é o limite.
- **O parse custa ~3,5x** (582 → 156 fps) e, no pior caso, entrega 8,5 MB/s.
Com 38 bytes de escape por célula, é o bloco mais caro do caminho de input
depois do desenho — mas já foi 14x antes do P20.
- **O desenho custa ~2,5x** (156 → 60 fps): com o parser rápido, virou a maior
fatia (49% do tempo no prof).
- O "0,7–1,9 MiB/s de parse + grade" do README é de outra bancada (powersave e
despejo uniforme): não serve de teto. O teto medido hoje, com esta carga, é
8,5 MB/s.

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
| atual (antes do P20) | char a char, `csi` string, `split`+`int`, `sgr` | 35,0 | — |
| B | `find("\x1b")` + split manual, runs de texto por slice | 10,05 | 3,5x |
| A | regex `\x1b\[(3\|4)8;2;r;g;bm` + runs por slice | 6,83 | 5,1x |
| **C (feita no P20)** | `find` + fim por `find("m")` + **cache de escape→cor** | **5,49 medido no app** | **5,8x** |

Os protótipos medem só o caminho feliz (wrap simples, sem reflow/charset/outros
CSI). A opção C foi implementada no P20 e o número medido no projeto é 5,49
µs/célula no mesmo frame (32,0 → 5,49 = 5,8x; texto puro 0,99 → 0,21 = 4,7x),
com o parser lento mantido como fallback de tudo que não é texto ou SGR
truecolor. Por que C ganha: `regex.search` custa ~1,1 µs por escape e
`int()`+`groups()` ~2,2; no doomfire só há 37 tons, então `dict[escape] →
(r,g,b)` (~0,05 µs) mata os dois.

Ordem de ataque, do que rende mais:

1. ~~**Fast path do SGR/CUP** (opção C)~~ — feito no P20, 5,8x.
2. **Texto por runs, não por char** — feito junto no P20 (0,99 → 0,21 µs/célula
no despejo uniforme). O que resta é o mesmo só para despejo de texto puro com
outros C0 no meio.
3. **`csi_dispatch` em uma passada**: sem `parts`+`nums`, sem `strip()` quando
não há intermediário, `params` direto no `sgr` quando não houver tupla. Agora
isso só afeta escape fora do padrão (cache miss). Ganho pequeno e barato.
4. ~~**`deque` no `scrollback`**~~: descartado por medição no P21 — o `pop(0)`
não aparece (13,64 / 13,81 / 13,69 µs com 0 / 500 / 1000 linhas). O custo do
scroll era a linha em branco (11,5 dos 13,7 µs, 70 listas de célula), resolvido
no P21 com célula compartilhada: 13,7 → 3,27 µs/linha e 38,4 → 10,9 µs/linha na
rolagem de 20000 linhas.
5. **Não ajuda**: decode UTF-8 (0,11), `put` isolado (0,97).

Ressalva de prioridade: com o desenho em 22,7–98 ms/frame, otimizar o parse só
aparece na vazão quando o desenho também cair — depois do P20 o desenho é 71–87%
do tempo (ver escada e a anomalia abaixo).

### Carga real: `dmesg` (2026-10-26)

O caso que motivou o P20 na prática. `Term` alimentado com o `dmesg` do sistema
(1319 linhas), 100×40, sem GTK:

| payload | antigo | P20+P21 | com P22 |
|---|---|---|---|
| `dmesg` sem cor (99,7 KB, 0 escapes) | 164,1 ms | 45,3 ms | 42,6 ms |
| `dmesg --color=always` (122,9 KB, 5172 escapes) | 188,5 ms | 82,2 ms | 78,6 ms |

Por leitura de ~4 KB: 7,01 → 1,90 ms (sem cor). Como o parse roda no thread do
GTK, é isso que congela a UI ao despejar o log; a “pausa rápida” percebida era
~165 ms antes e ~43 ms depois.

O P22 (cache de parâmetros de CSI) é o que faz o caso com cor passar de 2,0x
para 2,4x: os SGR do `dmesg` (`1`, `4`, `31`, `0`) não são truecolor e só
ficaram baratos quando o CSI inteiro passou a ser resolvido pelo cache, em vez
de cair no parser lento. Ver HISTORY.md (P22).

**Anomalia resolvida (2026-10-27): era o governor.** Ela existia porque o
desenho não reproduzia os 22,7 ms/frame: dava 47,7 ms em 60 frames, 97,8 em
300 e 105,1 em 400 na tomada — sempre com `PYTERM_DIAG` idêntico (avanço 14,0,
célula 14×28, res 130, 70 colunas). Nada no código explicava, e trocar
`powersave` → `schedutil` devolveu **22,12 / 21,70 / 20,97 / 22,18 ms** em
quatro tiros seguidos, com a vazão indo de 10,4 para 59–64 fps. O
`powersave` prendia a CPU em ~1,4 GHz sob carga sostenida; o gerador isolado
caiu de 744 para 256 fps na mesma troca, o que fecha a conta. Uma nuance
medida: o desenho de **texto uniforme** não muda com o governor (1,41 ms com
`powersave`, 1,45 ms com `schedutil`, 443–445 draws) — o que desaba é o
caminho caro, de ~2000 runs de cor por frame. Lição para qualquer medição
futura: **registrar o governor**, comparar só dentro do mesmo governor,
desconfiar de desenho fora da faixa de ~20–22 ms/frame nesta carga, e incluir
um tiro do gerador isolado como controle. (Também não era a energia: bateria e
tomada com `powersave` deram 10,52 e 10,89 ms no scroll, dentro do ruído.)

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
