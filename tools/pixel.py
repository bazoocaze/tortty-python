#!/usr/bin/env python3
"""Reads pixel colours from a PNG — to check what was drawn on the screen.

A **manual** test tool (it does not go into `--selftest`): it proves things like
"the footer got the background of the last row" or "the truecolor came out
exactly (18,52,86)" on a capture made with `import -window <id>`.

It uses GdkPixbuf (the same `gi` the window uses).

    tools/pixel.py shot.png                  # default probe points
    tools/pixel.py shot.png 697,515 350,90   # specific points (x,y)
    tools/pixel.py shot.png --scan 300       # column x=300, one sample per
                                             # 19 px band (the cell height)
    tools/pixel.py shot.png --row 515        # row y=515 sampled along the width
    tools/pixel.py shot.png --expect 5,9=ff0000   # colour at the point (repeatable;
                                                   # exits 1 on a mismatch)
    tools/pixel.py shot.png --find ff0000     # first point with the colour (x y)
    tools/pixel.py a.png --diff b.png --max 0 # how many pixels differ; exits 1
                                              # above the maximum (0 = identical)
    tools/pixel.py a.png --diff b.png --region 0,37,9999,460
                                              # compares only the rectangle (the
                                              # rest is an overlay that may animate)
"""

import argparse
import sys

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402


class Erro(Exception):
    pass


def carregar(caminho):
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(caminho)
    except Exception as e:
        raise Erro(f"não consegui abrir {caminho}: {e}")
    return {
        "w": pb.get_width(),
        "h": pb.get_height(),
        "rs": pb.get_rowstride(),
        "nc": pb.get_n_channels(),
        "px": pb.get_pixels(),
    }


def cor(img, x, y):
    if not (0 <= x < img["w"] and 0 <= y < img["h"]):
        raise Erro(f"ponto fora da imagem: {x},{y} ({img['w']}x{img['h']})")
    o = y * img["rs"] + x * img["nc"]
    return tuple(img["px"][o : o + 3])


def recortar(img, rx, ry, rw, rh):
    """Mesma imagem limitada ao retângulo (o que fica fora é descartado)."""
    x0, y0 = max(0, rx), max(0, ry)
    x1, y1 = min(img["w"], rx + rw), min(img["h"], ry + rh)
    if x1 <= x0 or y1 <= y0:
        raise Erro(f"região vazia: {rx},{ry},{rw},{rh} em {img['w']}x{img['h']}")
    nc = img["nc"]
    linhas = [img["px"][y * img["rs"] + x0 * nc : y * img["rs"] + x1 * nc] for y in range(y0, y1)]
    return {"w": x1 - x0, "h": y1 - y0, "rs": (x1 - x0) * nc, "nc": nc, "px": b"".join(linhas)}


def contar_diff(a, b):
    """Pixels que diferem entre duas capturas do mesmo tamanho."""
    if (a["w"], a["h"]) != (b["w"], b["h"]):
        raise Erro(f"tamanhos diferentes: {a['w']}x{a['h']} vs {b['w']}x{b['h']}")
    n = 0
    for y in range(a["h"]):
        oa, ob = y * a["rs"], y * b["rs"]
        fa = a["px"][oa : oa + a["w"] * a["nc"]]
        fb = b["px"][ob : ob + b["w"] * b["nc"]]
        if fa == fb:
            continue
        for x in range(a["w"]):
            i = x * a["nc"]
            if fa[i : i + 3] != fb[i : i + 3]:
                n += 1
    return n


