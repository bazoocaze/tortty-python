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

P23 — Atalhos de workspace com Super: `Super+1`…`9` troca de workspace,
`Super+N` cria uma nova e `Super+Q` encerra a workspace corrente (com todas as
abas dela). **Pedido em 2026-10-27, a fazer.**

Estado hoje: os três comportamentos já existem, mas só com `Ctrl+Shift`
(`handle_shortcut` em `core/window.py`: `Ctrl+Shift+N` → `new_workspace`,
`Ctrl+Shift+Q` → `close_workspace`, `Ctrl+Shift+1..9` →
`select_workspace_index`, com `_digit_of` traduzindo o keycode cru para o dígito
em ABNT2). O caminho é somar o modificador, não duplicar a lógica.

Como fazer:

- Detectar `Gdk.ModifierType.SUPER_MASK` em `handle_shortcut` (no X11 é o MOD4;
  o GTK3 expõe `SUPER_MASK` no keymap traduzido) e tratar o ramo `super and not
  ctrl and not alt`: dígito → `select_workspace_index`, `n/N` →
  `new_workspace`, `q/Q` → `close_workspace(ws)`.
- Manter `Ctrl+Shift+*` funcionando: é o que está documentado no README e o que
  os testes manuais usam; o Super entra como alias, não como substituto (a não
  ser que o usuário peça o contrário).
- `Super+Q` na última workspace encerra o app (o `close_workspace` já faz
  `dump()` + `destroy()`); confirmar que isso é o esperado e não pedir
  confirmação.
- Cuidado com o dígito: `Super+1` pode chegar como `KEY_1` ou como o símbolo
  shiftado do layout, dependendo do `ev.state`; reusar `_digit_of(ev)`, que já
  resolve isso pelo keycode, em vez de comparar `ev.keyval`.

Armadilha provável (testar antes de culpar o código): **no GNOME, `Super+1`…`9`
é atalho do shell** (lança/ativa apps do dash) e `Super+Q`/`Super+N` podem estar
capturados pelo WM — nesse caso o evento nunca chega ao app. Verificar com
`tools/xtest.py key super+1` e, se o shell engolir, registrar a decisão: usar
outro modificador (ex.: `Super+Shift+1`) ou aceitar que depende do WM, com a
nota em docs/LIMITATIONS.md se virar limite.

Verificação: com display, `tools/xtest.py key super+n` cria workspace,
`super+1` e `super+2` alternam, `super+q` fecha o corrente com as abas (dump via
`kill -USR1` para conferir que as abas foram junto) e a numeração dos cartões é
renumerada. Sem display não dá para cobrir: `keys`/`Gdk` ficam fora dos checks
por design (o `--selftest` não puxa `gi`), então isso é teste manual.

Os 21 itens anteriores (P1–P22) estão concluídos. Histórico, bugs e quirks:
[HISTORY.md](HISTORY.md). Status e por onde retomar:
[../TASK-bzmux.md](../TASK-bzmux.md).

O que sobra é limite conhecido, não item — caractere largo (CJK/emoji) ocupando
uma célula só, protocolo de teclado do kitty parcial, sequências não
interpretadas, sem configuração/tema — tudo em
[LIMITATIONS.md](LIMITATIONS.md).
