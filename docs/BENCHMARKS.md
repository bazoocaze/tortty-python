# Benchmarks e medição

Único doc com número de vazão, desenho, parse e pegada — com data e governor. Os
outros docs citam o fato em uma frase e linkam.

- Carga principal: doom-fire (`tools/doomfire.py`, P16) — pior caso sintético, o
  número da manchete.
- Carga real: `dmesg`, com e sem cor.
- Escada e decomposições: IO, parse e desenho separados, com sondas e perfil.
- Pegada: memória do app e peso de instalar o stack gráfico.
- Protocolo de comparação e armadilhas de medição.

## Convenções

- Formato para agente: título, item de lista, `code` e cerca para comando.
  Tabela só para dado tabular (medição com colunas), nunca decorativa.
- Conciso: cada seção responde uma pergunta, e um fato tem uma casa aqui dentro
  também. Leitura repetida em duas seções é divergência esperando acontecer: a
  outra seção cita em cinco palavras e aponta. Narrativa de tentativa fica no
  HISTORY. A exceção é a condição da medição (data, governor, grade, comando),
  que se repete em cada tabela. Medida nova atualiza o número; não ganha
  parágrafo de conclusão.
- Sem negrito de ênfase e sem itálico: aqui não há risco a sinalizar, e o número
  com a condição já é o destaque.
- Uma grandeza por item: o número, a condição (data, governor, grade, comando) e
  a leitura na mesma lista.
- Número só aqui: vazão, desenho, parse e pegada moram neste arquivo; os outros
  docs citam em uma frase e linkam.
- Número sem condição não vale: data, governor e frequência da CPU, a grade
  (cols x linhas) e o comando exato.
- Comparação exige mesma grade e mesma fonte; número de outra configuração não
  entra na mesma tabela.
- Unidade explícita: fps, MB/s, bytes/frame, µs/célula, ms por chamada de `draw`
  ou `pty`.
- Estimativa é dita como estimativa, com o modo de obtenção; nada de número
  arredondado apresentado como medição.
- Armadilha de medição vai para "Armadilhas"; de ferramenta ou de sessão, para
  [DEBUG.md](DEBUG.md); narrativa datada de item, para
  [HISTORY.md](HISTORY.md).

## Carga principal: doom-fire

- O caminho quente é parser → grade → agrupamento por cor → desenho no cairo.
- Para medir vazão não serve `seq 1 100000` (uma cor só) nem `vim` (poucas
  células por frame): o pior caso é a tela inteira trocando de cor a cada frame.
- Doom-fire (port de PSX: buffer de intensidade 0..36 propagado de baixo para cima
  com decaimento, paleta de 37 tons) é isso, e é sintético: sem app real, sem
  rede.
- Desenhado em meio-bloco (`▀`, dois pixels por célula) com fg e bg truecolor por
  célula, sem agrupar: cada célula custa dois escapes de 16 a 19 bytes.

### Como rodar

```
./bench.sh                       # a escada inteira, 300 frames (~20 s)
./bench.sh --frames 1200         # o protocolo de referência
./bench.sh --cols 70 --rows 21   # outra grade (a de 2026-10-27)
./bench.sh --xvfb                # só o display virtual
./bench.sh --sem-xvfb            # só o display atual
python3 tools/doomfire.py                      # 30 fps até Ctrl+C
python3 tools/doomfire.py --fps 0 --frames 1200 --stats-to /tmp/x.txt
```

- `--fps N` — ritmo fixo; `0` solta a mão e quem limita é o terminal.
- `--frames N` — para depois de N frames; `0` (default) vai até Ctrl+C.
- `--stats-to ARQ` — estatísticas em arquivo (`-`, default, vai em stderr).
- `--fps 0 --stats-to` é o modo de medição: o fps alcançado é a vazão do
  terminal, e o arquivo evita depender de ler a tela.
- Grade = tamanho do terminal (`cols × lines`, buffer de `cols × 2·lines`
  pixels); o tool não redimensiona.
