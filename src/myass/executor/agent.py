"""ExecutorAgent — o laço de protocolo do drone sobre o canal Noise.

Fecha o ciclo: disca para o Scheduler (transporte plugável), faz o handshake
``KKpsk0``, abre a sessão com ``HELLO`` e então puxa trabalho e o executa pelo
runner local, renovando o lease com ``WORK_BEAT`` e devolvendo o ``RESULT``.

- **Sessão persistente** com reconexão (backoff): montar o transporte custa, então
  a conexão fica viva; caiu → reconecta, refaz handshake + HELLO.
- **Slots = 1** nesta fatia (uma atividade por vez): o protocolo é request/response
  sequencial; o beat é enviado entre verificações enquanto o filho roda.
- O que rodar (interpretador + entrypoint) vem de um ``Resolver`` injetável — a
  camada de projeto/venv (PROJECT_GET + hash em árvore) é uma fatia à parte que
  implementa essa interface; aqui um ``MappingResolver`` basta para drones locais
  e testes.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol

from .. import errlog
from ..noise import channel as ch
from ..proto import envelope as E
from .dataplane import DataStore, compute_ref
from .project import ProjectCache, ProjectMissing, ProjectResolver
from .runner import ActivityRunner


class ProtocolError(Exception):
    pass


class Resolver(Protocol):
    def resolve(self, bot_ref: dict) -> tuple[str, str]:
        """Devolve (interpretador, entrypoint) para um ``bot_ref``."""
        ...


class MappingResolver:
    """Resolve ``bot_ref`` -> (interpretador, entrypoint) por ``script_hash``."""

    def __init__(self, by_script_hash: dict[str, tuple[str, str]]):
        self._m = by_script_hash

    def resolve(self, bot_ref: dict) -> tuple[str, str]:
        return self._m[bot_ref["script_hash"]]


class WireSource:
    """Fonte de projeto sobre o canal (PROJECT_GET → tar). Só chamada no laço
    principal do agente (sem concorrência com os beats)."""

    def __init__(self, agent: "ExecutorAgent"):
        self.agent = agent

    def fetch(self, project_hash: str) -> bytes:
        try:
            return self.agent.download(E.PROJECT_GET, {"project_hash": project_hash})
        except KeyError:
            raise ProjectMissing(project_hash)


class WireDataStore:
    """Plano de dados sobre o canal (DATA_GET/DATA_PUT). Content-addressed; só
    chamado no laço principal (em ``prepare``/``collect``, fora da thread do filho)."""

    def __init__(self, agent: "ExecutorAgent"):
        self.agent = agent

    def put(self, data: bytes) -> str:
        ref = compute_ref(data)
        self.agent.upload(E.DATA_PUT, {"data_ref": ref, "tamanho": len(data)}, data)
        return ref

    def get(self, data_ref: str) -> bytes:
        data = self.agent.download(E.DATA_GET, {"data_ref": data_ref})
        if compute_ref(data) != data_ref:
            raise ValueError(f"artefato não confere com {data_ref}")
        return data


class ExecutorAgent:
    def __init__(self, endpoint: dict, prologue: bytes, s_priv, s_pub: bytes,
                 scheduler_pub: bytes, psk: bytes, profile: dict,
                 resolver: Resolver | None = None, data_store: DataStore | None = None,
                 cache: ProjectCache | None = None,
                 capabilities: list | None = None, project_hashes: list | None = None,
                 beat_interval: float = 30.0, poll_interval: float = 2.0):
        self.endpoint = endpoint
        self.prologue = prologue
        self.s_priv, self.s_pub = s_priv, s_pub
        self.scheduler_pub = scheduler_pub
        self.psk = psk
        # Produção: fontes "de fio" (projeto via PROJECT_GET, dados via DATA_*).
        # Testes podem injetar resolver/data_store locais.
        self.data_store = data_store or WireDataStore(self)
        self.resolver = resolver or ProjectResolver(cache or ProjectCache(),
                                                    WireSource(self))
        self.runner = ActivityRunner(self.data_store)
        self.profile = profile
        self.capabilities = capabilities or []
        self.project_hashes = project_hashes or []
        self.beat_interval = beat_interval
        self.poll_interval = poll_interval
        self.channel: ch.NoiseChannel | None = None
        self.config: dict = {}

    # ---- sessão --------------------------------------------------------
    def connect(self) -> dict:
        """Abre transporte + handshake + HELLO. Devolve a config (HELLO_OK)."""
        sock = ch.connect(self.endpoint)
        self.channel = ch.initiate(sock, self.prologue, self.s_priv, self.s_pub,
                                   self.scheduler_pub, self.psk)
        self._send(E.HELLO, {"profile": self.profile, "capabilities": self.capabilities,
                             "project_hashes": self.project_hashes, "slots": 1})
        t, h, _ = self._recv()
        if t != E.HELLO_OK:
            raise ProtocolError(f"esperava HELLO_OK, veio {t}")
        self.config = h
        return h

    def close(self) -> None:
        if self.channel is not None:
            self.channel.close()
            self.channel = None

    def _send(self, t, fields=None, body=b"") -> None:
        self.channel.send(E.encode(t, fields, body))

    def _recv(self):
        return E.decode(self.channel.recv())

    def download(self, t: str, fields: dict) -> bytes:
        """RPC de download (PROJECT_GET/DATA_GET). Transferência em um record (o
        enquadramento Noise já fatia em blocos). MISS -> KeyError."""
        self._send(t, fields)
        rt, _h, body = self._recv()
        if rt in (E.PROJECT_MISS, E.DATA_MISS):
            raise KeyError(fields)
        return body

    def upload(self, t: str, fields: dict, data: bytes) -> None:
        """RPC de upload (DATA_PUT). Espera o ACK."""
        self._send(t, fields, data)
        self._recv()

    # ---- um ciclo de trabalho ------------------------------------------
    def poll_and_run(self):
        """Puxa uma atividade e a executa, devolvendo o RESULT. Retorna o
        ``atividade_id`` processado, ou ``None`` se NO_WORK.

        O canal é usado **só aqui no laço principal** (resolver/PROJECT_GET,
        prepare/DATA_GET, beats, collect/DATA_PUT, RESULT). A thread do filho
        (``execute``) não toca o canal — sem contenção com os beats.
        """
        self._send(E.WORK_GET, {"slots": 1})
        t, h, _ = self._recv()
        if t == E.NO_WORK:
            return None
        if t != E.WORK:
            raise ProtocolError(f"esperava WORK/NO_WORK, veio {t}")

        order = h["order"]
        aid = order["atividade_id"]
        interpreter, entrypoint = self.resolver.resolve(order["bot_ref"])  # PROJECT_GET
        prepared = self.runner.prepare(order)                              # DATA_GET (inputs)

        cancel = threading.Event()
        holder: dict = {}

        def work():
            holder["raw"] = self.runner.execute(prepared, interpreter, entrypoint,
                                                cancel_event=cancel)

        start = time.monotonic()
        th = threading.Thread(target=work)
        th.start()
        while True:                       # beats enquanto o filho roda (canal livre)
            th.join(self.beat_interval)
            if not th.is_alive():
                break
            self._send(E.WORK_BEAT, {"atividade_id": aid})
            bt, _, _ = self._recv()
            if bt == E.WORK_CANCEL:
                cancel.set()

        res = self.runner.collect(prepared, holder["raw"],
                                  time.monotonic() - start)                # DATA_PUT (outputs)
        self._send(E.RESULT, {"atividade_id": aid, "status": res.status,
                              "output": res.output, "stderr": res.stderr,
                              "duracao": res.duracao})
        self._recv()  # RESULT_ACK
        return aid

    # ---- loop com reconexão --------------------------------------------
    def run(self, stop_event: threading.Event) -> None:
        """Roda até ``stop_event``. Sessão persistente com reconexão por backoff;
        trabalho em voo sobrevive porque o lease/idempotência cobrem duplicatas."""
        while not stop_event.is_set():
            try:
                if self.channel is None:
                    self.connect()
                if self.poll_and_run() is None:
                    stop_event.wait(self.poll_interval)  # NO_WORK -> backoff
            except (ConnectionError, OSError, ProtocolError) as e:
                errlog.record(f"executor: sessão caiu ({e!r}); reconectando")
                self.close()
                stop_event.wait(self.poll_interval)
