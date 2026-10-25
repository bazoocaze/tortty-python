# bzmux

Terminal em Python puro: pty + parser VT + grade + desenho com cairo + Pango.
Experimento funcional que existe para medir o custo do caminho quente em Python
(não é produto). Roda shell, mc e vim; tem mouse com seleção/cópia, histórico
com wheel, reflow, truecolor, protocolo de teclado e de imagens do kitty,
bracketed paste, abas e workspaces. Este arquivo é convenção; o conteúdo
muda de lugar conforme o tipo (ver Documentação).

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
- docs/DOOM-FIRE.md — a carga de medição: por que ela existe, como rodar, o
  número (bzmux 0,5 MB/s contra 15,8 MB/s do kitty, 31x) e o protocolo de
  comparação.
- README.md — visão para humano: como rodar, ferramentas, ambiente, o que
  funciona, limites, medição, licença.

Ao fechar um item do backlog: mover de docs/BACKLOG.md para o fim de
"Backlog concluído" em docs/HISTORY.md, com o bug que apareceu no caminho e
como foi verificado. Bug corrigido fora de item de backlog entra na lista
numerada de bugs do HISTORY.md (e o quirk, se for armadilha de ambiente).
Decisão de NÃO fazer algo vai para docs/LIMITATIONS.md, não para o backlog; se o
limite deixar de existir, sai de lá e vira item concluído no HISTORY.md.

## Arquitetura

bzmux.py é só o ponto de entrada (chama core.cli.main). O código vive em core/:

    bzmux.py       ponto de entrada, só delega
    run.sh         roda o app (teste rápido; escolhe o python)
    debug.sh       desenvolvimento: background, log, --kill/--status
    run-tests.sh   roda a bateria de testes
    core/
      __init__.py  fachada com import preguiçoso (core.Term não puxa o Gtk)
      palette.py   célula [char, fg, bg, flags], paleta xterm-256, charset DEC
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
      cli.py       argv e arranque
    tests/         runner pytest de core/checks.py
    tools/         xtest.py, pixel.py — teste manual com X11;
                   doomfire.py — carga de medição

O que sustenta essa divisão: o caminho do --selftest importa só palette, term
(que puxa graphics), kitty_kbd e mouse, e nenhum deles puxa gi/cairo — é isso
que deixa os checks rodarem sem display e sem GTK (keys fica de fora: usa as
constantes de keyval do Gdk). Cada aba tem o seu Term; a janela só orquestra,
sem estado de sessão.

Dentro das duas maiores: term.py tem feed (máquina de estados), put/chars,
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

Não objetivo: virar o app. A parte C/GTK de referência ficou no repositório do
experimento do kitty (ver README.md); nada daqui é compartilhado com ela.

## Convenções

- Textos, descrições e comentários concisos; podem ser em português.
- Nomes de arquivo e símbolos no código (funções, variáveis, classes, constantes)
  em inglês.
- Docstrings e comentários no código: no máximo uma linha.
- Formato pensado para agente, não precisa ser agradável para humano.
- Cor de interface só em core/style.py (tokens + CSS gerado); nenhum hex solto
  no código. Cor de célula do terminal é palette.py — não misturar as duas.
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
- Áreas cobertas hoje: parser, SGR/EL/ED, alt-screen e scroll, charset e
  respostas (DA/CPR), CSI com intermediário, CLI, teclado do kitty, gráficos,
  reflow, histórico, mouse, seleção, paste, truecolor, contraste do estilo.
- Teste barato de rodar: um comando (./run-tests.sh), sem display. Os checks
  ficam em core/checks.py e têm dois runners: o pytest e o
  python3 bzmux.py --selftest (sem dependências, útil para provar que o caminho
  dos testes não puxa gi). O que precisar de X11 fica como comando manual em
  Scripts e ferramentas, não vira infraestrutura.
- tools/doomfire.py — carga de medição, não teste: doom-fire em meio-bloco
  truecolor (fg e bg por célula, pior caso), sem dependência de X.
  python3 tools/doomfire.py --fps 0 --frames 1200 --stats-to ARQ imprime fps e
  MB/s na saída, então dá para comparar dois terminais na mesma grade. Por que,
  resultados e protocolo: docs/DOOM-FIRE.md. Com PYTERM_PROF=1 no ambiente o
  app imprime, ao fechar a sessão, o custo de parse (on_pty) e de desenho
  (on_draw) — é o que decompõe a vazão.
- tools/ é manual, não suíte: xtest.py e pixel.py precisam de display e são
  chamados à mão durante a verificação. O comando dos testes é ./run-tests.sh.
- Medição não é teste: os números do README.md vêm de execução real e não
  viram benchmark automatizado sem necessidade.

## Scripts e ferramentas

App:

- python3 bzmux.py — o terminal. Opções: --cmd COMANDO, --quit-after SEG,
  --dump-to ARQUIVO, --selftest (roda os checks e sai), -h/--help (ajuda sem
  abrir janela; opção inválida também sai, com exit 2).
- ./run.sh — roda o app para testar rápido: passa os argumentos (--cmd,
  --quit-after, --dump-to, -h) para o bzmux.py, em foreground, e sai com o
  código dele. Escolhe o interpretador: .venv/bin/python quando ele importa gi,
  senão o python3 do sistema (com aviso). O venv precisa ser criado com
  uv venv --system-site-packages, porque o PyGObject vem da distro e o uv sync
  não passa essa flag.
- ./debug.sh — o script do desenvolvimento: abre/fecha o app sem deixar
  instância órfã. Modos: (nada) background com log em /tmp/bzmux.log, --fg
  foreground, --kill, --status; o resto dos argumentos vai para o app. Sobe pelo
  run.sh (mesmo interpretador) e controla por PID file (/tmp/bzmux.pid),
  matando só o processo que ele mesmo subiu: use isto em vez de
  pkill -f bzmux.py, que casa com a linha de comando de quem chama e mata o
  shell errado.
- ./run-tests.sh — selftest (sem dependências) e depois pytest; argumentos
  extras vão para o pytest (-k, -x). --selftest-only pula o pytest. Sai != 0 se
  algo falhar. Não precisa de display.
- uv run pytest -q — só a parte pytest; uv sync instala o ambiente (pytest).
- uv run python bzmux.py — o app direto pelo uv (mesmo interpretador do venv).

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
