# bzmux — backlog (pendente)

Só o que está em aberto. Concluído: [HISTORY.md](HISTORY.md). Status, escopo
e por onde retomar: [../TASK-bzmux.md](../TASK-bzmux.md).

Ordem não implica prioridade.

### P9 — Ligaduras (shaping) — não iniciado

O desenho usa `cairo.show_text` (API toy): não há shaping, então `->`, `!=`,
`=>` saem como dois glifos mesmo em fonte com ligadura. Fix: `PangoCairo` para
layout por run (com cache de `Pango.Layout`), o que **muda o custo do frame** —
que é justamente a medida do experimento, então tem que medir antes/depois.

### P10 — Fallback de fonte (emoji/CJK) — não iniciado

Caractere fora da fonte vira caixa de glifo ausente. O Pango resolve isso de
graça (fontconfig faz o fallback), ou seja: **P9 e P10 caem juntos** na mesma
migração; estão separados aqui só para o registro do que cada um entrega.

Teste: `printf '\u4e2d\u6587 \U0001F600'` e comparação de screenshot.

### P13 — Sistema de estilo da interface (lateral preta, selecionado verde) — não iniciado

Pedido: a lateral dos workspaces com fundo preto, o workspace selecionado numa
cor de fundo escura (verde pode), e o texto bem claro em cima — contraste alto.
Hoje a lateral e o cartão herdam o tema do sistema (e é o tema que pinta o
selecionado de verde claro), então o resultado depende da máquina.

Junto com isso, formalizar o estilo: **toda cor da interface vem de uma tabela
de tokens**, e o CSS é gerado a partir dela. Regras:

- Um lugar só para as cores da interface: `core/style.py`, puro (str e ints,
  sem Gtk), com os tokens e uma função que monta o CSS. Quem aplica é
  `window.py`/`gui.py` (`Gtk.CssProvider` +
  `Gtk.StyleContext.add_provider_for_screen` na prioridade de aplicação), uma
  vez, no arranque.
- **Nenhum hex solto no código.** Hoje há um: `#8a8a8a` no `_card_info` de
  `window.py`. Ele vira token (`CARD_INFO_FG`) como os outros.
- Tokens desta rodada: `SIDEBAR_BG` (preto), `CARD_FG` (claro),
  `CARD_INFO_FG` (claro/apagado), `CARD_SEL_BG` (verde escuro),
  `CARD_SEL_FG` (mais claro que o normal, é o que marca o workspace ativo).
  Abas entram depois, com os mesmos nomes trocando o prefixo.
- A paleta do terminal (`core/palette.py`, xterm-256 + truecolor) é outra
  coisa e não se mistura com esta: uma é célula, a outra é cromo da janela.
- Contraste conferível sem display: sendo `style.py` puro, um check calcula a
  luminância relativa e exige >= 4.5:1 entre texto e fundo, no cartão normal e
  no selecionado. Sem isso, "bem claro" é opinião.

Armadilhas:

- **Seleção deixa de ser o realce do tema.** Com fundo próprio, `:selected`
  tem que ser pintado por nós; se o CSS não cobrir, o tema volta a mandar.
- **Três retângulos independentes**: a `Gtk.ListBox`, cada `Gtk.ListBoxRow`
  (`:hover` incluso) e o `Gtk.EventBox` do cartão — cada um tem janela própria
  e pinta o seu pedaço. Cobrir só a `ListBox` deixa moldura e linha coloridas.
- **Widget precisa de alvo**: `set_name` (`#sidebar`) ou classe nos cartões;
  casar por tipo perde para o seletor do tema.
- **Escopo é a tela**, não a janela: `add_provider_for_screen` vale para todas
  as janelas do processo (aqui só há uma).
- **Rótulo de aba** é `Gtk.EventBox` com `Gtk.Label` e é recriado em
  `set_tab_label_text` quando o OSC chega — estilo por classe sobrevive, estilo
  por widget não.

Verificação: `./debug.sh` com 2+ workspaces e captura com `import -window`;
`python3 tools/pixel.py` amostra a lateral (preto), o cartão ativo (verde
escuro do token) e o texto (claro); mais o check puro de contraste, que roda no
`--selftest`.
