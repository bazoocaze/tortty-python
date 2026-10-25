# bzmux — histórico

Memória do projeto: backlog concluído, bugs corrigidos, quirks e git.
Não é tarefa. Pendências: [BACKLOG.md](BACKLOG.md). Status, escopo,
arquitetura, medições e como testar: [../TASK-bzmux.md](../TASK-bzmux.md).
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
cores não virando RGB, reset, sobrevive ao reflow) e pixel a pixel com `vim -c 'set termguicolors'`:
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
(`repos/kitty/kitty/key_encoding.c`), que foi a referência:

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
desenho no `window.py`. Parse do APC (`ESC _ G ... ESC \`) no parser do
`Term`, com estado `apc`/`apc-esc`.

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
  código 3`), que o `run.sh` guarda em `/tmp/bzmux.log`.
- **Hangup**: `os.killpg(child_pid, SIGHUP)` no fechamento (o `pty.fork` fez do
  filho líder de sessão), então jobs em background não ficam órfãos segurando o
  pty.
- **Ordem inversa também vale**: `EIO` antes do `waitpid` → espera o status;
  `waitpid` antes do `EIO` → drena e fecha.

Pegadinha que fez o hangup "não funcionar": **disposição de sinal é herdada**.
O `run.sh` sobe com `nohup` (SIGHUP = ignorado) e o Python ignora SIGPIPE — o
filho herdava os dois. Resultado: `killpg(SIGHUP)` não matava ninguém (o `sleep`
aparecia com `SigIgn: 01001007`) e `seq 1 100000 | head -3` não parava no pipe
quebrado. Fix: no filho do `pty.fork`, antes do `exec`, `SIGHUP`/`SIGPIPE`/
`SIGINT`/`SIGQUIT`/`SIGTERM` voltam para `SIG_DFL`.

Verificado: `--cmd 'exit 3'` fecha e loga o código 3; `Ctrl+D` num `bash`
interativo fecha; `sleep 120 & ... exit` fecha e o job morre no SIGHUP;
`seq 1 100000 | head -3` termina na hora; `--quit-after 2` continua fechando;
fechar a janela pelo WM mata o filho (o master fecha → SIGHUP do kernel no grupo
da frente).

### P11 — Abas — **feito**

`Ctrl+Shift+T` abre aba nova; `Alt+1` … `Alt+9` selecionam a aba N (`Alt+0` =
10ª?); `Ctrl+Shift+W` fecha a aba; fechar a última fecha a janela.

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

## Quirks registrados (não redescobrir)

- **`pkill -f bzmux.py` mata o próprio shell** de quem chama (o padrão casa com
  a linha de comando) e já deixou janelas órfãs. Usar `./run.sh --kill`, que
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
- **`xwininfo` "Absolute upper-left" é a origem do cliente** (é o que se usa para
  injetar); o `Position` do `xdotool getwindowgeometry` é o **frame** do WM —
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

## Git e origem do repositório

Nasceu no repositório do experimento `kitty`
(`~/dados/workflows/temp/kitty`), na pasta `pyterm/`, com o nome **pyterm**.
Em 2026-10-25 virou repositório próprio, `pybzmux`, com o nome **bzmux**. A
parte C/GTK do kitty (`native-port/`, GPL-3.0-only) ficou lá: não é compilada
nem testada aqui, e nada do bzmux é compartilhado com ela.

Os commits até a separação vieram por `git subtree split`, que **reescreve
hashes**: os do repositório de origem não existem aqui nem no GitHub, e as
mensagens antigas ainda dizem `pyterm`. O `520447b` é a renomeação para
`bzmux`.

Histórico completo: `git log --oneline` (a lista de hashes não é mantida à
mão).
