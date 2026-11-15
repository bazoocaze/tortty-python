"""Window state between runs: position, size and maximised.

Pure (no gi) so that the checks can test it: whoever talks to Gtk/Gdk is
window.py, which only hands rectangles in and out here.

The file is JSON under XDG_STATE_HOME (state, not configuration): if it goes
away, the window opens at the default and nothing else happens.
"""

import fcntl
import json
import os

MIN_W, MIN_H = 320, 200  # abaixo disto é lixo de WM/restauração, não geometria
SNAP_PREFIX = "session-"  # foto de aba (P57), ao lado do window.json
SNAP_EXT = ".ans"


def state_path():
    """.../tortty-python/window.json em XDG_STATE_HOME (fallback ~/.local/state)."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "tortty-python", "window.json")


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


def lock():
    """Pega o `flock` do estado: quem tem é o dono da sessão (P91).

    Devolve o arquivo aberto (mantê-lo aberto é o que segura o lock) ou None
    quando outra janela é a dona. Fechar o arquivo solta o lock.
    """
    path = os.path.join(snapshots_dir(), "state.lock")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = open(path, "a+", encoding="utf-8")
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return fd


def snapshot_name(ws, tab):
    """Nome do arquivo da foto de uma aba: um por (workspace, aba) (P57)."""
    return "%s%d-%d%s" % (SNAP_PREFIX, ws, tab, SNAP_EXT)


def snapshots_dir():
    """Diretório das fotos: o mesmo do window.json."""
    return os.path.dirname(state_path())


def save_snapshots(snaps):
    """Grava a foto de cada aba; o que não foi reescrito (aba fechada) some (P57).

    `snaps` é [(ws, aba, texto ANSI)]. Falhar aqui não pode derrubar o
    fechamento: a aba volta limpa na próxima execução, como antes do P57.
    """
    d = snapshots_dir()
    try:
        os.makedirs(d, exist_ok=True)
        for nome in os.listdir(d):
            if nome.startswith(SNAP_PREFIX) and nome.endswith(SNAP_EXT):
                os.remove(os.path.join(d, nome))
        for ws, tab, texto in snaps:
            _write_atomic(os.path.join(d, snapshot_name(ws, tab)), texto.encode("utf-8"))
    except OSError:
        pass


def load_snapshot(ws, tab):
    """Texto da foto daquela aba, ou None se não houver/vazia (P57)."""
    try:
        with open(os.path.join(snapshots_dir(), snapshot_name(ws, tab)), "rb") as f:
            dados = f.read()
    except OSError:
        return None
    return dados.decode("utf-8", "replace") or None


def _write_atomic(path, data):
    """tmp + rename: leitor nunca vê arquivo pela metade."""
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def layout(data):
    """Layout validado do dict salvo (P50), ou None se não houver/for lixo.

    O formato espelha o `Layout` do Rust: workspaces com nome e o cwd de cada
    aba, mais o índice do que estava na frente. cwd que não existe mais vira
    None (a aba nasce no diretório padrão do shell), como o Rust.
    """
    lay = data.get("layout") if isinstance(data, dict) else None
    if not isinstance(lay, dict):
        return None
    wss = lay.get("workspaces")
    if not isinstance(wss, list) or not wss:
        return None
    out = []
    for w in wss:
        if not isinstance(w, dict):
            return None
        nome, cwds = w.get("name"), w.get("cwds")
        if not isinstance(nome, str) or not isinstance(cwds, list):
            return None
        limpos = [c if isinstance(c, str) and os.path.isdir(c) else None for c in cwds]
        if limpos:  # workspace sem aba não existe (fecha junto com a última)
            out.append({"name": nome, "cwds": limpos})
    if not out:
        return None
    iws = lay.get("ws")
    iws = iws if isinstance(iws, int) and 0 <= iws < len(out) else 0
    cwds = out[iws]["cwds"]
    itab = lay.get("tab")
    itab = itab if isinstance(itab, int) and 0 <= itab < len(cwds) else 0
    return {"workspaces": out, "ws": iws, "tab": itab}


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
