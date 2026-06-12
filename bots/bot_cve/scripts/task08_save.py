"""Task08 — finaliza o doc do CVE (fim da trilha do filho).

No modelo real do myass o doc seria persistido no MongoDB pelo **canal de dados**
(``DATA_PUT``/GridFS, ``data_ref``) — o script de um drone não fala direto com o
Mongo do núcleo. Aqui o doc final é o **retorno do filho**: é ele que entra no
array do ``join`` e que o núcleo persiste. Marcamos os metadados de persistência.
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.io import run  # noqa: E402


def main(params, occ):
    doc = params
    doc["_id"] = doc["cve"].lower()
    doc["salvo_em"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    doc["salvo"] = True
    return doc


if __name__ == "__main__":
    run(main)
