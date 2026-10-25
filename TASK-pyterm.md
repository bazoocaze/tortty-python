# TASK-pyterm — terminal mínimo em Python (experimento de custo do caminho quente)

Status: **experimento funcional** (2026-10-26) — roda shell, `mc` e `vim`.
Não é produto nem caminho de produção: existe para responder, com número, à
pergunta "daria pra implementar tudo em Python?".
Criada em: 2026-10-26. Código em `pyterm/` (`pyterm.py`, `run.sh`, `README.md`).

---

## Objetivo

Medir na prática o que o núcleo C compra. O `gtkterm` usa o núcleo de emulação
do kitty compilado como `libkittycore.a`; o `pyterm` reimplementa o mesmo
caminho quente (parse VT + grade de células + desenho) em Python puro, sem VTE
nem nenhuma lib de terminal, e serve de termômetro: se a versão em Python for
usável no dia a dia, o argumento "precisa ser C" perde força; se engasgar, o
número mostra onde.

**Não objetivo:** virar o app. Nada do `pyterm` é compartilhado com o
`native-port/` e o `build.sh` da raiz não o compila nem o testa.

## Escopo

Dentro:

- pty real (`pty.fork`), resize por `TIOCSWINSZ`, SIGWINCH para o filho.
- Parser VT com máquina de estados ground/esc/csi/osc/charset.
- Grade de células com atributos, scrollback de 1000 linhas, alt-screen.
- Desenho em cairo com runs agrupados por atributo.
- Teclado suficiente para shell, `mc` e `vim`.

Fora (por decisão, não por falta de tempo):

- Mouse (report a apps e seleção/cópia).
- Protocolo de gráficos do kitty (nada de `kitten icat`) e kitty keyboard
  protocol.
- Reflow no resize e tela de histórico (scrollback só guarda).
- Truecolor fiel (aproxima para a paleta xterm de 256).
- Ligaduras, fallback de fonte para emoji/CJK, bracketed paste, busca.

## Arquitetura (como está)

```
pyterm.py
├── Term           # estado puro: grade, cursor, parser. SEM GTK.
│   ├── feed(text) # máquina de estados: ground/esc/csi/osc/charset
│   ├── put/chars  # escrita de célula, wrap, CR/LF/BS/TAB, charset DEC
│   ├── csi_dispatch/sgr/set_mode
│   └── child_out  # respostas ao filho (DA, CPR) — o host drena pro pty
├── PyTermWindow   # Gtk.Window + Gtk.DrawingArea
│   ├── spawn/on_pty (GLib.io_add_watch no master)
│   ├── on_resize (size-allocate) -> Term.resize + TIOCSWINSZ + SIGWINCH
│   ├── on_draw (cairo: fundo, runs por atributo, cursor bloco)
│   └── on_key (keyval -> bytes do terminal)
├── selftest()     # 14 checks do parser, sem abrir janela
└── run.sh         # controle de instância por PID file
```

Célula é uma lista `[char, fg, bg, flags]` com `fg/bg` em índice xterm
(0–255, `256`=fg default, `257`=bg default) e `flags` bitmask
(bold/underline/inverse). O desenho agrupa células vizinhas com atributos
iguais num único `show_text` — foi o que trouxe o frame de 1920 células para
~2 ms.

## Estado atual (2026-10-26)

Verificado funcionando: `ls --color`, `dmesg`, `seq 1 100000`, `mc`
(painéis, molduras DEC, barra de teclas, cores, **setas**, **resize**
68x22 → 110x36 → 70x21 sem sobras), `vim`/`less` (alt-screen), digitação com
acento (`~`+`a` → `ã`).

### Medições (nesta máquina, 2026-10-26)

| cenário | pyterm (Python) | núcleo nativo (referência) |
|---|---|---|
| uma tecla (eco de 1 char) | **0,4 µs por caractere** | ~1 ms de ponta a ponta (dominado por desenho) |
| parse + grade, despejo contínuo | **0,7–1,9 MiB/s** | 300–800 MiB/s (`rio-vt`, `alacritty_terminal`, `vt100`) |
| `seq 1 100000` (575 KiB) | **~0,8 s** | milissegundos |
| desenho de 1 frame (1920 células) | ~2,0 ms | ~1 ms (T2→T3 do `lat-battery`) |

