"""Task04 — anota se o CVE está no catálogo KEV da CISA (enriquecimento).

Não ramifica o fluxo (não é decision): só adiciona o campo ``kev`` ao doc.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.http import get_json  # noqa: E402
from lib.io import run  # noqa: E402

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
_FIELDS = ("dateAdded", "dueDate", "vulnerabilityName",
           "knownRansomwareCampaignUse", "requiredAction")


def main(params, occ):
    doc = params
    cve = doc["cve"].upper()
    doc["kev"] = None
    try:
        feed = get_json(KEV_URL, timeout=60)
        for v in feed.get("vulnerabilities", []):
            if (v.get("cveID") or "").upper() == cve:
                doc["kev"] = {k: v.get(k) for k in _FIELDS}
                break
    except Exception as e:  # noqa: BLE001
        doc["kev"] = {"erro": str(e)}
    return doc


if __name__ == "__main__":
    run(main)
