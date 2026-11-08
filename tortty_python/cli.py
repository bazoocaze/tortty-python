"""Linha de comando: `tortty-python [--cmd CMD] [--quit-after SEG] ...`."""

import sys

from . import __version__, shortcut
from .selftest import selftest

USAGE = """\
usage: tortty-python [options]

  --cmd CMD          initial command (default: the config `shell` option)
  -c, --config FILE  configuration file (default:
                     ~/.config/tortty-python/tortty-python.conf)
  --quit-after SEG   closes by itself after SEG seconds
  --dump-to FILE     saves the visible grid on exit
  --debug-log FILE   JSONL debug log of ?2026 x scroll (default: the option
                     `debug_log`; `off` disables it)
  --debug-socket FILE Unix socket of introspection (one JSON per line; `auto` =
                     $XDG_RUNTIME_DIR/tortty-python-<pid>.sock). Off by
                     default
  --selftest         runs the checks without opening a window
  --install-shortcut creates the shortcut in the system menu (.desktop + icon)
  --remove-shortcut  removes the shortcut
  -V, --version      prints the version and exits
  -h, --help         prints this help and exits"""


def parse_args(argv):
    """Só leitura de argv — separado para poder testar sem Gtk.

    Devolve (cmd, quit_after, dump_to, config, debug_log, debug_socket, erro),
    onde erro é a primeira opção desconhecida (ou sem valor) e None quando está
    tudo certo.
    """
    cmd, quit_after, dump_to, conf, dlog, dsock = None, 0, None, None, None, None
    args = list(argv[1:])
    while args:
        a = args.pop(0)
        if a == "--cmd" and args:
            cmd = args.pop(0)
        elif a in ("-c", "--config") and args:
            conf = args.pop(0)
        elif a == "--quit-after" and args:
            quit_after = int(args.pop(0))
        elif a == "--dump-to" and args:
            dump_to = args.pop(0)
        elif a == "--debug-log" and args:
            dlog = args.pop(0)
        elif a == "--debug-socket" and args:
            dsock = args.pop(0)
        else:
            return cmd, quit_after, dump_to, conf, dlog, dsock, a
    return cmd, quit_after, dump_to, conf, dlog, dsock, None


def run():
    """Entry point do console script (pipx): sem argv e sai com o código."""
    sys.exit(main())


def _shortcut(installing):
    """--install-shortcut / --remove-shortcut: só arquivos, sem Gtk."""
    if not installing:
        gone = shortcut.remove()
        if gone:
            print("shortcut removed: " + ", ".join(gone))
        else:
            print("no shortcut installed")
        return 0
    try:
        desktop, icon = shortcut.install()
    except RuntimeError as e:
        print(f"tortty-python: {e}", file=sys.stderr)
        return 1
    print(f"shortcut: {desktop}\nicon:     {icon}")
    bad = shortcut.validate(desktop)
    if bad:
        print(bad.rstrip(), file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if "-V" in argv[1:] or "--version" in argv[1:]:
        print("tortty-python " + __version__)
        return 0
    if "-h" in argv[1:] or "--help" in argv[1:]:
        print(USAGE)
        return 0
    if "--selftest" in argv:
        return selftest()
    if "--install-shortcut" in argv or "--remove-shortcut" in argv:
        return _shortcut("--install-shortcut" in argv)
    cmd, quit_after, dump_to, conf, dlog, dsock, erro = parse_args(argv)
    if erro:
        print(f"tortty-python: invalid option: {erro}\n\n{USAGE}", file=sys.stderr)
        return 2
    # import tardio: --selftest e --help rodam sem tocar em Gtk/PyGObject
    try:
        from .gui import Gdk, GdkX11, GLib, Gtk
        from .window import TorttyWindow
    except ModuleNotFoundError as e:
        if e.name not in ("gi", "cairo"):
            raise
        print(
            f"tortty-python: missing {e.name} (PyGObject/Gtk3 + pycairo from the system).\n"
            "  Linux (deb): sudo apt install python3-gi python3-gi-cairo "
            "gir1.2-gtk-3.0\n"
            "  installed by pipx/isolated venv: use --system-site-packages\n"
            "  (or run 'tortty-python --selftest', which needs no display nor gi)",
            file=sys.stderr,
        )
        return 1

    # WM_CLASS estável: o padrão do GLib vem do argv[0] e muda entre o console
    # script (tortty-python), o `-m tortty_python` (__main__.py) e o venv — com ele instável o
    # atalho do sistema não acha a janela. Casa com StartupWMClass do .desktop.
    GLib.set_prgname(shortcut.APP)
    Gdk.set_program_class(shortcut.WMCLASS)

    win = TorttyWindow(
        cmd=cmd,
        quit_after=quit_after,
        dump_to=dump_to,
        config_path=conf,
        debug_log=dlog,
        debug_socket=dsock,
    )
    win.show_all()
    # O Marco (MATE) nega present() com timestamp 0 (GDK_CURRENT_TIME): é
    # preciso o timestamp ATUAL do servidor X, como fazem os apps Qt.
    gdkwin = win.get_window()
    ts = GdkX11.x11_get_server_time(gdkwin) if GdkX11 else Gdk.CURRENT_TIME
    win.present_with_time(ts)
    win.grab_focus_current()
    Gtk.main()
    return 0
