# bzmux

Terminal em Python puro: pty + parser VT + grade + desenho com cairo + Pango.
Nasceu como experimento para medir o custo do caminho quente em Python e virou
aplicação real de uso diário: shell, mc e vim; mouse com seleção/cópia,
histórico com wheel, reflow, truecolor, protocolo de teclado e de imagens do
kitty, bracketed paste, abas e workspaces. A medição continua sendo a régua
(docs/BENCHMARKS.md); o que não é feito e por quê: docs/LIMITATIONS.md.
Este arquivo é convenção; o conteúdo muda de lugar conforme o tipo (ver
Documentação).

## Documentação

Divisão por tipo de conteúdo — cada fato mora em um só lugar, não duplicar.
Todos são escritos para leitura de agente; só o README.md é para humano.

- AGENTS.md (este) — convenções, arquitetura, scripts, ferramentas.
- TASK-bzmux.md — ficha magra: status, por onde retomar, fila.
- docs/BACKLOG.md — backlog pendente e as regras da fila (registrar,
  fechar, para onde vai o que não é item).
- docs/LIMITATIONS.md — o que não é feito e por quê (decisão/limite aceito, não
  fila). Antes de implementar algo "óbvio", checar aqui: pode ser decisão.
- docs/HISTORY.md — backlog concluído, bugs corrigidos e a nota de
  git: só narrativa datada (o registro do dia, não leitura corrente), com as
  regras de escrita no topo do próprio arquivo.
- docs/DEBUG.md — manual operacional: o que pode travar a sessão gráfica,
  ferramentas de teste manual, verificação com janela, sondas `PYTERM_*` e
  armadilhas de implementação (GTK/cairo/Pango/parser). **Ler antes de rodar
  ferramenta com display**; armadilha nova entra aqui, não no HISTORY.
- docs/PORTABILITY.md — estudo do P30 (Linux/Windows/macOS): o que é
  plataforma hoje, bloqueios no código, rotas e custo; decisão pendente.
- docs/BENCHMARKS.md — benchmarks e medição e **o único lugar com número de
  vazão/desenho/parse/pegada**: a carga doom-fire (manchete), o `dmesg` real, a
  escada e as decomposições, a pegada (PSS do app e disco do stack gráfico), o
  protocolo de comparação e as armadilhas (inclui o governor). Os demais docs
  citam o fato e linkam; não repetem valor.
- README.md — visão para humano: como rodar, ferramentas, ambiente, o que
  funciona, limites, medição, licença.

Cada arquivo acima é indexado em uma linha (o que é, quando usar); o detalhe
mora nele, não aqui.

Regras da fila (registro, fechamento, para onde vai o que não é item) estão no
topo de docs/BACKLOG.md.

**Número de medição mora em um só lugar: docs/BENCHMARKS.md** (com data e
governor da CPU). Os outros docs citam o fato em uma frase e linkam — não
repetem valor. Repetir número em cinco arquivos só produz divergência: cada
re-medição virava uma caçada para achar as cópias. Exceções: o README.md mantém
a linha do doom-fire na tabela comparativa (é a manchete para humano, um par de
números), o HISTORY.md registra o número do dia em que fechou um item (registro
datado, nunca leitura corrente) e o AGENTS.md pode citar valor de exemplo ao
explicar uma sonda.

## Arquitetura

bzmux é um pacote (bzmux/, instalável: `bzmux` no PATH ou `python -m bzmux`);
nenhum arquivo solto na raiz. O código:

- run.sh — roda o app (teste rápido; escolhe o python)
- debug.sh — desenvolvimento: background, log, --kill/--status
- run-tests.sh — roda o lint e a bateria de testes
- bench.sh — escada do doom-fire (medição, precisa de display)
- install.sh — instalador (Linux)
- bzmux/__main__.py — python -m bzmux (chama cli.run)
- bzmux/__init__.py — fachada com import preguiçoso (bzmux.Term não puxa o Gtk)
- bzmux/palette.py — célula [char, fg, bg, flags], paleta xterm-256 (int e float),
  charset DEC
