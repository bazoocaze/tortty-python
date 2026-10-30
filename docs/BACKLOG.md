# bzmux — backlog (pendente)

P19 — Interagindo com o `pi`, a cada algumas etapas do turno a tela reescreve
várias telas de uma vez. **Investigação aberta** (2026-10-25).

Já descartado, com dados: parser/grade. Três turnos reais do `pi` capturados num
pty próprio (respondendo as mesmas queries do bzmux) e replayados em `Term` e
`pyte`: rolagens iguais (32×32, 79×79) e tela final idêntica; o TUI do `pi` não
usa DECSTBM (`CSI r`), IL/DL (`CSI L/M`), SU/SD (`CSI S/T`) nem autowrap-off
(`?7l`) — só `CSI nA/nB/nG`, `CSI 2K`, `CSI 1G`, sync output (`?2026`) e
hyperlinks OSC 8. Também já corrigido o que mascarava sintoma parecido: tique de
1 Hz do `pi` (bug 14) e desenho em resolução errada (bug 13).

Falta o caso real (transcrição longa). Sonda pronta: `PYTERM_SCROLLLOG=ARQ
./run.sh` grava cada chunk que rola mais de meia tela com `jump=N`, `top/bottom`
da região, alt-screen e os 600 primeiros bytes crus. Ler o log e isolar a
sequência; se o log sair vazio, logar `on_resize` (reflow no meio do turno passa
a ser o suspeito). Hipóteses na fila: (a) reimpressão da transcrição inteira
quando um widget do rodapé muda de altura (o observer do `pi-blackhole` escreve
"Observational memory…" no meio da conversa); (b) `CSI 2J` + reimpressão; (c)
resize/reflow entrando no meio do turno.

Estado da investigação (2026-10-29): sonda **conferida** — `PYTERM_SCROLLLOG` só
grava o chunk que rola mais de `max(2, rows // 2)` linhas (teste: `seq 1 5000` →
3 entradas de 33 linhas; `seq 1 200` → nenhuma, porque o salto não passava de
meia tela num chunk). Os dois arquivos (`SCROLLLOG` e `RAWLOG`) são abertos em
append por chunk, então dá para apagar com o app rodando — o `RAWLOG` só passa a
gravar daí pra frente. Falta só a captura do caso real (logs + hora + etapa do
turno). Se o `scroll.log` sair **vazio** e o pulo acontecer, o suspeito vira
`on_resize`/reflow: instrumentar `on_resize` antes de mexer em qualquer outra
coisa.

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
decisão pendente** (2026-10-28). Hoje o app "não tem dependência" no sentido de
não ter nada no `pyproject.toml` — mas tem dependência **de sistema** (GTK3 +
Pango + cairo + PyGObject), que no Linux é grátis em termos marginais porque o
desktop já a paga e cara nos outros dois. Este item guarda os dados levantados e
o custo de cada rota.

### O que é plataforma hoje

`on_draw` (`view.py`, a partir de 524) recebe um cairo_t do `Gtk.DrawingArea` e
faz tudo com cairo + Pango: `cr.paint`, runs, `PangoCairo.create_layout`,
`show_layout`. Nenhuma chamada de X11/Win32/Quartz — o caminho quente é
portátil, e é ele que o BENCHMARKS mede. A dependência de plataforma está em
~10 primitivas de janela: `DrawingArea`, `add_events`, sinal `draw`,
`Gtk.Clipboard`, `Notebook`/`Stack` no cromo, CSS via `StyleContext`. `gui.py` é
o único import. A arquitetura já tem a costura; falta a porta existir.

### Bloqueios concretos no código atual (ordem de gravidade)

1. `gui.py:12` — `gi.require_version("GdkX11", "3.0")` está **fora** do try.
   Sem typelib GdkX11 (mac quartz, Windows win32) o import estoura antes do
   fallback que já existe na linha seguinte. Fix de uma linha.
2. `view.py:767` — wheel só trata `ScrollDirection.UP/DOWN/LEFT/RIGHT`;
   trackpad de mac e touchpad de precisão do Windows chegam como
   `SCROLL_SMOOTH` com delta → `btn is None` → histórico não rola.
3. `view.py:726/743` — botão do meio e cópia usam `SELECTION_PRIMARY`, que não
   existe fora do X11 (degrada silencioso, precisa cair em CLIPBOARD).
4. `view.py:396` — família "Monospace" hardcoded (melhor tabela por OS);
   `get_scale_factor()` nunca é lido (Retina 2x, Windows 150%). A métrica é
   medida do Pango, então a grade se adapta — o teste é o par do `PYTERM_DIAG`
   (avanço x célula x res x cols) rodado em cada OS, o mesmo que pegou o bug 13.

### Fatos verificados (2026-10-28)

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

