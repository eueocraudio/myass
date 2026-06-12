import io
import json
import os
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from myass.executor import project as proj  # noqa: E402
from myass.executor.dataplane import MemoryDataStore  # noqa: E402
from myass.executor.project import (  # noqa: E402
    DirSource, IntegrityError, ProjectCache, ProjectMissing, ProjectResolver,
)
from myass.executor.runner import RESULT_OK, ActivityRunner  # noqa: E402

ECHO = """
import sys, json, os
cfg = json.loads(sys.stdin.readline())
wd = cfg["workdir"]
inp = json.load(open(os.path.join(wd, "input.json")))
json.dump({"echo": inp["params"]}, open(os.path.join(wd, "output.json"), "w"))
"""


def make_project(root, script=ECHO):
    """Cria um mini-BOT (manifest + 1 script) e devolve (project_hash, bot_ref)."""
    os.makedirs(os.path.join(root, "scripts"))
    entry_rel = "scripts/echo.py"
    with open(os.path.join(root, entry_rel), "w") as f:
        f.write(script)
    sh = proj.file_hash(os.path.join(root, entry_rel))
    manifest = {
        "manifest_version": 1, "nome": "t", "versao": "1", "requirements": {},
        "scripts": {"echo": {"entrypoint": entry_rel, "script_hash": sh}},
    }
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump(manifest, f, sort_keys=True, indent=2)
    ph = proj.tree_hash(root)
    return ph, {"project_hash": ph, "script_hash": sh}


class TestTreeHash(unittest.TestCase):
    def test_deterministic_and_sensitive(self):
        a = tempfile.mkdtemp()
        b = tempfile.mkdtemp()
        make_project(a)
        make_project(b)
        self.assertEqual(proj.tree_hash(a), proj.tree_hash(b))  # mesmo conteúdo
        with open(os.path.join(a, "scripts", "echo.py"), "a") as f:
            f.write("# muda\n")
        self.assertNotEqual(proj.tree_hash(a), proj.tree_hash(b))  # 1 byte muda

    def test_ignores_pycache(self):
        a = tempfile.mkdtemp()
        make_project(a)
        h1 = proj.tree_hash(a)
        os.makedirs(os.path.join(a, "scripts", "__pycache__"))
        with open(os.path.join(a, "scripts", "__pycache__", "x.pyc"), "wb") as f:
            f.write(b"junk")
        self.assertEqual(proj.tree_hash(a), h1)  # __pycache__/.pyc não contam


class TestTar(unittest.TestCase):
    def test_pack_extract_roundtrip(self):
        src = tempfile.mkdtemp()
        ph, _ = make_project(src)
        dest = tempfile.mkdtemp()
        proj.extract(proj.pack(src), dest)
        self.assertEqual(proj.tree_hash(dest), ph)

    def test_extract_rejects_path_traversal(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"evil"
            ti = tarfile.TarInfo(name="../escapou")
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
        dest = tempfile.mkdtemp()
        with self.assertRaises(Exception):
            proj.extract(buf.getvalue(), dest)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(dest), "escapou")))


class TestRequirements(unittest.TestCase):
    def test_requirements_txt_uses_sha256_only(self):
        m = {"requirements": {"pillow": {"versao": "10.4.0",
                                         "hashes": ["blake2:aa", "sha256:bb"]}}}
        self.assertEqual(proj.requirements_txt(m), "pillow==10.4.0 --hash=sha256:bb\n")

    def test_requirements_txt_empty(self):
        self.assertEqual(proj.requirements_txt({"requirements": {}}), "")

    def test_build_venv_invokes_venv_and_pip(self):
        env = tempfile.mkdtemp()
        pdir = tempfile.mkdtemp()
        manifest = {"requirements": {"pkg": {"versao": "1.0", "hashes": ["sha256:cc"]}}}
        calls = []
        proj.build_venv(env, pdir, manifest, run=lambda cmd, check: calls.append(cmd))
        self.assertTrue(any("venv" in c for c in calls))
        self.assertTrue(any("--require-hashes" in c for c in calls))
        with open(os.path.join(pdir, ".requirements.txt")) as f:
            self.assertIn("pkg==1.0 --hash=sha256:cc", f.read())


class TestCache(unittest.TestCase):
    def test_install_verifies_hash(self):
        src = tempfile.mkdtemp()
        ph, _ = make_project(src)
        cache = ProjectCache(tempfile.mkdtemp())
        self.assertFalse(cache.is_cached(ph))
        cache.install(ph, proj.pack(src))
        self.assertTrue(cache.is_cached(ph))

    def test_install_rejects_wrong_hash(self):
        src = tempfile.mkdtemp()
        make_project(src)
        cache = ProjectCache(tempfile.mkdtemp())
        with self.assertRaises(IntegrityError):
            cache.install("blake2:" + "0" * 128, proj.pack(src))

    def test_install_idempotent(self):
        src = tempfile.mkdtemp()
        ph, _ = make_project(src)
        cache = ProjectCache(tempfile.mkdtemp())
        p1 = cache.install(ph, proj.pack(src))
        p2 = cache.install(ph, proj.pack(src))  # já em cache, não reextrai
        self.assertEqual(p1, p2)


class TestResolver(unittest.TestCase):
    def test_missing_without_source(self):
        cache = ProjectCache(tempfile.mkdtemp())
        r = ProjectResolver(cache, source=None)
        with self.assertRaises(ProjectMissing):
            r.resolve({"project_hash": "blake2:zz", "script_hash": "blake2:zz"})

    def test_resolve_fetches_and_runs(self):
        # Caminho completo de distribuição: empacota -> DirSource -> resolve ->
        # roda o script real pelo ActivityRunner.
        src = tempfile.mkdtemp()
        ph, bot_ref = make_project(src)
        source_dir = tempfile.mkdtemp()
        with open(os.path.join(source_dir, ph.split(":")[-1] + ".tar.gz"), "wb") as f:
            f.write(proj.pack(src))

        cache = ProjectCache(tempfile.mkdtemp())
        resolver = ProjectResolver(cache, DirSource(source_dir))
        interpreter, entrypoint = resolver.resolve(bot_ref)
        self.assertTrue(cache.is_cached(ph))

        runner = ActivityRunner(MemoryDataStore())
        res = runner.run({"atividade_id": "a", "occurrence_id": "o", "params": {"k": 1}},
                         interpreter, entrypoint)
        self.assertEqual(res.status, RESULT_OK)
        self.assertEqual(res.output, {"echo": {"k": 1}})

    def test_resolve_rejects_unknown_script_hash(self):
        src = tempfile.mkdtemp()
        ph, _ = make_project(src)
        cache = ProjectCache(tempfile.mkdtemp())
        cache.install(ph, proj.pack(src))
        r = ProjectResolver(cache)
        with self.assertRaises(IntegrityError):
            r.resolve({"project_hash": ph, "script_hash": "blake2:naoexiste"})


if __name__ == "__main__":
    unittest.main()
