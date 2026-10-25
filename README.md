# bzmux — terminal mínimo em Python (experimento)

> Repositório `pybzmux`; o projeto se chama **bzmux**. Nasceu como `pyterm`
> dentro do experimento `kitty` e virou repo próprio em 2026-10-25 — por isso
> os commits antigos falam `pyterm` e os caminhos da época eram `pyterm/...`.
> A referência de comparação — o `gtkterm`, com o `native-port/` que linka o
> núcleo C do kitty como `libkittycore.a` — ficou **naquele** repositório: aqui
> não há C, não há compilação e nada do bzmux é compartilhado com ela.

Terminal de verdade (pty + parse VT + grade + cairo) escrito em **Python puro**,
para sentir na pele o custo do caminho quente em Python comparado ao núcleo C
do `gtkterm`. Não é produto: é a resposta empírica à pergunta "daria pra fazer
tudo em Python?". O estado, a retomada e a fila ficam em
[`TASK-bzmux.md`](TASK-bzmux.md); o backlog pendente em
[`docs/BACKLOG.md`](docs/BACKLOG.md); o que já foi feito, os bugs corrigidos e
as armadilhas de teste em [`docs/HISTORY.md`](docs/HISTORY.md).

## Como rodar

```sh
./run.sh                      # abre aqui, para testar (erros na hora)
./run.sh --cmd 'mc'           # comando inicial
./run-tests.sh                # testes, sem janela
uv run pytest -q              # só a parte pytest
python3 bzmux.py --selftest   # os mesmos checks, sem depender de pytest
python3 bzmux.py --help       # opções, sem abrir janela
```

## Durante o desenvolvimento

`./debug.sh` sobe pelo `run.sh`, mas com log em `/tmp/bzmux.log`, PID file
(`/tmp/bzmux.pid`), `--kill` e `--status` — é o script de quem está mexendo no
código, onde o `run.sh` seria só um atalho.

```sh
./debug.sh                    # abre em background
./debug.sh --fg               # em foreground, com a saída na hora
./debug.sh --kill             # fecha a instância do runner
./debug.sh --status           # pid / rodando?
```

## Ferramentas de teste

`./run-tests.sh` cobre o parser, os protocolos, o reflow e a seleção sem
display; os mesmos checks rodam por pytest e pelo `--selftest` (que não depende
de nada e por isso é o que garante que o caminho dos testes não puxa gi/cairo).
O que só se prova com janela aberta é feito à mão com `tools/xtest.py` (XTest:
tecla, clique, duplo clique, wheel, arrasto, texto) e conferido com
`tools/pixel.py` (cor de pixel numa captura) — ver
[`docs/HISTORY.md`](docs/HISTORY.md). Precisa de servidor X e de
`python3-xlib`.

## Ambiente (uv)

O projeto é um ambiente uv (pyproject.toml + uv.lock) e **o app roda no python
do venv**. O venv é criado sobre o python do sistema com `--system-site-packages`:
é assim que ele enxerga o PyGObject (gi) da distro, que não se instala por pip
sem sofrimento. `python-preference = system` garante a mesma versão do python.

```sh
uv venv --system-site-packages   # uma vez (o uv sync não passa essa flag)
uv sync                          # pytest
uv run pytest -q                 # testes
uv sync --extra tools            # + python-xlib (as tools rodam com python3)
./run.sh                         # app rodando em .venv/bin/python
```

O `run.sh` escolhe o interpretador: `.venv/bin/python` quando ele importa `gi`,
senão o `python3` do sistema — com um aviso dizendo como recriar o venv. Para
rodar na mão: `uv run python bzmux.py`.

## Como o código está organizado

`bzmux.py` é só o ponto de entrada; o código vive em `core/`:

```
bzmux.py                 # ponto de entrada: só chama core.cli.main
run.sh                   # roda o app (teste rápido; escolhe o python)
debug.sh                 # desenvolvimento: background, log, --kill/--status
run-tests.sh             # selftest + pytest
pyproject.toml           # ambiente uv (uv.lock)
core/
├── palette.py   # célula [char,fg,bg,flags], paleta xterm-256, charset DEC
├── term.py      # grade, cursor, parser VT — NÃO conhece Gtk
├── keys.py      # keyval do X11 -> bytes do filho (dead keys, DECCKM)
├── kitty_kbd.py # protocolo de teclado do kitty (CSI ... u)
├── mouse.py     # protocolo de mouse: SGR e o antigo (puro)
├── graphics.py  # protocolo de imagens do kitty (APC G, puro)
├── gui.py       # import único de Gtk/Gdk/GLib/Pango/cairo (require_version)
├── style.py     # tokens de cor do cromo + CSS gerado + contraste WCAG
├── view.py      # TermView: uma sessão (pty, desenho cairo+Pango, eventos)
├── window.py    # Workspace (Gtk.Notebook + cartão) e BzmuxWindow
├── checks.py    # a bateria de testes
├── selftest.py  # runner sem dependências (--selftest)
└── cli.py       # argv, -h/--help e arranque
tests/                   # runner pytest de core/checks.py
tools/                   # xtest.py, pixel.py (manual, precisa de X),
                         # doomfire.py (carga de medição, roda em qualquer um)
```

