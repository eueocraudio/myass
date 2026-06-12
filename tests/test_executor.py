import glob
import os
import stat
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from myass.executor import dataplane, workdir  # noqa: E402
from myass.executor.dataplane import MemoryDataStore, compute_ref  # noqa: E402
from myass.executor.runner import (  # noqa: E402
    RESULT_ERRO_LOGICO, RESULT_OK, ActivityRunner,
)

# --- scripts-filho de teste (cada um segue o contrato Executor<->script) ---

ECHO = """
import sys, json, os
cfg = json.loads(sys.stdin.readline())
wd = cfg["workdir"]
inp = json.load(open(os.path.join(wd, "input.json")))
json.dump({"echo": inp["params"], "occ": inp["occurrence_id"]},
          open(os.path.join(wd, "output.json"), "w"))
"""

FAIL = """
import sys, json, os
cfg = json.loads(sys.stdin.readline())
wd = cfg["workdir"]
json.dump({"erro": "falhou de proposito"}, open(os.path.join(wd, "output.json"), "w"))
sys.exit(3)
"""

PRODUCE_FILE = """
import sys, json, os
cfg = json.loads(sys.stdin.readline())
wd = cfg["workdir"]
with open(os.path.join(wd, "saida.bin"), "wb") as f:
    f.write(b"ARTEFATO-GRANDE" * 10)
json.dump({"resultado": {"$file": "saida.bin"}}, open(os.path.join(wd, "output.json"), "w"))
"""

CONSUME_FILE = """
import sys, json, os
cfg = json.loads(sys.stdin.readline())
wd = cfg["workdir"]
inp = json.load(open(os.path.join(wd, "input.json")))
rel = inp["params"]["entrada"]["$file"]
data = open(os.path.join(wd, rel), "rb").read()
json.dump({"tam": len(data), "txt": data.decode()}, open(os.path.join(wd, "output.json"), "w"))
"""

NOISY_STDERR = """
import sys, json, os
cfg = json.loads(sys.stdin.readline())
wd = cfg["workdir"]
sys.stderr.write("aviso de uma lib barulhenta\\n")
json.dump({"ok": True}, open(os.path.join(wd, "output.json"), "w"))
"""

SLEEP = """
import sys, json, time
cfg = json.loads(sys.stdin.readline())
time.sleep(30)
"""


