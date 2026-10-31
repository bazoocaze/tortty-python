"""Configuração (P33): chave/valor no formato do kitty, puro (sem Gtk).

Sempre **merge**: o arquivo `data/bzmux.conf` que embarca com o pacote é a base
e o arquivo do usuário entra por cima, chave a chave. O `-c` só troca o caminho
do arquivo do usuário — a base continua valendo.

Config inválida nunca aplica nada: `load()` devolve a configuração anterior
(`values`) junto com `errors`, e quem chama mostra o erro e segue com o que já
estava funcionando.
"""

import os
import shutil
from pathlib import Path
from typing import NamedTuple

# Só para pacote mal montado (o `data/bzmux.conf` é a fonte normal dos padrões).
FALLBACK = {"shell": "/bin/bash"}
DEFAULT_SHELL = "/bin/bash"
DATA = Path(__file__).with_name("data") / "bzmux.conf"

KNOWN = ("shell",)


class Entry(NamedTuple):
    """Uma linha `chave valor` com o número da linha (para o erro citar)."""

    key: str
    value: str
    line: int


def default_path():
    """`$XDG_CONFIG_HOME/bzmux/bzmux.conf`; o `-c` substitui este caminho."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "bzmux" / "bzmux.conf"


def _sem_comentario(linha):
    """`#` no começo ou depois de espaço comenta até o fim da linha."""
    for i, ch in enumerate(linha):
        if ch == "#" and (i == 0 or linha[i - 1] in " \t"):
            return linha[:i]
    return linha


def parse(text):
    """Texto -> [Entry] em ordem; repetida aparece duas vezes, vence a última."""
    saidas = []
    for n, linha in enumerate(text.splitlines(), 1):
        linha = _sem_comentario(linha).strip()
        if not linha:
            continue
        partes = linha.split(None, 1)
        valor = partes[1].strip() if len(partes) > 1 else ""
        saidas.append(Entry(partes[0], valor, n))
    return saidas


def check_shell(valor):
    """Devolve a mensagem de erro, ou None. Nome puro é buscado no PATH."""
    if not valor:
        return "shell vazio"
    if os.sep not in valor:
        if shutil.which(valor) is None:
            return "shell não encontrado: %s" % valor
    elif not (os.path.isfile(valor) and os.access(valor, os.X_OK)):
        return "shell não executável: %s" % valor
    return None


CHECKS = {"shell": check_shell}


class Config:
    def __init__(self, values, path, errors=(), warnings=(), exists=False):
        self.values = values
        self.path = path
        self.errors = list(errors)
        self.warnings = list(warnings)
        self.exists = exists  # o arquivo do usuário existe?

    @property
    def shell(self):
        return self.values.get("shell", DEFAULT_SHELL)

    @property
    def ok(self):
        return not self.errors

    def __repr__(self):
        return "Config(%r, errors=%r)" % (self.values, self.errors)


def _read(path):
    """Texto do arquivo, ou None se ele não existe/ilegível (não é erro)."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _validated(vals, base):
    """Valida chave a chave sobre `base`; erro mantém o valor de `base`.

    Chave desconhecida é **erro**: linha lixo é config inválida, nada vale.
    """
    out, errors, warnings = dict(base), [], []
    vistos = {}  # chave -> linha da primeira ocorrência (repetida avisa)
    for e in vals:
        if e.key not in KNOWN:
            errors.append("linha %d: chave desconhecida: %s" % (e.line, e.key))
            continue
        if e.key in vistos:
            warnings.append(
                "linha %d: %s repetido, vale este (linha %d ignorada)"
                % (e.line, e.key, vistos[e.key])
            )
        vistos[e.key] = e.line
        err = CHECKS[e.key](e.value)
        if err:
            errors.append("linha %d: %s" % (e.line, err))
        else:
            out[e.key] = e.value
    return out, errors, warnings


def load(path=None):
    """Config mesclada (embutido <- usuário). Nunca levanta exceção."""
    path = Path(path) if path else default_path()
    base = dict(FALLBACK)
    emb = _read(DATA)
    if emb is None:
        errors = ["arquivo de padrões não encontrado: %s" % DATA]
    else:
        base, errors, _ = _validated(parse(emb), base)
    txt = _read(path)
    if txt is None:
        return Config(base, path, errors)
    values, user_errors, warnings = _validated(parse(txt), base)
    if user_errors:  # não aplica nada: fica com os padrões
        return Config(base, path, errors + user_errors, warnings, exists=True)
    return Config(values, path, errors, warnings, exists=True)


def watch(func, path=None):
    """Avisa `func` quando o arquivo de configuração mudar (debounce de 250 ms)."""
    from gi.repository import Gio, GLib

    path = Path(path) if path else default_path()
    state = {"id": 0}

    def changed(*_a):
        if state["id"]:
            GLib.source_remove(state["id"])

        def fire():
            state["id"] = 0
            func()
            return False

        # editor que salva por rename gera 2-3 eventos seguidos
        state["id"] = GLib.timeout_add(250, fire)

    monitor = Gio.File.new_for_path(str(path)).monitor_file(Gio.FileMonitorFlags.NONE, None)
    monitor.connect("changed", changed)
    return monitor


def message(cfg):
    """Erros/avisos numa linha só, para o toast."""
    partes = list(cfg.errors)
    if cfg.warnings:
        partes.append("; ".join(cfg.warnings[:3]))
        if len(cfg.warnings) > 3:
            partes.append("(+%d)" % (len(cfg.warnings) - 3))
    return " · ".join(partes) if partes else ""
