import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass import errlog  # noqa: E402
from myass.broker.broker import Broker  # noqa: E402
from myass.broker.classes import ClassTable  # noqa: E402
from myass.broker.store import BacklogStore  # noqa: E402
from myass.scheduler import states  # noqa: E402
from myass.scheduler.scheduler import Scheduler  # noqa: E402
from myass.scheduler.store import LeaseStore  # noqa: E402

BIG = {"mem_mb": 32768, "cpu_cores": 16}     # block que lê de todos os nós
LIGHT = {"mem_mb": 256, "cpu_cores": 1}
BLOCK_A = "blk-aaa"
BLOCK_B = "blk-bbb"


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def activity(i, **extra):
    a = {"atividade_id": f"atv-{i}", "occurrence_id": f"occ-{i}",
         "exigencia": LIGHT, "bot_ref": {"project_hash": "p", "script_hash": "s"},
         "params": {"n": i}}
    a.update(extra)
    return a


class SchedulerTestBase(unittest.TestCase):
    def setUp(self):
        db = mongomock.MongoClient().db
        self.backlog = BacklogStore(db)
        self.broker = Broker(self.backlog, classes=ClassTable(), async_load=False)
        self.leases = LeaseStore(db)
        self.clock = FakeClock()
        self.completed = []
        self.failed = []
        self.sched = Scheduler(
            self.broker, self.leases,
            default_lease_s=120, max_tentativas=3,
            on_complete=lambda lease, out: self.completed.append((lease["_id"], out)),
            on_logical_failure=lambda lease, motivo, p: self.failed.append((lease["_id"], motivo)),
            clock=self.clock,
        )
        self.sched.hello(BLOCK_A, BIG)
        self.sched.hello(BLOCK_B, BIG)

    def dispatch_one(self, block=BLOCK_A):
        orders = self.sched.request_work(block, slots=1)
        self.assertEqual(len(orders), 1)
        return orders[0]


class TestDispatch(SchedulerTestBase):
    def test_request_work_creates_lease(self):
        self.broker.enqueue(activity(1))
        order = self.dispatch_one()
        self.assertEqual(order["atividade_id"], "atv-1")
        self.assertEqual(order["lease_s"], 120)
        lease = self.leases.get_lease("atv-1")
        self.assertEqual(lease["state"], states.EXECUTANDO)
        self.assertEqual(lease["tentativa"], 1)
        self.assertEqual(lease["carrier_block"], BLOCK_A)
        self.assertEqual(lease["lease_expira_em"], 1000.0 + 120)

    def test_no_work_returns_empty(self):
        self.assertEqual(self.sched.request_work(BLOCK_A, slots=5), [])

    def test_hello_required(self):
        with self.assertRaises(ValueError):
            self.sched.request_work("blk-desconhecido", slots=1)

    def test_slots_limit(self):
        for i in range(5):
            self.broker.enqueue(activity(i))
        self.assertEqual(len(self.sched.request_work(BLOCK_A, slots=3)), 3)


class TestBeat(SchedulerTestBase):
    def test_beat_renews_lease(self):
        self.broker.enqueue(activity(1))
        self.dispatch_one()
        self.clock.advance(30)
        self.assertEqual(self.sched.beat(BLOCK_A, "atv-1"), states.BEAT_ACK)
        self.assertEqual(self.leases.get_lease("atv-1")["lease_expira_em"], 1030.0 + 120)

    def test_beat_unknown_activity_cancels(self):
        self.assertEqual(self.sched.beat(BLOCK_A, "atv-x"), states.WORK_CANCEL)

    def test_beat_old_carrier_cancels(self):
        self.broker.enqueue(activity(1))
        self.dispatch_one(BLOCK_A)
        # BLOCK_B nunca foi o portador desta atividade.
        self.assertEqual(self.sched.beat(BLOCK_B, "atv-1"), states.WORK_CANCEL)


class TestResult(SchedulerTestBase):
    def test_result_ok_completes(self):
        self.broker.enqueue(activity(1))
        self.dispatch_one()
        self.assertEqual(
            self.sched.result(BLOCK_A, "atv-1", states.RESULT_OK, output={"r": 42}),
            states.RESULT_ACK,
        )
        self.assertEqual(self.leases.get_lease("atv-1")["state"], states.CONCLUIDA)
        self.assertEqual(self.completed, [("atv-1", {"r": 42})])

    def test_duplicate_result_reacks_without_reprocessing(self):
        self.broker.enqueue(activity(1))
        self.dispatch_one()
        self.sched.result(BLOCK_A, "atv-1", states.RESULT_OK, output={"r": 1})
        # Duplicado: re-ACK, sem chamar on_complete de novo.
        self.assertEqual(
            self.sched.result(BLOCK_A, "atv-1", states.RESULT_OK, output={"r": 1}),
            states.RESULT_ACK,
        )
        self.assertEqual(len(self.completed), 1)

    def test_result_erro_logico_fails(self):
        self.broker.enqueue(activity(1))
        self.dispatch_one()
        self.sched.result(BLOCK_A, "atv-1", states.RESULT_ERRO_LOGICO, output={"erro": "x"})
        lease = self.leases.get_lease("atv-1")
        self.assertEqual(lease["state"], states.FALHA_LOGICA)
        self.assertEqual(lease["motivo"], states.MOTIVO_ERRO_LOGICO)
        self.assertEqual(self.failed, [("atv-1", states.MOTIVO_ERRO_LOGICO)])

    def test_first_result_wins_even_from_old_carrier(self):
        self.broker.enqueue(activity(1))
        self.dispatch_one(BLOCK_A)
        # Lease vence -> reap reenfileira -> redespacha para BLOCK_B (tentativa 2).
        self.clock.advance(121)
        self.sched.reap()
        order_b = self.dispatch_one(BLOCK_B)
        self.assertEqual(order_b["atividade_id"], "atv-1")
        self.assertEqual(self.leases.get_lease("atv-1")["carrier_block"], BLOCK_B)
        # O portador ANTIGO (A) entrega primeiro: vale, trabalho é idempotente.
        self.sched.result(BLOCK_A, "atv-1", states.RESULT_OK, output={"r": "A"})
        self.assertEqual(self.leases.get_lease("atv-1")["state"], states.CONCLUIDA)
        # O portador novo (B) bate depois -> WORK_CANCEL (já terminal).
        self.assertEqual(self.sched.beat(BLOCK_B, "atv-1"), states.WORK_CANCEL)


