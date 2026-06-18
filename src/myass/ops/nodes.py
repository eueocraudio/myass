"""Nós operacionais — montam e fiam os componentes a partir da config.

``CoreNode`` é a Rainha viva: abre os stores (Mongo/GridFS), monta broker +
Scheduler + motor de workflow + registro de publicação + borda (GET/SET) + Core,
e sobe o servidor Noise (opcionalmente atrás de um serviço onion). ``DroneNode`` é
um drone: monta o ``ExecutorAgent`` e roda seu laço.

Toda a fiação dos callbacks vive aqui (o "main" do quadrante):
  scheduler.on_complete  → engine.on_scheduler_complete   (o "tick")
  engine.on_finished     → core._on_finished              (resposta ao cliente)
  gateway.on_request     → core._on_request               (pedido do cliente)
"""

from __future__ import annotations

import threading

from ..broker.broker import Broker
from ..broker.classes import ClassTable
from ..core.core import Core, ReplyStore
from ..edge.gateway import Gateway
from ..edge.locutus import HttpLocutus, MemoryLocutus
from ..edge.registry import ClientRegistry
from ..executor.agent import ExecutorAgent
from ..executor.project import ProjectCache
from ..noise import primitives as P
from ..publish.registry import PublishRegistry
from ..scheduler.scheduler import Scheduler
from ..scheduler.server import SchedulerServer
from ..storage.db import connect, open_stores
from ..workflow.engine import WorkflowEngine


class CoreNode:
    """A Rainha: núcleo confiável inteiro num processo."""

    def __init__(self, core_config: dict, db=None, locutus=None, blobs=None):
        db = db if db is not None else connect()
        s = open_stores(db, blobs=blobs)
        self.stores = s
        self.broker = Broker(s.backlog, ClassTable())
        self.engine = WorkflowEngine(self.broker, s.occurrences)
        self.registry = PublishRegistry(db, s.blobs)
        self.engine.exigencia_for = self.registry.exigencia_for
        self.engine.params_for = self.registry.params_for  # valida inputs na partida
        # tick: o resultado de uma atividade avança a ocorrência
        self.scheduler = Scheduler(
            self.broker, s.leases,
            on_complete=self.engine.on_scheduler_complete,
            on_logical_failure=self.engine.on_scheduler_failure)

        if locutus is None:
            url = core_config.get("locutus_url")
            locutus = HttpLocutus(url) if url else MemoryLocutus()
        self.locutus = locutus
        clients = ClientRegistry(db)
        for cid, sec in (core_config.get("clients") or {}).items():
            clients.seed(cid, bytes.fromhex(sec))  # semeia do config sem sobrescrever
        self.gateway = Gateway(locutus, clients, s.seen)
        self.core = Core(self.gateway, self.engine, self.registry, ReplyStore(db),
                         interpreter_workflow_hash=core_config.get("interpreter_workflow_hash"))

        peers = [{"id": p["id"], "pub": bytes.fromhex(p["pub"]),
                  "psk": bytes.fromhex(p["psk"]), "role": p["role"]}
                 for p in core_config["peers"]]
        self.server = SchedulerServer(
            self.scheduler, core_config["host"], core_config["port"],
            P.load_private(bytes.fromhex(core_config["scheduler_priv"])),
            bytes.fromhex(core_config["scheduler_pub"]),
            bytes.fromhex(core_config["prologue"]), peers,
            engine=self.engine, registry=self.registry, blobs=s.blobs, data=s.data,
            core=self.core)
        self.port = core_config["port"]
        self._stop = threading.Event()
        self._loops: list[threading.Thread] = []

    def start(self, run_loops: bool = True, reap_interval: float = 30.0,
              poll_interval: float = 2.0, catalog_interval: float = 21600.0,
              poll_wait: int = 0) -> int:
        """Sobe o servidor Noise. Com ``run_loops``, também os laços de fundo
        (reap de leases, polling do Locutus e republicação dos catálogos antes do
        TTL — ``catalog_interval``, default 6h, bem abaixo do TTL de 1 dia).
        ``poll_wait>0`` faz o GET usar **long-poll** (segura a conexão N s no
        servidor) — reduz a taxa de conexões ao MySQL do Locutus (evita ban)."""
        self.poll_wait = poll_wait
        self.port = self.server.start()
        if run_loops:
            self._spawn(self._reap_loop, reap_interval)
            self._spawn(self._poll_loop, poll_interval)
            self._spawn(self._catalog_loop, catalog_interval)
        return self.port

    def _spawn(self, target, interval):
        t = threading.Thread(target=target, args=(interval,), daemon=True)
        t.start()
        self._loops.append(t)

    def _reap_loop(self, interval):
        while not self._stop.is_set():
            try:
                self.scheduler.reap()
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(interval)

    def _catalog_loop(self, interval):
        # publica na partida (catálogos podem ter expirado) e antes de cada TTL.
        while not self._stop.is_set():
            try:
                self.core.publish_all_catalogs()
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(interval)

    def _poll_loop(self, interval):
        # Com long-poll (poll_wait>0) o próprio GET espera no servidor; entre
        # sweeps só um respiro curto. Sem long-poll, paceia por ``interval``.
        wait = getattr(self, "poll_wait", 0)
        while not self._stop.is_set():
            try:
                self.core.poll_once(wait=wait)
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(0.2 if wait else interval)

    # operações manuais (úteis em teste/determinismo)
    def poll_once(self):
        return self.core.poll_once()

    def reap(self):
        return self.scheduler.reap()

    def stop(self):
        self._stop.set()
        self.server.stop()


class DroneNode:
    """Um drone: o ``ExecutorAgent`` montado a partir da config."""

    def __init__(self, drone_config: dict, cache=None):
        cache = cache or ProjectCache(drone_config.get("cache_dir"))
        self.agent = ExecutorAgent(
            drone_config["endpoint"], bytes.fromhex(drone_config["prologue"]),
            P.load_private(bytes.fromhex(drone_config["static_priv"])),
            bytes.fromhex(drone_config["static_pub"]),
            bytes.fromhex(drone_config["scheduler_pub"]),
            bytes.fromhex(drone_config["psk"]),
            profile=drone_config["profile"], cache=cache)

    def connect(self):
        return self.agent.connect()

    def run(self, stop_event: threading.Event):
        self.agent.run(stop_event)

    def poll_and_run(self):
        return self.agent.poll_and_run()

    def close(self):
        self.agent.close()
