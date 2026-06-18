"""SchedulerServer — o respondedor do canal sub-espacial (lado da Rainha).

Aceita conexões, faz o handshake ``KKpsk0`` com *trial* (descobre qual peer é
pela estática+PSK que casa — identidade do handshake, nunca auto-reportada) e
roteia por **papel**:

- **executor** (drone): HELLO/WORK_GET/WORK_BEAT/RESULT/WORK_RELEASE → métodos do
  ``Scheduler``;
- **publicador** (Painel admin): PUBLISH/CATALOG_GET/START_OCCURRENCE/
  LIST_OCCURRENCES/ENVIRONMENT → ``PublishRegistry`` + ``WorkflowEngine``.

Operação fora do papel → ``DENIED`` (um drone nunca publica; um admin nunca pega
trabalho). Uma thread por conexão; sessão persistente.
"""

from __future__ import annotations

import threading

from .. import errlog
from ..noise import channel as ch
from ..proto import envelope as E
from ..workflow.inputs import InputError
from .scheduler import Scheduler

ROLE_EXECUTOR = "executor"
ROLE_PUBLICADOR = "publicador"


class SchedulerServer:
    def __init__(self, scheduler: Scheduler, host: str, port: int,
                 s_priv, s_pub: bytes, prologue: bytes, peers,
                 engine=None, registry=None, blobs=None, data=None, core=None):
        """``peers`` = iterável de dicts ``{"id", "pub", "psk", "role"}``. ``blobs``
        (BlobStore de projetos) e ``data`` (CoreDataStore) servem PROJECT_GET/DATA_*.
        ``core`` (o ``Core``) serve a gestão de chaves de cliente (CREATE/UPDATE/LIST)."""
        self.scheduler = scheduler
        self.engine = engine
        self.registry = registry
        self.blobs = blobs
        self.data = data
        self.core = core
        self.host, self.port = host, port
        self.s_priv, self.s_pub = s_priv, s_pub
        self.prologue = prologue
        self.peers = list(peers)
        self._trial = [(p["id"], p["pub"], p["psk"]) for p in self.peers]
        self._roles = {p["id"]: p.get("role", ROLE_EXECUTOR) for p in self.peers}
        self._srv = None
        self._stop = threading.Event()

    def start(self) -> int:
        self._srv = ch.listen(self.host, self.port)
        self.port = self._srv.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._srv is not None:
            self._srv.close()

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn) -> None:
        try:
            peer_id, channel = ch.respond_trial(
                conn, self.prologue, self.s_priv, self.s_pub, self._trial)
        except Exception as e:  # noqa: BLE001
            errlog.record(f"scheduler: handshake recusado: {e!r}")
            conn.close()
            return
        role = self._roles.get(peer_id, ROLE_EXECUTOR)
        try:
            while not self._stop.is_set():
                t, h, body = E.decode(channel.recv())
                channel.send(self._dispatch(peer_id, role, t, h, body))
        except (ConnectionError, OSError):
            pass
        finally:
            channel.close()

    def _dispatch(self, peer_id: str, role: str, t: str, h: dict, body: bytes) -> bytes:
        if t == E.PING:
            return E.encode(E.PONG)
        if role == ROLE_EXECUTOR:
            return self._dispatch_executor(peer_id, t, h, body)
        if role == ROLE_PUBLICADOR:
            return self._dispatch_admin(peer_id, t, h, body)
        return E.encode(E.DENIED, {"motivo": "papel desconhecido"})

    # ---- drone --------------------------------------------------------
    def _dispatch_executor(self, block_hash, t, h, body) -> bytes:
        s = self.scheduler
        if t == E.HELLO:
            cfg = s.hello(block_hash, h["profile"], h.get("capabilities"),
                          h.get("project_hashes"))
            return E.encode(E.HELLO_OK, cfg)
        if t == E.WORK_GET:
            orders = s.request_work(block_hash, int(h.get("slots", 1)))
            return E.encode(E.WORK, {"order": orders[0]}) if orders else E.encode(E.NO_WORK)
        if t == E.WORK_BEAT:
            return E.encode(s.beat(block_hash, h["atividade_id"]))
        if t == E.RESULT:
            s.result(block_hash, h["atividade_id"], h["status"],
                     h.get("output"), h.get("stderr", ""), h.get("duracao"))
            return E.encode(E.RESULT_ACK)
        if t == E.WORK_RELEASE:
            s.release(block_hash, h["atividade_id"])
            return E.encode(E.RELEASE_ACK)
        if t == E.PROJECT_GET:
            tar = self.blobs.get(h["project_hash"]) if self.blobs else None
            if tar is None:
                return E.encode(E.PROJECT_MISS, {"project_hash": h["project_hash"]})
            return E.encode(E.PROJECT_DATA, {"project_hash": h["project_hash"]}, tar)
        if t == E.DATA_GET:
            try:
                data = self.data.get(h["data_ref"]) if self.data else None
            except KeyError:
                data = None
            if data is None:
                return E.encode(E.DATA_MISS, {"data_ref": h["data_ref"]})
            return E.encode(E.DATA_CHUNK, {"data_ref": h["data_ref"]}, data)
        if t == E.DATA_PUT:
            ref = self.data.put(body) if self.data else None  # content-addressed
            return E.encode(E.DATA_ACK, {"data_ref": ref})
        return E.encode(E.DENIED, {"motivo": f"executor não pode {t}"})

    # ---- admin --------------------------------------------------------
    def _dispatch_admin(self, publicador, t, h, body) -> bytes:
        if self.registry is None or self.engine is None:
            return E.encode(E.DENIED, {"motivo": "núcleo sem registry/engine"})
        if t == E.PUBLISH:
            return self._handle_publish(publicador, h, body)
        if t == E.CATALOG_GET:
            return E.encode(E.CATALOG, self.registry.catalog())
        if t == E.START_OCCURRENCE:
            template = self.registry.get_workflow(h["workflow_hash"])
            if template is None:
                return E.encode(E.START_ACK, {"erro": "workflow não aprovado"})
            try:
                occ_id = self.engine.start(template, h.get("inputs", {}))
            except InputError as e:
                return E.encode(E.START_ACK, {"erro": f"input inválido: {e}"})
            return E.encode(E.START_ACK, {"occurrence_id": occ_id})
        if t == E.LIST_OCCURRENCES:
            return E.encode(E.OCCURRENCES, {"ocorrencias": self.engine.store.recent()})
        if t == E.OCCURRENCE_GET:
            info = self.engine.store.detail(h.get("occurrence_id", ""))
            return E.encode(E.OCCURRENCE_INFO,
                            info or {"erro": "ocorrência não encontrada"})
        if t == E.ENVIRONMENT:
            return E.encode(E.ENV_INFO, {"blocks": self.scheduler.store.list_inventory()})
        if t in (E.CREATE_CLIENT, E.UPDATE_CLIENT, E.LIST_CLIENTS):
            if self.core is None:
                return E.encode(E.DENIED, {"motivo": "núcleo sem gestão de chaves"})
            if t == E.LIST_CLIENTS:
                return E.encode(E.CLIENTS, {"clients": self.core.list_clients()})
            try:
                if t == E.CREATE_CLIENT:
                    secret = self.core.create_client(h["name"], h.get("workflows"))
                    return E.encode(E.CLIENT_ACK, {"name": h["name"], "secret": secret.hex()})
                self.core.update_client(h["name"], h.get("workflows"))
                return E.encode(E.CLIENT_ACK, {"name": h["name"], "status": "atualizado"})
            except ValueError as e:
                return E.encode(E.CLIENT_ACK, {"erro": str(e)})
        return E.encode(E.DENIED, {"motivo": f"publicador não pode {t}"})

    def _handle_publish(self, publicador, h, body) -> bytes:
        try:
            import json
            if h.get("tipo") == "workflow":
                hash_ = self.registry.publish_workflow(json.loads(body.decode("utf-8")),
                                                       publicado_por=publicador)
            else:
                hash_ = self.registry.publish_bot(body, publicado_por=publicador)
            return E.encode(E.PUBLISH_ACK, {"hash": hash_, "status": "aceito"})
        except Exception as e:  # noqa: BLE001
            errlog.record(f"publish recusado de {publicador}: {e!r}")
            return E.encode(E.PUBLISH_ACK, {"status": "rejeitado", "motivo": str(e)})
