import io
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from myass.errlog import ErrorRing  # noqa: E402


class TestErrorRing(unittest.TestCase):
    def test_rejects_nonpositive_capacity(self):
        with self.assertRaises(ValueError):
            ErrorRing(0)

    def test_empty(self):
        r = ErrorRing(4, with_timestamp=False)
        self.assertEqual(len(r), 0)
        self.assertEqual(r.dump(), [])

    def test_dump_is_reverse_order(self):
        r = ErrorRing(8, with_timestamp=False)
        for e in ["a", "b", "c"]:
            r.record(e)
        # De trás para frente: mais recente primeiro.
        self.assertEqual(r.dump(), ["c", "b", "a"])

    def test_overwrites_oldest_when_full(self):
        r = ErrorRing(3, with_timestamp=False)
        for e in ["e1", "e2", "e3", "e4", "e5"]:
            r.record(e)
        # Só os 3 últimos sobrevivem; e1/e2 foram sobrescritos.
        self.assertEqual(len(r), 3)
        self.assertEqual(r.dump(), ["e5", "e4", "e3"])

    def test_total_counts_overwritten(self):
        r = ErrorRing(2, with_timestamp=False)
        for e in range(10):
            r.record(e)
        self.assertEqual(r.total, 10)   # total histórico
        self.assertEqual(len(r), 2)     # disponíveis agora
        self.assertEqual(r.dump(), [9, 8])

    def test_dump_limit(self):
        r = ErrorRing(100, with_timestamp=False)
        for e in range(10):
            r.record(e)
        self.assertEqual(r.dump(3), [9, 8, 7])
        self.assertEqual(r.dump(0), [])

    def test_clear(self):
        r = ErrorRing(4, with_timestamp=False)
        r.record("x")
        r.clear()
        self.assertEqual(len(r), 0)
        self.assertEqual(r.dump(), [])

    def test_print_reverse(self):
        r = ErrorRing(8, with_timestamp=False)
        for e in ["primeiro", "segundo", "terceiro"]:
            r.record(e)
        buf = io.StringIO()
        r.Print(file=buf)
        self.assertEqual(buf.getvalue().splitlines(), ["terceiro", "segundo", "primeiro"])

    def test_timestamp_wraps_item(self):
        r = ErrorRing(4)  # with_timestamp=True (default)
        r.record("boom")
        (ts, msg), = r.dump()
        self.assertIsInstance(ts, float)
        self.assertEqual(msg, "boom")

    def test_concurrent_record_is_consistent(self):
        # Sob concorrência, o total deve bater e o anel nunca corromper.
        r = ErrorRing(64, with_timestamp=False)
        n_threads, per = 8, 1000

        def worker(tid):
            for i in range(per):
                r.record((tid, i))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(r.total, n_threads * per)
        self.assertEqual(len(r), 64)
        self.assertEqual(len(r.dump()), 64)
        self.assertTrue(all(item is not None for item in r.dump()))


if __name__ == "__main__":
    unittest.main()
