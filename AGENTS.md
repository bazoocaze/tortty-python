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
- docs/BACKLOG.md — backlog pendente (vazio hoje).
- docs/LIMITATIONS.md — o que não é feito e por quê (decisão/limite aceito, não
  fila). Antes de implementar algo "óbvio", checar aqui: pode ser decisão.
- docs/HISTORY.md — backlog concluído (P1–P18), bugs corrigidos,
  quirks (armadilhas que não devem ser redescobertas) e a nota de git.
- docs/BENCHMARKS.md — benchmarks e medição e **o único lugar com número de
  vazão/desenho/parse/pegada**: a carga doom-fire (manchete), o `dmesg` real, a
  escada e as decomposições, a pegada (PSS do app e disco do stack gráfico), o
  protocolo de comparação e as armadilhas (inclui o governor). Os demais docs
  citam o fato e linkam; não repetem valor.
- README.md — visão para humano: como rodar, ferramentas, ambiente, o que
  funciona, limites, medição, licença.

Registrar item no backlog é só registrar: a investigação (ler código, medir,
reproduzir) acontece quando o item for **executado**, não quando ele é anotado.
Na anotação vai o que o pedido já trouxe — sintoma, e o que for de graça no
caminho — e para por aí; nada de diagnóstico completo, causa raiz ou plano
fechado antes da hora. Vale para registro novo: item já registrado não se
reescreve para caber nesta regra.

Ao fechar um item do backlog: mover de docs/BACKLOG.md para o fim de
"Backlog concluído" em docs/HISTORY.md, com o bug que apareceu no caminho e
como foi verificado. Bug corrigido fora de item de backlog entra na lista
numerada de bugs do HISTORY.md (e o quirk, se for armadilha de ambiente).
Decisão de NÃO fazer algo vai para docs/LIMITATIONS.md, não para o backlog; se o
limite deixar de existir, sai de lá e vira item concluído no HISTORY.md.
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

    run.sh         roda o app (teste rápido; escolhe o python)
    debug.sh       desenvolvimento: background, log, --kill/--status
    run-tests.sh   roda o lint e a bateria de testes
    bench.sh       escada do doom-fire (medição, precisa de display)
    bzmux/
      __main__.py  `python -m bzmux` (chama cli.run)
      __init__.py  fachada com import preguiçoso (bzmux.Term não puxa o Gtk)
      palette.py   célula [char, fg, bg, flags], paleta xterm-256 (int e float), charset DEC
      term.py      grade, cursor, parser VT — não conhece GTK
      keys.py      keyval do X11 -> bytes do filho (dead keys, DECCKM)
      kitty_kbd.py protocolo de teclado do kitty (CSI ... u)
      mouse.py     protocolo de mouse (SGR e o antigo) — puro
      graphics.py  protocolo de imagens do kitty (APC G) — puro
      gui.py       único import de Gtk/Gdk/GLib/Pango/PangoCairo/cairo
      style.py     tokens de cor do cromo + CSS gerado + contraste (puro)
      view.py      TermView: uma sessão (pty, cairo + Pango, eventos)
      window.py    Workspace + BzmuxWindow (abas, lateral, atalhos globais)
      checks.py    a bateria: asserts puros, sem display
      selftest.py  runner sem dependências do --selftest
      cli.py       argv e arranque (e o entry point do console script)
      shortcut.py  atalho do sistema (.desktop + ícone) — puro, roda antes do gi
      state.py     geometria da janela entre execuções (JSON em XDG_STATE_HOME)
      config.py    configuração (chave/valor do kitty) — puro; merge com o default
      data/        bzmux.svg (ícone) e bzmux.conf (opções default embarcadas)
    tests/         runner pytest de bzmux/checks.py
    tools/         xtest.py, pixel.py — teste manual, exige X11 (só eles);
                   doomfire.py — carga de medição

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
  resultados e protocolo: docs/BENCHMARKS.md. Com PYTERM_PROF=1 no ambiente o
  app imprime, ao fechar a sessão, o custo de parse (on_pty) e de desenho
  (on_draw) — é o que decompõe a vazão. Com PYTERM_SCROLLLOG=ARQ um chunk que
  rola mais de meia tela é gravado com jump/top/bottom/alt-screen e os bytes
  crus (sonda do P19). PYTERM_GEOM=980x640 trava o tamanho da janela (sem isso
  o WM às vezes abre 80x24 e o número muda; é o que o protocolo de comparação
  exige). Com PYTERM_DIAG=1 no primeiro draw ele imprime avanço da fonte, célula
  da grade, resolução e colunas: é o par que tem que bater (bug 13 do HISTORY —
  grade a 130 dpi e desenho a 96). As duas sondas de custo isolam as etapas: PYTERM_NODRAW=1 desliga o desenho (sobra
  pty -> grade) e PYTERM_NOPARSE=1 lê o pty e descarta (isola o IO); com
  PYTERM_PROF=1 o resumo ainda traz bytes lidos e eagain. Com
  PYTERM_GEOMLOG=1 cada configure imprime posição do cliente, da moldura e os
  frame extents — foi o que mostrou a janela descendo 30 px por execução (o
  título contado duas vezes). Com PYTERM_CONFLOG=1 cada reload de configuração
  aprovado imprime os valores no stderr (prova que o monitor disparou sem
  depender de olhar o toast). A escada com os números fica em
  docs/BENCHMARKS.md.
