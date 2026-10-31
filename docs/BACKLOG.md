# bzmux — backlog (pendente)

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

Os demais itens (P1–P25, P19, P28, P29, P31 e P32) estão concluídos. Histórico, bugs e quirks:
[HISTORY.md](HISTORY.md). Status e por onde retomar:
[../TASK-bzmux.md](../TASK-bzmux.md).

O que sobra é limite conhecido, não item — caractere largo (CJK/emoji) ocupando
uma célula só, protocolo de teclado do kitty parcial, sequências não
interpretadas, sem configuração/tema — tudo em
[LIMITATIONS.md](LIMITATIONS.md).

P33 — Arquivo de configuração (fonte, paleta, shell, atalhos). **A implementar**
(2026-10-29). Hoje tudo é fixo no código e quem quiser mudar edita o módulo:
família `Monospace` e `font_size=13` (`view.py:101`, `:463`), paleta de 256 cores
(`palette.py`), tokens de cor do cromo + CSS (`style.py`), teto do scrollback de
1000 linhas (`term.py:278`, `:322`), shell (`view.spawn` usa `SHELL`, cai em
`/bin/bash`), atalhos (`window.handle_shortcut`) e geometria
(`state.py`, que continua sendo estado, não configuração).

O que o item pede:

- flag `-c ARQ` / `--config ARQ` para apontar outro arquivo (o caminho default
  continua valendo quando ela não vem);
- um arquivo **default** que embarca com o pacote (ao lado de `bzmux/data/`,
  que já leva o ícone) com todas as opções e os valores de fábrica — o que o
  usuário não escrever sai dali, não de `if`s no código;
- formato do kitty: `chave valor`, um por linha, `#` comenta até o fim da linha,
  espaço em branco nas pontas ignorado; chave desconhecida não derruba nada;
- opção `shell`, default `bash`;
- `Ctrl+Shift+F2` abre o arquivo de configuração **numa aba nova com o `vim`**
  (o atalho está livre: `Ctrl+Shift` hoje só usa `t`, `w`, `n`, `q` e
  `1..9`; `Super` só `n`/`q`);
- **auto-reload** ao salvar, com validação antes de aplicar.

Decisões de projeto que o item carrega (resolver ao implementar, não no chute):

- **módulo puro `bzmux/config.py`**, sem `gi`: parse → dict, merge com o default,
  validação de tipo/faixa, e um objeto final que o resto lê. Isso mantém o
  caminho testável sem display (regra do `--selftest`) e é o mesmo módulo que a
  rota B do P30 (Qt) reaproveitaria;
- precedência: valor do usuário > valor do arquivo default > nada (erro de
  chave obrigatória nunca acontece, porque o default cobre tudo);
- **arquivo inválido não aplica nada**: mantém a configuração anterior e
  reclamar de forma visível (uma linha no log e a aba/título marcado é
  suficiente — decidir na hora). Validação ANTES de trocar qualquer coisa:
  parse inteiro, tipos, faixas (tamanho de fonte > 0, cor no formato aceito,
  `shell` que existe e é executável);
- **reload**: `Gio.FileMonitor` (o `gi` já está em `gui.py`; se preferir não
  somar Gio, `GLib.timeout_add_seconds` comparando mtime — o monitor é melhor
  porque não acorda o app à toa) com debounce, porque editor que salva por
  rename gera 2–3 eventos;
- o que pode ser quente e o que não: cor e paleta (redesenha), fonte/tamanho
  (re-mede a célula e faz `Term.resize` com o mesmo número de colunas/linhas
  que caiba — o reflow já existe), scrollback (passa a valer para as próximas
  linhas), atalhos (imediato), `shell` (só na próxima aba). Geometria fica no
  `state.py`: é estado de execução, não configuração.

Consequências fora do módulo: `cli.parse_args` ganha um valor a mais e hoje
devolve uma tupla de 4 campos — o check `argv_parsing` muda junto; `TermView`
passa a receber fonte/tamanho de fora; `window` passa a ler atalhos de um mapa
em vez de literais no `if`. Quando fechar, saem (ou encolhem) dois limites do
`docs/LIMITATIONS.md`: "sem arquivo de configuração/tema" e "sem remapeamento de
teclas".

Verificação: checks puros (parse com comentário/espaço/valor com espaço, merge
com o default, chave desconhecida ignorada, arquivo inválido mantém o anterior,
`-c` vence o default) + à mão, com display: editar o arquivo com o app aberto e
ver a cor mudar sem reiniciar, salvar lixo e ver a config anterior continuar,
`Ctrl+Shift+F2` abrindo o `vim` na aba nova, e `bzmux -c outro.conf`.
