#!/bin/sh
# Verificação automática de desenho: abre a janela num display isolado (Xvfb),
# desenha conteúdo conhecido, captura e **compara** — sem janela na sessão de
# trabalho e sem olho humano no resultado.
#
#   tools/render-check.sh               # roda a bateria e diz PASSED/FAILED
#   tools/render-check.sh --keep        # guarda os arquivos auxiliares
#   tools/render-check.sh --display :77 # usa outro display (sobe o Xvfb se faltar)
#
# O que prova, e que nenhum teste headless prova:
#
#   1. a janela desenha (superfície viva): mudou o conteúdo, mudou o pixel;
#   2. a cor sai certa: SGR 41/42 pintam o fundo da célula com color1/color2;
#   3. o texto cai na célula pedida: o glifo pinta dentro da banda da linha;
#   4. tela parada não repinta diferente (duas capturas seguidas = 0);
#   5. cada linha da grade cai na própria banda de pixels (a regressão do
#      espaçamento duplo: a linha `r` saía em `2r`).
#
# Precisa de display (o Xvfb sobe sozinho) e do ImageMagick (`import`); é
# manual, como o resto de tools/ — o teste continua sendo ./run-tests.sh.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DISPLAY_XVFB=${TORTTY_DISPLAY:-:77}
OUT_DIR=${TORTTY_RENDER_DIR:-/tmp/tortty-render}
KEEP=0
SOCK=/tmp/tortty-render.sock

while [ $# -gt 0 ]; do
    case "$1" in
        --keep) KEEP=1; shift ;;
        --display) DISPLAY_XVFB=$2; shift 2 ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "opção desconhecida: $1" >&2; exit 2 ;;
    esac
done

failures=0
ok() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAILURE %s\n' "$1"; failures=$((failures + 1)); }