A regra é a dependência apontar para dentro: `term`/`palette` não importam
`window` nem `gui`. Por isso `--selftest` roda em máquina **sem PyGObject**
(o import de Gtk é tardio, dentro de `cli.main`), e a janela pode ser trocada
sem tocar no núcleo de emulação.

O `debug.sh` controla a instância por **PID file** (`/tmp/bzmux.pid`) de
propósito: `pkill -f bzmux.py` casa com a linha de comando de quem chama e
mata o próprio shell (já aconteceu, deixando janelas órfãs). Ele sobe o app
pelo `run.sh`, que é quem escolhe o interpretador (venv do uv ou o python do
sistema) — por isso testar à mão e desenvolver usam o mesmo python.

Depende só de PyGObject (Gtk3) + pycairo, que já existem no sistema.

## O que funciona

- **pty real** com `forkpty`-equivalente (`pty.fork`), resize por `TIOCSWINSZ`.
- **Parser VT** com estados ground/esc/csi/osc, SGR (16 cores, 256 e
  truecolor 24-bit de verdade), cursor (`CUP`/`CUU`/`CUD`/`CUF`/`CUB`/`CNL`/`CPL`/`CHA`),
  apagamento (`ED`/`EL`/`ECH`), inserção/remoção de linha e caractere
  (`IL`/`DL`/`ICH`/`DCH`), região de scroll (`DECSTBM`), save/restore
  (`DECSC`/`DECRC`, `CSI s`/`u`), `DECAWM`, cursor on/off (`?25`),
  **alt-screen** (`?1047`/`?1049`), charset DEC (`ESC ( 0`) para molduras,
  título por `OSC 0/2`, respostas `DA`/`CPR` de volta ao filho.
- **Scrollback** de 1000 linhas no buffer principal, **com tela de
  histórico**: `Shift+PgUp`/`PgDn` (e `Shift+Home`/`End`) deslizam a visão,
  o **wheel** rola a viewport — sem falar com o app quando ele não pediu
  mouse, e mandando `64`/`65` quando pediu. Volta ao vivo ao digitar, ao
  clicar ou quando o filho escreve. Um `↑N` no canto mostra o quanto se
  voltou; o cursor do app não é desenhado no histórico.
- **Teclado**: letras (incluindo UTF-8), setas, Home/End, PgUp/PgDn,
  Insert/Delete, F1–F12, Ctrl+letra, Alt+letra, Shift+Tab. Respeita
  **DECCKM (`?1`)**: com o modo aplicação ligado (o que `mc`, `vim` e `less`
  fazem em tela cheia) as setas viram `\EOA`..`\EOD`, como no terminfo de
  xterm — sem isso o `mc` ignorava as setas.
- **Só caractere imprimível vira byte**: keyval de modificador e de função
  fica em `0xff00-0xffff` (`Shift_L`=0xffe1, `Control_L`=0xffe3, `Alt_L`=0xffe9,
  `Super_L`=0xffeb, `Caps_Lock`=0xffe5, `Menu`=0xff67). Sem esse filtro cada
  uma dessas teclas virava um caractere sem glifo (a "caixinha" na tela).
