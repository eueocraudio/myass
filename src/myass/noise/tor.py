"""Serviço onion Tor v3 — a face escondida do Scheduler (lado servidor).

O Scheduler é um **serviço onion Tor v3** (ver *Canais seguros → Transporte* em
CLAUDE.md): os drones discam o `.onion`, o IP do núcleo nunca é revelado, **sem
porta de escuta na clearnet** (a entrada chega pelo rendezvous do Tor — honra o
*sem entrada em direção à WAN*). Gerência via `stem` (controlador Tor).

O ``SchedulerServer`` continua escutando em ``127.0.0.1:<porta_local>``; o onion
**encaminha** ``onion:<porta_virtual> → 127.0.0.1:<porta_local>``. O drone disca
com ``channel.connect_tor(onion, porta_virtual)`` (já existente). Em LAN/localhost
o transporte é direto (sem Tor) — ver a decisão de topologia.

**Autorização de cliente (v3):** só drones provisionados têm a chave de auth do
descritor; partes não autorizadas nem alcançam o rendezvous. Isto fica *sob* o
Noise `KKpsk0` (defesa em profundidade). Aqui geramos os pares de auth; a chave
**privada** vai no Tor do drone (``ClientOnionAuthDir``, fora de banda, como o
resto do provisionamento) e a **pública** é registrada no serviço.

Requer `stem` (extra `tor`) e um Tor com ControlPort. Não exercitado pelos testes
sem um Tor real (teste de integração com `skipUnless`).
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

DEFAULT_VIRTUAL_PORT = 9735  # porta virtual do onion (arbitrária)


def _b32(raw: bytes) -> str:
    # Tor client-auth v3: base32 (RFC4648) sem padding, maiúsculas.
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def gen_client_auth() -> tuple[str, str]:
    """Gera um par de autorização de cliente v3 (X25519). Retorna
    ``(priv_b32, pub_b32)``: a privada vai no Tor do drone, a pública no serviço."""
    priv = X25519PrivateKey.generate()
    priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return _b32(priv_raw), _b32(pub_raw)


def client_auth_line(onion_address: str, priv_b32: str) -> str:
    """Linha para o ``ClientOnionAuthDir`` do Tor do drone (arquivo ``.auth_private``)."""
    name = onion_address.removesuffix(".onion")
    return f"{name}:descriptor:x25519:{priv_b32}"


class OnionService:
    """Publica um serviço onion v3 efêmero apontando para a porta local do
    Scheduler. Context manager: remove o onion ao sair.

    ``client_pubs`` = lista de pubkeys de auth (base32) dos drones autorizados.
    ``key`` (opcional) = chave privada salva para manter o ``.onion`` **estável**
    entre reinícios (a spec quer um endpoint onion estável); ``None`` cunha um novo.
    """

    def __init__(self, local_port: int, virtual_port: int = DEFAULT_VIRTUAL_PORT,
                 control_port: int = 9051, control_password: str | None = None,
                 client_pubs: list[str] | None = None, key: str | None = None):
        self.local_port = local_port
        self.virtual_port = virtual_port
        self.control_port = control_port
        self.control_password = control_password
        self.client_pubs = client_pubs or []
        self.key = key
        self._controller = None
        self._service_id = None
        self.onion_address: str | None = None
        self.private_key: str | None = None  # persistir para .onion estável

    def __enter__(self) -> "OnionService":
        from stem.control import Controller  # noqa: PLC0415
        self._controller = Controller.from_port(port=self.control_port)
        self._controller.authenticate(password=self.control_password)

        kwargs = {
            "await_publication": True,
            "detached": False,
        }
        if self.client_pubs:
            kwargs["client_auth_v3"] = self.client_pubs
        if self.key:
            kwargs["key_type"], kwargs["key_content"] = "ED25519-V3", self.key
        else:
            kwargs["key_type"], kwargs["key_content"] = "NEW", "ED25519-V3"

        resp = self._controller.create_ephemeral_hidden_service(
            {self.virtual_port: f"127.0.0.1:{self.local_port}"}, **kwargs)
        self._service_id = resp.service_id
        self.onion_address = resp.service_id + ".onion"
        if getattr(resp, "private_key", None):
            self.private_key = resp.private_key
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._controller and self._service_id:
                self._controller.remove_ephemeral_hidden_service(self._service_id)
        finally:
            if self._controller:
                self._controller.close()
