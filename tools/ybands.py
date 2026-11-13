#!/usr/bin/env python3
"""Faixas de pixel que diferem entre duas capturas — sem supor geometria.

Ferramenta **manual** de teste (não entra no `--selftest`): compara dois PNGs da
mesma janela e imprime os intervalos de `y` (e o `x` de cada um) onde os pixels
mudaram. Serve quando a conta de "linha x altura da célula" já custou tempo
demais: a resposta vem dos pixels, não de uma coordenada que se acredita certa.

    tools/ybands.py a.png b.png
    tools/ybands.py a.png b.png --min 4      # ignora blocos com menos de 4 px

O caso típico é provar que um hover/efeito pintou **onde devia** e em mais
nenhum lugar (P67/P70/P76). Para "quantos pixels diferem" e "--expect"/--find",
`tools/pixel.py` já responde; este lê o PNG e diz *onde*.
"""

import argparse
import sys

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402


def ler(caminho):
    pb = GdkPixbuf.Pixbuf.new_from_file(caminho)
    return pb.get_width(), pb.get_height(), pb.get_n_channels(), pb.get_pixels(), pb.get_rowstride()


def diferencas(a, b):
    """(y, x0, x1, n) por linha — as colunas que diferem em cada y."""
    wa, ha, ca, pa, sa = a
    wb, hb, cb, pb_, sb = b
    if (wa, ha, ca) != (wb, hb, cb):
        raise SystemExit(
            "capturas de tamanho/canais diferentes: %dx%d/%d vs %dx%d/%d" % (wa, ha, ca, wb, hb, cb)
        )
    out = []
    for y in range(ha):
        ia, ib = y * sa, y * sb
        la = pa[ia : ia + wa * ca]
        lb = pb_[ib : ib + wa * cb]
        if la == lb:
            continue
        xs = [x for x in range(wa) if la[x * ca : x * ca + ca] != lb[x * cb : x * cb + cb]]
        out.append((y, min(xs), max(xs), len(xs)))
    return out


def blocos(linhas, minimo):
    """Agrupa as linhas contínuas em faixas e aplica o mínimo de pixels."""
    if not linhas:
        return []
    grupos, atual = [], [linhas[0]]
    for item in linhas[1:]:
        if item[0] == atual[-1][0] + 1:
            atual.append(item)
        else:
            grupos.append(atual)
            atual = [item]
    grupos.append(atual)
    saida = []
    for g in grupos:
        # uma faixa só interessa se cada linha dela tem pelo menos `minimo` px
        if min(item[3] for item in g) < minimo:
            continue
        saida.append(
            (
                g[0][0],
                g[-1][0],
                min(item[1] for item in g),
                max(item[2] for item in g),
                sum(item[3] for item in g),
            )
        )
    return saida


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a", help="PNG de referência")
    ap.add_argument("b", help="PNG a comparar")
    ap.add_argument(
        "--min",
        type=int,
        default=1,
        help="pixels diferentes por linha para a faixa valer (padrão 1; 0 = tudo)",
    )
    a = ap.parse_args(argv)
    try:
        (la, lb) = (ler(a.a), ler(a.b))
    except GLib.Error as e:
        raise SystemExit("não consegui ler: %s" % e.message)
    linhas = diferencas(la, lb)
    if not linhas:
        print("idênticas")
        return 0
    faixas = blocos(linhas, a.min)
    if not faixas:
        print("só ruído: nenhuma faixa com %d px por linha" % a.min)
        return 0
    for y0, y1, x0, x1, n in faixas:
        print("y %d..%d   x %d..%d   %d px" % (y0, y1, x0, x1, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
