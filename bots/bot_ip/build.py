"""Ferramenta de publicação do bot_ip: gera manifest.json e workflow.json.

Uso:
    python build.py        # (re)gera manifest.json e workflow.json

- project_hash = blake2:<blake2b da árvore (caminho normalizado, hash) ordenada>
- script_hash  = blake2:<blake2b do arquivo do entrypoint>
- template_hash = blake2:<blake2b do JSON canônico do template>

Publica-se só o subconjunto executável (lib/ + scripts/ + manifest.json) — não a
pasta crua, senão o project_hash não casa com o bot_ref do workflow.
"""

import hashlib
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

INCLUDE_DIRS = ("lib", "scripts")
INCLUDE_FILES = ("manifest.json",)
EXCLUDE = {"__pycache__"}

# Metadados por script. As API keys (Shodan/AbuseIPDB) e o destino de upload vivem no
# ENV DO DRONE (capacidade do block), nunca no pedido — por isso aqui são
# `capacidades`, não `params`. `apis` declara o egress (sai via Tor).
SCRIPTS = {
    "split-ips": {
        "entrypoint": "scripts/task01_split.py",
        "exigencia": {"mem_mb": 256, "cpu_cores": 1},
        "capacidades": [], "apis": [],
        "params": {"texto": {"tipo": "str", "obrigatorio": True}},
        "retorno": {"ips": {"tipo": "list"}},
    },
    "shodan-host": {
        "entrypoint": "scripts/task02_shodan.py",
        "exigencia": {"mem_mb": 512, "cpu_cores": 1},
        "capacidades": ["api:shodan"], "apis": ["https://api.shodan.io"],
        "params": {"ip": {"tipo": "str", "obrigatorio": True}},
        "retorno": {"ip": {"tipo": "str"}, "shodan": {"tipo": "dict"}},
    },
    "abuse-check": {
        "entrypoint": "scripts/task03_abuseipdb.py",
        "exigencia": {"mem_mb": 512, "cpu_cores": 1},
        "capacidades": ["api:abuseipdb"], "apis": ["https://api.abuseipdb.com"],
        "params": {"ip": {"tipo": "str", "obrigatorio": True}},
        "retorno": {"abuseipdb": {"tipo": "dict"}},
    },
    "report-pdf": {
        "entrypoint": "scripts/task04_report.py",
        "exigencia": {"mem_mb": 512, "cpu_cores": 1},
        "capacidades": [], "apis": [],
        "params": {"ips": {"tipo": "list", "obrigatorio": True}},
        "retorno": {"pdf": {"tipo": "dict"}, "total": {"tipo": "int"}},
    },
    "publish": {
        "entrypoint": "scripts/task05_upload.py",
        "exigencia": {"mem_mb": 256, "cpu_cores": 1},
        "capacidades": ["upload:endpoint"], "apis": ["*"],
        "params": {"pdf": {"tipo": "dict", "obrigatorio": True}},
        "retorno": {"upload_url": {"tipo": "str"}},
    },
}


def _blake2(data: bytes) -> str:
    return "blake2:" + hashlib.blake2b(data).hexdigest()


def file_hash(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "rb") as f:
        return _blake2(f.read())


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def build_manifest() -> dict:
    scripts = {}
    for nome, meta in SCRIPTS.items():
        scripts[nome] = {
            "entrypoint": meta["entrypoint"],
            "script_hash": file_hash(meta["entrypoint"]),
            "exigencia": meta["exigencia"],
            "capacidades": meta["capacidades"],
            "apis": meta["apis"],
            "params": meta["params"],
            "retorno": meta["retorno"],
        }
    return {
        "manifest_version": 1,
        "nome": "bot_ip",
        "versao": "0.2",
        "descricao": "Extrai IPs de WAN de um texto, enriquece (Shodan + AbuseIPDB) "
                     "e publica um relatório PDF num serviço de upload.",
        "requirements": {},  # tudo stdlib
        "scripts": scripts,
    }


def project_hash() -> str:
    entries = []
    for d in INCLUDE_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in EXCLUDE]
            for fn in filenames:
                if fn.endswith(".pyc"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                entries.append((rel, file_hash(rel)))
    for fn in INCLUDE_FILES:
        entries.append((fn, file_hash(fn)))
    entries.sort()
    tree = "\n".join(f"{rel}\t{h}" for rel, h in entries)
    return _blake2(tree.encode("utf-8"))


def script_ref(proj: str, nome: str) -> dict:
    return {"project_hash": proj, "script_hash": file_hash(SCRIPTS[nome]["entrypoint"])}


def build_workflow(proj: str) -> dict:
    """Template Nassi do bot_ip (mesma estrutura/nomes do esquema do dono).
    Refs: "$input.X" entrada · "$item" item do loop · "$prev" saída anterior no
    corpo · "$node.<Nome>.<campo>" saída de um nó nomeado · ".join" array do loop."""
    body = {
        "tipo": "block",
        "filhos": [
            {"tipo": "action", "nome": "02_01_shodan",
             "bot_ref": script_ref(proj, "shodan-host"), "params": {"ip": "$item"}},
            {"tipo": "action", "nome": "02_02_abuseipdb",
             "bot_ref": script_ref(proj, "abuse-check"), "params": "$prev"},
        ],
    }
    return {
        "template_version": 1,
        "nome": "bot_ip",
        "versao": "0.2",
        "tipo": "workflow",
        "raiz": {
            "tipo": "block",
            "filhos": [
                {"tipo": "action", "nome": "01_quebrar_texto",
                 "bot_ref": script_ref(proj, "split-ips"),
                 "params": {"texto": "$input.texto"}},
                {"tipo": "loop", "nome": "02_dividir",
                 "array": "$node.01_quebrar_texto.ips", "item": "ip",
                 "corpo": body, "join": "itens"},
                {"tipo": "action", "nome": "03_report",
                 "bot_ref": script_ref(proj, "report-pdf"),
                 "params": {"ips": "$node.02_dividir.join"}},
                {"tipo": "action", "nome": "04_publish",
                 "bot_ref": script_ref(proj, "publish"), "params": "$node.03_report"},
            ],
        },
    }


def main():
    manifest = build_manifest()
    with open(os.path.join(ROOT, "manifest.json"), "w", encoding="utf-8") as f:
        f.write(canonical(manifest))
    proj = project_hash()
    template = build_workflow(proj)
    template_hash = _blake2(canonical(template).encode("utf-8"))
    workflow = {"template_hash": template_hash, "template": template}
    with open(os.path.join(ROOT, "workflow.json"), "w", encoding="utf-8") as f:
        f.write(canonical(workflow))
    print("project_hash :", proj)
    print("template_hash:", template_hash)
    print("scripts      :", len(SCRIPTS))


if __name__ == "__main__":
    main()
