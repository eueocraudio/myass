"""Task10 — gera o relatório PDF (bonito, colorido, tabulado e justificado) e o
devolve **inline (base64)** no resultado.

Capa com tabela de severidade + metodologia + índice; e por CVE: banner com
título+score, Publish/Update, vetor CVSS, descrição (justificada), Impact,
Vector Details (tabela), CVSS em versão humana + calculadora, CISA KEV, Exploits,
Knowledge (CVE Mitre), CWE, MITRE ATT&CK (via CWE→CAPEC), Recommended links e
References.

Convenção de arquivo inline: ``{"$b64": "<base64>", "nome": "relatorio.pdf"}``."""

import base64
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.attack import techniques_for, url as attack_url  # noqa: E402
from lib.cvss import calculator_url, options as cvss_options  # noqa: E402
from lib.io import run  # noqa: E402
from lib.minipdf import Pdf  # noqa: E402


def _bucket(score):
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    if s <= 0:
        return None
    return "Low" if s < 4 else "Medium" if s < 7 else "High" if s < 9 else "Critical"


def _titulo(d):
    dd = d.get("dados") or {}
    sc = dd.get("score")
    return (d.get("cve", "?") + (f" ({sc})" if sc is not None else "")
            + ": " + (dd.get("titulo") or ""))


