import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass import errlog  # noqa: E402
from myass.edge import crypto  # noqa: E402
from myass.edge.gateway import Gateway  # noqa: E402
from myass.edge.locutus import MemoryLocutus  # noqa: E402
from myass.edge.registry import ClientRegistry, SeenRequests  # noqa: E402

CLIENT = "cli-1"


class EdgeTestBase(unittest.TestCase):
    def setUp(self):
        self.locutus = MemoryLocutus()
        self.registry = ClientRegistry()
        self.secret = self.registry.mint(CLIENT)
        db = mongomock.MongoClient().db
        self.seen = SeenRequests(db)
        self.received = []
        self.gw = Gateway(
            self.locutus, self.registry, self.seen,
            on_request=lambda cid, rid, msg: self.received.append((cid, rid, msg)),
        )

    def deposit_request(self, request_id, texto, secret=None):
        """Simula o cliente (Arduino) depositando um pedido cego no Locutus."""
        secret = secret or self.secret
        pt = json.dumps({"request_id": request_id, "texto": texto}).encode()
        blob = crypto.seal_request(crypto.request_key(secret), pt)
        self.locutus.put(crypto.request_address(secret), blob)


class TestGet(EdgeTestBase):
    def test_poll_delivers_and_consumes(self):
        self.deposit_request("r1", "ligar a luz")
        self.assertEqual(self.gw.poll(), 1)
        self.assertEqual(len(self.received), 1)
        cid, rid, msg = self.received[0]
        self.assertEqual((cid, rid), (CLIENT, "r1"))
        self.assertEqual(msg["texto"], "ligar a luz")
        # Consumido: o blob saiu do Locutus.
        self.assertIsNone(self.locutus.get(crypto.request_address(self.secret)))

    def test_poll_empty(self):
        self.assertEqual(self.gw.poll(), 0)
        self.assertEqual(self.received, [])

    def test_replay_is_noop(self):
        self.deposit_request("r1", "x")
        self.assertEqual(self.gw.poll(), 1)
        # Mesmo request_id depositado de novo (replay de blob capturado).
        self.deposit_request("r1", "x")
        self.assertEqual(self.gw.poll(), 0)  # dedup -> no-op
        self.assertEqual(len(self.received), 1)

    def test_garbage_blob_is_dropped_and_logged(self):
        errlog.errors.clear()
        self.locutus.put(crypto.request_address(self.secret), b"nao-e-um-blob-valido")
        self.assertEqual(self.gw.poll(), 0)
        self.assertIsNone(self.locutus.get(crypto.request_address(self.secret)))
        msg = errlog.dump(1)[0][1]
        self.assertIn("blob inválido", msg)

    def test_failed_handoff_keeps_blob_for_retry(self):
        boom = Gateway(self.locutus, self.registry, self.seen,
                       on_request=lambda *a: (_ for _ in ()).throw(RuntimeError("nucleo caiu")))
        self.deposit_request("r1", "x")
        errlog.errors.clear()
        self.assertEqual(boom.poll(), 0)
        # Não consumido: continua lá para a próxima varredura.
        self.assertIsNotNone(self.locutus.get(crypto.request_address(self.secret)))
        # E agora um gateway saudável entrega.
        self.assertEqual(self.gw.poll(), 1)

    def test_multiple_clients(self):
        c2 = "cli-2"
        s2 = self.registry.mint(c2)
        self.deposit_request("a", "do cliente 1")
        self.deposit_request("b", "do cliente 2", secret=s2)
        self.assertEqual(self.gw.poll(), 2)
        ids = {(cid, rid) for cid, rid, _ in self.received}
        self.assertEqual(ids, {(CLIENT, "a"), (c2, "b")})


class TestSet(EdgeTestBase):
    def test_send_response_roundtrip(self):
        self.gw.send_response(CLIENT, "r1", {"status": "ok", "msg": "feito"})
        # O cliente puxa do seu endereço de resposta e decifra.
        blob = self.locutus.get(crypto.response_address(self.secret))
        self.assertIsNotNone(blob)
        pt = crypto.open_response(crypto.response_key(self.secret), blob)
        resp = json.loads(pt)
        self.assertEqual(resp["request_id"], "r1")
        self.assertEqual(resp["body"], {"status": "ok", "msg": "feito"})

    def test_send_to_unknown_client_raises(self):
        with self.assertRaises(KeyError):
            self.gw.send_response("ninguem", "r1", {})


class TestEndToEnd(EdgeTestBase):
    def test_request_then_response_full_cycle(self):
        # Cliente -> GET -> (núcleo processa) -> SET -> cliente.
        self.deposit_request("rid-9", "qual a temperatura?")
        self.gw.poll()
        cid, rid, _msg = self.received[0]
        self.gw.send_response(cid, rid, {"temp": 21})
        blob = self.locutus.get(crypto.response_address(self.secret))
        resp = json.loads(crypto.open_response(crypto.response_key(self.secret), blob))
        self.assertEqual(resp, {"request_id": "rid-9", "body": {"temp": 21}})


if __name__ == "__main__":
    unittest.main()
