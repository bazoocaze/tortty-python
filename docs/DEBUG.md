# bzmux — desenvolvimento: ferramentas, verificação e armadilhas

Manual operacional: ler a primeira seção antes de rodar ferramenta na sessão
gráfica.

Diretivas: título, item, `code`, cerca para sequência de comandos. Um item =
uma armadilha (sintoma + como evitar). Negrito só em "Sessão real". Backtick
só se realmente relevante. Sem tabela, itálico, data ou número de medição.

## Sessão real: o que pode travar tudo

- **`tools/xtest.py` injeta no X em uso:** ponteiro e botões reais (XTest).
  Todo `ButtonPress` abre implicit grab que só fecha no `ButtonRelease`: morrer
  entre os dois deixa o botão apertado, o cursor vira o de quem pegou o grab e
  o desktop parece travado. `drag` (press + ~8 movimentos + release) é o pior
  caso; `click`/`dclick`/`wheel`, mesma coisa em janela menor.
- **Destravar:** `xdotool mouseup 1` (e `2 3 4 5` se o press foi outro).
  Órfão segurando o grab: `pgrep -af "xtest.py|import"`, matar, repetir.
- **Regra:** xtest só com a sessão disponível e quando precisar de display,
  nunca `drag` de rotina, nunca sem release. Para automatizar: Xvfb/Xephyr
  (ponteiro virtual, nada do usuário para travar).
- **`xdotool windowactivate` rouba o foco** da pessoa. Não usar para conferir.
- **`import` sem `-window`** põe o cursor em mira e agarra o ponteiro até o
  clique de seleção: outro jeito de travar. Sempre `import -window ID`.
- **ID de janela nunca fixo:** o app reinicia e o ID muda (`Resource
  temporarily unavailable` no `import`). Resolver na hora: `state` do socket
  devolve o `xid`, ou `tools/xtest.py id` sem socket.
- **`pkill -f bzmux` mata o próprio shell** (o padrão casa com a linha de
  comando). Usar `./debug.sh --kill`, que confere o PID file contra
  `/proc/<pid>/cmdline`.
- **`wmctrl -r bzmux` falha** quando o app muda o título por OSC (mc faz).
  Achar a janela por `_NET_WM_PID` contra o PID do runner.
- **`<Caps_Lock>` injetado liga a trava de verdade:** o teste seguinte sai em
  maiúsculas. Desligar com outro e conferir com `xset q`.

## Ferramentas de teste manual

Em `tools/`, com o python3 do sistema (`python3-xlib` 0.33 e gi instalados).

- `tools/xtest.py SUBCOMANDO` — `id`, `geometry`, `activate`, `move`, `click`,
  `dclick`, `wheel`, `drag`, `key`, `type`. `type` aceita
  `/ - . , ; = { } [ ] | ~ ?` e maiúsculas.
- `tools/pixel.py` — cor de pixel de PNG: `tools/pixel.py shot.png 400,200`,
  `--scan X` (amostra por faixa de 19 px), `--row Y`. Confere desenho em
  captura (`import -window`).
- xdotool (`1:3.20160805`): `search --pid`, `type`, `key`,
  `mousemove --window`, `click --repeat 2`, `mouseup`. Mesmas coordenadas do
  xtest.

- Coordenada é relativa à janela e a grade não começa em (0,0): lateral
  (170 px, `SIDEBAR_W`) + aba (~28 px) põem a sessão em `y≈58`. `y=8` é a
  barra de abas — arrastar ali reordena aba.
- xwininfo "Absolute upper-left" é a origem do cliente (a que se usa para
  injetar); `Position` do `xdotool getwindowgeometry` é o frame do WM (11/40 px
  aqui). Confundir desloca todo clique.
- Janela por `_NET_WM_PID`: pegar a maior visível. O GTK cria ajudantes 10x10
  com o mesmo PID; a primeira que aparece devolve 10x10 e `BadMatch` no
  `set_input_focus`.
- `import -window root -crop` com geometria de xwininfo exige a janela ativa
  antes; senão captura o que estiver por cima.
