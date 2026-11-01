# bzmux — histórico

Memória do projeto: backlog concluído, bugs corrigidos e git.
Não é tarefa. Pendências: [BACKLOG.md](BACKLOG.md). O que não é feito e por quê:
[LIMITATIONS.md](LIMITATIONS.md). Status, escopo, arquitetura, medições e
como testar: [../TASK-bzmux.md](../TASK-bzmux.md). Ferramentas e armadilhas:
[DEBUG.md](DEBUG.md).

## Convenções

- Convenções do projeto: [../AGENTS.md](../AGENTS.md). As daqui são sobre o que
  se registra, não sobre o código.
- Conciso, e o detalhe fica onde já está: caminho e função tocados, assinatura
  nova, teste acrescentado, ordem das tentativas e diff estão no código e no
  `git log`. O item guarda só o que a memória precisa.
- O que fica: a decisão e o porquê, a alternativa descartada, a armadilha que não
  deve ser redescoberta, o bug (causa em uma frase, fix em uma frase) e como se
  provou que funcionou.
- Verificação é a observação, não o comando: "o dump mostrou 5 linhas", e não a
  linha de shell que gerou o dump — comando fica em DEBUG.md.
- Bug: causa e fix em uma frase cada. A sequência de tentativas não é regressão;
  se o caminho ensina armadilha, ela vai para DEBUG.md.
- Número de medição não mora aqui (vai para BENCHMARKS.md). Exceção: o número do
  dia em que o item fechou, como registro datado.
- Item fechado cabe em ~10 linhas. Passou disso é sinal de que está recontando o
  código.
- Formato: título `### Pn — assunto (data)`, parágrafos curtos ou lista, `code`
  para caminho, símbolo e valor. Negrito só no status do título; sem tabela.
- Vale para o que entrar daqui pra frente. Item antigo não se reescreve só para
  caber nesta regra.

## Backlog concluído

Ordem de execução, não de prioridade. Cada item guarda o que foi
implementado, o bug achado no caminho e como foi verificado — serve de
regressão: se o comportamento descrito aqui mudar, falta check ou o código
regrediu. Aberto: BACKLOG.md.

### P1 — Mouse (report a apps + seleção/cópia) — **feito**

`?1000`/`?1002`/`?1003` (clique / arrasto / movimento), `?1006` (SGR),
`?1004` (foco manda `CSI I` / `CSI O`), codificação em `core/mouse.py`
(puro, testável sem display). Fora dos modos de mouse a janela faz seleção
local arrastando: vídeo reverso, `Ctrl+Shift+C` copia (seleção ou viewport),
`Ctrl+Shift+V` cola, botão do meio cola o PRIMARY. `Ctrl+Shift+C/V` são
interceptados antes do teclado — senão `Ctrl+Shift+C` virava o mesmo `^C` de
`Ctrl+C` e matava o processo.

Bug achado no caminho (e corrigido): a inversão era feita nos **índices** de
cor e só depois convertida pra RGB. `DEF_FG`/`DEF_BG` são sentinelas (256/257),
não índices, então `256 - 256 % 256 = 0` virava preto e `257 % 256 = 1` virava
**vermelho**: selecionar texto default saía vermelho-em-preto, e `\e[7m`
idem. Fix: converter pra RGB primeiro, inverter depois.

Verificado com XTest sintético (`tools/xtest.py`): clique →
`\e[<0;5;4M`/`m`, arrasto → `\e[<32;12;6M`, wheel → `\e[<65;31;11M`;
seleção + `Ctrl+Shift+C` + `Ctrl+Shift+V` num `cat` devolveu o texto certo, e
screenshot confirmou o realce.

Falta (fica pra depois): duplo-clique por palavra, seleção retangular.

### P2 — Tela de histórico (rolar scrollback) + scroll com o mouse — **feito**

`Term.visible_rows(off)` devolve a janela de `rows` linhas sobre
`scrollback + grid` sem tocar no cursor nem no que o app escreveu; a janela
usa `off = view_off` no desenho, na cópia e no dump.

- `Shift+PgUp`/`PgDn` (uma página), `Shift+Home`/`End` (tudo), **wheel**
  (3 linhas por entalhe).
- Volta ao vivo ao digitar, ao clicar e quando o filho escreve.
- Wheel sem app em modo mouse rola a visão; com app em modo mouse manda
  `64`/`65` (`CSI < b ; x ; y M`/`m`) — mas **se a visão está no histórico o
  wheel continua no histórico**, senão o app "roubava" o scroll justo quando
  o usuário estava lendo.
- Indicador `↑N` no canto superior direito; cursor do app não é desenhado no
  histórico (o cursor de visÃo é separado, de propósito).

Bug achado no caminho: **apertar Shift resetava o histórico**. O Shift chega
como evento de tecla antes da tecla real, e "qualquer tecla volta pro vivo"
zerava a visão — então `Shift+PgUp` voltava ao vivo e recomeçava do `off`=0,
embora acumulasse certo no contador (`6 + 21` ficava 21). Fix:
`keys.is_modifier()` — modificador puro não sai do histórico.

Verificado: `seq 1 60`, 2 entalhes de wheel + `Shift+PgUp` → `↑27`, topo na
linha 13; digitar `a` voltou pro vivo (dump confirma).

### P3 — Reflow no resize — **feito**

Linha lógica agora é rastreável: `Term.row_wrapped[i]` (e `sb_wrapped`, paralelo
ao scrollback) marca *quebra mole* — a linha encheu e continua na de baixo,
diferente de um `\n` de verdade. `put()` liga a flag quando estoura a última
coluna; `scroll_up`, `IL`/`DL`, `ED 3` e `?1049` mantêm as listas em sincronia.

`_reflow(cols, rows)` junta as linhas lógicas de `scrollback + grid`, corta na
largura nova, recoloca o cursor na célula equivalente (offset dentro da linha
lógica, não `(cx, cy)`) e reparte o resultado: o que sobra em cima vai pro
scrollback, o que falta embaixo é preenchido. Alargar **puxa de volta** linhas
que estavam no scrollback — é isso que faz 100 caracteres voltarem a ser uma
linha só. Alt-screen continua no recorte (`_resize_crop`): `mc`/`vim`
redesenham inteiro no SIGWINCH.

Bug achado (o que quase estragou): sem **cortar o espaço em branco à direita**
da linha lógica, uma linha de 3 caracteres numa tela de 68 colunas re-quebra em
duas (a segunda só de espaços) e o conteúdo aparece **intercalado com linhas
vazias** ao estreitar — vi isso no `seq 1 200` a 36 colunas. Fix: corta célula
vazia de verdade (espaço com bg default), preserva fundo colorido, e nunca corta
antes da coluna do cursor. Também tive de parar de sobrescrever o cursor a cada
chunk: só o primeiro chunk que contém o offset ganha (senão o cursor pulava pro
último chunk da linha).

Verificado: uma linha de 400 caracteres em 1000x700 → 4 linhas; a 300x300 → 14
linhas (13×30 + 10), contíguas; `seq 1 200` estreitado para 36 colunas mantém
191..200 sem buracos; `--selftest` cobre 1→4 e 4→1 com cursor.

### P4 — Truecolor de verdade — **feito**

O RGB mora na **própria célula**, sem tabela de cores alocadas e sem tupla: o
índice de paleta continua sendo `int` pequeno (0-255) ou sentinela (256/257), e
truecolor vira `int` marcado no **bit 24** — `TC | r<<16 | g<<8 | b`
(`palette.rgb()` / `cell_rgb()`). Assim o caminho de 256 cores não paga nada
(nenhum `dict` por célula, nenhum LRU) e a célula não engorda: o `int` de um
`#123456` é 0x1123456, que em CPython ocupa o mesmo que 196.

SGR: `38;2;r;g;b`, `48;2;r;g;b` e a **forma com `:`** (`38:2::r:g:b`,
`38:2:0:r:g:b`, `48:5:196`). O subparâmetro vazio é o espaço de cor omitido, e
a posição importa: o parser guarda o grupo como tupla (só para o final `m`) e o
`sgr()` achata com `_sgr_subparams()` — filtrar os vazios mudaria o sentido de
`48:5::196`.

O desenho resolve a cor antes de inverter (`cell_rgb`), então inverso/seleção
seguem trocando RGB, e o agrupamento em runs continua comparando `int`
(células truecolor de cor distinta não se agrupam, como tem que ser).

Verificado no `--selftest` (fg/bg na célula, ida e volta, forma `:`, 256
cores não virando RGB, reset, sobrevive ao reflow) e pixel a pixel com
`vim -c 'set termguicolors'`:
`hi Normal guibg=#123456 guifg=#ffcc00` → fundo `(18,52,86)` e glifo
`(255,204,0)` exatos na captura. `38;2` não passa mais por `_nearest`.

