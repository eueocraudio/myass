import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from myass.workflow.inputs import InputError, required_inputs, validate_inputs

# manifesto-like: bot_ref -> schema de params do script consumidor
_SPLIT = {"project_hash": "blake2:p", "script_hash": "blake2:split"}
_PARAMS = {"blake2:split": {"texto": {"tipo": "str", "obrigatorio": True}}}


def params_for(bot_ref):
    return _PARAMS.get((bot_ref or {}).get("script_hash"))


# template estilo bot_cve: Task01 consome $input.texto (str, obrigatório)
TEMPLATE = {
    "tipo": "workflow",
    "raiz": {"tipo": "block", "filhos": [
        {"tipo": "action", "nome": "Task01", "bot_ref": _SPLIT,
         "params": {"texto": "$input.texto"}},
    ]},
}


class InputsTest(unittest.TestCase):
    def test_required_inputs_derived_from_manifest(self):
        schema = required_inputs(TEMPLATE, params_for)
        self.assertEqual(set(schema), {"texto"})
        self.assertEqual(schema["texto"]["tipo"], "str")
        self.assertTrue(schema["texto"]["obrigatorio"])

    def test_missing_required_raises(self):
        with self.assertRaises(InputError):
            validate_inputs(TEMPLATE, {}, params_for)

    def test_wrong_type_raises(self):
        with self.assertRaises(InputError):
            validate_inputs(TEMPLATE, {"texto": 123}, params_for)

    def test_valid_passes(self):
        validate_inputs(TEMPLATE, {"texto": "CVE-2024-0001"}, params_for)  # não levanta

    def test_bool_not_accepted_as_int(self):
        tmpl = {"raiz": {"tipo": "block", "filhos": [
            {"tipo": "action", "bot_ref": {"script_hash": "blake2:n"},
             "params": {"n": "$input.n"}}]}}
        pf = lambda r: {"n": {"tipo": "int", "obrigatorio": True}}
        with self.assertRaises(InputError):
            validate_inputs(tmpl, {"n": True}, pf)
        validate_inputs(tmpl, {"n": 7}, pf)  # int ok

    def test_unknown_schema_is_noop(self):
        # sem schema conhecido (params_for -> None), não valida nada
        validate_inputs(TEMPLATE, {}, lambda r: None)

    def test_optional_missing_ok(self):
        tmpl = {"raiz": {"tipo": "block", "filhos": [
            {"tipo": "action", "bot_ref": {"script_hash": "blake2:o"},
             "params": {"x": "$input.x"}}]}}
        pf = lambda r: {"x": {"tipo": "str", "obrigatorio": False}}
        validate_inputs(tmpl, {}, pf)  # opcional ausente: ok


if __name__ == "__main__":
    unittest.main()
