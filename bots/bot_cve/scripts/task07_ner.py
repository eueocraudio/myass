"""Task07 — extrai entidades (NER) dos textos do CVE com spaCy (fallback regex)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.io import run  # noqa: E402
from lib.text import entities  # noqa: E402


def main(params, occ):
    doc = params
    blob = []
    dados = doc.get("dados") or {}
    if dados.get("titulo"):
        blob.append(dados["titulo"])
    if dados.get("descricao"):
        blob.append(dados["descricao"])
    for r in doc.get("refs") or []:
        if r.get("texto"):
            blob.append(r["texto"])
    doc["entities"] = entities("\n".join(blob))
    return doc


if __name__ == "__main__":
    run(main)
