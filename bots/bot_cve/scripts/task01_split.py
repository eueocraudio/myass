"""Task01 — quebra o texto de entrada em CVEs (regex), array uppercase, dedup."""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.io import run  # noqa: E402

_RX = re.compile(r"CVE[-_\s]?(\d{4})[-_\s]?(\d{4,7})", re.IGNORECASE)


def main(params, occ):
    texto = params.get("texto", "") or ""
    out, seen = [], set()
    for ano, num in _RX.findall(texto):
        cve = f"CVE-{ano}-{num}".upper()
        if cve not in seen:
            seen.add(cve)
            out.append(cve)
    return {"cves": out}


if __name__ == "__main__":
    run(main)
