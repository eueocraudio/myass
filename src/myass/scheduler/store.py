"""Persistência do Scheduler no MongoDB: leases, inventário e auditoria.

Tudo o que a máquina de estados precisa vive aqui, e **toda transição é escrita
antes do ACK** — é o que torna a Rainha *stateless-sobre-MongoDB*: qualquer
réplica pode varrer leases vencidos (``find_expired``) e retomar o controle sem
estado em memória. A morte de uma réplica não órfã as atividades em voo.

Coleções:

- ``leases`` — o estado de despacho de cada atividade, chaveado por
  ``atividade_id`` (único por despacho; **não** por ``occurrence_id``)::

      { "_id": atividade_id, "occurrence_id", "state", "tentativa",
        "max_tentativas", "lease_s", "lease_expira_em", "timeout_em",
        "carrier_block",  # block_hash do portador atual (detecta portador antigo)
        "bot_ref", "params", "result", "motivo", "atualizado_em" }

- ``inventory`` — ``block_hash -> { profile, capabilities, last_seen }`` (do HELLO).
- ``audit`` — log append-only por evento de execução (linhagem à prova de
  adulteração; ver *Identidade & rastreabilidade*).
"""

from __future__ import annotations

import time
from typing import Any

from pymongo import ASCENDING
from pymongo.database import Database

from . import states


class LeaseStore:
    def __init__(self, db: Database):
        self.db = db
        self.leases = db["leases"]
        self.inventory = db["inventory"]
        self.audit = db["audit"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        # O índice que serve o reap: leases EXECUTANDO ordenados por expiração.
        self.leases.create_index(
            [("state", ASCENDING), ("lease_expira_em", ASCENDING)], name="reap"
        )
        self.audit.create_index([("atividade_id", ASCENDING)], name="por_atividade")

    # ---- inventário ----------------------------------------------------
    def upsert_inventory(self, block_hash: str, profile: dict, capabilities: list,
                         project_hashes: list, now: float) -> None:
        self.inventory.update_one(
            {"_id": block_hash},
            {"$set": {
                "profile": profile,
                "capabilities": capabilities or [],
                "project_hashes": project_hashes or [],
                "last_seen": now,
            }},
            upsert=True,
        )

    def get_inventory(self, block_hash: str) -> dict | None:
        return self.inventory.find_one({"_id": block_hash})

    def list_inventory(self) -> list[dict]:
        """Inventário dos blocks (para o admin ver o ambiente)."""
        return [{"block": d["_id"], "profile": d.get("profile"),
                 "capabilities": d.get("capabilities"), "last_seen": d.get("last_seen")}
                for d in self.inventory.find()]

    # ---- leases --------------------------------------------------------
    def get_lease(self, atividade_id: str) -> dict | None:
        return self.leases.find_one({"_id": atividade_id})

    def put_lease(self, doc: dict) -> None:
        doc = dict(doc)
        doc["atualizado_em"] = time.time()
        self.leases.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def set_fields(self, atividade_id: str, **fields: Any) -> None:
        fields["atualizado_em"] = time.time()
        self.leases.update_one({"_id": atividade_id}, {"$set": fields})

    def find_expired(self, now: float) -> list[dict]:
        """Leases EXECUTANDO cujo lease já venceu (sem beat recente)."""
        return list(self.leases.find(
            {"state": states.EXECUTANDO, "lease_expira_em": {"$lte": now}}
        ))

    # ---- auditoria -----------------------------------------------------
    def audit_append(self, atividade_id: str, evento: str, now: float, **extra: Any) -> None:
        entry = {"atividade_id": atividade_id, "evento": evento, "quando": now}
        entry.update(extra)
        self.audit.insert_one(entry)

    def audit_for(self, atividade_id: str) -> list[dict]:
        return list(self.audit.find({"atividade_id": atividade_id}).sort("quando", ASCENDING))
