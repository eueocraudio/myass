import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass import errlog  # noqa: E402
from myass.broker.broker import Broker  # noqa: E402
from myass.broker.classes import ClassTable  # noqa: E402
from myass.broker.store import STATUS_READY, STATUS_TAKEN, BacklogStore  # noqa: E402

# Perfis de hardware de teste (limiares default: mem 4096, cpu 4).
BIG = {"mem_mb": 32768, "cpu_cores": 16}    # lê de todos os nós
SMALL = {"mem_mb": 1024, "cpu_cores": 2}    # lê só do nó base C1

HEAVY = {"mem_mb": 16384, "cpu_cores": 8}   # exigência alta/alta -> C4
LIGHT = {"mem_mb": 256, "cpu_cores": 1}     # exigência baixa/baixa -> C1


def activity(i, exigencia=None):
    return {"atividade_id": f"atv-{i}", "exigencia": exigencia or LIGHT, "n": i}


class BrokerTestBase(unittest.TestCase):
    def make_broker(self, **kw):
        db = mongomock.MongoClient().db
        self.store = BacklogStore(db)
        # Determinístico por padrão: carga inline.
        kw.setdefault("async_load", False)
        return Broker(self.store, classes=ClassTable(), **kw)


class TestEnqueueDequeue(BrokerTestBase):
    def test_enqueue_classifies_and_delivers(self):
        b = self.make_broker()
        self.assertEqual(b.enqueue(activity(1, HEAVY)), "C4")
        self.assertEqual(b.enqueue(activity(2, LIGHT)), "C1")
        got = b.dequeue(BIG, max_n=10)
        self.assertEqual(sorted(a["n"] for a in got), [1, 2])

    def test_fifo_within_a_node(self):
        b = self.make_broker()
        for i in range(5):
            b.enqueue(activity(i, LIGHT))
        got = b.dequeue(BIG, max_n=5)
        self.assertEqual([a["n"] for a in got], [0, 1, 2, 3, 4])

    def test_empty_window_returns_immediately(self):
        b = self.make_broker()
        t0 = time.monotonic()
        self.assertEqual(b.dequeue(BIG, max_n=5), [])  # NO_WORK
        self.assertLess(time.monotonic() - t0, 0.5)  # não bloqueia

    def test_max_n_limits_delivery(self):
        b = self.make_broker()
        for i in range(10):
            b.enqueue(activity(i, LIGHT))
        self.assertEqual(len(b.dequeue(BIG, max_n=3)), 3)


class TestClassMatching(BrokerTestBase):
    def test_small_block_cannot_read_heavy_work(self):
        b = self.make_broker()
        b.enqueue(activity(1, HEAVY))  # vai para C4
        self.assertEqual(b.dequeue(SMALL, max_n=10), [])  # SMALL só lê C1
        # Um block grande pega o mesmo trabalho.
        self.assertEqual([a["n"] for a in b.dequeue(BIG, max_n=10)], [1])

    def test_small_block_reads_only_base_node(self):
        b = self.make_broker()
        b.enqueue(activity(1, HEAVY))   # C4
        b.enqueue(activity(2, LIGHT))   # C1
        self.assertEqual([a["n"] for a in b.dequeue(SMALL, max_n=10)], [2])


class TestDurabilityAndIdempotency(BrokerTestBase):
    def test_persisted_then_marked_taken(self):
        b = self.make_broker()
        b.enqueue(activity(1, LIGHT))
        doc = self.store.get("atv-1")
        self.assertEqual(doc["status"], STATUS_READY)
        self.assertEqual(doc["class_id"], "C1")
        b.dequeue(BIG, max_n=1)
        self.assertEqual(self.store.get("atv-1")["status"], STATUS_TAKEN)

    def test_duplicate_enqueue_delivered_once(self):
        b = self.make_broker()
        b.enqueue(activity(1, LIGHT))
        b.enqueue(activity(1, LIGHT))  # mesmo atividade_id -> no-op
        got = b.dequeue(BIG, max_n=10)
        self.assertEqual([a["n"] for a in got], [1])


class TestLazyLoading(BrokerTestBase):
    def test_backlog_larger_than_ring_drains_in_order(self):
        # Ring pequeno: a maioria do backlog vive só no Mongo e é trazida em
        # cargas sucessivas conforme a janela esvazia.
        b = self.make_broker(ring_capacity=2)
        for i in range(7):
            b.enqueue(activity(i, LIGHT))
        # A janela nunca passa de 2, mas o dequeue dispara recargas ao esvaziar.
        out = []
        for _ in range(10):
            batch = b.dequeue(BIG, max_n=2)
            if not batch:
                break
            out.extend(a["n"] for a in batch)
        self.assertEqual(out, [0, 1, 2, 3, 4, 5, 6])

    def test_recovery_resets_buffered_on_startup(self):
        # Simula um broker anterior que bufferizou itens; um novo broker sobre o
        # mesmo Mongo deve reconseguir carregá-los (a janela em RAM se perdeu).
        db = mongomock.MongoClient().db
        store = BacklogStore(db)
        store.append("C1", "atv-1", activity(1, LIGHT))
        store.load_ready("C1", 10)  # marca buffered=True (ring de um broker morto)
        self.assertEqual(store.get("atv-1")["buffered"], True)

        # Um novo broker: __init__ chama reset_buffered + aquece os rings, então
        # o item órfão (buffered mas sem ring vivo) volta a ser entregável.
        b = Broker(store, async_load=False)
        self.assertEqual([a["n"] for a in b.dequeue(BIG, max_n=5)], [1])


class TestLoaderErrorChannel(BrokerTestBase):
    def test_load_exception_is_captured_in_error_channel(self):
        errlog.errors.clear()
        b = self.make_broker()
        # Faz a carga estourar: o erro não pode sumir na thread/inline do loader.
        self.store.load_ready = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        b.enqueue(activity(1, LIGHT))  # dispara a carga
        recent = errlog.dump(1)
        self.assertEqual(len(recent), 1)
        _ts, msg = recent[0]
        self.assertIn("broker: falha ao carregar", msg)
        self.assertIn("boom", msg)


class TestAsyncLoad(BrokerTestBase):
    def test_async_loader_fills_ring(self):
        b = self.make_broker(async_load=True)
        b.enqueue(activity(1, LIGHT))
        b.wait_for_loaders(timeout=5)
        got = b.dequeue(BIG, max_n=5)
        self.assertEqual([a["n"] for a in got], [1])

    def test_single_load_in_flight_per_node(self):
        # O guard de <= 1 carga em voo por nó não deve travar a entrega: depois
        # de drenar os loaders, todo o backlog sai em ordem.
        b = self.make_broker(async_load=True, ring_capacity=4)
        for i in range(20):
            b.enqueue(activity(i, LIGHT))
        out = []
        for _ in range(50):
            b.wait_for_loaders(timeout=5)
            batch = b.dequeue(BIG, max_n=4)
            out.extend(a["n"] for a in batch)
            if len(out) >= 20:
                break
            time.sleep(0.01)
        self.assertEqual(out, list(range(20)))


if __name__ == "__main__":
    unittest.main()
