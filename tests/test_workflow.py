import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass.workflow.engine import (  # noqa: E402
    STATUS_DONE, STATUS_FAILED, OccurrenceStore, WorkflowEngine,
)


# ---- helpers de template ----------------------------------------------
def action(nome, task, params=None, **kw):
    n = {"tipo": "action", "nome": nome,
         "bot_ref": {"project_hash": "p", "script_hash": task},
         "params": params if params is not None else {}}
    n.update(kw)
    return n


def decision(nome, task, rotas, params=None, **kw):
    n = {"tipo": "decision", "nome": nome,
         "bot_ref": {"project_hash": "p", "script_hash": task},
         "params": params if params is not None else {}, "rotas": rotas}
    n.update(kw)
    return n


def loop(nome, array, item, corpo, **kw):
    n = {"tipo": "loop", "nome": nome, "array": array, "item": item, "corpo": corpo}
    n.update(kw)
    return n


def block(*filhos):
    return {"tipo": "block", "filhos": list(filhos)}


def wf(*filhos):
    return {"raiz": block(*filhos)}


IGNORAR = [{"match": "*", "disposicao": "ignorar"}]


class Fail:
    def __init__(self, payload=None, motivo="erro_logico"):
        self.payload = payload or {"erro": "x"}
        self.motivo = motivo


class RecordingBroker:
    def __init__(self):
        self.q = []

    def enqueue(self, activity):
        self.q.append(activity)
        return "C1"


class EngineTestBase(unittest.TestCase):
    def setUp(self):
        self.broker = RecordingBroker()
        db = mongomock.MongoClient().db
        self.engine = WorkflowEngine(self.broker, OccurrenceStore(db))

    def drive(self, template, inputs, responder):
        occ_id = self.engine.start(template, inputs)
        store = self.engine.store
        guard = 0
        while True:
            occ = store.get(occ_id)
            if occ["status"] != "running":
                return occ
            self.assertTrue(self.broker.q, "travou sem atividades e não concluiu")
            act = self.broker.q.pop(0)
            r = responder(act["bot_ref"]["script_hash"], act["params"])
            if isinstance(r, Fail):
                self.engine.activity_failed(occ_id, act["atividade_id"], r.motivo, r.payload)
            else:
                self.engine.activity_completed(occ_id, act["atividade_id"], r)
            guard += 1
            self.assertLess(guard, 1000, "loop infinito")


class TestOriginFilter(EngineTestBase):
    def test_internal_occurrences_hidden_from_recent(self):
        # ocorrência de topo (humana) aparece; interna (ex.: VAI) não.
        u = self.engine.start(wf(), {}, origin="user")
        i = self.engine.start(wf(), {}, origin="internal")
        ids = [o["occurrence_id"] for o in self.engine.store.recent()]
        self.assertIn(u, ids)
        self.assertNotIn(i, ids)


class TestLinear(EngineTestBase):
    def test_block_sequence_and_prev(self):
        t = wf(action("A", "A", {"x": 1}), action("B", "B", "$prev"))

        def resp(task, params):
            return {"a": 1} if task == "A" else {"got": params}

        occ = self.drive(t, {}, resp)
        self.assertEqual(occ["status"], STATUS_DONE)
        self.assertEqual(occ["result"], {"got": {"a": 1}})


class TestLoop(EngineTestBase):
    def test_foreach_fanout_and_join(self):
        t = wf(
            action("L1", "L1"),
            loop("L2", "$node.L1.items", "x", block(action("C", "C", {"v": "$item"}))),
            action("D", "D", {"all": "$node.L2.join"}),
        )
        seen = []

        def resp(task, params):
            if task == "L1":
                return {"items": [10, 20, 30]}
            if task == "C":
                seen.append(params["v"])
                return {"sq": params["v"]}
            return {"d": params["all"]}

        occ = self.drive(t, {}, resp)
        self.assertEqual(occ["status"], STATUS_DONE)
        self.assertCountEqual(seen, [10, 20, 30])  # fan-out: uma cópia por item
        self.assertEqual(occ["result"]["d"], [{"sq": 10}, {"sq": 20}, {"sq": 30}])

    def test_empty_array_skips_loop(self):
        t = wf(action("L1", "L1"),
               loop("L2", "$node.L1.items", "x", block(action("C", "C"))),
               action("D", "D", {"all": "$node.L2.join"}))

        def resp(task, params):
            if task == "L1":
                return {"items": []}
            if task == "C":
                raise AssertionError("corpo não deveria rodar com array vazio")
            return {"d": params["all"]}

        occ = self.drive(t, {}, resp)
        self.assertEqual(occ["result"]["d"], [])