- tools/ é manual, não suíte: xtest.py e pixel.py precisam de display e são
  chamados à mão durante a verificação. O comando dos testes é ./run-tests.sh.
- Medição não é teste: os números vêm de execução real. O `bench.sh` só roda o
  protocolo e imprime o resultado; nenhum valor é guardado no código.

## Scripts e ferramentas

App:

- ./install.sh — instala na máquina: confere/instala as dependências da distro
  (apt/dnf/pacman/zypper), acha o python3 que enxerga gi+cairo, garante o pipx e
  roda `pipx install --force --system-site-packages --python PY SPEC`; no fim
  roda o `--selftest`. SPEC é a árvore local quando o script está num clone e
  `git+ssh://git@github.com/bazoocaze/pybzmux.git` quando vem por pipe. Modos:
  --dry-run, --no-deps, --no-shortcut, --uninstall, -h. Só Linux. No fim cria o
  atalho do sistema chamando `bzmux --install-shortcut` (e o remove no
  --uninstall, antes do pipx, senão o comando já não existe). Usa o pipx do
  sistema quando existe e cai no `uvx --from pipx pipx` quando não — nesse caso
  o `--python` é obrigatório, porque o interpretador do uv não vê o gi da
  distro. Hoje o pipe exige `gh api`
  porque o repositório é privado; `curl | bash` só passa a valer quando ele
  abrir.
- bzmux — o terminal (console script instalado, `python3 -m bzmux` na árvore,
  ou ./run.sh). Opções: --cmd COMANDO, -c/--config ARQUIVO, --quit-after SEG,
  --dump-to ARQUIVO, --selftest (roda os checks e sai), --install-shortcut /
  --remove-shortcut (atalho no menu: .desktop + ícone em XDG_DATA_HOME), -h/--help
  (ajuda sem abrir janela; opção inválida também sai, com exit 2). Sem PyGObject
  no ambiente, a mensagem diz o que instalar em vez de estourar traceback.
- Configuração (P33): `chave valor` no formato do kitty, `#` comenta. O arquivo
do usuário é `$XDG_CONFIG_HOME/bzmux/bzmux.conf` (o `-c` troca o caminho) e é
**sempre mesclado** sobre `bzmux/data/bzmux.conf`, que é o default embarcado.
Opções (P33/P34): `shell` (`/bin/bash`; o `--cmd` vence), `font_family`
(`Monospace`), `font_size` (`12`, em **pontos**, não px), `cursor_shape`
(`block`/`beam`/`underline`), `cursor_blink` (`off`), `scrollback` (`1000`),
`window_padding_width` (`0`, px), `bell` (`none`/`visual`/`audible`) e
`copy_on_select` (`off`). O que é quente (fonte, padding, cursor) aplica em
todas as abas abertas no reload; `shell` só vale na próxima aba. `CSI 6 q`
(DECSCUSR) do app vence a config do cursor enquanto durar. Editar o arquivo com o app aberto aplica na hora
(`Gio.FileMonitor` com debounce de 250 ms). Erro é por linha: na **carga
inicial** o que validou vale e a chave inválida fica no padrão, com um toast de
10 s mostrando o **primeiro** erro (`(+N)` para os outros); no **reload**
qualquer erro mantém a configuração anterior (nada muda) e o toast lista os
erros.
`Ctrl+Shift+F2` abre o arquivo do usuário no `vim`, em aba nova. Com
`PYTERM_CONFLOG=1` cada reload aprovado imprime os valores no stderr.
- pipx install --system-site-packages git+ssh://git@github.com/bazoocaze/pybzmux.git
  — instala na máquina (Linux; build feito do clone pelo hatchling, o comando
  bzmux fica no PATH). Os detalhes e as armadilhas ficam em docs/BACKLOG.md
  (P31) e no HISTORY.md.
