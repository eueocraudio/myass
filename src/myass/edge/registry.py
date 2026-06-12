"""Registro de clientes e dedup de pedidos da borda.

- ``ClientRegistry`` — ``client_id -> segredo de 32 bytes`` (cunhado na parteira,
  provisionado out-of-band). Vive em memória no núcleo; segredo é material
  sensível (não persistir em claro). Revogar um cliente = esquecer o segredo.

- ``SeenRequests`` — a salvaguarda anti-replay **do lado do núcleo, custo zero
  para o cliente**: cada ``request_id`` é processado **uma vez** (dedup idempotente
  — já invariante do sistema), então o replay de um blob capturado vira no-op.
  Persistido no MongoDB para sobreviver a restart.
"""

from __future__ import annotations

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from . import crypto


class ClientRegistry:
    def __init__(self):
        self._secrets: dict[str, bytes] = {}

    def add(self, client_id: str, secret: bytes) -> None:
        if len(secret) != crypto.SECRET_LEN:
            raise ValueError(f"segredo deve ter {crypto.SECRET_LEN} bytes")
        self._secrets[client_id] = secret

    def mint(self, client_id: str) -> bytes:
        """Cunha e registra um segredo novo; devolve para provisionar out-of-band."""
        secret = crypto.new_secret()
        self._secrets[client_id] = secret
        return secret

    def revoke(self, client_id: str) -> None:
        self._secrets.pop(client_id, None)

    def get(self, client_id: str) -> bytes | None:
        return self._secrets.get(client_id)

    def items(self):
        return list(self._secrets.items())


class SeenRequests:
    def __init__(self, db: Database):
        self.col = db["edge_seen"]

    @staticmethod
    def _key(client_id: str, request_id: str) -> str:
        return f"{client_id}:{request_id}"

    def contains(self, client_id: str, request_id: str) -> bool:
        return self.col.find_one({"_id": self._key(client_id, request_id)}) is not None

    def add(self, client_id: str, request_id: str) -> bool:
        """Marca como visto. Retorna False se já estava (replay)."""
        try:
            self.col.insert_one({"_id": self._key(client_id, request_id)})
            return True
        except DuplicateKeyError:
            return False
