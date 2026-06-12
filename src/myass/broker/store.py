"""Lastro durável do broker: as atividades persistidas no MongoDB.

A durabilidade e a tolerância a falhas vivem aqui — o ring buffer é só um cache
em RAM por cima deste backlog. Toda atividade é gravada no Mongo no ``enqueue``
*antes* de qualquer coisa ir para o ring (o caminho mais seguro: nunca existe
trabalho que vive só em memória).

Modelo de uma atividade na coleção ``activities``::

    {
      "_id":       atividade_id,        # único por despacho (idempotência)
      "class_id":  "C4",                # o nó/classe em que foi escrita
      "seq":       <int>,               # ordem FIFO dentro do nó
      "status":    "ready" | "taken",   # disponível / já entregue ao block
      "buffered":  bool,                # já está na janela (ring) em RAM?
      "activity":  { ... },             # a ordem de atividade completa
      "enqueued_at": <epoch float>,
    }

``seq`` é um contador monotônico **por classe** (coleção ``counters``), dando uma
ordem total estável dentro de cada nó. ``buffered`` evita entrega dupla entre o
push direto e a carga preguiçosa: o loader só pega itens ``ready`` ainda não
``buffered``. Como o ring vive em RAM, na partida o broker chama
``reset_buffered`` (uma janela perdida volta a ser carregável).
"""

from __future__ import annotations

import time
from typing import Any

from pymongo import ASCENDING, MongoClient, ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

STATUS_READY = "ready"
STATUS_TAKEN = "taken"


class BacklogStore:
    def __init__(self, db: Database):
        """``db`` é um ``pymongo`` Database (ou compatível, p.ex. mongomock)."""
        self.db = db
        self.activities = db["activities"]
        self.counters = db["counters"]
        self._ensure_indexes()

    @classmethod
    def connect(cls, uri: str = "mongodb://localhost:27017/", dbname: str = "myass") -> "BacklogStore":
        """Conveniência: abre um cliente Mongo e devolve um store sobre ``dbname``."""
        return cls(MongoClient(uri)[dbname])

    def _ensure_indexes(self) -> None:
        # O índice que serve o loader: dentro de um nó, os 'ready' não 'buffered'
        # mais antigos primeiro.
        self.activities.create_index(
            [("class_id", ASCENDING), ("status", ASCENDING),
             ("buffered", ASCENDING), ("seq", ASCENDING)],
            name="loader",
        )

    def next_seq(self, class_id: str) -> int:
        """Próximo número de sequência (monotônico) para o nó ``class_id``."""
        doc = self.counters.find_one_and_update(
            {"_id": class_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(doc["seq"])

    def append(self, class_id: str, atividade_id: str, activity: dict) -> int | None:
        """Persiste uma atividade no nó ``class_id``. Retorna o ``seq`` atribuído,
        ou ``None`` se a atividade já existia (idempotência por ``atividade_id``)."""
        seq = self.next_seq(class_id)
        doc = {
            "_id": atividade_id,
            "class_id": class_id,
            "seq": seq,
            "status": STATUS_READY,
            "buffered": False,
            "activity": activity,
            "enqueued_at": time.time(),
        }
        try:
            self.activities.insert_one(doc)
            return seq
        except DuplicateKeyError:
            # Já enfileirada antes; não reempilha (replay vira no-op).
            return None

    def load_ready(self, class_id: str, limit: int) -> list[dict]:
        """Pega até ``limit`` atividades ``ready`` ainda não ``buffered`` do nó,
        em ordem FIFO, e as marca ``buffered`` (reservadas para o ring).

        Assume um único chamador por nó por vez (o broker garante <= 1 carga em
        voo por nó), então o find seguido do update não corre consigo mesmo.
        """
        if limit <= 0:
            return []
        cursor = (
            self.activities.find(
                {"class_id": class_id, "status": STATUS_READY, "buffered": False}
            )
            .sort("seq", ASCENDING)
            .limit(limit)
        )
        docs = list(cursor)
        if docs:
            ids = [d["_id"] for d in docs]
            self.activities.update_many({"_id": {"$in": ids}}, {"$set": {"buffered": True}})
        return docs

    def mark_taken(self, atividade_id: str) -> None:
        """Marca uma atividade como entregue a um block (saiu da fila)."""
        self.activities.update_one(
            {"_id": atividade_id}, {"$set": {"status": STATUS_TAKEN}}
        )

    def requeue(self, atividade_id: str) -> str | None:
        """Devolve uma atividade já entregue para a fila do seu nó (a *regeneração*
        do lease). Recebe um ``seq`` novo (vai para o fim da fila) e volta a
        ``ready``/não-``buffered``. Retorna o ``class_id`` do nó, ou ``None`` se a
        atividade não existe."""
        doc = self.activities.find_one({"_id": atividade_id}, {"class_id": 1})
        if doc is None:
            return None
        class_id = doc["class_id"]
        self.activities.update_one(
            {"_id": atividade_id},
            {"$set": {"status": STATUS_READY, "buffered": False, "seq": self.next_seq(class_id)}},
        )
        return class_id

    def count_ready(self, class_id: str) -> int:
        return self.activities.count_documents(
            {"class_id": class_id, "status": STATUS_READY}
        )

    def reset_buffered(self) -> int:
        """Recuperação na partida: o ring em RAM foi perdido, então todo item
        ``ready`` marcado ``buffered`` deve voltar a ser carregável. Retorna
        quantos foram resetados."""
        res = self.activities.update_many(
            {"status": STATUS_READY, "buffered": True}, {"$set": {"buffered": False}}
        )
        return int(res.modified_count)

    def get(self, atividade_id: str) -> dict | None:
        return self.activities.find_one({"_id": atividade_id})
