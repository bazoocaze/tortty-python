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

### P14 — Largura da lateral não fica fixa — não iniciado

`SIDEBAR_W` é 170, mas medido numa captura: a lateral abriu com **234 px**,
e o notebook começou em x=234 (primeira coluna não preta da barra de abas).
O cartão mostrava `user@host: pybzmux (1 aba)` na segunda linha.

`set_size_request` é mínimo, não largura: `Gtk.Label` sem `ellipsize` publica a
largura do texto como mínimo, e a `ListBox` cresce com o conteúdo. Acontece
com título de aba longo (OSC de `vim`/`mc`), cwd comprido e nome de workspace
renomeado — por isso parece dinâmico em alguns fluxos.

Efeito colateral pior que o estético: quando o título muda, a lateral muda de
largura, rouba colunas do terminal e dispara o reflow do P3 em todas as abas do
workspace — a grade "pula" justo quando o app escreve título.

Fix: `ellipsize(END)` nos dois rótulos do cartão (`name_label` e `info_label`),
que zera o mínimo deles e deixa o `SIDEBAR_W` mandar; o texto completo vai para
tooltip do cartão. Hoje `window.py` não importa `Pango` — ele entra em `gui.py`,
que é o único ponto de import de Gtk/Gdk.

Armadilhas:

- `ellipsize` sem largura conhecida não trunca: o `set_size_request` tem que
  continuar lá, é ele que dá o limite.
- O `info_label` estoura primeiro (cwd + contagem de abas) — é o caso de teste.
- Se o corte for por `max_width_chars`, o limite passa a depender da fonte (o
  `font_size` é configurável na janela); melhor depender da largura em pixels.
- Texto truncado sem tooltip esconde informação (nome da aba ativa).

Verificação: `./debug.sh` com 2+ workspaces, título longo por OSC
(`printf '\033]2;<60 chars>\007'`) e workspace renomeado com nome longo; a
fronteira lateral/terminal não pode sair de x=170 — medir por pixel na captura
(coluna onde começa a barra de abas, com o mouse fora da lateral, senão o
`:hover` escurece o fundo e engana a amostra) e conferir no dump que `cols` do
Term não mudou.
