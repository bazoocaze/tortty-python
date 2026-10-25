# TASK-bzmux — terminal mínimo em Python (experimento de custo do caminho quente)

Status: **experimento funcional** (2026-10-26) — roda shell, `mc`, `vim`; tem
mouse com seleção/cópia, histórico, reflow, truecolor, bracketed paste,
protocolo de teclado e de imagens do kitty, **abas** e **workspaces**
(**P1**–**P8**, **P11**, **P12** concluídos — [docs/HISTORY.md](docs/HISTORY.md);
só **P9**/**P10** em aberto — [docs/BACKLOG.md](docs/BACKLOG.md)).
Não é produto nem caminho de produção: existe para responder, com número, à
pergunta "daria pra implementar tudo em Python?".
Criado em: 2026-10-26. Código na raiz deste repositório: `bzmux.py` (ponto de
entrada) + pacote `core/` (`palette.py`, `term.py`, `keys.py`, `kitty_kbd.py`,
`mouse.py`, `graphics.py`, `gui.py`, `view.py`, `window.py`, `checks.py`,
`selftest.py`, `cli.py`), a bateria em `tests/`, as ferramentas manuais em
`tools/`, mais `run.sh`, `run-tests.sh`, `pyproject.toml`/`uv.lock`,
`README.md`, `AGENTS.md`, `LICENSE`.

**Histórico:** o projeto nasceu dentro do repositório do experimento `kitty`
(`~/dados/workflows/temp/kitty`), na pasta `pyterm/`, com o nome **pyterm**.
Em 2026-10-25 virou repositório próprio, `pybzmux`, com o nome **bzmux** — os
commits até aí vieram por `git subtree split`, então as mensagens antigas ainda
dizem `pyterm` e os caminhos da época eram `pyterm/...`. A parte C/GTK do kitty
(`native-port/`, GPL-3.0-only) continua no outro repositório e não é compilada
nem testada aqui.

### Por onde retomar

```sh
./run-tests.sh                  # bateria (selftest + pytest), sem display
./run.sh --cmd 'mc -d /usr/share'
```

Nada pela metade: árvore limpa, tudo commitado.

Feitos (como foi feito e verificado: [docs/HISTORY.md](docs/HISTORY.md)):
**P1** (mouse/seleção/cópia), **P2** (histórico + wheel), **P3**
(reflow), **P4** (truecolor RGB na célula), **P5** (kitty keyboard), **P6**
(gráficos, com `kitten icat` e imagens no histórico), **P7** (bracketed paste
— e o `\n` espúrio do `copy()`, que fazia o paste executar), **P8** (fechar
quando o shell sai), **P11** (abas) e **P12** (workspaces).

Fila sugerida: **P9/P10** em [docs/BACKLOG.md](docs/BACKLOG.md) — shaping e
fallback de fonte, que na prática caem juntos na migração pra Pango. Itens de
UI (P11 abas, P12 workspaces) fechados.

## Documentos

| arquivo | conteúdo |
|---|---|
| `TASK-bzmux.md` (este) | status, por onde retomar, objetivo, escopo, arquitetura, estado, medições, como testar, licença |
| `docs/BACKLOG.md` | backlog pendente (P9, P10) |
| `docs/HISTORY.md` | backlog concluído, bugs corrigidos, quirks, git |
| `README.md` | único doc para humano: como rodar, o que funciona, limites, medição |
| `AGENTS.md` | convenções e arquitetura curta |

---

## Objetivo

Medir na prática o que o núcleo C compra. O `gtkterm` usa o núcleo de emulação
do kitty compilado como `libkittycore.a`; o `bzmux` reimplementa o mesmo
caminho quente (parse VT + grade de células + desenho) em Python puro, sem VTE
nem nenhuma lib de terminal, e serve de termômetro: se a versão em Python for
usável no dia a dia, o argumento "precisa ser C" perde força; se engasgar, o
número mostra onde.

**Não objetivo:** virar o app. Nada do `bzmux` é compartilhado com o
`native-port/` e o `build.sh` da raiz não o compila nem o testa.

## Escopo

Dentro:

- pty real (`pty.fork`), resize por `TIOCSWINSZ`, SIGWINCH para o filho.
- Parser VT com máquina de estados ground/esc/csi/osc/apc/charset.
- Grade de células com atributos, scrollback de 1000 linhas, alt-screen,
  reflow no resize.
- Desenho em cairo com runs agrupados por atributo (+ imagens do protocolo).
- Teclado suficiente para shell, `mc` e `vim`, com mouse/colar/copiar e o
  protocolo de teclado do kitty.

Fora (por decisão, não por falta de tempo):

- Busca no scrollback e barra de rolagem clicável.
- Arquivo de configuração/tema: a fonte e a paleta são fixas no código, de
  propósito — o que está sendo medido é o caminho quente, não a customização.

## Arquitetura (como está)

```
bzmux.py                # ponto de entrada (só chama core.cli.main)
run.sh                  # abre/fecha o app por PID file (/tmp/bzmux.pid)
run-tests.sh            # roda a bateria: --selftest e depois pytest
pyproject.toml          # ambiente uv (uv.lock): pytest como grupo dev
core/
├── palette.py   # célula [char,fg,bg,flags], palette xterm-256, charset DEC
├── term.py      # Term: grade, cursor, parser. SEM GTK.
│   ├── feed(text) # máquina de estados: ground/esc/csi/osc/charset
│   ├── put/chars  # escrita de célula, wrap, CR/LF/BS/TAB, charset DEC
│   ├── csi_dispatch/sgr/set_mode
│   └── child_out  # respostas ao filho (DA, CPR) — o host drena pro pty
├── keys.py      # encode_key(): keyval do X11 -> bytes do filho
│                #   (tabelas SIMPLE/APP_CURSOR, dead keys, filtro de keyval)
├── kitty_kbd.py # protocolo de teclado do kitty: CSI ... u (flags/pilha)
├── mouse.py     # protocolo de mouse: SGR e o antigo (puro, sem Gtk)
├── graphics.py  # protocolo de imagens do kitty: APC G (puro, sem cairo)
├── gui.py       # import único de Gtk/Gdk/GLib/cairo (require_version aqui)
├── view.py      # TermView (uma sessão, por aba)
│   ├── spawn/on_pty (GLib.io_add_watch no master)
│   ├── on_resize (size-allocate) -> Term.resize + TIOCSWINSZ + SIGWINCH
│   ├── on_draw (cairo: fundo, runs por atributo, imagens, cursor bloco)
│   ├── on_key (delega em keys.encode_key e escreve no pty)
│   └── mouse/seleção/cópia, histórico (view_off), wheel
├── window.py    # Workspace + BzmuxWindow
│   ├── Workspace: Gtk.Notebook + cartão da lateral (nome, aba ativa)
│   ├── abas: Ctrl+Shift+T/W, Alt+N, clique do meio, rótulo OSC-ou-cwd
│   ├── workspaces: Ctrl+Shift+N, Ctrl+Shift+1..9, Ctrl+Shift+Q, duplo
│   │   clique renomeia, lateral só com 2+
│   └── dump/quit-after/SIGUSR1 (agrega workspaces e abas)
├── checks.py    # a bateria de testes, sem abrir janela
├── selftest.py  # runner sem dependências do --selftest
└── cli.py       # argv, -h/--help e arranque (import tardio do Gtk: --selftest
                 #   e --help rodam em máquina sem PyGObject)
tests/                  # runner pytest de core/checks.py
tools/                  # xtest.py, pixel.py — teste manual, precisa de X
```

A direção das dependências é para dentro: `palette` ← `term` ← (`keys`,
`checks`) e `view`/`window` em cima de todos; nada em `term.py` importa Gtk.
`view` e `window` são a mesma camada: `window` só empilha views.

Célula é uma lista `[char, fg, bg, flags]` com `fg/bg` em índice xterm
(0–255, `256`=fg default, `257`=bg default) e `flags` bitmask
(bold/underline/inverse). O desenho agrupa células vizinhas com atributos
iguais num único `show_text` — foi o que trouxe o frame de 1920 células para
~2 ms.

## Estado atual (2026-10-26)

Verificado funcionando: `ls --color`, `dmesg`, `seq 1 100000`, `mc`
(painéis, molduras DEC, barra de teclas, cores, **setas**, **resize**
68x22 → 110x36 → 70x21 sem sobras, inclusive saindo da tela cheia depois do
resize), `vim`/`less` (alt-screen), digitação com acento (`~`+`a` → `ã`),
**mouse** em `mc`/`vim` e seleção/cópia local, **histórico** com `Shift+PgUp` e
wheel, **reflow** ao estreitar/alargar, **`kitten icat`** desenhando PNG,
**abas** (ativa independente por aba, cwd herdado, título OSC no rótulo) e
**workspaces** (lateral, renomear, fechar por aba/workspace/janela).

Teste automatizado: `./run-tests.sh` — os mesmos checks passam pelo `--selftest`
(sem dependências) e pelo pytest, sem display — mais injeção sintética de
mouse/teclado via XTest (`tools/xtest.py`, no repo) — foi assim que
P1/P2/P5/P11/P12 foram verificados de ponta a ponta.

### Medições (nesta máquina, 2026-10-26)

| cenário | bzmux (Python) | núcleo nativo (referência) |
|---|---|---|
| uma tecla (eco de 1 char) | **0,4 µs por caractere** | ~1 ms de ponta a ponta (dominado por desenho) |
| parse + grade, despejo contínuo | **0,7–1,9 MiB/s** | 300–800 MiB/s (`rio-vt`, `alacritty_terminal`, `vt100`) |
| `seq 1 100000` (575 KiB) | **~0,8 s** | milissegundos |
| desenho de 1 frame (1920 células) | ~2,0 ms | ~1 ms (T2→T3 do `lat-battery`) |

**Conclusão honesta:** na interação o `bzmux` é imperceptível — a carga por
evento é minúscula. A desvantagem de 100–400× só aparece em **volume**
(despejo grande). Ou seja, Python não impede um terminal usável; impede um
terminal que não engasga em `cat` de log gigante. É o mesmo motivo pelo qual o
kitty é Python onde dá (boss/config/CLI/kittens) e C onde o volume chega
(grade/parser/render).

## Como testar

**Filosofia:** poucos checks, nos caminhos críticos — sem suíte exaustiva. A
diretriz está no [`AGENTS.md`](AGENTS.md) do repositório. Na prática:
`core/checks.py` tem uma função por área (parser, SGR/EL/ED, alt-screen e
scroll, charset e respostas, CSI com intermediário, CLI, teclado do kitty,
gráficos, reflow, histórico, mouse, seleção, paste, truecolor), com asserts de
coisas que já quebraram. O resto é smoke test manual com clique/tecla de
verdade.

```sh
./run-tests.sh                      # bateria: selftest + pytest (dia a dia)
./run-tests.sh -k graphics -x       # extras vão para o pytest
./run-tests.sh --selftest-only      # só o runner sem dependências
```

Duas portas para a mesma bateria, de propósito: `python3 bzmux.py --selftest`
(`core/selftest.py`) não importa pytest e, do projeto, só `term`, `palette`,
`mouse`, `kitty_kbd` e `cli` — nenhum deles puxa gi/cairo. É ele, então, que
prova que o caminho dos testes segue GTK-free: se alguém puser um
`from .gui import ...` ali, o pytest continua verde e o `--selftest` quebra.

### Ambiente (uv)

`pyproject.toml` + `uv.lock` (`package = false`, `python-preference = system`).
O app roda no venv do uv, criado sobre o python do sistema com
`--system-site-packages`: é isso que deixa o `gi` da distro visível (PyGObject
não se instala por pip sem sofrimento). Essa flag não existe no `uv sync`,
então o venv é criado uma vez à mão — e o `uv sync` preserva a configuração.

```sh
uv venv --system-site-packages # uma vez, antes do primeiro sync
uv sync                        # .venv com pytest
uv run pytest -q               # só a parte pytest
uv sync --extra tools          # + python-xlib (as tools rodam com python3)
./run.sh                       # app em .venv/bin/python
uv run python bzmux.py --help  # equivalente, sem o runner
```

O `run.sh` prefere `.venv/bin/python` e cai para o `python3` do sistema (com
aviso) se o venv não importar `gi` — venv criado sem a flag acima, por exemplo.

Opções do app: `--cmd`, `--quit-after`, `--dump-to`, `--selftest`, `-h/--help`.

### Teste manual, com janela

```sh
./run.sh                            # abre (fecha a instância anterior)
./run.sh --cmd 'mc -d /usr/share'   # direto no mc
./run.sh --status                   # pid / rodando?
./run.sh --kill                     # fecha
kill -USR1 $(cat /tmp/bzmux.pid)   # dumpar a grade em /tmp/bzmux-dump.txt
```

Injeção de teclas para teste automatizado (do projeto C):

```sh
./native-port/build/xkey-latency key "bzmux" '<dead_tilde>a<Return>'
```

`<...>` aceita nomes (`Return`, `Up`, `space`, `dead_tilde`, `Shift_L`...) e
prefixos `C-`, `S-`, `M-`, `A-`.

Atalhos globais (`Ctrl+Shift+N/1..9/Q`, `Alt+N`) e o duplo clique no cartão da
lateral saem de `tools/xtest.py`:

```sh
python3 tools/xtest.py key ctrl+shift+n     # workspace novo
python3 tools/xtest.py dclick 60 28         # duplo clique no cartão 1
python3 tools/xtest.py type 'echo ok'       # texto com símbolos
kill -USR1 $(cat /tmp/bzmux.pid)            # dumpar
```

O efeito aparece em `/tmp/bzmux-dump.txt` (cabeçalhos `=== workspace N: nome ===`
e `=== aba N: título ===` só quando há mais de um).

## Licença

**MIT** (2026-10-26), ver `bzmux/LICENSE`.

Por que não GPL, se o resto do repo é GPL-3.0-only: o `bzmux.py` (e agora o
pacote `core/`) **não é derivado do kitty** — é código original que só
importa `pty`, `termios`, `unicodedata`, `gi` (Gtk3, LGPL-2.1+) e `pycairo`
(LGPL/MPL). Estar no mesmo
repositório não contamina: são arquivos separados, sem linkagem nem import.
Quem é GPL por derivação é o `native-port/`, que linka `libkittycore.a`
compilado do kitty (GPLv3) — e lá os headers por arquivo continuam dizendo
`GPL-3.0-only`, corretamente.

A frase anterior neste arquivo ("GPL-3.0-only, como o resto do projeto
(derivado do kitty)") estava **errada** na justificativa.
