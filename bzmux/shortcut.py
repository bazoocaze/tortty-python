"""Atalho no sistema: .desktop + ícone em XDG_DATA_HOME.

Puro (sem gi): entra pelo cli antes do import do Gtk, como o --selftest.
"""

import os
import shutil
import subprocess
import sys
from importlib import resources

APP = "bzmux"
WMCLASS = "Bzmux"     # casa com Gdk.set_program_class no cli


def data_home():
    """Diretório XDG de dados do usuário (respeita XDG_DATA_HOME)."""
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def desktop_path():
    return os.path.join(data_home(), "applications", APP + ".desktop")


def theme_dir():
    """.../icons/hicolor, a raiz que o gtk-update-icon-cache conhece."""
    return os.path.join(data_home(), "icons", "hicolor")


def icon_path():
    return os.path.join(theme_dir(), "scalable", "apps", APP + ".svg")


def exec_path():
    """Caminho absoluto do comando instalado.

    A sessão gráfica não herda o PATH do shell, então Exec precisa ser absoluto.
    """
    found = shutil.which(APP)
    if found:
        return os.path.abspath(found)
    argv0 = os.path.abspath(sys.argv[0] or "")
    # rodando como `python3 -m bzmux` o argv[0] é o __main__.py: não serve
    if argv0 and not argv0.endswith(".py") and os.access(argv0, os.X_OK):
        return argv0
    return None


def entry(exe):
    """Conteúdo do .desktop (Categories + X-TerminalArgExec para o "abrir aqui")."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=bzmux\n"
        "GenericName=Emulador de terminal\n"
        "Comment=Terminal em Python com abas, workspaces e imagens\n"
        f"Exec={exe}\n"
        f"TryExec={exe}\n"
        f"Icon={APP}\n"
        "Terminal=false\n"
        "StartupNotify=true\n"
        f"StartupWMClass={WMCLASS}\n"
        "Categories=System;TerminalEmulator;\n"
        "Keywords=terminal;console;shell;tabs;\n"
        "X-TerminalArgExec=--cmd\n"
    )


def _icon_bytes():
    return resources.files(__package__).joinpath("data/bzmux.svg").read_bytes()


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _run(tool, *args):
    """Roda a ferramenta de cache se existir; ausência não é erro."""
    exe = shutil.which(tool)
    if not exe:
        return
    try:
        subprocess.run([exe] + list(args), check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def refresh():
    """Atualiza os caches (desktop database e ícone) do que acabou de ser escrito."""
    _run("update-desktop-database", os.path.dirname(desktop_path()))
    _run("gtk-update-icon-cache", "-q", "-t", theme_dir())


def validate(path=None):
    """Saída do desktop-file-validate, ou "" se ele não estiver instalado."""
    exe = shutil.which("desktop-file-validate")
    if not exe:
        return ""
    r = subprocess.run([exe, path or desktop_path()],
                       capture_output=True, text=True)
    return r.stdout + r.stderr


def install():
    """Escreve .desktop + ícone; devolve os dois caminhos. RuntimeError se não houver Exec."""
    exe = exec_path()
    if not exe:
        raise RuntimeError(
            "não achei o comando instalado (pipx install ...), e rodar da árvore "
            "não serve: o atalho precisa de um Exec absoluto")
    _write(desktop_path(), entry(exe).encode())
    _write(icon_path(), _icon_bytes())
    refresh()
    return desktop_path(), icon_path()


def remove():
    """Apaga .desktop e ícone; devolve o que existia."""
    gone = []
    for p in (desktop_path(), icon_path()):
        try:
            os.unlink(p)
            gone.append(p)
        except FileNotFoundError:
            pass
    if gone:
        refresh()
    return gone
