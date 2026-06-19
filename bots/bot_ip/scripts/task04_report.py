"""03_report — consolida os retornos do loop e gera o relatório PDF (inline b64).

Recebe ``{"ips": <join do loop>}`` = lista de registros ``{ip, shodan, abuseipdb,...}``.
Ordena por reputação (abuse score do AbuseIPDB), depois por exposição (vulns,
portas do Shodan). Monta capa + tabela-resumo + metodologia e **1 IP por página**
(reputação AbuseIPDB + exposição Shodan + vulns). Entrega ``{"pdf": {"$b64",
"nome"}, "total"}`` — o passo de publish sobe o arquivo.
"""

import base64
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.io import run  # noqa: E402
from lib.minipdf import Pdf  # noqa: E402


def _abuse(d):
    v = (d.get("abuseipdb") or {}).get("abuse_score")
    return v if isinstance(v, (int, float)) else -1


def _exposure(d):
    sh = d.get("shodan") or {}
    return (len(sh.get("vulns") or []), len(sh.get("ports") or []))


def _malware(d):
    c = (d.get("urlhaus") or {}).get("url_count")
    return c if isinstance(c, (int, float)) else 0


def _ordena(d):
    # reputação (abuse) e malware servido (URLhaus) são os sinais fortes; em
    # empate, a exposição do Shodan (vulns, portas).
    return (_abuse(d), _malware(d)) + _exposure(d)


def _risco(score):
    if not isinstance(score, (int, float)) or score < 0:
        return "?"
    return ("Baixo" if score < 25 else "Médio" if score < 50
            else "Alto" if score < 75 else "Crítico")


def main(params, occ):
    rel = sorted(params.get("ips") or [], key=_ordena, reverse=True)
    gerado = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    pdf = Pdf(title="IP intelligence report",
              footer="myass — relatório de IPs (Shodan + AbuseIPDB + URLhaus)")
    pdf.title("IP intelligence report")
    pdf.small(f"Gerado em {gerado}   ·   Total de IPs: {len(rel)}")

    pdf.heading("Summary")
    rows = []
    for d in rel:
        sh = d.get("shodan") or {}
        ab = d.get("abuseipdb") or {}
        uh = d.get("urlhaus") or {}
        rows.append([d.get("ip", "?"), str(ab.get("abuse_score", "?")), _risco(_abuse(d)),
                     (sh.get("org") or ab.get("isp") or "?")[:26],
                     str(len(sh.get("ports") or [])), str(len(sh.get("vulns") or [])),
                     str(uh.get("url_count")) if uh else "—"])
    if rows:
        pdf.table(["IP", "Abuse", "Risco", "Org/ISP", "Portas", "Vulns", "Malware"], rows,
                  [0.22, 0.11, 0.11, 0.25, 0.10, 0.10, 0.11])
    else:
        pdf.paragraph("Nenhum IP de WAN encontrado no texto.")

    pdf.heading("Methodology")
    pdf.paragraph(
        "Cada IP público extraído do texto foi consultado em três fontes: o "
        "Shodan (exposição na internet — portas, serviços, hostnames e vulns "
        "conhecidas), o AbuseIPDB (reputação — abuse confidence score, total de "
        "reports e tipo de uso) e o URLhaus da abuse.ch (distribuição de malware "
        "— URLs maliciosas servidas a partir do IP, famílias e tags). IPs "
        "privados, reservados e de loopback são descartados na extração. A "
        "ordenação prioriza os IPs com maior abuse score e mais malware servido "
        "(URLhaus) e, em empate, os mais expostos.")

    for d in rel:
        pdf.page_break()
        ip = d.get("ip", "?")
        ab = d.get("abuseipdb") or {}
        sh = d.get("shodan") or {}
        uh = d.get("urlhaus") or {}
        sc = ab.get("abuse_score")
        pdf.banner(f"{ip}" + (f"   ·   abuse {sc} ({_risco(sc)})" if sc is not None else ""))

        pdf.heading("Reputation — AbuseIPDB", 12)
        if ab:
            pdf.table(["Campo", "Valor"], [
                ["Abuse confidence", str(ab.get("abuse_score", "?")) + " %"],
                ["Total reports", f"{ab.get('total_reports')} (de {ab.get('distinct_users')} fontes)"],
                ["Tipo de uso", str(ab.get("usage_type") or "?")],
                ["ISP / Domínio", f"{ab.get('isp') or '?'} / {ab.get('domain') or '?'}"],
                ["País", str(ab.get("country_code") or "?")],
                ["Tor / Whitelisted", f"{ab.get('is_tor')} / {ab.get('is_whitelisted')}"],
                ["Último report", str(ab.get("last_reported_at") or "—")],
            ], [0.32, 0.68])
        else:
            pdf.small(d.get("abuseipdb_erro") or "sem dados do AbuseIPDB")
        if d.get("abuseipdb_erro"):
            pdf.small("AbuseIPDB: " + str(d["abuseipdb_erro"]))

        pdf.heading("Exposure — Shodan", 12)
        if sh:
            pdf.table(["Campo", "Valor"], [
                ["Org / ISP", f"{sh.get('org') or '?'} / {sh.get('isp') or '?'}"],
                ["ASN / País", f"{sh.get('asn') or '?'} / {sh.get('country') or '?'}"],
                ["OS", str(sh.get("os") or "?")],
                ["Portas", ", ".join(str(p) for p in (sh.get("ports") or [])) or "—"],
                ["Hostnames", ", ".join(sh.get("hostnames") or []) or "—"],
                ["Tags", ", ".join(sh.get("tags") or []) or "—"],
                ["Atualizado", str(sh.get("last_update") or "?")],
            ], [0.30, 0.70])
            vulns = sh.get("vulns") or []
            if vulns:
                pdf.heading("Vulnerabilities (Shodan)", 12)
                for v in vulns[:60]:
                    pdf.bullet(str(v))
        else:
            pdf.small(d.get("shodan_nota") or "sem dados do Shodan")

        pdf.heading("Malware distribution — URLhaus", 12)
        if uh:
            pdf.table(["Campo", "Valor"], [
                ["URLs maliciosas", f"{uh.get('url_count')} ({uh.get('urls_online')} online)"],
                ["Primeira vez visto", str(uh.get("firstseen") or "?")],
                ["Ameaças", ", ".join(uh.get("threats") or []) or "—"],
                ["Tags / famílias", ", ".join(uh.get("tags") or []) or "—"],
                ["Spamhaus DBL / SURBL",
                 f"{uh.get('spamhaus_dbl') or '?'} / {uh.get('surbl') or '?'}"],
            ], [0.32, 0.68])
            amostras = uh.get("amostras_urls") or []
            if amostras:
                pdf.heading("Sample malware URLs (URLhaus)", 12)
                for u in amostras:
                    pdf.bullet(str(u))
        else:
            pdf.small(d.get("urlhaus_erro") or d.get("urlhaus_nota") or "sem dados do URLhaus")

    b64 = base64.b64encode(pdf.render()).decode("ascii")
    return {"pdf": {"$b64": b64, "nome": "relatorio_ips.pdf"}, "total": len(rel),
            "gerado_em": gerado}


if __name__ == "__main__":
    run(main)
