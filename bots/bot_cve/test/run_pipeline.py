"""Plano de teste do bot_cve SEM a Rainha.

Espelha o estilo do bot_cve legado (rodar os scripts encadeados via subprocess),
mas usando o **contrato novo** do myass (stdin {"workdir"} + input.json/output.json
— não os 5 args/base64/DatabaseConnector do legado). Simula o que o Scheduler
faria: o cursor linear, o loop foreach (Task02), o join e o catch-ignorar (Task06).

Uso:
    python test/run_pipeline.py                 # usa o texto de exemplo embutido
    python test/run_pipeline.py < entrada.txt   # lê o texto do stdin

Com rede (e, opcionalmente, MYASS_PROXY apontando para o Tor), traz dados reais;
offline, os scripts degradam para um relatório parcial — o pipeline completa
mesmo assim e gera o PDF.
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

EXEMPLO = (
    "CVE-2026-45418 2026-06-11 23h16 +00:00     ClipBucket v5 is an open source "
    "video sharing platform. Prior to version 5.5.3 - #132, any authentic... "
    "SQL Injection     8.8    Alta     CVE-2026-45060     2026-06-11 23h16 +00:00     "
    "ClipBucket v5 is an open source video sharing platform. Prior to version 5.5.3 - "
    "#129, the actions/p... SQL Injection     9.8    Crítica      CVE-2026-42846     "
    "2026-06-11 23h16 +00:00     ClipBucket v5 is an open source video sharing platform. "
    "Prior to version 5.5.3 - #140, ClipBucket's ... OS Command Injection"
)


def run_script(script, occ, params):
    """Roda um script pelo contrato Executor<->script e devolve (output, exit_code)."""
    path = os.path.join(SCRIPTS, script)
    wd = tempfile.mkdtemp(prefix=f"myass-{occ}-")
    try:
        with open(os.path.join(wd, "input.json"), "w", encoding="utf-8") as f:
            json.dump({"occurrence_id": occ, "params": params}, f)
        proc = subprocess.run(
            [sys.executable, path],
            input=(json.dumps({"workdir": wd}) + "\n").encode(),
            capture_output=True,
        )
        out_path = os.path.join(wd, "output.json")
        output = {}
        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                output = json.load(f)
        if proc.stderr:
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        return output, proc.returncode
    finally:
        __import__("shutil").rmtree(wd, ignore_errors=True)


def step(label, script, occ, params, allow_fail=False):
    out, rc = run_script(script, occ, params)
    print(f"--- {label}  (exit={rc}) ---")
    print(json.dumps(out, ensure_ascii=False)[:400])
    if rc != 0 and not allow_fail:
        raise SystemExit(f"{label} falhou (exit {rc}): {out.get('erro')}")
    return out, rc


def main():
    texto = sys.stdin.read() if not sys.stdin.isatty() else EXEMPLO
    if not texto.strip():
        texto = EXEMPLO

    # Task01 — split
    out1, _ = step("Task01 split", "task01_split.py", "occ-test", {"texto": texto})
    cves = out1.get("cves", [])
    print(f"\n>>> {len(cves)} CVEs: {cves}\n")

    # Task02 — FOR (loop foreach): cada CVE vira uma trilha de filho (sync interna)
    docs = []
    for i, cve in enumerate(cves):
        occ = f"occ-test-{i}"
        print(f"\n===== FILHO {i} :: {cve} =====")
        doc, _ = step("Task03 fetch", "task03_fetch.py", occ, {"cve": cve})
        doc, _ = step("Task04 kev", "task04_kev.py", occ, doc)
        doc, _ = step("Task05 exploit", "task05_exploit.py", occ, doc)
        # Task06 — catch: IGNORA (engole) e continua
        out6, rc6 = step("Task06 refs", "task06_refs.py", occ, doc, allow_fail=True)
        if rc6 == 0:
            doc = out6
        else:
            print("    (Task06 falhou -> catch IGNORA, segue sem refs)")
        doc, _ = step("Task07 ner", "task07_ner.py", occ, doc)
        doc, _ = step("Task08 save", "task08_save.py", occ, doc)
        docs.append(doc)

    # join -> array[doc_cve]; Task09 consolida
    print("\n===== JOIN + consolidação =====")
    out9, _ = step("Task09 consolidate", "task09_consolidate.py", "occ-test", {"cves": docs})

    # Task10 — PDF
    out10, _ = step("Task10 pdf", "task10_pdf.py", "occ-test", out9)
    pdf = out10.get("pdf_path")
    print(f"\n>>> PDF gerado: {pdf}")
    if pdf and os.path.exists(pdf):
        with open(pdf, "rb") as f:
            head = f.read(8)
        print(f">>> {os.path.getsize(pdf)} bytes, header={head!r}")


if __name__ == "__main__":
    main()