class ExecutorTestBase(unittest.TestCase):
    def setUp(self):
        self.scripts = tempfile.mkdtemp(prefix="myass-test-scripts-")
        self.ds = MemoryDataStore()
        self.runner = ActivityRunner(self.ds)

    def script(self, name, code):
        path = os.path.join(self.scripts, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        return path

    def run_order(self, code, params=None, occ="occ-1", cancel_event=None):
        entry = self.script("s.py", code)
        order = {"atividade_id": "atv-1", "occurrence_id": occ, "params": params or {}}
        return self.runner.run(order, sys.executable, entry, cancel_event=cancel_event)


class TestWorkdir(unittest.TestCase):
    def test_alloc_is_700_and_cleanup(self):
        wd = workdir.alloc_workdir("occ-xyz")
        try:
            self.assertTrue(os.path.isdir(wd))
            self.assertTrue(os.path.basename(wd).startswith("myass-occ-xyz-"))
            self.assertEqual(stat.S_IMODE(os.stat(wd).st_mode), 0o700)
        finally:
            workdir.cleanup_workdir(wd)
        self.assertFalse(os.path.exists(wd))

    def test_cleanup_is_idempotent(self):
        wd = workdir.alloc_workdir()
        workdir.cleanup_workdir(wd)
        workdir.cleanup_workdir(wd)  # não levanta

    def test_sweep_orphans(self):
        wd = workdir.alloc_workdir("orfao")
        # não limpa: simula morte no meio
        removed = workdir.sweep_orphans()
        self.assertGreaterEqual(removed, 1)
        self.assertFalse(os.path.exists(wd))

    def test_luks_workdir_not_yet_implemented(self):
        with self.assertRaises(NotImplementedError):
            workdir.alloc_workdir("x", workdir_mb=1024)


class TestDataplane(unittest.TestCase):
    def test_compute_ref_prefix(self):
        self.assertTrue(compute_ref(b"abc").startswith("blake2:"))

    def test_memory_store_roundtrip_and_dedup(self):
        ds = MemoryDataStore()
        r1 = ds.put(b"mesmo")
        r2 = ds.put(b"mesmo")
        self.assertEqual(r1, r2)  # content-addressed: dedup
        self.assertEqual(ds.get(r1), b"mesmo")

    def test_resolve_inputs_materializes_files(self):
        ds = MemoryDataStore()
        ref = ds.put(b"conteudo")
        wd = workdir.alloc_workdir()
        try:
            resolved = dataplane.resolve_inputs({"x": {"$data": ref}}, ds, wd)
            rel = resolved["x"]["$file"]
            with open(os.path.join(wd, rel), "rb") as f:
                self.assertEqual(f.read(), b"conteudo")
        finally:
            workdir.cleanup_workdir(wd)

    def test_resolve_outputs_uploads_files(self):
        ds = MemoryDataStore()
        wd = workdir.alloc_workdir()
        try:
            with open(os.path.join(wd, "a.bin"), "wb") as f:
                f.write(b"saida")
            out = dataplane.resolve_outputs({"y": {"$file": "a.bin"}}, ds, wd)
            self.assertEqual(out["y"]["$data"], compute_ref(b"saida"))
            self.assertEqual(out["y"]["tamanho"], 5)
            self.assertEqual(ds.get(out["y"]["$data"]), b"saida")
        finally:
            workdir.cleanup_workdir(wd)

    def test_resolve_outputs_rejects_path_traversal(self):
        ds = MemoryDataStore()
        wd = workdir.alloc_workdir()
        try:
            with self.assertRaises(ValueError):
                dataplane.resolve_outputs({"y": {"$file": "../escapou"}}, ds, wd)
        finally:
            workdir.cleanup_workdir(wd)


class TestRunner(ExecutorTestBase):
    def test_ok_returns_output(self):
        res = self.run_order(ECHO, params={"a": 1}, occ="occ-9")
        self.assertEqual(res.status, RESULT_OK)
        self.assertEqual(res.output, {"echo": {"a": 1}, "occ": "occ-9"})
        self.assertEqual(res.exit_code, 0)

    def test_nonzero_exit_is_logical_error(self):
        res = self.run_order(FAIL)
        self.assertEqual(res.status, RESULT_ERRO_LOGICO)
        self.assertEqual(res.exit_code, 3)
        self.assertEqual(res.output, {"erro": "falhou de proposito"})

    def test_output_file_becomes_data_ref(self):
        res = self.run_order(PRODUCE_FILE)
        self.assertEqual(res.status, RESULT_OK)
        ref = res.output["resultado"]["$data"]
        expected = b"ARTEFATO-GRANDE" * 10
        self.assertEqual(res.output["resultado"]["tamanho"], len(expected))
        self.assertEqual(self.ds.get(ref), expected)

    def test_input_data_ref_becomes_file(self):
        ref = self.ds.put(b"entrada-grande")
        res = self.run_order(CONSUME_FILE, params={"entrada": {"$data": ref}})
        self.assertEqual(res.status, RESULT_OK)
        self.assertEqual(res.output, {"tam": 14, "txt": "entrada-grande"})

    def test_stderr_captured(self):
        res = self.run_order(NOISY_STDERR)
        self.assertEqual(res.status, RESULT_OK)
        self.assertIn("lib barulhenta", res.stderr)

    def test_workdir_removed_after_run(self):
        before = set(glob.glob("/tmp/myass-*"))
        self.run_order(ECHO, params={})
        after = set(glob.glob("/tmp/myass-*"))
        # Nenhum workdir myass-occ-* novo sobrou (o do runner é limpo no finally).
        self.assertEqual(after - before, set())

    def test_cancel_kills_child(self):
        ev = threading.Event()
        threading.Timer(0.3, ev.set).start()
        t0 = time.monotonic()
        res = self.run_order(SLEEP, cancel_event=ev)
        elapsed = time.monotonic() - t0
        self.assertTrue(res.cancelled)
        self.assertEqual(res.status, RESULT_ERRO_LOGICO)
        self.assertEqual(res.output.get("erro"), "cancelado")
        self.assertLess(elapsed, 10)  # morreu logo, não esperou os 30s


if __name__ == "__main__":
    unittest.main()
