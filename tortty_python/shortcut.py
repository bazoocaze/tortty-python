"""System shortcut: .desktop + icon in XDG_DATA_HOME.

Pure (no gi): it comes in through cli before the Gtk import, like --selftest.
"""

import os
import shutil
import subprocess
import sys
from importlib import resources

APP = "tortty-python"  # nome do .desktop e do ícone
NAME = "TorTTY (Python)"  # nome visível no menu do sistema
EXE = "tortty-python"  # console script que o pacote instala no PATH
WMCLASS = "tortty-python"  # WM_CLASS: casa com APP e com StartupWMClass
LEGACY = "pybzmux"  # .desktop/ícone do nome anterior: saem junto


def data_home():
    """Diretório XDG de dados do usuário (respeita XDG_DATA_HOME)."""
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def theme_dir():
    """.../icons/hicolor, a raiz que o gtk-update-icon-cache conhece."""
    return os.path.join(data_home(), "icons", "hicolor")


def _paths(name):
    """(.desktop, .svg) de um nome de aplicação."""
    return (
        os.path.join(data_home(), "applications", name + ".desktop"),
        os.path.join(theme_dir(), "scalable", "apps", name + ".svg"),
    )


def desktop_path():
    return _paths(APP)[0]


def icon_path():
    return _paths(APP)[1]


def exec_path():
    """Caminho absoluto do comando instalado.

    A sessão gráfica não herda o PATH do shell, então Exec precisa ser absoluto.
    """
    found = shutil.which(EXE)
    if found:
        return os.path.abspath(found)
    argv0 = os.path.abspath(sys.argv[0] or "")
    # rodando como `python3 -m tortty_python` o argv[0] é o __main__.py: não serve
    if argv0 and not argv0.endswith(".py") and os.access(argv0, os.X_OK):
        return argv0
    return None


def entry(exe):
    """Conteúdo do .desktop (Categories + X-TerminalArgExec para o "abrir aqui")."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        f"Name={NAME}\n"
        "GenericName=Terminal emulator\n"
        "Comment=Terminal in Python with tabs, workspaces and images\n"
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
    return resources.files(__package__).joinpath("data/tortty-python.svg").read_bytes()


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
        subprocess.run(
            [exe] + list(args),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
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
    r = subprocess.run([exe, path or desktop_path()], capture_output=True, text=True)
    return r.stdout + r.stderr


def install():
    """Escreve .desktop + ícone; devolve os dois caminhos (RuntimeError sem Exec)."""
    exe = exec_path()
    if not exe:
        raise RuntimeError(
            "installed command not found (pipx install ...), and running from "
            "the tree does not count: the shortcut needs an absolute Exec"
        )
    _write(desktop_path(), entry(exe).encode())
    _write(icon_path(), _icon_bytes())
    _unlink_legacy()
    refresh()
    return desktop_path(), icon_path()


def _legacy_paths():
    """(.desktop, .svg) do nome anterior; vazio quando o nome é o mesmo."""
    return () if LEGACY in ("", APP) else _paths(LEGACY)


def _unlink_legacy():
    """Apaga o atalho do nome anterior; ausência não é erro."""
    for p in _legacy_paths():
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def remove():
    """Apaga .desktop e ícone deste app (e do nome anterior); devolve o que existia.

    Só estes nomes: tortty.desktop/tortty.svg são da versão Rust.
    """
    gone = []
    for p in (desktop_path(), icon_path()) + _legacy_paths():
        try:
            os.unlink(p)
            gone.append(p)
        except FileNotFoundError:
            pass
    if gone:
        refresh()
    return gone
