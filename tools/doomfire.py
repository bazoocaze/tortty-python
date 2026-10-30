#!/usr/bin/env python3
"""Doom fire no terminal: carga máxima de escrita para medir o caminho quente.

O efeito do port de PSX do Doom: buffer de intensidade 0..36 propagado de baixo
para cima com decaimento aleatório e uma paleta de 37 cores. Desenhado em
meio-bloco (`▀`, dois pixels por célula) com fg e bg truecolor por célula, sem
agrupar nada — é o pior caso para o parser e para o desenho.

Medição, não teste: roda à mão dentro do terminal que se quer medir.

    python3 tools/doomfire.py                 # 30 fps até Ctrl+C
    python3 tools/doomfire.py --fps 0 --frames 600
    ./debug.sh --cmd 'python3 tools/doomfire.py --fps 0 --frames 600 \
        --stats-to /tmp/fire-bzmux.txt'      # estatística no arquivo

`--fps 0` solta a mão: quem passa a limitar é o terminal, e o fps alcançado (e
o MB/s de escapes) é a medida de vazão dele. As estatísticas saem ao sair, em
stderr ou no arquivo pedido, para dar para comparar dois terminais.

MIT (ver LICENSE).
"""

import argparse
import os
import shutil
import signal
import sys
import time

BLOCK = "▀".encode()

# paleta do doom fire (37 tons, do quase-preto ao branco)
PALETTE = [
    (0x07, 0x07, 0x07),
    (0x1F, 0x07, 0x07),
    (0x2F, 0x0F, 0x07),
    (0x47, 0x0F, 0x07),
    (0x57, 0x17, 0x07),
    (0x67, 0x1F, 0x07),
    (0x77, 0x1F, 0x07),
    (0x8F, 0x27, 0x07),
    (0x9F, 0x2F, 0x07),
    (0xAF, 0x3F, 0x07),
    (0xBF, 0x47, 0x07),
    (0xC7, 0x47, 0x07),
    (0xDF, 0x4F, 0x07),
    (0xDF, 0x57, 0x07),
    (0xDF, 0x57, 0x07),
    (0xD7, 0x5F, 0x07),
    (0xD7, 0x5F, 0x07),
    (0xD7, 0x67, 0x0F),
    (0xCF, 0x6F, 0x0F),
    (0xCF, 0x77, 0x0F),
    (0xCF, 0x7F, 0x0F),
    (0xCF, 0x87, 0x17),
    (0xC7, 0x87, 0x17),
    (0xC7, 0x8F, 0x17),
    (0xC7, 0x97, 0x1F),
    (0xBF, 0x9F, 0x1F),
    (0xBF, 0x9F, 0x1F),
    (0xBF, 0xA7, 0x27),
    (0xBF, 0xA7, 0x27),
    (0xBF, 0xAF, 0x2F),
    (0xB7, 0xAF, 0x2F),
    (0xB7, 0xB7, 0x2F),
    (0xB7, 0xB7, 0x37),
    (0xCF, 0xCF, 0x6F),
    (0xDF, 0xDF, 0x9F),
    (0xEF, 0xEF, 0xC7),
    (0xFF, 0xFF, 0xFF),
]

# escapes prontos por tom: montar a string por célula seria medir str, não o
# terminal, e o formato é o mesmo em todo frame
FG = [b"\033[38;2;%d;%d;%dm" % c for c in PALETTE]
BG = [b"\033[48;2;%d;%d;%dm" % c for c in PALETTE]
LAST = len(PALETTE) - 1


def update(buf, w):
    """Um passo do fogo: cada pixel herda do de baixo, com decaimento."""
    rand = int.from_bytes(os.urandom(1), "big")  # 0..255, barato o bastante
    n = len(buf)
    seed = rand | 0x100  # garante multiplicador ímpar no xorshift
    for src in range(w, n):
        if seed & 1:
            seed = (seed >> 1) ^ 0x8F3F73B5
        else:
            seed >>= 1
        pixel = buf[src]
        if not pixel:
            buf[src - w] = 0
            continue
        # deslocamento lateral de -1..+1 e decaimento de 0..1
        dst = src - w + (seed % 3) - 1
        if dst < 0:
            continue
        v = pixel - (seed & 1)
        buf[dst] = v if v > 0 else 0


def render(buf, w, h):
    """Frame inteiro em meio-bloco: fg = pixel de cima, bg = o de baixo."""
    out = bytearray(b"\033[H")
    fg, bg, block = FG, BG, BLOCK
    for row in range(0, h, 2):
        top = row * w
        bottom = top + w
        for x in range(w):
            out += fg[buf[top + x]]
            out += bg[buf[bottom + x]]
            out += block
    return out


def main(argv):
    ap = argparse.ArgumentParser(description="doom fire no terminal (medição)")
    ap.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="frames por segundo; 0 = sem limite (default 30)",
    )
    ap.add_argument(
        "--frames",
        type=int,
        default=0,
        help="para depois de N frames; 0 = até Ctrl+C",
    )
    ap.add_argument("--stats-to", default="-", help="arquivo das estatísticas; - = stderr")
    a = ap.parse_args(argv)

    cols, lines = shutil.get_terminal_size((80, 24))
    w, h = cols, lines * 2
    buf = bytearray(w * h)
    buf[-w:] = bytes([LAST]) * w  # última fileira no fogo máximo

    # SIGTERM/SIGINT param o laço (e não matam antes das estatísticas): dá para
    # medir com `timeout -s TERM 20 python3 tools/doomfire.py --fps 0`
    stop = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.append(True))

    out = sys.stdout.buffer
    out.write(b"\033[?1049h\033[0m\033[2J\033[?25l")
    out.flush()

    frames = 0
    sent = 0
    t0 = time.monotonic()
    deadline = t0
    try:
        while not stop and (not a.frames or frames < a.frames):
            update(buf, w)
            frame = render(buf, w, h)
            out.write(frame)
            out.flush()  # sem flush não há vazão a medir
            frames += 1
            sent += len(frame)
            if a.fps > 0:
                deadline += 1.0 / a.fps
                delay = deadline - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    deadline = time.monotonic()
    except KeyboardInterrupt:
        pass
    finally:
        # sem o SGR reset o texto das estatísticas herda a última cor do fogo
        out.write(b"\033[0m\033[?25h\033[?1049l\033[0m")
        out.flush()

    dt = time.monotonic() - t0
    linhas = [
        f"grade       {cols}x{lines} ({w}x{h} pixels)",
        f"frames      {frames} em {dt:.2f}s",
        f"fps         {frames / dt:.1f}",
        f"escrito     {sent / 1e6:.1f} MB ({sent / dt / 1e6:.1f} MB/s)",
        f"bytes/frame {sent / frames if frames else 0:.0f}",
    ]
    txt = "\n".join(linhas) + "\n"
    if a.stats_to == "-":
        sys.stderr.write(txt)
    else:
        with open(a.stats_to, "w", encoding="utf-8") as f:
            f.write(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
