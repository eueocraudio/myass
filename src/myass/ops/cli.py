"""CLIs de operação do quadrante — provisionar e subir os processos reais.

    python -m myass.ops provision --out ./quadrante --drones 1 --admins 1 --clients alice
    python -m myass.ops core  --config ./quadrante/core.json   [--mongo URI] [--onion]
    python -m myass.ops drone --config ./quadrante/drone-0.json [--cache DIR]
    python -m myass.ops admin --config ./quadrante/admin-0.json publish-bot ./bots/bot_cve
    python -m myass.ops admin --config ./quadrante/admin-0.json start <workflow_hash> '{"texto":"oi"}'
    python -m myass.ops admin --config ./quadrante/admin-0.json list

O `provision` roda na estação parteira (offline). `core`/`drone` rodam sobre infra
real (mongod + Tor). Transporte: direto na LAN/localhost; `--onion` publica o
serviço onion (precisa de Tor com ControlPort).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time

from ..noise import primitives as P
from . import nodes, provision


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---- provision --------------------------------------------------------
def cmd_provision(a):
    os.makedirs(a.out, exist_ok=True)
    prov = provision.provision_quadrante(
        n_drones=a.drones, n_admins=a.admins, clients=a.clients or [],
        host=a.host, port=a.port, locutus_url=a.locutus)
    _write(os.path.join(a.out, "core.json"), prov["core"])
    for i, d in enumerate(prov["drones"]):
        _write(os.path.join(a.out, f"drone-{i}.json"), d)
    for i, adm in enumerate(prov["admins"]):
        _write(os.path.join(a.out, f"admin-{i}.json"), adm)
    _write(os.path.join(a.out, "clients.json"), prov["clients"])
    print(f"provisionado em {a.out}: scheduler_pub={prov['scheduler_pub'][:16]}…  "
          f"drones={a.drones} admins={a.admins} clients={len(a.clients or [])}")
    print("ATENÇÃO: as chaves privadas estão nas configs — distribua out-of-band.")


# ---- core -------------------------------------------------------------
def cmd_core(a):
    from ..storage.db import connect
    cfg = _read(a.config)
    db = connect(a.mongo) if a.mongo else connect()
    core = nodes.CoreNode(cfg, db=db)
    onion = None
    if a.onion:
        from ..noise.tor import OnionService
        # client_pubs: as pubs de auth dos drones devem ser geradas no provision
        # (ver ops/provision para incluir client-auth); aqui publicamos sem auth
        # de descritor se não fornecidas (o Noise KKpsk0 ainda protege).
        onion = OnionService(cfg["port"], control_port=a.control_port)
    port = core.start(run_loops=True)
    msg = f"núcleo no ar em {cfg['host']}:{port}"
    if onion:
        onion.__enter__()
        msg += f" · onion {onion.onion_address}"
    print(msg + " (Ctrl+C para parar)")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        while not stop.is_set():
            stop.wait(1)
    finally:
        if onion:
            onion.__exit__(None, None, None)
        core.stop()
        print("núcleo parado.")


# ---- drone ------------------------------------------------------------
def cmd_drone(a):
    cfg = _read(a.config)
    if a.cache:
        cfg["cache_dir"] = a.cache
    drone = nodes.DroneNode(cfg)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    print(f"drone {cfg['id']} conectando a {cfg['endpoint']} (Ctrl+C para parar)")
    drone.run(stop)
    drone.close()
    print("drone parado.")


# ---- admin ------------------------------------------------------------
def cmd_admin(a):
    from ..client.admin import AdminClient
    cfg = _read(a.config)
    client = AdminClient(
        cfg["endpoint"], bytes.fromhex(cfg["prologue"]),
        P.load_private(bytes.fromhex(cfg["static_priv"])),
        bytes.fromhex(cfg["static_pub"]), bytes.fromhex(cfg["scheduler_pub"]),
        bytes.fromhex(cfg["psk"]))
    with client:
        if a.action == "publish-bot":
            from ..executor import project as proj
            print(client.publish_bot(proj.pack(a.arg)))
        elif a.action == "publish-workflow":
            print(client.publish_workflow(_read(a.arg)))
        elif a.action == "start":
            inputs = json.loads(a.arg2) if a.arg2 else {}
            print(client.start_occurrence(a.arg, inputs))
        elif a.action == "list":
            print(json.dumps(client.list_occurrences(), ensure_ascii=False, indent=2))
        elif a.action == "catalog":
            print(json.dumps(client.catalog(), ensure_ascii=False, indent=2))
        elif a.action == "env":
            print(json.dumps(client.environment(), ensure_ascii=False, indent=2))
        else:
            print(f"ação desconhecida: {a.action}", file=sys.stderr)


def main(argv=None):
    p = argparse.ArgumentParser(prog="myass.ops")
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("provision")
    pv.add_argument("--out", default="./quadrante")
    pv.add_argument("--drones", type=int, default=1)
    pv.add_argument("--admins", type=int, default=1)
    pv.add_argument("--clients", nargs="*", default=[])
    pv.add_argument("--host", default="127.0.0.1")
    pv.add_argument("--port", type=int, default=8400)
    pv.add_argument("--locutus", default="")
    pv.set_defaults(fn=cmd_provision)

    pc = sub.add_parser("core")
    pc.add_argument("--config", required=True)
    pc.add_argument("--mongo", default="")
    pc.add_argument("--onion", action="store_true")
    pc.add_argument("--control-port", type=int, default=9051)
    pc.set_defaults(fn=cmd_core)

    pd = sub.add_parser("drone")
    pd.add_argument("--config", required=True)
    pd.add_argument("--cache", default="")
    pd.set_defaults(fn=cmd_drone)

    pa = sub.add_parser("admin")
    pa.add_argument("--config", required=True)
    pa.add_argument("action")
    pa.add_argument("arg", nargs="?")
    pa.add_argument("arg2", nargs="?")
    pa.set_defaults(fn=cmd_admin)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
