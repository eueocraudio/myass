"""Sobe um quadrante sobre INFRA REAL e roda o ciclo do admin de ponta a ponta.

Processos de verdade (não in-process): um MongoDB real (localhost:27017), o
**núcleo** e o **drone** como subprocessos (`python -m myass.ops core|drone`),
conversando por sockets TCP reais (transporte direto Noise). O admin publica um
BOT + workflow, inicia uma ocorrência e acompanha até concluir — o drone baixa o
BOT via PROJECT_GET (GridFS real) e executa.

Pré-requisito: um `mongod` rodando em localhost:27017. Uso:
    PYTHONPATH=src python examples/run_real_quadrant.py
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from myass.client.admin import AdminClient          # noqa: E402
from myass.executor import project as proj          # noqa: E402
from myass.noise import primitives as P             # noqa: E402
from myass.ops import provision                     # noqa: E402

ECHO = ("import sys, json, os\n"
        "cfg=json.loads(sys.stdin.readline())\n"
        "wd=cfg['workdir']\n"
        "inp=json.load(open(os.path.join(wd,'input.json')))\n"
        "json.dump({'echo': inp['params']}, open(os.path.join(wd,'output.json'),'w'))\n")


def make_bot(root):
    os.makedirs(os.path.join(root, "scripts"))
    with open(os.path.join(root, "scripts/echo.py"), "w") as f:
        f.write(ECHO)
    sh = proj.file_hash(os.path.join(root, "scripts/echo.py"))
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump({"manifest_version": 1, "nome": "demo", "versao": "1",
                   "requirements": {},
                   "scripts": {"echo": {"entrypoint": "scripts/echo.py",
                                        "script_hash": sh,
                                        "exigencia": {"mem_mb": 256, "cpu_cores": 1}}}},
                  f, sort_keys=True, indent=2)
    return sh


def wait_port(port, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def spawn(args, env):
    return subprocess.Popen([sys.executable, "-m", "myass.ops", *args],
                            cwd=ROOT, env=env)


def main():
    quad = tempfile.mkdtemp(prefix="quad-")
    port = 8400
    prov = provision.provision_quadrante(n_drones=1, n_admins=1, host="127.0.0.1",
                                         port=port)
    for name, obj in [("core.json", prov["core"]),
                      ("drone-0.json", prov["drones"][0]),
                      ("admin-0.json", prov["admins"][0])]:
        with open(os.path.join(quad, name), "w") as f:
            json.dump(obj, f)

    env = {**os.environ, "PYTHONPATH": SRC, "QT_QPA_PLATFORM": "offscreen"}
    core = spawn(["core", "--config", os.path.join(quad, "core.json")], env)
    drone = None
    try:
        assert wait_port(port), "núcleo não subiu"
        print(f"[ok] núcleo no ar (pid {core.pid}) em 127.0.0.1:{port}")
        drone = spawn(["drone", "--config", os.path.join(quad, "drone-0.json"),
                       "--cache", os.path.join(quad, "cache")], env)
        print(f"[ok] drone no ar (pid {drone.pid})")
        time.sleep(2)

        cfg = prov["admins"][0]
        admin = AdminClient(
            cfg["endpoint"], bytes.fromhex(cfg["prologue"]),
            P.load_private(bytes.fromhex(cfg["static_priv"])),
            bytes.fromhex(cfg["static_pub"]), bytes.fromhex(cfg["scheduler_pub"]),
            bytes.fromhex(cfg["psk"]))
        with admin:
            botdir = tempfile.mkdtemp(prefix="bot-")
            sh = make_bot(botdir)
            bot = admin.publish_bot_dir(botdir)
            print(f"[ok] BOT publicado: {bot['status']} {bot['hash'][:24]}…")
            wf = {"nome": "fluxo", "versao": "1", "raiz": {"tipo": "block", "filhos": [
                {"tipo": "action", "nome": "T", "params": {"v": "$input.texto"},
                 "bot_ref": {"project_hash": bot["hash"], "script_hash": sh}}]}}
            wfa = admin.publish_workflow(wf)
            print(f"[ok] workflow publicado: {wfa['status']} {wfa['hash'][:24]}…")
            occ = admin.start_occurrence(wfa["hash"], {"texto": "oi infra real"})
            occ_id = occ["occurrence_id"]
            print(f"[ok] ocorrência iniciada: {occ_id}")

            for _ in range(30):
                time.sleep(1)
                done = [o for o in admin.list_occurrences()
                        if o["occurrence_id"] == occ_id and o["status"] != "running"]
                if done:
                    o = done[0]
                    print(f"[ok] ocorrência {o['status']}: result={o['result']}")
                    assert o["status"] == "done"
                    assert o["result"] == {"echo": {"v": "oi infra real"}}
                    print("\n>>> QUADRANTE RODOU SOBRE INFRA REAL (mongod + 2 processos + sockets) <<<")
                    return
            raise SystemExit("ocorrência não concluiu a tempo")
    finally:
        for p in (drone, core):
            if p:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()


if __name__ == "__main__":
    main()
