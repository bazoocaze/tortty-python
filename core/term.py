"""Estado do terminal: grade de células, cursor e parser VT.

Sem GTK aqui dentro — é o que deixa o parser testável por `--selftest` sem
abrir janela (e sem display). Quem desenha é `window.BzmuxWindow`.
"""

from .graphics import Graphics
from .palette import (DEF_FG, DEF_BG, BOLD, UL, INV, rgb, DEC_SPECIAL,
                      PALETTE256, FG_DEFAULT, BG_DEFAULT)
import re

# Fast path do parser (P20): fim do texto imprimível e cache de escape -> cor.
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_ESC_CACHE = {}
_ESC_MAX = 1024

# Célula em branco compartilhada (P21): escrever SEMPRE substitui a célula na
# linha (`row[x] = [...]`), nunca muta in-place — é o que permite uma única
# lista servir de linha em branco inteira.
_BLANK_CELL = [" ", DEF_FG, DEF_BG, 0]

# Cache de parâmetros de CSI (P22): (corpo do CSI, final) -> (nums, prefixo).
# Independente do estado do terminal — só o parse dos números é cacheado.
_CSI_CACHE = {}
_CSI_MAX = 1024
# CSI curto inteiro no buffer: corpo sem intermediários, final em 0x40-0x7e.
# Tudo que não casar aqui (chunk partido, intermediário, dígito Unicode) cai
# no parser lento, que continua sendo o dono da gramática.
_CSI_RE = re.compile(r"\x1b\[([0-9;:?]*)([\x40-\x7e])")


def _csi_parse(body, final):
    """Corpo do CSI (sem ESC[ e sem final) -> (nums, prefixo privado)."""
    while body and " " <= body[-1] <= "/":
        body = body[:-1]               # intermediários: não usamos nenhum
    prefix = ""
    while body and body[0] in "?<=>":
        prefix += body[0]
        body = body[1:]
    parts = []
    for tok in body.split(";") if body else []:
        tok = tok.strip()
        if ":" in tok and final == "m":
            # subparâmetro: guarda a posição (o vazio conta)
            parts.append(tuple(int(v) if v else None for v in tok.split(":")))
        elif tok == "" or tok.startswith((" ", "<", "=", ">")):
            parts.append(None if tok == "" else 0)
        else:
            try:
                parts.append(int(tok))
            except ValueError:
                parts.append(None)
    return tuple(p if p is not None else 0 for p in parts), prefix


def _parse_truecolor(key):
    """`\x1b[38;2;r;g;bm`/`48;2;...` -> (True se fg, cor) ou False."""
    if not (key.startswith("\x1b[38;2;") or key.startswith("\x1b[48;2;")):
        return False
    p = key[2:-1].split(";")
    if len(p) != 5 or p[1] != "2":
        return False
    try:
        r, g, b = int(p[2]), int(p[3]), int(p[4])
    except ValueError:
        return False
    if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
        return False
    return (p[0] == "38", rgb(r, g, b))


