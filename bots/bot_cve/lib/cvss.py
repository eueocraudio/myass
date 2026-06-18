"""Decodifica a string de vetor CVSS em métricas legíveis (Vector Details).

A tabela ``data/cvss.json`` (versões 3.1 e 4.0) traz, por elemento (AV, AC, …),
o nome humano e, por valor (N, L, …), o nome e a descrição. Dado um vetor
``CVSS:3.1/AV:N/AC:L/...`` devolvemos a lista de
``{metric, metric_name, value, value_name, value_description}`` + a referência
do first.org. Puro stdlib — sem dependências."""

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TABLE_PATH = os.path.join(_ROOT, "data", "cvss.json")

with open(_TABLE_PATH, encoding="utf-8") as _f:
    _TABLE = json.load(_f)


_HUMAN = {
    "AV": "vetor de ataque", "AC": "complexidade de ataque",
    "PR": "privilégios requeridos", "UI": "interação do usuário", "S": "escopo",
    "C": "impacto à confidencialidade", "I": "impacto à integridade",
    "A": "impacto à disponibilidade",
    # v4.0
    "AT": "requisitos de ataque", "VC": "impacto à confidencialidade",
    "VI": "impacto à integridade", "VA": "impacto à disponibilidade",
}


def human(decoded: dict | None) -> str:
    """Frase legível do CVSS (versão humana) a partir do vetor decodificado."""
    if not decoded:
        return ""
    byk = {m["metric"]: m["value_name"] for m in (decoded.get("elements") or [])}
    parts = [f"{label}: {byk[k]}" for k, label in _HUMAN.items() if k in byk]
    return "; ".join(parts)


def calculator_url(vector: str) -> str:
    """Link da calculadora CVSS do NVD com o vetor — a 'versão humana' interativa.
    Ref.: https://nvd.nist.gov/vuln-metrics/cvss/v3-calculator"""
    if not vector or "/" not in vector:
        return ""
    version, metrics = "3.1", vector
    if vector.upper().startswith("CVSS:"):
        head, _, metrics = vector.partition("/")
        version = head.split(":", 1)[1]
    return ("https://nvd.nist.gov/vuln-metrics/cvss/v3-calculator?vector="
            + metrics + "&version=" + version)


def options(vector: str) -> list:
    """Por métrica do vetor: nome + TODAS as opções possíveis, marcando a
    selecionada — para desenhar o 'painel' visual da calculadora (item VI)."""
    if not vector or "/" not in vector:
        return []
    version, parts = "3.1", vector
    if vector.upper().startswith("CVSS:"):
        head, _, parts = vector.partition("/")
        version = head.split(":", 1)[1]
    tbl = _TABLE.get(version)
    if tbl is None:
        return []
    chosen = {}
    for tok in parts.split("/"):
        if ":" in tok:
            m, v = tok.split(":", 1)
            chosen[m] = v
    out = []
    for m, code in chosen.items():
        el = (tbl.get("elements") or {}).get(m)
        if not el:
            continue
        vals = el.get("values") or {}
        out.append({
            "metric": m, "metric_name": el.get("name", m),
            "options": [{"code": vc, "name": vv.get("name", vc), "selected": vc == code}
                        for vc, vv in vals.items()],
        })
    return out


def decode(vector: str) -> dict | None:
    """``CVSS:3.1/AV:N/...`` → ``{version, reference, elements:[…]}`` (ou ``None``)."""
    if not vector or not isinstance(vector, str):
        return None
    parts = vector.strip().split("/")
    version = None
    if parts and parts[0].upper().startswith("CVSS:"):
        version = parts[0].split(":", 1)[1]
        parts = parts[1:]
    tbl = _TABLE.get(version)
    if tbl is None:
        return None
    elements = []
    for tok in parts:
        if ":" not in tok:
            continue
        m, v = tok.split(":", 1)
        el = (tbl.get("elements") or {}).get(m)
        if not el:
            continue
        val = (el.get("values") or {}).get(v) or {}
        elements.append({
            "metric": m,
            "metric_name": el.get("name", m),
            "value": v,
            "value_name": val.get("name", v),
            "value_description": val.get("description", ""),
        })
    return {"version": version, "reference": tbl.get("reference"), "elements": elements}
