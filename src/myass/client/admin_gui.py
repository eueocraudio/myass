"""Painel do administrador — GUI PySide6 (Parte I, apresentação).

App desktop sobre o ``AdminClient``: publicar BOTs/workflows, ler o catálogo,
iniciar e acompanhar ocorrências, e ver o ambiente (o que o enunciado pede para a
Parte I). A autoria de workflow aqui é por **JSON do template** (gerado pelo
``build.py`` do BOT ou editado à mão); o **canvas Nassi gráfico** (QGraphicsView)
é a camada de refinamento visual prevista em CLAUDE.md, montável por cima destas
mesmas chamadas.

Importar o módulo não cria ``QApplication`` (só ``main()``/instanciar a janela),
para permitir smoke test sem display.
"""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


class AdminWindow(QWidget):
    """Janela principal. ``client`` é um ``AdminClient`` (pode vir None p/ smoke)."""

    def __init__(self, client=None):
        super().__init__()
        self.client = client
        self.setWindowTitle("myass — Painel do administrador")
        self.resize(820, 560)

        tabs = QTabWidget()
        tabs.addTab(self._tab_publicar(), "Publicar")
        tabs.addTab(self._tab_catalogo(), "Catálogo")
        tabs.addTab(self._tab_ocorrencias(), "Ocorrências")
        tabs.addTab(self._tab_ambiente(), "Ambiente")

        self.status = QLabel("Pronto.")
        root = QVBoxLayout(self)
        root.addWidget(tabs)
        root.addWidget(self.status)

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
        self.catalog_tree = QTreeWidget()
        self.catalog_tree.setHeaderLabels(["nome", "versão", "hash"])
        btn = QPushButton("Atualizar catálogo")
        btn.clicked.connect(self._refresh_catalog)
        lay.addWidget(btn)
        lay.addWidget(self.catalog_tree)
        return w

    def _tab_ocorrencias(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.start_wf = QLineEdit()
        self.start_wf.setPlaceholderText("workflow_hash")
        self.start_inputs = QLineEdit()
        self.start_inputs.setPlaceholderText('inputs JSON, ex. {"texto": "..."}')
        btn_start = QPushButton("Iniciar ocorrência")
        btn_start.clicked.connect(self._start_occurrence)
        row.addWidget(self.start_wf)
        row.addWidget(self.start_inputs)
        row.addWidget(btn_start)
        lay.addLayout(row)
        self.occ_tree = QTreeWidget()
        self.occ_tree.setHeaderLabels(["ocorrência", "status"])
        btn_refresh = QPushButton("Atualizar ocorrências")
        btn_refresh.clicked.connect(self._refresh_occurrences)
        lay.addWidget(btn_refresh)
        lay.addWidget(self.occ_tree)
        return w

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
            self.status.setText(f"BOT: {ack.get('status')} {ack.get('hash', ack.get('motivo',''))}")
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"erro: {e}")

    def _publish_workflow(self):
        if not self._guard():
            return
        try:
            ack = self.client.publish_workflow(json.loads(self.wf_json.toPlainText()))
            self.status.setText(f"Workflow: {ack.get('status')} {ack.get('hash', ack.get('motivo',''))}")
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"erro: {e}")

    def _refresh_catalog(self):
        if not self._guard():
            return
        self.catalog_tree.clear()
        cat = self.client.catalog()
        for grupo, itens in (("bots", cat.get("bots", [])), ("workflows", cat.get("workflows", []))):
            top = QTreeWidgetItem([grupo, "", ""])
            for it in itens:
                top.addChild(QTreeWidgetItem([it["nome"], it["versao"], it["hash"]]))
            self.catalog_tree.addTopLevelItem(top)
        self.catalog_tree.expandAll()

    def _start_occurrence(self):
        if not self._guard():
            return
        try:
            inputs = json.loads(self.start_inputs.text() or "{}")
            ack = self.client.start_occurrence(self.start_wf.text(), inputs)
            self.status.setText(f"Ocorrência: {ack}")
            self._refresh_occurrences()
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"erro: {e}")

    def _refresh_occurrences(self):
        if not self._guard():
            return
        self.occ_tree.clear()
        for o in self.client.list_occurrences():
            self.occ_tree.addTopLevelItem(
                QTreeWidgetItem([o["occurrence_id"], o["status"]]))

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
