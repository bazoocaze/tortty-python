# pybzmux — limites

O que o pybzmux **não** faz, e por quê. Separado do backlog (que é fila de
trabalho, em [BACKLOG.md](BACKLOG.md)): aqui só entra o que é decisão
ou consequência aceita do escopo. Se algo desta lista virar tarefa, sai
daqui e vira item lá.

Cada linha diz o limite, a razão e a consequência prática. Formato pensado para
consulta por grep, não para leitura corrida. Visão geral do projeto:
[../README.md](../README.md). Números de medição: [BENCHMARKS.md](BENCHMARKS.md).

## Desempenho (o custo do caminho em Python)

- **Vazão de poucos MB/s, contra ~6x mais do kitty na mesma carga** — não é bug,
  é a medida, e o par (com data, governor, frequência e a escada que o decompõe)
  está em [`BENCHMARKS.md`](BENCHMARKS.md). Depois do P20–P22 o IO do pty deixou
  de ser gargalo; sobra o **parse em Python** e o **desenho**, nessa ordem.
- **Interação não sofre**: tecla custa microssegundos; o limite só aparece em
  volume (cat de log grande, seq 100000, scroll de saída massiva).
- **Um core por sessão ativa**: sob despejo contínuo o pybzmux satura um core. O
  desenho é coalescido em ~16 ms (60 Hz) de propósito, para o parse não morrer
  de fome.
- **A metadata não faz claim de desempenho**: a descrição do pacote diz o que o
  app tem (abas, workspaces, imagens), não "leve" nem "rápido". Leve é verdade
  em **pegada** (o número está em [`BENCHMARKS.md`](BENCHMARKS.md)) e falso em
  vazão, que é o limite acima; claim de velocidade viraria promessa que a
  própria régua desmente.

## Modelo de célula e texto

- **Sem `wcwidth`**: caractere largo (CJK, emoji) ocupa **uma** célula. O glifo
  é desenhado na largura da célula: app que conta coluna dupla (tabela em CJK,
  `vim` com wide chars) sai desalinhado. Resolver exige mexer no modelo de
  célula, não no desenho.
- **Sem combinação de célula para grafema complexo**: cada célula carrega um
  caractere; marca combinante é desenhada pelo Pango, mas não ocupa célula
  própria nem altera a contagem de colunas do app.
- **Ligadura depende da fonte instalada**: o shaping existe (Pango) e a família
  agora é configurável (`font_family`), mas a Monospace padrão da máquina
  (DejaVu) quase não tem ligadura — quem quiser precisa ter uma Fira Code ou
  JetBrains instalada e escolhê-la. Não há `font_features`/`letter_spacing`
  ligados por opção.

## Parser VT (o que não é interpretado)

- **SGR parcial**: implementa 0, 1, 4, 7, 22, 24, 27, 30–37, 39, 40–47, 49,
  90–97, 100–107, 38/48 (256 e truecolor). **Não** implementa 2 (meia
  intensidade), 3 (itálico), 5 (pisca), 8 (oculto), 9 (riscado), 21, 53
  (overline), 58/59 (cor do sublinhado). Quem usa 9 (git diff em alguns temas,
  `bat`) fica sem o risco.
- **Bold não vira cor clara**: com paleta de 8/16 cores, `SGR 1` só engrossa o
  glifo; não há "bold as bright" (que o xterm faz).
- **Sem `DECAWM` desligado**: autowrap é sempre ligado; `CSI ? 7 l` é ignorado.
- **Sem origem/margens especiais**: `DECSTBM` (região de scroll) funciona, mas
  `? 6` (origin mode), `? 3` (80/132), `DECDHL`/`DECDWL` (linha dupla) não.
- **Sem `REP`** (`CSI b`), sem `DECSTR` (`CSI ! p`) e sem `HTS`/`TBC` (tab stop
  é fixo de 8 em 8).
- **Sem double buffering de paleta**: `OSC 4` só responde consulta; não redefine
  entrada da paleta, e `OSC 104/110/111` (reset) são ignorados.

## OSC (o que não é atendido)

- **Sem `OSC 52`** (clipboard): copiar do app para o sistema não vai pela
  sequência — só pela seleção do mouse (que é local).
- **Sem `OSC 8`** (hyperlink): a sequência é consumida e descartada; link não
  fica clicável.
- **Sem `OSC 7`** (cwd do shell) e sem `OSC 133` (marcas de prompt): o título da
  aba vem de `OSC 0/2`, não do diretório nem de integração de shell.
- **Sem notificações** (`OSC 9`, `OSC 777`).

## Mouse e seleção

- **Seleção só por célula**: sem duplo-clique por palavra, sem triplo-clique por
  linha, sem modo bloco/retangular.
- **Sem barra de rolagem clicável**: histórico é teclado (Shift+PgUp/PgDn/Home/
  End) e wheel; o `↑N` no canto é só indicador.
- **Sem busca no scrollback**.
- **Sem protocolo de mouse em pixels** (`? 1016`) nem modo de mouse estendido do
  urxvt além do SGR/UTF-8/legado já suportados.
- **Seleção não sobrevive a resize nem a reflow**: âncora e ponta são
  coordenadas da grade.

## Teclado

- **Protocolo do kitty parcial**: sem `report alternate keys` (flag 4 — o Gdk
  não entrega o keysym alternativo direto), sem repeat distinguido de press (o
  Gdk repete como key-press) e sem o modo de teclado numérico.
- **Layouts não-US**: a tradução keyval→bytes é por tabela; texto vem do
  `ev.string` do Gdk quando existe, mas atalhos com teclas mortas e layout
  exótico dependem do que o Gdk entrega.