- bzmux/term.py — grade, cursor, parser VT; não conhece GTK
- bzmux/keys.py — keyval do X11 -> bytes do filho (dead keys, DECCKM)
- bzmux/kitty_kbd.py — protocolo de teclado do kitty (CSI ... u)
- bzmux/mouse.py — protocolo de mouse (SGR e o antigo) — puro
- bzmux/graphics.py — protocolo de imagens do kitty (APC G) — puro
- bzmux/gui.py — único import de Gtk/Gdk/GLib/Pango/PangoCairo/cairo
- bzmux/style.py — tokens de cor do cromo + CSS gerado + contraste (puro)
- bzmux/view.py — TermView: uma sessão (pty, cairo + Pango, eventos)
- bzmux/window.py — Workspace + BzmuxWindow (abas, lateral, atalhos globais)
- bzmux/checks.py — a bateria: asserts puros, sem display
- bzmux/selftest.py — runner sem dependências do --selftest
- bzmux/cli.py — argv e arranque (e o entry point do console script)
- bzmux/shortcut.py — atalho do sistema (.desktop + ícone); puro, antes do gi
- bzmux/state.py — geometria da janela entre execuções (JSON em XDG_STATE_HOME)
- bzmux/config.py — configuração (chave/valor do kitty); puro, merge c/ default
- bzmux/data/ — bzmux.svg (ícone) e bzmux.conf (opções default embarcadas)
- tests/ — runner pytest de bzmux/checks.py
- tools/xtest.py, tools/pixel.py — teste manual, exige X11
- tools/doomfire.py — carga de medição, não teste

O que sustenta essa divisão: o caminho do --selftest importa só palette, term
(que puxa graphics), kitty_kbd e mouse, e nenhum deles puxa gi/cairo — é isso
que deixa os checks rodarem sem display e sem GTK (keys fica de fora: usa as
constantes de keyval do Gdk). Cada aba tem o seu Term; a janela só orquestra,
sem estado de sessão.

Dentro das duas maiores: term.py tem feed (máquina de estados, com fast path de
texto e SGR truecolor em ground e o parser lento como fallback), put/chars,
csi_dispatch/sgr/set_mode e child_out (respostas ao filho, drenadas pelo host);
view.py tem spawn/on_pty (io_add_watch no master), on_resize (size-allocate →
Term.resize + TIOCSWINSZ + SIGWINCH), on_draw, on_key, mouse/seleção e
view_off; window.py tem Workspace (Gtk.Notebook + cartão da lateral) e
BzmuxWindow (Gtk.Stack + atalhos globais + dump/quit-after/SIGUSR1).

Célula é uma lista [char, fg, bg, flags]: fg/bg em índice xterm (0-255,
256=fg default, 257=bg default), flags bitmask (bold/underline/inverse). O
desenho agrupa células vizinhas de atributos iguais num run só e cada run vira
um Pango.Layout cacheado por (texto, negrito): agrupar trouxe o frame uniforme
de 1920 células para ~2 ms, e o Pango cobrou ~20% num frame de 1360 células com
37 cores (números em docs/HISTORY.md, P9).

Não objetivo: clonar o kitty/gtkterm ou derivar do núcleo C deles — nada daqui
vem de lá. Python puro não é limitação pendente: é a conclusão do experimento
(dá para fazer um terminal inteiro em Python, e ele é usado assim no dia a dia);
o teto de vazão é o preço aceito e se ataca em Python, não reescrevendo em C.

## Configuração

Chave/valor no formato do kitty (`#` comenta). O arquivo do usuário é
$XDG_CONFIG_HOME/bzmux/bzmux.conf (o -c ARQ troca) e é sempre mesclado sobre o
default embarcado em bzmux/data/bzmux.conf.

- Chaves, valores default e faixas válidas moram em bzmux/config.py (DEFAULTS).
  As que mais mudam o uso do dia a dia: font_size (em pontos, não px),
  scrollback e cursor_shape.
- Editar com o app aberto aplica na hora. Erro é por linha: na carga inicial o
  que validou vale (o toast mostra o primeiro erro), no reload nada muda.

## Convenções

