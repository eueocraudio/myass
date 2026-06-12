import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from myass.broker.ring import RingBuffer  # noqa: E402


class TestRingBuffer(unittest.TestCase):
    def test_rejects_nonpositive_capacity(self):
        with self.assertRaises(ValueError):
            RingBuffer(0)

    def test_empty(self):
        r = RingBuffer(4)
        self.assertTrue(r.is_empty())
        self.assertFalse(r.is_full())
        self.assertEqual(r.available(), 0)
        self.assertEqual(r.free_space(), 4)
        self.assertIsNone(r.pop())

    def test_fifo_order(self):
        r = RingBuffer(8)
        for i in range(5):
            self.assertTrue(r.push(i))
        self.assertEqual(r.available(), 5)
        self.assertEqual([r.pop() for _ in range(5)], [0, 1, 2, 3, 4])
        self.assertIsNone(r.pop())

    def test_full_rejects_push(self):
        r = RingBuffer(3)
        self.assertTrue(r.push("a"))
        self.assertTrue(r.push("b"))
        self.assertTrue(r.push("c"))
        self.assertTrue(r.is_full())
        self.assertFalse(r.push("d"))  # janela cheia
        self.assertEqual(r.available(), 3)

    def test_wraparound(self):
        # Os ponteiros são monotônicos; o índice físico é ptr % capacity. Encher,
        # esvaziar parcialmente e reencher deve dar a volta sem corromper a ordem.
        r = RingBuffer(3)
        r.push(1); r.push(2); r.push(3)
        self.assertEqual(r.pop(), 1)
        self.assertEqual(r.pop(), 2)
        self.assertTrue(r.push(4))
        self.assertTrue(r.push(5))
        self.assertTrue(r.is_full())
        self.assertEqual([r.pop() for _ in range(3)], [3, 4, 5])
        w, rr = r.pointers
        self.assertEqual((w, rr), (5, 5))

    def test_free_space_tracks_window(self):
        r = RingBuffer(4)
        r.push("x")
        self.assertEqual(r.free_space(), 3)
        r.pop()
        self.assertEqual(r.free_space(), 4)

    def test_pop_releases_reference(self):
        # pop não deve segurar a referência ao objeto consumido.
        r = RingBuffer(2)

        class Marker:
            pass

        m = Marker()
        r.push(m)
        self.assertIs(r.pop(), m)
        # O slot foi limpo; o ring não mantém m vivo.
        self.assertNotIn(m, r._buf)

    def test_concurrent_push_pop_conserves_items(self):
        # Sob concorrência, nenhum item deve ser duplicado ou perdido.
        r = RingBuffer(64)
        n = 5000
        produced = list(range(n))
        consumed = []
        cons_lock = threading.Lock()
        done = threading.Event()

        def producer():
            for i in produced:
                while not r.push(i):
                    pass  # janela cheia: espera abrir espaço

        def consumer():
            while not (done.is_set() and r.is_empty()):
                item = r.pop()
                if item is not None:
                    with cons_lock:
                        consumed.append(item)

        cons = [threading.Thread(target=consumer) for _ in range(3)]
        for c in cons:
            c.start()
        prod = threading.Thread(target=producer)
        prod.start()
        prod.join()
        done.set()
        for c in cons:
            c.join()

        self.assertEqual(sorted(consumed), produced)


if __name__ == "__main__":
    unittest.main()