- `bench.sh` roda a escada (full, `NODRAW`, `NOPARSE+NODRAW`) **duas vezes**, no
  display atual e num Xvfb privado que ele mesmo sobe e mata, mais o gerador
  isolado: sete linhas. Imprime fps, MB/s, bytes/frame, `draw ms/call`,
  `pty ms/call` e a frequência da CPU por etapa. Não guarda número: os de
  referência são os daqui.
- Os dois displays são o ponto: o X real do desktop usa glamor e o Xvfb pinta no
  pixmap, então a mesma grade custa 3,4x mais desenho no `:0`. Medir os dois na
  mesma execução separa o que é código do que é servidor — e um valor sozinho,
  sem o display anotado, não compara com nada.
- A condição é travada pelo **grid**, não pela janela: `tools/benchrun.py` sobe o
  app com o socket, ajusta com `resize` até `cols×rows` bater no alvo, confere e
  só então digita a carga no pty; grid diferente = etapa sem número (código 3),
  nunca número de outra condição. O padrão é **61×18 com fonte 13** (a janela
  que sobra sem estar maximizada); `--cols/--rows/--font-size` trocam, e a grade
  usada sai no rodapé da tabela.
- O grid não sai dos pixels: célula = fonte × dpi, e dpi é o `Xft.dpi` da sessão
  (`130` no desktop do autor, `96` sem o recurso). A mesma janela de 980x640 é
  70×21 com 130 e 98×27 com 96 — por isso o alvo é em células.
- Não digitar a carga antes da janela assentar: com `--cmd` o filho pode medir o
  padrão 80×24 (o primeiro `TIOCSWINSZ` chega depois) e o número vira de outro
  grid. É por isso que o `benchrun.py` escreve no pty só depois do `state`
  confirmar o alvo.

### O número da máquina hoje

Condição: as três primeiras etapas do `bench.sh`, 1200 frames, fonte 13,
`schedutil` a 4,25–4,29 GHz, 2026-11-01, um terminal de cada vez.

| display | grade | fps | MB/s | bytes/frame | `draw` |
|---|---|---|---|---|---|
| `:0` (X com glamor) | 61×18 | 113,9 | 4,9 | 42,8 KB | 13,9 ms |
| Xvfb `:96` (sem glamor) | 61×18 | 129,2 | 5,5 | 42,3 KB | 4,2 ms |
| `:0` (X com glamor) | 70×21 | 53,0 | 3,0 | 57,0 KB | 20,6 ms |
| Xvfb `:96` (sem glamor) | 70×21 | 111,4 | 6,3 | 56,7 KB | 5,8 ms |

- O mesmo código, o mesmo grid e quase a mesma área de pixels: 4,2 ms em Xvfb e
  13,9 ms no X real (61×18), 5,8 contra 20,6 ms (70×21). A diferença é o caminho do servidor — `:0` usa
  `modesetting` + `glamoregl`, onde cada preenchimento do cairo vira trabalho de
  GL; o Xvfb pinta direto no pixmap.
- Número de benchmark, portanto, é propriedade do **display** tanto quanto do
  código: comparar só dentro do mesmo display, e anotar qual.
- O cronômetro do `draw` cobre ~40% do frame (8,3 ms de 18,9 ms em 70×21); o
  resto é flush e pintura do lado do servidor, fora do `on_draw`.
- fps não é linear no número de células porque cada desenho cobre vários frames
  do gerador (2,5 em 70×21, 3,8 em 61×18): o terminal pinta o estado mais novo e
  descarta os intermediários.
- A referência de 2026-10-27 abaixo (110–122 fps em 70×21) é de outro momento
  desta máquina: não é re-medição, e o padrão do `bench.sh` hoje é 61×18.

### O número

Condição: grade 70×21 (1470 células), fonte de 13 pontos (o padrão da época,
hoje o default é 12), `--fps 0 --frames 1200`,
um terminal de cada vez, 3 tiros de cada em 2026-10-27, `schedutil` com turbo em
4,29 GHz.

| | fps | MB/s de escapes | bytes/frame |
|---|---|---|---|
| bzmux | 110,4–122,6 | 6,2–6,9 | ~56 KB |
| kitty 0.48.2 | 675,8–714,2 | 38,5–40,7 | ~56 KB |

