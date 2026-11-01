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

B17 — Seleção do mouse não acompanha o scroll da tela: com texto selecionado, o
conteúdo rola e a seleção não vai junto (o realce fica na posição de tela).
Registrado sem investigação; diagnóstico e reprodução ficam para a execução.

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
- `shell` (default `/bin/bash`) vira o comando de cada aba nova; `--cmd` vence.
  **Mudança de comportamento**: `$SHELL` não é mais consultado;
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
