"""Task06 — baixa o texto das referências do CVE. Se uma falha, ignora e segue.

Tolerância por referência aqui dentro (try/except no laço); além disso, o
workflow registra ``catch: ignorar`` para esta atividade inteira (ver workflow.json).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.http import get_text  # noqa: E402
from lib.io import run  # noqa: E402
from lib.text import html_paragraphs  # noqa: E402

MAX_REFS = 8
MAX_TEXT = 4000


def main(params, occ):
    doc = params
    doc["refs"] = []
    for url in (doc.get("referencias") or [])[:MAX_REFS]:
        try:
            texto = html_paragraphs(get_text(url, timeout=20))
            if texto.strip():
                doc["refs"].append({"url": url, "texto": texto[:MAX_TEXT]})
        except Exception:  # noqa: BLE001  (referência falhou -> ignora e continua)
            continue
    return doc


if __name__ == "__main__":
    run(main)
