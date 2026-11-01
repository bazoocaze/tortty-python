# bzmux — desenvolvimento: ferramentas, verificação e armadilhas

Manual operacional para quem mexe no app (agente ou humano). Ler a primeira
seção **antes de rodar qualquer ferramenta na sessão gráfica**.

Diretivas deste arquivo:

- **Formato simplificado, feito para agente**: título, lista e `código`. Sem
  tabela, sem enfeite, sem prosa corrida — o texto é para ser varrido, não lido.
- **Conciso**: uma armadilha por item; sintoma e como evitar em poucas linhas.
  Detalhe longo fica no código ou no doc dono do assunto.
- **Sem data e sem número de medição** (números: docs/BENCHMARKS.md). Narrativa
  datada de item/bug: docs/HISTORY.md. Decisão de não fazer algo:
  docs/LIMITATIONS.md. Armadilha nova entra aqui, não no HISTORY.

## Sessão real: o que pode travar tudo

- **`tools/xtest.py` injeta no X que você está usando.** Move o **ponteiro
  real** e aperta botões **reais** (XTest). Todo `ButtonPress` abre um
  *implicit grab* do X11 que só termina no `ButtonRelease` correspondente: se o
  processo morrer, estourar exceção ou for interrompido (Ctrl+C, timeout,
  comando abortado) entre os dois, o servidor continua achando o botão
  apertado — o cursor vira o de quem segurou o grab (mira/seleção), os cliques
  passam todos para aquela janela e o desktop inteiro parece travado. `drag` é
  o pior caso (press, ~8 movimentos de 30 ms, release); `click`/`dclick`/
  `wheel` têm janelas menores, mesma natureza.
- **Destravar:** entregar o release que faltou — `xdotool mouseup 1` (e
  `2 3 4 5` se o press foi de outro botão). Se houver processo órfão segurando o
  grab, `pgrep -af "xtest.py|import"`, matar e repetir o `mouseup`.
- **Regra de uso:** só rodar xtest com a sessão disponível e quando o teste
  precisar de display de verdade; nunca em `drag` de rotina, nunca deixando uma
  chamada sem release. Rodar em display privado (Xvfb/Xephyr) é o caminho para
  automatizar — o ponteiro é virtual e não existe sessão do usuário para travar.
- **`xdotool windowactivate` rouba o foco** do que a pessoa está fazendo. Não
  usar para "conferir" nada.
- **`import` sem `-window` põe o cursor em mira e agarra o ponteiro** esperando
  o clique de seleção — outro jeito de travar a sessão. Sempre
  `import -window ID`.
- **ID de janela nunca fixo:** o app reinicia e o ID muda (o `import` então
  falha com `Resource temporarily unavailable`). Resolver na hora:
  `tools/xtest.py id` / `_NET_WM_PID`.
- **`pkill -f bzmux` mata o próprio shell** de quem chama (o padrão casa com a
  linha de comando) e já deixou janelas órfãs. Usar `./debug.sh --kill`, que
  confere o PID file contra `/proc/<pid>/cmdline` antes de matar.
- **`wmctrl -r bzmux` deixa de funcionar** quando o app muda o título por OSC
  (`mc` faz isso). Para achar a janela, casar por `_NET_WM_PID` contra o PID do
  runner.
- **Injetar `<Caps_Lock>` liga a trava de verdade** no servidor X: o teste
  seguinte sai em maiúsculas. Desligar com outro `<Caps_Lock>` e conferir com
  `xset q`.

## Ferramentas de teste manual

As ferramentas moram em `tools/` e rodam com o `python3` do sistema
(`python3-xlib` 0.33 e `gi` já instalados).

- `tools/xtest.py SUBCOMANDO` — `id`, `geometry`, `activate`, `move`, `click`,
  `dclick`, `wheel`, `drag`, `key`, `type`. `type` aceita texto arbitrário
  (`/ - . , ; = { } [ ] | ~ ?` e maiúsculas).
- `tools/pixel.py` — cor de pixel de um PNG: `tools/pixel.py shot.png 400,200`,
  `--scan X` (uma amostra por faixa de 19 px), `--row Y`. É com ele que se
  confere desenho numa captura (`import -window`).
- `xdotool` também está instalado (`1:3.20160805`): `search --pid`, `type`,
  `key`, `mousemove --window`, `click --repeat 2`, `mouseup`. Serve para o que
  não vale escrever à mão. As duas ferramentas usam **as mesmas coordenadas**
  (conferido: mesmo pixel para o mesmo ponto relativo).

