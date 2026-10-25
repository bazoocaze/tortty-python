# bzmux — backlog (pendente)

Só o que está em aberto. Concluído: [HISTORY.md](HISTORY.md). Status, escopo
e por onde retomar: [../TASK-bzmux.md](../TASK-bzmux.md).

Ordem não implica prioridade.

### P9 — Ligaduras (shaping) — não iniciado

O desenho usa `cairo.show_text` (API toy): não há shaping, então `->`, `!=`,
`=>` saem como dois glifos mesmo em fonte com ligadura. Fix: `PangoCairo` para
layout por run (com cache de `Pango.Layout`), o que **muda o custo do frame** —
que é justamente a medida do experimento, então tem que medir antes/depois.

### P10 — Fallback de fonte (emoji/CJK) — não iniciado

Caractere fora da fonte vira caixa de glifo ausente. O Pango resolve isso de
graça (fontconfig faz o fallback), ou seja: **P9 e P10 caem juntos** na mesma
migração; estão separados aqui só para o registro do que cada um entrega.

Teste: `printf '\u4e2d\u6587 \U0001F600'` e comparação de screenshot.

### P18 — Dentro do `pi` as teclas aparecem dobradas — não iniciado

Sintoma: digitando no `pi`, cada tecla entra duas vezes (texto dobrado). Não
acontece em `vim`/`mc`/shell, só no `pi`.

Causa (já localizada, falta o fix): o `pi` liga o protocolo de teclado do kitty
com `CSI > 7 u`, ou seja com a flag **2 = report event types** (press/repeat/
release). Com ela, o bzmux manda o `release` (`on_key_release` em `core/view.py`,
`event=3`); mas para caractere imprimível sem modificador `kitty_kbd.encode`
devolve `None` (`mods == 1 and not report_all`) e o `encode_key` cai no caminho
legado, que **não tem noção de release** e devolve o texto de novo. Resultado:
`a` no press e `a` no release. Confirmado sem display:

    encode_key(Gdk.KEY_a, 0, 0, False, flags=7, event=1, text='a')  -> 'a'
    encode_key(Gdk.KEY_a, 0, 0, False, flags=7, event=3, text='a')  -> 'a'  (era pra ser nada)

Fix: release que cai no legado não emite nada — no `encode_key`, ou no
`on_key_release` (que só deve reportar release quando a flag 2 está ligada e o
teclado é de função/com modificador). Escolher um só lugar para a regra, senão
volta como "release por outro caminho".

Verificação: check em `core/checks.py` (press + release de `a` com flags=7 tem
que sair uma vez só) e ao vivo: digitar no `pi` sem precisar de app novo — o
`pi` já liga as flags no startup.
