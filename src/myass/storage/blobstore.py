"""Lastro de binários grandes — GridFS content-addressed.

O MongoDB é o lastro durável; binários grandes (projetos `.tar.gz`, artefatos do
*plano de dados*) passam de 16 MB e por isso vivem em **GridFS**, não em docs
comuns (ver *Plano de dados* e *BOT → Distribuição* em CLAUDE.md).

- ``BlobStore`` — key opaca → bytes (``put``/``get``/``exists``/``delete``).
  ``GridFSBlobStore`` (produção, pymongo) e ``MemoryBlobStore`` (dev/teste).
- ``CoreDataStore`` — o **plano de dados do lado do núcleo**: content-addressed
  (``data_ref = blake2:<hash>``), com **dedup** (mesmo conteúdo = mesmo ref = um
  upload) e **verificação de integridade na leitura**. Implementa a mesma
  interface ``DataStore`` do executor, então a tradução ``$file``↔``$data`` roda
  igual nas duas pontas. Projetos usam o ``BlobStore`` direto (key = `project_hash`).
"""

from __future__ import annotations

from typing import Protocol

from ..executor.dataplane import compute_ref


class BlobStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes | None: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


class MemoryBlobStore:
    """BlobStore em memória (dev/teste)."""

    def __init__(self):
        self._d: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self._d.setdefault(key, data)  # imutável: primeiro a gravar vence

    def get(self, key: str) -> bytes | None:
        return self._d.get(key)

    def exists(self, key: str) -> bool:
        return key in self._d

    def delete(self, key: str) -> None:
        self._d.pop(key, None)


class GridFSBlobStore:
    """BlobStore sobre GridFS. ``_id`` do arquivo = key (dedup natural). O bucket
    é criado preguiçosamente (assim o objeto pode ser construído sob mongomock,
    falhando só se um blob for de fato usado sem um Mongo real)."""

    def __init__(self, db):
        self._db = db
        self._fs = None

    @property
    def _gridfs(self):
        if self._fs is None:
            import gridfs  # noqa: PLC0415
            self._fs = gridfs.GridFS(self._db)
        return self._fs

    def put(self, key: str, data: bytes) -> None:
        fs = self._gridfs
        if not fs.exists(key):  # imutável / dedup
            fs.put(data, _id=key)

    def get(self, key: str) -> bytes | None:
        fs = self._gridfs
        return fs.get(key).read() if fs.exists(key) else None

    def exists(self, key: str) -> bool:
        return self._gridfs.exists(key)

    def delete(self, key: str) -> None:
        fs = self._gridfs
        if fs.exists(key):
            fs.delete(key)


class CoreDataStore:
    """Plano de dados do núcleo: content-addressed sobre um ``BlobStore``.

    Satisfaz a interface ``DataStore`` (``put(data)->ref`` / ``get(ref)->bytes``)
    usada pela tradução ``$file``↔``$data`` do executor.
    """

    def __init__(self, blobs: BlobStore):
        self.blobs = blobs

    def put(self, data: bytes) -> str:
        ref = compute_ref(data)
        if not self.blobs.exists(ref):  # dedup: mesmo conteúdo, um upload
            self.blobs.put(ref, data)
        return ref

    def get(self, data_ref: str) -> bytes:
        data = self.blobs.get(data_ref)
        if data is None:
            raise KeyError(data_ref)
        if compute_ref(data) != data_ref:  # integridade na leitura
            raise ValueError(f"blob corrompido: {data_ref}")
        return data
