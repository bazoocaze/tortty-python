"""Configuração (P33): chave/valor no formato do kitty, puro (sem Gtk).

Sempre **merge**: o arquivo `data/tortty-python.conf` que embarca com o pacote é a base
e o arquivo do usuário entra por cima, chave a chave. O `-c` só troca o caminho
do arquivo do usuário — a base continua valendo.

Erro é **por linha, não por arquivo**: `load()` aplica o que validou e devolve
os erros em `errors`; a chave inválida fica no valor padrão. Assim a carga
inicial aproveita o resto do arquivo (e o toast mostra o primeiro erro), e o
reload descarta tudo e mantém a configuração que já estava valendo (`ok`).
"""

import os
import shutil
from pathlib import Path
from typing import NamedTuple

# Só para pacote mal montado (o `data/tortty-python.conf` é a fonte normal dos padrões).
# Também é a lista de chaves conhecidas: chave fora daqui é erro (P33).
DEFAULTS = {
    "shell": "",  # vazio = herda o $SHELL do ambiente (ver effective_shell)
    "font_family": "Monospace",
    "font_size": "12",
    "cursor_shape": "block",
    "cursor_blink": "off",
    "scrollback": "1000",
    "window_padding_width": "0",
    "bell": "none",
    "copy_on_select": "off",
    "debug_log": "/tmp/tortty-python.debug.log",  # `off` desliga
}
DATA = Path(__file__).with_name("data") / "tortty-python.conf"

KNOWN = tuple(DEFAULTS)
CURSOR_SHAPES = ("block", "beam", "underline")
BELLS = ("none", "visual", "audible")
BOOLS = {
    "on": True,
    "yes": True,
    "true": True,
    "1": True,
    "off": False,
    "no": False,
    "false": False,
    "0": False,
}
FONT_MIN, FONT_MAX = 4.0, 96.0  # pontos
SCROLLBACK_MAX = 100000
PADDING_MAX = 200  # px


class Entry(NamedTuple):
    """Uma linha `chave valor` com o número da linha (para o erro citar)."""

    key: str
    value: str
    line: int


