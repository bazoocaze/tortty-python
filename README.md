# pyterm — terminal mínimo em Python (experimento)

Terminal de verdade (pty + parse VT + grade + cairo) escrito em **Python puro**,
para sentir na pele o custo do caminho quente em Python comparado ao núcleo C
do `gtkterm`. Não é produto: é a resposta empírica à pergunta "daria pra fazer
tudo em Python?". Escopo, medições, bugs já corrigidos, backlog e armadilhas de
teste ficam em [`TASK-pyterm.md`](../TASK-pyterm.md).

## Como rodar

```sh
cd pyterm
./run.sh                      # abre em background (log /tmp/pyterm.log)
./run.sh --fg                 # foreground (erros aparecem na hora)
./run.sh --cmd 'mc'           # comando inicial
./run.sh --kill               # fecha a instância do runner
./run.sh --status             # pid / rodando?
python3 pyterm.py --selftest  # testa o parser sem abrir janela (14 checks)
```

## Como o código está organizado

`pyterm.py` é só o ponto de entrada; o código vive em `pyterm_core/`:

```
pyterm.py                 # 20 linhas: só chama pyterm_core.cli.main
pyterm_core/
├── palette.py   # célula [char,fg,bg,flags], paleta xterm-256, charset DEC
├── term.py      # grade, cursor, parser VT — NÃO conhece Gtk
├── keys.py      # keyval do X11 -> bytes do filho (dead keys, DECCKM)
├── gui.py       # import único de Gtk/Gdk/GLib/cairo (require_version)
├── window.py    # janela GTK: pty, io_add_watch, desenho cairo, eventos
├── selftest.py  # 14 checks do parser
└── cli.py       # argv e arranque
```

A regra é a dependência apontar para dentro: `term`/`palette` não importam
`window` nem `gui`. Por isso `--selftest` roda em máquina **sem PyGObject**
(o import de Gtk é tardio, dentro de `cli.main`), e a janela pode ser trocada
sem tocar no núcleo de emulação.

O `run.sh` controla a instância por **PID file** (`/tmp/pyterm.pid`) de
propósito: `pkill -f pyterm.py` casa com a linha de comando de quem chama e
mata o próprio shell (já aconteceu, deixando janelas órfãs).

Depende só de PyGObject (Gtk3) + pycairo, que já existem no sistema.

## O que funciona

- **pty real** com `forkpty`-equivalente (`pty.fork`), resize por `TIOCSWINSZ`.
- **Parser VT** com estados ground/esc/csi/osc, SGR (16 cores, 256 e truecolor
  aproximado), cursor (`CUP`/`CUU`/`CUD`/`CUF`/`CUB`/`CNL`/`CPL`/`CHA`),
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
  cubo 6×6×6 + 24 cinzas); truecolor é aproximado para essa paleta.
- **Desenho** com cairo: runs agrupados por atributos, bold, sublinhado,
  inverso, cursor em bloco.
- **Kitty keyboard protocol** (`pyterm_core/kitty_kbd.py`): `CSI > flags u`
  (push), `CSI < n u` (pop), `CSI = flags ; modo u` (set/add/remove) e
  `CSI ? u` (query). Com `disambiguate`, Esc/Enter/Tab/Backspace e
  Ctrl/Alt/Super+tecla saem como `CSI codigo ; mods u`, então `Ctrl+Shift+letra`
  deixa de se confundir com `Ctrl+letra`; `report event types` acrescenta
  `:1`/`:2`/`:3`; `report all keys as escape codes` manda tudo em CSI-u.
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
- **Truecolor aproximado** para a paleta de 16 cores.
- **Sem protocolo de gráficos** (nada de `kitten icat`).
- **Sem ligaduras**, sem fontes fallback para emoji/CJK.
- **Kitty keyboard protocol parcial**: sem `report alternate keys` (a flag 4
  exige o keysym alternativo, que o Gdk não entrega direto), sem repeat
  distinguido de press (o Gdk repete como key-press) e sem o modo de teclado
  numérico.
- **Histórico sem barra de rolagem** clicável: só teclado/wheel, com o `↑N`
  no canto como indicador.
- **Reflow só no buffer principal**: alt-screen (`mc`, `vim`) recorta/preenche
  de propósito — quem está em tela cheia se redesenha no SIGWINCH, e re-quebrar
  por cima do que ele escreveu só atrapalharia.

## O que a medição realmente mostra (corrigido)

Medido nesta máquina (2026-10-26):

| cenário | pyterm (Python) | núcleo nativo (referência) |
|---|---|---|
| **uma tecla** (eco de 1 char) | **0,4 µs por caractere** | ~1 ms de ponta a ponta (dominado por desenho) |
| parse + grade, despejo contínuo | **0,7–1,9 MiB/s** | 300–800 MiB/s (`rio-vt`, `alacritty_terminal`, `vt100`) |
| `seq 1 100000` (575 KiB) | **~0,8 s** | milissegundos |
| desenho de 1 frame (1920 células) | ~2,0 ms | ~1 ms (T2→T3 do `lat-battery`) |

Conclusão honesta: **na interação o pyterm é imperceptível** — digitar, andar
no `mc`, abrir `vim` custa microssegundos por tecla, porque a carga por evento
é minúscula. A diferença de 100–400× só aparece em **volume**: `cat` de log
grande, `seq 100000`, scroll de saída massiva — aí são centenas de ms contra
milissegundos.

Ou seja: Python não impede um terminal *usável*; impede um terminal que não
engasga em despejo grande. É por isso que o kitty é Python onde dá
(boss/config/CLI/kittens) e C onde o volume chega (grade/parser/render) — e é
o mesmo motivo pelo qual o `gtkterm` usa o núcleo C.

## Autochetcagem

`kill -USR1 <pid>` dumpar a grade visível em `/tmp/pyterm-dump.txt` (ou no
arquivo de `--dump-to`) — foi assim que se provou que o `mc` é renderizado
fielmente: o dump bate byte a byte com o que o `mc` escreve.

`python3 pyterm.py --selftest` exercita o parser sem GTK: texto, SGR, CUP,
EL/ED, alt-screen (ida e volta), scroll, charset DEC, DA, DSR/CPR, região de
scroll e título por OSC.

## Licença

**MIT** (ver `LICENSE`). O `pyterm` é código original, sem uma linha do
kitty, então a licença dele não é ditada pelo núcleo. O `native-port/` continua
**GPL-3.0-only** porque linka `libkittycore.a` (derivado do kitty).
