"""Adapter do subspace relay sobre o serviço `bdd` (Blind Dead Drop) real.

O `bdd` é o transporte cego burro (a *camada externa* dos dois selos aninhados):
um serviço HTTPS/onion cujo servidor guarda blobs opacos em endereços opacos e
re-sela o payload do myass com a chave do channel (ver *Comunicação inter
-quadrante* em CLAUDE.md). O `bdd` modela exatamente nosso formato — um **channel**
(int) com **parts** request/response — então o mapeamento é direto.

Desacoplado do projeto `bdd` por um ``client_factory(host, port, secret,
insecure) -> client`` onde ``client`` tem ``send(part, channel:int, plaintext)`` e
``receive(part, channel:int) -> bytes|None`` (a interface do ``DeadDropClient``).
Cada par de Rainhas tem seu **endpoint onion + segredo-raiz do `bdd`** na tabela
de roteamento (provisionada out-of-band); aqui mapeamos os ``channel``s do relay
(BLAKE2s dos ids) para a config do par certo.
"""

from __future__ import annotations

from .relay import channel, prekey_channel


class BddRelayTransport:
    """Implementa ``RelayTransport`` sobre o `bdd`. ``peers`` =
    ``{peer_id: {"host","port","secret"(32B),"insecure"?}}``."""

    def __init__(self, my_id: str, peers: dict, client_factory):
        self.my_id = my_id
        self.client_factory = client_factory
        self._cfg: dict[str, dict] = {}      # channel_hex -> config do `bdd` do par
        self._clients: dict[str, object] = {}  # peer_id -> client (cacheado)
        self._peer_of: dict[str, str] = {}
        for peer_id, cfg in peers.items():
            for ch in (channel(my_id, peer_id), channel(peer_id, my_id),
                       prekey_channel(my_id, peer_id), prekey_channel(peer_id, my_id)):
                self._cfg[ch] = cfg
                self._peer_of[ch] = peer_id

    def _client(self, channel_hex: str):
        peer = self._peer_of[channel_hex]
        if peer not in self._clients:
            c = self._cfg[channel_hex]
            self._clients[peer] = self.client_factory(
                c["host"], c["port"], c["secret"], c.get("insecure", False))
        return self._clients[peer]

    @staticmethod
    def _chan_int(channel_hex: str) -> int:
        # O número do channel nunca chega ao servidor `bdd` (ele só vê o endereço
        # 64-hex derivado); o int é determinístico nos dois lados.
        return int(channel_hex, 16)

    def deposit(self, channel_hex: str, part: str, blob: bytes) -> None:
        self._client(channel_hex).send(part, self._chan_int(channel_hex), blob)

    def fetch(self, channel_hex: str, part: str) -> bytes | None:
        return self._client(channel_hex).receive(part, self._chan_int(channel_hex))

    def remove(self, channel_hex: str, part: str) -> None:
        # O `bdd` é write-once com TTL e não expõe delete pelo client; a dedup de
        # request_id + a expiração por TTL cobrem o reprocessamento. No-op.
        pass
