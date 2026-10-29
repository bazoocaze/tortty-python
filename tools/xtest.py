#!/usr/bin/env python3
"""Injeta eventos no X11 (XTest) numa janela do bzmux, achada por `_NET_WM_PID`.

Ferramenta **manual** de teste — não entra no `--selftest` (precisa de display).
Precisa de `python3-xlib` (está no sistema) e de um servidor X.

Coordenadas são **relativas à janela**: o script soma a origem sozinho. Cuidado
com o layout — a lateral ocupa 170 px e a barra de abas ~28 px, então a grade
começa em `y≈58`, não em `y=0`.

    tools/xtest.py id                        # id da janela (por _NET_WM_PID)
    tools/xtest.py activate
    tools/xtest.py geometry
    tools/xtest.py key ctrl+shift+n          # atalho global
    tools/xtest.py key Return
    tools/xtest.py type 'echo /usr/lib -x'   # texto arbitrário (com símbolos)
    tools/xtest.py click 60 28               # botão 1
    tools/xtest.py click 60 82 --button 2    # botão do meio
    tools/xtest.py dclick 60 28              # duplo clique (renomeia workspace)
    tools/xtest.py wheel 400 250 up --times 4
    tools/xtest.py drag 200 60 320 60        # seleção de texto
    tools/xtest.py move 300 200

O PID vem de `/tmp/bzmux.pid` (o `debug.sh` escreve lá); `--pid N` ou
`--window ID` sobrescrevem.
"""

import argparse
import json
import sys
import time

from Xlib import XK, X, display
from Xlib.ext import xtest

PIDFILE = "/tmp/bzmux.pid"
ATOM_PID = "_NET_WM_PID"

MODS = {"ctrl": "Control_L", "shift": "Shift_L", "alt": "Alt_L", "super": "Super_L"}

# layout US/ABNT: o símbolo que exige Shift aponta para a tecla base
SHIFTED = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "minus",
    "+": "equal",
    "{": "bracketleft",
    "}": "bracketright",
    "|": "backslash",
    ":": "semicolon",
    '"': "apostrophe",
    "<": "comma",
    ">": "period",
    "?": "slash",
    "~": "grave",
}
# símbolos que saem direto da tecla, sem modificador
PLAIN = {
    "-": "minus",
    "=": "equal",
    "[": "bracketleft",
    "]": "bracketright",
    "\\": "backslash",
    ";": "semicolon",
    "'": "apostrophe",
    ",": "comma",
    ".": "period",
    "/": "slash",
    "`": "grave",
    " ": "space",
    "\n": "Return",
    "\t": "Tab",
}


class Erro(Exception):
    pass


# --------------------------------------------------------------- janela ----
def _pid_do_arquivo():
    try:
        return int(open(PIDFILE).read().strip())
    except (OSError, ValueError):
        raise Erro(f"não achei o PID em {PIDFILE} (o bzmux está rodando?)")


def achar_janela(d, want_pid=None, want_id=None):
    """Acha a janela principal do bzmux.

    Um processo GTK tem **várias** janelas com o mesmo `_NET_WM_PID` (a do app e
    ajudantes de 10x10 do toolkit, que não são mapeadas). Pegar a primeira que
    aparece dá a ajudante: `geometry` mentia e `set_input_focus` estourava
    `BadMatch`. Então: entre as candidatas, ficar com a de **maior área** que
    esteja visível.
    """
    root = d.screen().root
    atom = d.intern_atom(ATOM_PID)
    achadas, pilha = [], [root]
    while pilha:
        w = pilha.pop()
        if want_id is not None:
            if w.id == want_id:
                return w
        else:
            try:
                p = w.get_full_property(atom, X.AnyPropertyType)
            except Exception:
                p = None
            if p and len(p.value) and p.value[0] == want_pid:
                achadas.append(w)
        try:
            pilha.extend(w.query_tree().children)
        except Exception:
            pass
    if not achadas:
        return None

    def visivel(w):
        try:
            return w.get_attributes().map_state == X.IsViewable
        except Exception:
            return False

    def area(w):
        try:
            g = w.get_geometry()
            return g.width * g.height
        except Exception:
            return 0

    visiveis = [w for w in achadas if visivel(w)]
    return max(visiveis or achadas, key=area)


# ------------------------------------------------------------- teclado ----
def _keysym(nome):
    ks = XK.string_to_keysym(nome)
    if not ks and len(nome) == 1:
        ks = XK.string_to_keysym(PLAIN.get(nome, nome))
    return ks


def combo_de_char(ch):
    """Caractere -> combinação de teclas (None se não der para digitar)."""
    if ch in PLAIN:
        return PLAIN[ch]
    if ch in SHIFTED:
        return "shift+" + SHIFTED[ch]
    if ch.isupper():
        return "shift+" + ch.lower()
    if ch.isdigit() or ch.islower():
        return ch
    return None


