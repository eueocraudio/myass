"""AdminClient — o Painel do administrador (lado lógico), sobre o canal Noise.

Provisionado como cliente do canal sub-espacial com papel **publicador** (Noise
``KKpsk0``, mesmo transporte plugável direto/Tor). Faz o que é privilegiado:
publicar BOTs/workflows, ler o catálogo, iniciar e acompanhar ocorrências, e ver
o ambiente. É a base sobre a qual a GUI (``admin_gui``) ou um CLI se apoiam.
"""

from __future__ import annotations

import json

from ..executor import project as proj
from ..noise import channel as ch
from ..proto import envelope as E


class AdminError(Exception):
    pass


class AdminClient:
    def __init__(self, endpoint: dict, prologue: bytes, s_priv, s_pub: bytes,
                 scheduler_pub: bytes, psk: bytes):
        self.endpoint = endpoint
        self.prologue = prologue
        self.s_priv, self.s_pub = s_priv, s_pub
        self.scheduler_pub = scheduler_pub
        self.psk = psk
        self.channel: ch.NoiseChannel | None = None

    def connect(self) -> "AdminClient":
        sock = ch.connect(self.endpoint)
        self.channel = ch.initiate(sock, self.prologue, self.s_priv, self.s_pub,
                                   self.scheduler_pub, self.psk)
        return self

    def close(self) -> None:
        if self.channel is not None:
            self.channel.close()
            self.channel = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    def _rpc(self, t, fields=None, body=b""):
        self.channel.send(E.encode(t, fields, body))
        rt, h, rbody = E.decode(self.channel.recv())
        if rt == E.DENIED:
            raise AdminError(f"negado: {h.get('motivo')}")
        return rt, h, rbody

    # ---- publicação ---------------------------------------------------
    def publish_bot(self, tar_bytes: bytes) -> dict:
        _, h, _ = self._rpc(E.PUBLISH, {"tipo": "bot"}, tar_bytes)
        return h

    def publish_bot_dir(self, project_dir: str) -> dict:
        """Empacota um diretório de projeto e o publica."""
        return self.publish_bot(proj.pack(project_dir))

    def publish_workflow(self, template: dict) -> dict:
        body = json.dumps(template, ensure_ascii=False).encode("utf-8")
        _, h, _ = self._rpc(E.PUBLISH, {"tipo": "workflow"}, body)
        return h

    # ---- consulta / operação ------------------------------------------
    def catalog(self) -> dict:
        return self._rpc(E.CATALOG_GET)[1]

    def start_occurrence(self, workflow_hash: str, inputs: dict | None = None) -> dict:
        return self._rpc(E.START_OCCURRENCE,
                         {"workflow_hash": workflow_hash, "inputs": inputs or {}})[1]

    def list_occurrences(self) -> list:
        return self._rpc(E.LIST_OCCURRENCES)[1].get("ocorrencias", [])

    def get_occurrence(self, occurrence_id: str) -> dict:
        return self._rpc(E.OCCURRENCE_GET, {"occurrence_id": occurrence_id})[1]

    def environment(self) -> dict:
        return self._rpc(E.ENVIRONMENT)[1]

    # ---- chaves de cliente (web) --------------------------------------
    def create_client(self, name: str, workflows: list) -> dict:
        """Cria uma chave (nome + segredo) com os workflows permitidos. O ack
        devolve o ``secret`` (hex) p/ distribuir ao usuário da web."""
        return self._rpc(E.CREATE_CLIENT, {"name": name, "workflows": workflows})[1]

    def update_client(self, name: str, workflows: list) -> dict:
        return self._rpc(E.UPDATE_CLIENT, {"name": name, "workflows": workflows})[1]

    def list_clients(self) -> list:
        return self._rpc(E.LIST_CLIENTS)[1].get("clients", [])
