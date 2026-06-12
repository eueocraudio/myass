"""Task10 — gera um relatório PDF rico e salva em /tmp/<UUID>.pdf."""

import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.io import run  # noqa: E402
from lib.minipdf import Pdf  # noqa: E402


def main(params, occ):
    rel = params.get("relatorio") or []
    pdf = Pdf()
    pdf.title("Relatório de Vulnerabilidades (CVE)")
    pdf.line(f"Ocorrência: {occ}")
    pdf.line(f"Total de CVEs analisados: {len(rel)}")
    pdf.line(f"Gerado em: {params.get('gerado_em', '?')}")

    pdf.heading("Sumário")
    for d in rel:
        dd = d.get("dados") or {}
        kev = "KEV" if d.get("kev") and "erro" not in (d.get("kev") or {}) else "-"
        pdf.line(f"{d.get('cve')}  | sev={dd.get('severidade', '?')} "
                 f"score={dd.get('score', '?')} | {kev} | "
                 f"exploits={len(d.get('exploits') or [])}")

    for d in rel:
        dd = d.get("dados") or {}
        pdf.spacer()
        pdf.rule()
        pdf.heading(d.get("cve", "?"))
        if dd.get("titulo"):
            pdf.line("Título: " + str(dd["titulo"]))
        pdf.line(f"Severidade: {dd.get('severidade', '?')}   "
                 f"Score: {dd.get('score', '?')}   Estado: {dd.get('estado', '?')}")
        if dd.get("vetor"):
            pdf.line("Vetor: " + str(dd["vetor"]))
        if d.get("kev") and "erro" not in (d.get("kev") or {}):
            k = d["kev"]
            pdf.line(f"CISA KEV: adicionado {k.get('dateAdded')} | prazo {k.get('dueDate')}")
        if dd.get("cwe"):
            pdf.line("CWE: " + ", ".join(dd["cwe"]))
        if dd.get("descricao"):
            pdf.heading("Descrição", 12)
            pdf.line(dd["descricao"])
        if d.get("exploits"):
            pdf.heading("Exploits", 12)
            for e in d["exploits"][:10]:
                pdf.line(f"- [{e.get('id')}] {e.get('descricao')}")
        if d.get("entities"):
            pdf.heading("Entidades (NER)", 12)
            pdf.line(", ".join(d["entities"][:40]))
        if d.get("refs"):
            pdf.heading("Referências", 12)
            for r in d["refs"]:
                pdf.line("- " + str(r.get("url", "")))

    path = f"/tmp/{uuid.uuid4()}.pdf"
    pdf.save(path)
    return {"pdf_path": path, "total": len(rel)}


if __name__ == "__main__":
    run(main)