Fora de escopo (documentado): `58;2` (cor do sublinhado) — nem desenhamos
sublinhado colorido.

### P5 — Kitty keyboard protocol — **feito**

`core/kitty_kbd.py` (puro, sem Gtk) + estado no `Term`
(`kbd_flags`/`kbd_stack`). Protocolo: `CSI > flags u` push, `CSI < n u` pop,
`CSI = flags ; modo u` (1 substitui, 2 acrescenta, 3 remove) e `CSI ? u` →
responde `CSI ?<flags>u`.

Encoding espelhado no `encode_key()`/`encode_function_key()` do kitty
(o `key_encoding.c` dele, que foi a referência):

- `disambiguate` (1): Esc/Enter/Tab/Backspace viram `CSI 27u`/`13u`/`9u`/`127u`;
  Ctrl/Alt/Super+tecla viram `CSI codigo ; mods u`; setas/F1–F12 com
  modificador viram `CSI 1 ; mods A` etc.
- `report event types` (2): sufixo `:1`/`:2`/`:3`; o window passa a escutar
  `key-release-event`.
- `report all keys as escape codes` (8) e `report associated text` (16).
- Fora esses casos, cai no caminho legado (`\x1bOA`, `\x03`, texto puro) — que
  é exatamente o que o kitty faz, então digitar continua funcionando.

Detalhe que só apareceu na referência: o campo de modificadores é
`1 + shift + 2*alt + 4*ctrl + 8*super`, e F3 é o único F que usa número (13)
em vez de letra (`CSI 13~`), porque `CSI 1;mR` colidiria com o relatório de
posição do cursor.

Fora (documentado no README): flag 4 (`report alternate keys` — exigiria o
keysym alternativo, que o Gdk não dá de graça), repeat distinguido de press (o
Gdk repete como key-press) e o modo keypad.

Verificado ponta a ponta com um filho que liga `CSI >3u` e imprime o que
recebe: Ctrl+a → `\e[97;5u` + `\e[97;5:3u`, Enter → `\e[13u` + `\e[13;1:3u`,
Shift+Up → `\e[1;2A` + `\e[1;2:3A`, e digitar `x` continua sendo `x`.

### P6 — Protocolo de gráficos (kitty) — **feito**

`graphics.py` puro (parse, decodificação e placements) e desenho na `TermView`;
APC `ESC _ G` no parser do `Term`. Cobre as ações e formatos do protocolo que o
`icat` usa — inclusive `o=z` (payload zlib) e `X=`/`Y=`, que é o que o `--place`
manda depois de escalar sozinho.

Decisão: a colocação guarda a linha da GRADE, não a da tela. Ela pode ficar
negativa e ir para o scrollback, e o desenho soma `view_off`, então
`Shift+PgUp`/wheel mostram a imagem na posição certa (`drop_above()` e o reflow
podam o que saiu de vez). Descartado: fazer a imagem acompanhar o reflow linha a
linha — ela fica na linha de tela, como no kitty (está em LIMITATIONS.md).

Bugs do caminho: a sonda `a=q` é de capacidade, não consulta de imagem (o
`icat` a usa de handshake e só segue com `OK`); `m=1` não pode ser acumulado no
dicionário de controle, senão a transmissão nunca termina; e o `CSI * x`
(DECSACE) que o `icat` manda antes de desenhar caía com o `*` como byte final,
deixando um "x" solto por imagem — fix: aceitar intermediários 0x20–0x2f.

Verificado: PNG 160x90 em 2 pedaços, RGBA cru 40x20 e a demo de cinco imagens
nos lugares certos (screenshot), rolagem acompanhando, e `kitten icat` real
saindo com código 0; o mesmo script roda igual no kitty.

### P7 — Bracketed paste — **feito**

`?2004` no `set_mode` junto de `?1000/?1006/?1004` → `Term.bracketed_paste`. A
política de colar mora no `Term` (`paste_payload()`), não na janela: com o modo
ligado o texto vai entre `ESC[200~` e `ESC[201~`, senão vai cru. Assim o
`--selftest` cobre o comportamento sem display, e o pty recebe **texto**, nunca
uma sequência que o parser do terminal interpretaria (é o ponto de segurança: o
que foi colado não vira tecla).

**O bug que apareceu junto (e era a causa do "Enter" ao colar):** o `copy()`
fazia `text += "\n"` **sempre**, então copiar `abcdef` com o mouse punha
`abcdef\n` no clipboard e o paste executava o comando. A regra do kitty é só
juntar as linhas com `\n` ENTRE elas (`add_trailing_newline = insert_newlines
&& !is_last_line` no `text_for_range`): o fim de linha só entra quando o arrasto
chega na coluna 0 da linha seguinte, porque aí a última linha da seleção é
vazia. Tirado o `+= "\n"`.

Verificado no `--selftest` (os dois modos de `paste_payload`, seleção sem
newline) e ponta a ponta com filho que liga `?2004` e despeja os bytes:

```
modo off      → recebi: b'abcdef\x04'
modo on       → recebi: b'\x1b[200~abcdef\x1b[201~\x04'
bash 5.2      → copiar "echo a" e colar NÃO executa; Enter executa
```

Não implementado de propósito: `strip_trailing_newlines` do kitty (tirar um
`\n` final na cola) — muda o comportamento de quem cola multi-linha de
propósito.

### P8 — Fechar a janela quando o shell termina — **feito**

O gatilho é o **`waitpid`**, não o EOF do pty: `GLib.child_watch_add(pid)` reapa
o filho e entrega o status. No Linux o master devolve **EIO** (não `b""`)
quando o último escravo fecha, e o `on_pty` antigo engolia esse `OSError` e
simplesmente removia o watch — era por isso que o `Ctrl+D` deixava a janela
aberta para sempre.

- **Sem zumbi**: quem colhe é o `child_watch_add` (o GLib faz o `waitpid`); o
  código do bzmux não chama `waitpid` de novo.
- **Drena antes de fechar**: `_drain_pty()` lê até `EAGAIN` (o fd é
  non-blocking) com teto de 64 leituras, alimentando o `Term` — senão o
  `dump()`/última tela saíam sem a despedida do shell.
- **Código de saída**: não-zero vai para o stderr (`bzmux: shell saiu com
  código 3`), que o `debug.sh` guarda em `/tmp/bzmux.log`.
- **Hangup**: `os.killpg(child_pid, SIGHUP)` no fechamento (o `pty.fork` fez do
  filho líder de sessão), então jobs em background não ficam órfãos segurando o
  pty.
- **Ordem inversa também vale**: `EIO` antes do `waitpid` → espera o status;
  `waitpid` antes do `EIO` → drena e fecha.

Pegadinha que fez o hangup "não funcionar": **disposição de sinal é herdada**.
O `debug.sh` sobe com `nohup` (SIGHUP = ignorado) e o Python ignora SIGPIPE — o
filho herdava os dois. Resultado: `killpg(SIGHUP)` não matava ninguém (o `sleep`
aparecia com `SigIgn: 01001007`) e `seq 1 100000 | head -3` não parava no pipe
quebrado. Fix: no filho do `pty.fork`, antes do `exec`, `SIGHUP`/`SIGPIPE`/
`SIGINT`/`SIGQUIT`/`SIGTERM` voltam para `SIG_DFL`.

Verificado: `--cmd 'exit 3'` fecha e loga o código 3; `Ctrl+D` num `bash`
interativo fecha; `sleep 120 & ... exit` fecha e o job morre no SIGHUP;
`seq 1 100000 | head -3` termina na hora; `--quit-after 2` continua fechando;
fechar a janela pelo WM mata o filho (o master fecha → SIGHUP do kernel no grupo
da frente).

### P9 — Ligaduras e shaping — **feito**

O desenho era `cairo.show_text` (API toy): sem shaping, então ligadura não saía,
árabe não ligava e marca combinante se separava do corpo da letra. Migrado para
Pango, com um `Pango.Layout` por draw reaproveitado em cada run.

- Cache de layout por `(texto, negrito)`, teto de 800: `set_text` é a parte cara e
  run se repete muito — sem cache o desenho dobra (números abaixo).
- Métricas saem do mesmo layout que desenha (avanço de "M" e `get_pixel_size`);
  misturar cairo e Pango desalinha a grade. Sublinhado segue retângulo do cairo,
  que não depende de métrica de fonte.

Custo do shaping com o doom-fire (68×20): 12,8 ms/frame antes, 30,5 sem cache,
15,2–15,6 com cache — ~20% do frame com cache, 2,4x sem. Os três são anteriores
ao bug 13 (desenho a 96 dpi): valem entre si, não contra
[BENCHMARKS.md](BENCHMARKS.md).

