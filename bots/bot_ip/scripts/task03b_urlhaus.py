"""02_03_urlhaus — abuse.ch URLhaus (distribuição de malware) para o IP. Recebe a
saída acumulada do loop (``$prev`` = ip + shodan + abuseipdb) e **acumula** o
resultado no mesmo registro, terceira fonte ao lado de exposição (Shodan) e
reputação (AbuseIPDB): malware servido a partir do IP.

API: ``POST https://urlhaus-api.abuse.ch/v1/host/`` com corpo ``host=<ip>`` e
header ``Auth-Key: <URLHAUS_API_KEY>`` (a chave vive no env do drone, nunca no
pedido — mesma decisão do dono de Shodan/AbuseIPDB). Falta de chave = erro
lógico (config). Falha de rede/HTTP é tolerada (registra ``urlhaus_erro`` e
segue, para um IP não derrubar o relatório). ``query_status`` != ``ok`` (ex.
``no_results``) vira ``urlhaus_nota``. O egress sai via ``MYASS_PROXY`` (Tor)
quando setado — ver lib/http.
"""

import os
import sys
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.http import post_form_json  # noqa: E402
from lib.io import run  # noqa: E402

API = "https://urlhaus-api.abuse.ch/v1/host/"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def main(params, occ):
    rec = dict(params) if isinstance(params, dict) else {}   # acumula shodan + abuseipdb
    ip = rec.get("ip") or rec.get("item")
    rec["ip"] = ip
    key = os.environ.get("URLHAUS_API_KEY")
    if not key:
        raise RuntimeError("URLHAUS_API_KEY ausente no env do drone")
    try:
        js = post_form_json(API, {"host": ip},
                            headers={"Auth-Key": key, "Accept": "application/json"})
        status = (js or {}).get("query_status")
        if status == "ok":
            urls = js.get("urls") or []
            bl = js.get("blacklists") or {}
            rec["urlhaus"] = {
                "url_count": _int(js.get("url_count")),
                "urls_online": sum(1 for u in urls if u.get("url_status") == "online"),
                "firstseen": js.get("firstseen"),
                "threats": sorted({u.get("threat") for u in urls if u.get("threat")}),
                "tags": sorted({t for u in urls for t in (u.get("tags") or [])}),
                "spamhaus_dbl": bl.get("spamhaus_dbl"),
                "surbl": bl.get("surbl"),
                "reference": js.get("urlhaus_reference"),
                "amostras_urls": [u.get("url") for u in urls[:10] if u.get("url")],
            }
        elif status == "no_results":
            rec["urlhaus_nota"] = "sem registros de malware no URLhaus"
        else:
            rec["urlhaus_nota"] = f"URLhaus query_status={status}"
    except urllib.error.HTTPError as e:
        rec["urlhaus_erro"] = f"URLhaus HTTP {e.code}"
    except urllib.error.URLError as e:
        rec["urlhaus_erro"] = f"URLhaus inacessível: {e.reason}"
    return rec


if __name__ == "__main__":
    run(main)
