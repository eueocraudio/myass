"""Painel do administrador — GUI PySide6 (Parte I, apresentação).

App desktop sobre o ``AdminClient``: publicar BOTs/workflows, ler o catálogo,
iniciar e acompanhar ocorrências, ver o ambiente, e **editar workflows** na
*Tela de Workflow* (abas; a 1ª é o editor Nassi-Shneiderman híbrido).

**Ciclo de vida de versão (decisão do dono):**
- ``Em Produção`` = versão publicada no registro **append-only/imutável** do
  núcleo (``(nome,versao) → template_hash``). Imutável; pode virar ocorrência.
- ``Em edição`` = rascunho local (em ``~/.myass/drafts/``), editável à vontade.
- **Promover** (Em edição → Em Produção) = ``PUBLISH`` → congela o hash. Editar
  uma versão em produção exige **nova versão** (rascunho com bump).

Importar o módulo não cria ``QApplication`` (só ``main()``/instanciar a janela),
para permitir smoke test sem display.
"""

from __future__ import annotations

import base64
import copy
import json
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..workflow.inputs import required_inputs
from ..workflow.template import canonical, node_at, template_hash


# ===== rascunhos locais (versões "Em edição") =========================
def drafts_dir() -> str:
    d = os.environ.get("MYASS_DRAFTS") or os.path.expanduser("~/.myass/drafts")
    os.makedirs(d, exist_ok=True)
    return d


def _draft_path(nome: str, versao: str) -> str:
    safe = f"{nome}__{versao}".replace("/", "_").replace("..", "_")
    return os.path.join(drafts_dir(), safe + ".json")


def list_drafts() -> list:
    out = []
    for fn in sorted(os.listdir(drafts_dir())):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(drafts_dir(), fn), encoding="utf-8") as f:
                    out.append(json.load(f))
            except Exception:  # noqa: BLE001
                pass
    return out


