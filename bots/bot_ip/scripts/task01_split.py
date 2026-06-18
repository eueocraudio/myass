"""01_quebrar_texto — extrai os IPs de WAN (IPv4 públicos) do texto de entrada.

Array sem duplicatas, na ordem de aparição. Privados/reservados/loopback/CGNAT
são descartados (ver lib/net.wan_ips).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.io import run  # noqa: E402
from lib.net import wan_ips  # noqa: E402


def main(params, occ):
    return {"ips": wan_ips(params.get("texto", "") or "")}


if __name__ == "__main__":
    run(main)
