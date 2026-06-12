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
from myass.client.admin import AdminClient, AdminError  # noqa: E402
from myass.executor import project as proj  # noqa: E402
from myass.noise import primitives as P  # noqa: E402
from myass.proto import envelope as E  # noqa: E402
from myass.publish.registry import PublishRegistry  # noqa: E402
from myass.scheduler.scheduler import Scheduler  # noqa: E402
from myass.scheduler.server import SchedulerServer  # noqa: E402
from myass.scheduler.store import LeaseStore  # noqa: E402
from myass.storage.blobstore import MemoryBlobStore  # noqa: E402
from myass.workflow.engine import OccurrenceStore, WorkflowEngine  # noqa: E402

PROLOGUE = b"myass/subspace/v1"
ECHO = "import sys, json, os\ncfg=json.loads(sys.stdin.readline())\n"


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


class AdminE2ETest(unittest.TestCase):
    def setUp(self):
        db = mongomock.MongoClient().db
        broker = Broker(BacklogStore(db), classes=ClassTable(), async_load=False)
        self.blobs = MemoryBlobStore()
        self.registry = PublishRegistry(db, self.blobs)
        self.engine = WorkflowEngine(broker, OccurrenceStore(db))
        sched = Scheduler(broker, LeaseStore(db))

        self.a_priv, self.a_pub = P.generate_keypair()
        self.s_priv, self.s_pub = P.generate_keypair()
        self.psk = os.urandom(32)

        self.server = SchedulerServer(
            sched, "127.0.0.1", 0, self.s_priv, self.s_pub, PROLOGUE,
            peers=[{"id": "admin-1", "pub": self.a_pub, "psk": self.psk,
                    "role": "publicador"}],
            engine=self.engine, registry=self.registry)
        port = self.server.start()
        self.admin = AdminClient(
            {"transport": "direct", "host": "127.0.0.1", "port": port},
            PROLOGUE, self.a_priv, self.a_pub, self.s_pub, self.psk).connect()

    def tearDown(self):
        self.admin.close()
        self.server.stop()

    def _publish_demo(self):
        d = tempfile.mkdtemp(prefix="myass-admin-")
        sh = make_bot(d)
        bot = self.admin.publish_bot_dir(d)
        self.assertEqual(bot["status"], "aceito")
        wf = {"nome": "fluxo", "versao": "1",
              "raiz": {"tipo": "block", "filhos": [
                  {"tipo": "action", "nome": "T", "params": {},
                   "bot_ref": {"project_hash": bot["hash"], "script_hash": sh}}]}}
        ack = self.admin.publish_workflow(wf)
        self.assertEqual(ack["status"], "aceito")
        return bot["hash"], ack["hash"]

    def test_publish_bot_and_workflow(self):
        bot_hash, wf_hash = self._publish_demo()
        cat = self.admin.catalog()
        self.assertEqual([b["hash"] for b in cat["bots"]], [bot_hash])
        self.assertEqual([w["hash"] for w in cat["workflows"]], [wf_hash])

    def test_publish_rejects_unapproved_workflow(self):
        # Workflow apontando para um bot_ref nunca publicado -> rejeitado.
        wf = {"nome": "x", "versao": "1", "raiz": {"tipo": "block", "filhos": [
            {"tipo": "action", "nome": "T", "params": {},
             "bot_ref": {"project_hash": "blake2:nope", "script_hash": "blake2:nope"}}]}}
        ack = self.admin.publish_workflow(wf)
        self.assertEqual(ack["status"], "rejeitado")

    def test_start_and_list_occurrence(self):
        _bot, wf_hash = self._publish_demo()
        ack = self.admin.start_occurrence(wf_hash, {"k": 1})
        occ_id = ack["occurrence_id"]
        self.assertTrue(occ_id)
        occs = self.admin.list_occurrences()
        self.assertEqual([o["occurrence_id"] for o in occs], [occ_id])
        self.assertEqual(occs[0]["status"], "running")  # sem drone, fica rodando

    def test_environment_lists_blocks(self):
        env = self.admin.environment()
        self.assertEqual(env["blocks"], [])  # nenhum drone fez HELLO ainda

    def test_cross_role_denied(self):
        # Um publicador não pode pegar trabalho de drone.
        with self.assertRaises(AdminError):
            self.admin._rpc(E.WORK_GET, {"slots": 1})


if __name__ == "__main__":
    unittest.main()
