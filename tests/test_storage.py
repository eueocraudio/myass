import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass.executor.dataplane import compute_ref  # noqa: E402
from myass.storage import open_stores  # noqa: E402
from myass.storage.blobstore import (  # noqa: E402
    CoreDataStore, GridFSBlobStore, MemoryBlobStore,
)


def _mongod_up():
    try:
        from pymongo import MongoClient
        MongoClient("mongodb://localhost:27017/",
                    serverSelectionTimeoutMS=300).admin.command("ping")
        return True
    except Exception:
        return False


class TestMemoryBlobStore(unittest.TestCase):
    def setUp(self):
        self.s = MemoryBlobStore()

    def test_put_get_exists_delete(self):
        self.assertFalse(self.s.exists("k"))
        self.s.put("k", b"v")
        self.assertTrue(self.s.exists("k"))
        self.assertEqual(self.s.get("k"), b"v")
        self.assertIsNone(self.s.get("ausente"))
        self.s.delete("k")
        self.assertFalse(self.s.exists("k"))

    def test_immutable_first_write_wins(self):
        self.s.put("k", b"primeiro")
        self.s.put("k", b"segundo")
        self.assertEqual(self.s.get("k"), b"primeiro")


class TestCoreDataStore(unittest.TestCase):
    def setUp(self):
        self.blobs = MemoryBlobStore()
        self.ds = CoreDataStore(self.blobs)

    def test_content_addressed_and_dedup(self):
        ref1 = self.ds.put(b"artefato")
        ref2 = self.ds.put(b"artefato")
        self.assertEqual(ref1, ref2)              # mesmo conteúdo, mesmo ref
        self.assertEqual(ref1, compute_ref(b"artefato"))
        self.assertEqual(self.ds.get(ref1), b"artefato")

    def test_get_missing_raises(self):
        with self.assertRaises(KeyError):
            self.ds.get("blake2:naoexiste")

    def test_integrity_check_on_read(self):
        ref = self.ds.put(b"intacto")
        self.blobs._d[ref] = b"adulterado"  # corrompe o lastro
        with self.assertRaises(ValueError):
            self.ds.get(ref)


class TestOpenStores(unittest.TestCase):
    def test_wires_all_stores(self):
        # open_stores monta tudo sobre um db injetado (mongomock); o GridFS é
        # preguiçoso, então a construção não exige um Mongo real.
        db = mongomock.MongoClient().db
        stores = open_stores(db)
        for attr in ("backlog", "leases", "occurrences", "seen", "blobs", "data"):
            self.assertTrue(hasattr(stores, attr))


@unittest.skipUnless(_mongod_up(), "precisa de um mongod em localhost:27017")
class TestGridFSBlobStore(unittest.TestCase):
    def setUp(self):
        from pymongo import MongoClient
        self.db = MongoClient("mongodb://localhost:27017/")["myass_test"]
        self.s = GridFSBlobStore(self.db)

    def tearDown(self):
        self.db.client.drop_database("myass_test")

    def test_roundtrip_and_dedup(self):
        self.s.put("k1", b"conteudo")
        self.assertTrue(self.s.exists("k1"))
        self.assertEqual(self.s.get("k1"), b"conteudo")
        self.s.put("k1", b"outro")  # imutável
        self.assertEqual(self.s.get("k1"), b"conteudo")
        self.s.delete("k1")
        self.assertFalse(self.s.exists("k1"))


if __name__ == "__main__":
    unittest.main()
