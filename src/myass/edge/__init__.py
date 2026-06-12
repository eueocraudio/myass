"""Borda do núcleo — GET/SET sobre o Locutus (o armazém público cego).

A primeira perna E2E (cliente em linguagem humana -> Locutus -> Rainha): blobs
selados com ChaCha20-Poly1305 sob um segredo por cliente (``crypto``), depositados
em endereços de dead drop derivados do segredo (``locutus``), puxados/decifrados
pelo núcleo com dedup de ``request_id`` (``gateway``/``registry``). Ver *Borda do
cliente* e *Filosofia Borg -> Locutus* em ``CLAUDE.md``.
"""

from . import crypto
from .gateway import Gateway
from .locutus import HttpLocutus, LocutusStore, MemoryLocutus
from .registry import ClientRegistry, SeenRequests

__all__ = [
    "Gateway", "ClientRegistry", "SeenRequests",
    "MemoryLocutus", "HttpLocutus", "LocutusStore", "crypto",
]
