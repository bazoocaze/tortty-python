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

P28 — Seleção com o mouse: clique de 1 char e âncora no scroll. **Na fila**;
scroll decidido: **desfazer a seleção ao rolar** (opção B, 2026-10-27). Dois sintomas, mesma raiz: a seleção vive em coordenadas da
**tela** (`y` de `visible_rows()`), não do conteúdo.

1. **Clique sem arrastar seleciona 1 caractere.** `on_button_press` faz
   `sel_start = sel_end = (row, col)` e já pinta a célula em reverso; no
   `on_button_release` o `copy(PRIMARY)` roda mesmo sem arrasto e **sobrescreve
   o PRIMARY do usuário com 1 char**. Um clique que devia só dar foco/limpar a
   seleção deixa um destaque na tela e estraga o "colar com o botão do meio".
   Não existe `n_clicks`: duplo clique = dois cliques de 1 char (não há seleção
   por palavra/linha).
2. **Rodar a tela mantém a seleção na linha física.** `sel_range()` devolve
   `(r1, c1, r2, c2)` em linhas visíveis e `_in_sel()` compara com o `y` do
   draw; `scroll_view()` muda `view_off` sem tocar na seleção, então o destaque
   fica na mesma posição da tela e passa a cobrir **outro texto**. Pior: o
   `copy()` seguinte usa `rows = visible_rows()` com o `view_off` novo, então
   copia o texto errado. Um clique no histórico (`back_to_live()`) também volta
   ao vivo antes da seleção — hoje não dá para selecionar histórico com o
   mouse.

Opções para o scroll — **(B) escolhida** (2026-10-27):

- **(A) ancorar a seleção no conteúdo** — **descartada**: guardar a linha
  absoluta (`len(scrollback) - view_off + y`) em vez do `y` da tela, com o
  destaque andando junto com o texto ao rolar (é o que xterm/kitty fazem). Custo
  médio e uma âncora que o experimento não tem onde guardar: o índice absoluto
  muda quando o `scrollback` cresce com a seleção viva, e reflow/resize
  invalidam tudo. Não se paga aqui.
- **(B) desfazer a seleção ao rolar** — **escolhida**: `scroll_view()` limpa
  `sel_start`/`sel_end` quando `view_off` muda. Três linhas, comportamento
  previsível, e resolve o "copia o texto errado" por construção. Perde a
  seleção ao rolar, o que é aceitável para um experimento.

Para o clique, independente do scroll: só criar seleção quando houver
arrasto (`on_motion` com botão pressionado) e não copiar no release se
`sel_start == sel_end`; no press, limpar a seleção anterior e dar foco. Se
duplo clique for desejado, é item à parte (palavra), não precisa entrar aqui.

Verificação (manual, com display): `tools/xtest.py` — `click` numa célula e
conferir no dump (`kill -USR1`) que não sobrou reverso e que o PRIMARY não
mudou (`xclip -o -selection primary`); `drag` e depois `wheel` — o destaque tem
de sumir; `copy` depois do wheel não pode devolver texto de outra linha. `core/checks.py` cobre `selection_text` puro,
mas não o estado da view (precisa de Gtk).

P29 — `Alt+Backspace` (e `Alt` nas teclas de `SIMPLE`) não manda o prefixo
`ESC`. **Na fila** (2026-10-27). No kitty e no ghostty, no `zsh`, `Alt+Backspace`
apaga a palavra à esquerda; no bzmux age como `Backspace` puro (apaga 1 char).

Causa: `encode_key()` (`core/keys.py`) trata `kv in SIMPLE` antes de qualquer
coisa e devolve `SIMPLE[kv]` **sem olhar o `alt`** — o `"\x1b" + s` só existe no
ramo dos imprimíveis e das dead keys. `BackSpace` está em `SIMPLE` como
`"\x7f"`, então Alt+Backspace sai igual a Backspace. O `zsh` liga
`backward-kill-word` em `"^[^?"` (ESC DEL) por padrão — que é o que xterm,
kitty e ghostty mandam nesse caso. No protocolo do kitty (flag 1,
`disambiguate`) o caminho é outro (`CSI 127;3u`), mas o `zsh` não fala esse
protocolo: o conserto é no caminho legado.

Mesma raiz, provavelmente o mesmo sintoma: `Alt+Tab`, `Alt+setas`,
`Alt+Home/End`, `Alt+F1..F12` e `Ctrl+Alt+letra` (que cai em
`chr(kv & 0x1f)` sem ESC). O escopo do fix é decidir se `Alt` prefixa `ESC` em
todas as sequências (como xterm faz) ou só nas de `SIMPLE`, tomando cuidado com
o que já tem tratamento próprio: `Shift+Tab` (`\x1b[Z`) e o `APP_CURSOR`
(DECCKM), para não sair `ESC ESC [ Z` nem perder o `\x1bO`.

