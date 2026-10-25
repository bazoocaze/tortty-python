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

### P15 — Tela do `pi` estabiliza bagunçada depois de ~10 s — não iniciado

Relato: abrir o `pi` no bzmux e esperar ~10 s até ele terminar de subir; a tela
que fica não está coerente. No kitty o mesmo app termina certo. O `pi` mexe no
título da janela, então provavelmente é o P14 por trás.

Medido (o P14 é real e não é sutil): um `while` que alterna
`printf '\033]2;curto\007'` com um título de 60 chars muda a grade entre
**73 e 121 colunas** — 48 colunas de diferença, com SIGWINCH e
`Term.resize` a cada troca. Qualquer app que escreva título de tamanho variável
redimensiona o terminal embaixo dele mesmo.

Por que isso termina bagunçado:

- A cada resize o app concorda com um tamanho novo e redesenha; se ele muda o
  título de novo no meio do redesenho, redesenha para um tamanho que já não
  vale. Enquanto as trocas acontecem, a tela é um recorte/frame velho.
- Em alt-screen não há reflow: `_resize_crop` recorta as colunas do que estava
  na tela. Um frame que o app não repinta fica cortado, e sobra de linha
  quebrada aparece no rodapé (visto num alt-screen estático: texto vazando na
  última linha).
- Não há output síncrono (CSI `?2026` é ignorado como modo privado
  desconhecido): o frame não é atômico, então um resize pode cair no meio de um
  frame e deixar linha rasgada até o próximo repaint completo.

Ordem de ataque: fechar o **P14** primeiro (largura da lateral fixa ⇒ título
não redimensiona nada ⇒ sem SIGWINCH). Só depois medir de novo: se o `pi` ainda
terminar torto, a causa é nossa (recorte do alt-screen ou falta de `?2026`), não
o resize. Sem separar as duas, o P15 vira caça ao fantasma.

Protocolo de comparação com o kitty (mesmo app, mesmo tamanho):

1. `./debug.sh --cmd 'pi'`, e `kill -USR1 $(cat /tmp/bzmux.pid)` a cada ~1 s
   durante a subida: a linha `=== viewport CxR ===` mostra quantas vezes a grade
   mudou de largura. Esse número é a medida do problema.
2. Mesma coisa no kitty (`kitty --override initial_window_columns=C`, ou
   redimensionar para casar cols/rows) e captura com `import -window`.
3. Terminada a subida, `--dump-to` do bzmux contra o texto do kitty: o dump é a
   grade real, então dá para ver se é sobra de célula antiga, corte de coluna ou
   cursor fora de lugar.

Verificação: com P14 feito, `cols` constante nos dumps durante a subida do `pi`
e tela coerente no fim, igual ao kitty.

Armadilhas:

- Não "resolver" deixando de atualizar o rótulo da aba: o título é informação
  legítima; o que não pode é ele mexer no layout.
- `?2026` sem suporte não gera erro; se for implementar, é preciso lembrar que
  ele pode vir junto com outras sequências no mesmo pacote de bytes.
- Ao implementar `?2026`, nada de parar o parser: o modo só acumula e desenha
  no fim (ou no timeout), senão uma app que nunca manda o "fim" congela a tela.
- O pi também costuma usar o título para progresso/spinner: oscilação rápida,
  não uma troca só.
