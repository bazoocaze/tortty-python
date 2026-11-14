#!/usr/bin/env python3
"""uploadbench.py — is trading N cairo operations for 1 upload per frame worth it?

P27 proposes caching a row in a surface and cutting the number of runs. On the
real display (glamor) the 2D cost is **per operation**: 13.9 ms per frame at
61x18, against 4.2 ms on Xvfb on the same grid. If that is the mechanism, drawing
the frame into an ImageSurface and uploading a single image should cost far less
than dozens of small fills — and that is what this microbench measures, without
touching the app.

Four strategies, same content, same number of pixels:

- `runs`: today's drawing — per run, a background `fill_rectangle` and a text
  `show_layout` straight into the window.
- `upload`: the same frame in an ImageSurface and one `set_source_surface` +
  `paint` into the window — one request per frame, but the pixels go up the wire
  every frame.
- `pixmap`: the frame in a **server-side** surface (`create_similar_surface`), as
  the P27 row cache dreams of: draw into the pixmap and compose once, uploading
  no pixel at all.
- `pixmap 10%`: the same, but redrawing only 10% of the grid (the dirty-rect
  case).

Every frame picks colours from a 37-shade palette (like the doom fire), so there
is no content cache between frames. Each frame has a `Gdk.Display.sync()`, which
is XSync: it guarantees the server work entered the count (tortty-python does not
sync; there the cost shows up as a blocked request buffer, but the total is the
same).

Usage: tools/uploadbench.py [--frames N] [--cols C] [--rows R] [--font-size P]
                            [--display :0]
It runs on the current display; to compare against a virtual one:
    Xvfb :99 -screen 0 1600x1000x24 & DISPLAY=:99 tools/uploadbench.py

It prints ms/frame of each strategy and the ratio between them. If the ratio
stays near 1, P27 does not pay off that way; if it reaches 3x or more, the upload
is the way.

MIT (see LICENSE).
"""

import argparse
import math
import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo  # noqa: E402

PALETA = [
    (r / 8.0, g / 8.0, b / 8.0) for r in range(6) for g in range(6) for b in range(2)
]  # 72 tons, o suficiente para não repetir vizinho


def celula(font_desc, dpi):
    """Mesma conta da view: avanço do M vira largura, ascent+descent a altura."""
    layout = Pango.Layout(Gtk.Window().get_pango_context())
    PangoCairo.context_set_resolution(layout.get_context(), dpi)
    layout.set_font_description(font_desc)
    layout.set_text("M", -1)
    w, h = layout.get_size()
    return math.ceil(w / Pango.SCALE), math.ceil(h / Pango.SCALE)


class Banco:
    def __init__(self, cols, rows, cw, ch, font_desc):
        self.cols, self.rows, self.cw, self.ch = cols, rows, cw, ch
        self.font_desc = font_desc
        self.lay = {}  # cache de layout por texto (equivalente ao cache da view)

    def layout(self, cr, texto):
        lay = self.lay.get(texto)
        if lay is None:
            lay = PangoCairo.create_layout(cr)
            lay.set_font_description(self.font_desc)
            lay.set_text(texto, -1)
            self.lay[texto] = lay
        return lay

    def runs(self, frame):
        """Lista de (col, linha, largura_celulas, fg, bg): células vizinhas iguais."""
        saida = []
        for linha in range(self.rows):
            col = 0
            while col < self.cols:
                fg, bg = self.cores(frame, linha, col)
                larg = 1
                while col + larg < self.cols and self.cores(frame, linha, col + larg) == (
                    fg,
                    bg,
                ):
                    larg += 1
                saida.append((col, linha, larg, fg, bg))
                col += larg
        return saida

    def cores(self, frame, linha, col):
        """Paleta trocando a cada frame, como o doom-fire."""
        i = (frame * 7 + linha * 13 + col) % len(PALETA)
        return PALETA[i], PALETA[(i + 5) % len(PALETA)]

    def desenha(self, cr, frame, escala=1.0, ate=None):
        cw, ch = self.cw, self.ch
        for col, linha, larg, fg, bg in self.runs(frame):
            if ate is not None and linha >= ate:
                break
            cr.set_source_rgb(*bg)
            cr.rectangle(col * cw, linha * ch, larg * cw, ch)
            cr.fill()
            lay = self.layout(cr, "▀" * larg)
            cr.set_source_rgb(*fg)
            cr.move_to(col * cw, linha * ch)
            PangoCairo.show_layout(cr, lay)