class Injecao:
    def __init__(self, janela, d):
        self.d = d
        self.root = d.screen().root
        self.janela = janela
        t = janela.translate_coords(self.root, 0, 0)
        self.ox, self.oy = -t.x, -t.y

    # -- primitivas
    def sync(self, pausa=0.03):
        self.d.sync()
        time.sleep(pausa)

    def move(self, x, y):
        xtest.fake_input(self.d, X.MotionNotify, x=self.ox + x, y=self.oy + y)
        self.sync()

    def botao(self, n, press):
        xtest.fake_input(self.d, X.ButtonPress if press else X.ButtonRelease, n)
        self.sync()

    def tap(self, keycode, mods=()):
        for m in mods:
            xtest.fake_input(self.d, X.KeyPress, m)
        xtest.fake_input(self.d, X.KeyPress, keycode)
        xtest.fake_input(self.d, X.KeyRelease, keycode)
        for m in reversed(mods):
            xtest.fake_input(self.d, X.KeyRelease, m)
        self.sync(0.05)

    # -- combinações
    def combo(self, spec):
        partes = spec.split("+")
        mods = []
        for p in partes[:-1]:
            nome = MODS.get(p)
            if nome is None:
                raise Erro(f"modificador desconhecido: {p}")
            mods.append(self.d.keysym_to_keycode(XK.string_to_keysym(nome)))
        ks = _keysym(partes[-1])
        if not ks:
            raise Erro(f"tecla desconhecida: {partes[-1]}")
        self.tap(self.d.keysym_to_keycode(ks), mods)

    def digitar(self, texto):
        for ch in texto:
            spec = combo_de_char(ch)
            if spec is None:
                raise Erro(f"não sei digitar {ch!r} (só ASCII do layout US)")
            self.combo(spec)


# ------------------------------------------------------------------ main ----
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pid", type=int, help="PID do bzmux (padrão: %s)" % PIDFILE)
    ap.add_argument("--window", type=lambda s: int(s, 0), help="id X11 da janela")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("id")
    sub.add_parser("activate")
    sub.add_parser("geometry")

    p = sub.add_parser("move")
    p.add_argument("x", type=int), p.add_argument("y", type=int)

    p = sub.add_parser("click")
    p.add_argument("x", type=int), p.add_argument("y", type=int)
    p.add_argument("--button", type=int, default=1)

    p = sub.add_parser("dclick")
    p.add_argument("x", type=int), p.add_argument("y", type=int)
    p.add_argument("--button", type=int, default=1)
    p.add_argument("--delay", type=float, default=0.06)

    p = sub.add_parser("wheel")
    p.add_argument("x", type=int), p.add_argument("y", type=int)
    p.add_argument("direcao", choices=("up", "down"))
    p.add_argument("--times", type=int, default=1)

    p = sub.add_parser("drag")
    p.add_argument("x1", type=int), p.add_argument("y1", type=int)
    p.add_argument("x2", type=int), p.add_argument("y2", type=int)
    p.add_argument("--button", type=int, default=1)
    p.add_argument("--steps", type=int, default=8)

    p = sub.add_parser("key")
    p.add_argument("combo", nargs="+", help="ex.: ctrl+shift+n Return")

    p = sub.add_parser("type")
    p.add_argument("texto")

    a = ap.parse_args(argv)

    d = display.Display()
    want_pid = a.pid if a.pid is not None else (None if a.window else _pid_do_arquivo())
    janela = achar_janela(d, want_pid, a.window)
    if janela is None:
        raise Erro("janela do bzmux não encontrada (PID %s)" % (want_pid,))
    inj = Injecao(janela, d)

    if a.cmd == "id":
        print(janela.id, flush=True)
    elif a.cmd == "geometry":
        g = janela.get_geometry()
        print(
            json.dumps(
                {"id": janela.id, "x": inj.ox, "y": inj.oy, "w": g.width, "h": g.height}
            )
        )
    elif a.cmd == "activate":
        janela.configure(stack_mode=X.Above)
        d.set_input_focus(janela, X.RevertToParent, X.CurrentTime)
        d.sync()
    elif a.cmd == "move":
        inj.move(a.x, a.y)
    elif a.cmd == "click":
        inj.move(a.x, a.y)
        inj.botao(a.button, True)
        inj.botao(a.button, False)
    elif a.cmd == "dclick":
        inj.move(a.x, a.y)
        for i in range(2):
            inj.botao(a.button, True)
            inj.botao(a.button, False)
            if i == 0:
                time.sleep(a.delay)
    elif a.cmd == "wheel":
        inj.move(a.x, a.y)
        n = 4 if a.direcao == "up" else 5
        for _ in range(a.times):
            inj.botao(n, True)
            inj.botao(n, False)
    elif a.cmd == "drag":
        inj.move(a.x1, a.y1)
        inj.botao(a.button, True)
        for i in range(1, a.steps + 1):
            inj.move(
                a.x1 + (a.x2 - a.x1) * i // a.steps, a.y1 + (a.y2 - a.y1) * i // a.steps
            )
        inj.botao(a.button, False)
    elif a.cmd == "key":
        for c in a.combo:
            inj.combo(c)
    elif a.cmd == "type":
        inj.digitar(a.texto)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Erro as e:
        print(f"xtest: {e}", file=sys.stderr)
        sys.exit(1)
