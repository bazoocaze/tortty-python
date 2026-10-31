#!/usr/bin/env python3
"""Mock do toast do bzmux: só o visual, sempre no rodapé-centro.

Cada linha da barra é uma dimensão da lista de opções, com os mesmos números e
letras: 1 forma · 2 padding · 2 largura · 3 fundo · 4 acento · 5 borda/sombra ·
6 tipografia · 7 entrada · 8 indicador de tempo. A pílula da base reflete a
combinação escolhida na hora (clicar de novo reexibe a entrada).

    python3 tools/toastmock.py
"""

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

CORES = {
    "sucesso": {
        "escuro": "#1f4d2e",
        "claro": "#245c33",
        "acento": "#4c9e67",
        "icone": "✓",
        "titulo": "Configuração aplicada",
        "fala": "shell /bin/dash",
    },
    "aviso": {
        "escuro": "#5c4a12",
        "claro": "#6b5614",
        "acento": "#b3912e",
        "icone": "!",
        "titulo": "Aviso na configuração",
        "fala": "chave desconhecida: shel",
    },
    "erro": {
        "escuro": "#5c1f1f",
        "claro": "#7a2626",
        "acento": "#c05252",
        "icone": "⚠",
        "titulo": "Erro na configuração",
        "fala": "shell não executável: /nao/existe",
    },
}
LOREM = "".join(
    linha + "\n"
    for _ in range(2)
    for linha in (
        "lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod",
        "tempor incididunt ut labore et dolore magna aliqua. ut enim ad minim",
        "veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea",
        "commodo consequat.",
        "",
        "duis aute irure dolor in reprehenderit in voluptate velit esse cillum",
        "dolore eu fugiat nulla pariatur. excepteur sint occaecat cupidatat non",
        "proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
        "",
        "sed ut perspiciatis unde omnis iste natus error sit voluptatem",
        "accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab",
        "illo inventore veritatis et quasi architecto beatae vitae dicta sunt",
        "explicabo. nemo enim ipsam voluptatem quia voluptas sit aspernatur aut",
        "odit aut fugit, sed quia consequuntur magni dolores eos qui ratione",
        "voluptatem sequi nesciunt.",
        "",
        "neque porro quisquam est, qui dolorem ipsum quia dolor sit amet,",
        "consectetur, adipisci velit, sed quia non numquam eius modi tempora",
        "incidunt ut labore et dolore magnam aliquam quaerat voluptatem.",
        "",
    )
)

# rótulos das dimensões: (chave, número+título, opções)
DIMENSOES = (
    ("1", "1 forma", (("a", "6px"), ("b", "8px"), ("c", "4px"), ("e", "pílula"))),
    (
        "2",
        "2 padding",
        (
            ("h", "8x16 hoje"),
            ("a", "meia"),
            ("b", "1 altura"),
            ("c", "2 alturas"),
            ("d", "3 alturas"),
        ),
    ),
    (
        "2w",
        "2 largura",
        (("i", "encolhe"), ("ii", "fixa 60 col")),
    ),
    ("3", "3 fundo", (("a", "escuro"), ("b", "claro"), ("c", "neutro"))),
    ("4", "4 acento", (("a", "nada"), ("b", "ícone"), ("c", "barra"), ("d", "ponto"))),
    (
        "5",
        "5 borda/sombra",
        (("a", "nada"), ("b", "borda"), ("c", "sombra"), ("d", "borda+sombra")),
    ),
    (
        "6",
        "6 tipografia",
        (("a", "normal"), ("b", "semibold"), ("c", "2 linhas"), ("d", "esquerda")),
    ),
    ("7", "7 entrada", (("a", "slide"), ("b", "fade"), ("c", "fade+sobe"))),
    ("8", "8 tempo", (("a", "nada"), ("b", "fio"))),
)

CSS = """
window, #board, #board text { background-color: #000000; color: #ffffff; }
button { background-image: none; background-color: #2a2a2a; color: #f0f0f0;
  border: 1px solid #454545; border-radius: 4px; padding: 2px 7px;
  box-shadow: none; text-shadow: none; }
button:hover { background-color: #383838; }
button:checked { background-color: #1f4d2e; border-color: #357a46; }
#barra { background-color: #141414; border-bottom: 1px solid #333333; }
#barra label { color: #e0e0e0; }
#toast label { color: #ffffff; }
#toast .detalhe { color: #dddddd; }
scrollbar { opacity: 0; min-width: 0; min-height: 0; }
"""


