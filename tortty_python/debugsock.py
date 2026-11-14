"""Introspection Unix socket (P35): one JSON line per request/response.

A debug tool with the agent as its user: the verbs may change without notice.
Off by default — only the command line opens it (`--debug-socket FILE`, and
`auto` = a file with the pid under `$XDG_RUNTIME_DIR`).

The dispatch is pure (testable without a display); the socket part imports
`GLib` only in `start()`, so this module does not drag Gtk into `--selftest`.
"""

import json
import os
import socket as socket_mod
import stat
import struct

VERBS = (
    "state",
    "text",
    "write",
    "drop",
    "sel",
    "keys",
    "resize",
    "prof",
    "log",
    "quit",
)
MODS = ("ctrl", "shift", "alt", "super")
# nomes que o keysym do X não conhece (PgUp não é "Page_Up" para o Gdk)
KEY_ALIASES = {
    "pgup": "Page_Up",
    "pgdn": "Page_Down",
    "pgdown": "Page_Down",
    "esc": "Escape",
    "enter": "Return",
    "del": "Delete",
    "bs": "BackSpace",
    "ins": "Insert",
    "space": "space",
}


def auto_path():
    """`$XDG_RUNTIME_DIR/tortty-python-<pid>.sock`; /tmp como último recurso."""
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, "tortty-python-%d.sock" % os.getpid())


def resolve(value):
    """`auto` vira caminho com o pid; vazio/None desliga."""
    if not value:
        return None
    return auto_path() if value == "auto" else value


def parse_key(spec):
    """`ctrl+shift+n` -> ("n", ("ctrl", "shift")); ValueError se não souber.

    Puro: quem resolve keyval e máscara de modificador é a janela, com o Gdk.
    """
    partes = [p.strip() for p in str(spec).split("+")]
    if not partes or not partes[-1]:
        raise ValueError("tecla vazia: %r" % spec)
    nome, mods = partes[-1], partes[:-1]
    for m in mods:
        if m.lower() not in MODS:
            raise ValueError("modificador desconhecido: %r (use %s)" % (m, MODS))
    return KEY_ALIASES.get(nome.lower(), nome), tuple(m.lower() for m in mods)


def _ok(**kw):
    kw["ok"] = True
    return json.dumps(kw, ensure_ascii=False)


def _err(msg):
    return json.dumps({"ok": False, "err": msg}, ensure_ascii=False)


def dispatch(target, line):
    """Pedido JSON -> resposta JSON de uma linha. Nunca levanta.

    O alvo é duck-typed: `debug_state`, `debug_text`, `debug_write`,
    `debug_drop`, `debug_sel`, `debug_log` e `debug_quit` (a janela implementa).
    """
    try:
        req = json.loads(line)
    except ValueError:
        return _err("json inválido")
    if not isinstance(req, dict):
        return _err("pedido precisa ser um objeto")
    cmd = req.get("cmd")
    try:
        if cmd == "state":
            return _ok(**target.debug_state())
        if cmd == "text":
            return _ok(
                lines=target.debug_text(
                    where=str(req.get("where", "view")),
                    start=int(req.get("start", 0)),
                    count=int(req.get("count", 40)),
                )
            )
        if cmd == "keys":
            data = req.get("data")
            specs = [data] if isinstance(data, str) else list(data or [])
            if not specs:
                return _err("keys precisa de data (string ou lista)")
            return _ok(keys=[target.debug_keys(str(s)) for s in specs])
        if cmd == "resize":
            return _ok(
                **target.debug_resize(cols=int(req.get("cols", 0)), rows=int(req.get("rows", 0)))
            )
        if cmd == "prof":
            return _ok(**target.debug_prof(on=req.get("on")))
        if cmd == "write":
            data = req.get("data")
            if not isinstance(data, str):
                return _err("write precisa de data (string)")
            target.debug_write(data)
            return _ok()
        if cmd == "sel":
            return _ok(**target.debug_sel())
        if cmd == "drop":
            path = req.get("path")
            if not isinstance(path, str):
                return _err("drop precisa de path (string)")
            return _ok(**target.debug_drop(path))
        if cmd == "log":
            return _ok(path=target.debug_log(str(req.get("value", ""))))
        if cmd == "quit":
            target.debug_quit()
            return _ok()
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        return _err("%s: %s" % (type(e).__name__, e))
    return _err("cmd desconhecido: %r (use %s)" % (cmd, ", ".join(VERBS)))