class TestDecision(EngineTestBase):
    def test_routes_by_label(self):
        t = wf(
            decision("DEC", "DEC", {"yes": block(action("E", "E")),
                                    "no": block(action("F", "F"))}),
            action("G", "G"),
        )
        ran = []

        def resp(task, params):
            if task == "DEC":
                return {"label": "yes"}
            ran.append(task)
            return {task: True}

        occ = self.drive(t, {}, resp)
        self.assertEqual(occ["status"], STATUS_DONE)
        self.assertIn("E", ran)
        self.assertNotIn("F", ran)  # rota 'no' não executa
        self.assertIn("G", ran)     # converge de volta

    def test_unmapped_label_fails(self):
        t = wf(decision("DEC", "DEC", {"yes": block(action("E", "E"))}))

        def resp(task, params):
            return {"label": "talvez"}

        occ = self.drive(t, {}, resp)
        self.assertEqual(occ["status"], STATUS_FAILED)


class TestCatch(EngineTestBase):
    def test_action_catch_ignore_keeps_prev(self):
        t = wf(action("C1", "C1"),
               action("BAD", "BAD", "$prev", catch=IGNORAR),
               action("E", "E", "$prev"))

        def resp(task, params):
            if task == "C1":
                return {"c": 1}
            if task == "BAD":
                return Fail()  # falha -> ignorada
            return {"got": params}

        occ = self.drive(t, {}, resp)
        self.assertEqual(occ["status"], STATUS_DONE)
        # E recebe o prev de C1 (BAD foi engolida, prev inalterado).
        self.assertEqual(occ["result"], {"got": {"c": 1}})

    def test_propagate_fails_occurrence(self):
        t = wf(action("C1", "C1"), action("BAD", "BAD"))

        def resp(task, params):
            return {"c": 1} if task == "C1" else Fail(motivo="erro_logico")

        occ = self.drive(t, {}, resp)
        self.assertEqual(occ["status"], STATUS_FAILED)
        self.assertEqual(occ["fail"]["motivo"], "erro_logico")

    def test_loop_catch_ignore_substitutes_join_item(self):
        # catch no NÓ do loop: um item que falha vira o payload no array do join.
        t = wf(action("L1", "L1"),
               loop("L2", "$node.L1.items", "x",
                    block(action("C", "C", {"v": "$item"})), catch=IGNORAR),
               action("D", "D", {"all": "$node.L2.join"}))

        def resp(task, params):
            if task == "L1":
                return {"items": [1, 2]}
            if task == "C":
                return Fail(payload={"erro": "boom"}) if params["v"] == 2 else {"sq": 1}
            return {"d": params["all"]}

        occ = self.drive(t, {}, resp)
        self.assertEqual(occ["status"], STATUS_DONE)
        joined = occ["result"]["d"]
        self.assertEqual(joined[0], {"sq": 1})
        self.assertEqual(joined[1]["erro"], "boom")  # item 2 substituído pelo payload


class TestBotCveShape(EngineTestBase):
    def test_full_bot_cve_workflow(self):
        body = block(
            action("Task03", "t3", {"cve": "$item"}),
            action("Task04", "t4", "$prev"),
            action("Task05", "t5", "$prev"),
            action("Task06", "t6", "$prev", catch=IGNORAR),
            action("Task07", "t7", "$prev"),
            action("Task08", "t8", "$prev"),
        )
        t = wf(
            action("Task01", "t1", {"texto": "$input.texto"}),
            loop("Task02", "$node.Task01.cves", "cve", body),
            action("Task09", "t9", {"cves": "$node.Task02.join"}),
            action("Task10", "t10", "$node.Task09"),
        )

        def resp(task, params):
            if task == "t1":
                return {"cves": ["CVE-1", "CVE-2"]}
            if task == "t3":
                return {"cve": params["cve"]}
            if task == "t4":
                return {**params, "kev": True}
            if task == "t5":
                return {**params, "exp": []}
            if task == "t6":
                return Fail()  # download de refs falha -> catch ignorar
            if task == "t7":
                return {**params, "ent": []}
            if task == "t8":
                return {**params, "saved": True}
            if task == "t9":
                return {"rel": params["cves"]}
            if task == "t10":
                return {"pdf_path": "/tmp/x.pdf", "n": len(params["rel"])}
            raise AssertionError(task)

        occ = self.drive(t, {"texto": "achei CVE-1 e CVE-2"}, resp)
        self.assertEqual(occ["status"], STATUS_DONE)
        self.assertEqual(occ["result"], {"pdf_path": "/tmp/x.pdf", "n": 2})
        rel = occ["node_outputs"]["Task02"]["join"]
        self.assertEqual(len(rel), 2)
        for doc in rel:
            self.assertTrue(doc["saved"])
            self.assertTrue(doc["kev"])
            self.assertNotIn("refs", doc)  # Task06 foi ignorada


if __name__ == "__main__":
    unittest.main()