- Distância de ~6x (5,6–6,6x tiro a tiro): o bzmux gasta ~7,7 ms por frame de
  1470 células e o kitty ~1,4 ms — 5,2 µs contra 1 µs por célula.
- Depois do P34 (2026-10-31) o padrão virou 12 pontos e a janela de 980x640
  passou a 75×22; `font_family`, `font_size` e `window_padding_width` mudam a
  célula. Os números acima não são re-medição do padrão novo: para comparar,
  `font_size 13` na config e fonte/tamanho/padding registrados no protocolo.
- O número antigo do kitty (275,9 fps / 15,8 MB/s, grade 68×19) é de outra
  condição desta máquina (CPU baixa) e não se compara: a mesma versão faz 2,5x
  mais hoje só com o turbo. Re-meça os dois na mesma sessão, com a mesma janela e
  a frequência registrada.
- A frequência efetiva decide o número: o mesmo código deu 107–121 fps com turbo
  em 4,3 GHz e 59–64 fps com a CPU em ~1,5 GHz (`draw` de 8,5 ms contra 22 ms);
  com `powersave` as medições davam 3–5x menos que `schedutil`. O controle pelo
  gerador isolado está em "Anomalia resolvida".
- fps depende da grade (célula maior = menos frames com a mesma vazão); MB/s é o
  número que compara. Com 300 frames a janela sobe no meio da conta e o fps sai
  10–20% acima, daí os 1200 do protocolo.
- Os 6,1–6,9 MB/s ficam acima dos 0,7–1,9 MiB/s de "parse + grade" do README
  porque aqui o desenho está ligado (desligado, o mesmo fogo dá 10,8–11,1 MB/s):
  o README mede despejo uniforme, aqui a tela troca de cor em toda célula.
- Este número é o depois do P9 (desenho por Pango), da fonte em pontos e do bug
  13: o desenho subiu de 12,8 para 22,7 ms por frame e a vazão caiu de 0,6 para
  0,5 MB/s. Parte é shaping e fallback de fonte, parte é tamanho de glifo — até o
  bug 13 o texto era desenhado a 96 dpi (glifo de 10×22 px) com a grade a 130
  dpi, ou seja, medições anteriores a 2026-10-25 pintavam menos pixels por
  célula. Comparar fps daqui pra frente.

### Onde o tempo vai

- `PYTERM_PROF=1`, 1200 frames a 70×21, 113,5 fps / 6,5 MB/s: parse 44% e desenho
  34% (o resto é o gerador esperando). Com a CPU baixa a ordem se inverte
  (desenho 49%, parse 25%): desenho é mais sensível à frequência que parse.
- Desenho roda ~40x/s e o fogo inteiro a ~110 frames/s: o desenho é coalescido a
  ~22–40 draws/s (teto de um a cada 16 ms), e desenhar menos é o que deixa o
  parse respirar.
- O desenho custa pelo número de runs de cor, não de células: 37 tons por linha
  fazem quase toda célula ser um run próprio. Com turbo, ~5 µs por célula (7,9 ms
  por frame de 1470 células) contra ~1 µs no caso uniforme (~1,45 ms por 1470
  células, desenho de `seq`, 445 draws). Medir desenho com tela de uma cor
  subestima o pior caso em ~5x (era 15x com a CPU baixa).

## Decomposição do desenho (2026-10-27)

- Medido no `_on_draw` com instrumentação temporária por seção (`perf_counter` em
  volta de cada trecho do laço; não ficou no código), doom-fire de 600 frames a
  70×21, grade travada com `PYTERM_GEOM`, turbo em 4,29 GHz.
- Colunas antes e depois do P24/P25 (cor em float cacheado,
  `show_layout_line`), mesma metodologia e mesma CPU: "antes" é referência
  histórica, "depois" é o que o código faz hoje.

