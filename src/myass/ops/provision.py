"""Provisionamento — a parteira efêmera que cunha as identidades do quadrante.

Gera, **out-of-band**, as chaves estáticas e PSKs (ver *Assimilação* e *Canais
seguros* em CLAUDE.md): a estática do Scheduler, um par X25519 + PSK por drone e
por admin, e um segredo por cliente. Produz a config do núcleo (com a tabela de
peers/papéis) e uma config por drone/admin/cliente. Em produção isto roda numa
estação air-gapped e as chaves privadas viajam em mídia física.

As configs são JSON-serializáveis (chaves em hex), consumidas por ``nodes.py``.
"""

from __future__ import annotations

import hashlib
import os

from ..edge import crypto as edge_crypto
from ..noise import primitives as P

DEFAULT_PROFILE = {"mem_mb": 4096, "cpu_cores": 4}


def _designation(pub: bytes) -> str:
    """A designação do drone = BLAKE2(pubkey estática) (ver *Identidade*)."""
    return "blk:" + hashlib.blake2b(pub).hexdigest()[:24]


def _peer(role: str, prologue: bytes, s_pub: bytes, host: str, port: int,
          profile: dict):
    priv, pub = P.generate_keypair()
    psk = os.urandom(32)
    pid = ("adm:" if role == "publicador" else "") + _designation(pub) \
        if role == "publicador" else _designation(pub)
    peer = {"id": pid, "pub": pub.hex(), "psk": psk.hex(), "role": role}
    node = {
        "id": pid, "role": role, "prologue": prologue.hex(),
        "endpoint": {"transport": "direct", "host": host, "port": port},
        "static_priv": P.private_bytes(priv).hex(), "static_pub": pub.hex(),
        "scheduler_pub": s_pub.hex(), "psk": psk.hex(),
    }
    if role == "executor":
        node["profile"] = profile
    return peer, node


def provision_quadrante(*, n_drones: int = 1, n_admins: int = 1,
                        clients: list[str] | None = None,
                        host: str = "127.0.0.1", port: int = 0,
                        locutus_url: str = "", profile: dict | None = None) -> dict:
    clients = clients or []
    profile = profile or DEFAULT_PROFILE
    prologue = os.urandom(16)
    s_priv, s_pub = P.generate_keypair()

    peers, drones, admins = [], [], []
    for _ in range(n_drones):
        peer, node = _peer("executor", prologue, s_pub, host, port, profile)
        peers.append(peer)
        drones.append(node)
    for _ in range(n_admins):
        peer, node = _peer("publicador", prologue, s_pub, host, port, profile)
        peers.append(peer)
        admins.append(node)

    client_secrets = [{"client_id": c, "secret": edge_crypto.new_secret().hex()}
                      for c in clients]

    core = {
        "prologue": prologue.hex(),
        "scheduler_priv": P.private_bytes(s_priv).hex(),
        "scheduler_pub": s_pub.hex(),
        "host": host, "port": port, "locutus_url": locutus_url,
        "peers": peers,
        "clients": {c["client_id"]: c["secret"] for c in client_secrets},
    }
    return {"core": core, "drones": drones, "admins": admins,
            "clients": client_secrets,
            "scheduler_pub": s_pub.hex(), "prologue": prologue.hex()}