- **Sem remapeamento de teclas**: os atalhos são fixos em `bzmux/window.py`,
  consequência de não haver arquivo de configuração.
- **Congelar o output (`Ctrl+S`/`Ctrl+Q`) é do tty, não do terminal**: quem
  para e retoma a entrega de bytes é a *line discipline* do kernel (`IXON` no
  termios). O app só entrega `0x13`/`0x11` ao filho — e é por isso que não
  funciona em app em modo raw (`vim`, `mc`, `pi`): eles limpam `IXON`, e todo
  terminal se comporta assim. Um "pause" nosso (parar de ler o pty) mudaria a
  semântica e não é feito.

## Gráficos (protocolo de imagens)

- **Sem animação e sem z-index**: `a=f`/`a=a` são ignorados, `z=` não existe;
  imagem vai em ordem de chegada, por cima do texto e abaixo do cursor.
- **Sem fonte externa de dados**: `t=f` (arquivo), `t=t` (temp file) e `t=s`
  (shared memory) não são lidos — a imagem tem que vir no escape base64.
- **Sem `f=100` otimizado além do PNG**: PNG é lido direto pelo cairo; RGBA
  cru passa por uma cópia por causa do stride.
- **Sem sixel e sem iTerm2 inline images**: só o protocolo do kitty.

## Reflow e histórico

- **Reflow só no buffer principal**: em alt-screen (`mc`, `vim`) o resize
  recorta/preenche de propósito — quem está em tela cheia se redesenha sozinho
  no SIGWINCH, e re-quebrar por cima do que ele escreveu atrapalharia.
- **Histórico limitado**: o scrollback tem teto de linhas; o que sai não volta.
- **Imagem no histórico é podada** quando a linha a que pertence sai do
  scrollback.
- **O histórico não volta sozinho ao vivo**: depois de rolar, a visão fica
  ancorada na linha (absoluta) que você parou de ler até uma ação sua — rolar
  até o fim, uma tecla, ou o app limpar o histórico (`CSI 3J`). Descartados por
  decisão: retorno por tempo (5 s sem rolar mede a coisa errada: ler é
  silencioso, e um app que escreve a cada 1 s arrancaria o usuário assim que o
  prazo vencesse) e *sticky bottom* (voltar quando a visão está a ≤1 linha do
  fim) — este último cabe no futuro sem mudar a âncora.

## Interface

- **Posição da janela só é lembrada no X11**: no Wayland o cliente não escolhe
  onde a janela fica, então o arquivo de estado guarda apenas tamanho e
  maximizado. Não é falta de código, é o protocolo.
- **Sem tema nem paleta configurável**: o arquivo de configuração (P33/P34)
  cobre fonte, tamanho, cursor, histórico, padding, bell e cópia, mas **cor** do
  terminal (`palette.py`) e do cromo (`style.py`) continuam fixas no código —
  mudar exige editar e reiniciar. Paleta e remapeamento de atalhos são o que
  falta; fonte em **pontos** (convenção de terminal, convertidos pelo DPI do
  display), não pixels.
- **Sem abas/workspaces persistentes**: abas e workspaces vivem só na execução;
  fechar a janela perde o layout.
- **Sem modo de cópia/scrollback**: sem editor de texto sobre o histórico.
- **Sem menu de contexto**: nada de menu na lateral ou na aba, e aba não se
  reordena arrastando.
- **Sem DnD de arquivo** na janela.

## Escopo (decisão, não falta)

- **Não é produto distribuído**: nasceu como experimento para medir o custo do
  caminho quente em Python e virou aplicação real de uso diário. Tem pacote
  instalável (`pipx` ou `install.sh`, item P31), mas não tem release, PyPI,
  instalador para outra plataforma, versionamento semântico nem suporte.
- **Só Linux, com GTK3 do sistema**: o PyGObject e o cairo vêm da distro e o
  cromo é GTK3 — macOS e Windows exigiriam levar o stack inteiro, o que é o
  estudo do P30 em [PORTABILITY.md](PORTABILITY.md). Não é portabilidade
  prometida para depois; é onde ele roda.
- **Python puro é decisão, não pendência**: o experimento perguntou se dava
  para fazer um terminal inteiro em Python e a resposta foi sim — ele é usado
  no dia a dia assim. O teto de vazão (~6x o kitty) é o preço aceito, e se
  ataca otimizando o caminho em Python (parse, desenho), não reescrevendo em C.
- **Núcleo nativo (C ou Rust) não entra**: já foi tentado antes, no experimento
  irmão que embute o núcleo do kitty como lib C: ~4,9 mil linhas de C escrito à
  mão e 68 commits em 6 dias, e os bugs caros foram de **fronteira**, não de
  VT — a tecla indo duas vezes ao pty ao fundir a instrumentação, e o frame de
  atraso que passou por "não é do app" e custou dois dias para achar, com
  métricas falsas de até 1,6 s criadas pelo próprio instrumento. O mesmo app em
  Python saiu em ~3,5 mil linhas, mais rápido e com mais escopo. Atravessar a
  fronteira (ABI, estado duplicado, debug em duas linguagens, teste que exige
  build) cobra mais do que o pedaço de código que evita. Se a vazão virar
  prioridade, a rota é otimizar o Python (P26/P27) ou reescrever o núcleo no
  mesmo repositório e na mesma linguagem — não colar um núcleo alheio.
- **Um usuário, uma máquina**: nada de multiplexação de sessão, servidor, ou
  reconexão.
