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
  temporarily unavailable` no `import`). Resolver na hora: `tools/xtest.py id`.
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
./debug.sh                                  # log em /tmp/bzmux.log
python3 tools/xtest.py key ctrl+shift+n     # workspace novo
python3 tools/xtest.py dclick 60 28         # duplo clique no cartão 1
python3 tools/xtest.py type 'echo ok'
kill -USR1 $(cat /tmp/bzmux.pid)            # dumpar a grade
```

Dump em `/tmp/bzmux-dump.txt` (`--dump-to ARQ` troca). Cabeçalho de workspace e
de aba só com mais de um; o da viewport diz `(histórico +N)` quando rolada.

- O dump é da grade VIVA, não da visão rolada (`dump_text` lê `Term.row_text`):
  conferir scroll por ele dá falso negativo. O offset só aparece no
  `(histórico +N)` ou em captura.
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
- `DIAG=1` — no primeiro draw: avanço, célula, resolução e colunas.
- `SCROLLLOG=ARQ` — chunk que rola mais de meia tela (jump/top/bottom/
  alt-screen + bytes crus).
- `CONFLOG=1` — cada reload aprovado imprime os valores.

`DIAG` é o par que tem de bater (avanço × célula; divergir = grade medida numa
resolução e desenhada em outra, bug 13 do HISTORY). `PROF` decompõe a vazão,
`NODRAW`/`NOPARSE` cortam um lado. Escada e números: docs/BENCHMARKS.md.

## Armadilhas de implementação

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
- `grab_focus()` dentro de `switch-page` não pega (a página ainda não está
  mapeada, o foco fica no notebook): agendar com `GLib.idle_add`.
- `GLib.idle_add` de foco rouba o foco de um `Gtk.Entry`: checar `get_focus()`
  antes, senão o nome digitado vai para o terminal.
- `sh -c "<cmd>"` não faz exec quando o comando tem argumento: o programa é
  neto do pty e o cwd do `sh` nunca muda. Herdar cwd pelo último descendente
  (`/proc/<pid>/task/<pid>/children`).
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
