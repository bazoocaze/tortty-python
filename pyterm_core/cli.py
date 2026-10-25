"""Linha de comando: `pyterm.py [--cmd CMD] [--quit-after SEG] ...`."""

from .selftest import selftest


def parse_args(argv):
    """Só leitura de argv — separado para poder testar sem Gtk."""
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
    return cmd, quit_after, dump_to


def main(argv):
    if "--selftest" in argv:
        return selftest()
    # import tardio: --selftest roda sem tocar em Gtk/PyGObject
    from .gui import Gtk, Gdk, GdkX11
    from .window import PyTermWindow

    cmd, quit_after, dump_to = parse_args(argv)
    win = PyTermWindow(cmd=cmd, quit_after=quit_after, dump_to=dump_to)
    win.show_all()
    # O Marco (MATE) nega present() com timestamp 0 (GDK_CURRENT_TIME): é
    # preciso o timestamp ATUAL do servidor X, como fazem os apps Qt.
    gdkwin = win.get_window()
    ts = GdkX11.x11_get_server_time(gdkwin) if GdkX11 else Gdk.CURRENT_TIME
    win.present_with_time(ts)
    win.grab_focus_current()
    Gtk.main()
    return 0
