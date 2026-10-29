"""Linha de comando: `bzmux [--cmd CMD] [--quit-after SEG] ...`."""

import sys

from .selftest import selftest

USAGE = """\
uso: bzmux [opções]

  --cmd CMD          comando inicial (default: $SHELL)
  --quit-after SEG   fecha sozinho depois de SEG segundos
  --dump-to ARQUIVO  salva a grade visível ao sair
  --selftest         roda os checks sem abrir janela
  -h, --help         mostra esta ajuda e sai"""


def parse_args(argv):
    """Só leitura de argv — separado para poder testar sem Gtk.

    Devolve (cmd, quit_after, dump_to, erro), onde erro é a primeira opção
    desconhecida (ou sem valor) e None quando está tudo certo.
    """
    cmd, quit_after, dump_to = None, 0, None
    args = list(argv[1:])
    while args:
        a = args.pop(0)
        if a == "--cmd" and args:
            cmd = args.pop(0)
        elif a == "--quit-after" and args:
            quit_after = int(args.pop(0))
        elif a == "--dump-to" and args:
            dump_to = args.pop(0)
        else:
            return cmd, quit_after, dump_to, a
    return cmd, quit_after, dump_to, None


def run():
    """Entry point do console script (pipx): sem argv e sai com o código."""
    sys.exit(main())


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if "-h" in argv[1:] or "--help" in argv[1:]:
        print(USAGE)
        return 0
    if "--selftest" in argv:
        return selftest()
    cmd, quit_after, dump_to, erro = parse_args(argv)
    if erro:
        print(f"bzmux: opção inválida: {erro}\n\n{USAGE}", file=sys.stderr)
        return 2
    # import tardio: --selftest e --help rodam sem tocar em Gtk/PyGObject
    try:
        from .gui import Gtk, Gdk, GdkX11
        from .window import BzmuxWindow
    except ModuleNotFoundError as e:
        if e.name not in ("gi", "cairo"):
            raise
        print(
            f"bzmux: falta o {e.name} (PyGObject/Gtk3 + pycairo do sistema).\n"
            "  Linux (deb): sudo apt install python3-gi python3-gi-cairo "
            "gir1.2-gtk-3.0\n"
            "  instalado por pipx/venv isolado: use --system-site-packages\n"
            "  (ou rode 'bzmux --selftest', que não precisa de display nem gi)",
            file=sys.stderr)
        return 1

    win = BzmuxWindow(cmd=cmd, quit_after=quit_after, dump_to=dump_to)
    win.show_all()
    # O Marco (MATE) nega present() com timestamp 0 (GDK_CURRENT_TIME): é
    # preciso o timestamp ATUAL do servidor X, como fazem os apps Qt.
    gdkwin = win.get_window()
    ts = GdkX11.x11_get_server_time(gdkwin) if GdkX11 else Gdk.CURRENT_TIME
    win.present_with_time(ts)
    win.grab_focus_current()
    Gtk.main()
    return 0
