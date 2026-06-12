import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from myass.broker.classes import ClassTable, HwClass  # noqa: E402


class TestDefaultQuadrants(unittest.TestCase):
    def setUp(self):
        # Limiares: mem 4096 MB, cpu 4 cores.
        self.t = ClassTable(mem_threshold_mb=4096, cpu_threshold_cores=4)

    def test_four_quadrants(self):
        self.assertEqual(self.t.class_ids, ["C1", "C2", "C3", "C4"])

    def test_classify_quadrants(self):
        # baixa/baixa -> C1
        self.assertEqual(self.t.classify({"mem_mb": 512, "cpu_cores": 1}), "C1")
        # baixa mem / alta cpu -> C2
        self.assertEqual(self.t.classify({"mem_mb": 512, "cpu_cores": 8}), "C2")
        # alta mem / baixa cpu -> C3
        self.assertEqual(self.t.classify({"mem_mb": 16384, "cpu_cores": 1}), "C3")
        # alta/alta -> C4
        self.assertEqual(self.t.classify({"mem_mb": 16384, "cpu_cores": 8}), "C4")

    def test_classify_on_threshold_is_high(self):
        # No limiar conta como "alta" (>=).
        self.assertEqual(self.t.classify({"mem_mb": 4096, "cpu_cores": 4}), "C4")

    def test_classify_missing_exigencia_is_base(self):
        self.assertEqual(self.t.classify(None), "C1")
        self.assertEqual(self.t.classify({}), "C1")

    def test_eligible_high_block_reads_all(self):
        elig = self.t.eligible_classes({"mem_mb": 32768, "cpu_cores": 16})
        self.assertEqual(set(elig), {"C1", "C2", "C3", "C4"})

    def test_eligible_low_block_reads_only_base(self):
        elig = self.t.eligible_classes({"mem_mb": 1024, "cpu_cores": 2})
        self.assertEqual(elig, ["C1"])

    def test_eligible_high_mem_low_cpu(self):
        elig = self.t.eligible_classes({"mem_mb": 16384, "cpu_cores": 2})
        self.assertEqual(set(elig), {"C1", "C3"})

    def test_eligible_preserves_table_order(self):
        elig = self.t.eligible_classes({"mem_mb": 32768, "cpu_cores": 16})
        self.assertEqual(elig, ["C1", "C2", "C3", "C4"])

    def test_classified_work_is_readable_by_a_matching_block(self):
        # Invariante: o nó em que a atividade é escrita é elegível para um block
        # cujo hardware é igual à exigência.
        exig = {"mem_mb": 16384, "cpu_cores": 1}
        cid = self.t.classify(exig)
        self.assertIn(cid, self.t.eligible_classes(exig))


class TestArbitraryTable(unittest.TestCase):
    def test_custom_classes(self):
        t = ClassTable(classes=[HwClass("small", 0, 0), HwClass("big", 8192, 8)])
        self.assertEqual(t.classify({"mem_mb": 100, "cpu_cores": 1}), "small")
        self.assertEqual(t.classify({"mem_mb": 9000, "cpu_cores": 9}), "big")
        self.assertEqual(t.eligible_classes({"mem_mb": 9000, "cpu_cores": 9}), ["small", "big"])
        self.assertEqual(t.eligible_classes({"mem_mb": 100, "cpu_cores": 1}), ["small"])

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            ClassTable(classes=[])

    def test_rejects_duplicate_ids(self):
        with self.assertRaises(ValueError):
            ClassTable(classes=[HwClass("x", 0, 0), HwClass("x", 1, 1)])


if __name__ == "__main__":
    unittest.main()