- `~`, `^` e `` ` `` são dead keys no ABNT2: `type '~nome'` digita `~` e o `n`
  compõe `ǹ` — comportamento certo (NFC), não falha da ferramenta. Til
  literal: espaço depois.
- `.n  Name` e nomes truncados com `~` no mc são do mc (bytes crus: ele escreve
  `.n  Name` e trunca pela largura do painel), não da renderização.

## Verificação com janela

```
./debug.sh --debug-socket auto              # log em /tmp/bzmux.log + socket
printf '{"cmd": "text"}\n' | nc -N -U /run/user/$UID/bzmux-*.sock  # a tela
python3 tools/xtest.py key ctrl+shift+n     # workspace novo (o app consome)
python3 tools/xtest.py dclick 60 28         # duplo clique no cartão 1
```

Roteiro de teste termina com `{"cmd": "quit"}` em vez de `sleep` +
`--quit-after` + `--kill`: espera-se a resposta que interessa (`state` com
`scrolled` > 0, por exemplo) e fecha. Digitar texto é `{"cmd": "write", "data":
"seq 1 200\r"}` — sem display, foco ou risco de grab.

- Quem lê a tela é `text` com `where` = `view` (o que a tela mostra, com
  `view_off`), `screen` (grade viva) ou `history` (scrollback por linha
  absoluta). O dump do `SIGUSR1` e o `--dump-to` continuam existindo para
  quando não há socket, e eles são da grade VIVA: conferir scroll por eles dá
  falso negativo (o offset só aparece no cabeçalho `(histórico +N)`).
- Pixel continua exigindo captura: `state` devolve o `xid` da janela, então
  `import -window $(...)` não depende mais de caçar o ID pelo `_NET_WM_PID`.
- Página oculta do `Gtk.Notebook` não é realocada: mantém o `size-allocate`
  antigo (lateral aberta estreita de 75 para 62 colunas só na visível) e
  corrige ao ser mapeada (`on_resize` → `TIOCSWINSZ`/`SIGWINCH`). Larguras
  diferentes no dump são isso.
- O app roda no venv do uv (PyGObject do sistema via `--system-site-packages`).

## Sondas do app (`PYTERM_*`)

Variável de ambiente na execução (não muda código):

- `PROF=1` — ao fechar, custo de parse (`on_pty`) e desenho (`on_draw`), bytes
  lidos e eagain.
- `NODRAW=1` — sem desenho (sobra pty → grade).
- `NOPARSE=1` — lê o pty e descarta (isola o IO).
- `GEOM=980x640` — trava o tamanho da janela (senão o WM abre 80x24).
- `GEOMLOG=1` — cada configure: cliente, moldura e frame extents.
- `SCROLLLOG=ARQ` — chunk que rola mais de meia tela (jump/top/bottom/
  alt-screen + bytes crus).

`PROF` decompõe a vazão, `NODRAW`/`NOPARSE` cortam um lado. Escada e números:
docs/BENCHMARKS.md. Avanço × célula (o par do bug 13 do HISTORY: divergir é
grade medida numa resolução e desenhada em outra) vem no `state` do socket, com
`advance`, `cell`, `dpi` e `padding`; a configuração carregada também
(`config`, `errors`), no lugar do antigo `CONFLOG`.

## Medição (doom-fire)

- Número de benchmark se compara por **grid**, não por janela: a célula é fonte ×
  `Xft.dpi` (130 no desktop do autor, 96 sem o recurso), então a mesma janela dá
  70×21 ou 98×27. Alvo em células, e o grid vem do `state` (`cols`, `rows`,
  `cell`, `dpi`).
- `--cmd` com a carga mede o grid errado: o filho nasce antes do primeiro
  `TIOCSWINSZ` e pode ver o padrão 80×24. Escrever a carga no pty depois que o
  `state` confirmar o alvo é o que tira a corrida.
- O display entra no número: o X real do desktop (glamor) desenha ~3x mais caro
  que um Xvfb na mesma grade. `./bench.sh --xvfb` mede no virtual.
- Geometria salva de execução anterior (`window.json`, inclusive `max`) muda o
  grid do teste: `XDG_STATE_HOME` descartável isola. O `tools/benchrun.py` já
  faz as três coisas.

## Log do `?2026` (opção `debug_log`)

Uma linha JSONL por evento, com `ts` local em ms:

- `debug_log /tmp/bzmux.debug.log` na configuração (default); `off` desliga;
  `--debug-log ARQ` na linha de comando vence a configuração; reload aplica.
- `2026` — transição de `sync_output`, com `on`, `v`, `pin`, `sb`, `scr`,
  `gen`; no fecho leva `ms` (duração da região, `time.monotonic`).
- `draw` — desenho que escapou com a região aberta (`v`, `pin`, `sb`, `scr`).
- `pos` — `view_off` mudou dentro da região (`v0`, `v1`, `pin`, ...).
- `wheel` — roda dentro da região (`d`, `v0`, `v1`, `pin`).
- `ms > 200` com um `draw` é o teto cumprindo o papel, não frame escapado; `pos`
  dentro de uma região é o que o bug 22 do HISTORY.md descrevia.
- Em teste, sempre `--debug-log /tmp/outro-nome.log`: o arquivo padrão é o da
  sessão do usuário e misturar os dois apaga a evidência dele.

## Socket de introspecção (`--debug-socket`)

Ferramenta para o agente, desligada por omissão: `--debug-socket ARQ`, ou `auto`
= arquivo com o pid em `$XDG_RUNTIME_DIR`. Arquivo em `0600` e só o mesmo uid
conecta; quando abre, a janela mostra um toast de aviso de segurança com o
caminho do socket.

- Um pedido JSON por linha, uma resposta JSON por linha; a mesma conexão aceita
  vários pedidos seguidos.
- `{"cmd": "state"}` — pid, `xid` da janela, grade, cursor, título, `view_off`,
  `pin`, `sync`, `scrolled`, `scrollback`, abas, workspaces, configuração,
  erros, e as métricas da grade (`advance`, `cell`, `dpi`, `padding`, `font`,
  `font_size`).
- `{"cmd": "text", "where": "view", "start": 0, "count": 40}` — `view` é o que
  a tela mostra (segue `view_off`), `screen` é a grade viva (o que o dump do
  `SIGUSR1` mostra) e `history` indexa o scrollback por linha absoluta, 0 = a
  mais antiga.
- `{"cmd": "write", "data": "seq 1 200\r"}` — bytes crus no pty, como se
  digitados; tecla que o app consome (PgUp, atalhos) não chega ao filho por
  aqui.
- `{"cmd": "keys", "data": "ctrl+shift+p"}` — tecla pelo caminho do app
  (atalho, `shift+PgUp`, encoder para o filho), não pelo pty; aceita lista.
  Nome de keysym do X (`Page_Up`, `F2`, `Return`) mais os atalhos `PgUp`,
  `PgDn`, `Esc`, `Enter`, `Del`, `BS`, `Ins`; modificadores `ctrl`, `shift`,
  `alt`, `super`. Tecla desconhecida é erro, não silêncio.
- `{"cmd": "resize", "cols": 100, "rows": 34}` — redimensiona a JANELA e deixa
  o caminho normal acontecer (allocation, `TIOCSWINSZ`, `SIGWINCH`); o
  resultado sai no `state` seguinte.
- `{"cmd": "prof", "on": true}` — liga a medição de custo em execução; sem `on`
  só devolve os contadores acumulados (pty, draw, bytes, eagain).
- `{"cmd": "log", "value": "/tmp/x.log"}` — liga, troca ou desliga (`off`) o
  `debug_log` em execução.
- `{"cmd": "quit"}` — fecha o app; o destroy vai num idle para a resposta sair
  antes (fazer direto fecha o socket no meio do pedido).
- Cliente fecha a conexão, não o servidor: ele fica aberto para receber mais
  pedidos. Sem `nc -N` (ou `-q 0`) o comando pendura esperando o fim da
  conexão; EOF do cliente encerra do lado do app.
- Pedido inválido responde `{"ok": false, "err": ...}`; o despacho é puro e o
  check `debug_socket` cobre ele com alvo falso.

## Armadilhas de implementação
- Dano do desenho: `Term.take_damage()` é a única fonte do que a view repinta.
  Caminho novo que escreva célula sem `touch(y)` (ou sem `touch_all()`, se mover
  linhas) não aparece na tela até algo rolar — o bug parece de parse.
- O laço de `_on_draw` filtra por `cr.clip_extents()`; é isso que faz o spinner
  de um caractere custar uma linha em vez do frame. Tirar o filtro (ou trocar
  `queue_draw_area` por `queue_draw`) devolve os 13 ms sem mudar um pixel.

- `show_all()` desfaz `set_visible(False)`: mostra todos os descendentes e um
  widget escondido no construtor volta. Controlar na mão exige
  `set_no_show_all(True)` nele.
- `io_add_watch` sem prioridade usa `DEFAULT` (0), acima de desenho: fd sempre
  pronto em 0 congela a tela. `PRIORITY_DEFAULT_IDLE` (200) deixa o redraw
  (120) passar. Vale para `timeout_add` de animação.
- `background-color` sozinho não pinta no GTK3: se o tema põe `background-image`
  no nó, a cor é ignorada. Fundo sólido precisa de `background-image: none` (foi
  o flash do bell "não funcionar").
- Nó CSS `tab` do `Gtk.Notebook` não é o rótulo: classe no rótulo pinta só o
  texto e `tab:checked` manda no resto. `label.get_parent()` é o próprio
  Notebook; dar `set_name` ao rótulo e cuidar do padding nele (P34).
- O desmapeio da página é do despacho do `Gtk.Notebook`: é dele que o pisca do
  cursor depende (`unmap`/`map`). Trocar o container e ele volta a rodar em
  todas as abas.
- Página recém-anexada ao `Gtk.Notebook` nasce oculta e `set_current_page` é
  ignorado (`get_current_page()` continua na anterior): `show_all()` na página e
  no rótulo antes de trocar.
- `get_current_page()` dentro do `switch-page` ainda é a página ANTIGA (o
  notebook só troca depois de emitir o sinal). Quem atualiza cartão, título ou
  rótulo no handler tem que usar o `page`/`page_num` do sinal, senão a tela
  anda uma ação atrás.
- `grab_focus()` dentro de `switch-page` não pega (a página ainda não está
  mapeada, o foco fica no notebook): agendar com `GLib.idle_add`.
- `GLib.idle_add` de foco rouba o foco de um `Gtk.Entry`: checar `get_focus()`
  antes, senão o nome digitado vai para o terminal.
- `CSI 3J` apaga o histórico: a âncora absoluta de rolagem morre com ele. O
  repaint que limpa reescreve o mesmo texto, então o que vale é a distância do
  vivo (`Term.hist_gen` marca a limpeza, `pinned_view_off` reconta); guardar a
  linha absoluta faz a visão saltar pro topo da história nova.
- `sh -c "<cmd>"` não faz exec quando o comando tem argumento: o programa é
  neto do pty e o cwd do `sh` nunca muda. Herdar cwd pelo último descendente
  (`/proc/<pid>/task/<pid>/children`).
- O filho do `pty.fork` herda o ambiente inteiro, `SHELL` incluído: ele passa a
  mentir quando o shell configurado é outro (ou quando o config está vazio e o
  `$SHELL` decide). Exportar o `SHELL` que `config.tab_command` devolve — o
  `--cmd` troca o comando, não o `SHELL`.
- `Gtk.EventBox` sem `add_events()` tem máscara vazia (`get_events() == 0`) e o
  clique nunca chega; e `notebook.set_tab_label_text()` troca o widget do
  rótulo (guardar o `Gtk.Label` e mudar o texto dele).
- `Gtk.Box` não tem `reorder()`: é `reorder_child(child, index)`.
- Em atalho `Ctrl+Shift+1` o keyval chega como `exclam`/`at`, não como `1`
  (o Gdk dá o símbolo): mapear de volta ou usar a coluna do teclado.
- `queue_resize()` não re-aloca quando o tamanho do widget não muda: com fonte
  nova o `size-allocate` não vem e a grade fica com a célula antiga. Chamar
  `on_resize` direto ao aplicar config.
- Métrica de fonte sai do contexto Pango do widget (`get_pango_context()`), não
  de uma `ImageSurface` solta: ponto→pixel usa outra resolução e a grade
  desalinha.
- cairo `FORMAT_A1` mede fonte, mas `font_extents()` devolve 5 valores (ascent,
  descent, height, max_x_advance, max_y_advance).
- Quebra pendente: emulador não deve contar o `\n` depois de linha cheia como
  segunda quebra — texto até a última coluna + `\r\n` é o padrão de TUI que
  desenha até a borda.
- Célula em branco é compartilhada (P21): `_blank_row()` é
  `[_BLANK_CELL] * cols`. Escrever substitui a célula
  (`row[x] = [ch, fg, bg, fl]`), nunca `row[x][2] = ...`: mutação in-place pinta
  a tela inteira. `blank_cell()` (bg corrente, para `erase_*`) aloca nova de
  propósito.
- `lista[-0:]` é a lista inteira: fatiar por teto configurável (`[-limit:]`)
  deixa de cortar com limite 0. Usar `del lista[:len(lista) - n]`.
- `chr(kv)` só existe para `0x20–0x7e`, `0xa0–0xff` e `0x01000000+U`; o resto é
  modificador/função.
- `create_for_data` do cairo não copia os bytes: o `bytearray` da imagem tem de
  continuar vivo enquanto a surface existir, senão o desenho sai com lixo.
- O `Gtk.EventBox` do cartão tem janela própria e pinta por cima da
  `ListBoxRow`, escondendo o `:selected`: deixá-lo transparente no CSS e pintar
  o fundo na linha.
- Atributo de markup (`<span foreground=...>`) ganha do CSS e o rótulo não muda
  de cor no selecionado: cor vai por classe, markup só com o `<small>`.
- `row`, `row:hover` e `row:selected` têm de estar no CSS: sem o `:selected`
  explícito o tema manda, e sem `:hover` o cartão sob o mouse pega o realce
  claro do tema.
- Chamada de binding do gi por run custa caro e anula o ganho de trocar a
  chamada de desenho: decidir na criação da entrada do cache, nunca por run.
- Baseline do layout vem de `get_baseline()`, não do ascent da fonte: com
  fallback CJK o layout resolve outra baseline e o texto sobe.
- Âncora de seleção e de histórico mora em linha **absoluta**
  (`scrolled - view_off + row`), nunca em fileira de tela: coordenada de tela
  envelhece ao rolar e ao chegar output. A geração do mapa (`Term.abs_gen`)
  invalida no reflow, em `CSI 3J` e na troca de buffer do alt-screen, mas
  **não** no corte do teto do `scrollback` — ali a linha absoluta continua a
  mesma (P32/B17).

## Instalação (pipx e shell)

- O venv do pipx nasce com o python **do próprio pipx**: `uvx pipx` instala num
  3.12 sem `gi` e `--system-site-packages` não salva — precisa de
  `--python /usr/bin/python3`. Pipx do apt já usa o do sistema.
- `pipx install --force` e `reinstall` preservam `include-system-site-packages`
  mas **ignoram** `--python`: trocar de interpretador exige `uninstall` e
  instalar de novo.
- `git+ssh://…` instala o **commit**, não a árvore de trabalho: mudança não
  commitada não chega no teste.
