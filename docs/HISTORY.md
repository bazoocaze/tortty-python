# bzmux — histórico

Memória do projeto: backlog concluído, bugs corrigidos, quirks e git.
Não é tarefa. Pendências: [BACKLOG.md](BACKLOG.md). O que não é feito e por quê:
[LIMITATIONS.md](LIMITATIONS.md). Status, escopo, arquitetura, medições e
como testar: [../TASK-bzmux.md](../TASK-bzmux.md).
Convenções: [../AGENTS.md](../AGENTS.md).

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

`core/graphics.py` (parse/decodificação/placements, sem cairo) +
desenho na `TermView` (era `window.py`; o P11 separou em `view.py`). Parse do
APC (`ESC _ G ... ESC \`) no parser do `Term`, com estado `apc`/`apc-esc`.

- Ações: `a=t` (transmitir), `a=T` (transmitir e mostrar), `a=p` (mostrar),
  `a=d` (apagar: `d=i,i=<id>` ou `d=A`), `a=q` (sonda).
- Formatos: `f=24` (RGB), `f=32` (RGBA) e `f=100` (PNG, com tamanho lido do
  IHDR); imagem em pedaços com `m=1`; `i` (id), `c`/`r` (tamanho em células),
  `C=1` (não mexer o cursor), `q` (silêncio), `o=z` (payload zlib — é o que o
  `icat --place` manda depois de escalar sozinho) e `X=`/`Y=` (offset em
  pixels dentro da célula, como o `icat` centraliza).
- Desenho: `ImageSurface` do cairo em cache por id; RGB/RGBA passam por troca
  de canais (o ARGB32 do cairo é BGRA) e o `bytearray` fica vivo porque o
  `create_for_data` **não copia**. Imagens sobem junto com o scroll.
- **Histórico**: a colocação guarda a linha da GRADE e pode ficar negativa
  quando a imagem sai pelo topo (`graphics.scroll(top, bottom, floor)`), indo
  para o scrollback. O desenho soma `view_off`, então `Shift+PgUp`/wheel
  mostram a imagem na posição certa; `drop_above()` poda o que saiu de vez do
  scrollback (as 1000 linhas mais antigas) e o reflow poda o que virou
  inalcançável. Limitação: a imagem não acompanha o reflow linha a linha (fica
  na linha de tela, como no kitty).

Bug/pegadinha que custou tempo: **`a=q` é sonda de capacidade, não consulta de
imagem**. Eu respondia `ENOENT` quando o id não existia, e o `kitten icat` usa
exatamente isso de handshake (manda três sondas — direto, arquivo, memória — e
só segue se receber `OK` na direta). Agora: `OK` quando o médium é `d` e o
formato é 24/32/100, `EINVAL` caso contrário. Outra: `m=1` não pode ser
acumulado no dicionário de controle — ele é do pedaço atual, e guardar o valor
fazia a transmissão nunca terminar.

Verificado: PNG 160x90 em 2 pedaços e RGBA cru 40x20 desenhados no lugar certo
(screenshot), rolagem acompanhando, e `kitten icat /tmp/t.png` real saindo com
código 0 e a imagem na tela. Depois, com a demo `/tmp/imgdemo/demo.sh` (PNG
opaco, gradiente 1px/coluna, RGBA translúcido, checker 4px com barras de 1px e
`--place 24x8@62x3`): as cinco imagens saem nos lugares certos e o mesmo script
roda igual no kitty de verdade.

Outro bug que só apareceu com imagem na tela: o `icat` manda `CSI * x`
(DECSACE) antes de desenhar; o parser CSI tratava `*` como byte final (ele só
aceitava params 0x30–0x3f) e o `x` caía no ground — aparecia um "x" solto na
tela, um por imagem. Fix: aceitar intermediários 0x20–0x2f no estado `csi`
(ECMA-48: params, intermediários, final) e descartá-los antes do dispatch.

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
árabe não ligava, marca combinante se separava do corpo da letra. Migrado para
**Pango**: um `Pango.Layout` por draw, reaproveitado em cada run, com
`PangoCairo.show_layout`.

Decisões que custaram teste:

- **`set_absolute_size` (pixels), não `set_size` (pontos)**: com `set_size` o
  Pango aplica o DPI 96 e a fonte muda de tamanho em relação ao cairo antigo.
- **Métricas saem do mesmo layout que desenha**: largura = avanço de "M",
  altura = `get_pixel_size()` do layout. Antes eram `text_extents`/`font_extents`
  do cairo; misturar as duas fontes de número desalinha a grade.
- **`move_to` na quina da célula e o layout desenha dali**: a linha de base sai
  do ascent do próprio layout, então não existe mais `+ ascent + 1` na mão.
- **Cache de layout por `(texto, negrito)`**, teto de 800 (limpa quando estoura):
  `set_text` é a parte cara, e run se repete muito. Sem o cache o desenho dobra
  de custo (ver números abaixo).
- Sublinhado continua sendo retângulo do cairo, não atributo do Pango: é o mesmo
  pixel em qualquer fonte e não depende de métrica de underline.

Medido com o doom-fire (P16), 68×20, `PYTERM_PROF=1`:

| desenho | ms/frame | fps | MB/s |
|---|---|---|---|
| `cairo.show_text` (antes) | 12,8 | 11,8 | 0,6 |
| Pango sem cache | 30,5 | 8,1 | 0,4 |
| Pango com cache de layout | 15,2–15,6 | 11,0 | 0,5 |

Estes três números foram medidos com o desenho ainda a 96 dpi (bug 13): servem
para comparar um com o outro, não com a linha de base de hoje (22,7 ms/frame,
8,2 fps em [BENCHMARKS.md](BENCHMARKS.md)).

Ou seja: shaping + fallback custam **~20% do frame** com cache, **2,4x** sem.
O parse não mudou (4,3 ms por leitura), como esperado — a migração é só desenho.

**Emenda: a fonte passou a ser em PONTOS (13 pt), sem flag.** O `font_size` veio
do `cairo.show_text`, onde "tamanho de fonte" é unidade de usuário (pixel); na
migração para Pango eu preservei isso com `set_absolute_size` para não mudar o
visual no meio da mudança. Mas todo terminal expõe pontos (kitty, alacritty,
GTK/fontconfig, xterm `-fs`), e o motivo é DPI: em tela com `Xft.dpi: 130`
(desta máquina) 13 pt = 23,5 px, contra os 16 px antigos — é por isso que o
"13" do kitty parecia maior que o "16" daqui. Agora usa `set_size` (pontos), e o
bzmux e o kitty dão a MESMA grade para a mesma janela (70×21 em 980×640).

Duas armadilhas dessa troca: (1) a métrica tem que sair do **contexto Pango do
próprio widget** (`self.get_pango_context()`), não de uma `ImageSurface` solta,
senão ponto→pixel usa resolução diferente da que desenha e a grade desalinha —
foi o que aconteceu na primeira tentativa (48 colunas em vez de 70); (2) a janela
padrão de 680×420 estava calibrada para a fonte de 16 px e passou a dar 48×14,
então virou 980×640.

### P10 — Fallback de fonte (emoji/CJK) — **feito**

Caiu junto com o P9: o fontconfig acha a fonte que tem o glifo, então CJK e
emoji em cor passam a desenhar sem nenhum código a mais. Verificado na tela com
`printf '\u4e2d\u6587 \U0001F600'` no bzmux.

Limite que fica (e não é bug do fallback): a grade **não tem `wcwidth`**, então
caractere largo ocupa uma célula só e o glifo é espremido/estourado nela. App que
conta coluna dupla (tabela em CJK) sai desalinhado; resolver isso é mexer no
modelo de célula, não no desenho.

### P11 — Abas — **feito**

`Ctrl+Shift+T` abre aba nova; `Alt+1` … `Alt+9` selecionam a aba N (`Alt+0` =
a 10ª); `Ctrl+Shift+W` fecha a aba; fechar a última fecha a janela.

Hoje o `BzmuxWindow` acumula tudo de uma sessão: `Term`, `master`/`child_pid`,
decoder, seleção (`sel_start`/`sel_end`/`_held`/`_state`), `view_off`,
`_img_cache`. O trabalho é extrair uma **`TermView(Gtk.DrawingArea)`** com esse
estado (é o mesmo recorte do `session.py` que a conversa de testes propôs) e
deixar a janela com um `Gtk.Notebook` + os atalhos globais.

- Título da aba: `term.title` (OSC 0/2), atualizado no `on_pty` da view.
- Nova aba herda o **cwd** da aba corrente via `readlink /proc/<pid>/cwd`
  (sem depender de OSC 7); se falhar, usa o cwd do bzmux.
- P8 passa a ser por aba: `child_watch_add` fecha a **aba**; a última fecha a
  janela. O hangup (`killpg SIGHUP`) é por sessão.
- `Alt+N` tem que ser tratado na janela (não na view), senão o filho recebe a
  tecla primeiro.
- O que **não** muda: `Term` continua sem GTK; cada aba tem o seu.

Ficou assim: `view.py` = `TermView(Gtk.DrawingArea)` com tudo que é por aba
(`Term`, `master`/`child_pid`, decoder, seleção, `view_off`, `_img_cache`);
`window.py` = `BzmuxWindow` com `Gtk.Notebook`, `Ctrl+Shift+T`/`W`,
`Alt+1..9` (`Alt+0` = 10ª), clique do meio no rótulo e o ciclo de vida
(`child_watch_add` fecha a **aba**; a última fecha a janela). O rótulo é o
título do app (OSC) ou o **cwd** da sessão — sem OSC todas as abas ficariam
"bzmux", e o `Alt+N` já dá o número (por isso não tem prefixo numérico).

Quatro armadilhas que custaram tempo (todas silenciosas):

1. **Página recém-anexada nasce *hidden*** e o `Gtk.Notebook` **ignora**
   `set_current_page` — `get_current_page()` continua na aba antiga e a tecla
   vai pra ela. Precisa `show_all()` na página e no rótulo.
2. **`grab_focus()` dentro do `switch-page` não pega**: a página ainda não está
   mapeada e o foco fica no notebook (as teclas seguintes não chegam em
   ninguém). `GLib.idle_add` resolve.
3. **O filho do pty é `sh -c "<cmd>"` e o `sh` NÃO faz exec** quando o comando
   tem argumento (`bash --norc`): o programa de verdade é **neto**, e o cwd do
   `sh` em `/proc` nunca muda. Para herdar o cwd é preciso descer até o último
   descendente (`/proc/<pid>/task/<pid>/children`).
4. **`Gtk.EventBox` sem `add_events()` tem janela e máscara vazia**
   (`get_events() == 0`): o clique do meio nunca chegava. E
   `notebook.set_tab_label_text()` **troca o widget** do rótulo (levando junto
   o EventBox) — tem que guardar o `Gtk.Label` e mudar o texto dele.

Teste: XTest (`Ctrl+Shift+T`, `Alt+2`, digitar em cada aba, clique do meio) +
screenshot + `xprop _NET_WM_NAME` para o título; o `--selftest` não cobre (é
camada GTK).

### P12 — Workspaces — **feito**

Sistema de **workspaces** como no cmux: cada workspace tem o seu conjunto de
abas, e o conjunto vive numa **barra lateral esquerda** com uma caixa por
workspace. O pré-requisito (P11: `TermView` + um `Gtk.Notebook` por conjunto)
já está no lugar, então aqui é só acrescentar o `Gtk.Stack` e a lateral.

Decisões já tomadas com o usuário: lateral **só aparece com 2+ workspaces**,
largura fixa (arrastável fica pra depois), caixa mostra `1  <título da aba
ativa>`, nome padrão "workspace N" e **editável** (duplo clique renomeia),
`Ctrl+Shift+1..9` seleciona, `Ctrl+Shift+N` cria, fechar todo o workspace =
clique do meio na caixa **ou** `Ctrl+Shift+Q`.

Atalhos pedidos:

- `Ctrl+Shift+1` … `Ctrl+Shift+9` — seleciona o workspace N (a caixa da
  lateral, como o `Alt+N` das abas do P11).
- `Ctrl+Shift+N` — cria workspace novo (nascendo com uma aba, herdando o cwd
  da aba ativa do workspace corrente, a mesma regra da aba nova do P11).
- `Alt+1` … `Alt+9` e `Ctrl+Shift+T` continuam sendo **abas do workspace
  atual** — é por isso que o P11 vem antes: o `Gtk.Notebook` deixa de ser "o"
  notebook da janela e passa a ser um por workspace.
- Fechar a última aba de um workspace **fecha o workspace** (a caixa sai da
  lateral); fechar o último workspace **fecha o programa**.

Como fica a estrutura:

```
Gtk.Window
├── Gtk.Box (horizontal)
│   ├── sidebar  — Gtk.ListBox, uma linha por workspace (índice + título da
│   │             aba ativa); é onde o Ctrl+click também seleciona
│   └── Gtk.Stack  — uma página por workspace, cada página um Gtk.Notebook
└── atalhos globais na janela (Alt+N, Ctrl+Shift+T/W, Ctrl+Shift+1..9)
```

`Gtk.Stack` (e não trocar as páginas do notebook) porque cada workspace tem
que manter a própria aba selecionada, a própria ordem e o próprio histórico de
títulos; trocar é uma chamada só e o notebook escondido não redesenha.

Detalhes que já se sabe que mordem:

- **`Ctrl+Shift+1` no teclado não entrega `1`.** Com Shift, o keyval chega como
  `exclam`/`at`/`numbersign`… (`Gdk` dá o símbolo, não o dígito). Tem que
  mapear de volta (`keyval` do dígito = o do símbolo não-shiftado) ou usar a
  coluna 1 do teclado; conferir em ABNT2 e US.
- **`Ctrl+N` foi descartado de propósito**: `C-n` é "próxima linha do
  histórico" no readline, autocomplete no vim e next-line no emacs. O cmux usa
  `Ctrl+N` porque não *é* um terminal; aqui o novo workspace é
  `Ctrl+Shift+N`. Não "consertar" isso pra `Ctrl+N` depois.
- **Captura na janela, não na view**: os atalhos têm que ser tratados no
  `key-press-event` da janela com `return True` (sem repassar pro filho) —
  mesma razão do `Alt+N` no P11. E com o protocolo do kitty ligado (P5) o app
  *consegue* pedir `Ctrl+Shift+T`; roubar é escolha, não acidente.
- **Aba escondida não recebe `size-allocate`**, então o `Term` de uma aba em
  outro workspace fica com `cols`/`rows` velhos e o `SIGWINCH` não sai. Ao
  trocar de workspace/aba, forçar o recálculo da `TermView` que apareceu (e
  manter o tamanho de célula num lugar só) — é a mesma classe de bug do resize
  em alt-screen que já apareceu.
- O `child_watch_add` do P8 passa a fechar **aba**; a agregação ("fechou a
  última aba → fecha o workspace → último workspace → fecha a janela") tem que
  ficar num lugar só, senão sobram janelas vazias.
- A lateral rouba colunas do terminal (ex.: 140 px ≈ 14 colunas) e todo resize
  re-quebra o buffer de cada aba (reflow do P3) — prever isso no teste.

Ficou assim: `Workspace` (em `window.py`) = um `Gtk.Notebook` + as `TermView`
dele + o cartão da lateral; `BzmuxWindow` = `Gtk.Box[ Gtk.ListBox | Gtk.Stack ]`
e os atalhos globais. `Gtk.Stack` (e não trocar páginas de um notebook só)
porque cada workspace guarda a própria aba selecionada, ordem e títulos.
Cartão: `1  <nome>` em negrito + `aba ativa (n abas)` em `<small>` cinza.

Atalhos: `Ctrl+Shift+N` cria (nasce com uma aba herdando o cwd da aba ativa do
workspace atual), `Ctrl+Shift+1..9` seleciona (`0` = o 10º), `Ctrl+Shift+Q` e
clique do meio no cartão fecham; **duplo clique** no cartão renomeia no lugar
(`Gtk.Entry` sobre o rótulo, Enter/foco-fora confirma, Esc cancela). A lateral
só aparece com 2+ workspaces e tem largura fixa (170 px); arrastável fica pra
depois. Fechar a última aba fecha o workspace, o último workspace fecha a
janela (a agregação mora em `Workspace.close_tab` → `close_workspace`).

Duas armadilhas novas (além das quatro do P11):

1. **`Gtk.Box` não tem `reorder()`** — é `reorder_child(child, index)`; o
   `AttributeError` só aparecia no clique do duplo clique (traceback no
   `/tmp/bzmux.log`, que fica fora da tela).
2. **`GLib.idle_add` do foco rouba o foco do `Gtk.Entry` de renomear**: o
   clique que seleciona o workspace agenda `_focus_idle`, que rodava depois do
   `grab_focus()` do entry — o nome digitado ia pro terminal (`bash: dev:
   command not found`). Agora `_focus_idle` desiste se o foco está num
   `Gtk.Entry`.

Teste (XTest + `xprop` + screenshot): `Ctrl+Shift+N` cria workspace com Term
próprio, `Ctrl+Shift+1/2` alternam, `Ctrl+Shift+T` abre aba **do workspace
atual**, renomear por duplo clique, `Ctrl+Shift+Q` e clique do meio fecham o
workspace (lateral some com 1), `exit` na última aba do ws2 fecha só o ws2 e
`exit`/`Ctrl+Shift+Q` no último fecha a janela. `--selftest` não cobre.

### P13 — Sistema de estilo da interface — **feito**

Pedido: lateral preta, workspace selecionado em cor escura (verde) e texto
claro. O que existia era o tema do sistema pintando tudo, com um hex solto
(`#8a8a8a`) no `_card_info`.

Agora `core/style.py` é a única fonte de cor do cromo: tokens
(`SIDEBAR_BG`, `CARD_HOVER_BG`, `CARD_FG`, `CARD_INFO_FG`, `CARD_SEL_BG`,
`CARD_SEL_FG`, `CARD_SEL_INFO_FG`), `css()` montando o texto a partir deles e
`contrast()` em sRGB relativo (WCAG). Puro: sem Gtk, então o check roda no
`--selftest`. A paleta do terminal (`palette.py`) continua separada — célula e
cromo não se misturam.

`apply_style()` em `window.py` registra o provider uma vez por processo
(`add_provider_for_screen`, prioridade de aplicação) e o CSS alcança os
widgets por nome e classe: `set_name("sidebar")` na `ListBox`, classe `.card`
no `EventBox` do cartão e `.info` no rótulo da segunda linha.

Decisões que custaram alguma coisa:

- **O `EventBox` do cartão é transparente no CSS.** Ele tem janela própria e
  pintava por cima da `ListBoxRow`, escondendo o `:selected`; quem pinta o
  fundo é a linha.
- **A cor da segunda linha saiu do markup.** `_card_info` embrulhava o texto
  num `<span foreground='#8a8a8a'>`, e atributo de markup ganha do CSS — a
  linha não mudaria de cor no cartão selecionado. Agora é a classe `.info` e o
  markup só carrega o `<small>`.
- **`row`, `row:hover` e `row:selected` precisam estar no CSS**: sem o
  `:selected` explícito o tema volta a mandar; sem o `:hover`, o cartão sob o
  mouse fica com o realce claro do tema.
- **O check mede contraste, não gosto**: `style_contrast` exige >= 4.5:1 nos
  quatro pares texto/fundo (normal e selecionado) — "bem claro" virou número.
  Também confere que o CSS usa os tokens, para não voltar a ter cópia à mão.

Verificado com `import -window` + `tools/pixel.py`: lateral e cartão normal em
`(0,0,0)`, cartão ativo em `(31,77,46)` (`CARD_SEL_BG`), hover em `(20,20,20)`
(`CARD_HOVER_BG`), nome do ativo em branco e a segunda linha em verde claro.
Contrastes: 15,9:1 (nome normal), 6,1:1 (info), 9,7:1 e 7,2:1 no selecionado.

Fora: a barra de abas e a moldura da janela continuam com o tema do sistema —
entram quando houver token de aba.

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

Motivo medido no doom-fire (70×21, 2 SGR truecolor por célula): 35 µs/célula de
parse, e **91% disso era o fechamento do CSI** (`csi += ch`, `split`/`strip`/
`int`, listas `parts`+`nums`, `sgr` com `flatten`), contra 0,97 de `put` e 0,11
de decode UTF-8. O gargalo não era iterar caracteres: era o custo fixo de
fechar e interpretar cada escape (~1 µs por byte de escape).

Fix: em `Term.feed`, quando o estado é `ground`, consumir o prefixo que o
caminho rápido entende — texto imprimível em bloco (um `slice` na linha) e
`CSI 38;2;r;g;b m`/`48;2;...m` resolvido por `dict[escape] -> cor` — e devolver
o resto ao parser de sempre, que ficou **intacto** como fallback. Cache com teto
de 1024 escapes; qualquer escape fora do padrão (`38;5;N`, subparâmetros `:`,
intermediários, `\x1b[H` entre outros) cai no parser lento, que é dono de todos
os estados.

`feed` passou de `for ch in text` para índice (`while`) para poder pular o
texto e os escapes já resolvidos; `ord(ch)` saiu do caminho quente do ground e
do `csi` (comparação de string no lugar).

Verificação: teste diferencial contra o parser do commit anterior (14 entradas:
frame do doom-fire, SGR 4-bit/256/truecolor, subparâmetro `:`, `?2026h`,
`\x1b(0`/`\x1b(B`, tab/backspace/rewrite, linha de 300 chars, `ED`/`EL`, RGB
fora de 0–255, OSC de título, inverse) comparando grade, cursor, fg/bg, flags,
wrap pendente, estado, título e scrollback — **0 divergências**. Mais
`./run-tests.sh` (17 checks).

Ganho: micro 32,0 → 5,49 µs/célula no frame do doom-fire (5,8x) e 0,99 → 0,21
em texto puro (4,7x); no app com `PYTERM_NODRAW=1`, **17,2 → 85 fps e 1,0 → 4,8
MB/s** (4,9x), parse de 4,17 para 0,72 ms por leitura. Com desenho ligado deu
10,4 fps / 0,6 MB/s, mas ali o desenho estava anômalo (101,8 ms por frame
contra 22,7 registrados) e vira 87% do tempo. **Fechado depois:** era o governor
`powersave` da CPU, não o código — ver o quirk do governor. O número com
desenho está em BENCHMARKS.md.

Carga real (2026-10-26), `dmesg` do sistema (1319 linhas), alimentado no `Term`
sem GTK: sem cor (99,7 KB, 0 escapes) **168,3 → 45,7 ms** (3,7x, 7,01 → 1,90 ms
por leitura de ~4 KB); com `--color=always` (122,9 KB, 5172 escapes) **187,8 →
94,8 ms** (2,0x). É a pausa que se percebia ao digitar `dmesg`: o parse roda no
thread do GTK, então cada leitura congela a UI — ~24–30 leituras de 4 KB por
despejo. Com cor o ganho é menor porque os SGR do `dmesg` (`1`, `4`, `31`, `0`)
não são truecolor e caem no parser lento; o cache de parâmetros virou o P22
(abaixo).

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
depois dele (34% do tempo). A decomposição por seção apontava 40% em
`PangoCairo.show_layout`, 19% no par `rectangle`+`fill` e 24% em cor/estado —
com 4 chamadas de contexto e 2 conversões de cor por run, ~1323 runs por draw no
doom-fire. Duas delas não tinham motivo para custar o que custavam.

Fix (nenhuma mudança de aparência; a grade sai **pixel a pixel igual**):

- `palette.cell_rgb_f(c)` devolve a cor já em float 0..1 e **cacheada** (tuplas
  compartilhadas, teto de 4096 para o truecolor). O laço do desenho deixou de
  montar `[c / 255 for c in rgb]` e de refazer 6 divisões por run; como a mesma
  cor devolve a **mesma tupla**, dá para pular o `set_source_rgb` com `is` —
  o que também ataca o caso de app monocromático, onde a cor se repete.
- o cache de layout guarda `(layout, linha, baseline)` e o desenho usa
  `PangoCairo.show_layout_line` em vez de `show_layout` (-17% no micro). A
  baseline vem de `layout.get_baseline()`, não do ascent da fonte: CJK resolve
  fallback com baseline 21 contra 17 do monoespaçado.

Ganho medido (doom-fire 600 frames, `PYTERM_GEOM`, turbo, 5 tiros cada):
`draw` **7,76 → 6,54 ms/call (-16%)** e 110,7 → 116,0 fps (+4,8%, coerente com
desenho ser 34% do tempo). Na decomposição instrumentada: `cell_rgb` 0,69 → 0,37
µs/run, estado+fundo 2,32 → 1,56, `move_to`+`show_layout_line` 2,83 → 2,44, soma
7,11 → 5,71 µs/run. O bench de 1200 frames: 118,5 fps / 6,8 MB/s (draw 6,93 ms).

**Armadilha que quase matou o ganho:** a primeira versão decidia entre
`show_layout` e `show_layout_line` com `lay.get_line_count() > 1` **por run**.
Uma chamada gi por run custa ~0,3 µs e anulou a diferença — o primeiro teste deu
só -4%. A decisão passou para a criação da entrada do cache (`line = None`
quando o texto tem quebra de linha), e o ganho apareceu. Chamada de binding por
run é caro mesmo quando "parece grátis".

Verificação: a bateria não cobre desenho (precisa de display), então a
fidelidade foi conferida por captura em display isolado (`Xvfb :99`, para o
mouse e a sessão do usuário não interferirem): tela com truecolor, negrito,
sublinhado, inverso, acento, CJK e emoji, capturada no HEAD e no código novo —
**0 pixels de diferença na grade** (`compare -metric AE`; os 448 que sobram são
o título da aba, "bz-antigo" vs "pybzmux"). 17 testes seguem passando.

### P31 — Pacote instalável: `pipx install` direto do GitHub (2026-10-28)

O app era `bzmux.py` solto na raiz importando o pacote `core/`. Funcionava
(`python3 bzmux.py`, `sys.path` da pasta do script) e não instalava: sem
`[project.scripts]`, o `uv tool`/`pipx` recusavam com `No executables are
provided by package`; e o `uv build` **não falhava** — caía num setuptools
legado e gerava um wheel com `top_level = core` (nome genérico, colisão no
site-packages) e **sem** o `bzmux.py` dentro. O critério de aceite passou a ser
inspecionar o wheel, não "buildou".

O que mudou:

- `core/` → `bzmux/` (git mv; todos os imports internos já eram relativos) e
  `bzmux.py` da raiz apagado — ele ficaria sombreado pelo diretório. No lugar
  dele, `bzmux/__main__.py` para `python -m bzmux`.
- `pyproject.toml`: `[build-system]` com hatchling, `packages = ["bzmux"]`,
  `[project.scripts] bzmux = "bzmux.cli:run"`, licença SPDX (`license = "MIT"`
  + `license-files`) e `package = false` removido (o uv passou a instalar o
  projeto em modo editable no `.venv`; o `uv.lock` mudou de `virtual` para
  `editable`).
- `cli.run()` (entry point, sem argv, sai com o código) e `main(argv=None)` —
  o `console_scripts` chama a função **sem argumentos**; `main(argv)` exigia a
  lista e estouraria `TypeError` no comando instalado. `main` continua aceitando
  argv explícito porque os checks dependem disso.
- guarda do `gi`: sem PyGObject o app sai com uma mensagem de duas linhas (apt
  ou `--system-site-packages`) em vez de traceback, e só captura
  `ModuleNotFoundError` de `gi`/`cairo` — erro de import nosso continua
  estourando.
- `USAGE` e os asserts de `checks.py` passam a dizer `bzmux` (a ajuda do comando
  instalado mentiria se dissesse `bzmux.py`).
- scripts: `run.sh` exporta `PYTHONPATH` com a raiz e roda `-m bzmux` (sem
  `cd`, porque o shell aberto herda o cwd de quem chamou — verificado abrindo
  de `/tmp` com `--cmd 'pwd > arquivo'`); `run-tests.sh` usa `-m bzmux`;
  `debug.sh` reconhece as duas formas do processo (`-m bzmux` e o script do
  PATH) — o `grep bzmux\.py` antigo deixaria `--kill`/`--status` pifando em
  silêncio.

Verificação: wheel com `bzmux/` + `entry_points.txt` (`bzmux = bzmux.cli:run`)
+ LICENSE e sem `core/`; `python3 -m bzmux --selftest` (17 checks) e `-h` sem
`gi`; `./run-tests.sh` (selftest + 17 pytest); `./run.sh --quit-after 2` e
`./debug.sh` (status/kill) fechando pelo PID; venv isolado **sem**
`--system-site-packages` mostrando a mensagem do `gi` e ainda rodando
`--selftest`; e o alvo de verdade, `pipx install --system-site-packages` do
repositório, que abriu e fechou a janela com `--quit-after 2` e cujo
`--selftest`/`-h` rodam de fora da árvore. O commit (não a árvore de trabalho)
é o que o `git+...` instala — descobrir isso custou uma rodada falhando com o
HEAD antigo.

Quirks do pipx que apareceram e ficam registrados:

- o venv da ferramenta é criado com o python **do próprio pipx**. Um pipx que
  rode num python do uv/pyenv (ex.: `uvx pipx`) gera venv num 3.12 sem `gi` e o
  `--system-site-packages` não ajuda em nada: precisa de
  `--python /usr/bin/python3`. Pipx instalado pelo apt já usa o do sistema e o
  comando simples funciona.
- `pipx reinstall` e `pipx install --force` **preservam** o
  `include-system-site-packages` mas **ignoram o `--python`**: a janela volta a
  falhar por falta de `gi` mesmo repetindo `--python`. Trocar de interpretador
  exige `pipx uninstall` e instalar de novo — verificado nas duas ordens.
- com `version = "0.1.0"` fixa, `pipx upgrade` não vê commit novo; atualização
  é `pipx install --force` (ou reinstalar), e versionar por tag fica para quando
  houver release.

Depois do fechamento, o `install.sh` (raiz) embrulha tudo isso num comando:
deps da distro por gerenciador (apt/dnf/pacman/zypper), o `python3` que importa
`gi` **e** `cairo`, `pipx install --force --system-site-packages --python PY`,
e `--selftest` no fim. Detecta clone (instala da árvore) x pipe (instala de
`git+ssh://…`); `--dry-run`, `--no-deps`, `--uninstall`. Dois bugs no caminho:
`[ -x python3 ]` testa arquivo no cwd, não no PATH (dizia "deps ausentes" com
tudo instalado), e a função de busca vazava o path no stdout quando usada como
condição. O pipe autenticado hoje é `gh api -H "Accept:
application/vnd.github.raw" /repos/.../contents/install.sh | bash`, porque repo
privado faz o `raw.githubusercontent` responder **404** — o `curl | bash`
clássico só passa a valer quando o repositório abrir.

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
sozinha para o rodapé a cada linha que chegava — impossível ler.

Causa: `view.py` voltava ao vivo em **três** casos — tecla, rolar até o fim e
"qualquer output que mude o conteúdo da tela visível" (`_view_signature()`
compara texto+cor de todas as ~4658 células visíveis). A terceira nasceu no bug
14 para o tique de 1 Hz do `pi` (cursor pra coluna 1 + esconde cursor a cada
segundo) e passou a cobrar o preço no caso normal de uso. A conta que já
existia logo abaixo (offset + crescimento do scrollback) segurava a posição,
mas o `if` da assinatura rodava antes.

Fix: âncora **absoluta** e nenhuma heurística de conteúdo —
`Term.anchored_view_off(anchor)` devolve `clamp(scrolled - anchor, 0,
len(scrollback))`, onde `anchor` é a linha absoluta que estava no topo quando o
usuário parou de rolar. O usuário só sai do histórico por ação dele: rolar até
o fim, uma tecla de verdade, ou a âncora ser destruída (limpeza de histórico com
`CSI 3J` — o clamp devolve o vivo).

Detalhes que a âncora absoluta resolve de graça:

- **tique de 1 Hz** não muda `scrolled`, então não mexe na visão (bug 14 segue
  protegido, sem assinatura);
- **scrollback no teto de 1000 linhas**: o `len()` para de crescer, e a conta
  "por diferença de tamanho" deixaria o texto derrapar linha a linha; a
  absoluta não (check cobre: com 10 linhas escritas a linha lida continua no
  topo, offset 3 → 13);
- **seleção** deixa de morrer a cada linha escrita (o `clear_selection` só
  roda em scroll do usuário, que é onde ela precisa morrer — vive em
  coordenadas de tela);
- sai o `_view_signature()`, que montava uma string de ~4658 células **por
  chunk** justamente enquanto se lia o histórico.

Descartados na discussão: **retorno por 5 s de inatividade de scroll** (mede a
coisa errada — ler é silencioso, e um app que escreve a cada 1 s arranca o
usuário assim que o prazo vence; fica imprevisível) e *sticky bottom* (voltar
com a visão a ≤1 linha do fim), que continua possível sem mudar a âncora. Os
dois estão registrados em `docs/LIMITATIONS.md`.

Verificação: check `scroll_anchor` (20º, sem display — inclusive o caso do teto
com a deriva de 10 linhas da conta antiga) e, no app de verdade, com gerador
que enche o histórico e depois escreve devagar: rolar 25 linhas → `view_off`
25 → 75 com **a mesma linha no topo** e seleção viva; tique de 1 Hz mantém
`view_off` em 25; tecla volta ao vivo (`view_off` 0). Confirmado pelo usuário
no uso real.

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
9. **Abas/workspaces: seis armadilhas silenciosas do GTK** (todas custaram
   depuração; detalhe nas seções P11/P12). (a) Página recém-anexada nasce
   *hidden* e o `Gtk.Notebook` **ignora** `set_current_page` — a tecla segue
   indo pra aba antiga. (b) `grab_focus()` dentro do `switch-page` não pega
   (página ainda não mapeada) → `GLib.idle_add`. (c) `sh -c "bash --norc"`
   **não faz exec**: o programa é neto e o cwd do `sh` em `/proc` nunca muda →
   descer até o último descendente em `/proc/<pid>/task/<pid>/children`
   (era o cwd herdado errado). (d) `Gtk.EventBox` sem `add_events()` tem janela
   e **máscara vazia** (`get_events() == 0`) — o clique do meio nunca chega.
   (e) `set_tab_label_text()` **troca o widget** do rótulo, levando o EventBox
   junto → guardar o `Gtk.Label`. (f) `Gtk.Box` não tem `reorder()` (é
   `reorder_child(child, idx)`) e o `idle_add` que foca a view roubava o foco
   do `Gtk.Entry` de renomear o workspace.

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

## Quirks registrados (não redescobrir)

- **Vazão medida depende do governor da CPU, e muito.** O mesmo doom-fire deu
  0,5 MB/s com `powersave` e 3,4 MB/s com `schedutil` (~6x); o gerador isolado,
  que nem toca no terminal, foi de 256 para 744 fps na mesma troca — é o
  `powersave` prendendo a CPU em ~1,4 GHz sob carga sostenida (o desenho de
  texto uniforme, leve, ficou em 1,41/1,45 ms nos dois governores — o efeito é
  do caminho com ~2000 runs de cor, não do trivial). Isso ficou horas disfarçado de
  "anomalia do desenho" (105 ms/frame contra os 22,7 registrados, com
  `PYTERM_DIAG` idêntico e bateria/tomada dando o mesmo), e a pista que
  resolveu foi medir uma etapa que não depende do app. Regras: registrar o
  governor junto com o número, comparar só dentro do mesmo governor, e sempre
  incluir um tiro do gerador isolado como controle.
- **`cProfile` não enxerga `gi.FunctionInfo`**: `PangoCairo.show_layout`
  chamado 20.000 vezes num teste isolado não aparece no perfil, e o tempo cai no
  `self` do chamador (já fez `_on_draw` medir 46% de "self" sem nenhuma chamada
  de Pango). Métodos de objeto cairo (`fill`, `rectangle`, `move_to`) aparecem;
  funções de módulo do gi, não. O `cProfile` também infla quem faz muitas
  chamadas Python (`join`: 21% no perfil contra 12% no relógio) e derrubou o
  doom-fire de 59,8 para 5,6 fps. Para proporção, medir com `perf_counter` por
  seção; o perfil serve para descobrir *quais* chamadas existem.
- **As primeiras chamadas de `_on_draw` custam mais**: 3 draws deram
  3,42 ms/chamada e 443 deram 1,41 ms na mesma carga (setup de layout/fonte/
  contexto). Medir `draw` com centenas de chamadas, ou comparar por razão.
- **`pkill -f bzmux.py` mata o próprio shell** de quem chama (o padrão casa com
  a linha de comando) e já deixou janelas órfãs. Usar `./debug.sh --kill`, que
  confere o PID file contra `/proc/<pid>/cmdline` antes de matar.
- **`wmctrl -r bzmux` deixa de funcionar** quando o app muda o título por OSC
  (`mc` faz isso). Para achar a janela, casar por `_NET_WM_PID` contra o PID do
  runner.
- **`import -window root -crop` com geometria de `xwininfo`** só funciona com a
  janela ativada antes; senão captura a janela que estiver por cima.
- **O `.n  Name` e os nomes truncados com `~` no `mc` são do próprio `mc`**
  (conferido nos bytes crus: ele escreve `.n  Name` e trunca conforme a largura
  do painel). Não é bug de renderização.
- **Injetar `<Caps_Lock>` liga a trava de verdade** no servidor X: o teste
  seguinte sai em maiúsculas. Desligar com outro `<Caps_Lock>` e conferir com
  `xset q`.
- **`chr(kv)` para keyval de tecla especial não existe**: só `0x20–0x7e`,
  `0xa0–0xff` e `0x01000000+U` são caractere. O resto é modificador/função.
- **As ferramentas de teste moram em `tools/`** (rodam com o `python3` do
  sistema — `python3-xlib` 0.33 e `gi` já estão instalados). `tools/xtest.py`
  injeta eventos: `id`, `geometry`, `activate`, `move`, `click`, `dclick`,
  `wheel`, `drag`, `key`, `type` (texto arbitrário, com `/ - . , ; = { } [ ]
  | ~ ?` e maiúsculas). `tools/pixel.py` lê cor de pixel de um PNG:
  `tools/pixel.py shot.png 400,200`, `--scan X` (uma amostra por faixa de
  19 px), `--row Y`.
- **`xdotool` também está instalado** (`1:3.20160805`): `search --pid`,
  `type`, `key`, `mousemove --window`, `click --repeat 2`. Serve para o que não
  vale escrever à mão. As duas ferramentas usam **as mesmas coordenadas**
  (conferido: mesmo pixel para o mesmo ponto relativo).
- **Coordenadas são relativas à janela, e a grade não começa em (0,0)**: com
  lateral (170 px) e barra de abas (~28 px), a sessão começa em `y≈58`. Clicar
  em `y=8` acerta a **barra de abas** — e arrastar ali **reordena aba** em vez
  de selecionar texto.
- **`xwininfo` "Absolute upper-left" é a origem do cliente** (é o que se usa
  para injetar); o `Position` do `xdotool getwindowgeometry` é o **frame** do WM —
  aqui 11/40 px deslocado. Confundir os dois desloca todo clique e todo teste.
- **Achar a janela por `_NET_WM_PID` tem de pegar a maior visível**: o GTK cria
  ajudantes de 10x10 com o mesmo PID, e a primeira que aparece engana
  (`geometry` devolvia 10x10 e `set_input_focus` estourava `BadMatch`).
- **`~`, `^` e `` ` `` são dead keys no ABNT2**: `type '~nome'` digita `~` e o
  `n` compõe `ǹ` — é o comportamento certo do terminal (composição por NFC),
  não falha da ferramenta. Para um til literal, digitar espaço depois.
- **`cairo` com `FORMAT_A1`** serve para medir fonte, mas `font_extents()`
  devolve **5** valores (ascent, descent, height, max_x_advance,
  max_y_advance) — não 6.

- **Quebra pendente e caracteres de controle**: emulador nenhum deve contar o
  `\n` que vem depois de uma linha cheia como segunda quebra; texto preenchendo
  a última coluna e `\r\n` é o padrão de qualquer TUI que desenha com padding
  até a borda.
- **`show_all()` desfaz `set_visible(False)`**: `Gtk.Widget.show_all()` mostra
  todos os descendentes, então um widget escondido no construtor volta a
  aparecer. Para controlar visibilidade na mão, `set_no_show_all(True)` nele.
- **Prioridade de fonte do GLib**: `io_add_watch` sem prioridade explícita usa
  `DEFAULT` (0), que é *maior* que qualquer coisa de desenho. Um fd sempre
  pronto em prioridade 0 congela a tela; `PRIORITY_DEFAULT_IDLE` (200) deixa o
  redraw (120) passar na frente. O mesmo vale para `timeout_add` de animação.
- **Custo de desenho depende de runs, não de células**: 1360 células com 37
  cores por linha custam ~13 ms; o mesmo número de células com uma cor custa
  ~1 ms. Medir desenho com tela uniforme subestima o pior caso por 10x.
- **Célula em branco é compartilhada (P21)**: `_blank_row()` é
  `[_BLANK_CELL] * cols`, e a mesma lista de célula aparece em toda a grade. É
  por isso que escrever tem que **substituir** a célula (`row[x] = [ch, fg, bg,
  fl]`), nunca fazer `row[x][2] = ...`: mutação in-place em uma célula em branco
  pinta a tela inteira. `blank_cell()` (com bg corrente, para `erase_*`) segue
  alocando uma célula nova de propósito.
- **fps de carga depende da grade**: a vazão em MB/s fica parada (0,6) e o fps
  cai quando a célula cresce; comparar fps entre grades diferentes não diz nada.

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
