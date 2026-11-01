# TASK-toast — mock para escolher o aviso (toast)

Pedido do usuário, numerado. Nada aqui é commitado: é rascunho de trabalho.

## Conteúdo e aparência

1. Um app **mock** para testarmos as opções de toast discutidas (não o app real).
2. Fundo **preto** com **lorem ipsum branco**, parecido com o bzmux atual.
3. Fonte com o **mesmo tamanho da do bzmux** (grade: Monospace 13 pt).
4. **Bons contrastes** de texto — legibilidade é requisito.
5. Sucesso **puxando para o verde**, fracasso **puxando para o vermelho**.
6. Sem **diálogo modal** — é toast: flutua ou ocupa faixa, não bloqueia.

## Controles

7. **Botões** para ativar cada opção discutida (variantes de posição/estilo e de
   comportamento).
8. Um dos botões tem de ser a **opção atual** (o toast de hoje), para comparar.

## Execução

9. Abre **maximizado**.
10. É só um mock: **simples**, sem recurso inventado.
11. **O usuário** verifica (nada de eu ficar capturando tela ou clicando por
    xdotool para julgar o desenho).
12. Tem de **rodar de fato** — janela na tela, sem traceback, sem morrer quando
    o comando que a lançou termina.

## Estado conhecido (2026-10-31)

- `tools/toastmock.py` existe e roda; o lançamento por `bash -c` matava o
  processo junto, hoje sobe com `setsid`.
- Pendências abertas: 9 (maximizado) e a revisão do 2/3/4 no que está na tela.

## Escopo agora: só o visual

Posição é **sempre rodapé-centro**. Fora da discussão, por ora: posições, tempos
(inclusive duração e animação de saída), reserva de espaço (faixa) e o item 7
(diálogo modal, descartado). Comportamento (fila, coalescer, pausa, dispensar)
fica para depois do visual.

## Fixo (não é opção)

- Fonte do texto do toast: **13 pontos** (não pixels), Monospace, a mesma da
  grade — via `Pango.FontDescription` como no `view.py`.
- Posição: rodapé-centro.

## Opções visuais

Descartados: 1d (reto) e opacidade (o toast é sempre opaco).

Cada dimensão abaixo é escolhida separadamente; o que está em **negrito** é o
que existe hoje no app.

1. **Forma** — retângulo 6 px (hoje) · raio 8 · raio 4 · pílula (raio =
   metade da altura). *Descartado: reto (raio 0).*
2. **Padding** — em todas as direções, em alturas da fonte do toast (28 px na
   fonte atual, medido via Pango): meia altura (~14) · 1 altura (28) · 2 alturas
   (56) · 3 alturas (84); hoje: 8×16 vertical×horizontal (só como referência no
   "mostrar como é hoje"). *Descartado: padding fixo em px (4/8/16/32) — as
   opções são sempre relativas à altura da fonte.*
   Largura: encolhe no texto (hoje) · largura fixa com quebra em ~60 colunas.
3. **Fundo** — verde/vermelho escuros (hoje: `#1f4d2e`/`#5c1f1f`) · verde e
   vermelho mais claros (`#245c33`/`#7a2626`) · neutro escuro (`#2a2a2a`) com a
   cor só no acento.
4. **Acento de severidade** — nenhum, só o fundo (hoje) · ícone (`✓`/`!`/`⚠`) ·
   barra vertical de 4 px à esquerda · ponto colorido antes do texto.
5. **Borda e sombra** — nenhuma (hoje) · borda de 1 px mais clara · sombra
   difusa (`0 3px 10px`) · borda + sombra (cara de flutuante).
6. **Tipografia** — corpo da grade em branco puro (hoje) · semibold · duas
   linhas (título curto + detalhe em tom mais claro) · texto centralizado (hoje)
   vs alinhado à esquerda com ícone fixo.
7. **Entrada** — slide de baixo (hoje) · fade puro · fade + subida de 4–6 px.
8. **Indicador de tempo** — nenhum (hoje) · fio de 2 px na base do toast que
   encurta (visual do timer).

## Escolha (visual fechado)

1e pílula · 2a meia altura (14 px, todos os lados) + largura i (encolhe no
texto) · 3a fundo escuro · 4c barra de acento de 4 px · 5d borda + sombra ·
6c duas linhas (título + detalhe) · 7c fade + subida · 8a sem fio de tempo.

Na hora de aplicar no app, lembrar de dois defeitos encontrados no mock:
- o `Gtk.EventBox` ignora padding do CSS no tamanho (o fundo pinta mas o widget
  não cresce) — o padding tem que ir na caixa interna (`Gtk.Box`); o `#toast`
  atual do app tem esse defeito (renderiza sem padding).
- `maximize()` do Marco soma a altura dos widgets e estoura a tela; abrir pela
  área útil do monitor.

## Comportamento (fechado)

1. Duração: 3 s para ok, 10 s para os outros.
2. Clique dispensa.
3. Toast novo com um visível: fila (mostra um depois do outro).
4. Reload válido limpo mostra confirmação ("configuração aplicada", 3 s).
5. Clique no erro abre a configuração via `open_config` (método único; o atalho
   Ctrl+Shift+F2 chama o mesmo — sem vim espalhado).
6. Texto longo: sem teto de largura, cresce e quebra na borda.
7. Erro na abertura: toast de 10 s e segue.

## Aplicado no app

Visual (1e 2a 2i 3a 4c 5d 6c 7c 8a) + comportamento (7 itens) em `bzmux/window.py`
e `bzmux/style.py`: pílula raio 14, padding meia altura da fonte medido no 1º
show (10 px na fonte atual) na caixa interna, fundo escuro, barra 4 px, borda +
sombra, título + detalhe, SLIDE_UP 220 ms. Sonda com foto: centro, barra, borda
e canto conferidos por pixel nos dois tons. Doc oficial pendente (README ainda
descreve o toast antigo).

## Três tons + repetida vira aviso

Fundo diferente por severidade (o combinado do mock): ok `#1f4d2e`, aviso
`#5c4a12`, erro `#5c1f1f`, cada um com seu acento de barra/borda. Chave repetida
virou a fonte do amarelo: "linha 2: shell repetido, vale este (linha 1
ignorada)" — antes sumia em silêncio. Desconhecida segue erro vermelho.