- Versão fixa no `pyproject` faz `pipx upgrade` não ver commit novo; atualização
  é `--force`.
- `[ -x python3 ]` testa arquivo no cwd, não no PATH: use `command -v`.
- Função que imprime e é usada como condição vaza no stdout: `if func; then`
  recebe o valor errado.

## Medição e perfil

Governor, carga e protocolo de medição: docs/BENCHMARKS.md. Do perfil:

- cProfile não enxerga `gi.FunctionInfo`: `PangoCairo.show_layout` 20.000 vezes
  não aparece e o tempo cai no self do chamador (`_on_draw` a 46% de "self" sem
  Pango). Método de objeto cairo (`fill`, `rectangle`) aparece; função de
  módulo do gi, não. Ele infla quem faz muita chamada Python e derruba o
  doom-fire: proporção, `perf_counter` por seção; perfil, só para saber quais
  chamadas existem.
- As primeiras `on_draw` custam mais (layout, fonte, contexto): medir `draw`
  com centenas de chamadas ou comparar por razão.
- Desenho depende de runs, não de células: a mesma contagem com uma cor custa
  uma fração de dezenas de cores por linha; tela uniforme subestima o pior caso.
- fps depende da grade: MB/s fica parado e fps cai quando a célula cresce;
  comparar fps entre grades não diz nada.
