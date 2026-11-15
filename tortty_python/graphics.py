"""Kitty graphics protocol (APC `G ...`) — the pure part.

An app sends an image like this::

    ESC _ G a=T,f=100,i=1,q=2;<base64 of the PNG> ESC \\

and the terminal answers (unless silence was asked) `ESC _ G i=1;OK ESC \\`.
Only the parse/decoding and the list of *placements* live here; cairo comes
later, in `window.py` (`surface_from_image`). That is what makes the protocol
testable without a display.

Supported (enough for `kitten icat`):

    a=t transmit   a=T transmit+show   a=p show (already transmitted)
    a=d delete (d=i,i=<id> or d=a)     a=q query
    f=24 RGB  f=32 RGBA  f=100 PNG   (m=1 for a chunked image)
    i=<id>  c=<columns>  r=<rows>  C=1 (do not move the cursor)  q=<silence>

Out: animation (`a=f`/`a=a`), z-index and transmission by file/shared-memory
(`t=f`/`t=t`/`t=s`). Compression `o=z` is supported (zlib).
"""

import base64
import math
import struct
import zlib


def png_size(data):
    """Largura/altura do IHDR — o PNG já diz, então não precisa de s=/v=."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    return struct.unpack(">II", data[16:24])


class Image:
    __slots__ = ("id", "width", "height", "fmt", "data")

    def __init__(self, id_, width, height, fmt, data):
        self.id, self.width, self.height = id_, width, height
        self.fmt, self.data = fmt, data


class Placement:
    __slots__ = ("image_id", "col", "row", "cols", "rows", "dx", "dy")

    def __init__(self, image_id, col, row, cols, rows, dx=0, dy=0):
        self.image_id, self.col, self.row = image_id, col, row
        self.cols, self.rows = cols, rows
        # `X=`/`Y=`: deslocamento em PIXELS da imagem dentro da primeira
        # célula. É assim que o `icat` centraliza (ele move o cursor por
        # células inteiras e deixe o resto no offset).
        self.dx, self.dy = dx, dy


class Graphics:
    def __init__(self):
        self.images = {}  # id -> Image
        self.placements = []  # o que está desenhado agora
        self.saved = None  # placement do buffer principal enquanto o alt está no ar
        self._next_id = 1
        self._buf = None  # chunks de uma transmissão em curso (m=1)

    # -- utilidades ---------------------------------------------------
    def clear(self):
        self.images.clear()
        self.placements.clear()
        self.saved = None
        self._buf = None

    def erase(self, top, bottom, left, right):
        """P86: erasing the cells takes the picture drawn in them.

        `ED`/`EL`/`ECH` erase cells; without this the placement survived, and an
        app that paints over without the alternate screen (`mc`) kept the image
        in every cell it left blank. A picture in the history is out of 0..rows
        and stays, so scrolling up to it still finds it.
        """
        if top >= bottom or left >= right:
            return
        self.placements = [
            p
            for p in self.placements
            if not (
                p.row < bottom and p.row + p.rows > top and p.col < right and p.col + p.cols > left
            )
        ]

    def enter_alt(self):
        """The alternate screen has its own set; the main one waits here (P86)."""
        self.saved = self.placements
        self.placements = []

    def leave_alt(self):
        """Leaving gives the main screen's pictures back, on their own lines."""
        if self.saved is not None:
            self.placements = self.saved
            self.saved = None

    def scroll(self, top, bottom, floor=None):
        """Acompanha o scroll: placements sobem junto com o texto.

        `floor`: até que linha (negativa, ou seja dentro do scrollback) guardar
        uma colocação que saiu pelo topo. `None` = descarta (scroll de região,
        onde não existe histórico). Sem isso a imagem sumia na primeira linha
        que rolava e não voltava ao subir no histórico com o wheel.
        """
        keep = []
        for p in self.placements:
            if p.row > bottom:
                keep.append(p)  # fora da região: não mexe
                continue
            p.row -= 1
            if floor is not None and p.row >= floor:
                keep.append(p)
            elif floor is None and p.row >= top:
                keep.append(p)
        self.placements = keep

    def drop_above(self, floor):
        """Descarta o que saiu de vez do scrollback (as linhas mais antigas)."""
        self.placements = [p for p in self.placements if p.row >= floor]

    def _place(self, img, kv, cursor, cell):
        cw, ch = cell
        cols = int(kv["c"]) if kv.get("c") else max(1, math.ceil(img.width / cw))
        rows = int(kv["r"]) if kv.get("r") else max(1, math.ceil(img.height / ch))
        col, row = cursor
        dx = int(kv.get("X") or 0)
        dy = int(kv.get("Y") or 0)
        self.placements.append(Placement(img.id, col, row, cols, rows, dx, dy))
        return rows

    # -- o protocolo --------------------------------------------------
    def handle(self, body, cursor=(0, 0), cell=(10, 19)):
        """Processa o `G...` de um APC. Devolve `(respostas, linhas, move)`.

        `respostas` são os corpos de APC a devolver ao app (sem ESC _ / ST);
        `linhas` é quantas linhas a imagem ocupou; `move` diz se o cursor deve
        descer (o `C=1` pede pra não mexer).
        """
        if not body.startswith("G"):
            return [], 0, False
        stream = body[1:]

        ctrl, sep, payload = stream.partition(";")
        cur = {}
        for item in ctrl.split(","):
            if item:
                k, _, v = item.partition("=")
                cur[k] = v
        # the control data of the FIRST chunk covers the whole transmission
        if self._buf is None:
            self._buf = {"data": b"", "kv": dict(cur)}
        # each chunk is base64 on its own, padding included (chafa and icat both
        # do it): decoding the join would stop at the first `=`
        try:
            self._buf["data"] += base64.b64decode(payload + "=" * (-len(payload) % 4))
        except Exception:
            kv = self._buf["kv"]
            self._buf = None
            return ["G" + self._err(kv, "EINVAL:base64")], 0, False
        if cur.get("m") == "1":
            return [], 0, False  # still more chunks to come

        kv, data = self._buf["kv"], self._buf["data"]
        self._buf = None
        if kv.get("o") == "z" and data:
            # `o=z`: o payload vem comprimido (o `icat --place` manda PNG
            # decodificado + zlib pra escalar no terminal sem reencodar)
            try:
                data = zlib.decompress(data)
            except zlib.error:
                return ["G" + self._err(kv, "EINVAL:zlib")], 0, False

        action = kv.get("a", "t")
        quiet = kv.get("q", "0") != "0"
        ident = int(kv["i"]) if kv.get("i") else 0

        if action in ("f", "a", "c"):
            return [], 0, False  # animação/controle: ignorado de propósito
        if action == "q":
            # `a=q` é sonda de CAPACIDADE, não consulta de imagem: o
            # `kitten icat` manda três (direto / arquivo / memória) e só segue
            # se receber OK na de transmissão direta. Responder ENOENT por o
            # id não existir faz o icat desistir com "terminal does not
            # support the graphics protocol".
            medium = kv.get("t", "d")
            fmt = int(kv.get("f", "32"))
            ok = medium == "d" and fmt in (24, 32, 100)
            name = "OK" if ok else "EINVAL:unsupported transmission"
            return ([f"Gi={ident};{name}"] if ident else []), 0, False
        if action == "d":
            how = kv.get("d", "a")
            if how == "i":
                self.images.pop(ident, None)
                self.placements = [p for p in self.placements if p.image_id != ident]
            else:
                self.placements.clear()
                if how == "a":
                    self.images.clear()
            return ([] if quiet else ["Gi=%d;OK" % ident]), 0, False
        if action == "p":
            img = self.images.get(ident)
            if img is None:
                return (["Gi=%d;ENOENT" % ident], 0, False)
            rows = self._place(img, kv, cursor, cell)
            return (
                ([] if quiet else ["Gi=%d;OK" % ident]),
                rows,
                kv.get("C") != "1",
            )
        if action not in ("t", "T"):
            return (
                ([] if quiet else ["G" + self._err(kv, "EINVAL:action")]),
                0,
                False,
            )

        # transmissão: f=24/32/100 (PNG é autodetectado pelo magic)
        fmt = int(kv.get("f", "32"))
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            fmt = 100
        if fmt == 100:
            width, height = png_size(data)
            width = int(kv.get("s") or width)
            height = int(kv.get("v") or height)
        else:
            width, height = int(kv.get("s") or 0), int(kv.get("v") or 0)
            need = width * height * (4 if fmt == 32 else 3)
            if not width or not height or len(data) < need:
                return ([f"Gi={ident};EINVAL:size"], 0, False)
        if not ident:
            ident = self._next_id
            self._next_id += 1
        img = Image(ident, width, height, fmt, data)
        self.images[ident] = img
        rows = 0
        move = False
        if action == "T":
            rows = self._place(img, kv, cursor, cell)
            move = kv.get("C") != "1"
        return ([] if quiet else [f"Gi={ident};OK"]), rows, move

    @staticmethod
    def _err(kv, msg):
        ident = kv.get("i", "0")
        return f"i={ident};{msg}"
