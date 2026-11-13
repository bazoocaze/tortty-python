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

from . import style
from .palette import parse_color

# O PADRÃO é o arquivo `data/tortty-python.conf`: ele embarca no pacote e é lido
# como qualquer configuração. Este dict é só a rede de segurança para pacote mal
# montado (arquivo ausente) — a mesma função do `fallback()` do Rust, e o check
# `config_options` garante que os dois não divergem.
# Também é a lista de chaves conhecidas: chave fora daqui é erro (P33).
FALLBACK = {
    "shell": "",  # vazio = herda o $SHELL do ambiente (ver effective_shell)
    "font_family": "Monospace",
    "font_size": "12",
    "ligatures": "standard",
    "cursor_shape": "block",
    "cursor_blink": "off",
    "scrollback": "1000",
    "window_padding_width": "0",
    "bell": "none",
    "copy_on_select": "off",
    # P64: `SGR 1` nas cores 0..7 vira a variante brilhante (boldColors do
    # xterm); off = só engrossa o traço, como sempre
    "bold_as_bright": "off",
    # P64: espaço extra entre caracteres, em px — a célula cresce junto
    "letter_spacing": "0",
    "debug_log": "/tmp/tortty-python.debug.log",  # `off` desliga
    # none = não restaura nada; layout = workspaces, abas e o cwd de cada uma
    # (P50); content = layout + a foto da tela de cada aba (P57).
    "restore_state": "layout",
}
# P75: o chrome (lateral, abas, cartões) também vem da configuração; o padrão
# de cada chave é o token de `style.py` — uma fonte só, sem cópia de hex aqui.
CHROME_KEYS = tuple(style.CHROME)
FALLBACK.update(style.defaults())


DATA = Path(__file__).with_name("data") / "tortty-python.conf"

# As 19 chaves de cor (P49): frente, fundo, cursor e as 16 ANSI — a paleta
# clássica do xterm, que é onde mc/htop e ls --color foram calibrados. Os mesmos
# valores do `data/tortty-python.conf` e do `palette.py`.
COLOR_KEYS = ("foreground", "background", "cursor_color") + tuple("color%d" % i for i in range(16))
FALLBACK.update(
    dict(
        zip(
            COLOR_KEYS,
            (
                "#d6d6d6",
                "#000000",
                "#d6d6d6",
                "#000000",
                "#cd0000",
                "#00cd00",
                "#cdcd00",
                "#0000ee",
                "#cd00cd",
                "#00cdcd",
                "#e5e5e5",
                "#7f7f7f",
                "#ff0000",
                "#00ff00",
                "#ffff00",
                "#5c5cff",
                "#ff00ff",
                "#00ffff",
                "#ffffff",
            ),
        )
    )
)

KNOWN = tuple(FALLBACK)
CURSOR_SHAPES = ("block", "beam", "underline")
LIGATURES = ("off", "standard", "all")
# `font-features` do Pango por modo (P45); "all" soma as discricionárias
LIGATURE_FEATURES = {
    "off": "liga=0,calt=0",
    "standard": "liga=1,calt=1",
    "all": "liga=1,calt=1,dlig=1",
}
BELLS = ("none", "visual", "audible")
RESTORE_STATES = ("none", "layout", "content")
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
# Teto de 30 pt porque a célula cresce em área: 4 a 30 cobre do terminal
# pequeno ao grande, e 96 pt era um valor herdado que só cabia numa tela 4K.
FONT_MIN, FONT_MAX = 4.0, 30.0  # pontos
# 10000 é o último degrau de graça: a ~50 B por célula são ~100 MB em 200
# colunas, e o corte do histórico é O(teto) na memória por linha que entra.
# 100000 (o teto do Rust, de célula mais barata) custava ~1 GB e 2,4x por linha.
SCROLLBACK_MIN, SCROLLBACK_MAX = 1, 10000
PADDING_MAX = 200  # px
# 20 px extra já é muito além do entrelinha que qualquer fonte pede; o que
# importa é o piso 0 (a célula continua o avanço do glifo, alinhada)
LETTER_SPACING_MAX = 20  # px


class Entry(NamedTuple):
    """Uma linha `chave valor` com o número da linha (para o erro citar)."""

    key: str
    value: str
    line: int


