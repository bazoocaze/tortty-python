# bzmux — backlog (pendente)

P19 — Interagindo com o `pi`, a cada algumas etapas do turno a tela reescreve
várias telas de uma vez. **Investigação aberta** (2026-10-25).

Já descartado, com dados: parser/grade. Três turnos reais do `pi` capturados num
pty próprio (respondendo as mesmas queries do bzmux) e replayados em `Term` e
`pyte`: rolagens iguais (32×32, 79×79) e tela final idêntica; o TUI do `pi` não
usa DECSTBM (`CSI r`), IL/DL (`CSI L/M`), SU/SD (`CSI S/T`) nem autowrap-off
(`?7l`) — só `CSI nA/nB/nG`, `CSI 2K`, `CSI 1G`, sync output (`?2026`) e
hyperlinks OSC 8. Também já corrigido o que mascarava sintoma parecido: tique de
1 Hz do `pi` (bug 14) e desenho em resolução errada (bug 13).

Falta o caso real (transcrição longa). Sonda pronta: `PYTERM_SCROLLLOG=ARQ
./run.sh` grava cada chunk que rola mais de meia tela com `jump=N`, `top/bottom`
da região, alt-screen e os 600 primeiros bytes crus. Ler o log e isolar a
sequência; se o log sair vazio, logar `on_resize` (reflow no meio do turno passa
a ser o suspeito). Hipóteses na fila: (a) reimpressão da transcrição inteira
quando um widget do rodapé muda de altura (o observer do `pi-blackhole` escreve
"Observational memory…" no meio da conversa); (b) `CSI 2J` + reimpressão; (c)
resize/reflow entrando no meio do turno.

P26 — Desenho: `cr.show_glyphs` com glifos pré-computados. **Experimento, não
compromisso.** É o único caminho que ataca de verdade o custo de emissão:
2,43 → 0,76 µs (-69%, ~24% do desenho). O preço é sair do Pango: sem fallback
de fonte, sem attrs de negrito e sem a resolução do widget (o app usa 130 dpi).
Medido: 440–958 bytes diferentes de 56.000 numa célula ~0,8% dos bytes) e
`dy` ótimo igual ao do Pango. A via fiel (extrair os glifos *do* Pango e chamar
`show_glyphs`) **não existe no pygobject**: `GlyphString.glyphs` estoura "Stack
overflow protection" e volta `[]`. Se for tentar, o desenho precisa escolher por
run (ASCII sem `.notdef` → cairo; senão Pango) e a validação é comparação de
pixels, não o fps.

P27 — Desenho: redesenho parcial (dirty-rect) e cache de linha em surface.
**Ideia estrutural, sem número.** No doom-fire não ganha nada (a tela muda
inteira), mas em uso real (vim parado, rolagem de log, shell) a maior parte da
grade não muda entre draws: uma linha cacheada vira 1 blit (1,15 µs) em vez de
~63 runs (~0,4 ms). Exige marcar dirty no `put`/scroll/resize (barato) e cuidar
de memória (21 linhas ≈ 2,6 MB) e invalidação no resize/DPI. Ganho não
mensurável pela carga atual — precisaria de uma segunda carga (scroll de log),
o que é decisão à parte.

P28 — Seleção com o mouse: clique de 1 char e âncora no scroll. **Na fila**;
scroll decidido: **desfazer a seleção ao rolar** (opção B, 2026-10-27). Dois sintomas, mesma raiz: a seleção vive em coordenadas da
**tela** (`y` de `visible_rows()`), não do conteúdo.

1. **Clique sem arrastar seleciona 1 caractere.** `on_button_press` faz
   `sel_start = sel_end = (row, col)` e já pinta a célula em reverso; no
   `on_button_release` o `copy(PRIMARY)` roda mesmo sem arrasto e **sobrescreve
   o PRIMARY do usuário com 1 char**. Um clique que devia só dar foco/limpar a
   seleção deixa um destaque na tela e estraga o "colar com o botão do meio".
   Não existe `n_clicks`: duplo clique = dois cliques de 1 char (não há seleção
   por palavra/linha).
2. **Rodar a tela mantém a seleção na linha física.** `sel_range()` devolve
   `(r1, c1, r2, c2)` em linhas visíveis e `_in_sel()` compara com o `y` do
   draw; `scroll_view()` muda `view_off` sem tocar na seleção, então o destaque
   fica na mesma posição da tela e passa a cobrir **outro texto**. Pior: o
   `copy()` seguinte usa `rows = visible_rows()` com o `view_off` novo, então
   copia o texto errado. Um clique no histórico (`back_to_live()`) também volta
   ao vivo antes da seleção — hoje não dá para selecionar histórico com o
   mouse.

