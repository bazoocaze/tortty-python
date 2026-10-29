"""Estado da janela entre execuções: posição, tamanho e maximizado.

Puro (sem gi) para poder ser testado nos checks: quem fala com Gtk/Gdk é o
window.py, que aqui só entrega e recebe retângulos.

O arquivo é JSON em XDG_STATE_HOME (estado, não configuração): se ele sumir, a
janela abre no padrão e nada mais acontece.
"""

import json
import os

MIN_W, MIN_H = 320, 200  # abaixo disto é lixo de WM/restauração, não geometria


def state_path():
    """.../bzmux/window.json em XDG_STATE_HOME (fallback ~/.local/state)."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "bzmux", "window.json")


def load():
    """Dicionário salvo, ou None se não houver/estiver corrompido."""
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save(data):
    """Grava de forma atômica (tmp + rename): nunca deixa JSON pela metade."""
    path = state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        pass  # não poder salvar não pode derrubar o fechamento


def fit(x, y, w, h, monitors):
    """Retângulo utilizável: tamanho são, e o canto dentro de algum monitor.

    Devolve (x, y, w, h) ou None se não sobrar nada aproveitável — monitor
    desconectado, arquivo editado à mão, resolução trocada.
    """
    try:
        x, y, w, h = int(x), int(y), int(w), int(h)
    except (TypeError, ValueError):
        return None
    if w < MIN_W or h < MIN_H:
        return None
    if not monitors:
        return (x, y, w, h)
    # basta o canto superior esquerdo estar num monitor: a barra de título fica
    # alcançável e o WM nunca abre a janela fora da tela
    for mx, my, mw, mh in monitors:
        if mx <= x < mx + mw and my <= y < my + mh:
            return (x, y, w, h)
    return None
