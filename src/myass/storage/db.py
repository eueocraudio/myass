"""Conexão central com o MongoDB e fiação dos stores do núcleo.

Ponto único onde o ``MongoClient`` real é criado (configurável por env) e os
stores de cada subsistema são instanciados sobre o mesmo database. A durabilidade
e a tolerância a falhas vivem no MongoDB (replica set em produção); o resto do
núcleo é *stateless-sobre-MongoDB*.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

DEFAULT_URI = "mongodb://localhost:27017/"
DEFAULT_DB = "myass"


def connect(uri: str | None = None, dbname: str | None = None):
    """Abre um ``MongoClient`` e devolve o database. Env: ``MYASS_MONGO_URI`` /
    ``MYASS_MONGO_DB``."""
    from pymongo import MongoClient  # noqa: PLC0415

    uri = uri or os.environ.get("MYASS_MONGO_URI", DEFAULT_URI)
    name = dbname or os.environ.get("MYASS_MONGO_DB", DEFAULT_DB)
    return MongoClient(uri)[name]


def open_stores(db=None, blobs=None) -> SimpleNamespace:
    """Instancia todos os stores do núcleo sobre um database (real ou injetado).

    Devolve um namespace com: ``backlog`` (broker), ``leases`` (scheduler),
    ``occurrences`` (workflow), ``seen`` (dedup da borda), ``blobs`` (GridFS por
    padrão; injetável p/ teste) e ``data`` (plano de dados content-addressed).
    """
    if db is None:
        db = connect()
    from ..broker.store import BacklogStore  # noqa: PLC0415
    from ..edge.registry import SeenRequests  # noqa: PLC0415
    from ..scheduler.store import LeaseStore  # noqa: PLC0415
    from ..workflow.engine import OccurrenceStore  # noqa: PLC0415
    from .blobstore import CoreDataStore, GridFSBlobStore  # noqa: PLC0415

    if blobs is None:
        blobs = GridFSBlobStore(db)
    return SimpleNamespace(
        db=db,
        backlog=BacklogStore(db),
        leases=LeaseStore(db),
        occurrences=OccurrenceStore(db),
        seen=SeenRequests(db),
        blobs=blobs,
        data=CoreDataStore(blobs),
    )
