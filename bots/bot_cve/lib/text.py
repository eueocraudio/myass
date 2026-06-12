"""Utilidades de texto: extrair <p> de HTML e NER (spaCy com fallback regex)."""

import re

_TAG = re.compile(r"<[^>]+>")
_P = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_WS = re.compile(r"\s+")


def html_paragraphs(html, limit=20000):
    """Concatena o texto dos <p> de uma página (best-effort, stdlib)."""
    parts = []
    for m in _P.findall(html):
        txt = _WS.sub(" ", _TAG.sub("", m)).strip()
        if txt:
            parts.append(txt)
    return "\n".join(parts)[:limit]


# --- NER -------------------------------------------------------------------

_CVE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
_CWE = re.compile(r"CWE-\d+", re.IGNORECASE)
_VER = re.compile(r"\bv?\d+\.\d+(?:\.\d+)*\b")
_PROPER = re.compile(r"\b[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,2}\b")


def entities(text, limit=60):
    """Lista de entidades únicas. Usa spaCy (en_core_web_md) se disponível;
    senão, um fallback regex (CVE/CWE/versões/nomes próprios)."""
    found = []
    try:
        import spacy  # noqa: PLC0415
        nlp = _load_spacy(spacy)
        for ent in nlp(text[:100000]).ents:
            found.append(f"{ent.label_}:{ent.text}")
    except Exception:  # noqa: BLE001  (sem spaCy/modelo -> fallback)
        for rx, label in ((_CVE, "CVE"), (_CWE, "CWE"), (_VER, "VERSION"),
                           (_PROPER, "PROPER")):
            for m in rx.findall(text):
                found.append(f"{label}:{m}")
    # únicos preservando ordem
    seen, out = set(), []
    for e in found:
        if e not in seen:
            seen.add(e)
            out.append(e)
        if len(out) >= limit:
            break
    return out


_SPACY_NLP = None


def _load_spacy(spacy):
    global _SPACY_NLP
    if _SPACY_NLP is None:
        _SPACY_NLP = spacy.load("en_core_web_md")
    return _SPACY_NLP
