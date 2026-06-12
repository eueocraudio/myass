"""Gerador de PDF mínimo em stdlib pura (sem fpdf/reportlab).

Suficiente para um relatório textual multi-página rico: título, cabeçalhos,
linhas com quebra automática e espaçadores. Fonte base Helvetica (WinAnsi).
Mantém o BOT com dependência zero para o PDF (alinhado ao "sem stacks externas").
"""

import textwrap

_A4 = (595, 842)  # pt
_MARGIN = 50
_LEADING = 14


def _esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class Pdf:
    def __init__(self):
        self.W, self.H = _A4
        self._pages = []          # cada página = lista de (x, y, size, texto)
        self._cur = []
        self._y = self.H - _MARGIN

    # ---- layout --------------------------------------------------------
    def _newpage(self):
        self._pages.append(self._cur)
        self._cur = []
        self._y = self.H - _MARGIN

    def _emit(self, text, size):
        if self._y - _LEADING < _MARGIN:
            self._newpage()
        self._cur.append((_MARGIN, self._y, size, _esc(text)))
        self._y -= _LEADING

    def title(self, s):
        self._emit(s, 20)
        self._y -= 6

    def heading(self, s, size=14):
        self._y -= 6
        self._emit(s, size)

    def line(self, s, size=10):
        s = "" if s is None else str(s)
        width = max(10, int((self.W - 2 * _MARGIN) / (size * 0.5)))
        for chunk in (textwrap.wrap(s, width=width) or [""]):
            self._emit(chunk, size)

    def spacer(self, n=1):
        self._y -= n * _LEADING

    def rule(self):
        self.line("-" * 90, 8)

    # ---- serialização --------------------------------------------------
    def save(self, path):
        with open(path, "wb") as f:
            f.write(self._build())

    def _build(self):
        if self._cur:
            self._newpage()
        pages = self._pages or [[]]

        objs = {}
        objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"

        page_obj_nums, next_obj = [], 4
        for page in pages:
            content = []
            for (x, y, size, text) in page:
                content.append(f"BT /F1 {size} Tf {x} {y} Td ({text}) Tj ET\n")
            stream = "".join(content).encode("latin-1", errors="replace")
            content_num = next_obj
            page_num = next_obj + 1
            next_obj += 2
            objs[content_num] = (b"<< /Length " + str(len(stream)).encode()
                                 + b" >>\nstream\n" + stream + b"\nendstream")
            objs[page_num] = (
                b"<< /Type /Page /Parent 2 0 R "
                b"/MediaBox [0 0 " + f"{self.W} {self.H}".encode() + b"] "
                b"/Resources << /Font << /F1 3 0 R >> >> "
                b"/Contents " + str(content_num).encode() + b" 0 R >>")
            page_obj_nums.append(page_num)

        kids = b" ".join(f"{n} 0 R".encode() for n in page_obj_nums)
        objs[2] = (b"<< /Type /Pages /Kids [" + kids + b"] /Count "
                   + str(len(page_obj_nums)).encode() + b" >>")

        # Monta o arquivo com a xref table.
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = {}
        for num in sorted(objs):
            offsets[num] = len(out)
            out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
        xref_pos = len(out)
        n = max(objs) + 1
        out += f"xref\n0 {n}\n".encode()
        out += b"0000000000 65535 f \n"
        for num in range(1, n):
            out += f"{offsets.get(num, 0):010d} 00000 n \n".encode()
        out += (b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R >>\n"
                b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n")
        return bytes(out)
