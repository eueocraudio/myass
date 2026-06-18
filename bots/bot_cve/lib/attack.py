"""Mapeia CWE → técnicas MITRE ATT&CK (via CAPEC), a partir do mapa embutido
``data/cwe_attack.json`` (gerado offline do CAPEC + CWE da MITRE).

A ligação CVE↔ATT&CK não é oficial nem completa: passa por CWE→CAPEC→ATT&CK e
**só cobre os CWEs que o CAPEC associa a técnicas** (muitos CWEs de aplicação —
SQLi, path traversal, deserialização — não têm técnica ATT&CK correspondente).
Onde existe, listamos; onde não, a seção simplesmente não aparece. Puro stdlib."""

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAP_PATH = os.path.join(_ROOT, "data", "cwe_attack.json")

with open(_MAP_PATH, encoding="utf-8") as _f:
    _MAP = json.load(_f)


def techniques_for(cwe_ids) -> list:
    """Técnicas ATT&CK (dedup, ordenadas) para uma lista de ids de CWE."""
    seen = {}
    for c in cwe_ids or []:
        for t in _MAP.get(str(c), []):
            seen.setdefault(t["id"], t.get("name", ""))
    return [{"id": k, "name": v} for k, v in sorted(seen.items())]


def url(tid: str) -> str:
    """Link da técnica no attack.mitre.org (trata sub-técnica ``T1027.006``)."""
    base, _, sub = tid.partition(".")
    if sub:
        return f"https://attack.mitre.org/techniques/{base}/{sub}/"
    return f"https://attack.mitre.org/techniques/{base}/"
