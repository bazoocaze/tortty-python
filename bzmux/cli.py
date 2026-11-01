"""Linha de comando: `bzmux [--cmd CMD] [--quit-after SEG] ...`."""

import sys

from . import __version__
from .selftest import selftest

USAGE = """\
uso: bzmux [opções]

  --cmd CMD          comando inicial (default: a opção `shell` da configuração)
  -c, --config ARQ   arquivo de configuração (default: ~/.config/bzmux/bzmux.conf)
  --quit-after SEG   fecha sozinho depois de SEG segundos
  --dump-to ARQUIVO  salva a grade visível ao sair
  --debug-log ARQ    log JSONL do ?2026 x scroll (default: a opção `debug_log`;
                     `off` desliga)
  --selftest         roda os checks sem abrir janela
  --install-shortcut cria o atalho no menu do sistema (.desktop + ícone)
  --remove-shortcut  remove o atalho
  -V, --version      mostra a versão e sai
  -h, --help         mostra esta ajuda e sai"""


def parse_args(argv):
    """Só leitura de argv — separado para poder testar sem Gtk.

    Devolve (cmd, quit_after, dump_to, config, debug_log, erro), onde erro é a
    primeira opção desconhecida (ou sem valor) e None quando está tudo certo.
    """
    cmd, quit_after, dump_to, conf, dlog = None, 0, None, None, None
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
        else:
            return cmd, quit_after, dump_to, conf, dlog, a
    return cmd, quit_after, dump_to, conf, dlog, None


def run():
    """Entry point do console script (pipx): sem argv e sai com o código."""
    sys.exit(main())


def _shortcut(installing):
    """--install-shortcut / --remove-shortcut: só arquivos, sem Gtk."""
    from . import shortcut

    if not installing:
        gone = shortcut.remove()
        if gone:
            print("atalho removido: " + ", ".join(gone))
        else:
            print("não havia atalho instalado")
        return 0
    try:
        desktop, icon = shortcut.install()
    except RuntimeError as e:
        print(f"bzmux: {e}", file=sys.stderr)
        return 1
    print(f"atalho: {desktop}\nícone:  {icon}")
    bad = shortcut.validate(desktop)
    if bad:
        print(bad.rstrip(), file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if "-V" in argv[1:] or "--version" in argv[1:]:
        print("bzmux " + __version__)
        return 0
    if "-h" in argv[1:] or "--help" in argv[1:]:
        print(USAGE)
        return 0
    if "--selftest" in argv:
        return selftest()
    if "--install-shortcut" in argv or "--remove-shortcut" in argv:
        return _shortcut("--install-shortcut" in argv)
    cmd, quit_after, dump_to, conf, dlog, erro = parse_args(argv)
    if erro:
        print(f"bzmux: opção inválida: {erro}\n\n{USAGE}", file=sys.stderr)
        return 2
    # import tardio: --selftest e --help rodam sem tocar em Gtk/PyGObject
    try:
        from .gui import Gdk, GdkX11, GLib, Gtk
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
            file=sys.stderr,
        )
        return 1

    # WM_CLASS estável: o padrão do GLib vem do argv[0] e muda entre o console
    # script (bzmux), o `-m bzmux` (__main__.py) e o venv — com ele instável o
    # atalho do sistema não acha a janela. Casa com StartupWMClass do .desktop.
    GLib.set_prgname("bzmux")
    Gdk.set_program_class("Bzmux")

    win = BzmuxWindow(
        cmd=cmd,
        quit_after=quit_after,
        dump_to=dump_to,
        config_path=conf,
        debug_log=dlog,
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
