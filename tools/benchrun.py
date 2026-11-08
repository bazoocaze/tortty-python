#!/usr/bin/env python3
"""benchrun.py — uma medição do doom-fire com a condição travada pelo GRID.

O número do benchmark não depende da janela em pixels: depende de quantas
células o fio desenha. Só que o grid cai da conta janela/célula, e a célula
muda com a fonte e com o Xft.dpi da sessão — a mesma janela de 980x640 dá 70x21
com Xft.dpi 130 e 98x27 com 96. Medir "no olho" produz número de outra condição.

Este script inverte a ordem e deixa o resto do drama de fora:

- sobe o app com o socket de introspecção e um XDG_STATE_HOME descartável (nada
  de geometria salva nem janela maximizada de uma execução anterior);
- pede o grid ao próprio app e usa o verbo `resize` até ele bater no alvo — o
  alvo é em células (61x18, a janela padrão na tela do dia a dia), não em
  pixels;
- confere o grid e, se não bater, sai com código 3 em vez de imprimir número de
  outra condição;
- só então digita o doomfire no pty. É isto que mata a corrida do arranque: o
  filho nasce depois da janela assentada, então ele mede o grid de verdade (com
  --cmd ele podia medir o padrão 80x24 antes do primeiro TIOCSWINSZ).

Uso: tools/benchrun.py [--frames N] [--cols C] [--rows R] [--font-size P]
                       [--app SCRIPT] [--env K=V]... [--stats ARQ] [--timeout S]

--cols 0 / --rows 0 deixam o grid como está (imprime o que veio; não é
comparável com a referência). Imprime linhas `chave valor` no stdout; uma
medição por execução — a escada é o bench.sh.

Roda com o python do sistema (só stdlib); quem sobe o app é o --app (run.sh por
padrão), que escolhe o python com gi. Roda no display atual: feche o que estiver
desenhando, dois terminais disputando CPU contaminam.

MIT (ver LICENSE).
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PADRAO = os.path.join(os.path.dirname(HERE), "run.sh")
DOOMFIRE = os.path.join(HERE, "doomfire.py")


class Falha(Exception):
    """Erro de condição ou de protocolo: vira mensagem e código de saída."""


class Alvo:
    """Cliente do socket de introspecção: um pedido JSON por linha."""

    def __init__(self, caminho):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(10)
        self.s.connect(caminho)
        self.buf = b""

    def pede(self, **req):
        cmd = req.pop("cmd")
        self.s.sendall((json.dumps({"cmd": cmd, **req}) + "\n").encode())
        while b"\n" not in self.buf:
            pedaco = self.s.recv(65536)
            if not pedaco:
                raise Falha("socket fechou antes da resposta")
            self.buf += pedaco
        linha, _, self.buf = self.buf.partition(b"\n")
        resp = json.loads(linha)
        if not resp.get("ok"):
            raise Falha(resp.get("err", "resposta sem ok"))
        return resp

    def fecha(self):
        try:
            self.s.close()
        except OSError:
            pass


def espera_socket(caminho, proc, limite=20.0):
    """Espera o arquivo existir E aceitar conexão (o listen vem depois)."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if proc.poll() is not None:
            raise Falha("o app morreu antes de abrir o socket (código %s)" % proc.returncode)
        if os.path.exists(caminho):
            try:
                return Alvo(caminho)
            except OSError:
                pass
        time.sleep(0.1)
    raise Falha("socket %s não abriu em %.0fs" % (caminho, limite))


def trava_grid(cliente, cols, rows, tentativas=6):
    """Usa o verbo `resize` até o grid bater no alvo; devolve o estado final."""
    st = cliente.pede(cmd="state")
    if not cols or not rows:
        return st
    for _ in range(tentativas):
        if st["cols"] == cols and st["rows"] == rows:
            return st
        cliente.pede(cmd="resize", cols=cols, rows=rows)
        time.sleep(0.35)
        st = cliente.pede(cmd="state")
    if st["cols"] != cols or st["rows"] != rows:
        raise Falha(
            "grade ficou %dx%d, alvo %dx%d (WM recusou o resize?)"
            % (st["cols"], st["rows"], cols, rows)
        )
    return st


def amostra_frequencia(parar, guarda):
    """Maior frequência do instante, amostrada enquanto a medição roda."""
    while not parar.is_set():
        try:
            valores = []
            for cpu in os.listdir("/sys/devices/system/cpu"):
                caminho = "/sys/devices/system/cpu/%s/cpufreq/scaling_cur_freq" % cpu
                try:
                    with open(caminho) as f:
                        valores.append(int(f.read()))
                except OSError:
                    pass
            if valores:
                guarda.append(max(valores))
        except OSError:
            pass
        parar.wait(0.2)


