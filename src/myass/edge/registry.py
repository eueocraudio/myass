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
    """``client_id -> {segredo 32B, nome, workflows permitidos}``.

    Persiste no Mongo (coleção ``edge_clients``) quando há ``db`` — necessário
    para o admin **criar/editar chaves em runtime** e o gateway reconhecê-las sem
    reiniciar; sem ``db`` fica em memória (testes). ``workflows = None`` significa
    **todos** (chave legada de provisionamento); uma lista restringe o que a chave
    pode ver/executar. Os segredos vivem no Mongo do núcleo confiável (sob LUKS),
    coerente com o modelo de ameaça (o núcleo já detém todos os segredos)."""

    def __init__(self, db=None):
        self.col = db["edge_clients"] if db is not None else None
        self._mem: dict[str, dict] = {}

    def _rec(self, client_id: str) -> dict | None:
        if client_id in self._mem:
            return self._mem[client_id]
        if self.col is not None:
            d = self.col.find_one({"_id": client_id})
            if d is not None:
                rec = {"secret": bytes.fromhex(d["secret"]),
                       "name": d.get("name", client_id), "workflows": d.get("workflows")}
                self._mem[client_id] = rec
                return rec
        return None

    def add(self, client_id: str, secret: bytes, workflows=None,
            name: str | None = None) -> None:
        if len(secret) != crypto.SECRET_LEN:
            raise ValueError(f"segredo deve ter {crypto.SECRET_LEN} bytes")
        rec = {"secret": secret, "name": name or client_id, "workflows": workflows}
        self._mem[client_id] = rec
        if self.col is not None:
            self.col.replace_one({"_id": client_id},
                {"_id": client_id, "secret": secret.hex(),
                 "name": rec["name"], "workflows": workflows}, upsert=True)

    def seed(self, client_id: str, secret: bytes) -> None:
        """Semeia uma chave do config só se ainda não existir — não sobrescreve o
        que o admin já criou/editou (idempotente entre reinícios)."""
        if self._rec(client_id) is None:
            self.add(client_id, secret)

    def mint(self, client_id: str) -> bytes:
        """Cunha e registra um segredo novo; devolve para provisionar out-of-band."""
        secret = crypto.new_secret()
        self.add(client_id, secret)
        return secret

    def create(self, name: str, workflows, secret: bytes | None = None) -> bytes:
        if self._rec(name) is not None:
            raise ValueError(f"chave já existe: {name}")
        secret = secret or crypto.new_secret()
        self.add(name, secret, workflows=list(workflows or []), name=name)
        return secret

    def update(self, name: str, workflows) -> None:
        rec = self._rec(name)
        if rec is None:
            raise ValueError(f"chave inexistente: {name}")
        self.add(name, rec["secret"], workflows=list(workflows or []), name=name)

    def revoke(self, client_id: str) -> None:
        self._mem.pop(client_id, None)
        if self.col is not None:
            self.col.delete_one({"_id": client_id})

    def get(self, client_id: str) -> bytes | None:
        rec = self._rec(client_id)
        return rec["secret"] if rec else None

    def allowed(self, client_id: str):
        """Workflows permitidos (lista) ou ``None`` = todos."""
        rec = self._rec(client_id)
        return rec["workflows"] if rec else None

    def items(self):
        if self.col is not None:
            return [(d["_id"], bytes.fromhex(d["secret"])) for d in self.col.find({})]
        return [(cid, r["secret"]) for cid, r in self._mem.items()]

    def list_clients(self) -> list[dict]:
        """Para o admin (canal Noise ao publicador confiável): nome, client_id,
        workflows e o segredo (hex) — para exibir/distribuir a chave."""
        ids = ([d["_id"] for d in self.col.find({}, {"_id": 1})] if self.col is not None
               else list(self._mem))
        out = []
        for cid in sorted(set(ids)):
            r = self._rec(cid)
            if r:
                out.append({"client_id": cid, "name": r["name"],
                            "workflows": r["workflows"], "secret": r["secret"].hex()})
        return out


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
