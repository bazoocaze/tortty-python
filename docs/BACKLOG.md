# pybzmux — backlog (pendente)

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

P38 — Runtime alternativo: PyPy e Cython no caminho quente. **Experimento, não
compromisso.** Pedido: dá para medir o projeto sob PyPy e sob Cython? O app
inteiro não: o `gi` só é importado em `bzmux/gui.py`, mas é por ele que passam
view e window, e o PyGObject não roda no PyPy (o `cpyext` não cobre a API C que
ele usa) — a janela não sobe. O que dá para medir é o caminho quente puro
(`palette`, `term`, `graphics`, `kitty_kbd`, `mouse`): alimentar N MB no `Term`
e comparar MB/s de parse+grade com o CPython, que é a régua do
[BENCHMARKS.md](BENCHMARKS.md). Cython é viável no mesmo subconjunto (nenhum
desses módulos importa `gi`), ao preço de um passo de build por versão de Python
no `install.sh`/pipx e de tipar os laços quentes — compilar sem tipos C rende
pouco. Cabe na mesma medição: mypyc (exige anotar o código) e Nuitka. Hoje
`pypy3` e `cython` não estão instalados.

P39 — Splits: mais de um terminal na mesma view. **Feature.** Pedido: dividir a
view em vários terminais. Custo levantado de graça na conversa (2026-11-01,
Xvfb, fonte 13, cena de texto com 8 cores): por frame há um fixo de ~0,4 ms mais
~0,5 µs por célula — 61x18 dá 0,99 ms, 31x18 dá 0,68 ms, 16x9 dá 0,49 ms, então
o desenho de N splits no mesmo widget custa praticamente o mesmo que a tela
cheia de hoje, e um widget por split paga o fixo uma vez por split. Memória é o
que escala de verdade: 90 KB a tela e **~5 MB por terminal** com `scrollback`
1000 (84 B por célula). Não há thread no projeto: cada split é mais um stream de
pty na mesma thread do desenho (como N abas hoje, mas com draw junto). O que
decidir na execução: um widget com dano por região vs. widget por split, cache
de layout e métricas de fonte compartilhados, blink só no visível, e o teto
prático de splits — que vem da memória, não do frame.

P30 — Portabilidade gráfica: rodar no Linux, Windows e macOS. **Aberto**
(revisto em 2026-11-01): nem Python nem cairo/Pango são identidade — foram
escolha inicial. Pontos em jogo, só registrados (não são requisitos): OS alvo,
features do alvo (splits, aviso de atenção, CLI), vazão/latência, forma de
instalar. O estudo, os bloqueios no código e o custo de cada rota (conda, Qt,
FFI) estão em [PORTABILITY.md](PORTABILITY.md); nada disso está decidido.

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
ferramentas e armadilhas em [DEBUG.md](DEBUG.md).

O que sobra é limite conhecido, não item — caractere largo (CJK/emoji) ocupando
uma célula só, protocolo de teclado do kitty parcial, sequências não
interpretadas, sem tema/paleta configurável — tudo em
[LIMITATIONS.md](LIMITATIONS.md).
