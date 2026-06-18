"""02_01_shodan — consulta o Shodan (exposição: portas, serviços, vulns) para um IP.

A API key vive no **env do drone** (``SHODAN_API_KEY``) — nunca no pedido/ocorrência
(decisão do dono). Falta de chave = erro lógico (config). Falha de rede/404 é
tolerada (registra a nota e segue, para um IP não derrubar o relatório inteiro).
O egress sai via ``MYASS_PROXY`` (Tor) quando setado — ver lib/http.
"""

import os
import sys
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.http import get_json  # noqa: E402
from lib.io import run  # noqa: E402

API = "https://api.shodan.io/shodan/host/{ip}?key={key}"


def main(params, occ):
    ip = params.get("ip") or params.get("item")        # item do loop
    rec = {"ip": ip, "shodan": None}
    key = os.environ.get("SHODAN_API_KEY")
    if not key:
        raise RuntimeError("SHODAN_API_KEY ausente no env do drone")
    try:
        js = get_json(API.format(ip=ip, key=key))
        rec["shodan"] = {
            "org": js.get("org"), "isp": js.get("isp"), "asn": js.get("asn"),
            "country": js.get("country_name"), "city": js.get("city"),
            "os": js.get("os"), "hostnames": js.get("hostnames") or [],
            "ports": sorted(js.get("ports") or []), "tags": js.get("tags") or [],
            "vulns": sorted(js.get("vulns") or []), "last_update": js.get("last_update"),
        }
    except urllib.error.HTTPError as e:
        rec["shodan_nota"] = ("sem informações no Shodan" if e.code == 404
                              else f"Shodan HTTP {e.code}")
    except urllib.error.URLError as e:
        rec["shodan_nota"] = f"Shodan inacessível: {e.reason}"
    return rec


if __name__ == "__main__":
    run(main)