| etapa do `_on_draw` | antes µs/run | depois µs/run | % hoje |
|---|---|---|---|
| agrupar run (`while j` comparando fg/bg/flags/seleção) | 0,27 | 0,26 | 5% |
| cor: 2× `cell_rgb` (lookup + 6 divisões → cache float) | 0,69 | 0,37 | 6% |
| estado + fundo: 2× `set_source_rgb` + `rectangle` + `fill` | 2,32 (0,99+1,33) | 1,56 | 27% |
| texto: `"".join` do run + `dict.get` do cache de layout | 1,00 | 0,93 | 16% |
| `cr.move_to` + `show_layout` → `show_layout_line` | 2,83 | 2,44 | 43% |
| soma das seções | 7,11 | 5,71 | 5,0 µs/célula |
| `draw` sem instrumentação | 7,76 ms | 6,54 ms (-16%) | |

- O resto do draw (métricas, o `cr.paint()` que limpa, cursor, sub-célula) fica em ~0,6
  ms, e o ganho de ponta é +4,8% de fps (110,7 → 116,0): o desenho é ~34% do
  tempo, então cortar 16% dele rende ~5% na vazão.
- São ~1323 runs por draw para 1470 células (1,13 célula/run): o fogo troca a cor
  de quase toda célula, então agrupar não tem o que juntar (o laço de agrupamento
  é só 4%). Quase todo run pinta fundo (`bgpaint` = 99,99% dos runs).
- A instrumentação custa caro aqui: 6 `perf_counter` por run inflam o draw de 8,1
  para ~9,5 ms (17%) e o fps cai de ~110 para ~100. Por isso o `ms/draw` acima é
  maior que o do `PYTERM_PROF`: com instrumentação compare proporções, nunca o
  total.
- A mesma decomposição com a CPU em ~1,5 GHz (a primeira medição, 500 frames,
  59,8 fps): 18,5 µs/run e 23,3 ms/draw, mesmas proporções (`show_layout` 41%,
  cor+fundo 37%, texto 12%, agrupamento 9,6%). O turbo reduz tudo por ~2,6x e não
  muda a ordem de ataque.
- Onde atacar: (1) Pango, 40% — o layout já vem do cache `(texto, negrito)`, então
  o custo é o `show_layout` emitindo ~1 glifo por run; medir
  `cr.show_glyphs`/`cr.show_text` contra ele antes de mexer; (2) fundo + estado,
  33% — 4 chamadas de contexto por run; cachear a cor (tupla float por índice da
  paleta evita 12 divisões por run), mas o par `rectangle`+`fill` por célula é
  intrínseco à cor por célula.
- Armadilha de método: `cProfile` infla quem faz muita chamada Python. `join`
  apareceu com 21% no perfil e 12% na medição real, e o app caiu de 59,8 para 5,6
  fps. O mecanismo (ele não enxerga `gi.FunctionInfo`) está em
  [DEBUG.md](DEBUG.md).

## Alternar fundo e glifo custa o frame (2026-11-01)

- Medido com o verbo `prof` do socket e `tools/benchrun.py`, doom-fire em 61x18
  no display real, supressão de um trecho por vez do `_on_draw` (patch
  temporário, não ficou no código):

| variante do laço | draw |
|---|---|
| cheio (fill + glifo por run, alternando) | 13,03 ms |
| sem `cr.paint()` de fundo | 12,97 ms |
| sem os `fill` de fundo | 3,03 ms |
| sem `show_layout_line` | 2,61 ms |
| sem os dois | 2,88 ms |

- Os dois lados não somam: tirar qualquer um dos dois derruba o custo para ~2,7
  ms, então o caro é a **alternância** (o X troca de estado por operação), não a
  soma das operações. Agrupar resolve: duas passadas por frame (todos os fundos,
  depois todo o texto) levam o mesmo frame de 13,0 para 7,9 ms.
- Custo real fora do pior caso: 18 linhas de texto com 8 cores e fundo default
  custam ~0,93 ms por frame cheio; um caractere trocado numa linha custa 0,81 ms.
- `cProfile` de novo mentiu: apontou `cell_rgb_f` (368 mil chamadas) como alvo
  grande, e podar aquilo rendeu 2% — a armadilha da seção "Onde o tempo vai"
  vale para qualquer contagem de chamadas pequenas.