**Conclusão honesta:** na interação o `pyterm` é imperceptível — a carga por
evento é minúscula. A desvantagem de 100–400× só aparece em **volume**
(despejo grande). Ou seja, Python não impede um terminal usável; impede um
terminal que não engasga em `cat` de log gigante. É o mesmo motivo pelo qual o
kitty é Python onde dá (boss/config/CLI/kittens) e C onde o volume chega
(grade/parser/render).

## Bugs encontrados e corrigidos (histórico útil)

Todos foram achados com medição, não por leitura — vale registrar o método.

1. **Métrica de célula errada (texto derrapando).** A largura da célula vinha
   de `text_extents("M").width` (680/75 ≈ 9,06 px) e o avanço real da fonte era
   maior, então as colunas desalinhavam e o texto sobrepunha. Fix: largura =
   `ceil(x_advance)`, altura = `ceil(ascent + descent)`.
2. **`resize` apagava a tela.** O `Term.resize` recriava a grade em branco; se
   o configure chegasse depois do primeiro output, o texto sumia. Fix: preserva
   recortando/preenchendo.
3. **`configure-event` não aplicava o resize.** O sinal do `GtkWindow` chega
   **antes** de o filho ser re-alocado, então `get_allocation()` devolvia o
   tamanho antigo e o `mc` ficava com layout quebrado. Fix: `size-allocate` na
   `DrawingArea`, usando a alocação recebida.
4. **Setas ignoradas no `mc`.** `mc`/`vim`/`less` ligam `DECCKM` (`?1`) e
   passam a esperar `\EOA`..`\EOD` (modo aplicação do terminfo de xterm); eu
   mandava sempre `\E[A`. Fix: rastrear `?1` e trocar a forma das setas,
   Home e End.
5. **Modificadores viravam caractere ("caixinha").** `Shift_L`, `Control_L`,
   `Alt_L`, `Super_L`, `Caps_Lock`, `Menu` têm keyval em `0xff00–0xffff`, e o
   fallback fazia `chr(kv)` → caractere sem glifo. Fix: só envia caractere
   imprimível (latin-1 `0x20–0x7e`/`0xa0–0xff` ou unicode `0x01000000+U`).
