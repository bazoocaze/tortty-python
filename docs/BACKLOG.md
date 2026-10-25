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

### P13 — Lateral dos workspaces com fundo preto — não iniciado

Hoje a lateral (`Gtk.ListBox` em `window.py`, `SIDEBAR_W`) usa o tema do
sistema, então numa sessão de terminal preto ela aparece clara. Pedido: fundo
preto, coerente com a grade — vale para a barra de abas também se ficar melhor
decidir os dois juntos.

Não há nada de estilo no projeto (nenhum `CssProvider`), então é o primeiro:
`Gtk.CssProvider` + `Gtk.StyleContext.add_provider_for_screen` com a prioridade
de aplicação. O CSS tem que atingir o que o tema pinta por baixo, senão sobra
moldura clara: a `Gtk.ListBox`, cada `Gtk.ListBoxRow` (inclusive `:hover` e
`:selected`) e o `Gtk.EventBox` do cartão — o `EventBox` do cartão e o do
rótulo da aba já têm janela própria, então cada um pinta o seu retângulo.

Armadilhas:

- **Seleção some no preto.** O tema marca o workspace ativo com fundo; com
  tudo preto essa é a única marca. Precisa de outro sinal (barra à esquerda,
  texto mais claro, negrito) — senão não se vê onde se está.
- **Cor do texto é do tema.** `name_label`/`info_label` usam markup; num tema
  claro o texto escuro fica ilegível sobre preto. O CSS tem que fixar `color`.
- **Especificidade.** O seletor de tema pode ganhar do nosso; usar `#sidebar`
  (via `set_name`) ou classe nos cartões em vez de casar por tipo.
- **Escopo é a tela toda**, não a janela: `add_provider_for_screen` afeta todas
  as janelas do processo (aqui só há uma, mas é bom saber).

Verificação: `./debug.sh` com 2+ workspaces, captura com `import -window` e
`python3 tools/pixel.py shot.png X,Y` num ponto da lateral — tem que dar
`(0,0,0)`, não a cor do tema; e conferir o cartão ativo legível.
