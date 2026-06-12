"""Task09 — junta os docs de todos os filhos (o array do join) em um só.

Recebe ``{"cves": [doc_cve, ...]}`` (a saída do join do loop) e devolve o
relatório consolidado, ordenado por score CVSS desc.
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.io import run  # noqa: E402


def _score(doc):
    try:
        return float((doc.get("dados") or {}).get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def main(params, occ):
    cves = params.get("cves") or []
    relatorio = sorted(cves, key=_score, reverse=True)
    return {
        "relatorio": relatorio,
        "total": len(relatorio),
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


if __name__ == "__main__":
    run(main)
