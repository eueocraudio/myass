"""Subspace relay — dead drop cego de REQUEST/RESPONSE entre Rainhas.

Quadrantes conversam Rainha↔Rainha por um dead drop cego que guarda só ciphertext
opaco (o projeto `bdd`, sobre Tor): uma Rainha *deposita* um REQUEST, a parceira o
*puxa*; RESPONSEs voltam pelo mesmo caminho (ver *Comunicação inter-quadrante* em
CLAUDE.md). É o **Locutus entre Rainhas** — assíncrono, store-and-forward.

- **E2E (a segurança que importa):** X3DH (``x3dh.py``) por par request/response.
- **Transporte cego (`RelayTransport`):** depósito/puxada de blobs por
  ``(channel, part)``; o ``bdd`` re-sela num endereço não-correlacionável. Aqui:
  ``MemoryRelayTransport`` (teste) e ``BddRelayTransport`` (sobre o `bdd`, doc).
- **Endereçamento:** ``channel(A→B) = BLAKE2s("myass/relay/ch|"+id_A+id_B)`` (par
  **ordenado**); prekeys em ``BLAKE2s("myass/relay/prekey|"+id_B+id_A)``.
- **Anti-replay:** contador monotônico por direção + ``request_id`` (estilo
  key-image); apagar a OPK já torna o replay do REQUEST irrecuperável.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from typing import Protocol

from . import x3dh

_V = "v1"


def channel(a_id: str, b_id: str) -> str:
    return hashlib.blake2s(f"myass/relay/ch|{a_id}{b_id}".encode()).hexdigest()


def prekey_channel(b_id: str, a_id: str) -> str:
    return hashlib.blake2s(f"myass/relay/prekey|{b_id}{a_id}".encode()).hexdigest()


# ---- transporte cego ---------------------------------------------------
class RelayTransport(Protocol):
    def deposit(self, channel: str, part: str, blob: bytes) -> None: ...
    def fetch(self, channel: str, part: str) -> bytes | None: ...
    def remove(self, channel: str, part: str) -> None: ...


class MemoryRelayTransport:
    """Dead drop em memória (teste/dev). Um slot por ``(channel, part)``."""

    def __init__(self):
        self._d: dict[tuple[str, str], bytes] = {}
        self._lock = threading.Lock()

    def deposit(self, channel, part, blob):
        with self._lock:
            self._d[(channel, part)] = blob   # write-once por slot (sobrescreve só após remove)

    def fetch(self, channel, part):
        with self._lock:
            return self._d.get((channel, part))

    def remove(self, channel, part):
        with self._lock:
            self._d.pop((channel, part), None)


# ---- a Rainha no relay -------------------------------------------------
class SubspaceRelay:
    """Uma Rainha falando com suas parceiras pelo relay.

    ``routing``: ``{quadrante_id: {"psk": bytes, "ik_sig_pub": bytes}}`` — a tabela
    provisionada out-of-band (PSK por par + IK de assinatura conhecida da parceira).
    """

    def __init__(self, identity: x3dh.Identity, transport: RelayTransport,
                 routing: dict, vault: x3dh.PrekeyVault | None = None):
        self.me = identity
        self.transport = transport
        self.routing = routing
        self.vault = vault or x3dh.PrekeyVault(identity)
        self._pending: dict[str, tuple[bytes, str]] = {}   # request_id -> (SK, dest)
        self._resp_keys: dict[tuple[str, str], bytes] = {}  # (peer, request_id) -> SK
        self._seen: dict[str, set[str]] = {}               # peer -> request_ids vistos
        self._counter = 0

    @property
    def quadrante_id(self) -> str:
        return self.me.quadrante_id

    # ---- prekeys ------------------------------------------------------
    def publish_prekeys(self) -> None:
        """Publica o bundle assinado para cada parceira (no prekey channel do par)."""
        bundle = json.dumps(self.vault.bundle()).encode()
        for peer_id in self.routing:
            self.transport.deposit(prekey_channel(self.me.quadrante_id, peer_id),
                                   "request", bundle)

    # ---- A: enviar REQUEST -------------------------------------------
    def send_request(self, dest_id: str, payload: bytes) -> str | None:
        peer = self.routing[dest_id]
        raw = self.transport.fetch(prekey_channel(dest_id, self.me.quadrante_id), "request")
        if raw is None:
            return None  # parceira ainda não publicou prekeys (fallback: tentar depois)
        bundle = json.loads(raw)
        x3dh.verify_bundle(bundle, peer["ik_sig_pub"])

        sk, header = x3dh.agree_sender(self.me, bundle, peer["psk"])
        request_id = "req:" + uuid.uuid4().hex
        self._counter += 1
        counter = self._counter
        ch = channel(self.me.quadrante_id, dest_id)
        ad = _ad("request", self.me.quadrante_id, dest_id, ch,
                 header.get("opk_id"), counter, request_id)
        ct = x3dh.seal(sk, b"req", counter, payload, ad)
        blob = json.dumps({"header": header, "request_id": request_id,
                           "counter": counter, "ct": ct.hex()}).encode()
        self.transport.deposit(ch, "request", blob)
        self._pending[request_id] = (sk, dest_id)
        return request_id

    # ---- B: receber REQUESTs -----------------------------------------
    def receive_requests(self) -> list[tuple[str, str, bytes]]:
        out = []
        for peer_id, peer in self.routing.items():
            ch = channel(peer_id, self.me.quadrante_id)
            raw = self.transport.fetch(ch, "request")
            if raw is None:
                continue
            self.transport.remove(ch, "request")  # consome o slot
            msg = json.loads(raw)
            rid, counter, header = msg["request_id"], msg["counter"], msg["header"]
            seen = self._seen.setdefault(peer_id, set())
            if rid in seen:
                continue  # replay -> no-op
            try:
                sk = x3dh.agree_receiver(self.me, self.vault, header, peer["psk"])
                ad = _ad("request", peer_id, self.me.quadrante_id, ch,
                         header.get("opk_id"), counter, rid)
                payload = x3dh.open_(sk, b"req", counter, bytes.fromhex(msg["ct"]), ad)
            except Exception:  # noqa: BLE001  (lixo/adulteração/opk gasta)
                continue
            seen.add(rid)
            self._resp_keys[(peer_id, rid)] = sk
            out.append((peer_id, rid, payload))
        return out

    # ---- B: responder -------------------------------------------------
    def send_response(self, sender_id: str, request_id: str, payload: bytes) -> bool:
        sk = self._resp_keys.pop((sender_id, request_id), None)
        if sk is None:
            return False
        self._counter += 1
        counter = self._counter
        ch = channel(sender_id, self.me.quadrante_id)  # mesma channel do REQUEST
        ad = _ad("response", self.me.quadrante_id, sender_id, ch, None, counter, request_id)
        ct = x3dh.seal(sk, b"resp", counter, payload, ad)
        blob = json.dumps({"request_id": request_id, "counter": counter,
                           "ct": ct.hex()}).encode()
        self.transport.deposit(ch, "response", blob)
        return True

    # ---- A: receber RESPONSEs ----------------------------------------
    def receive_responses(self) -> list[tuple[str, bytes]]:
        out = []
        for rid, (sk, dest) in list(self._pending.items()):
            ch = channel(self.me.quadrante_id, dest)
            raw = self.transport.fetch(ch, "response")
            if raw is None:
                continue
            msg = json.loads(raw)
            if msg["request_id"] != rid:
                continue
            ad = _ad("response", dest, self.me.quadrante_id, ch, None,
                     msg["counter"], rid)
            try:
                payload = x3dh.open_(sk, b"resp", msg["counter"],
                                     bytes.fromhex(msg["ct"]), ad)
            except Exception:  # noqa: BLE001
                continue
            self.transport.remove(ch, "response")
            del self._pending[rid]
            out.append((rid, payload))
        return out


def _ad(part: str, frm: str, to: str, ch: str, opk_id, counter: int, rid: str) -> bytes:
    return json.dumps({"v": _V, "part": part, "from": frm, "to": to, "ch": ch,
                       "opk_id": opk_id, "counter": counter, "rid": rid},
                      sort_keys=True, separators=(",", ":")).encode()
