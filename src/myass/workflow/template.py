"""Template de workflow Nassi — forma canônica, hash e navegação por path.

O template é a **árvore imutável** de atividades (ver *Rotinas & encadeamento* e
*Serialização do template* em CLAUDE.md): nós ``block``/``action``/``decision``/
``loop``, todo escopo podendo carregar um ``catch``. ``template_hash =
BLAKE2(JSON canônico)``. Nós são endereçados por **path** (lista de chaves/índices
a partir do dict do template), o que evita copiar subárvores no estado da ocorrência.
"""

from __future__ import annotations

import hashlib
import json

ROOT_PATH = ["raiz"]


def canonical(template: dict) -> str:
    return json.dumps(template, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def template_hash(template: dict) -> str:
    return "blake2:" + hashlib.blake2b(canonical(template).encode("utf-8")).hexdigest()


def node_at(template: dict, path: list):
    """Navega o template por ``path`` (chaves de dict e índices de lista)."""
    node = template
    for key in path:
        node = node[key]
    return node
