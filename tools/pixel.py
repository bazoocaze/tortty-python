#!/usr/bin/env python3
"""Lê cores de pixel de um PNG — para conferir o que foi desenhado na tela.

Ferramenta **manual** de teste (não entra no `--selftest`): serve para provar
coisa do tipo "o rodapé ficou com o fundo da última fileira" ou "o truecolor
saiu exatamente (18,52,86)" numa captura feita com `import -window <id>`.

Usa o GdkPixbuf (o mesmo `gi` que a janela usa).

    tools/pixel.py shot.png                  # pontos de sondagem padrão
    tools/pixel.py shot.png 697,515 350,90   # pontos específicos (x,y)
    tools/pixel.py shot.png --scan 300       # coluna x=300, uma amostra por
                                             # faixa de 19 px (altura da célula)
    tools/pixel.py shot.png --row 515        # linha y=515 amostrada na largura
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


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("png")
    ap.add_argument("pontos", nargs="*", help="x,y (repetível)")
    ap.add_argument(
        "--scan",
        type=int,
        metavar="X",
        help="amostra a coluna X a cada 19 px (altura da célula)",
    )
    ap.add_argument(
        "--row", type=int, metavar="Y", help="amostra a linha Y em 6 pontos da largura"
    )
    a = ap.parse_args(argv)

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
        print(
            f"  pé (y=h-3)       -> {[cor(img, x, h - 3) for x in (5, w // 2, w - 5)]}"
        )
        print(
            f"  direita (x=w-3)  -> {[cor(img, w - 3, y) for y in (5, h // 2, h - 5)]}"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Erro as e:
        print(f"pixel: {e}", file=sys.stderr)
        sys.exit(1)