def le_stats(caminho):
    """Lê o arquivo do doomfire e devolve o dicionário chave -> texto."""
    dados = {}
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            campos = linha.split(None, 1)
            if len(campos) == 2:
                dados[campos[0].rstrip("/")] = campos[1].strip()
    return dados


def le_prof(log):
    """Extrai draw e pty da linha `prof:` que a view imprime ao fechar."""
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            linhas = [linha for linha in f if linha.startswith("prof:")]
    except OSError:
        return {}
    if not linhas:
        return {}
    achado = {}
    for campo in linhas[-1][5:].split("|"):
        partes = campo.split()
        if len(partes) >= 2 and partes[0] in ("draw", "pty"):
            achado[partes[0]] = partes[2].split("/")[0]  # 5.91ms/call -> 5.91
    return achado


def main(argv):
    ap = argparse.ArgumentParser(description="uma medição do doom-fire pelo grid")
    ap.add_argument("--frames", type=int, default=1200)
    ap.add_argument("--cols", type=int, default=61)
    ap.add_argument("--rows", type=int, default=18)
    ap.add_argument("--font-size", default="13")
    ap.add_argument("--app", default=APP_PADRAO)
    ap.add_argument("--env", action="append", default=[], metavar="K=V")
    ap.add_argument("--stats", default="")
    ap.add_argument("--timeout", type=float, default=0)
    a = ap.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="tortty-python-bench-")
    conf = os.path.join(tmp, "tortty-python.conf")
    sock = os.path.join(tmp, "tortty-python.sock")
    stats = a.stats or os.path.join(tmp, "stats.txt")
    log = os.path.join(tmp, "app.log")
    with open(conf, "w", encoding="utf-8") as f:
        f.write("font_size %s\n" % a.font_size)

    env = dict(os.environ)
    env["PYTERM_PROF"] = "1"
    env["XDG_STATE_HOME"] = os.path.join(tmp, "state")  # nada de geometria salva
    env.pop("PYTERM_GEOM", None)  # o alvo é o grid, não o pixel
    for par in a.env:
        chave, _, valor = par.partition("=")
        env[chave] = valor

    ordem = [
        a.app,
        "-c",
        conf,
        "--debug-log",
        "off",
        "--debug-socket",
        sock,
    ]
    limite = a.timeout or (a.frames / 20.0 + 60)
    frequencias = []
    parar = None
    with open(log, "w", encoding="utf-8") as saida:
        proc = subprocess.Popen(ordem, env=env, stdout=saida, stderr=saida)
    try:
        cliente = espera_socket(sock, proc)
        st = trava_grid(cliente, a.cols, a.rows)
        if os.path.exists(stats):
            os.unlink(stats)
        parar = threading.Event()
        amostrador = threading.Thread(
            target=amostra_frequencia, args=(parar, frequencias), daemon=True
        )
        amostrador.start()
        inicio = time.monotonic()
        cliente.pede(
            cmd="write",
            data="python3 %s --fps 0 --frames %d --stats-to %s\r" % (DOOMFIRE, a.frames, stats),
        )
        while not os.path.exists(stats):
            if time.monotonic() - inicio > limite:
                raise Falha("o doomfire não escreveu %s em %.0fs" % (stats, limite))
            if proc.poll() is not None:
                raise Falha("o app morreu durante a carga (código %s)" % proc.returncode)
            time.sleep(0.2)
        cliente.pede(cmd="quit")
        cliente.fecha()
    finally:
        if parar is not None:
            parar.set()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)

    dados = le_stats(stats)
    prof = le_prof(log)
    grade = dados.get("grade", "").split()[0] if dados.get("grade") else "?"
    pico = max(frequencias) / 1e6 if frequencias else 0.0
    media = sum(frequencias) / len(frequencias) / 1e6 if frequencias else 0.0
    mbs = dados.get("escrito", "")
    mbs = mbs.split("(")[-1].rstrip(")") if "(" in mbs else "-"
    print("grade %s" % grade)
    print("fps %s" % dados.get("fps", "-"))
    print("mbs %s" % mbs)
    print("bpf %s" % dados.get("bytes/frame", "-"))
    print("draw %s" % prof.get("draw", "-"))
    print("pty %s" % prof.get("pty", "-"))
    print("dpi %s" % st.get("dpi", "-"))
    print("ghz %.2f/%.2f" % (media, pico))
    print("log %s" % log)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Falha as erro:
        print("erro: %s" % erro, file=sys.stderr)
        sys.exit(3)