command -v import >/dev/null || { echo "ImageMagick (import) falta" >&2; exit 2; }
command -v Xvfb >/dev/null || { echo "Xvfb falta" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 falta" >&2; exit 2; }

mkdir -p "$OUT_DIR"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/tortty-render.XXXXXX")
XVFB_PID=
APP_PID=

cleanup() {
    [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
    [ -n "$APP_PID" ] && wait "$APP_PID" 2>/dev/null
    [ -n "$XVFB_PID" ] && kill "$XVFB_PID" 2>/dev/null
    rm -f "$SOCK"
    [ "$KEEP" -eq 1 ] || rm -rf "$TMP"
}
trap cleanup EXIT INT TERM

# display isolado: ninguém vê, ninguém perde foco
if DISPLAY=$DISPLAY_XVFB xdpyinfo >/dev/null 2>&1; then
    :
else
    Xvfb "$DISPLAY_XVFB" -screen 0 1280x800x24 >"$TMP/xvfb.log" 2>&1 &
    XVFB_PID=$!
    i=0
    while ! DISPLAY=$DISPLAY_XVFB xdpyinfo >/dev/null 2>&1; do
        i=$((i + 1))
        [ "$i" -gt 50 ] && { echo "Xvfb não subiu: $(cat "$TMP/xvfb.log")" >&2; exit 2; }
        sleep 0.1
    done
fi

# cores fixas: sem isto o esperado depende do ~/.config de quem roda
cat >"$TMP/tortty.conf" <<'CONF'
background #000000
foreground #ffffff
color1 #ff0000
color2 #00ff00
cursor_blink off
window_padding_width 0
restore_state none
debug_log off
CONF

# PYTERM_GEOM trava o tamanho da janela e desliga o restore/save (o gate não
# pode herdar a sessão de quem roda). O child pinta as duas células de cor e
# dorme: sem shell, o que entra depois é o eco do pty — byte previsível.
PYTERM_GEOM=1000x700 DISPLAY=$DISPLAY_XVFB "$ROOT/run.sh" \
    -c "$TMP/tortty.conf" --debug-socket "$SOCK" \
    --cmd 'printf "\033[41m  \033[0m\033[42m  \033[0m"; sleep 600' \
    >"$TMP/app.log" 2>&1 &
APP_PID=$!

i=0
while [ ! -S "$SOCK" ]; do
    i=$((i + 1))
    [ "$i" -gt 100 ] && { echo "app não abriu o socket" >&2; cat "$TMP/app.log" >&2; exit 2; }
    sleep 0.1
done

# uma pergunta ao app (JSON por linha)
q() {
    python3 - "$SOCK" "$1" <<'PY'
import json, socket, sys
s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
f = s.makefile("rwb")
f.write(sys.argv[2].encode() + b"\n")
f.flush()
sys.stdout.write(f.readline().decode())
PY
}

# o xid vem do NOSSO instance: pegar por classe pegaria outra janela do display
XID=$(q '{"cmd":"state"}' | python3 -c 'import json,sys; print(json.load(sys.stdin).get("xid") or "")')
[ -n "$XID" ] || { echo "app não reportou xid no state" >&2; exit 1; }
# célula em floats: a banda da linha `r` é r*ch, e arredondar o ch acumula
# desvio para baixo da linha verdadeira
CELL=$(q '{"cmd":"state"}' | python3 -c 'import json,sys; st=json.load(sys.stdin); print("%s,%s" % tuple(st["cell"]))')
CWL=${CELL%,*}
CHL=${CELL#*,}
PIXEL="$ROOT/tools/pixel.py"

take() { # take <arquivo>
    DISPLAY=$DISPLAY_XVFB import -window "$XID" "$1" 2>/dev/null
    [ -s "$1" ] || { echo "captura vazia: $1" >&2; return 1; }
}

# a primeira captura tem que já ter o vermelho do SGR 41 (frame vivo)
i=0
while :; do
    if DISPLAY=$DISPLAY_XVFB import -window "$XID" "$OUT_DIR/a.png" 2>/dev/null &&
        [ -s "$OUT_DIR/a.png" ] &&
        python3 "$PIXEL" "$OUT_DIR/a.png" --find ff0000 >/dev/null 2>&1; then
        break
    fi
    i=$((i + 1))
    [ "$i" -gt 50 ] && { echo "a janela não desenhou (sem ff0000)" >&2; cat "$TMP/app.log" >&2; exit 1; }
    sleep 0.2
done
# a origem da grade: o SGR 41 começou na célula (0,0) — x = 0, sem margem
set -- $(python3 "$PIXEL" "$OUT_DIR/a.png" --find ff0000)
X0=$1
Y0=$2

# 1. desenho vivo: conteúdo novo tem que mudar pixel
q '{"cmd":"write","data":"CHANGED\r"}' >/dev/null
sleep 0.5
take "$OUT_DIR/b.png" || fail "captura 2"
if python3 "$PIXEL" --diff "$OUT_DIR/a.png" "$OUT_DIR/b.png" --max 0 >/dev/null 2>&1; then
    fail "conteúdo mudou e nenhum pixel mudou (superfície morta?)"
else
    ok "conteúdo novo mudou os pixels"
fi

# 2. cor pelo SGR 41/42 (color1/color2) e o fundo do resto da linha
EXPECTS=$(python3 -c "
x0, y0, cw, ch = float('$X0'), float('$Y0'), float('$CWL'), float('$CHL')
def p(cx, cy, c):
    return '%d,%d=%s' % (round(x0 + cx), round(y0 + cy), c)
print(p(cw / 2, ch / 2, 'ff0000'), p(2 * cw + cw / 2, ch / 2, '00ff00'),
      p(20 * cw, ch / 2, '000000'))")
# shellcheck disable=SC2086  # a word splitting monta os --expect repetidos
if python3 "$PIXEL" "$OUT_DIR/b.png" $(printf -- '--expect %s ' $EXPECTS) \
    >"$OUT_DIR/colors.txt" 2>&1; then
    ok "SGR 41/42 pintam color1/color2 na célula"
else
    fail "cor errada: $(tr '\n' ' ' <"$OUT_DIR/colors.txt")"
fi

# 3. texto na célula pedida: LINE na linha seguinte, coluna 0 — a grade e os
# pixels têm que dizer a mesma coisa
q '{"cmd":"write","data":"\rLINE\r"}' >/dev/null
sleep 0.5
take "$OUT_DIR/c.png" || fail "captura 3"
if python3 - "$SOCK" "$OUT_DIR/c.png" "$X0" "$Y0" "$CWL" "$CHL" <<'PY'
import json, socket, sys

sock, png, x0, y0, cw, ch = (
    sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]),
    float(sys.argv[5]), float(sys.argv[6]),
)


def q(**kw):
    c = socket.socket(socket.AF_UNIX)
    c.connect(sock)
    f = c.makefile("rwb")
    f.write(json.dumps(kw).encode() + b"\n")
    f.flush()
    r = json.loads(f.readline())
    c.close()
    return r


st = q(cmd="state")
grid = q(cmd="text", where="view", count=st["rows"])["lines"]
row = next((i for i, ln in enumerate(grid) if "LINE" in ln), None)
if row is None or grid[row].index("LINE") != 0:
    print(f"a grade não tem LINE na coluna 0: {grid[:4]!r}")
    sys.exit(1)

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

pb = GdkPixbuf.Pixbuf.new_from_file(png)
rs, nc = pb.get_rowstride(), pb.get_n_channels()
px = pb.get_pixels()
xa, xb = int(x0), int(x0 + 4 * cw)
ya, yb = int(y0 + row * ch), int(y0 + (row + 1) * ch)
achou = False
for yy in range(ya, min(yb, pb.get_height())):
    for xx in range(xa, min(xb, pb.get_width())):
        o = yy * rs + xx * nc
        if px[o] > 90 and px[o + 1] > 90 and px[o + 2] > 90:
            achou = True
            break
    if achou:
        break
if not achou:
    print(f"linha {row} tem LINE na grade e nenhum pixel claro na banda")
    sys.exit(1)
print(f"linha {row}, coluna 0")
PY
then
    ok "o texto pinta dentro da célula pedida"
else
    fail "o texto não aparece na banda da linha que a grade diz"
fi

# 4. tela parada: duas capturas seguidas têm que ser idênticas **na grade** —
# o toast do "security warning" e a barra de abas são overlay, e o toast sai
# sozinho (10 s) em algum momento do teste; o que se quer provar é que a grade
# não repinta diferente a cada frame
sleep 0.3
take "$OUT_DIR/d1.png" || fail "captura 4a"
sleep 0.4
take "$OUT_DIR/d2.png" || fail "captura 4b"
ROWS=$(q '{"cmd":"state"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["rows"])')
GRID=$(python3 -c "print('0,%d,9999,%d' % (int($CHL * 0.5) + 1, int($ROWS * $CHL)))")
if python3 "$PIXEL" --diff "$OUT_DIR/d1.png" "$OUT_DIR/d2.png" --max 0 --region "$GRID" \
    >/dev/null 2>&1; then
    ok "tela parada não repinta diferente"
else
    fail "duas capturas da mesma grade diferem (repinta instável)"
fi

# 5. linha `r` na banda `r`: cada número que a grade diz está na linha `r` tem
# que ter pixel claro em [y0 + r*ch, y0 + (r+1)*ch). Sem shell aqui: o que
# entrega o conteúdo é o eco do pty (`\r` vira quebra de linha no eco).
q "$(python3 -c 'import json; print(json.dumps({"cmd": "write", "data": "".join("%d\r" % i for i in range(15))}))')" >/dev/null
sleep 0.8
take "$OUT_DIR/e.png" || fail "captura 5"
if python3 - "$SOCK" "$OUT_DIR/e.png" "$X0" "$Y0" "$CWL" "$CHL" <<'PY'
import json, socket, sys

sock, png, x0, y0, cw, ch = (
    sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]),
    float(sys.argv[5]), float(sys.argv[6]),
)


