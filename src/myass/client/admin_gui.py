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

from PySide6.QtCore import Qt
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
                 on_select=None, selected=None) -> QWidget:
    """Widget do estrutograma para ``node`` (em ``path``). ``resolve(script_hash)
    -> 'bot/script'`` rotula as ações; ``on_select(path)`` torna os nós clicáveis."""
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
                                     on_select, selected))
        return holder

    if tipo == "action":
        box = _node_box(_NASSI_COLORS["action"], path, on_select, selected)
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
        box = _node_box(_NASSI_COLORS["loop"], path, on_select, selected)
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
            hb.addWidget(nassi_widget(corpo, resolve, path + ["corpo"], on_select, selected))
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
        box = _node_box(_NASSI_COLORS["decision"], path, on_select, selected)
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
                                      on_select, selected))
            cv.addStretch(1)
            hb.addWidget(col)
        v.addWidget(cols)
        for cl in _catch_lines(node):
            v.addWidget(_label(cl, small=True, gray=True))
        return box

    if "raiz" in node:
        return nassi_widget(node["raiz"], resolve, ["raiz"], on_select, selected)
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


class OccurrenceDetailDialog(QDialog):
    """Detalhes de uma ocorrência (curados pelo núcleo): status, workflow,
    inputs, resultado/falha e saídas por nó. Arquivos inline (``$b64``) ganham
    botões **Visualizar** (PDF, embutido) e **Salvar**."""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        oid = info.get("occurrence_id", "?")
        self.setWindowTitle(f"Ocorrência — {oid}")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        wf = info.get("workflow") or {}
        lay.addWidget(_label(oid, bold=True))
        lay.addWidget(_label(f"workflow: {wf.get('nome')} v{wf.get('versao')}"))
        st = info.get("status")
        badge = QLabel(f"  {st}  ")
        color = {"done": "#cdebd3", "failed": "#f5c6c6",
                 "running": "#fde2b3"}.get(st, "#dddddd")
        badge.setStyleSheet(f"QLabel {{ background:{color}; border:1px solid #888;"
                            " border-radius:3px; }")
        lay.addWidget(badge)

        # botões por arquivo inline (Visualizar PDF embutido + Salvar).
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
            lay.addLayout(row)

        body = QPlainTextEdit(json.dumps({
            "inputs": info.get("inputs"),
            "result": _strip_b64(info.get("result")),
            "fail": info.get("fail"),
            "node_outputs": _strip_b64(info.get("node_outputs")),
        }, ensure_ascii=False, indent=2))
        body.setReadOnly(True)
        lay.addWidget(body)

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
        tabs.addTab(self._tab_publicar(), "Publicar")
        tabs.addTab(self._tab_ambiente(), "Ambiente")

        self.status = QLabel("Pronto.")
        root = QVBoxLayout(self)
        root.addWidget(tabs)
        root.addWidget(self.status)

        self._refresh_drafts()

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
        OccurrenceDetailDialog(info, parent=self).exec()

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
