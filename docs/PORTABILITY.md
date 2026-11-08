# pybzmux — portabilidade gráfica (P30)

Estudo aberto: rodar em Linux, Windows e macOS. Item na fila:
[BACKLOG.md](BACKLOG.md). Limites de plataforma já aceitos:
[LIMITATIONS.md](LIMITATIONS.md). Pegada dos dois stacks, PSS e disco:
[BENCHMARKS.md](BENCHMARKS.md).

Fato datado aqui é retrato daquele dia, não leitura corrente: o que mudou desde
então está anotado no próprio texto.

## O que é

O app não declara dependência nenhuma no `pyproject.toml`, mas tem dependência
**de sistema** (GTK3 + Pango + cairo + PyGObject): no Linux é grátis em termos
marginais, porque o desktop já a paga, e cara nos outros dois. Este artigo guarda
os dados levantados e o custo de cada rota.

## O que é plataforma hoje

`on_draw` (`view.py`) recebe um cairo_t do `Gtk.DrawingArea` e
faz tudo com cairo + Pango: `cr.paint`, runs, `PangoCairo.create_layout`,
`show_layout`. Nenhuma chamada de X11/Win32/Quartz — o caminho quente é
portátil, e é ele que o BENCHMARKS mede. A dependência de plataforma está em
~10 primitivas de janela: `DrawingArea`, `add_events`, sinal `draw`,
`Gtk.Clipboard`, `Notebook`/`Stack` no cromo, CSS via `StyleContext`. `gui.py` é
o único import. A arquitetura já tem a costura; falta a porta existir.

## Bloqueios concretos no código atual (ordem de gravidade)

1. `gui.py` — `gi.require_version("GdkX11", "3.0")` está **fora** do try.
   Sem typelib GdkX11 (mac quartz, Windows win32) o import estoura antes do
   fallback que já existe na linha seguinte. Fix de uma linha.
2. `view.py` — wheel só trata `ScrollDirection.UP/DOWN/LEFT/RIGHT`;
   trackpad de mac e touchpad de precisão do Windows chegam como
   `SCROLL_SMOOTH` com delta → `btn is None` → histórico não rola.
3. `view.py` — botão do meio e cópia usam `SELECTION_PRIMARY`, que não
   existe fora do X11 (degrada silencioso, precisa cair em CLIPBOARD).
4. `view.py` — família "Monospace" hardcoded (melhor tabela por OS);
   `get_scale_factor()` nunca é lido (Retina 2x, Windows 150%). A métrica é
   medida do Pango, então a grade se adapta — o teste é o par avanço × célula
   que o `state` do socket devolve
   (avanço x célula x res x cols) rodado em cada OS, o mesmo que pegou o bug 13.

## Fatos verificados (2026-10-28)

- PyGObject **não tem wheel em lugar nenhum**: PyPI publica só sdist
  (3.58.1). `pip install pygobject` = compilar contra headers, sempre.
- pycairo 1.29.2: wheels win32/win_amd64/win_arm64 e **zero de macOS** (sdist).
- conda-forge cobre a matriz inteira: gtk3 3.24.52, pango 1.58.2, pygobject
  3.58.1, pycairo 1.29.2, gdk-pixbuf 2.44.8 para linux-64, osx-64, osx-arm64,
  win-64. Pango nunca será pip-installable.
- PySide6-Essentials 6.12: wheels manylinux_2_34 (x86_64/aarch64), win_amd64/
  arm64, macosx_14_0 universal2. Pisos: glibc 2.34+, macOS 14 (6.10 = 13,
  6.8.3 = 12), Python >= 3.10. Tamanho: 82 MB (win), 84 MB (linux), 116 MB
  (mac) de wheel; 244 MB instalado (medido). PyQt6 é GPL — fora.
- **Qt6 no Linux ainda tem dependência de sistema**: sem `libxcb-cursor0` o
  plugin xcb não carrega ("Could not load the Qt platform plugin xcb");
  reproduzido nesta máquina. Ou seja, "pip e roda" é verdade no Windows/mac,
  e quase-verdade no Linux (X11 precisa desse pacote; Wayland não).

## Custo de dependência dos dois lados

Os números de pegada (disco do stack e PSS do app nas duas rotas) moram em
[`BENCHMARKS.md`](BENCHMARKS.md), seção de pegada — aqui fica só a conclusão:
no Windows/mac o Qt **não é mais pesado** que levar GTK para lá (a closure do
GTK via conda tem ordem de grandeza parecida); a diferença é quem gerencia. No
Linux o GTK ganha por construção, porque o desktop já o tem carregado.

## Rota A — não mudar lib, mudar o gerenciador (conda-forge)

Um `environment.yml`, `run.sh` deixa de escolher entre venv e python do sistema.
Custo de código: os 4 bloqueios acima. Custo real: ~350-400 MB de ambiente,
visual GTK nas três plataformas (o cromo sempre parece o tema do OS) e
`uv tool install` fica impossível.

## Rota B — trocar GTK3 por Qt/PySide6

Única que dá instalação pip e visual uniforme. O que **não** muda: `term.py`,
`palette.py`, `mouse.py`, `kitty_kbd.py`, `graphics.py`, `style.py` e os checks.
O que muda: `view.py` (draw/eventos/clipboard) e `window.py` (abas/workspaces),
mais `keys.py` (constantes de tecla). Equivalências mapeadas: métrica =
`QFontMetricsF.horizontalAdvance("M")` + `height()`; o truque de
`letter_spacing` tem par direto em `QFont.setLetterSpacing(AbsoluteSpacing,
cw - advance)`; `pixelDelta` resolve o wheel smooth de graça; HiDPI é do Qt;
chrome desenhado em `paintEvent` fica idêntico nos três (mata o "cromo").
O empacotamento que faltava (`[build-system]`, `[project.scripts]`) foi feito
no P31; o que resta contra o `uv tool install` é a dependência de sistema, que
ele não aceita (ver abaixo). O `--selftest` e o `-h` têm de continuar rodando
sem importar Qt (mesma disciplina de import tardio do `cli.py`).

