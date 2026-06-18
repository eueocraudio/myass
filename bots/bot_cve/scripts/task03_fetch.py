"""Task03 — obtém os dados-base do CVE (MITRE CVE Services, JSON rico).

Dados-base vêm do MITRE (cveawg.mitre.org): título, descrição, referências, CWE.
O **CVSS** (score/vetor) muitas vezes não está no container do CNA, mas está no
container **ADP** (CISA ADP Vulnrichment) — buscamos nos dois, na mesma chamada
(o NVD é instável/limitado, então não dependemos dele). O exploit-db fica
reservado para os exploits (Task05).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.cvss import decode as cvss_decode  # noqa: E402
from lib.http import get_json  # noqa: E402
from lib.io import run  # noqa: E402

API = "https://cveawg.mitre.org/api/cve/{}"


def _sev(score):
    if score is None:
        return "?"
    s = float(score)
    return ("None" if s == 0 else "Low" if s < 4 else "Medium"
            if s < 7 else "High" if s < 9 else "Critical")


def _title_from(desc):
    """Título derivado da descrição (1ª frase) — a MITRE costuma não trazer title."""
    s = " ".join((desc or "").split())
    if not s:
        return None
    i = s.find(". ")
    cand = s[:i] if 0 < i <= 140 else s
    return cand if len(cand) <= 140 else cand[:120].rstrip() + "…"


def _metrics_from(container):
    """Primeiro CVSS com vectorString encontrado num container (cna/adp)."""
    for m in (container.get("metrics") or []):
        for v in m.values():
            if isinstance(v, dict) and v.get("vectorString"):
                return v.get("baseScore"), v.get("vectorString"), v.get("baseSeverity")
    return None, None, None


def _parse(js):
    containers = js.get("containers") or {}
    cna = containers.get("cna") or {}
    adps = containers.get("adp") or []
    meta = js.get("cveMetadata") or {}
    descs = cna.get("descriptions") or []

    # CVSS: tenta o CNA, depois os ADP (CISA Vulnrichment costuma ter).
    score, vetor, sev = _metrics_from(cna)
    if not vetor:
        for adp in adps:
            score, vetor, sev = _metrics_from(adp)
            if vetor:
                break

    # CWE (id + descrição): CNA e ADP, deduplicado.
    cwe = []
    for cont in [cna, *adps]:
        for p in (cont.get("problemTypes") or []):
            for d in (p.get("descriptions") or []):
                cid = d.get("cweId")
                if cid and not any(c["id"] == cid for c in cwe):
                    cwe.append({"id": cid, "description": d.get("description", "")})

    descricao = descs[0]["value"] if descs else None
    return {
        "titulo": cna.get("title") or _title_from(descricao),
        "descricao": descricao,
        "estado": meta.get("state"),
        "publicado": meta.get("datePublished"),
        "atualizado": meta.get("dateUpdated"),
        "score": score,
        "vetor": vetor,
        "vector_details": cvss_decode(vetor),  # Vector Details (CVSS decodificado)
        "severidade": sev or _sev(score),
        "cwe": cwe,
        "referencias": [r.get("url") for r in (cna.get("references") or []) if r.get("url")],
    }


def main(params, occ):
    cve = params["cve"].upper()
    doc = {"cve": cve, "dados": {}, "referencias": []}
    try:
        dados = _parse(get_json(API.format(cve)))
        doc["dados"] = dados
        doc["referencias"] = dados.get("referencias", [])
    except Exception as e:  # noqa: BLE001  (degrada: relatório parcial > nenhum)
        doc["dados"] = {"erro": str(e)}
    return doc


if __name__ == "__main__":
    run(main)
