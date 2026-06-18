"""Validação de inputs na partida da ocorrência.

O autor liga os params de uma atividade a entradas do workflow com ``"$input.X"``.
O **tipo esperado** de cada entrada vem do *schema de params do manifesto* do
script que a consome (campos ``tipo``/``obrigatorio``). Antes de criar a
ocorrência, o motor deriva esse schema do template e valida os ``inputs``;
**sobe ``InputError``** se faltar um obrigatório ou o tipo não casar — assim um
pedido malformado nunca vira ocorrência (vale para web, admin e VAI).

Sem schema conhecido (``params_for`` devolve ``None`` p/ o ``bot_ref``) a entrada
não é validada — não dá para checar o que não se conhece.
"""

from __future__ import annotations

_PYTYPES = {
    "str": str, "int": int, "float": (int, float),
    "bool": bool, "list": list, "dict": dict,
}


class InputError(Exception):
    """Input de início de ocorrência inválido (faltando ou com tipo errado)."""


def _iter_activities(node):
    """Emite os nós ``action``/``decision`` (que carregam ``params`` + ``bot_ref``)."""
    if not isinstance(node, dict):
        return
    if node.get("tipo") in ("action", "decision"):
        yield node
    for f in node.get("filhos", []) or []:
        yield from _iter_activities(f)
    if "corpo" in node:
        yield from _iter_activities(node["corpo"])
    for sub in (node.get("rotas") or {}).values():
        yield from _iter_activities(sub)


def required_inputs(template: dict, params_for) -> dict:
    """Deriva ``{nome_input: {"tipo", "obrigatorio"}}`` varrendo o template: para
    cada param ligado a ``"$input.<nome>"``, usa o schema do script consumidor."""
    raiz = template.get("raiz", template)
    schema: dict = {}
    for node in _iter_activities(raiz):
        params = node.get("params")
        if not isinstance(params, dict):
            continue
        pspec = params_for(node.get("bot_ref") or {}) or {}
        for field, value in params.items():
            if isinstance(value, str) and value.startswith("$input."):
                name = value[len("$input."):].split(".")[0]
                spec = pspec.get(field) or {}
                cur = schema.get(name, {})
                schema[name] = {
                    "tipo": cur.get("tipo") or spec.get("tipo"),
                    "obrigatorio": bool(cur.get("obrigatorio")) or bool(spec.get("obrigatorio")),
                    # extras só para a UI montar o form (default/descrição); a
                    # validação só olha tipo/obrigatorio.
                    "default": cur.get("default", spec.get("default")),
                    "descricao": cur.get("descricao") or spec.get("descricao"),
                }
    return schema


def validate_inputs(template: dict, inputs: dict, params_for) -> None:
    """Sobe ``InputError`` se ``inputs`` não casa com o schema do template."""
    inputs = inputs or {}
    for name, spec in required_inputs(template, params_for).items():
        if inputs.get(name) is None:
            if spec.get("obrigatorio"):
                tail = f" (tipo {spec['tipo']})" if spec.get("tipo") else ""
                raise InputError(f"input obrigatório ausente: '{name}'{tail}")
            continue
        tipo = spec.get("tipo")
        py = _PYTYPES.get(tipo)
        if py is None:
            continue
        val = inputs[name]
        # bool é subtipo de int em Python — não deixe um bool passar por int.
        if tipo == "int" and isinstance(val, bool):
            raise InputError(f"input '{name}': esperado int, veio bool")
        if not isinstance(val, py):
            raise InputError(
                f"input '{name}': esperado {tipo}, veio {type(val).__name__}")