LGPLv3 (PySide6) não contamina o projeto: o código continua MIT, não há
obrigação de abrir o fonte, e a exigência concreta é (a) Qt trocável —
bibliotecas dinâmicas separadas, nunca onefile congelado — e (b) aviso +
texto da licença junto da distribuição; (c) nada de módulo GPL-only (ficar no
Essentials) e nada de PyQt. Anti-tivoization só morde em aparelho lacrado.

## `uv tool install` e pipx (2026-10-28)

Na data do levantamento nenhum dos dois funcionava. O P31 resolveu o
empacotamento (`pipx install --system-site-packages` é o que o `install.sh` usa
hoje); o que continua valendo é a limitação do `uv tool`:

- Sem `[project.scripts]` o wheel sai sem `entry_points.txt` e o uv recusa:
  `No executables are provided by package bzmux; removing tool`. E o `uv build`
  **não falha**: cai num setuptools legado e produz um wheel com
  `top_level = core` (nome genérico, colide no site-packages) e **sem o
  `bzmux.py`** — armadilha: parece empacotável e não é.
- `uv tool install` cria o venv da ferramenta com `system_site_packages`
  **hardcoded em false** (`crates/uv-tool/src/lib.rs`), então `import gi`
  falha dentro do tool env. Posição do mantenedor (#13757): *"We don't support
  using system site packages in tools yet"*, com a sugestão
  `uv tool install --with <dep>` — que não serve para PyGObject (sdist).
  Pedido aberto: #18303; PR aberto que grava a flag no receipt: #18023.
- Contorno usado na prática: `uv tool install --python /usr/bin/python3` e
  depois `sed -i 's/include-system-site-packages = false/... = true/'
  "$(uv tool dir)/<tool>/pyvenv.cfg"`. Verificado aqui: passa a ver gi 3.48.2 e
  pycairo 1.25.1, e um `uv tool upgrade` preservou o ajuste. É `sed` em arquivo
  interno do uv — não é caminho para recomendar a usuário.
- Alternativas reais: `pipx install --system-site-packages` (funciona hoje) ou
  venv manual com `uv venv --system-site-packages` + symlink do script (o mesmo
  padrão que o `run.sh` já usa).

Consequência para a decisão: o "um comando" do Linux é pipx ou distro/flatpak,
nunca `uv tool`, enquanto a dependência for binding de sistema. Com Qt, o
`uv tool install` passa a ser verdade sem flag nenhuma.

## Rota C — cairo desenhando sobre QImage (descartada por ora)

O `on_draw` não mudaria uma linha: `cairo.ImageSurface.create_for_data` sobre o
buffer de um `QImage` (o projeto já faz isso para imagens do kitty em
`graphics.py`) e o Qt hospedaria janela/eventos/blit. Custa um memcpy de frame
(~250 KB em 1920 células) e **não resolve distribuição**: Pango continuaria
necessário. Só serve como estágio intermediário da rota B.

## Decisão (revista em 2026-11-01)

- **Python é escolha inicial, não identidade.** O experimento provou que dá para
  fazer um terminal inteiro em Python (foi assim que o app nasceu e é usado);
  provou isso, não que a linguagem seja obrigatória. Núcleo nativo em Rust/C não
  está descartado por princípio.
- **cairo + Pango também é escolha inicial**, revisável por requisito
  (distribuição, GPU, plataforma).
- Pontos em jogo, só registrados (não são requisitos fixados): OS alvo;
  features do alvo (splits, aviso de atenção, CLI); vazão/latência; forma de
  instalar (pip/`uv tool`, sem conda). O alvo cmux é macOS sobre Ghostty (GPU):
  se o alvo for ele, macOS e renderização acelerada entram na conversa e as
  rotas hoje fora voltam ao páreo.

Consequências que ficam valendo:

- Rota A (conda) existe para quem quer preservar Pango; rota B é o caminho
  quando o alvo é Windows/macOS, com porta fina (backend GTK3 atual + backend
  Qt) para medir os dois lado a lado.
- PyPy (P38) vira medição do caminho quente, não caminho de aplicação: sem
  `gi`, só com bindings cffi.
- GPU: o cairo desenha na CPU. Se renderização acelerada virar requisito (é o
  que Ghostty/cmux usam), ela não sai do stack atual — é uma das rotas a pesar,
  não um limite já aceito.
- Alvo de produto, se for clone do cmux (abas verticais, splits, aviso quando o
  agente pede atenção, CLI): abas verticais já existem como cartão de workspace,
  a CLI já é o socket de introspecção, splits são o P39 e o aviso depende de
  `OSC 9`/`OSC 777`, hoje não atendidos.

Se a rota B acontecer, o BENCHMARKS passa a ter número por backend e o piso de
comparação ganha dois parâmetros novos: família da fonte e scale factor
(rasterização CoreText/DirectWrite/FreeType mudam avanço e hinting; a grade
continua correta porque é medida, mas os fps não são comparáveis entre OS).

Verificação mínima em cada OS: `--selftest` (sem display), as métricas do
`state` pelo `--debug-socket`
(avanço x célula x res x cols batendo), wheel com trackpad, colar do clipboard,
seleção com botão do meio e `./bench.sh` — este último só onde houver leitura
de governor/frequência (no mac e no Windows vira outro protocolo, não uma
linha da escada atual).