def default_path():
    """`$XDG_CONFIG_HOME/tortty-python/tortty-python.conf`; o `-c` troca isso."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "tortty-python" / "tortty-python.conf"


def _valor(rest):
    """Valor da linha: `#` que ABRE o valor é a cor, `#` depois de espaço comenta.

    É a regra do Rust (`value_of`): `foreground #e6e6e6` é uma cor, não um
    comentário (P49).
    """
    rest = rest.strip()
    if rest.startswith("#"):
        return rest.split(None, 1)[0]
    for i, ch in enumerate(rest):
        if ch == "#" and i > 0 and rest[i - 1] in " \t":
            return rest[:i].strip()
    return rest


def parse(text):
    """Texto -> [Entry] em ordem; repetida aparece duas vezes, vence a última."""
    saidas = []
    for n, linha in enumerate(text.splitlines(), 1):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        partes = linha.split(None, 1)
        valor = _valor(partes[1]) if len(partes) > 1 else ""
        saidas.append(Entry(partes[0], valor, n))
    return saidas


def check_shell(valor):
    """Devolve a mensagem de erro, ou None. Nome puro é buscado no PATH."""
    if not valor:
        return None  # vazio é escolha: herda o $SHELL (effective_shell)
    if os.sep not in valor:
        if shutil.which(valor) is None:
            return "shell not found: %s" % valor
    elif not (os.path.isfile(valor) and os.access(valor, os.X_OK)):
        return "shell not executable: %s" % valor
    return None


def check_font_family(valor):
    """Só não-vazio: família inexistente cai no fallback do Pango, sem erro."""
    if not valor:
        return "font_family is empty"
    return None


def _number(valor, nome, minimo, maximo, inteiro=False):
    try:
        n = int(valor) if inteiro else float(valor)
    except ValueError:
        return "%s is not a number: %s" % (nome, valor)
    if not minimo <= n <= maximo:
        fmt = "%d" if inteiro else "%g"
        return "%s out of range (%s..%s): %s" % (nome, fmt % minimo, fmt % maximo, valor)
    return None


def _enum(valor, nome, aceitos):
    if valor.lower() not in aceitos:
        return "%s invalid: %s (use %s)" % (nome, valor, "/".join(aceitos))
    return None


def check_font_size(valor):
    return _number(valor, "font_size", FONT_MIN, FONT_MAX)


def check_cursor_shape(valor):
    return _enum(valor, "cursor_shape", CURSOR_SHAPES)


def check_ligatures(valor):
    return _enum(valor, "ligatures", LIGATURES)


def check_bell(valor):
    return _enum(valor, "bell", BELLS)


def _bool(valor, nome):
    if valor.lower() not in BOOLS:
        return "%s invalid: %s (use on/off)" % (nome, valor)
    return None


def check_cursor_blink(valor):
    return _bool(valor, "cursor_blink")


def check_copy_on_select(valor):
    return _bool(valor, "copy_on_select")


def check_bold_as_bright(valor):
    return _bool(valor, "bold_as_bright")


def check_letter_spacing(valor):
    return _number(valor, "letter_spacing", 0, LETTER_SPACING_MAX, inteiro=True)


def check_restore_state(valor):
    return _enum(valor, "restore_state", RESTORE_STATES)


def check_scrollback(valor):
    """1 não é escolha: `0` desligava o histórico em silêncio, agora é erro."""
    return _number(valor, "scrollback", SCROLLBACK_MIN, SCROLLBACK_MAX, inteiro=True)


def check_padding(valor):
    return _number(valor, "window_padding_width", 0, PADDING_MAX, inteiro=True)


def check_debug_log(valor):
    """`off` (ou vazio, como no Rust) desliga; o resto é caminho de arquivo."""
    return None  # a chave aceita qualquer valor; `debug_log_path` interpreta


def check_color(valor):
    """`#RGB`/`#RRGGBB`, obrigatório — como no Rust, cor vazia é erro."""
    if not valor:
        return "color is empty (use #RRGGBB)"
    if parse_color(valor) is None:
        return "invalid color: %s (use #RRGGBB)" % valor
    return None


def debug_log_path(value):
    """Caminho do log de depuração, ou None quando está desligado."""
    return None if not value or value.lower() == "off" else value


CHECKS = {
    "shell": check_shell,
    "font_family": check_font_family,
    "font_size": check_font_size,
    "ligatures": check_ligatures,
    "cursor_shape": check_cursor_shape,
    "cursor_blink": check_cursor_blink,
    "scrollback": check_scrollback,
    "window_padding_width": check_padding,
    "bell": check_bell,
    "copy_on_select": check_copy_on_select,
    "bold_as_bright": check_bold_as_bright,
    "letter_spacing": check_letter_spacing,
    "debug_log": check_debug_log,
    "restore_state": check_restore_state,
}
CHECKS.update({k: check_color for k in COLOR_KEYS})
CHECKS.update({k: check_color for k in CHROME_KEYS})


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
        return self.values.get(key, FALLBACK[key])

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
    def ligatures(self):
        return self._get("ligatures").lower()

    @property
    def ligature_features(self):
        """`font-features` do Pango para o modo de ligaduras (P45)."""
        return LIGATURE_FEATURES.get(self.ligatures, LIGATURE_FEATURES["standard"])

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
    def bold_as_bright(self):
        """`SGR 1` em 0..7 escolhe a cor brilhante (xterm `boldColors`)."""
        return BOOLS.get(self._get("bold_as_bright").lower(), False)

    @property
    def letter_spacing(self):
        """Espaço extra entre caracteres em px (0..20); a célula acompanha."""
        return int(self._get("letter_spacing"))

    @property
    def debug_log(self):
        """Caminho do log JSONL de depuração (?2026 x scroll), ou None."""
        return debug_log_path(self._get("debug_log"))

    @property
    def colors(self):
        """As 19 chaves de cor (P49): nome -> int RGB; ausente = padrão."""
        out = {}
        for k in COLOR_KEYS:
            v = self._get(k)
            if v:
                c = parse_color(v)
                if c is not None:
                    out[k] = c
        return out

    @property
    def chrome(self):
        """As cores do chrome (P75) em '#rrggbb', para o `style.css`."""
        return {k: self._get(k) for k in CHROME_KEYS if self._get(k)}

    @property
    def restore_state(self):
        """`none`/`layout`/`content` (P50/P57): o que a próxima execução herda."""
        return self._get("restore_state").lower()

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
            errors.append("line %d: unknown key: %s" % (e.line, e.key))
            continue
        if e.key in vistos:
            warnings.append(
                "line %d: %s repeated, this one wins (line %d ignored)"
                % (e.line, e.key, vistos[e.key])
            )
        vistos[e.key] = e.line
        err = CHECKS[e.key](e.value)
        if err:
            errors.append("line %d: %s" % (e.line, err))
        else:
            out[e.key] = e.value
    return out, errors, warnings


def load(path=None):
    """Config mesclada (embutido <- usuário). Nunca levanta exceção."""
    path = Path(path) if path else default_path()
    base = dict(FALLBACK)
    emb = _read(DATA)
    if emb is None:
        errors = ["defaults file not found: %s" % DATA]
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
