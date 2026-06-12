"""Camada de armazenamento — conexão Mongo central + lastro GridFS.

``db`` centraliza a conexão e a fiação dos stores; ``blobstore`` guarda binários
grandes (projetos, artefatos do plano de dados) em GridFS, content-addressed.
"""

from .blobstore import (
    BlobStore, CoreDataStore, GridFSBlobStore, MemoryBlobStore,
)
from .db import connect, open_stores

__all__ = [
    "connect", "open_stores",
    "BlobStore", "MemoryBlobStore", "GridFSBlobStore", "CoreDataStore",
]