class Mock(Gtk.Window):
    def __init__(self):
        super().__init__(title="toast mock")
        self.sev = "erro"
        # hoje = a combinação que existe no app (sem ícone, sem sombra, 6 px)
        self.hoje_escolha = {
            "1": "a",
            "2": "h",
            "2w": "i",
            "3": "a",
            "4": "a",
            "5": "a",
            "6": "a",
            "7": "a",
            "8": "a",
        }
        self.escolha = dict(self.hoje_escolha)
        self.botoes = {}
        self.sincronizando = False
        self.prov = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.prov.load_from_data(CSS.encode())

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        barra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        barra.set_name("barra")
        barra.set_border_width(5)

        linha = Gtk.Box(spacing=4)
        rotulo = Gtk.Label(label="cor")
        rotulo.set_xalign(0)
        rotulo.set_size_request(110, -1)
        linha.pack_start(rotulo, False, False, 0)
        self.cor_botoes = {}
        for nome in CORES:
            b = Gtk.ToggleButton(label=nome)
            b.set_active(nome == self.sev)
            b.connect("toggled", self.on_cor, nome)
            self.cor_botoes[nome] = b
            linha.pack_start(b, False, False, 0)
        reexibir = Gtk.Button(label="reexibir")
        reexibir.connect("clicked", lambda *a: self.preview())
        linha.pack_end(reexibir, False, False, 0)
        hoje = Gtk.Button(label="mostrar como é hoje")
        hoje.connect("clicked", lambda *a: self.volta_hoje())
        linha.pack_end(hoje, False, False, 0)
        barra.pack_start(linha, False, False, 0)

        for chave, titulo, opcoes in DIMENSOES:
            barra.pack_start(self.linha(chave, titulo, opcoes), False, False, 0)
        vbox.pack_start(barra, False, False, 0)

        board = Gtk.TextView()
        board.set_name("board")
        board.set_editable(False)
        board.set_cursor_visible(False)
        board.override_font(fonte())
        board.set_left_margin(12)
        board.set_top_margin(6)
        board.get_buffer().set_text(LOREM)
        # sem o ScrolledWindow o TextView reporta a altura do conteúdo como
        # mínima (1154 px): a janela não caberia na tela e o rodapé ficaria fora
        rolagem = Gtk.ScrolledWindow()
        # AUTOMATIC (e barra escondida no CSS): com NEVER o scroller herda a
        # altura do conteúdo como mínimo e a janela cresce para 1463 px
        rolagem.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        rolagem.set_overlay_scrolling(True)
        rolagem.add(board)
        self.overlay = Gtk.Overlay()
        self.overlay.add(rolagem)
        vbox.pack_start(self.overlay, True, True, 0)

        rot = Gtk.Label()
        lay = rot.create_pango_layout("")
        lay.set_font_description(fonte())
        self.altura = lay.get_pixel_size()[1]

        self.add(vbox)
        self.preview()

    # -- barra de opções ------------------------------------------------
    def linha(self, chave, titulo, opcoes):
        linha = Gtk.Box(spacing=4)
        rotulo = Gtk.Label(label=titulo)
        rotulo.set_xalign(0)
        rotulo.set_size_request(110, -1)
        linha.pack_start(rotulo, False, False, 0)
        grupo = []
        for letra, texto in opcoes:
            b = Gtk.ToggleButton(label="%s %s" % (letra, texto))
            b.set_active(self.escolha[chave] == letra)
            b.connect("toggled", self.on_opcao, chave, letra, grupo)
            grupo.append(b)
            self.botoes[(chave, letra)] = b
            linha.pack_start(b, False, False, 0)
        return linha

    def on_opcao(self, botao, chave, letra, grupo):
        if self.sincronizando or not botao.get_active():
            return
        self.escolha[chave] = letra
        for outro in grupo:
            if outro is not botao and outro.get_active():
                outro.set_active(False)
        self.preview()

    def volta_hoje(self):
        """Marca a combinação de hoje nos botões e redesenha."""
        self.escolha = dict(self.hoje_escolha)
        self.sincronizando = True
        for (chave, letra), botao in self.botoes.items():
            botao.set_active(self.escolha[chave] == letra)
        self.sincronizando = False
        self.preview()

    def on_cor(self, botao, nome):
        if not botao.get_active():
            return
        self.sev = nome
        for outro_nome, outro in self.cor_botoes.items():
            if outro_nome != nome and outro.get_active():
                outro.set_active(False)
        self.preview()

    # -- a pílula -------------------------------------------------------
    def preview(self):
        """Redesenha a pílula do rodapé com a combinação escolhida."""
        for filho in self.overlay.get_children()[1:]:
            self.overlay.remove(filho)
        self.prov.load_from_data((CSS + css_toast(self.escolha, self.sev, self.altura)).encode())

        rev = Gtk.Revealer()
        rev.set_halign(Gtk.Align.CENTER)
        rev.set_valign(Gtk.Align.END)
        rev.set_margin_bottom(40)
        tipos = {
            "a": Gtk.RevealerTransitionType.SLIDE_DOWN,
            "b": Gtk.RevealerTransitionType.CROSSFADE,
            "c": Gtk.RevealerTransitionType.SLIDE_UP,
        }
        rev.set_transition_type(tipos[self.escolha["7"]])
        rev.set_transition_duration(220)

        caixa = Gtk.EventBox()
        caixa.set_name("toast")
        conteudo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        conteudo.get_style_context().add_class("corpo")
        linha = Gtk.Box(spacing=10)

        acento = self.escolha["4"]
        if acento == "b":
            linha.pack_start(self.texto(CORES[self.sev]["icone"]), False, False, 0)
        elif acento == "c":
            barra = Gtk.EventBox()
            barra.get_style_context().add_class("acento-barra")
            barra.set_size_request(4, -1)
            linha.pack_start(barra, False, False, 0)
        elif acento == "d":
            ponto = Gtk.EventBox()
            ponto.get_style_context().add_class("acento-ponto")
            ponto.set_size_request(10, 10)
            ponto.set_valign(Gtk.Align.CENTER)
            linha.pack_start(ponto, False, False, 0)

        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        if self.escolha["6"] == "c":
            textos.pack_start(self.texto(CORES[self.sev]["titulo"]), False, False, 0)
            detalhe = self.texto(CORES[self.sev]["fala"])
            detalhe.get_style_context().add_class("detalhe")
            textos.pack_start(detalhe, False, False, 0)
        else:
            textos.pack_start(self.texto(CORES[self.sev]["fala"]), False, False, 0)
        if self.escolha["2w"] == "ii":
            for filho in textos.get_children():
                filho.set_line_wrap(True)
                filho.set_max_width_chars(60)
            caixa.set_size_request(640, -1)
        if self.escolha["6"] == "d":  # à esquerda, sem centralizar
            textos.set_halign(Gtk.Align.START)
        linha.pack_start(textos, False, False, 0)
        conteudo.pack_start(linha, False, False, 0)

        if self.escolha["8"] == "b":  # fio de tempo na base
            fio = Gtk.EventBox()
            fio.get_style_context().add_class("fio")
            fio.set_size_request(160, 2)
            conteudo.pack_start(fio, False, False, 0)

        caixa.add(conteudo)
        rev.add(caixa)
        self.overlay.add_overlay(rev)
        rev.show_all()
        rev.set_reveal_child(True)

    def texto(self, conteudo):
        label = Gtk.Label(label=conteudo)
        label.override_font(fonte())
        return label