- ./run.sh — roda o app para testar rápido: passa os argumentos (--cmd,
  --quit-after, --dump-to, -h) para o app, em foreground, e sai com o
  código dele. Escolhe o interpretador: .venv/bin/python quando ele importa gi,
  senão o python3 do sistema (com aviso). O venv precisa ser criado com
  uv venv --system-site-packages, porque o PyGObject vem da distro e o uv sync
  não passa essa flag. Exporta PYTHONPATH com a raiz do repositório (é `-m
  bzmux`), sem mudar de diretório: o shell aberto herda o cwd de quem chamou.
- ./debug.sh — o script do desenvolvimento: abre/fecha o app sem deixar
  instância órfã. Modos: (nada) background com log em /tmp/bzmux.log, --fg
  foreground, --kill, --status; o resto dos argumentos vai para o app. Sobe pelo
  run.sh (mesmo interpretador) e controla por PID file (/tmp/bzmux.pid),
  matando só o processo que ele mesmo subiu: use isto em vez de
  pkill -f bzmux, que casa com a linha de comando de quem chama e mata o
  shell errado. Reconhece as duas formas do processo (`python -m bzmux` e o
  script do PATH).
- ./bench.sh — roda a escada do doom-fire (full, `NODRAW`,
  `NOPARSE+NODRAW` e o gerador isolado), espera cada etapa terminar e imprime
  fps, MB/s, bytes/frame, custo de `draw`/`pty` e a frequência da CPU por
  etapa. Com o padrão (300 frames) leva ~10 s; `--frames 1200` é o protocolo de
  referência. Precisa de display e não guarda número: os valores ficam em
  docs/BENCHMARKS.md. Fecha cada app com SIGTERM (o handler faz dump e imprime
  o prof).
- ./run-tests.sh — ruff (check + format --check), selftest (sem dependências)
  e depois pytest; argumentos extras vão para o pytest (-k, -x).
  --selftest-only pula o pytest, --no-lint pula o ruff. Sai != 0 se algo
  falhar. Não precisa de display.
- uv run pytest -q — só a parte pytest; uv sync instala o ambiente (pytest +
  ruff).
- uv run ruff check . / uv run ruff format . — lint (E, F, I, W; config em
  pyproject.toml, line-length 88) e formatação. O run-tests só *verifica* o
  formato; formatar é decisão de quem mexe, não do fluxo de teste.
- uv run python -m bzmux — o app direto pelo uv (mesmo interpretador do venv).

Teste manual, com display e python3-xlib (em tools/):

- tools/xtest.py SUBCOMANDO — id, geometry, activate, move, click, dclick,
  wheel, drag, key, type. Coordenadas relativas à janela; a grade começa em
  y≈58 (barra de abas + lateral). type só aceita texto simples.
- tools/pixel.py — cor de pixel num PNG: pontos X,Y, --scan X, --row Y. Serve
  para conferir desenho em captura (import -window).

Fluxo de verificação com janela: ./debug.sh; ferramenta; kill -USR1 $(cat
/tmp/bzmux.pid) e ler /tmp/bzmux-dump.txt (cabeçalhos de workspace e de aba só
quando há mais de um). Exemplo:

    python3 tools/xtest.py key ctrl+shift+n     # workspace novo
    python3 tools/xtest.py dclick 60 28         # duplo clique no cartão 1
    python3 tools/xtest.py type 'echo ok'       # texto com símbolos
    kill -USR1 $(cat /tmp/bzmux.pid)            # dumpar a grade

O app roda no venv do uv, que enxerga o PyGObject do sistema via
--system-site-packages.
