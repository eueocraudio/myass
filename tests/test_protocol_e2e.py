"""End-to-end: drone (ExecutorAgent) <-> Noise <-> SchedulerServer <-> broker.

Fecha o ciclo enqueue -> dispatch -> executa script -> RESULT -> conclui, tudo
in-process: o broker e o scheduler reais (mongomock), o servidor Noise numa
thread, e o agente do drone conectando pelo transporte direto (127.0.0.1).
"""

import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass.broker.broker import Broker  # noqa: E402
from myass.broker.classes import ClassTable  # noqa: E402
from myass.broker.store import BacklogStore  # noqa: E402
from myass.executor import MemoryDataStore  # noqa: E402
from myass.executor.agent import ExecutorAgent, MappingResolver  # noqa: E402
from myass.noise import primitives as P  # noqa: E402
from myass.scheduler import states  # noqa: E402
from myass.scheduler.scheduler import Scheduler  # noqa: E402
from myass.scheduler.server import SchedulerServer  # noqa: E402
from myass.scheduler.store import LeaseStore  # noqa: E402

PROLOGUE = b"myass/subspace/v1"
BIG = {"mem_mb": 32768, "cpu_cores": 16}
LIGHT = {"mem_mb": 256, "cpu_cores": 1}
SCRIPT_HASH = "blake2:echo-script"

ECHO = """
import sys, json, os
cfg = json.loads(sys.stdin.readline())
wd = cfg["workdir"]
inp = json.load(open(os.path.join(wd, "input.json")))
json.dump({"echo": inp["params"], "occ": inp["occurrence_id"]},
          open(os.path.join(wd, "output.json"), "w"))
"""

SLEEP = """
import sys, json, time, os
cfg = json.loads(sys.stdin.readline())
time.sleep(0.6)
wd = cfg["workdir"]
json.dump({"ok": True}, open(os.path.join(wd, "output.json"), "w"))
"""


def activity(i, exig=LIGHT):
    return {"atividade_id": f"atv-{i}", "occurrence_id": f"occ-{i}",
            "exigencia": exig, "bot_ref": {"project_hash": "p", "script_hash": SCRIPT_HASH},
            "params": {"n": i}}


class ProtocolE2ETest(unittest.TestCase):
    def setUp(self):
        db = mongomock.MongoClient().db
        self.broker = Broker(BacklogStore(db), classes=ClassTable(), async_load=False)
        self.leases = LeaseStore(db)
        self.completed = []
        self.sched = Scheduler(
            self.broker, self.leases, default_lease_s=120,
            on_complete=lambda lease, out: self.completed.append((lease["_id"], out)),
        )

        # Chaves estáticas (provisionadas out-of-band) + PSK por par.
        self.drone_priv, self.drone_pub = P.generate_keypair()
        self.sched_priv, self.sched_pub = P.generate_keypair()
        self.psk = os.urandom(32)
        self.block_hash = "blk-001"

        self.server = SchedulerServer(
            self.sched, "127.0.0.1", 0, self.sched_priv, self.sched_pub, PROLOGUE,
            peers=[{"id": self.block_hash, "pub": self.drone_pub, "psk": self.psk,
                    "role": "executor"}])
        self.port = self.server.start()

        # Script local + resolver (a fatia de projeto/venv plugaria aqui).
        self.scripts = tempfile.mkdtemp(prefix="myass-e2e-")
        self.agent = None

    def tearDown(self):
        if self.agent:
            self.agent.close()
        self.server.stop()

    def make_agent(self, beat_interval=30.0):
        entry = os.path.join(self.scripts, "s.py")
        with open(entry, "w") as f:
            f.write(self._script)
        resolver = MappingResolver({SCRIPT_HASH: (sys.executable, entry)})
        self.agent = ExecutorAgent(
            endpoint={"transport": "direct", "host": "127.0.0.1", "port": self.port},
            prologue=PROLOGUE, s_priv=self.drone_priv, s_pub=self.drone_pub,
            scheduler_pub=self.sched_pub, psk=self.psk, resolver=resolver,
            data_store=MemoryDataStore(), profile=BIG, beat_interval=beat_interval)
        return self.agent

    def test_hello_and_no_work(self):
        self._script = ECHO
        agent = self.make_agent()
        cfg = agent.connect()
        self.assertEqual(cfg["t"], "HELLO_OK")
        self.assertIn("lease_s", cfg)
        # Fila vazia -> NO_WORK.
        self.assertIsNone(agent.poll_and_run())

    def test_full_cycle_enqueue_to_complete(self):
        self._script = ECHO
        self.broker.enqueue(activity(1))
        agent = self.make_agent()
        agent.connect()
        aid = agent.poll_and_run()
        self.assertEqual(aid, "atv-1")
        # O Scheduler concluiu o lease com o output do script.
        self.assertEqual(self.leases.get_lease("atv-1")["state"], states.CONCLUIDA)
        self.assertEqual(self.completed, [("atv-1", {"echo": {"n": 1}, "occ": "occ-1"})])

    def test_wrong_psk_is_rejected(self):
        self._script = ECHO
        agent = self.make_agent()
        agent.psk = os.urandom(32)  # PSK não provisionada -> handshake recusado
        with self.assertRaises((ConnectionError, OSError)):
            agent.connect()

    def test_long_activity_renews_lease_via_beats(self):
        # beat curto + script que dorme: o laço de beat roda e o lease é renovado;
        # a atividade conclui ok mesmo durando mais que um intervalo de beat.
        self._script = SLEEP
        self.broker.enqueue(activity(2))
        agent = self.make_agent(beat_interval=0.05)
        agent.connect()
        aid = agent.poll_and_run()
        self.assertEqual(aid, "atv-2")
        self.assertEqual(self.leases.get_lease("atv-2")["state"], states.CONCLUIDA)


if __name__ == "__main__":
    unittest.main()