Emenda: a fonte passou a ser em **pontos**, não em pixels. O `font_size` vinha do
cairo, onde tamanho é unidade de usuário; mas todo terminal expõe pontos, e a
diferença é DPI — com `Xft.dpi: 130`, 13 pt = 23,5 px contra 16 px, e era por isso
que o "13" do kitty parecia maior que o "16" daqui. Com pontos, bzmux e kitty dão
a mesma grade para a mesma janela (70×21 em 980×640). A métrica tem que sair do
contexto Pango do widget, não de uma surface solta ([DEBUG.md](DEBUG.md)).

### P10 — Fallback de fonte (emoji/CJK) — **feito**

Caiu junto com o P9: o fontconfig acha a fonte que tem o glifo, então CJK e
emoji em cor passam a desenhar sem nenhum código a mais. Verificado na tela com
`printf '\u4e2d\u6587 \U0001F600'` no bzmux.

Limite que fica (e não é bug do fallback): a grade **não tem `wcwidth`**, então
caractere largo ocupa uma célula só e o glifo é espremido/estourado nela. App que
conta coluna dupla (tabela em CJK) sai desalinhado; resolver isso é mexer no
modelo de célula, não no desenho.

### P11 — Abas — **feito**

`Ctrl+Shift+T` abre aba, `Alt+1..9` (`Alt+0` = a 10ª) seleciona, `Ctrl+Shift+W`
fecha; fechar a última fecha a janela.

- Decisão estrutural: extrair `TermView(Gtk.DrawingArea)` com o estado de sessão
  (pty, decoder, seleção, `view_off`, cache de imagem) e deixar a janela com o
  `Gtk.Notebook` mais os atalhos globais. `Term` continua sem GTK. `Alt+N` é
  tratado na janela, senão o filho recebe a tecla primeiro.
- Rótulo é o título do OSC 0/2 ou o cwd da sessão (`readlink /proc/<pid>/cwd`, sem
  depender de OSC 7): sem OSC todas as abas ficariam "bzmux", e o `Alt+N` já
  numera — daí não haver prefixo numérico.
- O `child_watch_add` do P8 passa a fechar a **aba**, e a agregação "última aba →
  janela" mora num lugar só.

Quatro armadilhas silenciosas (página nova nasce oculta e o `set_current_page` é
ignorado; `grab_focus` dentro de `switch-page` não pega; `sh -c` não faz exec, o
cwd está no neto; `EventBox` sem `add_events` tem máscara vazia e
`set_tab_label_text` troca o widget): conserto em [DEBUG.md](DEBUG.md).

Teste por XTest (criar, alternar, digitar em cada aba, clique do meio) e
`_NET_WM_NAME` para o título. `--selftest` não cobre — é camada GTK.

### P12 — Workspaces — **feito**

Workspace é um conjunto de abas com um cartão na lateral: `1  <título da aba
ativa>`, largura fixa (170 px), e a lateral só aparece com 2+ workspaces.
`Ctrl+Shift+1..9` seleciona (`0` = o 10º), `Ctrl+Shift+N` cria, `Ctrl+Shift+Q` ou
clique do meio no cartão fecham, duplo clique renomeia no lugar. Fechar a última
aba fecha o workspace; o último, a janela.

- `Gtk.Stack` com um `Gtk.Notebook` por página, não troca de páginas de um
  notebook só: cada workspace guarda a própria aba selecionada, ordem e títulos,
  e a troca é uma chamada.
- `Ctrl+N` foi descartado de propósito: `C-n` é próxima linha no readline,
  autocomplete no vim e next-line no emacs. O cmux usa `Ctrl+N` porque não *é* um
  terminal. Não "consertar" para `Ctrl+N` depois.
- Aba escondida não recebe `size-allocate`: ao trocar de workspace é preciso
  forçar o recálculo da view que apareceu, senão `cols`/`rows` e o `SIGWINCH` do
  `Term` ficam velhos. A lateral custa ~14 colunas e todo resize re-quebra o
  buffer (reflow do P3).
- Armadilhas de teclado, foco e widget: [DEBUG.md](DEBUG.md).

Teste por XTest e `xprop`: criar, alternar, renomear, fechar por atalho e por
clique do meio, e conferir que `Ctrl+Shift+T` abre aba do workspace atual.
`--selftest` não cobre.

### P13 — Sistema de estilo da interface — **feito**

Pedido: lateral preta, workspace selecionado em verde escuro e texto claro. O
que existia era o tema do sistema pintando tudo, com um hex solto no cartão.

Decisão: `style.py` é a única fonte de cor do cromo — tokens (fundo, texto,
hover e selecionado), `css()` montando o texto a partir deles e `contrast()` em
sRGB relativo (WCAG). Puro, então o check roda no `--selftest`; a paleta do
terminal continua separada, célula e cromo não se misturam.

O check mede contraste, não gosto — `style_contrast` exige >= 4,5:1 nos quatro
pares texto/fundo (normal e selecionado) e confere que o CSS usa os tokens, para
não voltar a ter cópia à mão.

Verificado com captura e `tools/pixel.py`: lateral e cartão normal em preto,
ativo em verde escuro e hover em cinza-escuro, nome do ativo em branco e a
segunda linha em verde claro; no dia, 15,9:1 no nome e 6,1:1 na informação.

### P14 — Largura da lateral não fica fixa — **feito**

`SIDEBAR_W` é 170, mas medido numa captura do P13 a lateral abria com **234 px**
e a barra de abas começava em x=234. `set_size_request` é mínimo, não largura:
o texto do cartão (`1 workspace`, título da aba ativa) é que dava a largura.

Duas propriedades do `Gtk.Label` atrapalham, e são diferentes:

- **o mínimo** — um `Label` sem `ellipsize` publica a largura do texto como
  mínimo, e a `ListBox` cresce junto;
- **o natural** — corrigido o mínimo (só `ellipsize`), o `pack_start` com
  `expand=False` ainda entrega ao filho a largura *natural*, que continua sendo
  a do texto: medido 454 px de lateral, 22 colunas de grade.

A receita que fecha os dois: `ellipsize(END)` + `max_width_chars(1)` +
`set_single_line_mode(True)` e `pack_start(label, False, True, 0)` (o `fill`
faz o rótulo ocupar os 170 px e truncar dentro deles).

O mesmo problema existia na **aba** do `Gtk.Notebook`, e aí era pior: o título
longo virava mínimo do notebook e a janela inteira esticava — medido 1062 px de
janela e 121 colunas de grade em vez de 680/51. `scrollable(True)` não resolve
(o mínimo continua vindo do rótulo). Fix: as mesmas três propriedades no rótulo
da aba, com `TAB_TITLE_CHARS = 20` (largura em chars porque a aba é medida em
chars; já a lateral é px, e é ela que não pode depender da fonte).

O texto inteiro foi para tooltip (cartão e aba): truncar sem tooltip esconde
informação.

Verificação (e a razão de existir como item): um `while` alternando
`printf '\033]2;curto\007'` com um título de 60 chars fazia a grade oscilar
entre **73 e 121 colunas** — 48 colunas de resize, SIGWINCH e reflow a cada
troca — e a janela crescia para 1062 px. Depois: `cols` constante em 51 nos
dumps de SIGUSR1 e janela em 680, com o título longo truncado em "…" no cartão
e na aba (fronteira da lateral medida por pixel em x=170, mouse fora dela para
o `:hover` não enganar a amostra).

De quebra, `Pango` entrou no `gui.py` (ponto único de import) e o `Entry` de
renomear ganhou `width_chars(6)` — ele também publicava largura.

### P15 — Tela do `pi` estabilizava bagunçada — **feito**

Relato: abrir o `pi` no bzmux, esperar a subida, e a tela parar incoerente (no
kitty ficava certa). O que se via: os blocos de aviso do startup com a linha de
status e a barra `bh/P/X` *no meio deles*, bordas repetidas e linhas em branco
entre uma linha e outra — layout "dobrado".

