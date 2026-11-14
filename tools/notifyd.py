#!/usr/bin/env python3
"""Fake notification daemon: records what the window sends over D-Bus.

A **manual** test tool (it does not go into `--selftest`): it takes the name
`org.freedesktop.Notifications` on a D-Bus session and writes every `Notify`
received as `<summary> | <body>` on one line. It is what proves that an
`OSC 9`/`777` reached the desktop (P74) without depending on the real daemon of
the session.

    dbus-run-session -- sh -c 'tools/notifyd.py /tmp/notif.txt & sleep 1;
        tortty-python --debug-socket /tmp/s.sock & ...'
    cat /tmp/notif.txt

The app only calls the daemon when it is **not** in front: with no WM, take the
X focus away (`set_input_focus` on `PointerRoot`) or the notification never goes.
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