Verificação (manual, precisa de display): dentro do bzmux, `cat -v` e apertar
`Alt+Backspace` — tem de aparecer `^[^?` (hoje aparece `^?`); no `zsh`, digitar
duas palavras e apertar `Alt+Backspace` — apaga a palavra, como no kitty.
`tools/xtest.py key alt+BackSpace` injeta a tecla. `keys.py` fica fora do
`--selftest` por depender das constantes do Gdk, então não entra em
`core/checks.py`.

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

### Custo de dependência dos dois lados (medido)

- GTK3 atual: closure de pacotes no Debian = 210 instalados, 346 MB em disco
  (dominado por fontes e ICU), mas **já pago pelo desktop**. Custo marginal
  medido no app rodando: PSS total 17 MB, dos quais ~2 MB do stack
  gtk/pango/cairo/freetype/python (o resto é compartilhado e residente).
- Qt: 244 MB em disco, sem compartilhamento num desktop GTK. App trivial
  (QWidget + QFontMetricsF, offscreen): PSS total 50 MB, dos quais 23 MB de
  libs PySide6.
- Conclusão dos números: no Windows/mac o Qt **não é mais pesado** que levar
  GTK para lá (a closure do GTK via conda tem ordem de grandeza parecida); a
  diferença é quem gerencia. No Linux o GTK ganha por construção, porque o
  desktop já o tem carregado.

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

P31 — Empacotamento para `pipx install` **a partir do GitHub**. **Na fila**
(2026-10-28). Independente do P30: resolve **só o Linux** (onde o `gi` vem do
sistema). Sem PyPI por enquanto — a instalação é
`pipx install --system-site-packages "git+ssh://git@github.com/bazoocaze/pybzmux.git"`.
Hoje o `pipx` não consegue instalar porque o wheel sai errado e não existe
executável — o diagnóstico está no P30. O nome `bzmux` está livre no PyPI
(verificado: HTTP 404), o que fica registrado para quando/se houver release.

O que falta, em ordem de dependência:

1. **Layout.** `core/` → `bzmux/` e **apagar o `bzmux.py` da raiz** (ficaria
   sombreado pelo diretório). Ganha `bzmux/__main__.py` para o `python -m
   bzmux` funcionar em `run.sh` e `run-tests.sh`. Os imports internos já são
   todos relativos: renomear diretório não mexe no código. Manter `core/` como
   nome do pacote está fora: `top_level = core` no site-packages é colisão
   garantida (e foi o que o wheel atual gerou).
2. **pyproject.** `[build-system]` explícito (hatchling com
   `packages = ["bzmux"]`, ou `uv_build` com `module-root`),
   `[project.scripts] bzmux = "bzmux.cli:run"`, e **remover**
   `[tool.uv] package = false`. `dependencies = []` continua: `PyGObject` é
   sdist e declarar isso quebraria o build do venv isolado — a dependência é do
   sistema e o caminho é `pipx install --system-site-packages`.
3. **`main(argv=None)`.** O entry point `console_scripts` chama a função **sem
   argumentos**; `cli.main(argv)` hoje exige a lista (por isso `bzmux.py`
   passava `sys.argv`). Dois ajustes: `def main(argv=None)` com
   `argv = sys.argv if argv is None else argv`, e um `run()` que faz
   `sys.exit(main())` para o script virar o `bzmux` do PATH. Os checks que
   chamam `cli.main(["bzmux.py", ...])` continuam valendo.
4. **String de uso.** `USAGE` e os asserts de `core/checks.py` dizem
   `bzmux.py`; passam a dizer `bzmux` (senão a ajuda do comando instalado mente).
5. **Guarda do `gi`.** Hoje, num env isolado, o usuário leva
   `ModuleNotFoundError: No module named 'gi'` com traceback. Tratar no import
   tardio do `cli.py`: mensagem de uma linha com os dois caminhos —
   `sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0` ou
   `pipx install --system-site-packages` — e sair != 0. `--selftest` e `-h`
   têm de continuar sem tocar em `gui.py`.
6. **Scripts.** `run.sh`: `exec "$PY" -m bzmux "$@"` (com o repositório no
   `sys.path`). `run-tests.sh`: `python3 -m bzmux --selftest`. `tests/`:
   `from bzmux.checks import ALL` (o `pythonpath = ["."]` do pytest continua
   servindo). **`debug.sh`**: o `is_ours()` casa `bzmux\.py` na cmdline — com
   `-m bzmux` e com o script do PATH isso deixa de casar e o `--kill` para de
   funcionar (falha silenciosa clássica); ajustar o padrão.