def main(params, occ):
    rel = params.get("relatorio") or []
    pdf = Pdf(title="Vulnerability reporting based on CVE",
              footer="myass — relatório de vulnerabilidades")
    pdf.title("Vulnerability reporting based on CVE")
    pdf.small(f"Gerado em {params.get('gerado_em', '?')}   ·   Total de CVEs: {len(rel)}")

    # ---- tabela de severidade ----
    counts = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
    for d in rel:
        b = _bucket((d.get("dados") or {}).get("score"))
        if b:
            counts[b] += 1
    pdf.heading("Severity table")
    pdf.table(["Severity", "Total"],
              [[k, counts[k]] for k in ("Low", "Medium", "High", "Critical")],
              col_widths=[120, 40], aligns=["L", "R"])

    # ---- methodology ----
    pdf.heading("Methodology")
    pdf.paragraph(
        "Os CVEs são extraídos do texto de entrada e cada um é enriquecido, de "
        "forma automatizada, a partir de fontes autoritativas:")
    for b in ("MITRE CVE Services (cveawg): título, descrição, CWE e referências.",
              "MITRE ADP / CISA Vulnrichment: métricas CVSS (score e vetor).",
              "CISA KEV: indicação de exploração conhecida em campo.",
              "Exploit-DB: exploits públicos associados ao CVE.",
              "Extração de linguagem natural (NER): entidades de impacto e frases.",
              "CWE -> CAPEC -> MITRE ATT&CK: técnicas de adversário relacionadas."):
        pdf.bullet(b)
    pdf.paragraph(
        "O vetor CVSS é decodificado conforme a especificação FIRST.org e a "
        "severidade segue a faixa do score "
        "(Low 0.1–3.9, Medium 4.0–6.9, High 7.0–8.9, Critical 9.0–10.0).")

    # ---- índice clicável (gerado automaticamente: título … nº de página) ----
    pdf.start_toc()

    # ---- um CVE por página (clicável a partir do índice) ----
    for d in rel:
        dd = d.get("dados") or {}
        pdf.page_break()               # item II: 1 CVE por página
        pdf.section(_titulo(d))        # item VIII: CVE (SCORE): TÍTULO no índice
        pdf.banner(_titulo(d))         # item VIII: idem no banner
        pdf.spacer()                   # item III: respiro entre título e Publish

        pub = (dd.get("publicado") or "").split("T")[0]
        upd = (dd.get("atualizado") or "").split("T")[0]
        if pub or upd:
            pdf.kv("Publish:", f"{pub}    Update in: {upd}")
        if dd.get("vetor"):
            pdf.kv("CVSS:", dd["vetor"])
        pdf.kv("Severidade:",
               f"{dd.get('severidade', '?')}   Score: {dd.get('score', '?')}   "
               f"Estado: {dd.get('estado', '?')}")
        if d.get("kev") and "erro" not in (d.get("kev") or {}):
            k = d["kev"]
            pdf.kv("CISA KEV:",
                   f"adicionado {k.get('dateAdded')} | prazo {k.get('dueDate')}")

        if dd.get("descricao"):
            pdf.heading("Descrição", 12)
            pdf.paragraph(dd["descricao"].replace("\n", " "))

        obj = d.get("object") or d.get("entities") or []
        if obj:
            pdf.heading("Impact", 12)
            pdf.paragraph(", ".join(obj[:40]), justify=False)  # lista de termos

        vd = dd.get("vector_details")
        if vd and vd.get("elements"):
            pdf.heading("Vector Details", 12)
            pdf.table(["Métrica", "Valor"],
                      [[m["metric_name"], m["value_name"]] for m in vd["elements"]],
                      col_widths=[160, 120], aligns=["L", "L"])
            opts = cvss_options(dd.get("vetor"))
            if opts:
                pdf.small("Calculadora CVSS (opção selecionada em destaque):")
                pdf.cvss_options(opts)
            calc = calculator_url(dd.get("vetor"))
            if calc:
                pdf.link("Calculadora (interativa): " + calc)
            if vd.get("reference"):
                pdf.small("Reference: " + vd["reference"])

        if d.get("exploits"):
            pdf.heading("Exploits", 12)
            for e in d["exploits"][:10]:
                desc = e.get("descricao")
                if isinstance(desc, list):  # exploit-db: ["<id>", "<título>"]
                    desc = " ".join(str(x) for x in desc[1:]) or " ".join(map(str, desc))
                pdf.bullet(str(desc or e.get("text") or e.get("id") or ""))
                href = e.get("href") or e.get("url")
                if not href and e.get("id"):
                    href = "https://www.exploit-db.com/exploits/" + str(e["id"])
                if href:
                    pdf.link(str(href), indent=24)

        if d.get("lista_knowledge"):
            pdf.heading("Knowledge (CVE Mitre)", 12)
            for s in d["lista_knowledge"]:
                pdf.bullet(s)

        if dd.get("cwe"):
            pdf.heading("Common Weakness Enumeration", 12)
            for c in dd["cwe"]:
                cid, desc = c.get("id", ""), c.get("description") or ""
                pdf.bullet(desc if desc.startswith(cid) else f"{cid} {desc}".strip())

        techs = techniques_for([c.get("id") for c in (dd.get("cwe") or [])])
        if techs:
            pdf.heading("MITRE ATT&CK Techniques", 12)
            pdf.table(["Técnica", "Nome"],
                      [[t["id"], t["name"]] for t in techs],
                      col_widths=[70, 230], aligns=["L", "L"])
            for t in techs:
                pdf.link(attack_url(t["id"]))

        pdf.heading("Recommended links", 12)
        cid = d.get("cve", "")
        for u in ("https://vulmon.com/vulnerabilitydetails?qid=" + cid,
                  "https://www.cvedetails.com/cve/" + cid + "/",
                  "https://nvd.nist.gov/vuln/detail/" + cid):
            pdf.link(u)
        for c in (dd.get("cwe") or []):
            num = str(c.get("id", "")).split("-")[-1]
            if num.isdigit():
                pdf.link("https://cwe.mitre.org/data/definitions/" + num + ".html")

        refs = dd.get("referencias") or d.get("referencias") or []
        if refs:
            pdf.heading("Reference", 12)
            for u in refs:
                pdf.small(str(u))

    b64 = base64.b64encode(pdf.render()).decode("ascii")
    return {"pdf": {"$b64": b64, "nome": "relatorio.pdf"}, "total": len(rel)}


if __name__ == "__main__":
    run(main)
