"""Cores e CSS do cromo da janela (lateral, cartões) — puro, sem Gtk.

Esta é a única fonte de cor da interface: o CSS é gerado daqui e ninguém mais
escreve hex. A paleta do terminal é outra coisa (`palette.py`: célula, xterm-256
e truecolor) e não se mistura com esta.

Contraste é medido, não opinado: `contrast()` é sRGB relativo (WCAG) e o check
`style_contrast` exige o mínimo entre cada texto e o seu fundo.
"""

SIDEBAR_BG = "#000000"  # fundo da lateral e do cartão normal
CARD_HOVER_BG = "#141414"  # cartão sob o mouse
CARD_FG = "#e0e0e0"  # nome do workspace
CARD_INFO_FG = "#8a8a8a"  # linha de baixo (aba ativa, contagem)
CARD_SEL_BG = "#1f4d2e"  # workspace ativo: verde escuro
CARD_SEL_FG = "#ffffff"  # nome sobre o verde escuro
CARD_SEL_INFO_FG = "#cfe3d5"  # linha de baixo sobre o verde
TAB_BAR_BG = "#000000"  # barra de abas (o vazio ao lado das abas)
TAB_ACTIVE_BG = "#1f4d2e"  # aba ativa: mesmo verde do workspace ativo
TAB_SEP = "#333333"  # linha de 1 px entre as abas
TOAST_BG = "#1f4d2e"  # fundo do toast de aviso (mesmo verde do cartão ativo)
TOAST_FG = "#ffffff"  # texto do toast
TOAST_ERR_BG = "#5c1f1f"  # toast de erro de configuração
TOAST_ERR_FG = "#ffffff"

CSS = """
#sidebar { background-color: %(SIDEBAR_BG)s; }
#sidebar row { background-color: %(SIDEBAR_BG)s; }
#sidebar row:hover { background-color: %(CARD_HOVER_BG)s; }
#sidebar row:selected { background-color: %(CARD_SEL_BG)s; }
.card { background-color: transparent; }
.card label { color: %(CARD_FG)s; background-color: transparent; }
.card .info { color: %(CARD_INFO_FG)s; }
#sidebar row:selected .card label { color: %(CARD_SEL_FG)s; }
#sidebar row:selected .card .info { color: %(CARD_SEL_INFO_FG)s; }
notebook > header { background-color: %(TAB_BAR_BG)s; border-color: %(TAB_BAR_BG)s; }
notebook > header > tabs { background-color: %(TAB_BAR_BG)s; }
notebook > header > tabs > tab {
  background-color: %(TAB_BAR_BG)s; box-shadow: none; color: %(CARD_FG)s;
  border-width: 0 0 0 1px; border-style: solid; border-color: %(TAB_SEP)s;
  border-radius: 0; padding: 5px 16px; }
notebook > header > tabs > tab:first-child { border-left-width: 0; }
notebook > header > tabs > tab:hover { background-color: %(CARD_HOVER_BG)s; }
notebook > header > tabs > tab:checked { background-color: %(TAB_ACTIVE_BG)s; }
#toast {
  background-color: %(TOAST_BG)s; color: %(TOAST_FG)s; border-radius: 6px;
  padding: 8px 16px; }
#toast.erro { background-color: %(TOAST_ERR_BG)s; color: %(TOAST_ERR_FG)s; }
#toast label { color: inherit; }
"""


def _tokens():
    return {
        k: v
        for k, v in globals().items()
        if k.isupper() and isinstance(v, str) and v.startswith("#")
    }


def css():
    """O CSS com os tokens substituídos."""
    return CSS % _tokens()


def _linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(fg, bg):
    """Razão de contraste WCAG entre duas cores '#rrggbb' (1.0 a 21.0)."""
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)