## A escada: IO, parse e desenho (2026-10-26)

- `PYTERM_NODRAW=1` desliga o desenho (`request_draw` vira no-op) e
  `PYTERM_NOPARSE=1` lê o pty e descarta os bytes (sem decode, sem parse, sem
  grade).
- Mesma carga, 300 frames, uma linha por etapa, grade travada por
  `PYTERM_GEOM=980x640`. As linhas de `schedutil` são de 2026-10-27; as do P20
  foram medidas com `powersave` (fps antigo entre parênteses onde existe).

| etapa ligada | fps | MB/s | onde o tempo vai |
|---|---|---|---|
| geração pura, fora do terminal (80×24) | 756–771 | 55 | é o teto do gerador (turbo) |
| só read do pty (NOPARSE+NODRAW) | 629–635 | 35 | o IO não é o limite (turbo) |
| read + parse → grade (NODRAW), antes do P20 | 17,2 | 1,0 | powersave; pty 4,17 ms/leitura = 99% |
| read + parse → grade (NODRAW), depois do P20 | 192–198 | 11 | turbo; pty 0,27 ms/leitura (CPU baixa: 156 / 8,8) |
| + desenho (normal), antes do P20 | 8,2 | 0,5 | powersave; parse 48% + desenho 52% |
| + desenho (normal), hoje | 110–123 | 6,2–6,9 | turbo; parse 45% + desenho 31% (CPU baixa: 60 / 3,4) |

- Bancadas diferentes não se comparam: o mesmo NOPARSE deu 14 MB/s com
  `powersave`, 25–33 com `schedutil` em CPU baixa e 41 com turbo.

Custo da etapa que entrou:

- read do pty é quase grátis (448–582 fps contra 742 do gerador puro): o IO custa
  uns 25–40% do tempo do gerador e não é o limite.
- parse custa ~3,5x. Com 38 bytes de escape por célula é o bloco mais caro do
  input depois do desenho — mas já foi 14x antes do P20.
- desenho custa ~2,5x: com o parser rápido, virou a maior fatia (49% do prof).
- O teto medido hoje, com esta carga, é 8,5 MB/s; o número do README é de outra
  bancada (ver "O número").

### Buffering do pty (por que o número vale)

- O teste mede o mínimo entre o que o filho produz e o que o emulador consome, e
  isso foi verificado, não suposto.
- O master é não-bloqueante (`os.set_blocking(fd, False)` no spawn): `os.read`
  levanta `BlockingIOError` em vez de travar a UI; `PYTERM_PROF=1` conta `eagain`
  e bytes.
- Bytes lidos == bytes escritos: 16,82 MB contra 16,8 MB nos dois modos (só-read
  e com parse). Não sobra byte no buffer do kernel.
- `eagain 0` em todas as rodadas, inclusive 5 s de pty ocioso (`sleep 5`), quando
  `on_pty` não é chamado nenhuma vez: o watch é level-triggered e só dispara com
  dado. Não há giro nem exceção por segundo.
- O buffer do pty (kernel, dezenas de KB) é transitório e é o que dá backpressure:
  com o parser lento o filho espera, então 1,0 MB/s é a taxa do emulador, não a do
  buffer. Read médio de ~4 KB não é acúmulo: é o watch disparando assim que chega
  qualquer coisa.

## Decomposição do parse (por que 35 µs/célula)

- Frame real do doomfire (70×21, 34 B/célula: 2 SGR truecolor de 19 B + `▀`),
  alimentado direto no `Term`, sem GTK, melhor de 300 rodadas — mesma ordem da
  medição de ponta (38,8 µs/célula).

