"""Task03 — obtém os dados-base do CVE (MITRE CVE API, JSON rico).

Default desta implementação (ver README): dados-base vêm do MITRE
(cveawg.mitre.org), que dá descrição/CVSS/referências/CWE para um relatório rico;
o exploit-db fica reservado para os exploits (Task05). Fácil de trocar.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.http import get_json  # noqa: E402
from lib.io import run  # noqa: E402

API = "https://cveawg.mitre.org/api/cve/{}"


def _sev(score):
    if score is None:
        return "?"
    s = float(score)
    return ("None" if s == 0 else "Low" if s < 4 else "Medium"
            if s < 7 else "High" if s < 9 else "Critical")


def _parse(js):
    cna = (js.get("containers") or {}).get("cna") or {}
    meta = js.get("cveMetadata") or {}
    descs = cna.get("descriptions") or []
    score = vetor = sev = None
    for m in (cna.get("metrics") or []):
        for v in m.values():
            if isinstance(v, dict) and v.get("baseScore") is not None:
                score, vetor, sev = v.get("baseScore"), v.get("vectorString"), v.get("baseSeverity")
                break
        if score is not None:
            break
    cwe = []
    for p in (cna.get("problemTypes") or []):
        for d in (p.get("descriptions") or []):
            if d.get("cweId"):
                cwe.append(d["cweId"])
    return {
        "titulo": cna.get("title"),
        "descricao": descs[0]["value"] if descs else None,
        "estado": meta.get("state"),
        "publicado": meta.get("datePublished"),
        "score": score,
        "vetor": vetor,
        "severidade": sev or _sev(score),
        "cwe": cwe,
        "referencias": [r.get("url") for r in (cna.get("references") or []) if r.get("url")],
    }


def main(params, occ):
    cve = params["cve"].upper()
    doc = {"cve": cve, "dados": {}, "referencias": []}
    try:
        doc["dados"] = _parse(get_json(API.format(cve)))
        doc["referencias"] = doc["dados"].get("referencias", [])
    except Exception as e:  # noqa: BLE001  (degrada: relatório parcial > nenhum)
        doc["dados"] = {"erro": str(e)}
    return doc


if __name__ == "__main__":
    run(main)
