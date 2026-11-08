#!/usr/bin/env python3
"""uploadbench.py — vale trocar N operações de cairo por 1 upload por frame?

O P27 propõe cachear linha em surface e reduzir o número de runs. No display
real (glamor), o custo do 2D é **por operação**: 13,9 ms por frame em 61x18,
contra 4,2 ms no Xvfb na mesma grade. Se for esse o mecanismo, desenhar o frame
num ImageSurface e subir uma imagem só deveria custar bem menos que dezenas de
preenchimentos pequenos — e é isso que este microbench mede, sem tocar no app.

Duas estratégias, mesmo conteúdo, mesmo número de pixels:

- `runs`: o desenho de hoje — por run, um `fill_rectangle` de fundo e um
  `show_layout` de texto direto na janela.
- `upload`: o mesmo frame num ImageSurface e um `set_source_surface` + `paint`
  na janela — um pedido por frame, mas os pixels sobem pelo fio a cada frame.
- `pixmap`: o frame num surface **do servidor** (`create_similar_surface`), como
  o cache de linha do P27 sonha: desenha no pixmap e compõe uma vez, sem subir
  pixel nenhum.
- `pixmap 10%`: idem, mas redesenhando só 10% da grade (o caso do dirty-rect).

Cada frame sorteia cores de uma paleta de 37 tons (como o doom-fire), então não
há cache de conteúdo entre frames. A cada frame há `Gdk.Display.sync()`, que é
XSync: garante que o trabalho do servidor entrou na conta (o tortty-python não sincroniza;
lá o custo aparece como bloqueio do buffer de pedidos, mas o total é o mesmo).

Uso: tools/uploadbench.py [--frames N] [--cols C] [--rows R] [--font-size P]
                          [--display :0]
Roda no display atual; para comparar com um virtual:
    Xvfb :99 -screen 0 1600x1000x24 & DISPLAY=:99 tools/uploadbench.py

Imprime ms/frame de cada estratégia e a razão entre elas. Se a razão ficar perto
de 1, o P27 não se paga por aí; se ficar em 3x ou mais, o upload é o caminho.

MIT (ver LICENSE).
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
