"""Task07 — extrai conhecimento dos textos do CVE.

Porta a ideia do gerador legado (spaCy: entidades → *Impact*; frases → *Knowledge*)
com base **stdlib** robusta e spaCy aproveitado quando disponível:

- ``object`` / ``entities``: entidades nomeadas (NER via spaCy, fallback regex em
  ``lib.text.entities``) — viram a seção **Impact** do relatório.
- ``lista_knowledge``: frases curtas da descrição (+ descrições das métricas
  CVSS), no espírito das frases sujeito-verbo-objeto do legado — viram a seção
  **Knowledge (CVE Mitre)**.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.io import run  # noqa: E402
from lib.text import entities  # noqa: E402

_SENT = re.compile(r"(?<=[.;:])\s+|\n+")
_VERSION_ONLY = re.compile(r"^[\d.]+$")


def _impact(ents, limit=40):
    """Limpa as entidades para a seção Impact: tira o rótulo ``LABEL:``, remove
    números de versão soltos e deduplica."""
    out, seen = [], set()
    for e in ents:
        txt = e.split(":", 1)[1] if ":" in e else e
        txt = txt.strip()
        key = txt.lower()
        if not txt or key in seen or _VERSION_ONLY.match(txt):
            continue
        seen.add(key)
        out.append(txt)
        if len(out) >= limit:
            break
    return out


def _knowledge(blob: str, limit: int = 12) -> list:
    """Frases curtas e informativas (dedup, 4..20 palavras)."""
    out, seen = [], set()
    for raw in _SENT.split(blob or ""):
        s = " ".join(raw.split()).strip(" -•\t")
        if not (4 <= len(s.split()) <= 20):
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def main(params, occ):
    doc = params
    dados = doc.get("dados") or {}
    # só título + descrição (como o legado): texto de refs/exploit-db polui o NER.
    blob = [x for x in (dados.get("titulo"), dados.get("descricao")) if x]

    ents = entities("\n".join(blob))
    doc["entities"] = ents
    doc["object"] = _impact(ents)  # Impact (entidades limpas)

    base = dados.get("descricao") or ""
    for m in ((dados.get("vector_details") or {}).get("elements") or []):
        if m.get("value_description"):
            base += " " + m["value_description"]
    doc["lista_knowledge"] = _knowledge(base)
    return doc


if __name__ == "__main__":
    run(main)
