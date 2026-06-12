"""A borda do núcleo: GET (puxa pedidos) e SET (empurra respostas).

Sentido de dentro para fora — a infraestrutura **nunca escuta** conexões de
entrada (ver *Topologia* em ``CLAUDE.md``):

- **GET** faz polling no Locutus pelos pedidos de cada cliente, **decifra dentro
  do núcleo** (o Locutus segue cego), aplica a dedup de ``request_id`` e entrega
  o pedido à Rainha via ``on_request``.
- **SET** cifra um resultado para o cliente e o empurra ao Locutus.

Os endereços de request/response são derivados do segredo de cada cliente
(``crypto``), então o GET sabe exatamente onde olhar sem nenhum identificador em
claro no armazém. Um pedido em voo por cliente (endereço fixo, consumido ao ler)
— suficiente para clientes do dono; evoluível depois.
"""

from __future__ import annotations

import json
from typing import Callable

from .. import errlog
from . import crypto
from .locutus import LocutusStore
from .registry import ClientRegistry, SeenRequests

# on_request(client_id, request_id, message_dict)
OnRequest = Callable[[str, str, dict], None]


class Gateway:
    def __init__(self, store: LocutusStore, registry: ClientRegistry,
                 seen: SeenRequests, on_request: OnRequest | None = None):
        self.store = store
        self.registry = registry
        self.seen = seen
        self.on_request = on_request

    # ---- GET: puxa pedidos do Locutus ----------------------------------
    def poll(self) -> int:
        """Uma varredura: processa pedidos novos de todos os clientes. Retorna
        quantos foram entregues à Rainha. Não bloqueia (deve ser chamado num laço
        com intervalo, como o reap do Scheduler)."""
        delivered = 0
        for client_id, secret in self.registry.items():
            addr = crypto.request_address(secret)
            blob = self.store.get(addr)
            if blob is None:
                continue

            # Decifra DENTRO do núcleo. Blob ilegível = lixo/adulteração: registra
            # e descarta (não trava a borda).
            try:
                plaintext = crypto.open_request(crypto.request_key(secret), blob)
                msg = json.loads(plaintext)
                request_id = msg["request_id"]
            except Exception as exc:
                errlog.record(f"edge GET: blob inválido de cliente={client_id}: {exc!r}")
                self.store.delete(addr)
                continue

            # Replay: já processado -> no-op (consome e segue).
            if self.seen.contains(client_id, request_id):
                self.store.delete(addr)
                continue

            # Entrega à Rainha. Se o handoff falhar, deixa o blob para a próxima
            # varredura (entrega ao-menos-uma-vez; a dedup cobre o reprocesso).
            try:
                if self.on_request is not None:
                    self.on_request(client_id, request_id, msg)
            except Exception as exc:
                errlog.record(f"edge GET: on_request falhou cliente={client_id} "
                              f"req={request_id}: {exc!r}")
                continue

            self.seen.add(client_id, request_id)
            self.store.delete(addr)
            delivered += 1
        return delivered

    # ---- SET: empurra a resposta ao Locutus ----------------------------
    def send_response(self, client_id: str, request_id: str, body) -> None:
        """Cifra um resultado para o cliente e o deposita no endereço de resposta
        dele. Levanta ``KeyError`` se o cliente não está registrado."""
        secret = self.registry.get(client_id)
        if secret is None:
            raise KeyError(f"cliente desconhecido: {client_id}")
        plaintext = json.dumps(
            {"request_id": request_id, "body": body},
            ensure_ascii=False,
        ).encode("utf-8")
        blob = crypto.seal_response(crypto.response_key(secret), plaintext)
        self.store.put(crypto.response_address(secret), blob)