def achar(img, rgb):
    """Primeiro ponto (linha a linha) com a cor, ou None."""
    alvo = bytes(rgb)
    for y in range(img["h"]):
        base = y * img["rs"]
        for x in range(img["w"]):
            o = base + x * img["nc"]
            if img["px"][o : o + 3] == alvo:
                return x, y
    return None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("png", nargs="?", help="PNG a inspecionar (não precisa com --diff)")
    ap.add_argument("pontos", nargs="*", help="x,y (repetível)")
    ap.add_argument(
        "--scan",
        type=int,
        metavar="X",
        help="amostra a coluna X a cada 19 px (altura da célula)",
    )
    ap.add_argument(
        "--row",
        type=int,
        metavar="Y",
        help="amostra a linha Y em 6 pontos da largura",
    )
    ap.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="X,Y=RRGGBB",
        help="cor esperada no ponto (repetível); sai 1 se algum divergir",
    )
    ap.add_argument("--find", metavar="RRGGBB", help="primeiro ponto com a cor; sai 1 se não achar")
    ap.add_argument(
        "--diff",
        nargs=2,
        metavar=("A", "B"),
        help="conta os pixels que diferem entre dois PNG",
    )
    ap.add_argument("--max", type=int, default=0, help="com --diff: máximo aceito (padrão 0)")
    ap.add_argument(
        "--region",
        metavar="X,Y,W,H",
        help="com --diff: compara só este retângulo (fora dele é ignorado)",
    )
    a = ap.parse_args(argv)

    if a.diff:
        img_a, img_b = carregar(a.diff[0]), carregar(a.diff[1])
        if a.region:
            try:
                rx, ry, rw, rh = (int(v) for v in a.region.split(","))
            except ValueError:
                raise Erro(f"região inválida: {a.region!r} (esperado x,y,w,h)")
            img_a, img_b = recortar(img_a, rx, ry, rw, rh), recortar(img_b, rx, ry, rw, rh)
        n = contar_diff(img_a, img_b)
        print(f"  difere: {n} px (máximo {a.max})")
        return 0 if n <= a.max else 1
    if not a.png:
        raise Erro("falta o PNG (ou use --diff A B)")
    if a.expect:
        img = carregar(a.png)
        falhas = 0
        for item in a.expect:
            try:
                xy, hexv = item.split("=")
                x, y = (int(v) for v in xy.split(","))
                esperado = tuple(bytes.fromhex(hexv))
            except ValueError:
                raise Erro(f"ponto inválido: {item!r} (esperado x,y=rrggbb)")
            obtido = cor(img, x, y)
            ok = obtido == esperado
            print(f"  {x},{y} -> {obtido} (esperado {esperado}) {'ok' if ok else 'DIVERGIU'}")
            falhas += 0 if ok else 1
        return 1 if falhas else 0
    if a.find:
        try:
            alvo = tuple(bytes.fromhex(a.find))
        except ValueError:
            raise Erro(f"cor inválida: {a.find!r} (esperado rrggbb)")
        p = achar(carregar(a.png), alvo)
        if p is None:
            print(f"  cor {a.find} não aparece", file=sys.stderr)
            return 1
        print(f"  {p[0]} {p[1]}")
        return 0

    img = carregar(a.png)
    print(f"{a.png}: {img['w']}x{img['h']}")

    if a.pontos:
        for p in a.pontos:
            try:
                x, y = (int(v) for v in p.split(","))
            except ValueError:
                raise Erro(f"ponto inválido: {p!r} (esperado x,y)")
            print(f"  {x},{y} -> {cor(img, x, y)}")
    elif a.scan is not None:
        x = a.scan
        for faixa in range(img["h"] // 19 + 1):
            y = min(img["h"] - 1, faixa * 19)
            print(f"  y={y:4d} -> {cor(img, x, y)}")
    elif a.row is not None:
        y = a.row
        amostras = [
            0,
            img["w"] // 5,
            2 * img["w"] // 5,
            3 * img["w"] // 5,
            4 * img["w"] // 5,
            img["w"] - 1,
        ]
        print("  " + "  ".join(f"x={x}->{cor(img, x, y)}" for x in amostras))
    else:
        w, h = img["w"], img["h"]
        print(f"  centro           -> {cor(img, w // 2, h // 2)}")
        print(f"  topo (y=2)       -> {cor(img, 5, 2)}")
        print(f"  pé (y=h-3)       -> {[cor(img, x, h - 3) for x in (5, w // 2, w - 5)]}")
        print(f"  direita (x=w-3)  -> {[cor(img, w - 3, y) for y in (5, h // 2, h - 5)]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Erro as e:
        print(f"pixel: {e}", file=sys.stderr)
        sys.exit(1)
