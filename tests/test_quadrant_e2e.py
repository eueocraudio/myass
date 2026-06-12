import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mongomock  # noqa: E402

from myass.edge import crypto as C  # noqa: E402
from myass.edge.locutus import MemoryLocutus  # noqa: E402
from myass.storage.blobstore import MemoryBlobStore  # noqa: E402
from myass.executor import project as proj  # noqa: E402
from myass.executor.project import ProjectCache  # noqa: E402
from myass.ops.nodes import CoreNode, DroneNode  # noqa: E402
from myass.ops.provision import provision_quadrante  # noqa: E402

ECHO = ("import sys, json, os\n"
        "cfg=json.loads(sys.stdin.readline())\n"
        "wd=cfg['workdir']\n"
        "inp=json.load(open(os.path.join(wd,'input.json')))\n"
        "json.dump({'echo': inp['params']}, open(os.path.join(wd,'output.json'),'w'))\n")


def make_bot(root):
    os.makedirs(os.path.join(root, "scripts"))
    entry = "scripts/echo.py"
    with open(os.path.join(root, entry), "w") as f:
        f.write(ECHO)
    sh = proj.file_hash(os.path.join(root, entry))
    manifest = {"manifest_version": 1, "nome": "demo", "versao": "1",
                "requirements": {},
                "scripts": {"echo": {"entrypoint": entry, "script_hash": sh,
                                     "exigencia": {"mem_mb": 256, "cpu_cores": 1}}}}
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump(manifest, f, sort_keys=True, indent=2)
    return sh


class QuadrantE2ETest(unittest.TestCase):
    """O quadrante inteiro, montado pela operação, rodando o ciclo do usuário
    final: cliente web → Locutus → núcleo → drone → resultado de volta."""

    def test_mounted_quadrant_full_cycle(self):
        prov = provision_quadrante(n_drones=1, n_admins=0, clients=["cli"],
                                   host="127.0.0.1", port=0)
        db = mongomock.MongoClient().db
        locutus = MemoryLocutus()
        core = CoreNode(prov["core"], db=db, locutus=locutus, blobs=MemoryBlobStore())
        core.start(run_loops=False)  # só o servidor; driblamos poll/reap manualmente
        self.addCleanup(core.stop)

        # Publica o BOT + o workflow (caminho do admin, via o registro do núcleo).
        d = tempfile.mkdtemp(prefix="myass-bot-")
        sh = make_bot(d)
        ph = core.registry.publish_bot(proj.pack(d), publicado_por="admin")
        wf = {"nome": "fluxo", "versao": "1", "raiz": {"tipo": "block", "filhos": [
            {"tipo": "action", "nome": "T", "params": {"v": "$input.texto"},
             "bot_ref": {"project_hash": ph, "script_hash": sh}}]}}
        wf_hash = core.registry.publish_workflow(wf, publicado_por="admin")

        # O usuário (browser) deposita o pedido cifrado no Locutus.
        secret = bytes.fromhex(prov["clients"][0]["secret"])
        req = {"request_id": "r1", "action": "start_occurrence",
               "workflow_hash": wf_hash, "inputs": {"texto": "oi"}}
        locutus.put(C.request_address(secret),
                    C.seal_request(C.request_key(secret), json.dumps(req).encode()))

        # Núcleo puxa o pedido e cria a ocorrência (enfileira a 1ª atividade).
        self.assertEqual(core.poll_once(), 1)
        core.broker.wait_for_loaders(timeout=2)  # ring quente p/ o drone pegar

        # O drone conecta, baixa o BOT (PROJECT_GET) e executa.
        drone_cfg = prov["drones"][0]
        drone_cfg["endpoint"]["port"] = core.port
        drone = DroneNode(drone_cfg, cache=ProjectCache(tempfile.mkdtemp()))
        self.addCleanup(drone.close)
        drone.connect()
        aid = drone.poll_and_run()
        self.assertIsNotNone(aid)

        # O resultado voltou ao cliente pelo SET (Locutus), cifrado.
        blob = locutus.get(C.response_address(secret))
        self.assertIsNotNone(blob)
        resp = json.loads(C.open_response(C.response_key(secret), blob))["body"]
        self.assertEqual(resp["status"], "done")
        self.assertEqual(resp["result"], {"echo": {"v": "oi"}})


if __name__ == "__main__":
    unittest.main()