| etapa | onde | µs/célula |
|---|---|---|
| `decoder.decode` UTF-8 incremental | view.py:242 | 0,11 |
| `for ch in text` + máquina de estados (ground) | term.py `feed` | 0,15 |
| `put`: `grid[cy][cx] = [ch, fg, bg, flags]`, autowrap, charset | term.py `put` | 0,97 |
| acumular CSI char a char (`self.csi += ch`) | term.py (estado csi) | ~2,9 por escape de 19 B |
| fechar o CSI: strip de intermediário, prefixo `?<>=`, `split(';')`, `strip()`, `int()` por token, listas `parts` + `nums` | term.py `feed` | ~5 por escape (`split`+`int` = 2,66) |
| `sgr`: `flatten` de subparâmetros (`isinstance`), loop, setar fg/bg/flags | term.py `sgr` | ~8 por escape |
| `newline`/`scroll_up`: `pop(0)`+`append`+`blank_row`+`sb_wrapped` | term.py | 14 µs/linha (0,2 por célula) |
| total | | 35,0 |

- SGR truecolor é 91% do parse (32 de 35). `put` e o laço de caracteres somam
  1,1; decode UTF-8 0,11 (0,3%).
- Escape não é grátis mesmo sem cor: `CSI 10;10 H` de 8 B custa 8 µs, ou ~1 µs
  por byte de escape contra ~15 ns por byte de texto puro.
- O gargalo não é iterar caracteres, é o custo fixo de fechar e interpretar cada
  CSI.

## Opções de otimização (prototipadas, µs/célula no mesmo frame)

| opção | como | µs/célula | ganho |
|---|---|---|---|
| atual (antes do P20) | char a char, `csi` string, `split`+`int`, `sgr` | 35,0 | — |
| B | `find("\x1b")` + split manual, runs de texto por slice | 10,05 | 3,5x |
| A | regex `\x1b\[(3\|4)8;2;r;g;bm` + runs por slice | 6,83 | 5,1x |
| C (feita no P20) | `find` + fim por `find("m")` + cache de escape→cor | 5,49 medido no app | 5,8x |

- Protótipos medem só o caminho feliz (wrap simples, sem reflow/charset/outros
  CSI). A opção C foi para o código no P20: 32,0 → 5,49 µs/célula = 5,8x (texto
  puro 0,99 → 0,21 = 4,7x), com o parser lento como fallback de tudo que não é
  texto ou SGR truecolor.
- Por que C ganha: `regex.search` custa ~1,1 µs por escape e `int()`+`groups()`
  ~2,2; no doomfire só há 37 tons, então `dict[escape] → (r,g,b)` (~0,05 µs) mata
  os dois.

Ordem de ataque, do que rende mais:

- Fast path do SGR/CUP (opção C): feito no P20, 5,8x.
- Texto por runs, não por char: feito junto no P20 (0,99 → 0,21 µs/célula no
  despejo uniforme). O que resta é despejo de texto puro com outros C0 no meio.
- `csi_dispatch` em uma passada: sem `parts`+`nums`, sem `strip()` quando não há
  intermediário, `params` direto no `sgr` quando não houver tupla. Agora isso só
  afeta escape fora do padrão (cache miss); ganho pequeno e barato.
- `deque` no scrollback: descartado por medição no P21 — `pop(0)` não aparece
  (13,64 / 13,81 / 13,69 µs com 0 / 500 / 1000 linhas). O custo era a linha em
  branco (11,5 dos 13,7 µs, 70 listas de célula), resolvido no P21 com célula
  compartilhada: 13,7 → 3,27 µs/linha e 38,4 → 10,9 µs/linha na rolagem de 20000
  linhas.
- Não ajuda: decode UTF-8 (0,11), `put` isolado (0,97).
- Ressalva de prioridade: com o desenho em 22,7–98 ms/frame, otimizar o parse só
  aparece na vazão quando o desenho também cair; depois do P20 o desenho é 71–87%
  do tempo.

## Carga real: `dmesg` (2026-10-26)

- O caso que motivou o P20: `Term` alimentado com o `dmesg` do sistema (1319
  linhas), 100×40, sem GTK.

| payload | antigo | P20+P21 | com P22 |
|---|---|---|---|
| `dmesg` sem cor (99,7 KB, 0 escapes) | 164,1 ms | 45,3 ms | 42,6 ms |
| `dmesg --color=always` (122,9 KB, 5172 escapes) | 188,5 ms | 82,2 ms | 78,6 ms |