def save_draft(nome: str, versao: str, template: dict) -> None:
    draft = {"nome": nome, "versao": versao, "estado": "em_edicao",
             "template": template}
    with open(_draft_path(nome, versao), "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)


def delete_draft(nome: str, versao: str) -> None:
    p = _draft_path(nome, versao)
    if os.path.exists(p):
        os.remove(p)


def bump_version(v: str) -> str:
    parts = str(v).split(".")
    if parts and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{v}.1"


# ===== render Nassi-Shneiderman (estrutograma) ========================
# Caixas contíguas e aninhadas (sem setas): block = pilha vertical, action =
# caixa, loop = moldura com o corpo recuado, decision = cabeçalho + colunas por
# label. Em editor: cada nó é clicável (seleciona p/ o inspetor).

_NASSI_COLORS = {
    "action": "#eaf2fb", "decision": "#fdf3e0",
    "loop": "#eaf7ee", "block": "transparent",
}

# Cores de status de execução (sobrepõem a cor do tipo quando há ``status_of``):
# verde = feito, amarelo = executando, vermelho = falhou. Mesma paleta do badge.
_STATUS_COLORS = {"done": "#cdebd3", "running": "#fde2b3", "failed": "#f5c6c6"}


def _box_color(tipo: str, node: dict, status_of) -> str:
    """Cor da caixa: o status de execução vence a cor do tipo, se houver."""
    if status_of is not None:
        c = _STATUS_COLORS.get(status_of(node))
        if c:
            return c
    return _NASSI_COLORS.get(tipo, "transparent")


def _short(h) -> str:
    if not isinstance(h, str):
        return ""
    tail = h.split(":")[-1]
    return tail[:8] + "…" if len(tail) > 8 else tail


def _catch_lines(node) -> list:
    return [f"⚠ catch: {c.get('match', '*')} → {c.get('disposicao', 'subir')}"
            for c in (node.get("catch") or [])]


def _params_summary(node) -> str:
    p = node.get("params")
    if p in (None, {}, ""):
        return ""
    s = p if isinstance(p, str) else json.dumps(p, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= 60 else s[:57] + "…"


def _label(text: str, *, bold=False, small=False, gray=False, center=False) -> QLabel:
    lab = QLabel(text)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    lab.setWordWrap(True)
    css = ["border: none;", "background: transparent;"]
    if bold:
        css.append("font-weight: bold;")
    if small:
        css.append("font-size: 11px;")
    if gray:
        css.append("color: #555;")
    lab.setStyleSheet("QLabel {" + " ".join(css) + "}")
    if center:
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lab


class _NodeFrame(QFrame):
    """Caixa de nó clicável: chama ``on_select(path)`` ao receber o clique."""

    def __init__(self, path, on_select):
        super().__init__()
        self._path = list(path)
        self._cb = on_select

    def mousePressEvent(self, e):  # noqa: N802
        if self._cb:
            self._cb(self._path)
        e.accept()  # innermost vence: não propaga ao escopo pai


def _node_box(color, path=None, on_select=None, selected=None) -> QFrame:
    f = _NodeFrame(path, on_select) if on_select else QFrame()
    f.setFrameShape(QFrame.Shape.Box)
    f.setLineWidth(1)
    hl = path is not None and selected is not None and list(selected) == list(path)
    border = "2px solid #1e7e34" if hl else "1px solid #888"
    bg = "" if (not color or color == "transparent") else f"background: {color};"
    f.setStyleSheet(f"QFrame {{ {bg} border: {border}; }}")
    return f


def nassi_widget(node: dict, resolve=lambda h: "", path=("raiz",),
                 on_select=None, selected=None, status_of=None) -> QWidget:
    """Widget do estrutograma para ``node`` (em ``path``). ``resolve(script_hash)
    -> 'bot/script'`` rotula as ações; ``on_select(path)`` torna os nós clicáveis;
    ``status_of(node) -> 'done'|'running'|'failed'|None`` colore por execução."""
    path = list(path)
    tipo = node.get("tipo")

    if tipo == "block":
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        filhos = node.get("filhos", []) or []
        if not filhos:
            empty = _node_box("transparent", path, on_select, selected)
            QVBoxLayout(empty).addWidget(_label("(bloco vazio)", small=True, gray=True))
            v.addWidget(empty)
        for i, ch in enumerate(filhos):
            v.addWidget(nassi_widget(ch, resolve, path + ["filhos", i],
                                     on_select, selected, status_of))
        return holder

    if tipo == "action":
        box = _node_box(_box_color("action", node, status_of), path, on_select, selected)
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 5, 8, 5)
        v.setSpacing(1)
        v.addWidget(_label(node.get("nome", "ação"), bold=True))
        ref = resolve((node.get("bot_ref") or {}).get("script_hash"))
        v.addWidget(_label(ref or f"script {_short((node.get('bot_ref') or {}).get('script_hash'))}",
                           small=True, gray=True))
        ps = _params_summary(node)
        if ps:
            v.addWidget(_label("params: " + ps, small=True, gray=True))
        for cl in _catch_lines(node):
            v.addWidget(_label(cl, small=True, gray=True))
        return box

    if tipo == "loop":
        box = _node_box(_box_color("loop", node, status_of), path, on_select, selected)
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = (f"↻ {node.get('nome', 'loop')} — para cada item de "
                f"{node.get('array', '?')} como '{node.get('item', 'item')}'")
        hl = _label(head, bold=True)
        hl.setContentsMargins(8, 4, 8, 4)
        v.addWidget(hl)
        inset = QWidget()
        hb = QHBoxLayout(inset)
        hb.setContentsMargins(16, 0, 0, 0)
        hb.setSpacing(0)
        corpo = node.get("corpo")
        if corpo:
            hb.addWidget(nassi_widget(corpo, resolve, path + ["corpo"],
                                      on_select, selected, status_of))
        else:
            hb.addWidget(_node_box("transparent"))
        v.addWidget(inset)
        foot = _label(f"join → {node.get('join', '')}", small=True, gray=True)
        foot.setContentsMargins(8, 2, 8, 2)
        v.addWidget(foot)
        for cl in _catch_lines(node):
            v.addWidget(_label(cl, small=True, gray=True))
        return box

    if tipo == "decision":
        box = _node_box(_box_color("decision", node, status_of), path, on_select, selected)
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        ref = resolve((node.get("bot_ref") or {}).get("script_hash"))
        hl = _label(f"◇ {node.get('nome', 'decisão')} — {ref or 'condição'}",
                    bold=True, center=True)
        hl.setContentsMargins(8, 4, 8, 4)
        v.addWidget(hl)
        cols = QWidget()
        hb = QHBoxLayout(cols)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(0)
        rotas = node.get("rotas", {}) or {}
        if not rotas:
            hb.addWidget(_node_box("transparent"))
        for label, sub in rotas.items():
            col = QWidget()
            cv = QVBoxLayout(col)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(0)
            cv.addWidget(_label(str(label), small=True, center=True))
            cv.addWidget(nassi_widget(sub, resolve, path + ["rotas", label],
                                      on_select, selected, status_of))
            cv.addStretch(1)
            hb.addWidget(col)
        v.addWidget(cols)
        for cl in _catch_lines(node):
            v.addWidget(_label(cl, small=True, gray=True))
        return box

    if "raiz" in node:
        return nassi_widget(node["raiz"], resolve, ["raiz"], on_select, selected, status_of)
    box = _node_box("transparent", path, on_select, selected)
    QVBoxLayout(box).addWidget(_label(f"[{tipo}]", gray=True))
    return box


# ===== Tela de Workflow (abas; 1ª = editor Nassi híbrido) =============
def _new_node(tipo: str, palette: list) -> dict:
    ref = palette[0]["bot_ref"] if palette else {"project_hash": "", "script_hash": ""}
    if tipo == "action":
        return {"tipo": "action", "nome": "NovaAcao", "bot_ref": ref, "params": {}}
    if tipo == "loop":
        return {"tipo": "loop", "nome": "NovoLoop", "array": "$input.itens",
                "item": "item", "corpo": {"tipo": "block", "filhos": []}, "join": "itens"}
    if tipo == "decision":
        return {"tipo": "decision", "nome": "NovaDecisao", "bot_ref": ref, "params": {},
                "rotas": {"sim": {"tipo": "block", "filhos": []},
                          "nao": {"tipo": "block", "filhos": []}}}
    raise ValueError(tipo)


class WorkflowWindow(QDialog):
    """Tela de Workflow. ``estado`` ∈ {em_edicao, em_producao}; em produção é
    leitura (imutável) com a opção de criar um rascunho de nova versão."""

    def __init__(self, *, nome, versao, estado, template, client=None,
                 resolve=lambda h: "", palette=None, bots=None, on_change=None,
                 parent=None):
        super().__init__(parent)
        self.nome = nome
        self.versao = versao
        self.estado = estado
        self.template = template if "raiz" in template else {"raiz": template}
        self.template.setdefault("nome", nome)
        self.template.setdefault("versao", versao)
        self.template.setdefault("tipo", "workflow")
        self.client = client
        self.resolve = resolve
        self.palette = palette or []
        self.bots = bots or []  # [{"nome","project_hash","scripts":[{"nome","script_hash"}]}]
        self.on_change = on_change
        self.selected_path = None
        self.editable = (estado == "em_edicao")

        self.setWindowTitle(f"Tela de Workflow — {nome} {versao}")
        self.resize(940, 680)
        root = QVBoxLayout(self)

        # cabeçalho: título + badge de estado + ações de ciclo de vida
        head = QHBoxLayout()
        head.addWidget(_label(f"{nome}  v{versao}", bold=True))
        self.badge = QLabel()
        head.addWidget(self.badge)
        head.addStretch(1)
        self.btn_new_draft = QPushButton("Criar rascunho (nova versão)")
        self.btn_new_draft.clicked.connect(self._new_draft_from_current)
        self.btn_save = QPushButton("Salvar rascunho")
        self.btn_save.clicked.connect(self._save)
        self.btn_promote = QPushButton("Promover para Produção")
        self.btn_promote.clicked.connect(self._promote)
        head.addWidget(self.btn_new_draft)
        head.addWidget(self.btn_save)
        head.addWidget(self.btn_promote)
        root.addLayout(head)
        self.hash_lbl = _label("", small=True, gray=True)
        root.addWidget(self.hash_lbl)

        tabs = QTabWidget()
        tabs.addTab(self._tab_nassi(), "Nassi (editor)")
        tabs.addTab(self._tab_json(), "JSON")
        root.addWidget(tabs)

        self.status = _label("", small=True, gray=True)
        root.addWidget(self.status)

        self._sync_lifecycle()
        self._render()

    # ---- aba Nassi (editor híbrido) -----------------------------------
    def _tab_nassi(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        bar = QHBoxLayout()
        self._tool_btns = []
        for txt, fn in (("+ Ação", lambda: self._add("action")),
                        ("+ Loop", lambda: self._add("loop")),
                        ("+ Decisão", lambda: self._add("decision")),
                        ("Remover", self._remove),
                        ("↑", lambda: self._move(-1)),
                        ("↓", lambda: self._move(1))):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            bar.addWidget(b)
            self._tool_btns.append(b)
        bar.addStretch(1)
        lay.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        self._diagram_scroll = QScrollArea()
        self._diagram_scroll.setWidgetResizable(True)
        split.addWidget(self._diagram_scroll)
        self._inspector = QScrollArea()
        self._inspector.setWidgetResizable(True)
        self._inspector.setMinimumWidth(300)
        split.addWidget(self._inspector)
        split.setSizes([600, 320])
        lay.addWidget(split)
        return w

    def _tab_json(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.json_edit = QPlainTextEdit()
        lay.addWidget(self.json_edit)
        row = QHBoxLayout()
        b_apply = QPushButton("Aplicar JSON ao diagrama")
        b_apply.clicked.connect(self._apply_json)
        b_from = QPushButton("Recarregar do diagrama")
        b_from.clicked.connect(self._json_from_template)
        row.addWidget(b_apply)
        row.addWidget(b_from)
        row.addStretch(1)
        lay.addLayout(row)
        return w

    # ---- ciclo de vida -------------------------------------------------
    def _sync_lifecycle(self):
        em_ed = (self.estado == "em_edicao")
        self.editable = em_ed
        if em_ed:
            self.badge.setText("  Em edição  ")
            self.badge.setStyleSheet("QLabel { background:#fde2b3; color:#7a4b00;"
                                     " border:1px solid #d99a2b; border-radius:3px; }")
        else:
            self.badge.setText("  Em Produção  ")
            self.badge.setStyleSheet("QLabel { background:#cdebd3; color:#1e5b2c;"
                                     " border:1px solid #1e7e34; border-radius:3px; }")
        self.btn_new_draft.setVisible(not em_ed)
        self.btn_save.setVisible(em_ed)
        self.btn_promote.setVisible(em_ed)
        for b in getattr(self, "_tool_btns", []):
            b.setEnabled(em_ed)

    # ---- render --------------------------------------------------------
    def _render(self):
        raiz = self.template.get("raiz", self.template)
        diag = nassi_widget(raiz, self.resolve, ["raiz"],
                            on_select=self._select, selected=self.selected_path)
        holder = QWidget()
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(6, 6, 6, 6)
        hv.addWidget(diag)
        hv.addStretch(1)
        self._diagram_scroll.setWidget(holder)
        self._build_inspector()
        self._json_from_template()
        try:
            self.hash_lbl.setText("template_hash: " + template_hash(self.template))
        except Exception:  # noqa: BLE001
            self.hash_lbl.setText("")

    def _select(self, path):
        self.selected_path = path
        self._render()

    def _selected_node(self):
        if self.selected_path is None:
            return None
        try:
            return node_at(self.template, self.selected_path)
        except Exception:  # noqa: BLE001
            return None

    # ---- inspetor do nó selecionado -----------------------------------
    def _build_inspector(self):
        w = QWidget()
        form = QFormLayout(w)
        node = self._selected_node()
        if node is None:
            form.addRow(_label("Selecione um nó no diagrama para editar, ou use a "
                               "barra para inserir.", small=True, gray=True))
            self._inspector.setWidget(w)
            return

        tipo = node.get("tipo")
        form.addRow("tipo", _label(tipo))
        if tipo == "block":
            form.addRow(_label("Bloco (container). Selecione um filho, ou insira "
                               "um nó — ele entra neste bloco.", small=True, gray=True))
            self._inspector.setWidget(w)
            return

        widgets = {}
        nome_edit = QLineEdit(node.get("nome", ""))
        form.addRow("nome", nome_edit)
        widgets["nome"] = nome_edit

        if tipo in ("action", "decision"):
            # dois combos: BOT → script (um workflow pode usar vários BOTs; cada
            # atividade escolhe um BOT e um script dentro dele).
            cur_ref = node.get("bot_ref") or {}
            cur_proj, cur_sh = cur_ref.get("project_hash"), cur_ref.get("script_hash")
            bot_items = list(self.bots)
            known = {b["project_hash"] for b in bot_items}
            if cur_proj and cur_proj not in known:  # mostra o BOT atual mesmo fora da paleta
                bot_items = [{"nome": f"(atual) {_short(cur_proj)}", "project_hash": cur_proj,
                              "scripts": [{"nome": self.resolve(cur_sh) or _short(cur_sh),
                                           "script_hash": cur_sh}]}] + bot_items
            bot_combo = QComboBox()
            for b in bot_items:
                bot_combo.addItem(b["nome"], b)
            script_combo = QComboBox()

            def _fill_scripts(bot, select_sh=None):
                script_combo.clear()
                for s in (bot or {}).get("scripts", []):
                    script_combo.addItem(s["nome"], {"project_hash": bot["project_hash"],
                                                     "script_hash": s["script_hash"]})
                if select_sh:
                    for i in range(script_combo.count()):
                        if (script_combo.itemData(i) or {}).get("script_hash") == select_sh:
                            script_combo.setCurrentIndex(i)
                            break

            bsel = next((i for i, b in enumerate(bot_items)
                         if b["project_hash"] == cur_proj), 0)
            bot_combo.setCurrentIndex(bsel)
            _fill_scripts(bot_items[bsel] if bot_items else None, cur_sh)
            bot_combo.currentIndexChanged.connect(
                lambda _i: _fill_scripts(bot_combo.currentData()))
            form.addRow("BOT", bot_combo)
            form.addRow("script", script_combo)
            widgets["script_combo"] = script_combo
            pe = QPlainTextEdit(json.dumps(node.get("params", {}), ensure_ascii=False, indent=2))
            pe.setFixedHeight(90)
            form.addRow("params (JSON)", pe)
            widgets["params"] = pe

        if tipo == "loop":
            for key, default in (("array", ""), ("item", "item"), ("join", "")):
                le = QLineEdit(str(node.get(key, default)))
                form.addRow(key, le)
                widgets[key] = le

        if tipo == "decision":
            re = QPlainTextEdit("\n".join((node.get("rotas") or {}).keys()))
            re.setFixedHeight(70)
            form.addRow("rotas (1 label/linha)", re)
            widgets["rotas"] = re

        cc = QComboBox()
        cc.addItems(["(sem catch)", "ignorar (*)", "subir (*)"])
        cur_catch = node.get("catch") or []
        if cur_catch:
            disp = cur_catch[0].get("disposicao")
            cc.setCurrentIndex({"ignorar": 1, "subir": 2}.get(disp, 0))
        form.addRow("catch", cc)
        widgets["catch"] = cc

        apply_btn = QPushButton("Aplicar ao nó")
        apply_btn.clicked.connect(lambda: self._apply_node(node, widgets))
        form.addRow(apply_btn)

        if not self.editable:
            for cls in (QLineEdit, QComboBox, QPlainTextEdit, QPushButton):
                for ch in w.findChildren(cls):
                    ch.setEnabled(False)
        self._inspector.setWidget(w)

    def _apply_node(self, node, widgets):
        if not self.editable:
            return
        node["nome"] = widgets["nome"].text().strip() or node.get("nome", "")
        if "script_combo" in widgets:
            ref = widgets["script_combo"].currentData()
            if ref and ref.get("script_hash"):
                node["bot_ref"] = copy.deepcopy(ref)
        if "params" in widgets:
            val = self._parse_params(widgets["params"].toPlainText())
            if val is _INVALID:
                self._err("params: JSON inválido")
                return
            node["params"] = val
        for key in ("array", "item", "join"):
            if key in widgets:
                node[key] = widgets[key].text().strip()
        if "rotas" in widgets:
            labels = [ln.strip() for ln in widgets["rotas"].toPlainText().splitlines()
                      if ln.strip()]
            old = node.get("rotas", {}) or {}
            node["rotas"] = {lb: old.get(lb, {"tipo": "block", "filhos": []})
                             for lb in labels}
        disp = {0: None, 1: "ignorar", 2: "subir"}[widgets["catch"].currentIndex()]
        if disp:
            node["catch"] = [{"match": "*", "disposicao": disp}]
        else:
            node.pop("catch", None)
        self.status.setText("nó atualizado.")
        self._render()

    @staticmethod
    def _parse_params(text):
        t = text.strip()
        if not t:
            return {}
        try:
            return json.loads(t)
        except Exception:  # noqa: BLE001
            return t if t.startswith("$") else _INVALID

    # ---- barra de ferramentas: inserir / remover / mover --------------
    def _parent_list_index(self, path):
        """Para um nó em ``[...,'filhos', i]`` devolve (lista_filhos, i)."""
        if path and len(path) >= 2 and path[-2] == "filhos":
            return node_at(self.template, path[:-1]), path[-1]
        return None, None

    def _insertion_list(self):
        """Lista de filhos onde inserir + índice (após o selecionado)."""
        path = self.selected_path
        if path:
            lst, idx = self._parent_list_index(path)
            if lst is not None:
                return lst, idx + 1
            node = self._selected_node() or {}
            if node.get("tipo") == "block":
                return node.setdefault("filhos", []), len(node.get("filhos", []))
            if node.get("tipo") == "loop":
                return node["corpo"].setdefault("filhos", []), len(node["corpo"]["filhos"])
        raiz = self.template.setdefault("raiz", {"tipo": "block", "filhos": []})
        return raiz.setdefault("filhos", []), len(raiz.get("filhos", []))

    def _add(self, tipo):
        if not self.editable:
            return
        lst, idx = self._insertion_list()
        lst.insert(idx, _new_node(tipo, self.palette))
        self.selected_path = None
        self.status.setText(f"{tipo} inserido.")
        self._render()

    def _remove(self):
        if not self.editable:
            return
        lst, idx = self._parent_list_index(self.selected_path or [])
        if lst is None:
            self._err("selecione um nó dentro de um bloco para remover.")
            return
        lst.pop(idx)
        self.selected_path = None
        self.status.setText("nó removido.")
        self._render()

    def _move(self, delta):
        if not self.editable:
            return
        lst, idx = self._parent_list_index(self.selected_path or [])
        if lst is None:
            return
        j = idx + delta
        if 0 <= j < len(lst):
            lst[idx], lst[j] = lst[j], lst[idx]
            self.selected_path = self.selected_path[:-1] + [j]
            self._render()

    # ---- aba JSON ------------------------------------------------------
    def _json_from_template(self):
        self.json_edit.setPlainText(canonical(self.template))

    def _apply_json(self):
        if not self.editable:
            self._err("workflow em produção é imutável; crie um rascunho.")
            return
        try:
            tmpl = json.loads(self.json_edit.toPlainText())
        except Exception as e:  # noqa: BLE001
            self._err(f"JSON inválido: {e}")
            return
        if "raiz" not in tmpl:
            self._err("template precisa de 'raiz'.")
            return
        self.template = tmpl
        self.selected_path = None
        self.status.setText("JSON aplicado.")
        self._render()

    # ---- ciclo de vida: salvar / promover / novo rascunho -------------
    def _save(self):
        save_draft(self.nome, self.versao, self.template)
        self.status.setText(f"rascunho salvo em {drafts_dir()}")
        if self.on_change:
            self.on_change()

    def _promote(self):
        if self.client is None:
            self._err("sem conexão com o núcleo (não dá para publicar).")
            return
        if QMessageBox.question(self, "Promover", f"Publicar {self.nome} v{self.versao} "
                                "como versão imutável de Produção?") != QMessageBox.StandardButton.Yes:
            return
        try:
            ack = self.client.publish_workflow(self.template)
        except Exception as e:  # noqa: BLE001
            self._err(f"erro ao publicar: {e}")
            return
        if ack.get("status") == "aceito":
            delete_draft(self.nome, self.versao)
            self.estado = "em_producao"
            self._sync_lifecycle()
            self._render()
            self.status.setText(f"PROMOVIDO. hash {_short(ack.get('hash'))}")
            if self.on_change:
                self.on_change()
        else:
            self._err(f"rejeitado: {ack.get('motivo', ack)}")

    def _new_draft_from_current(self):
        ver, ok = QInputDialog.getText(self, "Novo rascunho",
                                       "Versão do novo rascunho:", text=bump_version(self.versao))
        if not ok or not ver.strip():
            return
        ver = ver.strip()
        tmpl = copy.deepcopy(self.template)
        tmpl["versao"] = ver
        save_draft(self.nome, ver, tmpl)
        if self.on_change:
            self.on_change()
        WorkflowWindow(nome=self.nome, versao=ver, estado="em_edicao", template=tmpl,
                       client=self.client, resolve=self.resolve, palette=self.palette,
                       bots=self.bots, on_change=self.on_change, parent=self.parent()).show()
        self.status.setText(f"rascunho v{ver} criado (Em edição).")

    def _err(self, msg):
        self.status.setText("erro: " + msg)
        QMessageBox.warning(self, "myass", msg)


_INVALID = object()


# ===== formulário dinâmico de inputs (compartilhado) ==================
def _field_widget(spec: dict):
    """Widget de entrada conforme o tipo declarado (str/int/float → caixa;
    bool → checkbox; list/dict/None → editor JSON)."""
    tipo, default = spec.get("tipo"), spec.get("default")
    if tipo == "bool":
        cb = QCheckBox()
        cb.setChecked(bool(default))
        return cb
    if tipo in ("list", "dict") or tipo is None:
        te = QPlainTextEdit()
        te.setFixedHeight(56)
        te.setPlaceholderText("JSON" if tipo else "valor (JSON ou texto)")
        if default is not None:
            te.setPlainText(json.dumps(default, ensure_ascii=False))
        return te
    le = QLineEdit()
    le.setPlaceholderText(tipo or "")
    if default is not None:
        le.setText(str(default))
    return le


def _collect_form(fields: dict) -> dict:
    """Lê os widgets, coage por tipo e valida obrigatórios. Sobe ValueError."""
    inputs = {}
    for name, (spec, widget) in fields.items():
        tipo, obrig = spec.get("tipo"), spec.get("obrigatorio")
        if isinstance(widget, QCheckBox):
            inputs[name] = widget.isChecked()
            continue
        if isinstance(widget, QPlainTextEdit):
            raw = widget.toPlainText().strip()
            if not raw:
                if obrig:
                    raise ValueError(f"'{name}' é obrigatório")
                continue
            try:
                inputs[name] = json.loads(raw)
            except Exception:  # noqa: BLE001
                if tipo in ("list", "dict"):
                    raise ValueError(f"'{name}': JSON inválido")
                inputs[name] = raw
            continue
        raw = widget.text().strip()
        if not raw:
            if obrig:
                raise ValueError(f"'{name}' é obrigatório")
            continue
        if tipo == "int":
            try:
                inputs[name] = int(raw)
            except ValueError:
                raise ValueError(f"'{name}': esperado int")
        elif tipo == "float":
            try:
                inputs[name] = float(raw)
            except ValueError:
                raise ValueError(f"'{name}': esperado float")
        else:
            inputs[name] = raw
    return inputs


def _client_params_for(catalog: dict):
    """params_for client-side: script_hash → schema de params (do catálogo)."""
    idx = {}
    for b in (catalog or {}).get("bots", []):
        for sm in ((b.get("conteudo") or {}).get("scripts") or {}).values():
            idx[sm.get("script_hash")] = sm.get("params") or {}
    return lambda bot_ref: idx.get((bot_ref or {}).get("script_hash"))


class NewOccurrenceDialog(QDialog):
    """Diálogo de nova ocorrência: escolhe o workflow e o form de inputs é gerado
    do template (tipos do manifesto). Iniciar → ``start_occurrence``."""

    def __init__(self, client, catalog, on_started=None, parent=None):
        super().__init__(parent)
        self.client = client
        self.catalog = catalog or {}
        self.on_started = on_started
        self._fields = {}
        self.setWindowTitle("Nova ocorrência")
        self.resize(560, 460)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Workflow:"))
        self.wf_combo = QComboBox()
        for wf in self.catalog.get("workflows", []):
            self.wf_combo.addItem(f"{wf['nome']}  v{wf['versao']}", wf)
        self.wf_combo.currentIndexChanged.connect(lambda _i: self._build_form())
        top.addWidget(self.wf_combo, 1)
        lay.addLayout(top)
        lay.addWidget(_label("Inputs (gerado do workflow; * = obrigatório):",
                             small=True, gray=True))
        self.form_area = QScrollArea()
        self.form_area.setWidgetResizable(True)
        lay.addWidget(self.form_area)
        self.status = _label("", small=True, gray=True)
        lay.addWidget(self.status)
        btn = QPushButton("Iniciar ocorrência")
        btn.clicked.connect(self._start)
        lay.addWidget(btn)
        self._build_form()

    def _build_form(self):
        wf = self.wf_combo.currentData()
        cont = QWidget()
        form = QFormLayout(cont)
        self._fields = {}
        if not wf:
            form.addRow(_label("(nenhum workflow publicado)", small=True, gray=True))
            self.form_area.setWidget(cont)
            return
        schema = required_inputs(wf.get("conteudo") or {}, _client_params_for(self.catalog))
        if not schema:
            form.addRow(_label("(este workflow não declara inputs)", small=True, gray=True))
        for name, spec in schema.items():
            wgt = _field_widget(spec)
            tipo = spec.get("tipo")
            lbl = name + (" *" if spec.get("obrigatorio") else "") + (f"  [{tipo}]" if tipo else "")
            if spec.get("descricao"):
                wgt.setToolTip(spec["descricao"])
            form.addRow(lbl, wgt)
            self._fields[name] = (spec, wgt)
        self.form_area.setWidget(cont)

    def _start(self):
        wf = self.wf_combo.currentData()
        if not wf:
            self.status.setText("selecione um workflow.")
            return
        try:
            inputs = _collect_form(self._fields)
        except ValueError as e:
            self.status.setText(f"input inválido: {e}")
            return
        try:
            ack = self.client.start_occurrence(wf["hash"], inputs)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"erro: {e}")
            return
        if ack.get("erro"):
            self.status.setText(ack["erro"])
            return
        if self.on_started:
            self.on_started()
        self.accept()


def _find_artifacts(value, out):
    """Coleta arquivos inline ``{"$b64": ..., "nome": ...}`` na saída."""
    if isinstance(value, dict):
        if "$b64" in value:
            out.append((value.get("nome", "arquivo.bin"), value["$b64"]))
            return
        for v in value.values():
            _find_artifacts(v, out)
    elif isinstance(value, list):
        for v in value:
            _find_artifacts(v, out)


def _strip_b64(value):
    """Cópia para exibição com o base64 trocado por um marcador curto."""
    if isinstance(value, dict):
        if "$b64" in value:
            n = len(value["$b64"])
            return {"$b64": f"<{n} bytes base64 — use o botão Salvar>",
                    "nome": value.get("nome")}
        return {k: _strip_b64(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_b64(v) for v in value]
    return value


class PdfViewerDialog(QDialog):
    """Visualizador de PDF embutido (QtPdf), a partir dos bytes do artefato."""

    def __init__(self, data: bytes, nome="documento.pdf", parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QBuffer, QByteArray
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
        self.setWindowTitle("PDF — " + nome)
        self.resize(820, 940)
        lay = QVBoxLayout(self)
        self._buf = QBuffer(self)
        self._buf.setData(QByteArray(data))
        self._buf.open(QBuffer.OpenModeFlag.ReadOnly)
        self._doc = QPdfDocument(self)
        self._doc.load(self._buf)
        view = QPdfView(self)
        view.setDocument(self._doc)
        view.setPageMode(QPdfView.PageMode.MultiPage)
        view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        lay.addWidget(view)


def _walk_named_nodes(node):
    """Itera os nós nomeados (action/decision/loop) — a unidade que ganha status."""
    if isinstance(node, dict):
        if node.get("tipo") in ("action", "decision", "loop") and node.get("nome"):
            yield node
        for v in (node.get("raiz"), node.get("corpo")):
            if v:
                yield from _walk_named_nodes(v)
        for ch in node.get("filhos") or []:
            yield from _walk_named_nodes(ch)
        for sub in (node.get("rotas") or {}).values():
            yield from _walk_named_nodes(sub)


def _iter_errors(obj):
    """Acha dicts em forma de erro (``motivo``/``erro``) em qualquer profundidade."""
    if isinstance(obj, dict):
        msg = obj.get("motivo") or obj.get("erro")
        if msg:
            yield obj
        for v in obj.values():
            yield from _iter_errors(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_errors(v)


def _short_val(v) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 200 else s[:200] + "…"


def _fill_tree(parent, value):
    """Popula um QTreeWidget(Item) recursivamente a partir de um JSON."""
    items = (value.items() if isinstance(value, dict)
             else enumerate(value) if isinstance(value, list) else [])
    for k, v in items:
        key = str(k) if isinstance(value, dict) else f"[{k}]"
        if isinstance(v, (dict, list)):
            n = len(v)
            kind = f"{{{n}}}" if isinstance(v, dict) else f"[{n}]"
            it = QTreeWidgetItem(parent, [key, kind])
            _fill_tree(it, v)
        else:
            QTreeWidgetItem(parent, [key, _short_val(v)])


class OccurrenceDetailDialog(QDialog):
    """Detalhes de uma ocorrência em 4 abas, para humanos:
    **Diagrama** (estrutograma Nassi colorido: verde=feito, amarelo=executando,
    vermelho=falhou), **JSON** (árvore expansível), **Status** (números da
    execução) e **Erros** (texto). Topo: badge de status, botões de artefato
    (Visualizar PDF / Salvar) e **Re-executar** com os mesmos inputs."""

    def __init__(self, info: dict, resolve=None, client=None, on_rerun=None, parent=None):
        super().__init__(parent)
        self._info = info
        self._client = client
        self._on_rerun = on_rerun
        oid = info.get("occurrence_id", "?")
        self.setWindowTitle(f"Ocorrência — {oid}")
        self.resize(860, 680)
        lay = QVBoxLayout(self)
        wf = info.get("workflow") or {}

        # ---- cabeçalho: id + workflow + badge + ações --------------------
        self._resolve = resolve
        head = QHBoxLayout()
        idcol = QVBoxLayout()
        idcol.addWidget(_label(oid, bold=True))
        idcol.addWidget(_label(f"workflow: {wf.get('nome')} v{wf.get('versao')}", small=True))
        head.addLayout(idcol)
        self._badge = QLabel()
        self._set_badge(info.get("status"))
        head.addWidget(self._badge)
        head.addStretch(1)
        # Botão Update: só aparece enquanto a ocorrência está em execução —
        # re-busca o detalhe no núcleo e redesenha as abas (status muda no tempo).
        self._btn_update = QPushButton("↻ Update")
        self._btn_update.clicked.connect(self._update)
        self._btn_update.setVisible(client is not None and info.get("status") == "running")
        head.addWidget(self._btn_update)
        # V — re-executar com os mesmos inputs (precisa de client + template_hash).
        if client is not None and info.get("template_hash"):
            brer = QPushButton("↻ Re-executar (mesmos inputs)")
            brer.clicked.connect(self._rerun)
            head.addWidget(brer)
        lay.addLayout(head)

        # Corpo (artefatos + abas), reconstruído a cada Update.
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._body)
        self._render_body()

    def _set_badge(self, st):
        color = _STATUS_COLORS.get(st, "#dddddd")
        self._badge.setText(f"  {st}  ")
        self._badge.setStyleSheet(f"QLabel {{ background:{color}; border:1px solid #888;"
                                  " border-radius:3px; }")

    @staticmethod
    def _clear_layout(lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                OccurrenceDetailDialog._clear_layout(it.layout())

    def _render_body(self):
        """(Re)constrói os botões de artefato + as 4 abas a partir de ``self._info``,
        preservando a aba selecionada."""
        info = self._info
        prev = getattr(self, "_tabs", None)
        keep = prev.currentIndex() if prev is not None else 0
        self._clear_layout(self._body_lay)

        artifacts = []
        _find_artifacts(info.get("result"), artifacts)
        for nome, b64 in artifacts:
            row = QHBoxLayout()
            if str(nome).lower().endswith(".pdf"):
                bview = QPushButton(f"Visualizar {nome}")
                bview.clicked.connect(lambda _c=False, n=nome, b=b64: self._view(n, b))
                row.addWidget(bview)
            bsave = QPushButton(f"Salvar {nome}…")
            bsave.clicked.connect(lambda _c=False, n=nome, b=b64: self._save(n, b))
            row.addWidget(bsave)
            row.addStretch(1)
            self._body_lay.addLayout(row)

        tabs = QTabWidget()
        tabs.addTab(self._tab_diagram(info, self._resolve), "Diagrama")
        tabs.addTab(self._tab_json(info), "JSON (árvore)")
        tabs.addTab(self._tab_stats(info), "Status")
        tabs.addTab(self._tab_errors(info), "Erros")
        tabs.setCurrentIndex(keep)
        self._tabs = tabs
        self._body_lay.addWidget(tabs)

    def _update(self):
        """Re-busca o detalhe da ocorrência no núcleo e redesenha (p/ ``running``)."""
        try:
            new = self._client.get_occurrence(self._info.get("occurrence_id"))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "myass", f"erro ao atualizar: {e}")
            return
        if new.get("erro"):
            QMessageBox.warning(self, "myass", new["erro"])
            return
        # o workflow não muda: preserva o template se o detalhe novo não o trouxer.
        if not new.get("template") and self._info.get("template"):
            new["template"] = self._info["template"]
        self._info = new
        self._set_badge(new.get("status"))
        self._btn_update.setVisible(new.get("status") == "running")
        self._render_body()

    # ---- I — diagrama Nassi colorido por status -----------------------
    def _tab_diagram(self, info, resolve):
        w = QWidget()
        v = QVBoxLayout(w)
        legend = QHBoxLayout()
        for txt, key in (("feito", "done"), ("executando", "running"), ("falhou", "failed")):
            tag = QLabel(f"  {txt}  ")
            tag.setStyleSheet(f"QLabel {{ background:{_STATUS_COLORS[key]};"
                              " border:1px solid #888; border-radius:3px; }")
            legend.addWidget(tag)
        legend.addStretch(1)
        v.addLayout(legend)
        tmpl = info.get("template")
        if not tmpl:
            v.addWidget(_label("(núcleo antigo: sem template no detalhe)", gray=True))
            return w
        ns = info.get("node_status") or {}
        diag = nassi_widget(tmpl, resolve or (lambda h: ""), ["raiz"],
                            status_of=lambda node: ns.get(node.get("nome")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(diag)
        v.addWidget(scroll)
        return w

    # ---- II — JSON em árvore expansível -------------------------------
    def _tab_json(self, info):
        tree = QTreeWidget()
        tree.setHeaderLabels(["chave", "valor"])
        tree.setColumnWidth(0, 280)
        data = {
            "status": info.get("status"),
            "inputs": info.get("inputs"),
            "result": _strip_b64(info.get("result")),
            "node_outputs": _strip_b64(info.get("node_outputs")),
            "fail": info.get("fail"),
            "node_status": info.get("node_status"),
        }
        _fill_tree(tree, data)
        tree.expandToDepth(0)
        return tree

    # ---- III — números da execução ------------------------------------
    def _tab_stats(self, info):
        w = QWidget()
        form = QFormLayout(w)
        ns = info.get("node_status") or {}
        total = sum(1 for _ in _walk_named_nodes(info.get("template") or {}))
        done = sum(1 for s in ns.values() if s == "done")
        running = sum(1 for s in ns.values() if s == "running")
        failed = sum(1 for s in ns.values() if s == "failed")
        artifacts = []
        _find_artifacts(info.get("result"), artifacts)
        n_err = sum(1 for _ in _iter_errors(info.get("node_outputs"))) + \
            (1 if info.get("fail") else 0)
        pct = f"{(100 * done / total):.0f}%" if total else "—"
        rows = [
            ("Ocorrência", info.get("occurrence_id", "?")),
            ("Status", info.get("status", "?")),
            ("Workflow", f"{(info.get('workflow') or {}).get('nome')} "
                         f"v{(info.get('workflow') or {}).get('versao')}"),
            ("Atividades (total)", str(total)),
            ("Concluídas", f"{done}  ({pct})"),
            ("Em execução", str(running)),
            ("Falhas", str(failed)),
            ("Artefatos no resultado", str(len(artifacts))),
            ("Erros registrados", str(n_err)),
            ("Tem resultado final", "sim" if info.get("result") is not None else "não"),
        ]
        for k, val in rows:
            form.addRow(_label(k + ":", bold=True), _label(str(val)))
        return w

    # ---- IV — todos os erros em texto ---------------------------------
    def _tab_errors(self, info):
        lines = []
        fail = info.get("fail")
        if fail:
            nm = fail.get("_node")
            lines.append(f"[FALHA DA OCORRÊNCIA] {('nó ' + nm + ': ') if nm else ''}"
                         f"{fail.get('motivo', '')}".rstrip())
            lines.append(json.dumps(_strip_b64(fail), ensure_ascii=False, indent=2))
            lines.append("")
        for name, out in (info.get("node_outputs") or {}).items():
            for err in _iter_errors(out):
                nm = err.get("_node") or name
                lines.append(f"[{nm}] {err.get('motivo') or err.get('erro')}")
        body = QPlainTextEdit("\n".join(lines).rstrip() if lines
                              else "Sem erros registrados.")
        body.setReadOnly(True)
        return body

    # ---- V — re-executar ----------------------------------------------
    def _rerun(self):
        th = self._info.get("template_hash")
        inputs = self._info.get("inputs") or {}
        try:
            ack = self._client.start_occurrence(th, inputs)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "myass", f"erro ao re-executar: {e}")
            return
        if ack.get("erro"):
            QMessageBox.warning(self, "myass", f"rejeitado: {ack['erro']}")
            return
        new_oid = ack.get("occurrence_id", "?")
        if self._on_rerun:
            self._on_rerun()
        QMessageBox.information(self, "myass", f"nova ocorrência: {new_oid}")

    def _view(self, nome, b64):
        try:
            data = base64.b64decode(b64)
            PdfViewerDialog(data, nome, parent=self).exec()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "myass", f"não foi possível abrir o PDF: {e}")

    def _save(self, nome, b64):
        path, _ = QFileDialog.getSaveFileName(self, "Salvar arquivo", nome)
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "myass", f"erro ao salvar: {e}")
            return
        QMessageBox.information(self, "myass", f"salvo: {path}")


class ClientKeyDialog(QDialog):
    """Criar/editar uma chave de cliente da web: nome + seleção de workflows que a
    chave pode ver/executar. Ao criar, o núcleo gera o segredo e publica o catálogo
    selado; o segredo é exibido para distribuir. Ao editar, atualiza os workflows
    (o núcleo republica o catálogo)."""

    def __init__(self, client: dict | None, workflows: list, admin, parent=None):
        super().__init__(parent)
        self._client = client
        self._admin = admin
        editing = client is not None
        self.setWindowTitle("Editar chave" if editing else "Nova chave")
        self.resize(540, 500)
        lay = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(client["name"] if editing else "")
        self.name_edit.setReadOnly(editing)
        form.addRow("Nome:", self.name_edit)
        self.secret_edit = QLineEdit(client.get("secret", "") if editing else "")
        self.secret_edit.setReadOnly(True)
        self.secret_edit.setPlaceholderText("(gerada ao criar)")
        secret_row = QWidget()
        sr = QHBoxLayout(secret_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(self.secret_edit)
        self.copy_btn = QPushButton("Copiar nome.chave")
        self.copy_btn.clicked.connect(self._copy_namekey)
        sr.addWidget(self.copy_btn)
        form.addRow("Chave (hex):", secret_row)
        lay.addLayout(form)

        lay.addWidget(_label("Workflows que esta chave pode ver/executar:", bold=True))
        allowed = client.get("workflows") if editing else None  # None = todos (legado)
        self.wf_tree = QTreeWidget()
        self.wf_tree.setHeaderLabels(["workflow", "versão", "hash"])
        for wdef in workflows:
            h = wdef["hash"]
            it = QTreeWidgetItem([wdef.get("nome", wdef.get("label", "?")),
                                  str(wdef.get("versao", "")), _short(h)])
            it.setData(0, Qt.ItemDataRole.UserRole, h)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # editar: marca os permitidos (allowed None = todos). novo: desmarcado.
            chk = editing and (allowed is None or h in (allowed or []))
            it.setCheckState(0, Qt.CheckState.Checked if chk else Qt.CheckState.Unchecked)
            self.wf_tree.addTopLevelItem(it)
        lay.addWidget(self.wf_tree)

        row = QHBoxLayout()
        row.addStretch(1)
        self.save_btn = QPushButton("Salvar" if editing else "Criar")
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        lay.addLayout(row)
        self.status = QLabel("")
        lay.addWidget(self.status)

    def _copy_namekey(self):
        """Copia ``nome.chave`` (nome + segredo hex) para a área de transferência."""
        name = self.name_edit.text().strip()
        secret = self.secret_edit.text().strip()
        if not secret:
            self.status.setText("ainda não há chave — crie/salve primeiro.")
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(f"{name}.{secret}")
        self.status.setText("nome.chave copiado para a área de transferência.")

    def _selected(self) -> list:
        out = []
        for i in range(self.wf_tree.topLevelItemCount()):
            it = self.wf_tree.topLevelItem(i)
            if it.checkState(0) == Qt.CheckState.Checked:
                out.append(it.data(0, Qt.ItemDataRole.UserRole))
        return out

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            self.status.setText("informe um nome para a chave.")
            return
        wfs = self._selected()
        editing = self._client is not None
        try:
            ack = (self._admin.update_client(name, wfs) if editing
                   else self._admin.create_client(name, wfs))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "myass", f"erro: {e}")
            return
        if ack.get("erro"):
            self.status.setText("erro: " + ack["erro"])
            return
        if not editing and ack.get("secret"):
            self.secret_edit.setText(ack["secret"])
            QMessageBox.information(
                self, "myass",
                "Chave criada. Copie e entregue ao usuário (não some depois):\n\n"
                + ack["secret"])
        self.accept()


class AdminWindow(QWidget):
    """Janela principal. ``client`` é um ``AdminClient`` (pode vir None p/ smoke)."""

    def __init__(self, client=None):
        super().__init__()
        self.client = client
        self.setWindowTitle("myass — Painel do administrador")
        self.resize(820, 560)
        self._last_catalog = {}
        self._script_index = {}
        self._palette = []
        self._bots = []

        tabs = QTabWidget()
        # Ocorrências e Catálogo primeiro: é com workflows/ocorrências que se opera;
        # publicar e ambiente são tarefas de bastidor.
        tabs.addTab(self._tab_ocorrencias(), "Ocorrências")
        tabs.addTab(self._tab_catalogo(), "Catálogo")
        tabs.addTab(self._tab_chaves(), "Chaves")
        tabs.addTab(self._tab_publicar(), "Publicar")
        tabs.addTab(self._tab_ambiente(), "Ambiente")
        self._tabs = tabs
        # Entrar numa aba já a atualiza (sem clicar "Atualizar").
        tabs.currentChanged.connect(self._on_tab_changed)

        self.status = QLabel("Pronto.")
        root = QVBoxLayout(self)
        root.addWidget(tabs)
        root.addWidget(self.status)

        self._refresh_drafts()
        # Auto-atualiza tudo ao abrir o painel — adiado para depois do 1º paint,
        # para a janela já aparecer responsiva enquanto os dados chegam.
        QTimer.singleShot(0, self._refresh_all)

    def _on_tab_changed(self, idx: int):
        {0: self._refresh_occurrences, 1: self._refresh_catalog,
         2: self._refresh_clients, 4: self._refresh_env}.get(idx, lambda: None)()

    def _refresh_all(self):
        """Carrega catálogo (+paleta), ocorrências, chaves e ambiente de uma vez.
        No-op sem conexão (cada _refresh_* já protege com _guard)."""
        if self.client is None:
            return
        self._refresh_catalog()
        self._refresh_occurrences()
        self._refresh_clients()
        self._refresh_env()

    # ---- abas ----------------------------------------------------------
    def _tab_publicar(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Publicar BOT (diretório do projeto):"))
        row = QHBoxLayout()
        self.bot_dir = QLineEdit()
        btn_browse = QPushButton("Escolher…")
        btn_browse.clicked.connect(self._pick_bot_dir)
        btn_pub_bot = QPushButton("Publicar BOT")
        btn_pub_bot.clicked.connect(self._publish_bot)
        row.addWidget(self.bot_dir)
        row.addWidget(btn_browse)
        row.addWidget(btn_pub_bot)
        lay.addLayout(row)
        lay.addWidget(QLabel("Publicar Workflow (JSON do template):"))
        self.wf_json = QPlainTextEdit()
        self.wf_json.setPlaceholderText('{"nome": "...", "versao": "1", "raiz": {...}}')
        lay.addWidget(self.wf_json)
        btn_pub_wf = QPushButton("Publicar Workflow")
        btn_pub_wf.clicked.connect(self._publish_workflow)
        lay.addWidget(btn_pub_wf)
        return w

    def _tab_catalogo(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        btn = QPushButton("Atualizar catálogo")
        btn.clicked.connect(self._refresh_catalog)
        lay.addWidget(btn)
        lay.addWidget(_label("Em Produção (duplo-clique → Tela de Workflow):",
                             bold=True))
        self.catalog_tree = QTreeWidget()
        self.catalog_tree.setHeaderLabels(["workflow", "versão", "hash"])
        self.catalog_tree.itemDoubleClicked.connect(self._open_workflow)
        lay.addWidget(self.catalog_tree)

        row = QHBoxLayout()
        btn_new = QPushButton("Novo workflow (rascunho)")
        btn_new.clicked.connect(self._new_workflow)
        btn_rd = QPushButton("Atualizar rascunhos")
        btn_rd.clicked.connect(self._refresh_drafts)
        row.addWidget(btn_new)
        row.addWidget(btn_rd)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_label("Em edição — rascunhos locais (duplo-clique → editar):",
                             bold=True))
        self.drafts_tree = QTreeWidget()
        self.drafts_tree.setHeaderLabels(["rascunho", "versão", "estado"])
        self.drafts_tree.itemDoubleClicked.connect(self._open_draft)
        lay.addWidget(self.drafts_tree)
        return w

    def _tab_ocorrencias(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        btn_new = QPushButton("Nova ocorrência…")
        btn_new.clicked.connect(self._new_occurrence)
        btn_refresh = QPushButton("Atualizar")
        btn_refresh.clicked.connect(self._refresh_occurrences)
        row.addWidget(btn_new)
        row.addWidget(btn_refresh)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_label("Ocorrências (duplo-clique → detalhes):", small=True, gray=True))
        self.occ_tree = QTreeWidget()
        self.occ_tree.setHeaderLabels(["ocorrência", "workflow", "status"])
        self.occ_tree.itemDoubleClicked.connect(self._open_occurrence)
        lay.addWidget(self.occ_tree)
        return w

    def _new_occurrence(self):
        if not self._guard():
            return
        self._ensure_palette()
        if not self._last_catalog:
            try:
                self._last_catalog = self.client.catalog()
                self._build_palette(self._last_catalog)
            except Exception as e:  # noqa: BLE001
                self.status.setText(f"erro: {e}")
                return
        NewOccurrenceDialog(self.client, self._last_catalog,
                            on_started=self._refresh_occurrences, parent=self).exec()
        self._refresh_occurrences()

    def _open_occurrence(self, item, _col=0):
        if not self._guard():
            return
        oid = item.data(0, Qt.ItemDataRole.UserRole) or item.text(0)
        try:
            info = self.client.get_occurrence(oid)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"erro: {e}")
            return
        if info.get("erro"):
            self.status.setText(info["erro"])
            return
        self._ensure_palette()  # garante o índice script_hash→nome p/ rotular o diagrama
        # Fallback: se o núcleo não enviou o template no detalhe, pega o do
        # catálogo (o ``conteudo`` do workflow publicado é o próprio template) —
        # assim a aba Diagrama desenha todas as tasks mesmo contra núcleo antigo.
        if not info.get("template"):
            th, wf = info.get("template_hash"), info.get("workflow") or {}
            for w in (self._last_catalog or {}).get("workflows", []):
                if w.get("hash") == th or (w.get("nome") == wf.get("nome")
                                           and str(w.get("versao")) == str(wf.get("versao"))):
                    info = {**info, "template": w.get("conteudo")}
                    break
        OccurrenceDetailDialog(info, resolve=self._resolve(), client=self.client,
                               on_rerun=self._refresh_occurrences, parent=self).exec()

    # ---- aba Chaves (criar/editar chaves de cliente da web) -----------
    def _tab_chaves(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        b_new = QPushButton("Nova chave…")
        b_new.clicked.connect(self._new_client)
        b_ref = QPushButton("Atualizar")
        b_ref.clicked.connect(self._refresh_clients)
        row.addWidget(b_new)
        row.addWidget(b_ref)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_label("Chaves de cliente (duplo-clique → editar workflows):",
                             small=True, gray=True))
        self.clients_tree = QTreeWidget()
        self.clients_tree.setHeaderLabels(["nome", "workflows", "chave (hex)"])
        self.clients_tree.setColumnWidth(0, 160)
        self.clients_tree.itemDoubleClicked.connect(self._edit_client)
        lay.addWidget(self.clients_tree)
        return w

    def _refresh_clients(self):
        if not self._guard():
            return
        self.clients_tree.clear()
        for c in self.client.list_clients():
            wf = c.get("workflows")
            qtd = "todos" if wf is None else str(len(wf))
            it = QTreeWidgetItem([c.get("name", c["client_id"]), qtd, c.get("secret", "")])
            it.setData(0, Qt.ItemDataRole.UserRole, c)
            self.clients_tree.addTopLevelItem(it)

    def _new_client(self):
        if not self._guard():
            return
        self._ensure_palette()
        ClientKeyDialog(None, (self._last_catalog or {}).get("workflows", []),
                        self.client, parent=self).exec()
        self._refresh_clients()

    def _edit_client(self, item, _col=0):
        if not self._guard():
            return
        self._ensure_palette()
        c = item.data(0, Qt.ItemDataRole.UserRole)
        ClientKeyDialog(c, (self._last_catalog or {}).get("workflows", []),
                        self.client, parent=self).exec()
        self._refresh_clients()

    def _tab_ambiente(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.env_tree = QTreeWidget()
        self.env_tree.setHeaderLabels(["block", "perfil", "capacidades"])
        btn = QPushButton("Atualizar ambiente")
        btn.clicked.connect(self._refresh_env)
        lay.addWidget(btn)
        lay.addWidget(self.env_tree)
        return w

    # ---- ações (todas tolerantes a client=None / erros) ---------------
    def _guard(self):
        if self.client is None:
            self.status.setText("Sem conexão (client não configurado).")
            return False
        return True

    def _pick_bot_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Diretório do BOT")
        if d:
            self.bot_dir.setText(d)

    def _publish_bot(self):
        if not self._guard():
            return
        try:
            ack = self.client.publish_bot_dir(self.bot_dir.text())
            self.status.setText(f"BOT: {ack.get('status')} {ack.get('hash', ack.get('motivo', ''))}")
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"erro: {e}")

    def _publish_workflow(self):
        if not self._guard():
            return
        try:
            ack = self.client.publish_workflow(json.loads(self.wf_json.toPlainText()))
            self.status.setText(f"Workflow: {ack.get('status')} {ack.get('hash', ack.get('motivo', ''))}")
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"erro: {e}")

    def _build_palette(self, cat):
        self._script_index = {}
        self._palette = []
        self._bots = []  # [{"nome", "project_hash", "scripts":[{"nome","script_hash"}]}]
        for b in cat.get("bots", []):
            scripts = (b.get("conteudo") or {}).get("scripts") or {}
            bot = {"nome": b["nome"], "project_hash": b["hash"], "scripts": []}
            for sname, smeta in scripts.items():
                label = f"{b['nome']}/{sname}"
                self._script_index[smeta.get("script_hash")] = label
                self._palette.append({"label": label, "bot_ref": {
                    "project_hash": b["hash"], "script_hash": smeta.get("script_hash")}})
                bot["scripts"].append({"nome": sname, "script_hash": smeta.get("script_hash")})
            self._bots.append(bot)

    def _refresh_catalog(self):
        if not self._guard():
            return
        self.catalog_tree.clear()
        cat = self.client.catalog()
        self._last_catalog = cat
        self._build_palette(cat)
        # Só workflows: é a unidade que se opera. BOTs/scripts são paleta de autoria.
        for w in cat.get("workflows", []):
            it = QTreeWidgetItem([w["nome"], w["versao"], w["hash"]])
            it.setData(0, Qt.ItemDataRole.UserRole, w)
            self.catalog_tree.addTopLevelItem(it)
        self.catalog_tree.expandAll()

    def _refresh_drafts(self):
        self.drafts_tree.clear()
        for d in list_drafts():
            it = QTreeWidgetItem([d.get("nome", "?"), d.get("versao", ""), "Em edição"])
            it.setData(0, Qt.ItemDataRole.UserRole, d)
            self.drafts_tree.addTopLevelItem(it)

    def _resolve(self):
        return lambda h: self._script_index.get(h, "")

    def _ensure_palette(self):
        """Carrega a paleta de scripts (do catálogo) se ainda não houver — para o
        combo de script da Tela de Workflow já abrir com os nomes resolvidos."""
        if self._palette or self.client is None:
            return
        try:
            cat = self.client.catalog()
            self._last_catalog = cat
            self._build_palette(cat)
        except Exception:  # noqa: BLE001
            pass

    def _open_workflow(self, item, _col=0):
        w = item.data(0, Qt.ItemDataRole.UserRole)
        if not w:
            return
        self._ensure_palette()
        WorkflowWindow(nome=w["nome"], versao=w["versao"], estado="em_producao",
                       template=copy.deepcopy(w.get("conteudo") or {}),
                       client=self.client, resolve=self._resolve(), palette=self._palette,
                       bots=self._bots, on_change=self._refresh_drafts, parent=self).show()

    def _open_draft(self, item, _col=0):
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if not d:
            return
        self._ensure_palette()
        WorkflowWindow(nome=d["nome"], versao=d["versao"], estado="em_edicao",
                       template=d.get("template") or {}, client=self.client,
                       resolve=self._resolve(), palette=self._palette, bots=self._bots,
                       on_change=self._refresh_drafts, parent=self).show()

    def _new_workflow(self):
        nome, ok = QInputDialog.getText(self, "Novo workflow", "Nome:")
        if not ok or not nome.strip():
            return
        ver, ok = QInputDialog.getText(self, "Novo workflow", "Versão:", text="0.1")
        if not ok or not ver.strip():
            return
        tmpl = {"template_version": 1, "nome": nome.strip(), "versao": ver.strip(),
                "tipo": "workflow", "raiz": {"tipo": "block", "filhos": []}}
        save_draft(nome.strip(), ver.strip(), tmpl)
        self._refresh_drafts()
        WorkflowWindow(nome=nome.strip(), versao=ver.strip(), estado="em_edicao",
                       template=tmpl, client=self.client, resolve=self._resolve(),
                       palette=self._palette, bots=self._bots,
                       on_change=self._refresh_drafts, parent=self).show()

    def _refresh_occurrences(self):
        if not self._guard():
            return
        self.occ_tree.clear()
        for o in self.client.list_occurrences():
            it = QTreeWidgetItem([o["occurrence_id"], o.get("workflow", ""), o["status"]])
            it.setData(0, Qt.ItemDataRole.UserRole, o["occurrence_id"])
            self.occ_tree.addTopLevelItem(it)

    def _refresh_env(self):
        if not self._guard():
            return
        self.env_tree.clear()
        for b in self.client.environment().get("blocks", []):
            self.env_tree.addTopLevelItem(QTreeWidgetItem([
                b["block"], json.dumps(b.get("profile")), json.dumps(b.get("capabilities"))]))


def main(client=None) -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    win = AdminWindow(client)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
