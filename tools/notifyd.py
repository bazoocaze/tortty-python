#!/usr/bin/env python3
"""Daemon de notificação falso: registra o que a janela manda por D-Bus.

Ferramenta **manual** de teste (não entra no `--selftest`): assume o nome
`org.freedesktop.Notifications` numa sessão D-Bus e grava cada `Notify` recebido
como `<resumo> | <corpo>` numa linha. Serve para provar que um `OSC 9`/`777`
chegou ao desktop (P74) sem depender do daemon de verdade da sessão.

    dbus-run-session -- sh -c 'tools/notifyd.py /tmp/notif.txt & sleep 1;
        tortty-python --debug-socket /tmp/s.sock & ...'
    cat /tmp/notif.txt

O app só chama o daemon quando **não** está na frente: sem WM, tire o foco do X
(`set_input_focus` em `PointerRoot`) ou a notificação não sai.
"""

import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="Notify">
      <arg type="s" direction="in"/><arg type="u" direction="in"/>
      <arg type="s" direction="in"/><arg type="s" direction="in"/>
      <arg type="s" direction="in"/><arg type="as" direction="in"/>
      <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/>
      <arg type="u" direction="out"/>
    </method>
    <method name="GetServerInformation">
      <arg type="s" direction="out"/><arg type="s" direction="out"/>
      <arg type="s" direction="out"/><arg type="s" direction="out"/>
    </method>
    <method name="GetCapabilities">
      <arg type="as" direction="out"/>
    </method>
  </interface>
</node>
"""


def chamada(saida, conn, sender, path, iface, metodo, params, invocation):
    """Responde as três chamadas que um cliente faz; grava o corpo do `Notify`."""
    if metodo == "Notify":
        resumo, corpo = params.unpack()[3], params.unpack()[4]
        with open(saida, "a") as f:
            f.write("%s | %s\n" % (resumo, corpo))
        invocation.return_value(GLib.Variant("(u)", (1,)))
    elif metodo == "GetCapabilities":
        invocation.return_value(GLib.Variant("(as)", (["body"],)))
    else:
        invocation.return_value(GLib.Variant("(ssss)", ("notifyd", "test", "1", "1.2")))
    return True


def main(argv):
    if len(argv) != 1:
        raise SystemExit("uso: tools/notifyd.py ARQUIVO")
    saida = argv[0]
    info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]

    def nome_ok(conn, name):
        conn.register_object(
            "/org/freedesktop/Notifications",
            info,
            lambda *a: chamada(saida, *a),
            None,
            None,
        )

    Gio.bus_own_name(
        Gio.BusType.SESSION,
        "org.freedesktop.Notifications",
        Gio.BusNameOwnerFlags.NONE,
        nome_ok,
        None,
        None,
    )
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
