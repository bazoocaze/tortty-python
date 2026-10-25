# bzmux

Terminal em Python puro: pty + parser VT + grade + desenho com cairo.
Experimento funcional que existe para medir o custo do caminho quente em Python
(não é produto). Roda shell, mc e vim; tem mouse com seleção/cópia, histórico
com wheel, reflow, truecolor, protocolo de teclado e de imagens do kitty,
bracketed paste, abas e workspaces. Escopo, medições, bugs e backlog ficam em
TASK-bzmux.md.

## Arquitetura

bzmux.py é só o ponto de entrada (chama core.cli.main). O código vive em core/:

    bzmux.py       ponto de entrada, só delega
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
      selftest.py  checks sem display
      cli.py       argv e arranque
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
- Teste barato de rodar: um comando (uv run pytest -q), sem display. Os checks
  ficam em core/checks.py e têm dois runners: o pytest e o
  python3 bzmux.py --selftest (sem dependências, útil para provar que o caminho
  dos testes não puxa gi). O que precisar de X11 fica documentado como comando
  manual no TASK-bzmux.md, não vira infraestrutura.
- tools/ é manual, não suíte: xtest.py e pixel.py precisam de display e são
  chamados à mão durante a verificação.
- Medição não é teste: os números do TASK-bzmux.md vêm de execução real e não
  viram benchmark automatizado sem necessidade.