- Por leitura de ~4 KB: 7,01 → 1,90 ms (sem cor).
- Como o parse roda no thread do GTK, é isso que congela a UI ao despejar o log:
  a "pausa rápida" percebida era ~165 ms antes e ~43 ms depois.
- O P22 (cache de parâmetros de CSI) leva o caso com cor de 2,0x para 2,4x: os SGR
  do `dmesg` (`1`, `4`, `31`, `0`) não são truecolor e só ficaram baratos quando o
  CSI inteiro passou a ser resolvido pelo cache, em vez de cair no parser lento
  (HISTORY, P22).

### Anomalia resolvida (2026-10-27): era o governor

- O desenho não reproduzia os 22,7 ms/frame: dava 47,7 ms em 60 frames, 97,8 em
  300 e 105,1 em 400, sempre com as métricas idênticas (`state` do socket: avanço 14,0, célula
  14×28, res 130, 70 colunas).
- Trocar `powersave` → `schedutil` devolveu 22,12 / 21,70 / 20,97 / 22,18 ms em
  quatro tiros seguidos, com a vazão indo de 10,4 para 59–64 fps.
- O `powersave` prendia a CPU em ~1,4 GHz sob carga sustentada; o gerador isolado
  caiu de 744 para 256 fps na mesma troca, o que fecha a conta.
- Nuance medida: o desenho de texto uniforme não muda com o governor (1,41 ms com
  `powersave`, 1,45 ms com `schedutil`, 443–445 draws) — o que desaba é o caminho
  caro, de ~2000 runs de cor por frame.
- Não era energia: bateria e tomada deram 10,52 e 10,89 ms no scroll, dentro do
  ruído.
- Regra: registrar o governor, comparar só dentro do mesmo governor, desconfiar de
  desenho fora da faixa de ~20–22 ms/frame nesta carga e incluir um tiro do
  gerador isolado como controle.

```
PYTERM_NOPARSE=1 PYTERM_NODRAW=1 PYTERM_PROF=1 ./run.sh --cmd 'python3 \
    tools/doomfire.py --fps 0 --frames 300 --stats-to /tmp/df.txt'
# prof: draw 1x 3.4ms/call | pty 2134x 0.06ms/call (137ms)
```

## Perfil do bzmux

- As sondas `PYTERM_*` estão em [DEBUG.md](DEBUG.md); aqui só o que elas produzem
  como número.
- `PYTERM_PROF=1` liga contadores no `TermView` (`bzmux/view.py`): tempo e número
  de chamadas de `on_pty` (parse) e `on_draw` (desenho), no stderr (logo, no
  `/tmp/bzmux.log` do `debug.sh`) quando a sessão fecha. Sem a variável o código
  não faz nada (só o `if not _PROF` na entrada).

```
PYTERM_PROF=1 ./debug.sh --cmd 'python3 tools/doomfire.py --fps 0 \
    --frames 300 --stats-to /tmp/df.txt'
grep prof: /tmp/bzmux.log
# prof: draw 821x 22.67ms/call (18610ms) | pty 4102x 4.22ms/call (17314ms)
```

## Pegada: memória e disco (2026-10-28)

- Peso, não vazão: o que custa ter isto instalado e rodando. Medido no próprio
  desktop GTK onde ele roda, com o `gi`/cairo do sistema.
- App rodando, uma sessão: PSS total ~17 MB, dos quais ~2 MB do stack
  gtk/pango/cairo/freetype/python — o resto é página compartilhada com o desktop,
  que já a tinha carregada.
- Instalar o stack onde ele não existe (closure do GTK3 + Pango + cairo no
  Debian): 210 pacotes, 346 MB em disco, dominado por fontes (`fonts-noto-core`
  42 MB) e ICU (`libicu74` 36 MB). Numa máquina GTK esse custo é zero, porque o
  desktop já o pagou.
- Rota Qt, para comparação (P30, em [PORTABILITY.md](PORTABILITY.md)): PySide6 244 MB
  instalado, app trivial com PSS de 50 MB, dos quais 23 MB de libs Qt. No
  Windows/macOS é a mesma ordem de grandeza de levar GTK para lá; no Linux o GTK
  ganha por construção.