Detalhes que já custaram tempo:

- **Coordenadas são relativas à janela, e a grade não começa em (0,0)**: com
  lateral (170 px, `SIDEBAR_W`) e barra de abas (~28 px), a sessão começa em
  `y≈58`. Clicar em `y=8` acerta a **barra de abas** — e arrastar ali
  **reordena aba** em vez de selecionar texto.
- **`xwininfo` "Absolute upper-left" é a origem do cliente** (é o que se usa
  para injetar); o `Position` do `xdotool getwindowgeometry` é o **frame** do
  WM — aqui 11/40 px deslocado. Confundir os dois desloca todo clique.
- **Achar a janela por `_NET_WM_PID` tem de pegar a maior visível**: o GTK cria
  ajudantes de 10x10 com o mesmo PID, e a primeira que aparece engana
  (`geometry` devolvia 10x10 e `set_input_focus` estourava `BadMatch`).
- **`import -window root -crop` com geometria de `xwininfo`** só funciona com a
  janela ativada antes; senão captura a janela que estiver por cima.
- **`~`, `^` e `` ` `` são dead keys no ABNT2**: `type '~nome'` digita `~` e o
  `n` compõe `ǹ` — é o comportamento certo do terminal (composição por NFC),
  não falha da ferramenta. Para um til literal, digitar espaço depois.
- **O `.n  Name` e os nomes truncados com `~` no `mc` são do próprio `mc`**
  (conferido nos bytes crus: ele escreve `.n  Name` e trunca conforme a largura
  do painel). Não é bug de renderização.

## Verificação com janela

```
./debug.sh                                  # abre com log em /tmp/bzmux.log
python3 tools/xtest.py key ctrl+shift+n     # workspace novo
python3 tools/xtest.py dclick 60 28         # duplo clique no cartão 1
python3 tools/xtest.py type 'echo ok'       # texto com símbolos
kill -USR1 $(cat /tmp/bzmux.pid)            # dumpar a grade
```

O dump sai em `/tmp/bzmux-dump.txt` (`--dump-to ARQ` troca). Cabeçalhos de
workspace e de aba aparecem só quando há mais de um; o da viewport diz
`(histórico +N)` quando a visão está rolada.

- **O dump mostra a grade VIVA, não a visão rolada.** `dump_text` usa
  `Term.row_text`, então com a visão no histórico as linhas continuam sendo o
  rodapé: conferir o scroll por ele dá falso negativo (o wheel funciona e o dump
  parece parado). O offset só se vê no cabeçalho `(histórico +N)` ou em captura.
- **Página oculta do `Gtk.Notebook` não é realocada.** A view de uma aba ou
  workspace que não está na tela mantém o `size-allocate` **antigo**: abrir a
  lateral estreita a grade (75 → 62 colunas) só na página visível, e as ocultas
  só corrigem quando mapeadas (`on_resize` → `TIOCSWINSZ`/`SIGWINCH`). Ver duas
  views com larguras diferentes no dump é isso, não bug de geometria.
- O app roda no venv do uv, que enxerga o PyGObject do sistema via
  `--system-site-packages`.

## Sondas do app (`PYTERM_*`)

Variável de ambiente na execução do app (não muda código):

- `PROF=1` — ao fechar a sessão, custo de parse (`on_pty`) e desenho
  (`on_draw`), bytes lidos e `eagain`.
- `NODRAW=1` — desliga o desenho (sobra pty → grade).
- `NOPARSE=1` — lê o pty e descarta (isola o IO).
- `GEOM=980x640` — trava o tamanho da janela (senão o WM às vezes abre 80x24).
- `GEOMLOG=1` — cada configure imprime cliente, moldura e frame extents.
- `DIAG=1` — no primeiro draw, avanço da fonte, célula, resolução e colunas.
- `SCROLLLOG=ARQ` — grava chunk que rola mais de meia tela (jump/top/bottom/
  alt-screen + bytes crus).
- `CONFLOG=1` — cada reload de configuração aprovado imprime os valores.

`DIAG` é o par que tem que bater (avanço × célula) — divergência ali é grade
medida numa resolução e desenhada em outra (bug 13 do HISTORY). As sondas de
custo isolam as etapas: `PROF` decompõe a vazão, `NODRAW`/`NOPARSE` cortam um
lado de cada vez. A escada e os números ficam em docs/BENCHMARKS.md.

## Armadilhas de implementação

- **`show_all()` desfaz `set_visible(False)`**: `Gtk.Widget.show_all()` mostra
  todos os descendentes, então um widget escondido no construtor volta a
  aparecer. Para controlar visibilidade na mão, `set_no_show_all(True)` nele.
- **Prioridade de fonte do GLib**: `io_add_watch` sem prioridade explícita usa
  `DEFAULT` (0), que é *maior* que qualquer coisa de desenho. Um fd sempre
  pronto em prioridade 0 congela a tela; `PRIORITY_DEFAULT_IDLE` (200) deixa o
  redraw (120) passar na frente. O mesmo vale para `timeout_add` de animação.
- **`background-color` sozinho não pinta no GTK3**: se o tema põe um
  `background-image` (gradiente) no nó, a cor é ignorada. Regra de CSS que
  precisa de fundo sólido tem de vir com `background-image: none` (foi o que
  fazia o flash do `bell` "não funcionar").
- **O nó CSS `tab` do `Gtk.Notebook` não é o widget do rótulo**: classe no
  rótulo pinta só a área do texto, e `tab:checked` continua mandando no resto.
  `label.get_parent()` devolve o próprio Notebook; o caminho é dar nome próprio
  ao rótulo (`set_name`) e cuidar do padding nele (P34).
- **O despacho do `Gtk.Notebook` é o que desmapeia a página**: é disso que o
  pisca do cursor depende para parar em aba oculta (`unmap`/`map`); se alguém
  trocar o container, o pisca volta a rodar em todas as abas.
- **`cairo` com `FORMAT_A1`** serve para medir fonte, mas `font_extents()`
  devolve **5** valores (ascent, descent, height, max_x_advance,
  max_y_advance) — não 6.
- **Quebra pendente e caracteres de controle**: emulador nenhum deve contar o
  `\n` que vem depois de uma linha cheia como segunda quebra; texto preenchendo
  a última coluna e `\r\n` é o padrão de qualquer TUI que desenha com padding
  até a borda.
- **Célula em branco é compartilhada (P21)**: `_blank_row()` é
  `[_BLANK_CELL] * cols`, e a mesma lista de célula aparece em toda a grade. É
  por isso que escrever tem que **substituir** a célula (`row[x] = [ch, fg, bg,
  fl]`), nunca fazer `row[x][2] = ...`: mutação in-place em uma célula em branco
  pinta a tela inteira. `blank_cell()` (com bg corrente, para `erase_*`) segue
  alocando uma célula nova de propósito.
- **`lista[-0:]` é a lista inteira**, não lista vazia: fatiamento com um teto
  configurável (`[-limit:]`) deixa de cortar quando o limite é 0. Usar
  `del lista[:len(lista) - n]`.
- **`chr(kv)` para keyval de tecla especial não existe**: só `0x20–0x7e`,
  `0xa0–0xff` e `0x01000000+U` são caractere. O resto é modificador/função.

## Medição e perfil

Armadilhas de **medição** (governor da CPU, a carga, o protocolo de comparação)
moram em docs/BENCHMARKS.md. O que aparece ao perfilar e não é medição:

- **`cProfile` não enxerga `gi.FunctionInfo`**: `PangoCairo.show_layout`
  chamado 20.000 vezes num teste isolado não aparece no perfil, e o tempo cai no
  `self` do chamador (já fez `_on_draw` medir 46% de "self" sem nenhuma chamada
  de Pango). Métodos de objeto cairo (`fill`, `rectangle`, `move_to`) aparecem;
  funções de módulo do gi, não. O `cProfile` também infla quem faz muitas
  chamadas Python e derruba o doom-fire. Para proporção, medir com
  `perf_counter` por seção; o perfil serve para descobrir *quais* chamadas
  existem.
- **As primeiras chamadas de `_on_draw` custam mais** (setup de layout, fonte e
  contexto): medir `draw` com centenas de chamadas, ou comparar por razão.
- **Custo de desenho depende de runs, não de células**: a mesma contagem de
  células com uma cor custa uma fração do que custa com dezenas de cores por
  linha. Medir desenho com tela uniforme subestima o pior caso.
- **fps de carga depende da grade**: a vazão em MB/s fica parada e o fps cai
  quando a célula cresce; comparar fps entre grades diferentes não diz nada.
