# bzmux

Terminal em Python puro: pty + parser VT + grade + desenho com cairo.
Experimento funcional que existe para medir o custo do caminho quente em Python
(não é produto). Roda shell, mc e vim; tem mouse com seleção/cópia, histórico
com wheel, reflow, truecolor, protocolo de teclado e de imagens do kitty,
bracketed paste, abas e workspaces. Este arquivo é convenção; o conteúdo
muda de lugar conforme o tipo (ver Documentação).

## Documentação

Divisão por tipo de conteúdo — cada fato mora em um só lugar, não duplicar.
Todos são escritos para leitura de agente; só o README.md é para humano.

- AGENTS.md (este) — convenções, arquitetura curta, scripts e ferramentas.
- TASK-bzmux.md — status, por onde retomar, objetivo, escopo, arquitetura
  detalhada, estado atual, medições, como testar, ambiente uv, licença.
- docs/BACKLOG.md — backlog pendente (P9 shaping, P10 fallback de fonte).
- docs/HISTORY.md — backlog concluído (P1–P8, P11, P12), bugs corrigidos,
  quirks (armadilhas que não devem ser redescobertas) e a nota de git.
- README.md — visão para humano: como rodar, ferramentas, ambiente, o que
  funciona, limites, medição, licença.

Ao fechar um item do backlog: mover de docs/BACKLOG.md para o fim de
"Backlog concluído" em docs/HISTORY.md, com o bug que apareceu no caminho e
como foi verificado. Bug corrigido fora de item de backlog entra na lista
numerada de bugs do HISTORY.md (e o quirk, se for armadilha de ambiente).

## Arquitetura

bzmux.py é só o ponto de entrada (chama core.cli.main). O código vive em core/:

    bzmux.py       ponto de entrada, só delega
    run.sh         abre/fecha o app por PID file
    run-tests.sh   roda a bateria de testes
    core/
      palette.py   célula [char, fg, bg, flags], paleta xterm-256, charset DEC
      term.py      grade, cursor, parser VT — não conhece GTK
      keys.py      keyval do X11 -> bytes do filho (dead keys, DECCKM)
      kitty_kbd.py protocolo de teclado do kitty (CSI ... u)
      mouse.py     protocolo de mouse (SGR e o antigo) — puro
      graphics.py  protocolo de imagens do kitty (APC G) — puro
      gui.py       único import de Gtk/Gdk/GLib/cairo
      view.py      TermView: uma sessão (pty, cairo, eventos)
      window.py    Workspace + BzmuxWindow (abas, lateral, atalhos globais)
      checks.py    a bateria: asserts puros, sem display
      selftest.py  runner sem dependências do --selftest
      cli.py       argv e arranque
    tests/         runner pytest de core/checks.py
    tools/         xtest.py, pixel.py — teste manual com X11

O que sustenta essa divisão: o caminho do --selftest importa só palette, term,
kitty_kbd e mouse, e nenhum deles puxa gi/cairo — é isso que deixa os checks
rodarem sem display e sem GTK (keys fica de fora: usa as constantes de keyval do
Gdk). Cada aba tem o seu Term; a janela só orquestra, sem estado de sessão.

## Convenções

- Textos, descrições e comentários concisos; podem ser em português.
- Nomes de arquivo e símbolos no código (funções, variáveis, classes, constantes)
  em inglês.
- Docstrings e comentários no código: no máximo uma linha.
- Formato pensado para agente, não precisa ser agradável para humano.
- Não atualizar a documentação a cada iteração de código. Quando o usuário
  terminar uma iteração, mencionar discretamente que a doc está pendente; a
  decisão de sincronizar é dele.
- Evitar backticks.

## Testes

- Poucos testes, nas partes mais importantes: parser, protocolos e tudo que já
  quebrou uma vez (regressão vale mais do que cobertura).
- Sem suíte exaustiva: nada de matriz de casos por combinação de parâmetros,
  nada de teste que só reescreve o código na forma de asserção, nada de perseguir
  cobertura.
- Um bug corrigido = um check, quando der; não uma bateria em volta dele.
- Teste barato de rodar: um comando (./run-tests.sh), sem display. Os checks
  ficam em core/checks.py e têm dois runners: o pytest e o
  python3 bzmux.py --selftest (sem dependências, útil para provar que o caminho
  dos testes não puxa gi). O que precisar de X11 fica documentado como comando
  manual no TASK-bzmux.md, não vira infraestrutura.
- tools/ é manual, não suíte: xtest.py e pixel.py precisam de display e são
  chamados à mão durante a verificação. O comando dos testes é ./run-tests.sh.
- Medição não é teste: os números do TASK-bzmux.md vêm de execução real e não
  viram benchmark automatizado sem necessidade.

## Scripts e ferramentas

App:

- python3 bzmux.py — o terminal. Opções: --cmd COMANDO, --quit-after SEG,
  --dump-to ARQUIVO, --selftest (roda os checks e sai), -h/--help (ajuda sem
  abrir janela; opção inválida também sai, com exit 2).
- ./run.sh — abre/fecha o app. Modos: (nada) background com log em
  /tmp/bzmux.log, --fg foreground, --kill, --status, --cmd, --quit-after,
  --dump-to. Controla por PID file (/tmp/bzmux.pid) e só mata o processo que ele
  mesmo subiu: use isto em vez de pkill -f bzmux.py, que casa com a linha de
  comando de quem chama e mata o shell errado.
- ./run-tests.sh — selftest (sem dependências) e depois pytest; argumentos
  extras vão para o pytest (-k, -x). --selftest-only pula o pytest. Sai != 0 se
  algo falhar. Não precisa de display.
- ./run.sh escolhe o interpretador: .venv/bin/python quando ele importa gi,
  senão o python3 do sistema (com aviso). O venv precisa ser criado com
  uv venv --system-site-packages, porque o PyGObject vem da distro e o uv sync
  não passa essa flag.
- uv run pytest -q — só a parte pytest; uv sync instala o ambiente (pytest).
- uv run python bzmux.py — o app direto pelo uv (mesmo interpretador do venv).

Teste manual, com display e python3-xlib (em tools/):

- tools/xtest.py SUBCOMANDO — id, geometry, activate, move, click, dclick,
  wheel, drag, key, type. Coordenadas relativas à janela; a grade começa em
  y≈58 (barra de abas + lateral). type só aceita texto simples.
- tools/pixel.py — cor de pixel num PNG: pontos X,Y, --scan X, --row Y. Serve
  para conferir desenho em captura (import -window).

O app roda no venv do uv, que enxerga o PyGObject do sistema via
--system-site-packages.