- **Dead keys** (`´ \` ^ ~ ¨ ¸`): guarda a marca e compõe com a letra seguinte
  por NFC (`~`+`a` → `ã`); dead key + espaço emite o caractere isolado
  (`~`, `^`, `` ` ``...), a convenção do X11.
- **256 cores** (`TERM=xterm-256color`): paleta xterm completa (16 base +
  cubo 6×6×6 + 24 cinzas).
- **Truecolor 24-bit** (`38;2;r;g;b`/`48;2;…`, e a forma com `:`): o RGB fica na
  célula marcado no bit 24, sem tabela de cores alocadas — `vim` com
  `termguicolors`, `bat`, gradiente em texto saem com a cor exata.
- **Desenho** com cairo + Pango: runs agrupados por atributos, bold,
  sublinhado, inverso, cursor em bloco, shaping de verdade (árabe ligado,
  combinações) e fallback de fonte (CJK, emoji em cor).
- **Kitty keyboard protocol** (`core/kitty_kbd.py`): `CSI > flags u`
  (push), `CSI < n u` (pop), `CSI = flags ; modo u` (set/add/remove) e
  `CSI ? u` (query). Com `disambiguate`, Esc/Enter/Tab/Backspace e
  Ctrl/Alt/Super+tecla saem como `CSI codigo ; mods u`, então `Ctrl+Shift+letra`
  deixa de se confundir com `Ctrl+letra`; `report event types` acrescenta
  `:1`/`:2`/`:3`; `report all keys as escape codes` manda tudo em CSI-u;
  `report associated text` (`16`) anexa o texto da tecla.
- **Protocolo de gráficos do kitty** (`core/graphics.py`): APC `G` com
  `a=t`/`a=T`/`a=p`/`a=d`/`a=q`, `f=24` (RGB), `f=32` (RGBA) e `f=100` (PNG),
  imagem em pedaços (`m=1`), `i`/`c`/`r`/`C=1`/`q`, compressão `o=z` (zlib) e
  os offsets `X=`/`Y=` em pixels dentro da célula (é assim que o `icat`
  centraliza e posiciona). O `kitten icat` funciona inteiro, inclusive
  `--place` e `--scale-up` (detecta via `a=q` + `DA`, transmite em stream ou
  comprimido e desenha). As imagens rolam junto com o texto **inclusive para
  dentro do histórico**: `Shift+PgUp`/wheel trazem a imagem de volta na linha
  certa (a colocação vive na grade e pode ter linha negativa, como no kitty) e
  são desenhadas por cima das células.
- **Bracketed paste** (`?2004`): quando o app pede, o `Ctrl+Shift+V`/botão do
  meio mandam o texto entre `ESC[200~` e `ESC[201~` — o readline/vim sabem que
  é cola e não executam cada linha. Colar uma linha copiada com o mouse não
  ganha mais um `\n` no fim (era o que fazia o comando rodar sozinho).
- **Abas** (`Gtk.Notebook`): `Ctrl+Shift+T` abre, `Ctrl+Shift+W` fecha, `Alt+1`
  … `Alt+9` seleciona (`Alt+0` = a 10ª), clique do meio no rótulo fecha. O
  rótulo é o título do app (OSC 0/2) ou, sem OSC, o **cwd** da sessão; aba nova
  herda o cwd da atual via `/proc/<pid>/cwd`, e cada aba tem o seu `Term`,
  histórico, seleção e pty (o `P8` virou por aba: a última fecha a janela).
- **Workspaces** (tipo cmux): cada um com o seu conjunto de abas, numa lateral
  à esquerda que só aparece com 2+ workspaces. `Ctrl+Shift+N` cria,
  `Ctrl+Shift+1`…`9` seleciona, `Ctrl+Shift+Q` fecha (ou clique do meio no
  cartão); **duplo clique** no cartão renomeia (padrão "workspace N"). O cartão
  mostra `1  <nome>` e, embaixo, a aba ativa e a contagem. Fechar a última aba
  fecha o workspace; fechar o último workspace fecha o programa.
- **Fecha quando o shell termina**: `GLib.child_watch_add` reapa o filho (sem
  zumbi) e fecha a janela no `Ctrl+D`/`exit`; antes de fechar drena o que
  sobrou no pty (senão some a última tela) e manda `SIGHUP` pro grupo do filho
  (jobs em background não ficam órfãos).
- **Cromo escuro** (`core/style.py`): as cores da interface (lateral dos
  workspaces, cartões) vêm de uma tabela de tokens e o CSS é gerado dela — sem
  hex solto no código. A lateral é preta, o workspace ativo fica num verde
  escuro com texto claro, e o contraste (>= 4.5:1) é conferido por check. A
  paleta da célula do terminal é outra coisa e não se mistura com esta.
- **Reflow no resize**: linhas que quebraram mole são re-quebradas na largura
  nova (uma linha longa vira várias ao estreitar, volta a ser uma ao alargar),
  o cursor fica sobre o mesmo caractere e o scrollback é re-aproveitado. Fundo
  colorido de barra/status não é cortado junto com o espaço em branco.
- **Mouse**: reporta pro app quando ele pede (`?1000` clique, `?1002`
  arrasto, `?1003` movimento, `?1006` coordenadas SGR, `?1004` foco), e fora
  desses modos faz **seleção local** arrastando — e ela vira cópia:
  `Ctrl+Shift+C` copia (seleção ou viewport), `Ctrl+Shift+V` cola, e o
  **botão do meio** cola o PRIMARY (convenção X11). A seleção é vídeo
  reverso. Clique em `mc`/`vim` chega como `CSI < b ; x ; y M/m`.

Testado com `ls --color`, `mc` (painéis, molduras, barra de teclas, cores,
setas e resize 68x22 → 110x36 → 70x21 sem sobras) e `vim`/`less` (alt-screen).

## Limites conhecidos (de propósito)

- **Seleção só por célula**: sem duplo-clique por palavra e sem modo
  bloco/retangular.
- **Gráficos sem animação/z-index**: `a=f`/`a=a` são ignorados, sem
  `t=f`/`t=t`/`t=s` (arquivo, temp file, shared memory) e sem `z=` (z-index).
- **Caractere largo (CJK/emoji) ocupa uma célula**: a grade não tem `wcwidth`,
  então o glifo é desenhado na largura da célula e o espaçamento de app que
  conta coluna dupla (tabela em CJK) sai errado. Ligadura depende da fonte: com
  a Monospace padrão (DejaVu) quase não há, mas o shaping está lá.
- **Kitty keyboard protocol parcial**: sem `report alternate keys` (a flag 4
  exige o keysym alternativo, que o Gdk não entrega direto), sem repeat
  distinguido de press (o Gdk repete como key-press) e sem o modo de teclado
  numérico.
- **Sem busca no scrollback** e sem barra de rolagem clicável: só teclado e
  wheel, com o `↑N` no canto como indicador.
- **Sem arquivo de configuração/tema**: fonte e paleta são fixas no código, de
  propósito — o que está sendo medido é o caminho quente, não a customização.
- **Reflow só no buffer principal**: alt-screen (`mc`, `vim`) recorta/preenche
  de propósito — quem está em tela cheia se redesenha no SIGWINCH, e re-quebrar
  por cima do que ele escreveu só atrapalharia.

## O que a medição realmente mostra (corrigido)

Medido nesta máquina (2026-10-26):

| cenário | bzmux (Python) | núcleo nativo (referência) |
|---|---|---|
| **uma tecla** (eco de 1 char) | **0,4 µs por caractere** | ~1 ms de ponta a ponta (dominado por desenho) |
| parse + grade, despejo contínuo | **0,7–1,9 MiB/s** | 300–800 MiB/s (`rio-vt`, `alacritty_terminal`, `vt100`) |
| `seq 1 100000` (575 KiB) | **~0,8 s** | milissegundos |
| desenho de 1 frame (1920 células) | ~2,0 ms | ~1 ms (T2→T3 do `lat-battery`) |
| doom-fire, tela cheia trocando de cor (`tools/doomfire.py`) | **11,0 fps / 0,5 MB/s** | 314 fps / 15,9 MB/s (kitty) |

A carga do doom-fire (tela toda trocando de cor, pior caso do parser) tem
detalhe, protocolo e armadilhas em [`docs/DOOM-FIRE.md`](docs/DOOM-FIRE.md).

Conclusão honesta: **na interação o bzmux é imperceptível** — digitar, andar
no `mc`, abrir `vim` custa microssegundos por tecla, porque a carga por evento
é minúscula. A diferença de 100–400× só aparece em **volume**: `cat` de log
grande, `seq 100000`, scroll de saída massiva — aí são centenas de ms contra
milissegundos.

Ou seja: Python não impede um terminal *usável*; impede um terminal que não
engasga em despejo grande. É por isso que o kitty é Python onde dá
(boss/config/CLI/kittens) e C onde o volume chega (grade/parser/render) — e é
o mesmo motivo pelo qual o `gtkterm` usa o núcleo C.

## Autochetcagem

`kill -USR1 <pid>` dumpar a grade visível em `/tmp/bzmux-dump.txt` (ou no
arquivo de `--dump-to`) — foi assim que se provou que o `mc` é renderizado
fielmente: o dump bate byte a byte com o que o `mc` escreve.

`uv run pytest -q` exercita parser e protocolos sem GTK: texto, SGR/EL/ED,
CUP, alt-screen (ida e volta), scroll, charset DEC, DA/DSR/CPR, CSI com
intermediário, região de scroll, título por OSC, reflow, histórico, mouse,
seleção, paste, truecolor, teclado do kitty, gráficos e argv.

## Licença

**MIT** (ver `LICENSE`). O `bzmux` é código original, sem uma linha do
kitty, então a licença dele não é ditada pelo núcleo: importa apenas `pty`,
`termios`, `unicodedata`, `gi` (Gtk3, LGPL-2.1+) e `pycairo` (LGPL/MPL).
Estar no mesmo repositório não contamina — arquivos separados, sem linkagem
nem import. O lado C, que ficou no outro repositório, continua GPL-3.0-only
por derivar do kitty.