6. **Dead keys não faziam nada.** Fix: guarda a marca e compõe por NFC
   (`~`+`a` → `ã`); dead key + espaço emite o isolado (`~`, `^`, `` ` ``...).
7. **`DA` nunca respondia.** `CSI c` sem parâmetros virava `[0]` no parser e a
   condição `not params` falhava. Fix: corpo vazio → lista vazia.

## Como testar

```sh
cd pyterm
python3 pyterm.py --selftest        # 14 checks do parser, sem abrir janela
./run.sh                            # abre (fecha a instância anterior)
./run.sh --cmd 'mc -d /usr/share'   # direto no mc
./run.sh --status                   # pid / rodando?
./run.sh --kill                     # fecha
kill -USR1 $(cat /tmp/pyterm.pid)   # dumpar a grade em /tmp/pyterm-dump.txt
```

Injeção de teclas para teste automatizado (do projeto C):

```sh
./native-port/build/xkey-latency key "pyterm" '<dead_tilde>a<Return>'
```

`<...>` aceita nomes (`Return`, `Up`, `space`, `dead_tilde`, `Shift_L`...) e
prefixos `C-`, `S-`, `M-`, `A-`.

## Backlog

Ordem não implica prioridade.

### P1 — Mouse (report a apps + seleção/cópia) — não iniciado

`mc` e `vim` funcionam sem mouse, mas selecionar texto para copiar não existe.
Falta: `?1000`/`?1002`/`?1006` (report SGR), `?1004` (foco), arrastar para
selecionar na grade, `Ctrl+Shift+C` copiando a seleção (ou a viewport).

### P2 — Tela de histórico (rolar scrollback) — não iniciado

O scrollback guarda 1000 linhas mas não há como olhar para trás: `Shift+PgUp`
deveria entrar num modo de histórico (cursor de visão separado do cursor do
app) e voltar ao vivo ao digitar.

### P3 — Reflow no resize — não iniciado

Hoje recorta/preenche. Reflow (re-quebrar linhas longas ao estreitar) é o que
terminais modernos fazem; exige guardar linhas lógicas em vez de linhas de
tela.

### P4 — Truecolor de verdade — não iniciado

`38;2;r;g;b` é aproximado para a paleta de 256. Fix: guardar RGB na célula
(mais memória por célula) ou uma tabela de cores alocadas.

### P5 — Kitty keyboard protocol — não iniciado

Sem ele, `Ctrl+Shift+letra` chega como `Ctrl+letra` e apps não distinguem
modificadores. Relevante se o `pyterm` virar banco de testes de input.

### P6 — Protocolo de gráficos (kitty) — não iniciado

Nada de `kitten icat`. Seria a versão Python do que o `gtkterm` já faz
(handshake, decode, desenho) — só faz sentido como comparação de custo.

### P7 — Bracketed paste e ligaduras/fallback de fonte — não iniciado

Colar multi-linha hoje pode disparar comandos; ligaduras e emoji/CJK caem em
glifo ausente.

## Quirks registrados (não redescobrir)

- **`pkill -f pyterm.py` mata o próprio shell** de quem chama (o padrão casa com
  a linha de comando) e já deixou janelas órfãs. Usar `./run.sh --kill`, que
  confere o PID file contra `/proc/<pid>/cmdline` antes de matar.
- **`wmctrl -r pyterm` deixa de funcionar** quando o app muda o título por OSC
  (`mc` faz isso). Para achar a janela, casar por `_NET_WM_PID` contra o PID do
  runner.
- **`import -window root -crop` com geometria de `xwininfo`** só funciona com a
  janela ativada antes; senão captura a janela que estiver por cima.
- **O `.n  Name` e os nomes truncados com `~` no `mc` são do próprio `mc`**
  (conferido nos bytes crus: ele escreve `.n  Name` e trunca conforme a largura
  do painel). Não é bug de renderização.
- **Injetar `<Caps_Lock>` liga a trava de verdade** no servidor X: o teste
  seguinte sai em maiúsculas. Desligar com outro `<Caps_Lock>` e conferir com
  `xset q`.
- **`chr(kv)` para keyval de tecla especial não existe**: só `0x20–0x7e`,
  `0xa0–0xff` e `0x01000000+U` são caractere. O resto é modificador/função.
- **`cairo` com `FORMAT_A1`** serve para medir fonte, mas `font_extents()`
  devolve **5** valores (ascent, descent, height, max_x_advance,
  max_y_advance) — não 6.

## Git

- `a86ec5b` — `pyterm: terminal minimo em Python (experimento de custo do
  caminho quente)` (pyterm.py, run.sh, README.md).
- `25a8b01` — `xkey-latency: nomes de modificador e prefixo C-/S-/M-/A- correto`
  (ferramenta do projeto C; o parser lia `<Menu>`/`<Caps_Lock>` como prefixo).

## Licença

**MIT** (2026-10-26), ver `pyterm/LICENSE`.

Por que não GPL, se o resto do repo é GPL-3.0-only: o `pyterm.py` **não é
derivado do kitty** — é código original que só importa `pty`, `termios`,
`unicodedata`, `gi` (Gtk3, LGPL-2.1+) e `pycairo` (LGPL/MPL). Estar no mesmo
repositório não contamina: são arquivos separados, sem linkagem nem import.
Quem é GPL por derivação é o `native-port/`, que linka `libkittycore.a`
compilado do kitty (GPLv3) — e lá os headers por arquivo continuam dizendo
`GPL-3.0-only`, corretamente.

A frase anterior neste arquivo ("GPL-3.0-only, como o resto do projeto
(derivado do kitty)") estava **errada** na justificativa.