class Term:
    """Estado do terminal: grade, cursor, parser VT. Sem GTK aqui."""

    def __init__(self, cols=80, rows=24):
        self.cols, self.rows = cols, rows
        self.grid = [self._blank_row() for _ in range(rows)]
        self.alt_grid = None          # None = buffer principal
        self.scrolled = 0             # linhas que saíram pelo topo (diagnóstico)
        self.scrollback = []
        # reflow (P3): row_wrapped[i] = "esta linha continua na de baixo"
        # (quebra mole, não '\n'). É o que permite re-quebrar no resize em vez
        # de recortar. sb_wrapped é o mesmo, paralelo ao scrollback.
        self.row_wrapped = [False] * rows
        self.sb_wrapped = []
        self.alt_wrapped = None
        self.cx, self.cy = 0, 0
        self.fg, self.bg, self.flags = DEF_FG, DEF_BG, 0
        self.top, self.bottom = 0, rows - 1   # scroll region
        self.wrap_pending = False
        self.cursor_visible = True
        self.app_cursor = False       # DECCKM (?1): setas em modo aplicação
        self.mouse_mode = 0           # ?1000=1 ?1002=2 ?1003=3 (0 = off)
        self.mouse_sgr = False        # ?1006: coordenadas SGR
        self.focus_report = False     # ?1004: avisar foco in/out
        self.bracketed_paste = False  # ?2004: colar com marcadores
        # protocolo de teclado do kitty (P5): flags atuais + pilha para
        # push/pop (CSI > flags u / CSI < n u / CSI = flags ; modo u)
        self.kbd_flags = 0
        self.kbd_stack = []
        self.cell_size = (10, 19)     # px por célula (o window ajusta)
        self.charset_dec = False      # ESC ( 0 ativo?
        self.saved = None
        self.child_out = bytearray()  # respostas ao filho (DA, CPR...)
        self.graphics = Graphics()    # protocolo de imagens do kitty (P6)
        self.apc = ""
        self.title = "bzmux"
        self.state = "ground"
        self.csi = ""
        self.osc = ""
        self.apc = ""
        # resposta a query de tamanho (o icat pergunta; aqui só o básico)
        self.respond_size = False

    # -- grade ------------------------------------------------------
    def _blank_row(self):
        return [_BLANK_CELL] * self.cols

    def blank_cell(self):
        # áreas apagadas herdam o bg corrente (bce, como terminal real)
        return [" ", DEF_FG, self.bg, 0]

    def reset(self):
        """RIS (ESC c): limpa tudo, mantém o tamanho."""
        cols, rows = self.cols, self.rows
        self.__init__(cols, rows)

    def resize(self, cols, rows):
        """Redimensiona: re-quebra (reflow) no buffer principal.

        Alt-screen não tem reflow — quem está em tela cheia (mc, vim) se
        redesenha inteiro no SIGWINCH, e re-quebrar por cima do que ele
        escreveu só atrapalharia.
        """
        if (cols, rows) == (self.cols, self.rows):
            return
        if self.alt_grid is None:
            self._reflow(cols, rows)
        else:
            self._resize_crop(cols, rows)

    def _resize_crop(self, cols, rows):
        """Alt-screen: recorta a tela e re-quebra o buffer principal salvo.

        O `alt_grid` (o buffer principal guardado enquanto o app está em tela
        cheia) TAMBÉM tem que acompanhar o tamanho novo — senão, ao sair de
        `mc`/`vim` depois de um resize, a grade volta com a largura antiga e a
        primeira `EL` estoura (`IndexError` em `erase_line`), o que derruba o
        watch do pty e congela o terminal.
        """
        old_grid, old_cols, old_rows = self.grid, self.cols, self.rows
        old_wrapped, old_cx, old_cy = self.row_wrapped, self.cx, self.cy
        if self.alt_grid is not None:
            self.grid, self.row_wrapped = self.alt_grid, self.alt_wrapped
            self.cols, self.rows = old_cols, old_rows
            self.cx, self.cy = self.saved or (0, 0)
            self._reflow(cols, rows)          # re-quebra o principal salvo
            self.alt_grid, self.alt_wrapped = self.grid, self.row_wrapped
            self.saved = (self.cx, self.cy)
        self.cols, self.rows = cols, rows
        new = []
        for y in range(rows):
            if y < old_rows:
                row = old_grid[y][:cols]
                if len(row) < cols:
                    row = row + [self._blank_cell_raw()
                                 for _ in range(cols - len(row))]
                new.append(row)
            else:
                new.append([self._blank_cell_raw() for _ in range(cols)])
        self.grid = new
        self.row_wrapped = (old_wrapped[:rows] +
                            [False] * max(0, rows - len(old_wrapped)))
        self.top, self.bottom = 0, rows - 1
        self.cx = min(old_cx, cols - 1)
        self.cy = min(old_cy, rows - 1)
        self.wrap_pending = False

    def _reflow(self, cols, rows):
        """Junta as linhas lógicas (scrollback + grade), corta na largura nova
        e recoloca o cursor na célula equivalente.

        Linha lógica = sequência de linhas de tela ligadas por quebra mole. Ao
        estreitar, uma linha longa vira várias; ao alargar, várias voltam a
        ser uma. O que sobra em cima vai pro scrollback, o que falta embaixo é
        preenchido — e o cursor continua sobre o mesmo caractere.
        """
        old_cols = self.cols
        total = len(self.scrollback) + len(self.grid)
        cur_abs = len(self.scrollback) + self.cy
        cur_off = None
        lines, row_info = [], []
        cur = None
        off = 0
        for i in range(total):
            if i < len(self.scrollback):
                row, wrapped = self.scrollback[i], self.sb_wrapped[i]
            else:
                row, wrapped = self.grid[i - len(self.scrollback)], \
                    self.row_wrapped[i - len(self.scrollback)]
            if cur is None:
                cur = []
                lines.append(cur)
                off = 0
            row_info.append((len(lines) - 1, off))
            cur.extend(row)
            off += len(row)
            if not wrapped:
                cur = None
        if cur is not None and not cur:
            lines.pop()
        if cur_abs < len(row_info):
            line_idx, off0 = row_info[cur_abs]
            cur_off = off0 + min(self.cx, old_cols - 1)
        else:
            line_idx, cur_off = None, None

        # Corta o espaço em branco à direita de cada linha lógica. Sem isso,
        # uma linha de 3 caracteres numa tela de 68 colunas re-quebra em DUAS
        # linhas (a segunda só de espaços) e o conteúdo aparece intercalado
        # com linhas vazias ao estreitar. Só corta célula vazia de verdade
        # (espaço com bg default) — fundo colorido de barra/status fica.
        for li, line in enumerate(lines):
            real = len(line)
            while real and line[real - 1][0] == " " and line[real - 1][2] == DEF_BG:
                real -= 1
            if li == line_idx and cur_off is not None and cur_off > real:
                real = cur_off          # não perde a posição do cursor
            del line[real:]

        new_rows, new_wrap = [], []
        cur_new = None
        blank = self._blank_cell_raw
        for li, line in enumerate(lines):
            chunks = ([line[k:k + cols] for k in range(0, len(line), cols)]
                      if line else [[]])
            for ci, chunk in enumerate(chunks):
                if len(chunk) < cols:
                    chunk = chunk + [blank() for _ in range(cols - len(chunk))]
                new_rows.append(chunk)
                new_wrap.append(ci < len(chunks) - 1)
                # só o primeiro chunk que contém o cursor ganha (sem isso o
                # último chunk da linha sobrescrevia e o cursor pulava)
                if (li == line_idx and cur_off is not None and cur_new is None
                        and (cur_off < (ci + 1) * cols
                             or ci == len(chunks) - 1)):
                    cur_new = (len(new_rows) - 1,
                               max(0, min(cols - 1, cur_off - ci * cols)))
        # o que está DEPOIS do cursor é área em branco: não vale empurrar
        # linha vazia pro scrollback só porque a tela alargou
        if cur_new is not None:
            while len(new_rows) - 1 > cur_new[0]:
                last = new_rows[-1]
                if any(c[0] != " " for c in last):
                    break
                new_rows.pop()
                new_wrap.pop()

        split = max(0, len(new_rows) - rows)
        self.scrollback = new_rows[:split][-1000:]
        self.sb_wrapped = new_wrap[:split][-1000:]
        self.grid = new_rows[split:]
        self.row_wrapped = new_wrap[split:]
        while len(self.grid) < rows:
            self.grid.append([blank() for _ in range(cols)])
            self.row_wrapped.append(False)

        # As colocações de imagem vivem em LINHAS DE TELA, e o reflow acabou
        # de mudar quantas linhas existem acima da grade: quem ficou fora do
        # histórico virou inalcançável (nem com o wheel) e nunca mais seria
        # desenhado — melhor descartar do que guardar lixo. As que continuam
        # na faixa ficam onde estão (imagem não acompanha reflow linha a linha,
        # como no kitty).
        self.graphics.drop_above(-len(self.scrollback))

        self.cols, self.rows = cols, rows
        self.top, self.bottom = 0, rows - 1
        self.wrap_pending = False
        if cur_new is not None:
            self.cy = max(0, min(rows - 1, cur_new[0] - split))
            self.cx = max(0, min(cols - 1, cur_new[1]))
        else:
            self.cx = min(self.cx, cols - 1)
            self.cy = min(self.cy, rows - 1)

    def _blank_cell_raw(self):
        return _BLANK_CELL

    def scroll_up(self):
        self.scrolled += 1
        # rolagem de tela cheia: a linha que sai pelo topo vai pro histórico,
        # então a imagem que estava nela continua existindo (com linha
        # negativa) e reaparece quando a visão sobe no scrollback
        self.graphics.scroll(self.top, self.bottom,
                            -1001 if self.top == 0 else None)
        if self.alt_grid is not None:
            self.grid.pop(self.top)
            self.grid.insert(self.bottom, self._blank_row())
            self.row_wrapped.pop(self.top)
            self.row_wrapped.insert(self.bottom, False)
        else:
            if self.top == 0 and self.bottom == self.rows - 1:
                self.scrollback.append(self.grid.pop(0))
                self.sb_wrapped.append(self.row_wrapped.pop(0))
                if len(self.scrollback) > 1000:
                    self.scrollback.pop(0)
                    self.sb_wrapped.pop(0)
                    # o que estava preso nessa linha morreu de vez
                    self.graphics.drop_above(-len(self.scrollback))
                self.grid.append(self._blank_row())
                self.row_wrapped.append(False)
            else:
                self.grid.pop(self.top)
                self.grid.insert(self.bottom, self._blank_row())
                self.row_wrapped.pop(self.top)
                self.row_wrapped.insert(self.bottom, False)

    def newline(self):
        if self.cy == self.bottom:
            self.scroll_up()
        else:
            self.cy = min(self.cy + 1, self.rows - 1)

    def put(self, ch):
        # Controle vem ANTES da quebra pendente: um `\r\n` depois de uma linha
        # que encheu a largura avançava DUAS linhas (a quebra pendente + o LF),
        # e app que preenche a linha inteira (pi, Ink) caía em layout dobrado
        # e tela rolando sem parar (P15).
        if ch == "\r":
            self.cx, self.wrap_pending = 0, False
            return
        if ch == "\n":
            self.wrap_pending = False
            self.newline()
            return
        if ch == "\b":
            self.cx, self.wrap_pending = max(0, self.cx - 1), False
            return
        if ch == "\t":
            self.wrap_pending = False
            self.cx = min(self.cols - 1, ((self.cx // 8) + 1) * 8)
            return
        if self.wrap_pending:
            # a linha que encheu continua na de baixo (quebra mole): é o que
            # o reflow usa pra juntar de novo ao alargar
            self.row_wrapped[self.cy] = True
            self.cx = 0
            self.newline()
            self.wrap_pending = False
        if self.charset_dec:
            ch = DEC_SPECIAL.get(ch, ch)
        self.grid[self.cy][self.cx] = [ch, self.fg, self.bg, self.flags]
        if self.cx == self.cols - 1:
            self.wrap_pending = True
        else:
            self.cx += 1

    # -- comandos ----------------------------------------------------
    def cursor_to(self, r, c):
        self.cy = max(0, min(self.rows - 1, r))
        self.cx = max(0, min(self.cols - 1, c))
        self.wrap_pending = False

    def erase_display(self, n):
        if n == 2 or n == 3:
            for y in range(self.rows):
                self.grid[y] = [self.blank_cell() for _ in range(self.cols)]
            if n == 3:
                self.scrollback.clear()
                self.sb_wrapped.clear()
                self.graphics.clear()
            self.cursor_to(0, 0)
        elif n == 1:
            for x in range(self.cx + 1):
                self.grid[self.cy][x] = self.blank_cell()
            for y in range(self.cy):
                self.grid[y] = [self.blank_cell() for _ in range(self.cols)]
        else:  # 0
            for x in range(self.cx, self.cols):
                self.grid[self.cy][x] = self.blank_cell()
            for y in range(self.cy + 1, self.rows):
                self.grid[y] = [self.blank_cell() for _ in range(self.cols)]

    def erase_line(self, n):
        if n == 2:
            self.grid[self.cy] = [self.blank_cell() for _ in range(self.cols)]
        elif n == 1:
            for x in range(self.cx + 1):
                self.grid[self.cy][x] = self.blank_cell()
        else:
            for x in range(self.cx, self.cols):
                self.grid[self.cy][x] = self.blank_cell()

    def insert_lines(self, n):
        for _ in range(n):
            self.grid.pop(self.bottom)
            self.grid.insert(self.cy, [self.blank_cell()
                                       for _ in range(self.cols)])
            self.row_wrapped.pop(self.bottom)
            self.row_wrapped.insert(self.cy, False)

    def delete_lines(self, n):
        for _ in range(n):
            self.grid.pop(self.cy)
            self.grid.insert(self.bottom, [self.blank_cell()
                                           for _ in range(self.cols)])
            self.row_wrapped.pop(self.cy)
            self.row_wrapped.insert(self.bottom, False)

    def sgr(self, params):
        # subparâmetros com ':' (38:2::r:g:b) chegam como tupla: acha a forma
        # canônica com ';' antes de interpretar (só aloca `flat` se houver)
        flat = params
        for p in params:
            if isinstance(p, tuple):
                flat = []
                for q in params:
                    if isinstance(q, tuple):
                        flat.extend(self._sgr_subparams(q))
                    else:
                        flat.append(q)
                break
        it = iter(flat)
        for p in it:
            if p == 0:
                self.fg, self.bg, self.flags = DEF_FG, DEF_BG, 0
            elif p == 1:
                self.flags |= BOLD
            elif p == 4:
                self.flags |= UL
            elif p == 7:
                self.flags |= INV
            elif p == 22:
                self.flags &= ~BOLD
            elif p == 24:
                self.flags &= ~UL
            elif p == 27:
                self.flags &= ~INV
            elif 30 <= p <= 37:
                self.fg = p - 30
            elif p == 39:
                self.fg = DEF_FG
            elif 40 <= p <= 47:
                self.bg = p - 40
            elif p == 49:
                self.bg = DEF_BG
            elif 90 <= p <= 97:
                self.fg = p - 90 + 8
            elif 100 <= p <= 107:
                self.bg = p - 100 + 8
            elif p in (38, 48):
                try:
                    mode = next(it)
                except StopIteration:
                    break
                if mode == 5:
                    try:
                        c = next(it)
                    except StopIteration:
                        break
                    if 0 <= c <= 255:
                        if p == 38:
                            self.fg = c
                        else:
                            self.bg = c
                elif mode == 2:
                    vals = []
                    for _ in range(3):
                        try:
                            vals.append(next(it))
                        except StopIteration:
                            break
                    # truecolor de verdade (P4): o RGB fica na célula, sem
                    # passar por tabela de cores alocadas. Antes disto o
                    # `38;2;r;g;b` era aproximado pro vizinho mais próximo da
                    # paleta 256 — vim com termguicolors, bat e gradiente em
                    # texto caíam todos em faixas chapadas.
                    if len(vals) == 3:
                        c = rgb(min(255, max(0, vals[0])),
                                min(255, max(0, vals[1])),
                                min(255, max(0, vals[2])))
                        if p == 38:
                            self.fg = c
                        else:
                            self.bg = c

    @staticmethod
    def _sgr_subparams(sub):
        """`38:2::r:g:b` (SGR com ':') -> forma canônica com ';'.

        O campo vazio é o "espaço de cor" omitido (`38:2::1:2:3` ==
        `38:2:0:1:2:3` == `38;2;1;2;3`), então o descarte só vale quando a
        posição é de espaço de cor — filtrar todos os vazios mudaria o
        significado de `48:5::196`.
        """
        vals = list(sub)
        if len(vals) >= 5 and vals[1] == 2:
            last3 = [0 if v is None else v for v in vals[-3:]]
            return [vals[0], 2] + last3
        return [0 if v is None else v for v in vals]

    def set_mode(self, params, private, on):
        for p in params:
            if private and p == 25:
                self.cursor_visible = on
            elif private and p == 1:
                # DECCKM: com o modo ligado as setas viram \EOA..\EOD
                # (é o que o terminfo de xterm chama de "aplicação"; mc,
                # vim e less ligam isso ao entrar em tela cheia)
                self.app_cursor = on
            elif p in (47, 1047, 1049):
                if on and self.alt_grid is None:
                    self.alt_grid = self.grid
                    self.alt_wrapped = self.row_wrapped
                    self.grid = [self._blank_row() for _ in range(self.rows)]
                    self.row_wrapped = [False] * self.rows
                    self.saved = (self.cx, self.cy)
                    self.cursor_to(0, 0)
                    if p == 1049:
                        self.scrollback.clear()
                        self.sb_wrapped.clear()
                elif not on and self.alt_grid is not None:
                    self.grid = self.alt_grid
                    self.alt_grid = None
                    if len(self.alt_wrapped) == self.rows:
                        self.row_wrapped = self.alt_wrapped
                    self.alt_wrapped = None
                    if self.grid and len(self.grid[0]) != self.cols:
                        # tamanho mudou com a tela cheia ligada: re-quebra
                        # em vez de deixar linha curta na grade
                        self._reflow(self.cols, self.rows)
                    if self.saved:
                        self.cx, self.cy = self.saved
                    self.top, self.bottom = 0, self.rows - 1
            elif p == 1048:
                if on:
                    self.saved = (self.cx, self.cy)
                elif self.saved:
                    self.cx, self.cy = self.saved
            elif private and p in (1000, 1002, 1003):
                # modos de mouse: 1 = só cliques, 2 = clique + arrasto,
                # 3 = qualquer movimento. Desligar qualquer um desliga o
                # report (é o que o xterm faz).
                self.mouse_mode = {1000: 1, 1002: 2, 1003: 3}[p] if on else 0
            elif private and p == 1006:
                self.mouse_sgr = on     # coordenadas SGR (>223 e release)
            elif private and p == 1004:
                self.focus_report = on  # CSI I / CSI O no foco
            elif private and p in (1005, 1015):
                # UTF-8 / urxvt: o SGR (1006) cobre; não vale implementar
                # três codificações de coordenada para o experimento
                pass
            elif private and p == 2004:
                # bracketed paste: o app pede pra saber que o texto colado não
                # foi digitado. Sem isso, colar 3 linhas no shell executa 3.
                self.bracketed_paste = on

    def csi_dispatch(self, final, params, prefix=""):
        get = lambda i, d: (params[i] if i < len(params)
                            and params[i] is not None else d)
        private = prefix == "?"

        if final == "m":
            self.sgr(params or [0])
        elif final in "ABCDEFG":
            k = get(0, 1) or 1
            if final in "AE":
                self.cursor_to(self.cy - k if final == "A" else self.cy + k,
                               self.cx)
            elif final in "CD":
                self.cursor_to(self.cy,
                               self.cx + k if final == "C" else self.cx - k)
            elif final == "B":
                self.cursor_to(self.cy + k, self.cx)
            elif final == "F":
                self.cursor_to(self.cy - k, 0)
            elif final == "G":
                self.cursor_to(self.cy, k - 1)
        elif final in "Hf":
            self.cursor_to(get(0, 1) - 1, get(1, 1) - 1)
        elif final == "d":
            self.cursor_to(get(0, 1) - 1, self.cx)
        elif final == "J":
            self.erase_display(get(0, 0))
        elif final == "K":
            self.erase_line(get(0, 0))
        elif final == "L":
            self.insert_lines(get(0, 1) or 1)
        elif final == "M":
            self.delete_lines(get(0, 1) or 1)
        elif final == "@":
            k = get(0, 1) or 1
            row = self.grid[self.cy]
            row[self.cx:self.cx] = [self.blank_cell()] * k
            del row[self.cols:]
        elif final == "P":
            k = get(0, 1) or 1
            row = self.grid[self.cy]
            del row[self.cx:self.cx + k]
            row.extend([self.blank_cell()] * k)
        elif final == "X":
            k = get(0, 1) or 1
            for x in range(self.cx, min(self.cols, self.cx + k)):
                self.grid[self.cy][x] = self.blank_cell()
        elif final == "r":
            t, b = get(0, 1) - 1, get(1, self.rows) - 1
            if 0 <= t < b < self.rows:
                self.top, self.bottom = t, b
                self.cursor_to(0, 0)
        elif final == "s":
            self.saved = (self.cx, self.cy)
        elif final == "u" and prefix:
            self._kbd_protocol(params, prefix)
        elif final == "u":
            if self.saved:
                self.cx, self.cy = self.saved
        elif final in "hl":
            self.set_mode(params or [0], private, final == "h")
        elif final == "c" and not params and not private:
            self.child_out += b"\x1b[?62c"  # DA: VT102
        elif final == "t" and params:
            # 16 = tamanho da célula em px; 18 = área de texto em chars. Apps
            # de TUI (pi, neovim) perguntam para calcular layout em pixels e
            # ficam esperando a resposta; sem ela o startup arrasta.
            if params[0] == 16:
                cw, ch = self.cell_size
                self.child_out += f"\x1b[6;{ch};{cw}t".encode()
            elif params[0] == 18:
                self.child_out += f"\x1b[8;{self.rows};{self.cols}t".encode()
        elif final == "n" and params == (6,):
            # DSR: informa posição do cursor
            self.child_out += f"\x1b[{self.cy + 1};{self.cx + 1}R".encode()
        # resto: ignorado silenciosamente (experimento mínimo)

    # -- parser -------------------------------------------------------
    def _sgr_fast(self, text, i):
        """`CSI 38;2;r;g;b m` aplicado direto; devolve o índice seguinte ou None."""
        end = text.find("m", i + 2)
        if end < 0 or end - i > 24:
            return None
        key = text[i:end + 1]
        v = _ESC_CACHE.get(key)
        if v is None:
            v = _parse_truecolor(key)
            if len(_ESC_CACHE) > _ESC_MAX:
                _ESC_CACHE.clear()
            _ESC_CACHE[key] = v
        if v is False:
            return None
        is_fg, color = v
        if is_fg:
            self.fg = color
        else:
            self.bg = color
        return end + 1

    def _put_run(self, run):
        """Trecho imprimível de uma vez, com a mesma quebra mole do put."""
        fg, bg, fl = self.fg, self.bg, self.flags
        i, n = 0, len(run)
        while i < n:
            if self.wrap_pending:
                self.row_wrapped[self.cy] = True
                self.cx = 0
                self.newline()
                self.wrap_pending = False
            cx = self.cx
            avail = self.cols - cx
            k = n - i
            row = self.grid[self.cy]
            if k >= avail:                 # enche até a última coluna: quebra mole
                row[cx:] = [[c, fg, bg, fl] for c in run[i:i + avail]]
                self.cx = self.cols - 1
                self.wrap_pending = True
                i += avail
            else:
                row[cx:cx + k] = [[c, fg, bg, fl] for c in run[i:]]
                self.cx = cx + k
                i = n

    def _csi_fast(self, text, i):
        """CSI completo no buffer, resolvido pelo cache de parâmetros."""
        m = _CSI_RE.match(text, i)
        if m is None:
            return None
        key = (m.group(1), m.group(2))
        parsed = _CSI_CACHE.get(key)
        if parsed is None:
            parsed = _csi_parse(key[0], key[1])
            if len(_CSI_CACHE) > _CSI_MAX:
                _CSI_CACHE.clear()
            _CSI_CACHE[key] = parsed
        self.csi_dispatch(key[1], parsed[0], parsed[1])
        return m.end()

    def feed(self, text):
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            st = self.state
            if st == "ground":
                if ch == "\x1b":
                    # P20/P22: SGR truecolor aplica direto; qualquer outro CSI
                    # curto resolve pelo cache; o resto cai no parser de sempre
                    j = self._sgr_fast(text, i)
                    if j is None:
                        j = self._csi_fast(text, i)
                    if j is not None:
                        i = j
                        continue
                    self.state = "esc"
                elif ch in "\x07":
                    pass  # BEL
                elif ch < " " or ch == "\x7f":
                    if ch in "\n\r\b\t":
                        self.put(ch)
                    # resto dos C0 ignorado
                elif not self.charset_dec:
                    # P20: texto imprimível de uma vez (slice na linha)
                    m = _CTRL.search(text, i)
                    j = m.start() if m else n
                    self._put_run(text[i:j])
                    i = j
                    continue
                else:
                    self.put(ch)
            elif st == "esc":
                if ch == "[":
                    self.state, self.csi = "csi", ""
                elif ch == "]":
                    self.state, self.osc = "osc", ""
                elif ch == "_":
                    self.state, self.apc = "apc", ""
                elif ch == "(":
                    self.state = "charset"
                elif ch == "M":
                    self.cursor_to(self.cy - 1, self.cx)  # RI
                    self.state = "ground"
                elif ch == "7":
                    self.saved = (self.cx, self.cy)
                    self.state = "ground"
                elif ch == "8":
                    if self.saved:
                        self.cx, self.cy = self.saved
                    self.state = "ground"
                elif ch in "c":
                    self.reset()  # RIS
                elif ch in "DEH":
                    self.state = "ground"  # IND/NEL/HTS: só volta
                elif ch in "=>":
                    self.state = "ground"  # teclado numérico
                else:
                    self.state = "ground"
            elif st == "csi":
                # ECMA-48: params 0x30-0x3f, DEPOIS intermediários 0x20-0x2f,
                # e só então o byte final. Sem aceitar os intermediários, um
                # `CSI * x` (DECSACE, que o icat manda) terminava no `*` e o
                # `x` caía no ground — imprimia um "x" solto na tela.
                if (ch.isdigit() or ch in ";?: " or ch in "<=>" or
                        " " <= ch <= "/"):
                    self.csi += ch
                else:
                    key = (self.csi, ch)
                    parsed = _CSI_CACHE.get(key)
                    if parsed is None:
                        parsed = _csi_parse(self.csi, ch)
                        if len(_CSI_CACHE) > _CSI_MAX:
                            _CSI_CACHE.clear()
                        _CSI_CACHE[key] = parsed
                    self.csi_dispatch(ch, parsed[0], parsed[1])
                    self.state = "ground"
            elif st == "osc":
                if ch == "\x07":
                    self._osc_done()
                elif ch == "\x1b":
                    self.state = "osc-esc"
                else:
                    self.osc += ch
            elif st == "osc-esc":
                if ch == "\\":
                    self._osc_done()
                else:  # ESC sozinho: volta a interpretar
                    self.state = "ground"
                    self.feed(ch)
            elif st == "apc":
                if ch == "\x07":
                    self._apc_done()
                elif ch == "\x1b":
                    self.state = "apc-esc"
                else:
                    self.apc += ch
            elif st == "apc-esc":
                if ch == "\\":
                    self._apc_done()
                else:
                    self.state = "ground"
            elif st == "charset":
                self.charset_dec = (ch == "0")
                self.state = "ground"
            i += 1

    def _apc_done(self):
        body, self.apc = self.apc, ""
        self.state = "ground"
        cw, ch = self.cell_size
        resp, used, move = self.graphics.handle(body, (self.cx, self.cy),
                                                (cw, ch))
        for r in resp:
            self.child_out += b"\x1b_" + r.encode() + b"\x1b\\"
        if move and used:
            for _ in range(used):
                self.newline()

    def _osc_done(self):
        o = self.osc
        self.osc = ""
        self.state = "ground"
        if o[:2] in ("0;", "2;"):
            self.title = o[2:]
        elif o in ("10;?", "11;?"):
            # cor padrão de frente/fundo (X11: 4 dígitos por componente)
            r, g, b = FG_DEFAULT if o[0] == "1" and o[1] == "0" else BG_DEFAULT
            self.child_out += (
                f"\x1b]{o[:2]};rgb:{r*257:04x}/{g*257:04x}/{b*257:04x}\x1b\\"
                .encode())
        elif o.startswith("4;"):
            # entrada da paleta: OSC 4 ; índice ; ? (pode vir em pares)
            parts = o.split(";")[1:]
            out = ""
            for i in range(0, len(parts) - 1, 2):
                if not parts[i + 1].startswith("?"):
                    continue
                try:
                    n = int(parts[i])
                except ValueError:
                    continue
                if 0 <= n < len(PALETTE256):
                    r, g, b = PALETTE256[n]
                    out += f"\x1b]4;{n};rgb:{r*257:04x}/{g*257:04x}/{b*257:04x}\x1b\\"
            self.child_out += out.encode()

    def _kbd_protocol(self, params, prefix):
        """CSI > flags u (push) / CSI < n u (pop) / CSI = flags ; modo u (set)
        / CSI ? u (query). Modo: 1 = substitui, 2 = acrescenta, 3 = remove."""
        if prefix == "?":
            self.child_out += f"\x1b[?{self.kbd_flags}u".encode()
        elif prefix == ">":
            self.kbd_stack.append(self.kbd_flags)
            self.kbd_flags = params[0] if params else 0
        elif prefix == "<":
            for _ in range(params[0] if params else 1):
                self.kbd_flags = self.kbd_stack.pop() if self.kbd_stack else 0
        elif prefix == "=":
            flags = params[0] if params else 0
            mode = params[1] if len(params) > 1 else 1
            if mode == 1:
                self.kbd_flags = flags
            elif mode == 2:
                self.kbd_flags |= flags
            elif mode == 3:
                self.kbd_flags &= ~flags

    def row_text(self, y):
        return "".join(c[0] for c in self.grid[y])

    def visible_rows(self, off=0):
        """As `rows` linhas que estão na tela, com `off` linhas de histórico.

        `off`=0 é o vivo (a grade). `off`>0 puxa as últimas `off` linhas do
        scrollback pra cima da grade — a tela é uma janela que desliza, sem
        mexer no cursor nem no que o app escreveu.
        """
        off = max(0, min(off, len(self.scrollback)))
        if not off:
            return self.grid
        return self.scrollback[-off:] + self.grid[:self.rows - off]

    # -- texto (cópia) ------------------------------------------------
    def paste_payload(self, text):
        """O que mandar pro filho quando o usuário cola `text`.

        Com `?2004` ligado, o texto vai entre `ESC[200~` e `ESC[201~`: o app
        (readline, vim, python) sabe que é cola e não trata `\n` como Enter.
        A política mora aqui (e não na janela) pra ser testável sem display.
        """
        if self.bracketed_paste:
            return "\x1b[200~" + text + "\x1b[201~"
        return text

    def selection_text(self, start, end, rows=None):
        """Texto entre duas células (row, col), 0-based, pontas inclusivas.

        Ordem invertida (arrastar de baixo pra cima) é normalizada. Espaço à
        direita de cada linha sai fora — é o que todo terminal faz ao copiar.
        `rows` permite copiar da visão de histórico em vez da grade viva.
        """
        if rows is None:
            rows = self.grid
        (r1, c1), (r2, c2) = start, end
        if (r1, c1) > (r2, c2):
            (r1, c1), (r2, c2) = (r2, c2), (r1, c1)
        last = len(rows) - 1
        r1 = max(0, min(last, r1))
        r2 = max(0, min(last, r2))
        out = []
        for y in range(r1, r2 + 1):
            a = c1 if y == r1 else 0
            b = (c2 + 1) if y == r2 else self.cols
            row = rows[y]
            out.append("".join(c[0] for c in row[a:b]).rstrip())
        return "\n".join(out)

    def all_text(self, rows=None):
        """A viewport inteira (Ctrl+Shift+C sem seleção)."""
        rows = self.grid if rows is None else rows
        lines = ["".join(c[0] for c in row).rstrip() for row in rows]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines) + ("\n" if lines else "")
