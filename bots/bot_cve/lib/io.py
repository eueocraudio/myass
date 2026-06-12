"""Contrato Executor <-> script (lado do script).

Cada script do BOT segue o contrato novo do myass (ver *BOT -> Execução* em
CLAUDE.md), e não o legado de /opt/myass:

    stdin: {"workdir": "..."}                      (só o apontador)
    workdir/input.json: {"occurrence_id", "params"}
    workdir/output.json: <retorno do script>       (vira o RESULT)
    exit 0 = sucesso · exit != 0 = erro lógico

Testável isolado, sem Rainha:

    echo '{"workdir": "/tmp/x"}' | python scripts/task01_split.py
"""

import json
import os
import sys
import traceback


def read_context():
    """Lê o stdin (apontador) e o input.json. Retorna (workdir, occ_id, params)."""
    cfg = json.loads(sys.stdin.readline())
    workdir = cfg["workdir"]
    with open(os.path.join(workdir, "input.json"), encoding="utf-8") as f:
        inp = json.load(f)
    return workdir, inp.get("occurrence_id"), inp.get("params", {})


def write_output(workdir, output):
    with open(os.path.join(workdir, "output.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)


def run(main):
    """Boilerplate: lê contexto, chama ``main(params, occ)``, grava a saída.

    Exceção em ``main`` -> grava {"erro", "traceback"} e sai com código 1
    (erro lógico, payload para a cadeia de catch do workflow).
    """
    workdir = None
    try:
        workdir, occ, params = read_context()
        write_output(workdir, main(params, occ))
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        if workdir:
            try:
                write_output(workdir, {"erro": str(e), "traceback": traceback.format_exc()})
            except Exception:  # noqa: BLE001
                pass
        sys.exit(1)
