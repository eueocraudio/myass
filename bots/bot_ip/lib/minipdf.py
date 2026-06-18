"""minipdf — gerador de PDF em **stdlib** (sem dependências), com cores, tabelas,
texto justificado e cabeçalho/rodapé por página.

Usa métricas das fontes-padrão Helvetica/Helvetica-Bold (larguras WinAnsi) para
medir texto — o que permite quebra por largura real, centralização, alinhamento
à direita e **justificação** (via operador ``Tw``). Três fontes: F1 Helvetica,
F2 Helvetica-Bold, F3 Helvetica-Oblique.
"""

# ---- métricas (largura/1000 em em) das fontes-padrão (subset WinAnsi) --------
def _widths(spec):
    d = {}
    for ch, w in spec:
        d[ch] = w
    return d


_HELV = _widths([
    (" ", 278), ("!", 278), ('"', 355), ("#", 556), ("$", 556), ("%", 889),
    ("&", 667), ("'", 191), ("(", 333), (")", 333), ("*", 389), ("+", 584),
    (",", 278), ("-", 333), (".", 278), ("/", 278),
    ("0", 556), ("1", 556), ("2", 556), ("3", 556), ("4", 556), ("5", 556),
    ("6", 556), ("7", 556), ("8", 556), ("9", 556),
    (":", 278), (";", 278), ("<", 584), ("=", 584), (">", 584), ("?", 556),
    ("@", 1015), ("A", 667), ("B", 667), ("C", 722), ("D", 722), ("E", 667),
    ("F", 611), ("G", 778), ("H", 722), ("I", 278), ("J", 500), ("K", 667),
    ("L", 556), ("M", 833), ("N", 722), ("O", 778), ("P", 667), ("Q", 778),
    ("R", 722), ("S", 667), ("T", 611), ("U", 722), ("V", 667), ("W", 944),
    ("X", 667), ("Y", 667), ("Z", 611), ("[", 278), ("\\", 278), ("]", 278),
    ("^", 469), ("_", 556), ("`", 333),
    ("a", 556), ("b", 556), ("c", 500), ("d", 556), ("e", 556), ("f", 278),
    ("g", 556), ("h", 556), ("i", 222), ("j", 222), ("k", 500), ("l", 222),
    ("m", 833), ("n", 556), ("o", 556), ("p", 556), ("q", 556), ("r", 333),
    ("s", 500), ("t", 278), ("u", 556), ("v", 500), ("w", 722), ("x", 500),
    ("y", 500), ("z", 500), ("{", 334), ("|", 260), ("}", 334), ("~", 584),
])
_HELVB = _widths([
    (" ", 278), ("!", 333), ('"', 474), ("#", 556), ("$", 556), ("%", 889),
    ("&", 722), ("'", 238), ("(", 333), (")", 333), ("*", 389), ("+", 584),
    (",", 278), ("-", 333), (".", 278), ("/", 278),
    ("0", 556), ("1", 556), ("2", 556), ("3", 556), ("4", 556), ("5", 556),
    ("6", 556), ("7", 556), ("8", 556), ("9", 556),
    (":", 333), (";", 333), ("<", 584), ("=", 584), (">", 584), ("?", 611),
    ("@", 975), ("A", 722), ("B", 722), ("C", 722), ("D", 722), ("E", 667),
    ("F", 611), ("G", 778), ("H", 722), ("I", 278), ("J", 556), ("K", 722),
    ("L", 611), ("M", 833), ("N", 722), ("O", 778), ("P", 667), ("Q", 778),
    ("R", 722), ("S", 667), ("T", 611), ("U", 722), ("V", 667), ("W", 944),
    ("X", 667), ("Y", 667), ("Z", 611), ("[", 333), ("\\", 278), ("]", 333),
    ("^", 584), ("_", 556), ("`", 333),
    ("a", 556), ("b", 611), ("c", 556), ("d", 611), ("e", 556), ("f", 333),
    ("g", 611), ("h", 611), ("i", 278), ("j", 278), ("k", 556), ("l", 278),
    ("m", 889), ("n", 611), ("o", 611), ("p", 611), ("q", 611), ("r", 389),
    ("s", 556), ("t", 333), ("u", 611), ("v", 556), ("w", 778), ("x", 556),
    ("y", 556), ("z", 500), ("{", 389), ("|", 280), ("}", 389), ("~", 584),
])
_DEFAULT_W = 556

# ---- geometria (A4, em pontos) ----------------------------------------------
_W, _H = 595.28, 841.89
_LEFT, _RIGHT = 56.0, 539.28
_CONTENT_W = _RIGHT - _LEFT
_TOP = _H - 92.0          # início do conteúdo (abaixo do cabeçalho)
_BOTTOM = 58.0            # fim do conteúdo (acima do rodapé)