def mede(win, banco, frames, modo, img):
    """Desenha `frames` frames com a estratégia pedida; devolve ms/frame."""
    display = win.get_display()
    janela = win.get_window()
    import cairo

    regiao = cairo.Region(cairo.RectangleInt(0, 0, janela.get_width(), janela.get_height()))
    tempos = []
    for frame in range(frames):
        ctx = janela.begin_draw_frame(regiao)
        cr = ctx.get_cairo_context()
        t0 = time.perf_counter()
        if modo == "runs":
            banco.desenha(cr, frame)
        elif modo == "upload":
            cr2 = img[1]
            banco.desenha(cr2, frame)
            cr.set_source_surface(img[0], 0, 0)
            cr.paint()
        elif modo in ("pixmap-so", "pixmap-comp"):
            pix, cr2 = img[2]
            if modo == "pixmap-so":  # só desenha no pixmap
                banco.desenha(cr2, frame)
            else:  # só compõe o pixmap na janela
                cr.set_source_surface(pix, 0, 0)
                cr.rectangle(0, 0, banco.cols * banco.cw, banco.rows * banco.ch)
                cr.fill()
        else:
            pix, cr2 = img[2] if img[2] is not None else (None, None)
            if pix is None:
                raise SystemExit("surface do servidor indisponível")
            linhas = banco.rows if modo == "pixmap" else max(1, banco.rows // 10)
            banco.desenha(cr2, frame, ate=linhas)
            # compõe só o que mudou: 1 pedido, do tamanho da área desenhada
            cr.set_source_surface(pix, 0, 0)
            cr.rectangle(0, 0, banco.cols * banco.cw, linhas * banco.ch)
            cr.fill()
        display.sync()  # XSync: o servidor entra na conta
        tempos.append((time.perf_counter() - t0) * 1000.0)
        janela.end_draw_frame(ctx)
    tempos.sort()
    return tempos[len(tempos) // 2], sum(tempos) / len(tempos)


def main(argv):
    ap = argparse.ArgumentParser(description="N ops de cairo x 1 upload por frame")
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--cols", type=int, default=61)
    ap.add_argument("--rows", type=int, default=18)
    ap.add_argument("--font-size", type=int, default=13)
    ap.add_argument("--font", default="Monospace")
    a = ap.parse_args(argv)

    win = Gtk.Window()
    win.set_default_size(10, 10)
    win.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    dpi = Gdk.Screen.get_default().get_resolution() or 96.0
    font_desc = Pango.FontDescription.from_string("%s %d" % (a.font, a.font_size))
    cw, ch = celula(font_desc, dpi)
    larg, alt = a.cols * cw, a.rows * ch
    win.resize(larg, alt)
    while Gtk.events_pending():
        Gtk.main_iteration()

    import cairo

    imagem = cairo.ImageSurface(cairo.FORMAT_RGB24, larg, alt)
    banco = Banco(a.cols, a.rows, cw, ch, font_desc)
    pix = win.get_window().create_similar_surface(cairo.CONTENT_COLOR, larg, alt)
    img = (imagem, cairo.Context(imagem), (pix, cairo.Context(pix)))

    # aquece as duas estratégias (Pango e o servidor) para não medir rampa
    modos = ("runs", "upload", "pixmap", "pixmap10", "pixmap-so", "pixmap-comp")
    for modo in modos:
        mede(win, banco, 10, modo, img)

    resultados = {}
    for modo in modos:
        resultados[modo] = mede(win, banco, a.frames, modo, img)
    med_runs, avg_runs = resultados["runs"]

    print(
        "display %s · grade %dx%d · célula %dx%d · %d frames"
        % (win.get_display().get_name(), a.cols, a.rows, cw, ch, a.frames)
    )
    print(
        "runs   mediana %6.2f ms  média %6.2f ms  (%d runs/frame)"
        % (med_runs, avg_runs, len(banco.runs(0)))
    )
    for modo, rotulo in (
        ("upload", "1 pedido/frame, pixels pelo fio"),
        ("pixmap", "surface do servidor, compõe tudo"),
        ("pixmap10", "surface do servidor, 10% redesenhado"),
        ("pixmap-so", "só desenhar no pixmap (sem compor)"),
        ("pixmap-comp", "só compor o pixmap (sem desenhar)"),
    ):
        med, avg = resultados[modo]
        print(
            "%-8s mediana %6.2f ms  média %6.2f ms  (%s)  razão %.2fx"
            % (modo, med, avg, rotulo, med_runs / med if med else 0.0)
        )
    win.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
