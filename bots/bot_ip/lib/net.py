"""Extração de IPs de WAN (IPv4 públicos) de um texto.

WAN = ``ipaddress.is_global``: exclui privados (10/8, 172.16/12, 192.168/16),
loopback (127/8), link-local (169.254/16), CGNAT (100.64/10), multicast,
reservados e não-especificado. Só stdlib.
"""

import ipaddress
import re

# candidatos a IPv4 (validação real é no ipaddress.ip_address abaixo)
_RX = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def wan_ips(texto: str) -> list[str]:
    """IPs de WAN no texto, sem duplicar, na ordem de aparição."""
    out, seen = [], set()
    for cand in _RX.findall(texto or ""):
        try:
            ip = ipaddress.ip_address(cand)
        except ValueError:
            continue
        if ip.version == 4 and ip.is_global and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out