Causa: **o `\r\n` depois de uma linha que enche a largura avançava DUAS linhas.**
Em `put()`, a quebra pendente (`wrap_pending`, a que marca "esta linha cheia
continua na de baixo") era executada ANTES do tratamento de `\r`, `\n`, `\b` e
`\t`; então o `\r\n` pagava a quebra pendente + o próprio LF. App que preenche
a linha inteira até o fim — pi renderiza com padding até a última coluna, como
todo renderizador Ink — crescia uma linha por linha, a tela rolava sem parar e
o conteúdo se sobrepunha.

Fix: controle primeiro, quebra depois. `\r`/`\n`/`\b`/`\t` zeram
`wrap_pending` e só então fazem o que fazem; a quebra pendente continua valendo
para texto (aí sim a linha quebra). Check novo: `wrap_and_control`.

Verificação (foi o que fechou o diagnóstico, depois de duas tentativas erradas):
com `PYTERM_RAWLOG` gravou-se a saída do `pi` e ela foi reproduzida no `Term` sem
display — a bagunça aparecia igual. Comparada com um emulador de referência
(`uv pip install pyte`, temporário), a nossa grade passou de **38 linhas
diferentes em 45** para **0**, com o mesmo cursor e zero scrollback espúrio.
Depois, ao vivo: janela de 140x45, `pi` renderizado igual ao kitty.

Duas pistas falsas, registradas porque custaram tempo: (1) faltar resposta às
consultas `CSI 16t` e `OSC 10/11/4` *não* era a causa — implementar as respostas
não mudou o layout; (2) rodar os dois terminais ao mesmo tempo contamina a
medição e a comparação visual. O que resolveu foi replay determinístico contra
referência, não screenshot de screenshot.

### P16 — Doom fire como carga de medição — **feito**

`tools/doomfire.py`: o efeito do port de PSX do Doom (buffer 0..36 propagado de
baixo para cima com decaimento, paleta de 37 tons) em meio-bloco, com fg e bg
truecolor **por célula**, sem agrupar nada — o pior caso para o parser e para o
desenho, sem depender de app real. `--fps 0` solta a mão: quem limita passa a
ser o terminal, e o fps alcançado é a medida de vazão dele.

Medido, mesma grade de 68 colunas (68×20, a padrão desde o P17), `--fps 0`,
terminais um de cada vez:

| | fps | MB/s de escapes |
|---|---|---|
| bzmux | 11,8 | 0,6 |
| kitty | 314,2 | 15,9 |

Essa é a medição da época do P16, com o desenho do cairo. Depois vieram o P9
(Pango), a fonte em pontos (13 pt → grade 70×21) e o bug 13 (que só então passou
a desenhar na resolução da tela); o número vivo está no
[BENCHMARKS.md](BENCHMARKS.md).

O `PYTERM_PROF=1` decompõe o tempo no bzmux: **parse 61%** (4,3 ms por leitura)
e **desenho 37%** (12,8 ms por frame de 1360 células, ~29 draws/s). O desenho custa caro aqui não pelo número de células, e
sim pelo número de *runs* de cor: com 37 tons por linha quase toda célula é um
run próprio, e o custo por célula sai ~11 µs, contra ~1 µs do caso uniforme que
o README mede. É a linha de base do P9 (Pango muda exatamente esse custo).

A primeira medição (24,6 fps / 1,0 MB/s) era inválida: foi feita com a tela
congelada pelo bug 12, ou seja, medindo só o parse. Registro mantido porque a
lição vale: número de vazão sem conferir que a tela está mudando não mede
desenho.

Duas armadilhas do próprio script, que só apareceram rodando dentro do bzmux:
sem `SGR 0` na saída as estatísticas herdam a última cor do fogo (texto com
fundo amarelo), e SIGTERM no meio deixava a tela no alt-screen — agora tem
handler e o `finally` restaura pincel, cursor e tela. O handler também permite
medir com `timeout -s TERM 20`, que é como as medições rápidas são feitas.

### P17 — Lateral aparece com um workspace só — **feito**

Com **um** workspace a lateral já aparecia (170 px), embora `new_workspace()`
chame `set_visible(len(workspaces) > 1)`. Quem mostrava era o `show_all()` da
janela: ele mostra todos os descendentes, inclusive a `ListBox` que tinha sido
escondida antes. Custo medido: a grade caía de 68 para 51 colunas na janela
padrão (680 px).

Fix: `sidebar.set_no_show_all(True)` — o `show_all()` passa a ignorar a lateral
e quem manda na visibilidade é só o nosso `set_visible`. Verificado por pixel
(ponto da lateral preto/ocupado com 2+ workspaces, sem lateral com 1) e pelo
dump (`68x20` com um workspace, `51x20` com dois).

### P18 — Teclas dobradas dentro do `pi` — **feito**

Sintoma: digitando no `pi` cada tecla entrava duas vezes; shell, `vim` e `mc`
normais. Só o `pi` liga o protocolo de teclado do kitty com `CSI > 7 u`, isto é,
com a flag **2 = report event types**: o app passa a receber press, repeat e
release.

Causa: o release não tem forma no caminho legado (lá "a tecla saiu" é só mandar
o byte de novo, o que seria um segundo press), mas o `encode` devolvia `None`
para os casos em que o legado "já faz certo" — texto puro, seta sem
modificador. `None` significa *use o legado* em `encode_key`, então o release
caía lá e reenviava o texto. `a` saía no press e de novo no release.

Fix: a regra ficou num lugar só, `kitty_kbd.encode` — com a flag 2 e release,
ou sai a sequência do kitty, ou sai `""` (nada); nunca `None`. `encode_key`
segue sem saber de release, e o caminho legado não muda para press nem repeat
(repeat continua reenviando o byte, que é o certo: no legado repetição *é* um
press novo).

Verificação: check no `kitty_keyboard` (com flags=7, `a` no press e `""` no
release) e ao vivo no `pi` — digitar `abcabc` e ler a linha de entrada: sai
`abcabc`, não `aabbcc…`.

### P20 — Fast path de escape no parser — **feito**

Motivo medido: 35 µs/célula de parse no frame do doom-fire, e 91% disso era o
fechamento do CSI (`split`/`int`, listas de params, `sgr` com `flatten`). O
gargalo não era iterar caracteres: era o custo fixo de fechar e interpretar
cada escape (~1 µs por byte de escape).

Fix: em `Term.feed`, no estado `ground`, consumir o prefixo que o caminho rápido
entende — texto imprimível em bloco (um `slice` na linha) e
`CSI 38;2;r;g;b m`/`48;2;...m` resolvido por `dict[escape] -> cor` — e devolver
o resto ao parser de sempre, que ficou intacto como fallback e é dono de todos
os estados: escape fora do padrão (`38;5;N`, `:`, intermediários, `\x1b[H`) cai
nele.

Verificação: teste diferencial contra o parser do commit anterior (14 entradas:
frame do doom-fire, SGR 4-bit/256/truecolor, `:` sub, charset, `ED`/`EL`, OSC,
RGB fora de 0–255, inverse) comparando grade, cursor, cores, flags, wrap
pendente, estado e scrollback — 0 divergências.

No dia: micro 32,0 → 5,49 µs/célula (5,8x; texto puro 4,7x); com
`PYTERM_NODRAW=1`, 17,2 → 85 fps e 1,0 → 4,8 MB/s; `dmesg` real sem cor 168,3 →
45,7 ms. Com cor o ganho é menor: os SGR do `dmesg` não são truecolor e caem no
parser lento — foi o que virou o P22. O número com desenho parecia anômalo e era
o governor `powersave`. Leitura corrente: BENCHMARKS.md.

### P21 — Linha em branco compartilhada no scroll — **feito**

Motivo: o `scroll_up` custa 13,7 µs por linha. A hipótese inicial era o
`pop(0)` do `scrollback` com teto de 1000 — **errada**: medido com scrollback de
0, 500 e 1000 linhas, o custo foi 13,64 / 13,81 / 13,69 µs, ou seja o deslocamento
da lista não aparece. O caro era criar a linha em branco: `_blank_row()` alocava
70 listas de célula, 11,5 dos 13,7 µs. `deque` no `scrollback` não renderia nada
e ainda quebraria as fatias do reflow.

Fix: uma célula em branco `_BLANK_CELL` de módulo, compartilhada —
`_blank_row()` vira `[_BLANK_CELL] * cols` e `_blank_cell_raw()` devolve a mesma
lista. Só é seguro porque **nada muta célula in-place**: escrita sempre substitui
(`row[x] = [ch, fg, bg, fl]`), `erase_*` cria célula com o bg corrente
(`blank_cell()`, que continua alocando) e reflow/resize só leem e substituem.
Limpou de passagem uma expressão morta em `_blank_row`
(`self.bg if False else DEF_BG`).

Verificação: check em `wrap_and_control` (duas células em branco são o mesmo
objeto e escrever numa não muda a outra — mutação in-place pintaria a tela
inteira), diferencial contra o parser anterior nos 14 casos (0 divergências) e
`./run-tests.sh` (17 checks).

Ganho: scroll 13,7 → 3,27 µs/linha (4,2x); rolagem de 20000 linhas 38,4 →
10,9 µs/linha (3,5x, o caso `cat` de log grande); no doom-fire 85,0 → 86,6 fps,
porque ali o parse já era pequeno e a rolagem é 21 linhas por frame. O gargalo
de vazão segue sendo o desenho.

### P22 — Cache de parâmetros de CSI — **feito**

Motivo: o P20 só acelerou o SGR truecolor. Log com cor (o `dmesg` do sistema:
5172 escapes de `1`/`4`/`31`/`0`) ganhava 2,0x e não 3,7x, porque esses escapes
caíam no parser lento inteiro (`csi += ch`, `split`/`strip`/`int`, listas
`parts`+`nums`) — e ainda pagavam o `find`/`slice` do `_sgr_fast` antes de cair
lá.

Fix: `_csi_parse(body, final) -> (nums, prefixo)` e cache módulo-level
`(corpo, final) -> resultado`, teto de 1024. O `_csi_fast` casa o CSI inteiro no
buffer com `\x1b\[([0-9;:?]*)([\x40-\x7e])` e aplica pelo cache; o parser lento
continua dono da gramática e recebe o que o regex não casa (CSI partido entre
dois feeds, intermediário `0x20-0x2f`, dígito Unicode).

Consequências: `csi_dispatch` passa a receber **tupla** (imutável — seguro para
cache), então `params == [6]` virou `params == (6,)`; e `sgr` só aloca a lista
`flat` quando existe subparâmetro com `:` (antes alocava em todo SGR).

Tentativa descartada, com número: prefix check no `_sgr_fast` (para não fazer
`find`/`slice` em escape não-truecolor) com indexação de char cortava 5% no
`dmesg` com cor e custava **18% no doom-fire** (5,46 → 6,47 µs/célula); com
`startswith` empatava. Revertido — truecolor é o caminho que importa no
benchmark.

Verificação: diferencial contra o parser anterior nos 14 casos (0 divergências)
e `./run-tests.sh` (17 checks).

Ganho: `dmesg` sem cor 164,1 → 42,6 ms (3,8x); com `--color=always` 188,5 →
78,6 ms (**2,4x**, contra 2,0x antes do P22). No doom-fire nada muda (5,46
µs/célula) — lá o truecolor já era fast path. App com `PYTERM_NODRAW=1`: 86,5
fps / 4,9 MB/s.

### P23 — Atalhos de workspace com `Super` (2026-10-27)

Pedido: `Super+1`…`9` troca de workspace, `Super+N` cria e `Super+Q` encerra a
workspace corrente (com todas as abas dela). Os três comportamentos já existiam
em `Ctrl+Shift`, então foi alias, não lógica nova: `handle_shortcut` passou a
ler `SUPER_MASK` e um ramo `super and not ctrl and not alt` reusa
`new_workspace` / `close_workspace` / `select_workspace_index`. O dígito
continua vindo de `_digit_of(ev)` (traduz o keycode cru, então funciona em
ABNT2), e o `Ctrl+Shift+*` fica intacto.

**Bug que apareceu no teste:** `select_workspace_index` devolve `False` quando
o índice não existe, e o `return` repassava esse `False` — a tecla caía no
encoder e ia para o filho. Como `Super+2` chega como texto puro (`2`, sem
`Ctrl`), o dígito era **digitado no shell** (cursor 10,2 → 11,2 no dump). Fix:
consumir a tecla (`return True`) quando o keycode é dígito de workspace, mesmo
que não haja workspace naquele índice. O mesmo valia para `Ctrl+Shift+9` com
nove workspaces (vazava um `CSI` para o app).

Verificação (manual, com display — `Gdk` fica fora dos checks por design):
`xtest.py key super+n` cria o segundo workspace; `super+1`/`super+2` alternam
(dump com o ws corrente e a contagem de abas); `super+q` fecha o ws com 3 abas
de uma vez e os filhos morrem (contagem de `bash --norc` cai); a lateral
desaparece com um workspace só; `ctrl+shift+n` continua criando. O WM daqui não
tem grab em `Super+1`…`9`/`N`/`Q` (o `xtest` injeta no servidor e passaria pelo
grab), mas fica a nota no README: se o dash do GNOME capturar, use a variante
`Ctrl+Shift`.

### P24/P25 — Desenho: cor em float e `show_layout_line` (2026-10-27)

Motivo medido: com o parser resolvido (P20–P22), o desenho virou a maior fatia
depois dele (34% do tempo), com 4 chamadas de contexto e 2 conversões de cor por
run em ~1323 runs por draw. Duas delas não tinham motivo para custar o que
custavam.

Fix, sem mudança de aparência (a grade sai pixel a pixel igual): a cor passou a
vir cacheada em float 0..1 (`palette.cell_rgb_f`), tuplas compartilhadas, e como
a mesma cor devolve a mesma tupla dá para pular o `set_source_rgb` comparando
por identidade — o que também ataca o caso de app monocromático, onde a cor se
repete. E o cache de layout guarda a linha, desenhando com
`PangoCairo.show_layout_line` em vez de `show_layout` (-17% no micro).

Verificação: a bateria não cobre desenho (precisa de display), então a
fidelidade foi conferida por captura em `Xvfb :99` do código novo contra o HEAD
— 0 pixel de diferença na grade (os 448 que sobram são o título da aba, que
mudou de nome). No dia, `draw` 7,76 → 6,54 ms/call (-16%) e 110,7 → 116,0 fps
(+4,8%, coerente com desenho ser 34% do tempo). Decomposição por seção:
BENCHMARKS.md.

### P31 — Pacote instalável: `pipx install` direto do GitHub (2026-10-28)

O app era `bzmux.py` solto na raiz importando `core/`: rodava, não instalava. Sem
`[project.scripts]` o `pipx`/`uv tool` recusava, e o `uv build` **não falhava** —
caía num setuptools legado e gerava um wheel com `top_level = core` (nome
genérico, colisão no site-packages) e sem o script dentro. Daí o critério de
aceite ter virado inspecionar o wheel, não "buildou".

- `core/` → `bzmux/`, com `bzmux/__main__.py` no lugar do script da raiz (que
  ficaria sombreado pelo diretório homônimo).
- O entry point é uma função **sem** argumentos (`cli.run`): o `console_scripts`
  chama sem argv, e `main(argv)` exigiria a lista e estouraria `TypeError` no
  comando instalado. `main` continua aceitando argv porque os checks dependem.
- A guarda do `gi` só captura `ModuleNotFoundError` de `gi`/`cairo`: erro de
  import nosso continua estourando, e sem PyGObject a saída é uma mensagem de
  duas linhas em vez de traceback.

O que o `git+…` instala é o commit, não a árvore de trabalho — descobrir isso
custou uma rodada falhando com o HEAD antigo. `install.sh` embrulha o resto
(deps da distro, o `python3` que importa `gi` e `cairo`, pipx, `--selftest`), e o
pipe autenticado é `gh api …/contents/install.sh | bash` porque repositório
privado faz o `raw.githubusercontent` responder 404.

Armadilhas do pipx (o venv nasce com o python do próprio pipx; `--force` e
`reinstall` ignoram `--python`) e os dois bugs de shell do `install.sh` estão em
[DEBUG.md](DEBUG.md).

Verificado pelo wheel (pacote + `entry_points.txt` + LICENSE, sem `core/`),
`python3 -m bzmux --selftest` e `-h` sem `gi`, venv isolado mostrando a mensagem
do `gi`, e `pipx install --system-site-packages` do repositório abrindo e fechando
a janela com `--quit-after 2`.

### P28 — Seleção com o mouse: clique de 1 char e âncora no scroll (2026-10-29)

Dois sintomas com a mesma raiz: a seleção vivia em coordenadas de **tela**
(`y` de `visible_rows()`), não de conteúdo.

1. Clicar numa célula (sem arrastar) criava `sel_start = sel_end` e o release
   copiava isso para o PRIMARY — um clique qualquer sobrescrevia a seleção do
   usuário com 1 caractere e estragava o "colar com o botão do meio".
2. Rolar o histórico mantinha o destaque na mesma linha física, agora por cima
   de **outro** texto; o `copy()` seguinte usava `view_off` novo e copiava o
   texto errado.

Fix (opção B, decidida no item): `scroll_view()` desfaz a seleção quando
`view_off` muda — e o ajuste automático de `view_off` no `on_pty` (saída nova
com histórico aberto) faz o mesmo. A seleção passou a nascer no **arrasto**:
`on_button_press` só guarda a célula e o pixel do press, e `clear_selection()`
limpa a anterior; `on_motion` cria a âncora quando o ponteiro anda mais de
`DRAG_SLOP = 3` px; `on_button_release` copia para o PRIMARY **só** quando houve
arrasto para outra célula. Selecionar histórico com o mouse deixou de ser
possível (o press chama `back_to_live()`) — consequência aceita da opção B.

Bug no caminho: a primeira versão não tinha folga de arrasto. Segurar o botão
sem mover fechava uma seleção de 1 célula, porque o Gtk entrega `motion` com o
botão apertado por qualquer tremidinha. Foi o usuário que viu, testando à mão.
A folga é medida em **pixels** (3), não em células: `cell_at` já arredonda, e
1 célula é larga demais (14 px) para separar clique de arrasto.

Verificação: manual, com display — clique-segura-solta em `cat -v` (nenhum
reverso na tela, `xclip -o -selection primary` inalterado), arrasto curto
(seleção + PRIMARY), wheel com seleção viva (destaque some) e arrasto novo
depois do wheel (seleciona o texto certo). `selection_text` puro continua
coberto em `checks.py`. A bateria não cobre o estado da view (precisa de Gtk).

A opção B foi desfeita pelo B17 (bug 17): a seleção passou a ser ancorada no
conteúdo, então rolar não desfaz mais o destaque.

### P29 — `Alt` não prefixava `ESC` nas teclas especiais (2026-10-29)

`Alt+Backspace` apagava **1 caractere** em vez de uma palavra no `zsh`, e o
mesmo valia para `Alt+Tab`, `Alt+setas`, `Alt+Home/End`, `Alt+F1..F12` e
`Ctrl+Alt+letra`. Causa: em `encode_key()` o ramo `kv in SIMPLE` devolvia a
sequência **sem olhar o `alt`** — o prefixo `ESC` só existia no ramo dos
imprimíveis e das dead keys.

Fix genérico, no formato do xterm (não um `if` para o Backspace):

- teclas de controle (`\r`, `\x7f`, `\t`, ESC) ganham prefixo `ESC` quando há
  `Alt` — `Alt+Backspace` = `\x1b\x7f` (`^[^?`, o `backward-kill-word` do zsh);
- teclas que já são CSI/SS3 levam o modificador como **parâmetro**
  (`\e[1;3A` em `Alt+Up`, `\e[3;3~` em `Alt+Delete`, `\e[15;3~` em
  `Alt+F5`, `\e[1;3P` em `Alt+F1`), com `_mod_param` = 1 + shift(1) +
  alt(2) + ctrl(4);
- `Ctrl+Alt+letra` = `ESC` + o caractere de controle;
- preservados: `Shift+Tab` = `\e[Z` (com Alt vira `\e[1;3Z`) e DECCKM
  (`\eOA` continua para seta sem modificador, `\e[1;3A` com Alt);
- `Ctrl+Backspace` (sem Alt) continua `\x7f`: só `Alt` prefixa `ESC` nas
  teclas de controle.

Verificação: tabela de 16 casos (`Alt+Backspace`, `Backspace`, `Ctrl+Backspace`,
`Alt+Tab`, `Shift+Tab`, `Alt+Shift+Tab`, `Alt+Up`, `Ctrl+Up`, `Up`,
`Alt+Delete`, `Alt+F1`, `Alt+F5`, `Ctrl+Alt+a`, `Alt+a`, `Alt+Escape`,
`Alt+Return`) conferida contra o esperado do xterm, e `Alt+Backspace` testado
no app pelo usuário (funcionou). `keys.py` fica fora do `--selftest` por
depender das constantes do Gdk; a tabela foi conferida à mão com `gi` e não
virou check.

Quirk de X11 registrado no caminho: injetar teclas com `xdotool key alt+F1` é
armadilha — no MATE isso é o atalho do **menu do painel**, e sem foco na janela
certa a tecla abre menu de sistema em vez de testar o app. Teste de teclado
manual: `tools/xtest.py key ...` (fixa o foco por `_NET_WM_PID`) e evitar as
combinações de `Mod1` que o WM usa.

### P19 — `pi` "reescrevia várias telas" durante o turno (2026-10-29)

Sintoma: a cada algumas etapas do turno dentro do `pi`, a tela dava um salto de
várias telas. **Não era o parser.** Três turnos reais replayados em `Term` e em
`pyte`: tela final idêntica, rolagens iguais (32×32, 79×79) e quebra preguiçosa
correta (linha de exatamente 137 colunas + `\r\r\n` consome 1 linha, não 2) — o
`pi` não usa DECSTBM (`CSI r`), IL/DL (`CSI L/M`), SU/SD (`CSI S/T`) nem
autowrap-off (`?7l`).

O que o stream tem (1163 entradas de scroll, 12 MB preservados em
`~/dados/temp/p19-evidence-2026-10-29/`): ~10 mil repaints, **cada um dentro de
uma transação `?2026`** (synchronized output), e **99% das leituras do pty
terminam no meio de uma transação** (19058 de 19182 leituras de 4095 B). Como o
app ignorava `?2026`, todo desenho caía com a tela meio-repintada: o scroll
existia de verdade (o `pi` sobe 4 linhas com `CSI 4A` e escreve ~13 por repaint,
terminando cada uma com `\r\r\n`), mas ninguém devia ver o caminho.

Feito:

- `?2026` honrado — `Term.sync_output` e o desenho adiado até o fecho da
  transação, com teto de 200 ms para app que esquece de fechar (a tela não
  congela; o estado parcial é desenhado uma vez);
- dois erros de resposta achados na comparação com o kitty: DA2 (`CSI > c`)
  respondia no formato do **DA1** (`\e[?62c`), deixando o app sem saber com quem
  falava; e DECRQM (`CSI ? Ps $ p`) não era respondido porque o parser
  descartava o intermediário — agora responde 1/2/0 para os modos que existem
  (inclusive `?2026`).

Verificação: desenhos no meio de transação caíram de "praticamente todos" para
**0** (app instrumentado por fora, gerador de 120 repaints: 91 desenhos, 0 no
meio, 0 estouro do teto); vazão do doom-fire intacta (112 fps full, 161 NODRAW,
512 IO); suíte 19 checks + 19 pytest OK. No uso real o enchimento de 1000 linhas
na abertura deixou de "subir em pedaços" (conferido pelo usuário, já com o
build novo — PID iniciado depois do commit `f918dbe`).

Se o salto voltar, a conta é do `pi`: ele escreve mais linhas do que sobe em
cada repaint, então a rolagem acontece em qualquer terminal fiel (o `pyte` rola
igual). O suspeito seguinte é widget do rodapé mudando de altura no meio do
turno.

### P32 — O histórico não segurava quem estava lendo (2026-10-29)

Sintoma: lendo o histórico enquanto o `pi` escrevia devagar, a visão voltava
sozinha para o rodapé a cada linha.

Causa: `view.py` voltava ao vivo em três casos — tecla, rolar até o fim e
"qualquer output que mude o conteúdo da tela visível". O terceiro nasceu no bug
14 para o tique de 1 Hz do `pi` e passou a cobrar o preço no uso normal: a conta
por offset e scrollback segurava a posição, mas o `if` da assinatura rodava
antes.

Fix: âncora absoluta, sem heurística de conteúdo. `Term.anchored_view_off` mede
a distância entre a linha que estava no topo e o fim, e o usuário só sai do
histórico por ação dele: rolar até o fim, uma tecla de verdade, ou a âncora ser
destruída (limpeza com `CSI 3J`). Sai o `_view_signature()`, que montava uma
string de todas as células visíveis a cada chunk justamente enquanto se lia; de
graça, a âncora cobre também o tique de 1 Hz, o teto de 1000 linhas e a seleção.

Descartados: retorno por 5 s de inatividade de scroll (ler é silencioso, e um
app que escreve a cada 1 s arranca o usuário quando o prazo vence) e sticky
bottom (voltar a ≤1 linha do fim); os dois em LIMITATIONS.md.

Verificado: check `scroll_anchor` sem display, inclusive o caso do teto com a
deriva de 10 linhas; no app real, rolar 25 linhas com o gerador escrevendo
devagar manteve a mesma linha no topo e a seleção viva, o tique não mexeu no
offset e uma tecla voltou ao vivo (confirmado no uso).

### P34 — Configuração v2: as oito opções comuns (2026-10-31)

O v1 (P33) já tinha parse, merge, validação, reload e toast; aqui entraram as
chaves e o uso de cada uma: `font_family` (Monospace), `font_size` (12 pontos,
era 13 fixo no código), `cursor_shape`, `cursor_blink` (off), `scrollback`
(1000), `window_padding_width` (0), `bell` (none/visual/audible — BEL era
ignorado) e `copy_on_select` (off). O que é quente (fonte, padding, cursor) vale
nas abas abertas; `shell` só na próxima.

- Pisca é um `GLib.timeout_add(530)` que invalida só a célula do cursor, e só na
  view visível (unmap remove o timer, map religa): N abas, 1 timer. Dois draws
  inteiros por segundo seriam caros e o dirty-rect é o P27.
- `DECSCUSR` (`CSI 6 q`) vence a config enquanto durar, como no kitty.
- Padding é translação no draw, e o resto de sub-célula desconta `2*padding` —
  sem isso a última coluna pintava sobre a margem.
- Duas armadilhas de implementação ficaram no [DEBUG.md](DEBUG.md): `queue_resize`
  que não re-aloca com fonte nova e `lista[-0:]`, que é a lista inteira.

Erro passou a ser por linha, revisto no mesmo dia a pedido: a carga inicial aplica
o que validou (a chave inválida fica no padrão) e um toast mostra o primeiro erro
com `(+N)`; o reload continua tudo-ou-nada e mantém a configuração que estava
valendo. O toast só aparece quando há erro.

Bugs do caminho: o flash do `bell` só cobriu a aba inteira depois de mover o
padding do nó `tab` para o rótulo — e `background-color` sozinho não pintava sem
`background-image: none`. As duas são armadilhas de GTK3, no [DEBUG.md](DEBUG.md).

Verificado pelos checks `config_options` e `scrollback_and_bell` e à mão: 12
pontos dá célula 13×27 e 75×22, trocar a família re-mediu (13×26, 75×23), padding
20 conferido pixel a pixel com o mouse acertando a coluna, as três formas de
cursor e o pisca por captura, `copy_on_select` no CLIPBOARD e `scrollback 5`
deixando 5 linhas.

## Bugs encontrados e corrigidos (histórico útil)

Todos foram achados com medição, não por leitura — vale registrar o método.

1. **Métrica de célula errada (texto derrapando).** A largura da célula vinha
   de `text_extents("M").width` (680/75 ≈ 9,06 px) e o avanço real da fonte era
   maior, então as colunas desalinhavam e o texto sobrepunha. Fix: largura =
   `ceil(x_advance)`, altura = `ceil(ascent + descent)`.
2. **`resize` apagava a tela.** O `Term.resize` recriava a grade em branco; se
   o configure chegasse depois do primeiro output, o texto sumia. Fix: preserva
   recortando/preenchendo.
3. **`configure-event` não aplicava o resize.** O sinal do `GtkWindow` chega
   **antes** de o filho ser re-alocado, então `get_allocation()` devolvia o
   tamanho antigo e o `mc` ficava com layout quebrado. Fix: `size-allocate` na
   `DrawingArea`, usando a alocação recebida.
4. **Setas ignoradas no `mc`.** `mc`/`vim`/`less` ligam `DECCKM` (`?1`) e
   passam a esperar `\EOA`..`\EOD` (modo aplicação do terminfo de xterm); eu
   mandava sempre `\E[A`. Fix: rastrear `?1` e trocar a forma das setas,
   Home e End.
5. **Modificadores viravam caractere ("caixinha").** `Shift_L`, `Control_L`,
   `Alt_L`, `Super_L`, `Caps_Lock`, `Menu` têm keyval em `0xff00–0xffff`, e o
   fallback fazia `chr(kv)` → caractere sem glifo. Fix: só envia caractere
   imprimível (latin-1 `0x20–0x7e`/`0xa0–0xff` ou unicode `0x01000000+U`).
6. **Dead keys não faziam nada.** Fix: guarda a marca e compõe por NFC
   (`~`+`a` → `ã`); dead key + espaço emite o isolado (`~`, `^`, `` ` ``...).
7. **Rodapé preto embaixo de app com fundo colorido.** O fundo de cada run
   era pintado com altura `ch` e largura `(j-x)*cw`, então a sobra sub-célula
   da janela (quase nunca `altura % ch == 0`, aqui 520 − 27×19 = 7 px) ficava
   com o fundo default. Com `vim` + `termguicolors` (`guibg=#123456`) isso
   aparecia como uma tarja preta no pé da tela. Fix: a faixa que sobra herda o
   fundo da **última fileira** (e a da direita, da última coluna) — medido por
   captura: `y=512..519` virou `(18,52,86)`. Sem app colorido nada muda, porque
   a última fileira tem células de fundo default.
8. **`DA` nunca respondia.** `CSI c` sem parâmetros virava `[0]` no parser e a
   condição `not params` falhava. Fix: corpo vazio → lista vazia.
9. **Abas/workspaces: seis armadilhas silenciosas do GTK** — página nova oculta
   com `set_current_page` ignorado, `grab_focus` em `switch-page`, `sh -c` sem
   exec (cwd no neto), `EventBox` sem máscara, `set_tab_label_text` trocando o
   widget do rótulo e `Gtk.Box` sem `reorder()`. As seis estão em
   [DEBUG.md](DEBUG.md), com o conserto.

10. **`--help` abria a janela.** `parse_args` ignorava em silêncio qualquer
    opção desconhecida, então `bzmux.py --help` (e `--nada`) caíam no fluxo
    normal e subiam o app. Fix: `-h`/`--help` é tratado antes do import de Gtk
    (imprime o uso, exit 0) e opção desconhecida — ou sem valor — virou erro de
    uso (uso no stderr, exit 2). `parse_args` passou a devolver também o erro, e
    o check `argv_parsing` cobre os dois caminhos.

11. **Renomear o workspace deixava a sessão surda.** O `Gtk.Entry` do nome é
    removido ao confirmar e leva o foco embora; nada o devolvia, então nem a
    digitação nem os atalhos chegavam a ninguém. Pior: os atalhos globais
    (`Ctrl+Shift+T/N/W/Q`, `Alt+N`) só existiam no `on_key` da `TermView` —
    bastava o foco sair da sessão (clique no cartão da lateral, `Entry` de
    renomear, barra de abas) e eles paravam de responder. Fix: `finish()` do
    rename devolve o foco pra view e a janela ganhou um `key-press-event`
    próprio chamando o mesmo `handle_shortcut` (a view trata primeiro e
    retorna `True`, então não há tratamento duplo).

12. **Tela congelava sob despejo contínuo.** O watch do pty estava em
    `GLib.PRIORITY_DEFAULT` (0) e o redraw do GDK roda em `GDK_PRIORITY_REDRAW`
    (120): com pty sempre pronto a leitura ganhava a disputa em toda iteração e
    o desenho nunca acontecia — a surface ficava com o último frame, para
    sempre, até o app parar de escrever. Foi visto com o doom-fire (P16): três
    capturas com 2 s de intervalo, pixels idênticos, enquanto o pty consumia
    0,3 MB/s. Fix: watch do pty em `PRIORITY_DEFAULT_IDLE` (200, abaixo do
    redraw) e desenho coalescido em ~16 ms (`request_draw`, 60 Hz) — sem o
    coalescimento eram dezenas de draws por frame e a vazão caía para 7,9 fps.
    Resultado: tela anima e vazão de 0,6 MB/s (11,8 fps a 68×20, medição com o
    desenho do cairo e antes do bug 13).

13. **Texto espremido e coluna errada depois da fonte em pontos.** A célula era
    medida com o contexto do widget (130 dpi na tela: 14×28 px) e o texto era
    desenhado por layouts criados a partir do `cr`, cujo contexto vem **sem
    resolução** (96 dpi): avanço de 10 px por caractere dentro de células de
    14. Resultado visível: run de N caracteres ocupando 71% da largura que a
    grade reserva (espaço entre palavras sumindo, box-drawing com fresta,
    linha de 70 `M` terminando em 700 px de 980) e wrap parecendo cair na
    coluna errada, porque quem quebra linha é a grade (70 colunas), não o
    desenho. Fix: `PangoCairo.context_set_resolution(ctx, dpi)` em **todo**
    layout (o do frame e os do cache de runs), com o DPI tirado do contexto do
    widget e, se vier vazio, de `Gdk.Screen.get_resolution()`. Medido depois:
    70 `M` ocupando 0..979 px, linha de 70 + 10 caracteres quebrando em 140 px
    na fileira de baixo (10 células exatas). O `PYTERM_DIAG=1` (abaixo) nasceu
    aqui: imprime avanço, célula, resolução e colunas no primeiro draw — foi o
    que separou "métrica errada" de "desenho com outra resolução".

14. **Histórico inutilizável dentro do `pi`: a visão voltava pro rodapé.** O
    `on_pty` devolvia a visão ao vivo em *qualquer* output ("o app está falando,
    o usuário não está lendo o histórico"), e o `pi` publica **a cada 1 segundo,
    para sempre**, 10 bytes invisíveis: `CSI 1 G` (cursor pra coluna 1) +
    `CSI ? 25 l` (esconde cursor). Capturado de um `pi` ocioso com um pty
    próprio respondendo como o bzmux (22 s, 24 tiques, 11,4 KB, 10 bytes por
    segundo exato). Nada muda na tela, mas cada tique zerava o `view_off` —
    rolar o histórico e voltar em 1 s. Fix: guardar a assinatura do que está
    visível (texto + fg + bg por célula) antes do `feed` e só voltar ao vivo se
    ela mudar; output invisível mantém a posição (e a visão anda junto com o
    scrollback, para não deslizar por baixo). Medido depois, com o mesmo tique
    de 1 s: duas capturas com 3,2 s de intervalo, **0 pixel de diferença** com a
    visão no histórico (antes voltava ao rodapé no primeiro tique); output de
    verdade continua trazendo pro vivo. Armadilha do teste: `tools/xtest.py`
    mexe no ponteiro real da sessão — não sair rodando à toa num display em uso.

15. **Rolar o histórico ficava mais lento quanto mais para cima.** Sintoma
    relatado no uso: wheel para cima ficava progressivamente pesado. Causa em
    `Term.visible_rows(off)`: `scrollback[-off:] + grid[:rows - off]` — com
    `off > rows` o segundo termo é `grid[:negativo]`, que devolve a grade
    **inteira** (ou vazia, quando o corte cai antes do começo), então o total
    saía `off + len(grid)` em vez de `rows`. O `_on_draw` percorre `len(rows)`,
    ou seja pintava `off` linhas — a maioria fora da tela, mas o Pango e o
    `fill` eram cobrados do mesmo jeito. Com scrollback de 1000 linhas e
    `off=1000`, 1000 linhas desenhadas em vez de 21 (~48x as células).
    Medido no app com `PYTERM_PROF` (as duas versões no mesmo estado de carga,
    3 corridas cada): `draw 10,72 / 10,97 / 10,99 ms/chamada` com a visão no
    topo, contra `1,67 / 1,63 / 1,65` depois do fix — 6,6x. Referência do vivo
    (`off=0`, 443 draws): `1,41 ms`, então o topo do histórico deixou de custar
    7,7x o vivo e passou a custar ~1,2x (o resíduo é o fatiamento O(off) de
    `visible_rows`, alguns µs). Fix: quando `off >= rows`, fatiar direto o
    scrollback (`sb[len(sb)-off : len(sb)-off+rows]`), senão o caminho antigo
    (que é correto). `visible_rows` sempre devolve exatamente `rows` linhas.
    Check de regressão no `history()` (0, 1, rows, rows+1, scrollback inteiro).
    Armadilha: o bug só aparece com `off > rows` — testar rolagem de 1 linha não
    pega. A primeira leitura foi feita com o notebook na bateria (10,52 → 1,78,
    5,9x); a de cima, na tomada. O sentido do ganho não mudou.

16. **Clicar para arrastar no histórico voltava pro vivo.** Relatado no uso:
    rolar pra cima e apertar o botão esquerdo para copiar um trecho antigo
    saltava para o rodapé já no press, então o arrasto selecionava texto de
    agora. Causa: `on_button_press` chamava `back_to_live()` **antes de qualquer
    ramo**, inclusive no botão 1 que só arma a seleção local. Fix: a visão fica
    onde está quando o press arma seleção (botão 1 sem `mouse_mode`) e volta ao
    vivo só onde o destino é o app — report de mouse (`mouse_mode`, cuja
    coordenada é do vivo) e paste do botão do meio. Verificado no app real com
    capturas: visão no topo (`1`), press+arrasto → continua no topo e o PRIMARY
    recebe `1008` (a linha do histórico sob o arrasto); com `?1000` ligado o
    clique volta ao vivo (`1183`), e o botão do meio também. Armadilha de
    manutenção: `scroll_view` chama `clear_selection`, então o `back_to_live`
    não pode reaparecer no `on_motion` (apagaria o arrasto em curso). Sem check
    automático — a decisão vive num handler de GTK e exige display; a bateria
    não cobre `view.py`.

17. **A seleção não acompanhava o scroll da tela.** `sel_start`/`sel_end`
    guardavam fileira e coluna da **tela**: rolar (`view_off`, wheel,
    `Shift+PgUp`) movia o texto e deixava o realce na mesma posição física,
    agora sobre outro texto — e o `copy` seguinte copiava o errado; a mitigação
    do P28 (desfazer a seleção ao rolar) só trocava "texto errado" por
    "seleção perdida". Fix: âncora absoluta (`Term.CellAnchor`, linha =
    `scrolled - view_off + row`), a mesma conta do P32 — o desenho volta à
    fileira de tela e o `copy` lê pela âncora, então seleção que saiu da tela
    continua valendo. A âncora carrega a geração do mapa (`Term.abs_gen`):
    `CSI 3J`, RIS, reflow e a troca de buffer do alt-screen a invalidam, o corte
    no teto do `scrollback` não. Verificado pelo check
    `selection_follows_history` (as duas ordens, output no teto de 1000, morte
    por `CSI 3J` e reflow) e com janela em display privado: realce 3 fileiras
    abaixo na captura e `Ctrl+Shift+C` devolvendo o texto certo depois do wheel.

18. **RIS devolvia o teto do histórico para 1000.** `Term.reset` recriava o
    `Term` inteiro (`__init__`) e levava junto o `scrollback_limit`, que é
    configuração e não estado do app: com `scrollback 5`, um `ESC c` do
    programa passava a guardar 1000 linhas. Fix: ler o valor antes do
    `__init__` e repor depois. Achado ao revisar o bug 17 (o `reset` mudou
    naquele fix); o check `scrollback_and_bell` agora manda `RIS` e confere que
    o teto sobrevive.

19. **O `$SHELL` do filho não era o shell que rodava.** O `sh -c` do pty herda
    o ambiente de quem abriu o bzmux, então `SHELL=/usr/bin/zsh` continuava no
    filho mesmo com `shell /bin/dash` na configuração (e o `dash` era quem
    executava). Fix: `config.effective_shell` resolve a cadeia config vazio ->
    `$SHELL` -> `/bin/bash` e devolve caminho; a view exporta esse valor como
    `SHELL` no filho. Verificado em `Xvfb` com `echo $SHELL` na sessão: vazio
    + `$SHELL=zsh` dá zsh, `shell /bin/dash` dá dash.

20. **Rolar o histórico e o repaint do app jogava a visão pro topo.** O `pi` em
    modo regular redesenha com `?2026h` + `2J H 3J` + o buffer inteiro: o `3J`
    zerava o histórico mas a âncora de rolagem continuava absoluta, então cada
    linha reescrita aumentava `scrolled - anchor` e o clamp em
    `len(scrollback)` escorava no topo da história nova. Fix: `Term.hist_gen`
    avisa a limpeza e a view troca a âncora por "distância do vivo"
    (`Term.pinned_view_off`), segurando até a distância voltar — quem rolou
    continua lendo, sem cair no topo nem no vivo. Verificado no check
    `redraw_keeps_history_position` (o caminho antigo dá o topo) e no app:
    `histórico +9` antes e depois do repaint.

## Nota de documentação: número só em um lugar

Até 2026-10-27 os números de vazão viviam repetidos em README, LIMITATIONS,
TASK e AGENTS, e a regra do AGENTS.md mandava atualizar todos juntos. Na prática
eles divergiram em toda re-medição (três rodadas de "0,5 → 0,6 → 3,4 MB/s" e
cópias esquecidas em 0,5). A regra mudou: **o valor mora só em BENCHMARKS.md**
(data + governor); os outros docs citam o fato e linkam. O README mantém a linha
do doom-fire na tabela comparativa (manchete) e o HISTORY registra o número do
dia em que fechou um item, como registro datado — não como leitura corrente.
Duas linhas obsoletas do README (parse+grade "0,7–1,9 MiB/s" e "desenho 1,2 ms")
saíram junto: eram de bancada antiga e agora contradiziam o BENCHMARKS.

## Armadilhas (saíram daqui)

As armadilhas de desenvolvimento, sessão gráfica e ferramentas ficavam nesta
seção; agora moram em [DEBUG.md](DEBUG.md) — arquivo curto, operacional, para
ser lido antes de rodar ferramenta. O que é número de medição continua em
[BENCHMARKS.md](BENCHMARKS.md). Este arquivo guarda só a narrativa datada.

## Git e origem do repositório

Nasceu no repositório do experimento `kitty`
(`~/dados/workflows/temp/kitty`), na pasta `pyterm/`, com o nome **pyterm**.
Em 2026-10-25 virou repositório próprio, `pybzmux`, com o nome **bzmux**. A
parte C/GTK ficou lá (ver README.md): não é compilada nem testada aqui.

Os commits até a separação vieram por `git subtree split`, que **reescreve
hashes**: os do repositório de origem não existem aqui nem no GitHub, e as
mensagens antigas ainda dizem `pyterm`. O `520447b` é a renomeação para
`bzmux`.

Histórico completo: `git log --oneline` (a lista de hashes não é mantida à
mão).