- Textos, descrições e comentários concisos; podem ser em português.
- Nomes de arquivo e símbolos no código (funções, variáveis, classes, constantes)
  em inglês.
- Docstrings e comentários no código: no máximo uma linha.
- Dados com campos nomeados (NamedTuple/dataclass), não tuplas cruas: posição
  não diz o que é, nome diz.
- Formato pensado para agente, não precisa ser agradável para humano.
- Cor de interface só em bzmux/style.py (tokens + CSS gerado); nenhum hex solto
  no código. Cor de célula do terminal é palette.py — não misturar as duas.
- Não atualizar a documentação a cada iteração de código. Quando o usuário
  terminar uma iteração, mencionar discretamente que a doc está pendente; a
  decisão de sincronizar é dele.
- Evitar backticks.
- Estilo é do `ruff format` (line-length 88), não de alinhamento manual; o lint
  é `ruff check` com E, F, I, W. Não escolher hand-format em cima do formatter:
  `./run-tests.sh` falha se o arquivo não estiver formatado.

## Testes

- Poucos testes, nas partes mais importantes: parser, protocolos e tudo que já
  quebrou uma vez (regressão vale mais do que cobertura).
- Sem suíte exaustiva: nada de matriz de casos por combinação de parâmetros,
  nada de teste que só reescreve o código na forma de asserção, nada de perseguir
  cobertura.
- Um bug corrigido = um check, quando der; não uma bateria em volta dele.
- Áreas cobertas hoje: parser, SGR/EL/ED, alt-screen e scroll, charset e
  respostas (DA/CPR), CSI com intermediário, CLI, teclado do kitty, gráficos,
  reflow, histórico, mouse, seleção, paste, truecolor, contraste do estilo.
- Teste barato de rodar: um comando (./run-tests.sh), sem display. Os checks
  ficam em bzmux/checks.py e têm dois runners: o pytest e o
  python3 -m bzmux --selftest (sem dependências, útil para provar que o caminho
  dos testes não puxa gi). O que precisar de X11 fica como comando manual em
  Scripts e ferramentas, não vira infraestrutura.
- tools/doomfire.py — carga de medição, não teste: doom-fire em meio-bloco
  truecolor (fg e bg por célula, pior caso), sem dependência de X.
  python3 tools/doomfire.py --fps 0 --frames 1200 --stats-to ARQ imprime fps e
  MB/s na saída, então dá para comparar dois terminais na mesma grade. Por que,
  resultados e protocolo: docs/BENCHMARKS.md. As sondas de diagnóstico
  (`PYTERM_PROF/NODRAW/NOPARSE/GEOM/GEOMLOG/DIAG/SCROLLLOG/CONFLOG`) estão na
  tabela de docs/DEBUG.md; a escada com os números fica em docs/BENCHMARKS.md.
- tools/ é manual, não suíte: xtest.py e pixel.py precisam de display e são
  chamados à mão durante a verificação. O comando dos testes é ./run-tests.sh.
- Medição não é teste: os números vêm de execução real. O `bench.sh` só roda o
  protocolo e imprime o resultado; nenhum valor é guardado no código.

## Scripts e ferramentas

Uso, opções e o porquê de cada script estão no cabeçalho dele — ler antes de
rodar. Aqui só cabe qual usar.

- ./install.sh — instalador Linux: deps da distro, pipx, --selftest no fim.
- ./run.sh — roda o app aqui, em foreground; escolhe o python (venv do uv
  quando ele enxerga o gi, senão o do sistema).
- ./debug.sh — desenvolvimento: background com log, --kill/--status por PID
  file (nunca pkill -f bzmux, que mata o shell de quem chama).
- ./run-tests.sh — lint + selftest + pytest, sem display.
- ./bench.sh — escada do doom-fire; precisa de display e não guarda número.
- bzmux, python3 -m bzmux, uv run python -m bzmux — o app (opções: bzmux -h).
- uv run pytest -q, uv run ruff check ., uv run ruff format . — bateria e lint
  pelo venv do uv.

Teste manual e verificação com janela: docs/DEBUG.md.
