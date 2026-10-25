"""Estado do terminal: grade de células, cursor e parser VT.

Sem GTK aqui dentro — é o que deixa o parser testável por `--selftest` sem
abrir janela (e sem display). Quem desenha é `window.PyTermWindow`.
"""

from .palette import DEF_FG, DEF_BG, BOLD, UL, INV, PALETTE, DEC_SPECIAL


class Term:
    """Estado do terminal: grade, cursor, parser VT. Sem GTK aqui."""

    def __init__(self, cols=80, rows=24):
        self.cols, self.rows = cols, rows
        self.grid = [self._blank_row() for _ in range(rows)]
        self.alt_grid = None          # None = buffer principal
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
        self.charset_dec = False      # ESC ( 0 ativo?
        self.saved = None
        self.child_out = bytearray()  # respostas ao filho (DA, CPR...)
        self.title = "pyterm"
        self.state = "ground"
        self.csi = ""
        self.osc = ""
        # resposta a query de tamanho (o icat pergunta; aqui só o básico)
        self.respond_size = False

    # -- grade ------------------------------------------------------
    def _blank_row(self):
        return [[" ", DEF_FG, self.bg if False else DEF_BG, 0]
                for _ in range(self.cols)]

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
        """Recorta/preenche, sem re-quebrar (alt-screen)."""
        old_grid, old_rows = self.grid, self.rows
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
        self.row_wrapped = (self.row_wrapped[:rows] +
                            [False] * max(0, rows - len(self.row_wrapped)))
        self.top, self.bottom = 0, rows - 1
        self.cx = min(self.cx, cols - 1)
        self.cy = min(self.cy, rows - 1)
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
        return [" ", DEF_FG, DEF_BG, 0]

    def scroll_up(self):
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
        if self.wrap_pending:
            # a linha que encheu continua na de baixo (quebra mole): é o que
            # o reflow usa pra juntar de novo ao alargar
            self.row_wrapped[self.cy] = True
            self.cx = 0
            self.newline()
            self.wrap_pending = False
        if ch == "\n":
            self.newline()
            return
        if ch == "\r":
            self.cx, self.wrap_pending = 0, False
            return
        if ch == "\b":
            self.cx, self.wrap_pending = max(0, self.cx - 1), False
            return
        if ch == "\t":
            self.cx = min(self.cols - 1, ((self.cx // 8) + 1) * 8)
            return
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
        it = iter(params)
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
                    # truecolor: aproxima para a paleta (experimento mínimo)
                    if len(vals) == 3:
                        idx = self._nearest(*vals)
                        if p == 38:
                            self.fg = idx
                        else:
                            self.bg = idx

    @staticmethod
    def _nearest(r, g, b):
        best, bd = 0, 1e9
        for i, (pr, pg, pb) in enumerate(PALETTE):
            d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if d < bd:
                best, bd = i, d
        return best

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
            # bracketed paste (2004): fora de escopo (P7)

    def csi_dispatch(self, final, params, private):
        get = lambda i, d: (params[i] if i < len(params)
                            and params[i] is not None else d)

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
        elif final == "u":
            if self.saved:
                self.cx, self.cy = self.saved
        elif final in "hl":
            self.set_mode(params or [0], private, final == "h")
        elif final == "c" and not params and not private:
            self.child_out += b"\x1b[?62c"  # DA: VT102
        elif final == "n" and params == [6]:
            # DSR: informa posição do cursor
            self.child_out += f"\x1b[{self.cy + 1};{self.cx + 1}R".encode()
        # resto: ignorado silenciosamente (experimento mínimo)

    # -- parser -------------------------------------------------------
    def feed(self, text):
        for ch in text:
            o = ord(ch)
            st = self.state
            if st == "ground":
                if ch == "\x1b":
                    self.state = "esc"
                elif ch in "\x07":
                    pass  # BEL
                elif o < 0x20 or o == 0x7f:
                    if ch in "\n\r\b\t":
                        self.put(ch)
                    # resto dos C0 ignorado
                else:
                    self.put(ch)
            elif st == "esc":
                if ch == "[":
                    self.state, self.csi = "csi", ""
                elif ch == "]":
                    self.state, self.osc = "osc", ""
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
                if ch.isdigit() or ch in ";?: " or ch in "<=>":
                    self.csi += ch
                else:
                    body = self.csi
                    private = body.startswith("?")
                    body = body.lstrip("?")
                    parts = []
                    for tok in body.split(";") if body else []:
                        tok = tok.strip()
                        if tok == "" or tok.startswith((" ", "<", "=", ">")):
                            parts.append(None if tok == "" else 0)
                        else:
                            try:
                                parts.append(int(tok))
                            except ValueError:
                                parts.append(None)
                    nums = [p if p is not None else 0 for p in parts]
                    self.csi_dispatch(ch, nums, private)
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
            elif st == "charset":
                self.charset_dec = (ch == "0")
                self.state = "ground"

    def _osc_done(self):
        # só título (0/2); resto ignorado
        if self.osc[:2] in ("0;", "2;"):
            self.title = self.osc[2:]
        self.osc = ""
        self.state = "ground"

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
