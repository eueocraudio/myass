"""Registro de publicação — o muro que dá legitimidade (substitui o sandbox).

Hash dá integridade; o registro dá **legitimidade** (ver *Publicação e autorização*
em CLAUDE.md). Coleção append-only no MongoDB, espelhada na auditoria. A Rainha só
agenda `bot_ref` aprovado (`project_hash` ativo **e** `script_hash` no manifesto
registrado), e o vínculo `(nome, versao) → hash` é **imutável**.

O núcleo **revalida tudo ao receber** (o cliente não se confia, mesmo sendo do
dono): recomputa a árvore do tar contra o `project_hash` alegado, confere o
manifesto (cada `script_hash` × arquivo, entrypoints existem, requirements com
hashes), e a imutabilidade de `(nome, versao)`. Tudo ok → GridFS + registro +
auditoria; qualquer falha → rejeição integral.
"""

from __future__ import annotations

import shutil
import tempfile
import time

from ..executor import project as proj
from ..workflow.template import canonical, template_hash

STATUS_ATIVO = "ativo"
STATUS_REVOGADO = "revogado"


class PublishError(Exception):
    pass


class PublishRegistry:
    def __init__(self, db, blobs):
        self.pubs = db["publications"]      # {_id: hash, tipo, nome, versao, ...}
        self.names = db["publish_names"]    # {_id: "tipo:nome:versao", hash}
        self.audit = db["publish_audit"]
        self.blobs = blobs                  # BlobStore (GridFS): tar de projeto / template

    # ---- publicação de BOT --------------------------------------------
    def publish_bot(self, tar_bytes: bytes, publicado_por: str) -> str:
        tmp = tempfile.mkdtemp(prefix="myass-publish-")
        try:
            proj.extract(tar_bytes, tmp)            # extração defensiva
            project_hash = proj.tree_hash(tmp)      # recomputa a árvore
            manifest = proj.read_manifest(tmp)
            self._validate_manifest(tmp, manifest)
            nome, versao = manifest["nome"], manifest["versao"]
            self._check_immutable("bot", nome, versao, project_hash)

            self.blobs.put(project_hash, tar_bytes)  # lastro durável (GridFS)
            self._record("bot", project_hash, nome, versao, manifest, publicado_por)
            return project_hash
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _validate_manifest(self, project_dir: str, manifest: dict) -> None:
        scripts = manifest.get("scripts") or {}
        if not scripts:
            raise PublishError("manifesto sem scripts")
        import os
        for nome, meta in scripts.items():
            entry = meta.get("entrypoint")
            full = os.path.join(project_dir, entry or "")
            if not entry or not os.path.isfile(full):
                raise PublishError(f"entrypoint inexistente: {nome} -> {entry}")
            if proj.file_hash(full) != meta.get("script_hash"):
                raise PublishError(f"script_hash não confere: {nome}")
        for pkg, spec in (manifest.get("requirements") or {}).items():
            if not any(h.startswith("sha256:") for h in spec.get("hashes", [])):
                raise PublishError(f"requirement sem hash sha256: {pkg}")

    # ---- publicação de WORKFLOW ---------------------------------------
    def publish_workflow(self, template: dict, publicado_por: str) -> str:
        th = template_hash(template)
        nome = template.get("nome")
        versao = template.get("versao")
        if not nome or not versao:
            raise PublishError("template sem nome/versao")
        self._validate_workflow_refs(template)
        self._check_immutable("workflow", nome, versao, th)
        self.blobs.put(th, canonical(template).encode("utf-8"))
        self._record("workflow", th, nome, versao, template, publicado_por)
        return th

    def _validate_workflow_refs(self, template: dict) -> None:
        """Todo bot_ref do template tem de estar aprovado (project ativo + script
        no manifesto registrado)."""
        for bot_ref in _iter_bot_refs(template.get("raiz", {})):
            if not self.is_approved(bot_ref):
                raise PublishError(f"bot_ref não aprovado: {bot_ref}")

    # ---- aprovação / catálogo -----------------------------------------
    def is_approved(self, bot_ref: dict) -> bool:
        doc = self.pubs.find_one({"_id": bot_ref.get("project_hash"),
                                  "tipo": "bot", "status": STATUS_ATIVO})
        if not doc:
            return False
        sh = bot_ref.get("script_hash")
        return any(m.get("script_hash") == sh
                   for m in (doc["conteudo"].get("scripts") or {}).values())

    def exigencia_for(self, bot_ref: dict) -> dict | None:
        """Exigência de hardware (MEM/CPU) do script — alimenta o roteamento do
        broker quando o motor enfileira a atividade."""
        doc = self.pubs.find_one({"_id": bot_ref.get("project_hash"),
                                  "tipo": "bot", "status": STATUS_ATIVO})
        if not doc:
            return None
        for m in (doc["conteudo"].get("scripts") or {}).values():
            if m.get("script_hash") == bot_ref.get("script_hash"):
                return m.get("exigencia")
        return None

    def params_for(self, bot_ref: dict) -> dict | None:
        """Schema de params do script (campo→{tipo,obrigatorio,...}) — alimenta a
        validação dos inputs na partida da ocorrência."""
        doc = self.pubs.find_one({"_id": bot_ref.get("project_hash"),
                                  "tipo": "bot", "status": STATUS_ATIVO})
        if not doc:
            return None
        for m in (doc["conteudo"].get("scripts") or {}).values():
            if m.get("script_hash") == bot_ref.get("script_hash"):
                return m.get("params")
        return None

    def catalog(self) -> dict:
        bots, workflows = [], []
        for doc in self.pubs.find({"status": STATUS_ATIVO}):
            item = {"hash": doc["_id"], "nome": doc["nome"], "versao": doc["versao"],
                    "conteudo": doc["conteudo"]}
            (bots if doc["tipo"] == "bot" else workflows).append(item)
        return {"bots": bots, "workflows": workflows}

    def get_workflow(self, template_hash_: str) -> dict | None:
        doc = self.pubs.find_one({"_id": template_hash_, "tipo": "workflow",
                                  "status": STATUS_ATIVO})
        return doc["conteudo"] if doc else None

    def revoke(self, hash_: str) -> None:
        self.pubs.update_one({"_id": hash_}, {"$set": {"status": STATUS_REVOGADO}})
        self.audit.insert_one({"evento": "revogado", "hash": hash_, "quando": time.time()})

    # ---- internos -----------------------------------------------------
    def _check_immutable(self, tipo: str, nome: str, versao: str, hash_: str) -> None:
        key = f"{tipo}:{nome}:{versao}"
        existing = self.names.find_one({"_id": key})
        if existing and existing["hash"] != hash_:
            raise PublishError(
                f"({nome}, {versao}) já publicado com outro hash — versão é imutável")

    def _record(self, tipo, hash_, nome, versao, conteudo, publicado_por) -> None:
        now = time.time()
        # idempotente: republicar o mesmo hash não duplica nem falha
        self.pubs.update_one(
            {"_id": hash_},
            {"$set": {"tipo": tipo, "nome": nome, "versao": versao,
                      "conteudo": conteudo, "publicado_por": publicado_por,
                      "publicado_em": now, "status": STATUS_ATIVO}},
            upsert=True)
        self.names.update_one({"_id": f"{tipo}:{nome}:{versao}"},
                              {"$set": {"hash": hash_}}, upsert=True)
        self.audit.insert_one({"evento": "publicado", "tipo": tipo, "hash": hash_,
                               "nome": nome, "versao": versao,
                               "publicado_por": publicado_por, "quando": now})


def _iter_bot_refs(node: dict):
    """Percorre a árvore do template emitindo todos os bot_ref (action/decision)."""
    if not isinstance(node, dict):
        return
    if "bot_ref" in node:
        yield node["bot_ref"]
    for filho in node.get("filhos", []):
        yield from _iter_bot_refs(filho)
    if "corpo" in node:
        yield from _iter_bot_refs(node["corpo"])
    for sub in (node.get("rotas") or {}).values():
        yield from _iter_bot_refs(sub)
