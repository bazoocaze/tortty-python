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

P35 — Socket de introspecção para o agente (`--debug-socket`). O usuário
principal é o agente de IA, que hoje fala com o app por três caminhos ruins:
`PYTERM_*` (só na partida e muda o comportamento), arquivo (`--dump-to` só na
saída; `debug_log` é só escrita e `/tmp` é global, disputado entre a sessão do
usuário e a de teste) e `tools/xtest.py` (exige display, injeta no X real e já
travou o desktop por implicit grab). O dump do `SIGUSR1` mostra a grade viva,
não a visão rolada — justamente o que investigação de scroll precisa.

Decisões tomadas na discussão (2026-11-01):

- socket Unix, não TCP: JSON por linha, um pedido por linha e uma resposta por
  linha; sem HTTP, sem thread (`GLib.io_add_watch` no fd de escuta e nos
  clientes, mesma thread da UI, sem corrida com o `Term`).
- `--debug-socket ARQ` com valor obrigatório e `auto` = arquivo com o pid no
  nome em `$XDG_RUNTIME_DIR`; só linha de comando (nada na configuração), vale
  na partida e desligado por omissão. Sem contrato a manter: verbo pode mudar
  sem aviso.
- `0600`, conexão só do mesmo uid (`SO_PEERCRED`), `unlink` na saída e do socket
  órfão antes do `bind` (só se for socket e ninguém estiver ouvindo).
- Verbos mínimos: `state` (grade, cursor, título, `view_off`, `pin`,
  `sync_output`, tamanho do histórico), `text` (fatia visível e fatia do
  histórico por linha absoluta), `write` (bytes crus para o pty, como se
  digitados) e `log` (liga/desliga/troca o `debug_log` em execução). `tab` e
  `resize` só se aparecer necessidade real.

Custo estimado: módulo novo com o despacho puro (testável sem display, com alvo
falso) mais o glue do `GLib`; o resto reaproveita o que o dump e o `view_off` já
fazem. Ferramenta de debug — registro no DEBUG.md, não no README.

Os demais itens estão concluídos: histórico e bugs em [HISTORY.md](HISTORY.md),
ferramentas e armadilhas em [DEBUG.md](DEBUG.md), status e por onde retomar em
[../TASK-bzmux.md](../TASK-bzmux.md).

O que sobra é limite conhecido, não item — caractere largo (CJK/emoji) ocupando
uma célula só, protocolo de teclado do kitty parcial, sequências não
interpretadas, sem tema/paleta configurável — tudo em
[LIMITATIONS.md](LIMITATIONS.md).