7. **Docs.** README ganha a seção de instalação (apt + pipx); AGENTS muda o
   mapa da arquitetura e a seção de scripts; TASK/BACKLOG acompanham.

Armadilha que já mordeu: **`uv build` não falha** neste repositório hoje — cai
num setuptools legado e produz um wheel com `top_level = core`, sem
`entry_points.txt` e **sem o `bzmux.py`**. O critério de aceite não é "buildou",
é inspecionar o conteúdo do wheel.

### Instalação via git (o alvo)

O remote é `git@github.com:bazoocaze/pybzmux.git` e o repositório **não é
público** (https responde 404; `git ls-remote` pelo ssh funciona — verificado).
Consequência direta para o comando de instalação:

- `git+ssh://git@github.com/bazoocaze/pybzmux.git` — reusa a chave ssh do
  usuário, funciona em repo privado. **É a forma a documentar.**
- `git+https://...` — em repo privado exige token na URL (vaza em histórico de
  shell e em log de CI); só vale se um dia o repo abrir.
- `pipx run --spec "git+ssh://..."` roda sem instalar (útil para experimentar
  antes de substituir a instalação).

O que acompanha essa escolha:

- **`git` tem de estar instalado** e a chave ssh configurada; o pip clona e
  constrói o wheel na hora — logo o `[build-system]` do item 2 é pré-requisito
  e o build baixa o backend (hatchling/uv_build) do PyPI: não funciona offline
  na primeira vez.
- **Versão estática + upgrade que não pega commit novo.** Com `version =
  "0.1.0"` fixa, o `pipx upgrade` compara versão e conclui que já está na
  última, mesmo com `main` adiantado. Até existir release/tag, a atualização é
  `pipx install --force "git+ssh://..."` (recria o venv). Alternativa de
  versionamento por tag (`hatch-vcs`/`setuptools-scm`) fica para quando houver
  release de verdade — acrescenta dependência de build e não resolve o pipx
  sozinha.
- Conferir se `pipx reinstall` preserva o `--system-site-packages` (o pipx
  grava os parâmetros do venv junto da ferramenta, mas não verifiquei). O pipx
  atual também aceita `--backend {pip,uv}`: testar se `--backend uv` respeita o
  `--system-site-packages` — se respeitar, o caminho uv entra de graça aqui,
  sem o `sed` do `pyvenv.cfg` do P30.

Verificação, na ordem:

```sh
uv build
python3 -c "import zipfile,glob; z=zipfile.ZipFile(glob.glob('dist/*.whl')[0]); \
  print([n for n in z.namelist() if n.startswith(('bzmux/','core'))][:3], \
  'entry_points' in ' '.join(z.namelist()))"       # bzmux/..., True; nada de core/
python3 -m bzmux --selftest                        # sem gi, sem display
./run-tests.sh && ./run.sh --quit-after 2          # fluxo de dev intacto

# 1) antes de empurrar: pip resolve git local (git+file), mesmo caminho do ssh
uv venv --system-site-packages /tmp/pipxcheck
/tmp/pipxcheck/bin/python -m pip install "git+file://$PWD"
/tmp/pipxcheck/bin/bzmux --selftest && /tmp/pipxcheck/bin/bzmux -h
/tmp/pipxcheck/bin/bzmux --quit-after 2            # abre e fecha (precisa display)
/tmp/pipxcheck/bin/python -m pip uninstall -y bzmux; rm -rf /tmp/pipxcheck

# 2) o alvo de verdade, depois do push
pipx install --system-site-packages "git+ssh://git@github.com/bazoocaze/pybzmux.git"
bzmux --selftest && bzmux -h && bzmux --quit-after 2
pipx list                                          # tem de listar bzmux + o venv compartilhado
pipx install --force "git+ssh://git@github.com/bazoocaze/pybzmux.git"   # upgrade real
pipx uninstall bzmux
```

Fora de escopo: Windows/macOS (depende da decisão do P30), publicar no PyPI,
versionamento por tag/release, flatpak e pacote de distro.

Os 25 itens anteriores (P1–P25) estão concluídos. Histórico, bugs e quirks:
[HISTORY.md](HISTORY.md). Status e por onde retomar:
[../TASK-bzmux.md](../TASK-bzmux.md).

O que sobra é limite conhecido, não item — caractere largo (CJK/emoji) ocupando
uma célula só, protocolo de teclado do kitty parcial, sequências não
interpretadas, sem configuração/tema — tudo em
[LIMITATIONS.md](LIMITATIONS.md).
