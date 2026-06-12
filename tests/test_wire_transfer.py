import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass.broker.broker import Broker  # noqa: E402
from myass.broker.classes import ClassTable  # noqa: E402
from myass.broker.store import BacklogStore  # noqa: E402
from myass.executor import project as proj  # noqa: E402
from myass.executor.agent import ExecutorAgent  # noqa: E402
from myass.executor.project import ProjectCache  # noqa: E402
from myass.noise import primitives as P  # noqa: E402
from myass.proto import envelope as E  # noqa: E402
from myass.scheduler import states  # noqa: E402
from myass.scheduler.scheduler import Scheduler  # noqa: E402
from myass.scheduler.server import SchedulerServer  # noqa: E402
from myass.scheduler.store import LeaseStore  # noqa: E402
from myass.storage.blobstore import CoreDataStore, MemoryBlobStore  # noqa: E402

PROLOGUE = b"myass/subspace/v1"
BIG = {"mem_mb": 32768, "cpu_cores": 16}
LIGHT = {"mem_mb": 256, "cpu_cores": 1}
ECHO = ("import sys, json, os\n"
        "cfg=json.loads(sys.stdin.readline())\n"
        "wd=cfg['workdir']\n"
        "inp=json.load(open(os.path.join(wd,'input.json')))\n"
        "json.dump({'echo': inp['params']}, open(os.path.join(wd,'output.json'),'w'))\n")


def make_bot(root):
    os.makedirs(os.path.join(root, "scripts"))
    entry = "scripts/echo.py"
    with open(os.path.join(root, entry), "w") as f:
        f.write(ECHO)
    sh = proj.file_hash(os.path.join(root, entry))
    manifest = {"manifest_version": 1, "nome": "demo", "versao": "1",
                "requirements": {},
                "scripts": {"echo": {"entrypoint": entry, "script_hash": sh}}}
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump(manifest, f, sort_keys=True, indent=2)
    return sh


class WireTransferTest(unittest.TestCase):
    def setUp(self):
        db = mongomock.MongoClient().db
        self.broker = Broker(BacklogStore(db), classes=ClassTable(), async_load=False)
        self.leases = LeaseStore(db)
        self.completed = []
        self.sched = Scheduler(self.broker, self.leases,
                               on_complete=lambda l, o: self.completed.append((l["_id"], o)))
        self.blobs = MemoryBlobStore()
        self.data = CoreDataStore(self.blobs)

        # Projeto só no núcleo (GridFS/blobs) — o drone NÃO tem em cache.
        d = tempfile.mkdtemp(prefix="myass-bot-")
        self.sh = make_bot(d)
        self.ph = proj.tree_hash(d)
        self.blobs.put(self.ph, proj.pack(d))

        self.d_priv, self.d_pub = P.generate_keypair()
        self.s_priv, self.s_pub = P.generate_keypair()
        self.psk = os.urandom(32)
        self.server = SchedulerServer(
            self.sched, "127.0.0.1", 0, self.s_priv, self.s_pub, PROLOGUE,
            peers=[{"id": "blk", "pub": self.d_pub, "psk": self.psk, "role": "executor"}],
            blobs=self.blobs, data=self.data)
        port = self.server.start()

        self.agent = ExecutorAgent(
            {"transport": "direct", "host": "127.0.0.1", "port": port},
            PROLOGUE, self.d_priv, self.d_pub, self.s_pub, self.psk, profile=BIG,
            cache=ProjectCache(tempfile.mkdtemp(prefix="myass-cache-")))
        self.agent.connect()

    def tearDown(self):
        self.agent.close()
        self.server.stop()

    def test_drone_downloads_project_via_wire_and_runs(self):
        self.broker.enqueue({"atividade_id": "atv-1", "occurrence_id": "occ-1",
                             "exigencia": LIGHT, "params": {"n": 7},
                             "bot_ref": {"project_hash": self.ph, "script_hash": self.sh}})
        aid = self.agent.poll_and_run()  # resolver -> PROJECT_GET -> cache -> roda
        self.assertEqual(aid, "atv-1")
        self.assertEqual(self.leases.get_lease("atv-1")["state"], states.CONCLUIDA)
        self.assertEqual(self.completed, [("atv-1", {"echo": {"n": 7}})])

    def test_data_put_get_roundtrip_over_wire(self):
        blob = b"ARTEFATO-GRANDE" * 5000  # vários blocos Noise
        ref = self.agent.data_store.put(blob)      # DATA_PUT
        self.assertEqual(self.agent.data_store.get(ref), blob)  # DATA_GET
        # E o núcleo guardou content-addressed (mesmo ref do lado de cá).
        self.assertEqual(self.data.get(ref), blob)

    def test_project_miss_for_unknown_hash(self):
        with self.assertRaises(KeyError):
            self.agent.download(E.PROJECT_GET, {"project_hash": "blake2:naoexiste"})


if __name__ == "__main__":
    unittest.main()
