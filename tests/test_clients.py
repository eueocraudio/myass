"""Chaves de cliente: registro persistente (nome + workflows permitidos),
autorização por chave e publicação do catálogo selado no Locutus."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass.core.core import Core, ReplyStore  # noqa: E402
from myass.edge import crypto  # noqa: E402
from myass.edge.locutus import MemoryLocutus  # noqa: E402
from myass.edge.registry import ClientRegistry  # noqa: E402

WF_A = "blake2:aaaa"
WF_B = "blake2:bbbb"
CATALOG = [{"hash": WF_A, "nome": "wfA", "versao": "1.0"},
           {"hash": WF_B, "nome": "wfB", "versao": "2.0"}]


class _Gateway:
    def __init__(self, db):
        self.store = MemoryLocutus()
        self.registry = ClientRegistry(db)
        self.on_request = None
        self.responses = []

    def send_response(self, client_id, request_id, body):
        self.responses.append((client_id, request_id, body))


class _Store:
    def recent_for(self, client_id, limit=50):
        return [{"occurrence_id": "occ-1", "status": "done", "workflow": "wfA v1.0"}]

    def detail(self, occ_id):
        return {"occurrence_id": occ_id, "status": "done",
                "node_status": {"T1": "done"}, "result": {"ok": 1}}


class _Engine:
    on_finished = None
    store = _Store()

    def start(self, *a, **k):  # só chamado no caminho autorizado
        raise AssertionError("engine.start não deveria ser chamado")


class _Pub:
    def catalog(self):
        return {"workflows": CATALOG}

    def get_workflow(self, h):
        return {"raiz": {}} if any(w["hash"] == h for w in CATALOG) else None


def _core():
    db = mongomock.MongoClient().db
    gw = _Gateway(db)
    return Core(gw, _Engine(), _Pub(), ReplyStore(db)), gw


class RegistryTest(unittest.TestCase):
    def test_create_update_persist(self):
        db = mongomock.MongoClient().db
        r = ClientRegistry(db)
        sec = r.create("alice", [WF_A])
        self.assertEqual(len(sec), crypto.SECRET_LEN)
        self.assertEqual(r.allowed("alice"), [WF_A])
        # persistência: outra instância sobre o mesmo db enxerga
        r2 = ClientRegistry(db)
        self.assertEqual(r2.get("alice"), sec)
        self.assertEqual(r2.allowed("alice"), [WF_A])
        # editar troca os workflows
        r.update("alice", [WF_A, WF_B])
        self.assertEqual(ClientRegistry(db).allowed("alice"), [WF_A, WF_B])

    def test_create_duplicate_raises(self):
        r = ClientRegistry(mongomock.MongoClient().db)
        r.create("bob", [])
        with self.assertRaises(ValueError):
            r.create("bob", [])

    def test_seed_no_clobber(self):
        db = mongomock.MongoClient().db
        r = ClientRegistry(db)
        sec = r.create("web", [WF_A])
        r.seed("web", crypto.new_secret())   # não sobrescreve
        self.assertEqual(r.get("web"), sec)

    def test_list_and_items(self):
        r = ClientRegistry(mongomock.MongoClient().db)
        r.create("a", [WF_A])
        r.create("b", None)
        self.assertEqual({c["name"] for c in r.list_clients()}, {"a", "b"})
        self.assertEqual({cid for cid, _ in r.items()}, {"a", "b"})


class CatalogPublishTest(unittest.TestCase):
    def test_create_publishes_sealed_catalog(self):
        core, gw = _core()
        sec = core.create_client("alice", [WF_A])
        blob = gw.store.get(crypto.catalog_address(sec))
        self.assertIsNotNone(blob)  # publicado
        cat = json.loads(crypto.open_catalog(crypto.catalog_key(sec), blob))
        self.assertEqual(cat["name"], "alice")
        self.assertEqual([w["hash"] for w in cat["workflows"]], [WF_A])  # só o permitido
        self.assertEqual(cat["workflows"][0]["label"], "wfA")

    def test_update_republishes(self):
        core, gw = _core()
        sec = core.create_client("alice", [WF_A])
        core.update_client("alice", [WF_A, WF_B])
        cat = json.loads(crypto.open_catalog(crypto.catalog_key(sec),
                                             gw.store.get(crypto.catalog_address(sec))))
        self.assertEqual({w["hash"] for w in cat["workflows"]}, {WF_A, WF_B})

    def test_allow_all_when_none(self):
        core, gw = _core()
        sec = core.gateway.registry.mint("legacy")  # workflows=None → todos
        core._publish_catalog("legacy", sec, core.gateway.registry.allowed("legacy"))
        cat = json.loads(crypto.open_catalog(crypto.catalog_key(sec),
                                             gw.store.get(crypto.catalog_address(sec))))
        self.assertEqual({w["hash"] for w in cat["workflows"]}, {WF_A, WF_B})


class OccurrencePublishTest(unittest.TestCase):
    def test_publish_index_and_detail(self):
        core, gw = _core()
        sec = core.create_client("alice", [WF_A])
        core._publish_occurrences("alice")
        core._publish_occ_detail("alice", "occ-1")
        # índice
        idx_blob = gw.store.get(crypto.occ_index_address(sec))
        idx = json.loads(crypto.open_occ_index(crypto.occ_index_key(sec), idx_blob))
        self.assertEqual(idx[0]["occurrence_id"], "occ-1")
        self.assertEqual(idx[0]["status"], "done")
        # detalhe (endereço por occ_id)
        det_blob = gw.store.get(crypto.occ_detail_address(sec, "occ-1"))
        det = json.loads(crypto.open_occ_detail(crypto.occ_detail_key(sec), det_blob))
        self.assertEqual(det["node_status"], {"T1": "done"})
        self.assertEqual(det["result"], {"ok": 1})

    def test_detail_address_varies_by_occ(self):
        sec = crypto.new_secret()
        self.assertNotEqual(crypto.occ_detail_address(sec, "occ-1"),
                            crypto.occ_detail_address(sec, "occ-2"))


class CatalogInputsTest(unittest.TestCase):
    def test_catalog_has_inputs_schema(self):
        # params_for é usado por required_inputs; aqui o template não tem $input,
        # então o schema vem vazio — mas a chave 'inputs' deve existir.
        core, _ = _core()
        cat = core._build_catalog("x", [WF_A])
        self.assertIn("inputs", cat["workflows"][0])


class AuthorizationTest(unittest.TestCase):
    def test_rejects_workflow_outside_allowlist(self):
        core, gw = _core()
        core.create_client("alice", [WF_A])
        core._start_workflow("alice", "r1", WF_B, {})  # não permitido
        self.assertTrue(gw.responses)
        _, _, body = gw.responses[-1]
        self.assertIn("não autorizado", body.get("erro", ""))

    def test_allow_all_passes_authorization(self):
        # workflows=None → autorização passa; cai no get_workflow (aqui inexistente)
        core, gw = _core()
        core.gateway.registry.mint("legacy")
        core._start_workflow("legacy", "r1", "blake2:zzz", {})
        _, _, body = gw.responses[-1]
        self.assertIn("não aprovado", body.get("erro", ""))  # passou da autorização


if __name__ == "__main__":
    unittest.main()