def default_path():
    """`$XDG_CONFIG_HOME/tortty-python/tortty-python.conf`; o `-c` troca isso."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "tortty-python" / "tortty-python.conf"


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
        return None  # vazio é escolha: herda o $SHELL (effective_shell)
    if os.sep not in valor:
        if shutil.which(valor) is None:
            return "shell não encontrado: %s" % valor
    elif not (os.path.isfile(valor) and os.access(valor, os.X_OK)):
        return "shell não executável: %s" % valor
    return None


def check_font_family(valor):
    """Só não-vazio: família inexistente cai no fallback do Pango, sem erro."""
    if not valor:
        return "font_family vazio"
    return None


def _number(valor, nome, minimo, maximo, inteiro=False):
    try:
        n = int(valor) if inteiro else float(valor)
    except ValueError:
        return "%s não é número: %s" % (nome, valor)
    if not minimo <= n <= maximo:
        fmt = "%d" if inteiro else "%g"
        return "%s fora da faixa (%s..%s): %s" % (nome, fmt % minimo, fmt % maximo, valor)
    return None


def _enum(valor, nome, aceitos):
    if valor.lower() not in aceitos:
        return "%s inválido: %s (use %s)" % (nome, valor, "/".join(aceitos))
    return None


def check_font_size(valor):
    return _number(valor, "font_size", FONT_MIN, FONT_MAX)


def check_cursor_shape(valor):
    return _enum(valor, "cursor_shape", CURSOR_SHAPES)


def check_bell(valor):
    return _enum(valor, "bell", BELLS)


def _bool(valor, nome):
    if valor.lower() not in BOOLS:
        return "%s inválido: %s (use on/off)" % (nome, valor)
    return None


def check_cursor_blink(valor):
    return _bool(valor, "cursor_blink")


def check_copy_on_select(valor):
    return _bool(valor, "copy_on_select")


def check_scrollback(valor):
    return _number(valor, "scrollback", 0, SCROLLBACK_MAX, inteiro=True)


def check_padding(valor):
    return _number(valor, "window_padding_width", 0, PADDING_MAX, inteiro=True)


def check_debug_log(valor):
    """`off` desliga; qualquer outro valor é caminho de arquivo."""
    if valor.lower() == "off" or valor:
        return None
    return "debug_log vazio (use off para desligar)"


def debug_log_path(value):
    """Caminho do log de depuração, ou None quando está desligado."""
    return None if not value or value.lower() == "off" else value


CHECKS = {
    "shell": check_shell,
    "font_family": check_font_family,
    "font_size": check_font_size,
    "cursor_shape": check_cursor_shape,
    "cursor_blink": check_cursor_blink,
    "scrollback": check_scrollback,
    "window_padding_width": check_padding,
    "bell": check_bell,
    "copy_on_select": check_copy_on_select,
    "debug_log": check_debug_log,
}


def effective_shell(value, env=None):
    """SHELL do filho: o da config (vazio herda o ambiente), sempre caminho."""
    env = os.environ if env is None else env
    return shutil.which(value or env.get("SHELL") or "/bin/bash") or "/bin/bash"


def tab_command(cmd, shell, env=None):
    """(comando da aba, SHELL do filho): o `--cmd` vence e não mexe no SHELL."""
    sh = effective_shell(shell, env)
    return (cmd or sh, sh)


class Config:
    def __init__(self, values, path, errors=(), warnings=(), exists=False):
        self.values = values
        self.path = path
        self.errors = list(errors)
        self.warnings = list(warnings)
        self.exists = exists  # o arquivo do usuário existe?

    def _get(self, key):
        return self.values.get(key, DEFAULTS[key])

    @property
    def shell(self):
        return self._get("shell")

    @property
    def font_family(self):
        return self._get("font_family")

    @property
    def font_size(self):
        """Em PONTOS (o Pango converte pelo DPI); float aceita 12.5."""
        return float(self._get("font_size"))

    @property
    def cursor_shape(self):
        return self._get("cursor_shape").lower()

    @property
    def cursor_blink(self):
        return BOOLS.get(self._get("cursor_blink").lower(), False)

    @property
    def scrollback(self):
        return int(self._get("scrollback"))

    @property
    def padding(self):
        return int(self._get("window_padding_width"))

    @property
    def bell(self):
        return self._get("bell").lower()

    @property
    def copy_on_select(self):
        return BOOLS.get(self._get("copy_on_select").lower(), False)

    @property
    def debug_log(self):
        """Caminho do log JSONL de depuração (?2026 x scroll), ou None."""
        return debug_log_path(self._get("debug_log"))

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
    base = dict(DEFAULTS)
    emb = _read(DATA)
    if emb is None:
        errors = ["arquivo de padrões não encontrado: %s" % DATA]
    else:
        base, errors, _ = _validated(parse(emb), base)
    txt = _read(path)
    if txt is None:
        return Config(base, path, errors)
    values, user_errors, warnings = _validated(parse(txt), base)
    # chave inválida fica no padrão e o resto do arquivo VALE (carga inicial);
    # no reload quem chama olha `ok` e mantém a configuração anterior
    return Config(values, path, errors + user_errors, warnings, exists=True)


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


def first_error(cfg):
    """Primeiro erro, com a contagem dos outros — cabe num toast só."""
    if not cfg.errors:
        return ""
    return cfg.errors[0] + (" · (+%d)" % (len(cfg.errors) - 1) if len(cfg.errors) > 1 else "")


def message(cfg):
    """Erros/avisos numa linha só, para o toast."""
    partes = list(cfg.errors)
    if cfg.warnings:
        partes.append("; ".join(cfg.warnings[:3]))
        if len(cfg.warnings) > 3:
            partes.append("(+%d)" % (len(cfg.warnings) - 3))
    return " · ".join(partes) if partes else ""
