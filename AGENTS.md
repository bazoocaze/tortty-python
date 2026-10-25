# Diretrizes do projeto

## Testes: poucos e focados

Diretriz do autor, vale para o repositório inteiro:

> "Não me oponho que tenha testes, mas apenas alguns poucos focando nas coisas
> mais importantes, ao invés de testes exaustivos."

Na prática:

- **Poucos checks nos caminhos críticos** — parser, protocolos, e tudo que já
  quebrou uma vez (regressão vale mais que cobertura).
- **Sem suíte exaustiva**: nada de matriz de casos gerada por combinação de
  parâmetros, nada de teste que só reescreve o código na forma de asserção,
  nada de perseguir 100% de cobertura.
- **Um bug corrigido = um check** (quando der), não uma bateria em volta dele.
- **Teste tem que ser barato de rodar**: um comando (`python3 bzmux.py
  --selftest`) e, de preferência, sem display. Se precisar de X11/GUI, documente
  o comando manual no `TASK-bzmux.md` em vez de montar infraestrutura de teste.
- **Sem infraestrutura de suíte** (pytest, `tests/`, `pyproject.toml`, CI) sem o
  autor pedir: os checks vivem em `core/selftest.py` e rodam com `--selftest`.
- **Medição não é teste**: os números do `TASK-bzmux.md` vêm de execução real;
  não transformar isso em benchmark automatizado sem necessidade.

## Commits

- Não usar `Co-Authored-By:` em commits/PRs.