# ---- paleta ----
_C_TEXT = (0.13, 0.13, 0.13)
_C_HEAD = (0.12, 0.27, 0.53)      # azul dos títulos de seção
_C_BANNER = (0.86, 0.86, 0.86)    # cinza do banner do CVE
_C_TH = (1.0, 0.39, 0.0)          # laranja do cabeçalho de tabela
_C_TH_TXT = (1.0, 1.0, 1.0)
_C_ROW = (0.88, 0.92, 1.0)        # azul claro de linha alternada
_C_GRAY = (0.5, 0.5, 0.5)
_C_LINK = (0.1, 0.3, 0.6)


def _esc(s):
    return (s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))


def _wtable(bold):
    return _HELVB if bold else _HELV


def string_width(s, size, bold=False):
    t = _wtable(bold)
    return sum(t.get(c, _DEFAULT_W) for c in s) / 1000.0 * size


def _wrap(text, size, max_w, bold=False):
    """Quebra em linhas que cabem em ``max_w`` (largura real da fonte)."""
    out = []
    for para in str(text).split("\n"):
        words = para.split(" ")
        line = ""
        for w in words:
            cand = w if not line else line + " " + w
            if string_width(cand, size, bold) <= max_w or not line:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    return out or [""]


class Pdf:
    def __init__(self, title="", footer=""):
        self.W, self.H = _W, _H
        self._title = title
        self._footer = footer
        self._pages = []
        self._ops = []
        self._y = _TOP
        self._sections = []     # (título, índice de página preliminar, y) p/ o TOC
        self._toc_at = None     # onde inserir o TOC (após a capa)

    # ---- emissão de baixo nível ---------------------------------------
    def _flush(self):
        self._pages.append(self._ops)
        self._ops = []
        self._y = _TOP

    def _space(self, h):
        if self._y - h < _BOTTOM:
            self._flush()

    def page_break(self):
        """Força o início de uma nova página (item: 1 CVE por página)."""
        if self._ops:
            self._flush()

    def start_toc(self):
        """Marca o ponto (após a capa) onde o Índice clicável será inserido."""
        if self._ops:
            self._flush()
        self._toc_at = len(self._pages)

    def section(self, title):
        """Registra um destino do Índice na página atual (chame após page_break)."""
        self._sections.append((title, len(self._pages), self._y))

    def _text(self, x, y, size, s, *, bold=False, italic=False, color=_C_TEXT, tw=0.0):
        font = 2 if bold else 3 if italic else 1
        self._ops.append(("t", x, y, size, font, color, tw, _esc(s)))

    def _rect(self, x, y, w, h, color):
        self._ops.append(("r", x, y, w, h, color))

    # ---- API de conteúdo ----------------------------------------------
    def title(self, s):
        """Título grande (capa)."""
        self._space(30)
        for ln in _wrap(s, 20, _CONTENT_W, bold=True):
            self._text(_LEFT, self._y, 20, ln, bold=True, color=_C_HEAD)
            self._y -= 26
        self._y -= 6

    def heading(self, s, size=13):
        self._space(size + 12)
        self._y -= 6
        self._text(_LEFT, self._y, size, s, bold=True, color=_C_HEAD)
        self._y -= size + 4

    def banner(self, s, size=14):
        """Faixa cinza com o título (um CVE)."""
        lines = _wrap(s, size, _CONTENT_W - 12, bold=True)
        lh = size + 6
        h = lh * len(lines) + 8
        self._space(h + 6)
        top = self._y
        self._rect(_LEFT, top - h + 4, _CONTENT_W, h, _C_BANNER)
        y = top - size
        for ln in lines:
            self._text(_LEFT + 6, y, size, ln, bold=True)
            y -= lh
        self._y = top - h - 2

    def paragraph(self, text, size=10, justify=True, color=_C_TEXT, indent=0.0):
        max_w = _CONTENT_W - indent
        lines = _wrap(text, size, max_w)
        lh = size * 1.4
        for i, ln in enumerate(lines):
            self._space(lh)
            last = (i == len(lines) - 1)
            tw = 0.0
            words = ln.split(" ")
            if justify and not last and len(words) > 1:
                gaps = len(words) - 1
                extra = max_w - string_width(ln, size)
                if extra > 0:
                    tw = extra / gaps
            self._text(_LEFT + indent, self._y, size, ln, color=color, tw=tw)
            self._y -= lh

    def line(self, s, size=10):
        """Compat: parágrafo não-justificado (uma 'linha' que pode quebrar)."""
        self.paragraph("" if s is None else str(s), size=size, justify=False)

    def kv(self, label, value, size=10):
        self._space(size * 1.4)
        self._text(_LEFT, self._y, size, label, bold=True)
        lw = string_width(label + "  ", size, bold=True)
        self._text(_LEFT + lw, self._y, size, str(value))
        self._y -= size * 1.4

    def bullet(self, s, size=10, indent=14.0):
        self.paragraph("• " + str(s), size=size, justify=False, indent=indent)

    def link(self, s, size=9, indent=14.0):
        self.paragraph(str(s), size=size, justify=False, color=_C_LINK, indent=indent)

    def small(self, s, size=8):
        self.paragraph(str(s), size=size, justify=False, color=_C_GRAY)

    def spacer(self, n=1):
        self._y -= n * 12

    def rule(self):
        self._space(8)
        self._rect(_LEFT, self._y + 2, _CONTENT_W, 0.6, _C_GRAY)
        self._y -= 8

    def table(self, headers, rows, col_widths, aligns=None, size=10):
        """Tabela: cabeçalho laranja, linhas alternadas em azul claro. Sempre
        ocupa a largura inteira (as colunas são escaladas proporcionalmente)."""
        total = sum(col_widths)
        scale = _CONTENT_W / total if total else 1.0  # estica p/ a largura toda
        cw = [w * scale for w in col_widths]
        aligns = aligns or ["L"] * len(headers)
        lh = size + 8

        def draw_row(cells, fill, txt_color, bold):
            self._space(lh)
            top = self._y
            self._rect(_LEFT, top - lh + 4, sum(cw), lh, fill)
            x = _LEFT
            for i, cell in enumerate(cells):
                s = str(cell)
                pad = 4
                if aligns[i] == "R":
                    tx = x + cw[i] - pad - string_width(s, size, bold)
                elif aligns[i] == "C":
                    tx = x + (cw[i] - string_width(s, size, bold)) / 2
                else:
                    tx = x + pad
                self._text(tx, top - size + 1, size, s, bold=bold, color=txt_color)
                x += cw[i]
            self._y = top - lh

        draw_row(headers, _C_TH, _C_TH_TXT, True)
        for i, r in enumerate(rows):
            draw_row(r, _C_ROW if i % 2 == 0 else (1, 1, 1), _C_TEXT, False)
        self._y -= 12  # espaço extra depois da tabela (item VII)

    def cvss_options(self, metrics, size=8):
        """'Painel' visual da calculadora: por métrica, todas as opções com a
        selecionada destacada (item VI)."""
        lh = size + 7
        label_w = 150.0
        for met in metrics:
            self._space(lh)
            top = self._y
            self._text(_LEFT, top - size + 1, size, met["metric_name"], bold=True)
            x = _LEFT + label_w
            for opt in met["options"]:
                w = string_width(opt["name"], size, opt["selected"]) + 10
                if x + w > _RIGHT:               # quebra: nova linha alinhada
                    top -= lh
                    self._space(lh)
                    x = _LEFT + label_w
                fill = _C_TH if opt["selected"] else (0.93, 0.93, 0.93)
                tc = _C_TH_TXT if opt["selected"] else _C_GRAY
                self._rect(x, top - size - 1, w, size + 5, fill)
                self._text(x + 5, top - size + 1, size, opt["name"],
                           color=tc, bold=opt["selected"])
                x += w + 4
            self._y = top - lh - 2

    # ---- serialização --------------------------------------------------
    def render(self) -> bytes:
        return self._build()

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self._build())

    def _chrome(self, page_ops, page_no, total):
        """Cabeçalho (título emoldurado, centralizado) + rodapé (url + página)."""
        ops = []
        if self._title:
            tw = string_width(self._title, 13, bold=True)
            bx = (_W - tw - 16) / 2
            ops.append(("r", bx, _H - 56, tw + 16, 22, (1, 1, 1)))
            ops.append(("L", bx, _H - 56, tw + 16, 22))  # moldura
            ops.append(("t", bx + 8, _H - 48, 13, 2, _C_TEXT, 0.0, _esc(self._title)))
        foot = self._footer or ""
        ft = f"{foot}  -  Página {page_no} de {total}".strip(" -")
        fw = string_width(ft, 8)
        ops.append(("t", (_W - fw) / 2, 38, 8, 3, _C_GRAY, 0.0, _esc(ft)))
        return ops + page_ops

    def _serialize(self, ops):
        buf = []
        for op in ops:
            k = op[0]
            if k == "r":
                _, x, y, w, h, c = op
                buf.append(f"{c[0]:.3f} {c[1]:.3f} {c[2]:.3f} rg "
                           f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")
            elif k == "L":
                _, x, y, w, h = op
                buf.append(f"0.2 0.2 0.2 RG 0.6 w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")
            else:
                _, x, y, s, f, c, tw, txt = op
                buf.append(f"BT /F{f} {s} Tf {c[0]:.3f} {c[1]:.3f} {c[2]:.3f} rg "
                           f"{tw:.3f} Tw {x:.2f} {y:.2f} Td ({txt}) Tj ET")
        # WinAnsiEncoding == CP1252: mapeia •, –, aspas e acentos corretamente.
        return "\n".join(buf).encode("cp1252", errors="replace")

    def _count_toc_pages(self):
        lh, y, pages = 16, _TOP - 20, 1
        for _ in self._sections:
            if y - lh < _BOTTOM:
                pages += 1
                y = _TOP
            y -= lh
        return pages

    def _render_toc(self, T):
        """Páginas do Índice (título … nº) + specs de link. ``T`` = nº de páginas
        do índice (para os números de página já saírem corretos)."""
        size, lh = 10, 16
        pages, ops, y, links = [], [], _TOP, []
        ops.append(("t", _LEFT, y, 14, 2, _C_HEAD, 0.0, _esc("Índice")))
        y -= 20
        dotw = string_width(".", size) or 2.0
        for (title, pidx, _ty) in self._sections:
            if y - lh < _BOTTOM:
                pages.append(ops)
                ops, y = [], _TOP
            pageno = str(pidx + T + 1)
            numw = string_width(pageno, size)
            max_title = _CONTENT_W - numw - 28
            t = title
            if string_width(t, size) > max_title:
                while t and string_width(t + "…", size) > max_title:
                    t = t[:-1]
                t = t.rstrip() + "…"
            tw = string_width(t, size)
            ops.append(("t", _LEFT, y, size, 1, _C_LINK, 0.0, _esc(t)))
            dl, dr = _LEFT + tw + 4, _RIGHT - numw - 6
            nd = max(0, int((dr - dl) / dotw))
            if nd:
                ops.append(("t", dl, y, size, 1, _C_GRAY, 0.0, "." * nd))
            ops.append(("t", _RIGHT - numw, y, size, 1, _C_TEXT, 0.0, _esc(pageno)))
            links.append((len(pages), (_LEFT, y - 3, _RIGHT, y + size), pidx + T))
            y -= lh
        pages.append(ops)
        return pages, links

    def _build(self):
        if self._ops:
            self._flush()
        pages = self._pages or [[]]
        cover = self._toc_at if self._toc_at is not None else len(pages)
        toc_pages, links = [], []
        if self._toc_at is not None and self._sections:
            toc_pages, links = self._render_toc(self._count_toc_pages())
        final = pages[:cover] + toc_pages + pages[cover:]
        total = len(final)

        objs = {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
            5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>",
        }
        next_obj = 6
        page_obj, content_obj = [], []
        for _ in range(total):
            page_obj.append(next_obj)
            content_obj.append(next_obj + 1)
            next_obj += 2

        # anotações de link do Índice (clicável)
        toc_annots = {}
        for (toc_local, rect, target_final) in links:
            a = next_obj
            next_obj += 1
            x0, y0, x1, y1 = rect
            objs[a] = (f"<< /Type /Annot /Subtype /Link /Border [0 0 0] "
                       f"/Rect [{x0:.2f} {y0:.2f} {x1:.2f} {y1:.2f}] "
                       f"/Dest [{page_obj[target_final]} 0 R /XYZ {_LEFT:.2f} "
                       f"{_H - 40:.2f} 0] >>").encode("latin-1")
            toc_annots.setdefault(cover + toc_local, []).append(a)

        for i, page in enumerate(final):
            stream = self._serialize(self._chrome(page, i + 1, total))
            objs[content_obj[i]] = (b"<< /Length " + str(len(stream)).encode()
                                    + b" >>\nstream\n" + stream + b"\nendstream")
            ann = b""
            if i in toc_annots:
                ann = (b" /Annots [" + b" ".join(f"{a} 0 R".encode()
                       for a in toc_annots[i]) + b"]")
            objs[page_obj[i]] = (
                b"<< /Type /Page /Parent 2 0 R "
                b"/MediaBox [0 0 " + f"{_W:.2f} {_H:.2f}".encode() + b"] "
                b"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
                b"/Contents " + str(content_obj[i]).encode() + b" 0 R" + ann + b" >>")

        kids = b" ".join(f"{n} 0 R".encode() for n in page_obj)
        objs[2] = (b"<< /Type /Pages /Kids [" + kids + b"] /Count "
                   + str(total).encode() + b" >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = {}
        for num in sorted(objs):
            offsets[num] = len(out)
            out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
        xref_pos = len(out)
        n = max(objs) + 1
        out += f"xref\n0 {n}\n".encode() + b"0000000000 65535 f \n"
        for num in range(1, n):
            out += f"{offsets.get(num, 0):010d} 00000 n \n".encode()
        out += (b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R >>\n"
                b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n")
        return bytes(out)
