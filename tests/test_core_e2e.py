import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass.core.core import Core, ReplyStore  # noqa: E402
from myass.edge import crypto as C  # noqa: E402
from myass.edge.gateway import Gateway  # noqa: E402
from myass.edge.locutus import MemoryLocutus  # noqa: E402
from myass.edge.registry import ClientRegistry, SeenRequests  # noqa: E402
from myass.workflow.engine import OccurrenceStore, WorkflowEngine  # noqa: E402


def wf_single():
    return {"nome": "f", "versao": "1", "raiz": {"tipo": "block", "filhos": [
        {"tipo": "action", "nome": "T",
         "bot_ref": {"project_hash": "p", "script_hash": "s"},
         "params": {"x": "$input.k"}}]}}


class FakeRegistry:
    def __init__(self, table):
        self.table = table

    def get_workflow(self, h):
        return self.table.get(h)


class RecordingBroker:
    def __init__(self):
        self.q = []

    def enqueue(self, activity):
        self.q.append(activity)
        return "C1"


class CoreE2ETest(unittest.TestCase):
    def setUp(self):
        db = mongomock.MongoClient().db
        self.broker = RecordingBroker()
        self.engine = WorkflowEngine(self.broker, OccurrenceStore(db))
        self.locutus = MemoryLocutus()
        self.clients = ClientRegistry()
        self.secret = self.clients.mint("cli")
        self.gateway = Gateway(self.locutus, self.clients, SeenRequests(db))
        self.registry = FakeRegistry({"wf-1": wf_single()})
        self.core = Core(self.gateway, self.engine, self.registry, ReplyStore(db))

    def _deposit(self, msg):
        pt = json.dumps(msg).encode()
        blob = C.seal_request(C.request_key(self.secret), pt)
        self.locutus.put(C.request_address(self.secret), blob)

    def _read_response(self):
        blob = self.locutus.get(C.response_address(self.secret))
        if blob is None:
            return None
        resp = json.loads(C.open_response(C.response_key(self.secret), blob))
        return resp["body"]  # send_response envelopa em {request_id, body}

    def test_get_starts_occurrence_and_set_returns_result(self):
        self._deposit({"request_id": "r1", "action": "start_occurrence",
                       "workflow_hash": "wf-1", "inputs": {"k": 5}})
        self.assertEqual(self.core.poll_once(), 1)        # GET entregou o pedido
        self.assertIsNone(self._read_response())          # ainda rodando, sem resposta

        # Simula o drone concluindo a atividade (o "tick" do motor).
        act = self.broker.q.pop(0)
        self.assertEqual(act["params"], {"x": 5})         # $input.k resolvido
        self.engine.activity_completed(act["occurrence_id"], act["atividade_id"],
                                       {"r": 5})
        # on_finished -> SET: o cliente puxa e decifra a resposta.
        resp = self._read_response()
        self.assertEqual(resp["status"], "done")
        self.assertEqual(resp["result"], {"r": 5})

    def test_unknown_workflow_responds_error(self):
        self._deposit({"request_id": "r2", "action": "start_occurrence",
                       "workflow_hash": "nope", "inputs": {}})
        self.core.poll_once()
        self.assertEqual(self._read_response()["erro"], "workflow não aprovado")

    def test_unknown_action_responds_error(self):
        self._deposit({"request_id": "r3", "action": "dançar", "foo": 1})
        self.core.poll_once()
        self.assertIn("ação desconhecida", self._read_response()["erro"])


if __name__ == "__main__":
    unittest.main()