- PyGObject nunca vem de wheel: o PyPI publica só sdist (3.58.1), então
  `pip install pygobject` é compilar contra headers. É o fato que faz o instalador
  depender do gerenciador de pacotes da distro, e não do pip.
- A metadata do pacote não faz claim de desempenho (sem "leve", sem "rápido"):
  leve é verdade em pegada e falso em vazão. Decisão em
  [LIMITATIONS.md](LIMITATIONS.md).

## Protocolo (para comparar dois terminais)

1. Um de cada vez: dois terminais desenhando ao mesmo tempo disputam CPU e os dois
   números saem piores.
2. Mesmas colunas e mesmas linhas nos dois. No bzmux, `PYTERM_GEOM=980x640` (sem
   isso o WM às vezes abre 80×24 e o número muda); no kitty, pedir o mesmo tamanho
   em pixels, já que fonte e DPI são as mesmas:

```
kitty --override remember_window_size=no --override initial_window_width=980 \
    --override initial_window_height=640 -e ...
```

- A janela padrão do bzmux é 980×640, o que dá 70×21 com um workspace e 57×21 com
  dois: abrir ou fechar a lateral muda a grade e o fps, então compare com a mesma
  quantidade de workspaces.
3. `--fps 0 --frames 1200 --stats-to ARQ` nos dois.
4. Comparar fps e MB/s (o bytes/frame varia um pouco com o tamanho do escape).

## Como saber que está desenhando

- O dump traz `▀` em todas as linhas da viewport (1470 células em 70×21): prova
  que o parser recebe, não que a tela muda. O que prova são duas capturas com
  ~1,5 s de intervalo:

```
import -window $(python3 tools/xtest.py id) /tmp/a.png; sleep 2
import -window $(python3 tools/xtest.py id) /tmp/b.png
# comparar as áreas: 0 pixels diferentes = tela congelada
```

- Foi assim que se achou o bug 12 (três capturas idênticas com 0,3 MB/s correndo).

## Armadilhas

- Armadilha de ferramenta ou de sessão (ponteiro travado, dump que mostra a grade
  viva, achar a janela) mora em [DEBUG.md](DEBUG.md); aqui ficam as de medição.
- A primeira medição era inválida: 24,6 fps / 1,0 MB/s com a tela congelada por um
  bug de prioridade do GLib (bug 12 do HISTORY), então aquilo media só parse.
  Número de vazão só significa depois de conferir que a tela muda.
- Fonte sem `▀`: a célula ainda tem bg e fg, então o fogo aparece como faixas de
  cor mesmo sem o glifo; se nem as faixas aparecem, o problema não é o glifo.
- `render` não emite `\r\n`: cada linha sai com exatamente `cols` meias-células e
  a quebra é mole (autowrap), quem decide a próxima linha é o emulador. Grade em
  diagonal = quebra errada — foi assim que se viu o bug do P15 (controle depois de
  linha cheia avançando duas linhas).
- SGR na saída: sem `\033[0m` as estatísticas herdam a última cor do fogo (texto
  com fundo amarelo). Já corrigido no tool.
- SIGTERM no meio: sem handler a tela fica no alt-screen. Já corrigido (`finally`
  restaura pincel, cursor e tela).
- Medir com `--fps 30` e achar que é a vazão: com ritmo fixo o tool dorme, e o fps
  medido é o alvo, não o limite do terminal.
- Janela do bzmux não é a grade: `size_request` da lateral e a barra de abas comem
  largura; a grade é o que o dump diz (`=== viewport CxR ===`).

## Para que serve

- A carga existe para medir mudança no caminho quente: rodar antes e depois, na
  mesma grade, e comparar com a linha de base acima. Foi assim que o P9 (desenho
  por Pango) foi avaliado: 12,8 → 15,4 ms por frame, 30,5 sem cache de layout.
- Números anteriores ao bug 13 entram só entre si, nunca contra a tabela de cima
  (o porquê está em "O número").
- O número vivo da tabela muda quando o desenho muda; o antes/depois fica no
  HISTORY.