def css_toast(escolha, sev, altura):
    """CSS da pílula; padding em fatores da altura da fonte (todos os lados)."""
    cor = CORES[sev]
    raio = {"a": "6px", "b": "8px", "c": "4px", "e": "14px"}[escolha["1"]]
    if escolha["2"] == "h":  # hoje: 8 vertical x 16 horizontal, só de referência
        corpo = "8px 16px"
    else:
        fator = {"a": 0.5, "b": 1.0, "c": 2.0, "d": 3.0}[escolha["2"]]
        corpo = "%dpx" % round(fator * altura)
    fundo = {"a": cor["escuro"], "b": cor["claro"], "c": "#2a2a2a"}[escolha["3"]]
    borda = ""
    if escolha["5"] in ("b", "d"):
        borda = "border: 1px solid %s;" % cor["acento"]
    sombra = ""
    if escolha["5"] in ("c", "d"):
        sombra = "box-shadow: 0 3px 10px rgba(0, 0, 0, 0.75);"
    peso = "font-weight: 600;" if escolha["6"] == "b" else ""
    # o EventBox ignora padding no cálculo do tamanho (o fundo pinta mas
    # não cresce): o padding vai na caixa interna .corpo, que é Gtk.Box
    return """
#toast { background-color: %(fundo)s; border-radius: %(raio)s;
  %(borda)s %(sombra)s }
#toast .corpo { padding: %(corpo)s; }
#toast label { color: #ffffff; %(peso)s }
#toast .detalhe { color: #dddddd; }
.acento-barra { background-color: %(acento)s; border-radius: 2px; }
.acento-ponto { background-color: %(acento)s; border-radius: 5px; }
.fio { background-color: %(acento)s; border-radius: 1px; }
""" % {
        "fundo": fundo,
        "raio": raio,
        "corpo": corpo,
        "borda": borda,
        "sombra": sombra,
        "peso": peso,
        "acento": cor["acento"],
    }


def fonte():
    """Monospace 13 pontos, a mesma fonte da grade do bzmux."""
    desc = Pango.FontDescription()
    desc.set_family("Monospace")
    desc.set_size(13 * Pango.SCALE)
    return desc


def encaixa(win):
    """Abre na área útil do monitor: maximize() do Marco somava a barra."""
    tela = Gdk.Screen.get_default()
    area = tela.get_monitor_workarea(tela.get_primary_monitor())
    win.set_default_size(area.width, area.height)
    win.move(area.x, area.y)
    win.show_all()


def main():
    win = Mock()
    win.connect("destroy", Gtk.main_quit)
    encaixa(win)
    Gtk.main()


if __name__ == "__main__":
    main()