def _clear_stale(path):
    """Remove socket órfão e devolve None; caminho ocupado vira mensagem."""
    try:
        modo = os.stat(path).st_mode
    except FileNotFoundError:
        return None
    except OSError as e:
        return "%s: %s" % (path, e.strerror or e)
    if not stat.S_ISSOCK(modo):
        return "path exists and is not a socket: %s" % path
    probe = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
    try:
        probe.connect(path)
    except OSError:  # ECONNREFUSED: ninguém escuta, o arquivo é lixo
        try:
            os.unlink(path)
        except OSError as e:
            return "%s: %s" % (path, e.strerror or e)
        return None
    finally:
        probe.close()
    return "another process is listening on %s" % path


def _same_uid(conn):
    """Só o mesmo uid fala com o socket (SO_PEERCRED, Linux)."""
    if not hasattr(socket_mod, "SO_PEERCRED"):
        return False
    try:
        pid, uid, _gid = struct.unpack(
            "3i", conn.getsockopt(socket_mod.SOL_SOCKET, socket_mod.SO_PEERCRED, 12)
        )
    except (OSError, struct.error):
        return False
    return uid == os.getuid()


class Server:
    """Aceita conexões locais e responde com `dispatch`, na thread da UI."""

    def __init__(self, path, target):
        self.path = path
        self.target = target
        self._glib = None
        self._srv = None
        self._watch = 0
        self._clients = {}  # fileno -> [socket, watch, bytearray]

    def start(self):
        """Abre o socket. Devolve None ou a mensagem do erro."""
        from .gui import GLib

        erro = _clear_stale(self.path)
        if erro:
            return erro
        srv = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        try:
            srv.bind(self.path)
            os.chmod(self.path, 0o600)
            srv.listen(4)
        except OSError as e:
            srv.close()
            return "%s: %s" % (self.path, e.strerror or e)
        self._glib, self._srv = GLib, srv
        self._watch = GLib.io_add_watch(srv.fileno(), GLib.IO_IN, self._on_accept)
        return None

    def stop(self):
        """Fecha clientes e escuta, e remove o arquivo do socket."""
        for fd in list(self._clients):
            self._drop(fd)
        if self._srv is not None:
            if self._watch:
                self._glib.source_remove(self._watch)
                self._watch = 0
            self._srv.close()
            self._srv = None
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _on_accept(self, *_):
        try:
            conn, _addr = self._srv.accept()
        except OSError:
            return True  # sobra de accept: o watch continua
        if not _same_uid(conn):
            conn.close()
            return True
        fd = conn.fileno()
        watch = self._glib.io_add_watch(fd, self._glib.IO_IN | self._glib.IO_HUP, self._on_read)
        self._clients[fd] = [conn, watch, bytearray()]
        return True

    def _on_read(self, fd, *_):
        item = self._clients.get(fd)
        if item is None:
            return False
        conn, _watch, buf = item
        try:
            data = conn.recv(65536)
        except OSError:
            data = b""
        if not data:
            self._drop(fd)
            return False
        buf.extend(data)
        while b"\n" in buf:
            i = buf.index(b"\n")
            line = bytes(buf[:i])
            del buf[: i + 1]
            out = dispatch(self.target, line.decode("utf-8", "replace"))
            try:
                conn.sendall(out.encode("utf-8") + b"\n")
            except OSError:
                self._drop(fd)
                return False
        return True

    def _drop(self, fd):
        item = self._clients.pop(fd, None)
        if item is None:
            return
        conn, watch, _buf = item
        if watch:
            self._glib.source_remove(watch)
        conn.close()
