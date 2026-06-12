"""Ferramenta de publicação do bot_cve: gera manifest.json e workflow.json.

Faz o papel do editor/ferramenta de publicação (ver *BOT — anatomia* e
*Serialização do template* em CLAUDE.md): computa os hashes de conteúdo (BLAKE2)
e emite os dois artefatos em JSON canônico (UTF-8, chaves ordenadas, indent 2).

    python build.py        # (re)gera manifest.json e workflow.json

- script_hash  = blake2:<blake2b do arquivo do script>
- project_hash = blake2:<blake2b da árvore (caminho normalizado, hash) ordenada>
- template_hash= blake2:<blake2b do JSON canônico do template>
"""

import hashlib
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

# Arquivos que compõem o BOT executável (entram no project_hash). Dev-tooling
# (test/, build.py, workflow.json, README, caches) fica de fora.
INCLUDE_DIRS = ("lib", "scripts", "data")
INCLUDE_FILES = ("manifest.json",)
EXCLUDE = {"__pycache__"}

# Metadados por script (exigência de hardware, capacidades, APIs, schema).
SCRIPTS = {
    "split-cves": {
        "entrypoint": "scripts/task01_split.py",
        "exigencia": {"mem_mb": 256, "cpu_cores": 1},
        "capacidades": [], "apis": [],
        "params": {"texto": {"tipo": "str", "obrigatorio": True}},
        "retorno": {"cves": {"tipo": "list"}},
    },
    "fetch-cve": {
        "entrypoint": "scripts/task03_fetch.py",
        "exigencia": {"mem_mb": 512, "cpu_cores": 1},
        "capacidades": [], "apis": ["https://cveawg.mitre.org"],
        "params": {"cve": {"tipo": "str", "obrigatorio": True}},
        "retorno": {"cve": {"tipo": "str"}, "dados": {"tipo": "dict"},
                    "referencias": {"tipo": "list"}},
    },
    "check-kev": {
        "entrypoint": "scripts/task04_kev.py",
        "exigencia": {"mem_mb": 512, "cpu_cores": 1},
        "capacidades": [], "apis": ["https://www.cisa.gov"],
        "params": {"cve": {"tipo": "str", "obrigatorio": True}},
        "retorno": {"kev": {"tipo": "dict"}},
    },
    "find-exploit": {
        "entrypoint": "scripts/task05_exploit.py",
        "exigencia": {"mem_mb": 512, "cpu_cores": 1},
        "capacidades": [], "apis": ["https://www.exploit-db.com"],
        "params": {"cve": {"tipo": "str", "obrigatorio": True}},
        "retorno": {"exploits": {"tipo": "list"}},
    },
    "fetch-refs": {
        "entrypoint": "scripts/task06_refs.py",
        "exigencia": {"mem_mb": 512, "cpu_cores": 1},
        "capacidades": [], "apis": ["*"],
        "params": {"referencias": {"tipo": "list", "obrigatorio": False}},
        "retorno": {"refs": {"tipo": "list"}},
    },
    "ner-spacy": {
        "entrypoint": "scripts/task07_ner.py",
        "exigencia": {"mem_mb": 4096, "cpu_cores": 2},
        "capacidades": ["spacy:en_core_web_md"], "apis": [],
        "params": {"dados": {"tipo": "dict", "obrigatorio": False}},
        "retorno": {"entities": {"tipo": "list"}},
    },
    "save-cve": {
        "entrypoint": "scripts/task08_save.py",
        "exigencia": {"mem_mb": 256, "cpu_cores": 1},
        "capacidades": [], "apis": [],
        "params": {"cve": {"tipo": "str", "obrigatorio": True}},
        "retorno": {"salvo": {"tipo": "bool"}},
    },
    "consolidate": {
        "entrypoint": "scripts/task09_consolidate.py",
        "exigencia": {"mem_mb": 256, "cpu_cores": 1},
        "capacidades": [], "apis": [],
        "params": {"cves": {"tipo": "list", "obrigatorio": True}},
        "retorno": {"relatorio": {"tipo": "list"}, "total": {"tipo": "int"}},
    },
    "build-pdf": {
        "entrypoint": "scripts/task10_pdf.py",
        "exigencia": {"mem_mb": 512, "cpu_cores": 1},
        "capacidades": [], "apis": [],
        "params": {"relatorio": {"tipo": "list", "obrigatorio": True}},
        "retorno": {"pdf_path": {"tipo": "str"}},
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
        "nome": "bot_cve",
        "versao": "1.0",
        "descricao": "Coleta, enriquece e relata CVEs (MITRE + CISA KEV + exploit-db + NER).",
        "requirements": {},  # tudo stdlib; spaCy é capacidade do block (classe B)
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
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT)
                entries.append((rel, file_hash(rel)))
    for fn in INCLUDE_FILES:
        entries.append((fn, file_hash(fn)))
    entries.sort()
    tree = "\n".join(f"{rel}\t{h}" for rel, h in entries)
    return _blake2(tree.encode("utf-8"))


def script_ref(proj: str, nome: str) -> dict:
    return {"project_hash": proj, "script_hash": file_hash(SCRIPTS[nome]["entrypoint"])}


def build_workflow(proj: str) -> dict:
    """O template Nassi. Convenção de dados (provisória, até o motor de workflow):
    "$input.X" = entrada do workflow · "$item" = item do loop · "$prev" = saída
    da atividade anterior no corpo · "$node.<Nome>" = saída de um nó nomeado ·
    "$join" = array de retornos do loop."""
    body = {
        "tipo": "block",
        "filhos": [
            {"tipo": "action", "nome": "Task03", "bot_ref": script_ref(proj, "fetch-cve"),
             "params": {"cve": "$item"}},
            {"tipo": "action", "nome": "Task04", "bot_ref": script_ref(proj, "check-kev"),
             "params": "$prev"},
            {"tipo": "action", "nome": "Task05", "bot_ref": script_ref(proj, "find-exploit"),
             "params": "$prev"},
            {"tipo": "action", "nome": "Task06", "bot_ref": script_ref(proj, "fetch-refs"),
             "params": "$prev",
             "catch": [{"match": "*", "disposicao": "ignorar"}]},
            {"tipo": "action", "nome": "Task07", "bot_ref": script_ref(proj, "ner-spacy"),
             "params": "$prev"},
            {"tipo": "action", "nome": "Task08", "bot_ref": script_ref(proj, "save-cve"),
             "params": "$prev"},
        ],
    }
    template = {
        "template_version": 1,
        "nome": "bot_cve",
        "versao": "1.0",
        "tipo": "workflow",
        "raiz": {
            "tipo": "block",
            "filhos": [
                {"tipo": "action", "nome": "Task01", "bot_ref": script_ref(proj, "split-cves"),
                 "params": {"texto": "$input.texto"}},
                {"tipo": "loop", "nome": "Task02", "array": "$node.Task01.cves",
                 "item": "cve", "corpo": body, "join": "cves"},
                {"tipo": "action", "nome": "Task09", "bot_ref": script_ref(proj, "consolidate"),
                 "params": {"cves": "$node.Task02.join"}},
                {"tipo": "action", "nome": "Task10", "bot_ref": script_ref(proj, "build-pdf"),
                 "params": "$node.Task09"},
            ],
        },
    }
    return template


def main():
    # 1) manifest (precisa existir antes do project_hash, que o cobre)
    manifest = build_manifest()
    with open(os.path.join(ROOT, "manifest.json"), "w", encoding="utf-8") as f:
        f.write(canonical(manifest))

    # 2) project_hash sobre a árvore (já com o manifest escrito)
    proj = project_hash()

    # 3) workflow + template_hash
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