def q(**kw):
    c = socket.socket(socket.AF_UNIX)
    c.connect(sock)
    f = c.makefile("rwb")
    f.write(json.dumps(kw).encode() + b"\n")
    f.flush()
    r = json.loads(f.readline())
    c.close()
    return r


st = q(cmd="state")
grid = q(cmd="text", where="view", count=st["rows"])["lines"]

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

pb = GdkPixbuf.Pixbuf.new_from_file(png)
W, H, rs, nc = pb.get_width(), pb.get_height(), pb.get_rowstride(), pb.get_n_channels()
px = pb.get_pixels()

erros, vistos = [], 0
for r, ln in enumerate(grid):
    if not ln.strip():
        continue
    ya, yb = int(y0 + r * ch), min(int(y0 + (r + 1) * ch), H)
    xb = min(int(x0 + cw * len(ln)), W)
    if ya >= H:
        break
    claro = False
    for yy in range(ya, yb):
        for xx in range(int(x0), xb):
            o = yy * rs + xx * nc
            if px[o] > 90 and px[o + 1] > 90 and px[o + 2] > 90:
                claro = True
                break
        if claro:
            break
    vistos += 1
    if not claro:
        erros.append(f"linha {r} tem texto na grade e nenhum pixel na banda")
if vistos < 5:
    erros.append(f"poucas linhas conferidas ({vistos})")
print("; ".join(erros))
sys.exit(1 if erros else 0)
PY
then
    ok "linha r é pintada na banda r (espaçamento de 1 célula)"
else
    fail "linhas fora da banda (espaçamento duplo ou cursor deslocado)"
fi

echo
if [ "$failures" -eq 0 ]; then
    echo "render-check: tudo ok (capturas em $OUT_DIR)"
    exit 0
fi
echo "render-check: $failures falha(s)"
exit 1
