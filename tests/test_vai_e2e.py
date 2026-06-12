"""Caminho do pedido em LINGUAGEM NATURAL (drone VAI).

cliente "interpret" {texto} → Core dispara o workflow interpretador (BOT VAI) →
o VAI devolve o PLANO {workflow_hash, inputs} → a Rainha VALIDA no registro e só
então dispara o workflow real → resultado volta ao cliente. Hallucination/prompt
-injection não executa hash não aprovado.
"""

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

INTERP_HASH = "blake2:interp"
REAL_HASH = "blake2:real"


def one_action(nome, params=None):
    return {"nome": nome, "versao": "1", "raiz": {"tipo": "block", "filhos": [
        {"tipo": "action", "nome": "T",
         "bot_ref": {"project_hash": "p", "script_hash": nome},
         "params": params or {}}]}}


class FakeRegistry:
    def __init__(self):
        self.t = {
            INTERP_HASH: one_action("vai", {"texto": "$input.texto",
                                            "catalogo": "$input.catalogo"}),
            REAL_HASH: one_action("real"),
        }

    def get_workflow(self, h):
        return self.t.get(h)

    def catalog(self):
        return {"workflows": [{"hash": REAL_HASH, "label": "fluxo real"}], "bots": []}


class RecordingBroker:
    def __init__(self):
        self.q = []

    def enqueue(self, a):
        self.q.append(a)
        return "C1"


class VaiE2ETest(unittest.TestCase):
    def setUp(self):
        db = mongomock.MongoClient().db
        self.broker = RecordingBroker()
        self.engine = WorkflowEngine(self.broker, OccurrenceStore(db))
        self.locutus = MemoryLocutus()
        self.clients = ClientRegistry()
        self.secret = self.clients.mint("cli")
        self.gateway = Gateway(self.locutus, self.clients, SeenRequests(db))
        self.core = Core(self.gateway, self.engine, FakeRegistry(), ReplyStore(db),
                         interpreter_workflow_hash=INTERP_HASH)

    def _deposit(self, msg):
        self.locutus.put(C.request_address(self.secret),
                         C.seal_request(C.request_key(self.secret), json.dumps(msg).encode()))

    def _resp(self):
        blob = self.locutus.get(C.response_address(self.secret))
        return json.loads(C.open_response(C.response_key(self.secret), blob))["body"] if blob else None

    def _complete_next(self, output):
        act = self.broker.q.pop(0)
        self.engine.activity_completed(act["occurrence_id"], act["atividade_id"], output)
        return act

    def test_natural_language_request_runs_real_workflow(self):
        self._deposit({"request_id": "r1", "action": "interpret",
                       "texto": "rode o fluxo real, por favor"})
        self.assertEqual(self.core.poll_once(), 1)

        # 1) o VAI roda e devolve o PLANO (vê o catálogo, escolhe o workflow).
        vai = self.broker.q[0]
        self.assertEqual(vai["params"]["texto"], "rode o fluxo real, por favor")
        self.assertEqual(vai["params"]["catalogo"][0]["hash"], REAL_HASH)
        self._complete_next({"workflow_hash": REAL_HASH, "inputs": {"x": 1}})

        # 2) a Rainha validou o hash e disparou o workflow REAL.
        self.assertIsNone(self._resp())  # ainda sem resposta (real rodando)
        real = self.broker.q[0]
        self.assertEqual(real["bot_ref"]["script_hash"], "real")
        self._complete_next({"feito": True})

        # 3) resultado do workflow real volta ao cliente.
        self.assertEqual(self._resp(), {"occurrence_id": self._resp()["occurrence_id"],
                                        "status": "done", "result": {"feito": True},
                                        "fail": None})

    def test_unapproved_plan_is_not_executed(self):
        self._deposit({"request_id": "r2", "action": "interpret", "texto": "hack"})
        self.core.poll_once()
        # VAI (alucinado/injetado) sugere um hash não aprovado.
        self._complete_next({"workflow_hash": "blake2:NAO-APROVADO", "inputs": {}})
        # Nada de workflow real enfileirado; cliente recebe a interpretação (não execução).
        self.assertEqual(self.broker.q, [])
        self.assertIn("interpretacao", self._resp())


if __name__ == "__main__":
    unittest.main()
