"""02_02_abuseipdb — AbuseIPDB (reputação de abuso) para o IP. Recebe a saída do
Shodan (``$prev``) e **acumula** o resultado no mesmo registro.

API: ``GET https://api.abuseipdb.com/api/v2/check?ipAddress=<ip>&maxAgeInDays=90``
com header ``Key: <ABUSEIPDB_API_KEY>`` (a chave vive no env do drone, nunca no
pedido). Falta de chave = erro lógico; falha de rede/HTTP é tolerada (registra
``abuseipdb_erro`` e segue).
"""

import os
import sys
import urllib.error
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.http import get_json  # noqa: E402
from lib.io import run  # noqa: E402

API = "https://api.abuseipdb.com/api/v2/check"


def main(params, occ):
    rec = dict(params) if isinstance(params, dict) else {}   # acumula o $prev (Shodan)
    ip = rec.get("ip") or rec.get("item")
    rec["ip"] = ip
    key = os.environ.get("ABUSEIPDB_API_KEY")
    if not key:
        raise RuntimeError("ABUSEIPDB_API_KEY ausente no env do drone")
    url = API + "?" + urllib.parse.urlencode({"ipAddress": ip, "maxAgeInDays": 90})
    try:
        js = get_json(url, headers={"Key": key, "Accept": "application/json"})
        d = (js or {}).get("data") or {}
        rec["abuseipdb"] = {
            "abuse_score": d.get("abuseConfidenceScore"),
            "total_reports": d.get("totalReports"),
            "distinct_users": d.get("numDistinctUsers"),
            "country_code": d.get("countryCode"),
            "usage_type": d.get("usageType"),
            "isp": d.get("isp"), "domain": d.get("domain"),
            "is_tor": d.get("isTor"), "is_whitelisted": d.get("isWhitelisted"),
            "last_reported_at": d.get("lastReportedAt"),
        }
        errs = (js or {}).get("errors")
        if errs:
            rec["abuseipdb_erro"] = "; ".join(e.get("detail", "") for e in errs)
    except urllib.error.HTTPError as e:
        rec["abuseipdb_erro"] = f"AbuseIPDB HTTP {e.code}"
    except urllib.error.URLError as e:
        rec["abuseipdb_erro"] = f"AbuseIPDB inacessível: {e.reason}"
    return rec


if __name__ == "__main__":
    run(main)
