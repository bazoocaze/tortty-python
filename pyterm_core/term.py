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
        self.cx, self.cy = 0, 0
        self.fg, self.bg, self.flags = DEF_FG, DEF_BG, 0
        self.top, self.bottom = 0, rows - 1   # scroll region
        self.wrap_pending = False
        self.cursor_visible = True
        self.app_cursor = False       # DECCKM (?1): setas em modo aplicação
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
        """Redimensiona preservando o conteúdo (recorta/preenche)."""
        old_grid, old_cols, old_rows = self.grid, self.cols, self.rows
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
        self.top, self.bottom = 0, rows - 1
        self.cx = min(self.cx, cols - 1)
        self.cy = min(self.cy, rows - 1)
        self.wrap_pending = False

    def _blank_cell_raw(self):
        return [" ", DEF_FG, DEF_BG, 0]

    def scroll_up(self):
        if self.alt_grid is not None:
            self.grid.pop(self.top)
            self.grid.insert(self.bottom, self._blank_row())
        else:
            if self.top == 0 and self.bottom == self.rows - 1:
                self.scrollback.append(self.grid.pop(0))
                if len(self.scrollback) > 1000:
                    self.scrollback.pop(0)
                self.grid.append(self._blank_row())
            else:
                self.grid.pop(self.top)
                self.grid.insert(self.bottom, self._blank_row())

    def newline(self):
        if self.cy == self.bottom:
            self.scroll_up()
        else:
            self.cy = min(self.cy + 1, self.rows - 1)

    def put(self, ch):
        if self.wrap_pending:
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

    def delete_lines(self, n):
        for _ in range(n):
            self.grid.pop(self.cy)
            self.grid.insert(self.bottom, [self.blank_cell()
                                           for _ in range(self.cols)])

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
                    self.grid = [self._blank_row() for _ in range(self.rows)]
                    self.saved = (self.cx, self.cy)
                    self.cursor_to(0, 0)
                    if p == 1049:
                        self.scrollback.clear()
                elif not on and self.alt_grid is not None:
                    self.grid = self.alt_grid
                    self.alt_grid = None
                    if self.saved:
                        self.cx, self.cy = self.saved
                    self.top, self.bottom = 0, self.rows - 1
            elif p == 1048:
                if on:
                    self.saved = (self.cx, self.cy)
                elif self.saved:
                    self.cx, self.cy = self.saved
            # mouse (1000/1002/1006), bracketed paste (2004),
            # foco (1004): rastreados e ignorados — sem mouse aqui

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