Opções para o scroll — **(B) escolhida** (2026-10-27):

- **(A) ancorar a seleção no conteúdo** — **descartada**: guardar a linha
  absoluta (`len(scrollback) - view_off + y`) em vez do `y` da tela, com o
  destaque andando junto com o texto ao rolar (é o que xterm/kitty fazem). Custo
  médio e uma âncora que o experimento não tem onde guardar: o índice absoluto
  muda quando o `scrollback` cresce com a seleção viva, e reflow/resize
  invalidam tudo. Não se paga aqui.
- **(B) desfazer a seleção ao rolar** — **escolhida**: `scroll_view()` limpa
  `sel_start`/`sel_end` quando `view_off` muda. Três linhas, comportamento
  previsível, e resolve o "copia o texto errado" por construção. Perde a
  seleção ao rolar, o que é aceitável para um experimento.

Para o clique, independente do scroll: só criar seleção quando houver
arrasto (`on_motion` com botão pressionado) e não copiar no release se
`sel_start == sel_end`; no press, limpar a seleção anterior e dar foco. Se
duplo clique for desejado, é item à parte (palavra), não precisa entrar aqui.

Verificação (manual, com display): `tools/xtest.py` — `click` numa célula e
conferir no dump (`kill -USR1`) que não sobrou reverso e que o PRIMARY não
mudou (`xclip -o -selection primary`); `drag` e depois `wheel` — o destaque tem
de sumir; `copy` depois do wheel não pode devolver texto de outra linha. `core/checks.py` cobre `selection_text` puro,
mas não o estado da view (precisa de Gtk).

P29 — `Alt+Backspace` (e `Alt` nas teclas de `SIMPLE`) não manda o prefixo
`ESC`. **Na fila** (2026-10-27). No kitty e no ghostty, no `zsh`, `Alt+Backspace`
apaga a palavra à esquerda; no bzmux age como `Backspace` puro (apaga 1 char).

Causa: `encode_key()` (`core/keys.py`) trata `kv in SIMPLE` antes de qualquer
coisa e devolve `SIMPLE[kv]` **sem olhar o `alt`** — o `"\x1b" + s` só existe no
ramo dos imprimíveis e das dead keys. `BackSpace` está em `SIMPLE` como
`"\x7f"`, então Alt+Backspace sai igual a Backspace. O `zsh` liga
`backward-kill-word` em `"^[^?"` (ESC DEL) por padrão — que é o que xterm,
kitty e ghostty mandam nesse caso. No protocolo do kitty (flag 1,
`disambiguate`) o caminho é outro (`CSI 127;3u`), mas o `zsh` não fala esse
protocolo: o conserto é no caminho legado.

Mesma raiz, provavelmente o mesmo sintoma: `Alt+Tab`, `Alt+setas`,
`Alt+Home/End`, `Alt+F1..F12` e `Ctrl+Alt+letra` (que cai em
`chr(kv & 0x1f)` sem ESC). O escopo do fix é decidir se `Alt` prefixa `ESC` em
todas as sequências (como xterm faz) ou só nas de `SIMPLE`, tomando cuidado com
o que já tem tratamento próprio: `Shift+Tab` (`\x1b[Z`) e o `APP_CURSOR`
(DECCKM), para não sair `ESC ESC [ Z` nem perder o `\x1bO`.

Verificação (manual, precisa de display): dentro do bzmux, `cat -v` e apertar
`Alt+Backspace` — tem de aparecer `^[^?` (hoje aparece `^?`); no `zsh`, digitar
duas palavras e apertar `Alt+Backspace` — apaga a palavra, como no kitty.
`tools/xtest.py key alt+BackSpace` injeta a tecla. `keys.py` fica fora do
`--selftest` por depender das constantes do Gdk, então não entra em
`core/checks.py`.

Os 25 itens anteriores (P1–P25) estão concluídos. Histórico, bugs e quirks:
[HISTORY.md](HISTORY.md). Status e por onde retomar:
[../TASK-bzmux.md](../TASK-bzmux.md).

O que sobra é limite conhecido, não item — caractere largo (CJK/emoji) ocupando
uma célula só, protocolo de teclado do kitty parcial, sequências não
interpretadas, sem configuração/tema — tudo em
[LIMITATIONS.md](LIMITATIONS.md).