### Custo de dependência dos dois lados

Os números de pegada (disco do stack e PSS do app nas duas rotas) moram em
[`BENCHMARKS.md`](BENCHMARKS.md), seção de pegada — aqui fica só a conclusão:
no Windows/mac o Qt **não é mais pesado** que levar GTK para lá (a closure do
GTK via conda tem ordem de grandeza parecida); a diferença é quem gerencia. No
Linux o GTK ganha por construção, porque o desktop já o tem carregado.

### Rota A — não mudar lib, mudar o gerenciador (conda-forge)

Um `environment.yml`, `run.sh` deixa de escolher entre venv e python do sistema.
Custo de código: os 4 bloqueios acima. Custo real: ~350-400 MB de ambiente,
visual GTK nas três plataformas (o cromo sempre parece o tema do OS) e
`uv tool install` fica impossível.

### Rota B — trocar GTK3 por Qt/PySide6

Única que dá instalação pip e visual uniforme. O que **não** muda: `term.py`,
`palette.py`, `mouse.py`, `kitty_kbd.py`, `graphics.py`, `style.py` e os checks.
O que muda: `view.py` (draw/eventos/clipboard) e `window.py` (abas/workspaces),
mais `keys.py` (constantes de tecla). Equivalências mapeadas: métrica =
`QFontMetricsF.horizontalAdvance("M")` + `height()`; o truque de
`letter_spacing` tem par direto em `QFont.setLetterSpacing(AbsoluteSpacing,
cw - advance)`; `pixelDelta` resolve o wheel smooth de graça; HiDPI é do Qt;
chrome desenhado em `paintEvent` fica idêntico nos três (mata o "cromo").
`uv tool install bzmux` exige trabalho de empacotamento que hoje não existe:
diretório de pacote com nome publicável (hoje o código vive em `core/` e o
pyproject declara `package = false`), `[build-system]` e
`[project.scripts] bzmux = "...:main"`. O `--selftest` e o `-h` têm de continuar
rodando sem importar Qt (mesma disciplina de import tardio do `cli.py`).

LGPLv3 (PySide6) não contamina o projeto: o código continua MIT, não há
obrigação de abrir o fonte, e a exigência concreta é (a) Qt trocável —
bibliotecas dinâmicas separadas, nunca onefile congelado — e (b) aviso +
texto da licença junto da distribuição; (c) nada de módulo GPL-only (ficar no
Essentials) e nada de PyQt. Anti-tivoization só morde em aparelho lacrado.

### `uv tool install` / pipx hoje — estado real (2026-10-28)

A versão atual **não** permite nenhum dos dois, e não é só por empacotamento:

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

### Rota C — cairo desenhando sobre QImage (descartada por ora)

O `on_draw` não mudaria uma linha: `cairo.ImageSurface.create_for_data` sobre o
buffer de um `QImage` (o projeto já faz isso para imagens do kitty em
`graphics.py`) e o Qt hospedaria janela/eventos/blit. Custa um memcpy de frame
(~250 KB em 1920 células) e **não resolve distribuição**: Pango continuaria
necessário. Só serve como estágio intermediário da rota B.

### Decisão pendente

A pergunta que precede código: **cairo + Pango é identidade do projeto ou
detalhe de implementação?** Identidade → rota A (conda) é a única que preserva.
Implementação → rota B, e o caminho de menor risco é uma porta fina (backend
GTK3 atual + backend Qt), porque aí dá para medir os dois lado a lado e o
`bench.sh` continua valendo na transição — é ela que responde com número se o
Qt é mais rápido que o cairo/Pango no caminho quente.

Se a rota B acontecer, o BENCHMARKS passa a ter número por backend e o piso de
comparação ganha dois parâmetros novos: família da fonte e scale factor
(rasterização CoreText/DirectWrite/FreeType mudam avanço e hinting; a grade
continua correta porque é medida, mas os fps não são comparáveis entre OS).

Verificação mínima em cada OS: `--selftest` (sem display), `PYTERM_DIAG=1`
(avanço x célula x res x cols batendo), wheel com trackpad, colar do clipboard,
seleção com botão do meio e `./bench.sh` — este último só onde houver leitura
de governor/frequência (no mac e no Windows vira outro protocolo, não uma
linha da escada atual).

Os itens P1–P25, P28, P29 e P31 estão concluídos. Histórico, bugs e quirks:
[HISTORY.md](HISTORY.md). Status e por onde retomar:
[../TASK-bzmux.md](../TASK-bzmux.md).

O que sobra é limite conhecido, não item — caractere largo (CJK/emoji) ocupando
uma célula só, protocolo de teclado do kitty parcial, sequências não
interpretadas, sem configuração/tema — tudo em
[LIMITATIONS.md](LIMITATIONS.md).
