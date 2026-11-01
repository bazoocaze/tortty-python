# bzmux — backlog (pendente)

Regras da fila:

- Registrar é só registrar: a investigação (ler código, medir, reproduzir)
  acontece quando o item for executado, não quando ele é anotado. Na anotação
  vai o que o pedido já trouxe — sintoma, e o que for de graça no caminho — e
  para por aí; nada de diagnóstico completo, causa raiz ou plano fechado antes
  da hora. Item já registrado não se reescreve para caber nesta regra.
- Ao fechar um item: mover para o fim de "Backlog concluído" em
  [HISTORY.md](HISTORY.md), com o bug que apareceu no caminho e como foi
  verificado.
- Bug corrigido fora de item entra na lista numerada de bugs do HISTORY.md; o
  quirk, se for armadilha de ambiente ou de ferramenta, em [DEBUG.md](DEBUG.md).
- Decisão de NÃO fazer algo vai para [LIMITATIONS.md](LIMITATIONS.md), não para
  cá; se o limite deixar de existir, sai de lá e vira item concluído no HISTORY.

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
**Microbench feito (2026-11-01): a ideia como está não se paga.** Evidência em
`tools/uploadbench.py` (frame sintético de 1098 células em 61x18, display real,
mediana de 60 frames, `sync` por frame):

- desenho direto na janela (o de hoje): **4,0 ms** por frame;
- frame num ImageSurface e um `paint`: **5,6 ms** (0,72x — mais lento, os pixels
  sobem pelo fio);
- frame num surface do servidor (`create_similar_surface`) e uma composição:
  **42,6 ms** (0,10x), porque desenhar nos pixmaps pequenos custa ~10x mais por
  operação que na janela;
- o mesmo pixmap com só 10% redesenhado: **5,7 ms** (0,71x — ainda perde para o
  desenho direto);
- compor o pixmap inteiro sem desenhar nada: **0,38 ms** (10,8x mais rápido que
  desenhar) — ou seja o cache só ganha se o frame estiver *parado*, e aí o
  bzmux nem desenha.

O `cProfile` no app (doom-fire, 61x18, 160 draws) mostra que o alvo real é
outro: o tempo de `_on_draw` é majoritariamente **Python**, não servidor —
`cell_rgb_f` 368 mil chamadas (2 por run, uma delas só para comparar com
`DEF_BG`), `"".join(...)` com genexpr 298 mil, um `dict.get` por run. As
chamadas cairo somam ~40% do draw.

Direção revisada (a confirmar com o mesmo `prof` antes/depois): cortar trabalho
Python por run — comparar `bg != DEF_BG` em vez de chamar `cell_rgb_f` de novo,
list comp em vez de genexpr no join, cache do par (fg, bg) → tuplas RGB por
draw. Estimativa grosseira: 3–4 ms dos 13,7 (25%) só com isso; cache de linha em
surface e dirty-rect ficam fora até haver número que os justifique.

P30 — Portabilidade gráfica: rodar no Linux, Windows e macOS. **Discussão,
decisão pendente** (2026-10-28). O estudo (o que é plataforma hoje, os bloqueios
no código, o custo de cada rota e a pergunta que precede o código) saiu para
[PORTABILITY.md](PORTABILITY.md); aqui fica só o item aberto.

P33 — Arquivo de configuração: **v1 implementado** (2026-10-29), falta o uso
real. A decisão de escopo foi "começar só com `shell`": nada de cores, fonte ou
atalhos. O que existe:

- `bzmux/config.py` puro (sem `gi`): parse do formato do kitty (`chave valor`,
  `#` comenta até o fim da linha, espaço nas pontas, chave repetida vale a
  última), validação por chave e merge **sempre** com o default;
- default embarcado em `bzmux/data/bzmux.conf` (vai no wheel como o ícone);
- arquivo do usuário em `$XDG_CONFIG_HOME/bzmux/bzmux.conf`, e `-c ARQ` /
  `--config ARQ` troca só esse caminho (o merge com o default continua);
- `shell` (vazio no default) vira o comando de cada aba nova; `--cmd` vence.
  Vazio herda o `$SHELL` do ambiente, e o `$SHELL` entregue ao filho é sempre o
  shell que roda de fato (antes ficava o herdado, mesmo com outro configurado);
- auto-reload por `Gio.FileMonitor` com debounce de 250 ms; no reload, erro
  mantém a configuração anterior (nada muda) e o erro vai para um toast de 10 s
  na base da janela (estilo Android, `Gtk.Revealer` + `#toast` no `style.py`);
- `Ctrl+Shift+F2` abre o arquivo do usuário no `vim`, em aba nova.

Fonte, cursor, histórico, padding, bell e cópia já entraram (P34, concluído). O
que fica para depois: paleta (`color0..15`, `foreground`, `background`,
`cursor`, com `#rrggbb` no formato do kitty) e remapeamento de atalhos.

Dois bugs achados no caminho, registrados no `docs/HISTORY.md`: o
`Gio.FileMonitor` era coletado pelo GC (sem referência guardada o reload nunca
disparava) e `no_show_all` bloqueia até o `show_all()` chamado direto no widget
(a caixa do toast ficava invisível).

Os demais itens estão concluídos: histórico e bugs em [HISTORY.md](HISTORY.md),
ferramentas e armadilhas em [DEBUG.md](DEBUG.md), status e por onde retomar em
[../TASK-bzmux.md](../TASK-bzmux.md).

O que sobra é limite conhecido, não item — caractere largo (CJK/emoji) ocupando
uma célula só, protocolo de teclado do kitty parcial, sequências não
interpretadas, sem tema/paleta configurável — tudo em
[LIMITATIONS.md](LIMITATIONS.md).