class TestRegeneration(SchedulerTestBase):
    def test_expired_lease_requeues_and_increments_attempt(self):
        self.broker.enqueue(activity(1))
        self.dispatch_one(BLOCK_A)
        self.clock.advance(121)  # lease venceu
        self.assertEqual(self.sched.reap(), {"reenfileiradas": 1, "esgotadas": 0, "timeouts": 0})
        # Redespacho: mesma atividade, tentativa 2.
        order = self.dispatch_one(BLOCK_B)
        self.assertEqual(order["atividade_id"], "atv-1")
        self.assertEqual(self.leases.get_lease("atv-1")["tentativa"], 2)

    def test_exhaustion_promotes_to_logical_failure(self):
        self.broker.enqueue(activity(1, max_tentativas=2))
        # tentativa 1
        self.dispatch_one(BLOCK_A)
        self.clock.advance(121)
        self.assertEqual(self.sched.reap()["reenfileiradas"], 1)
        # tentativa 2 (== max)
        self.dispatch_one(BLOCK_A)
        self.clock.advance(121)
        stats = self.sched.reap()
        self.assertEqual(stats, {"reenfileiradas": 0, "esgotadas": 1, "timeouts": 0})
        lease = self.leases.get_lease("atv-1")
        self.assertEqual(lease["state"], states.FALHA_LOGICA)
        self.assertEqual(lease["motivo"], states.MOTIVO_ESGOTADA)
        self.assertEqual(self.failed, [("atv-1", states.MOTIVO_ESGOTADA)])

    def test_late_result_after_requeue_is_not_redispatched(self):
        self.broker.enqueue(activity(1))
        self.dispatch_one(BLOCK_A)
        self.clock.advance(121)
        self.sched.reap()  # atv-1 volta para a fila (ready)
        # Um portador conclui antes do redespacho.
        self.sched.result(BLOCK_A, "atv-1", states.RESULT_OK, output={"r": 1})
        self.assertEqual(self.leases.get_lease("atv-1")["state"], states.CONCLUIDA)
        # O próximo pull descarta a entrada reciclada (lease já terminal).
        self.assertEqual(self.sched.request_work(BLOCK_B, slots=5), [])


class TestErrlogIntegration(SchedulerTestBase):
    def test_logical_failure_is_recorded_in_error_channel(self):
        errlog.errors.clear()
        self.broker.enqueue(activity(1))
        self.dispatch_one()
        self.sched.result(BLOCK_A, "atv-1", states.RESULT_ERRO_LOGICO, output={"erro": "x"})
        recent = errlog.dump(1)
        self.assertEqual(len(recent), 1)
        _ts, msg = recent[0]
        self.assertIn("falha_logica", msg)
        self.assertIn("atv-1", msg)
        self.assertIn(states.MOTIVO_ERRO_LOGICO, msg)


class TestRelease(SchedulerTestBase):
    def test_release_requeues_immediately(self):
        self.broker.enqueue(activity(1))
        self.dispatch_one(BLOCK_A)
        self.assertEqual(self.sched.release(BLOCK_A, "atv-1"), states.RELEASE_ACK)
        # Disponível de novo de imediato, sem esperar o lease.
        order = self.dispatch_one(BLOCK_B)
        self.assertEqual(order["atividade_id"], "atv-1")


class TestTimeoutTotal(SchedulerTestBase):
    def test_beat_after_timeout_cancels_and_fails_logically(self):
        self.broker.enqueue(activity(1, timeout_total=300))
        self.dispatch_one(BLOCK_A)
        # Beats mantêm o lease vivo, mas o timeout_total é o teto absoluto.
        self.clock.advance(301)
        self.assertEqual(self.sched.beat(BLOCK_A, "atv-1"), states.WORK_CANCEL)
        lease = self.leases.get_lease("atv-1")
        self.assertEqual(lease["state"], states.FALHA_LOGICA)
        self.assertEqual(lease["motivo"], states.MOTIVO_TIMEOUT)

    def test_timeout_is_not_renewed_by_release(self):
        # timeout_em é fixado no 1o despacho; uma regeneração não o estende.
        self.broker.enqueue(activity(1, timeout_total=300))
        self.dispatch_one(BLOCK_A)
        self.clock.advance(121)
        self.sched.reap()  # reenfileira (lease venceu, mas timeout ainda não)
        self.dispatch_one(BLOCK_B)
        self.assertEqual(self.leases.get_lease("atv-1")["timeout_em"], 1000.0 + 300)


if __name__ == "__main__":
    unittest.main()
