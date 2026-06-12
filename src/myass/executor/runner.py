"""O contrato Executor <-> script (decisão do dono: SEM sandbox).

O script roda como processo filho comum do Executor, mesmo usuário (todas as
máquinas são do dono; sandbox só traria complexidade — o muro de segurança fica
na cadeia de publicação). Protocolo (ver *BOT → Execução* em ``CLAUDE.md``)::

    EXECUTOR                                  PROCESSO FILHO (script BOT)
      mkdtemp /tmp/myass-<occ>-XXXX (700)
      grava input.json {occurrence_id, params}
      spawn ── stdin: {"workdir": "…"} ─▶     lê  workdir/input.json
                                              grava workdir/output.json (+ artefatos)
      ◀─ exit 0 = sucesso · exit ≠ 0 = erro lógico ─
      lê output.json (vira o RESULT)           stderr → capturado p/ auditoria
      finally: rmtree(workdir)

- **Dado de verdade vai em arquivo no workdir**; o stdin carrega só o apontador.
- ``exit != 0`` = falha **lógica** (matéria das cadeias de catch). Travamento não
  é erro lógico — é assunto do lease/regeneração (camada do Scheduler).
- O filho **não recebe nada além de** ``occurrence_id`` + ``params`` (sem bot_ref,
  sem lease, sem chaves, sem contexto do canal).
- Cancelamento (``WORK_CANCEL`` por timeout): o chamador seta ``cancel_event`` →
  o filho é morto → vira erro lógico.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from subprocess import PIPE, Popen

from . import dataplane, workdir
from .dataplane import DataStore

# Status de um RESULT (espelha scheduler.states.RESULT_*).
RESULT_OK = "ok"
RESULT_ERRO_LOGICO = "erro_logico"

_POLL_INTERVAL_S = 0.02
_TERMINATE_GRACE_S = 5.0


@dataclass
class RunResult:
    status: str                      # RESULT_OK | RESULT_ERRO_LOGICO
    output: dict = field(default_factory=dict)
    stderr: str = ""
    duracao: float = 0.0
    exit_code: int | None = None
    cancelled: bool = False


@dataclass
class Prepared:
    workdir: str
    occurrence_id: str


class ActivityRunner:
    """Roda uma ordem de atividade num processo filho e devolve o RESULT.

    Três fases, para o plano de dados (que pode ir à rede) ficar **fora da thread
    do filho** — o canal só é tocado no laço principal do agente:

    - ``prepare`` — resolve as entradas (``$data`` -> arquivos, via ``DATA_GET``) e
      grava o input.json. **Usa o data_store** (rede).
    - ``execute`` — spawna o filho e coleta exit/stderr/output bruto. **Sem rede.**
    - ``collect`` — sobe as saídas (``$file`` -> ``$data``, via ``DATA_PUT``) e limpa
      o workdir. **Usa o data_store** (rede).

    ``run`` encadeia as três (conveniência para uso local/sem rede).
    """

    def __init__(self, data_store: DataStore):
        self.data_store = data_store

    def prepare(self, order: dict) -> Prepared:
        occurrence_id = order.get("occurrence_id", "")
        wd = workdir.alloc_workdir(occurrence_id)
        params = dataplane.resolve_inputs(order.get("params", {}), self.data_store, wd)
        with open(os.path.join(wd, "input.json"), "w", encoding="utf-8") as f:
            json.dump({"occurrence_id": occurrence_id, "params": params}, f)
        return Prepared(wd, occurrence_id)

    def execute(self, prepared: Prepared, interpreter: str, entrypoint: str,
                cancel_event: threading.Event | None = None) -> dict:
        """Spawna o filho (sem rede). Devolve dados crus para o ``collect``."""
        exit_code, stderr, cancelled = self._spawn(
            prepared.workdir, interpreter, entrypoint, cancel_event)
        return {"exit_code": exit_code, "stderr": stderr, "cancelled": cancelled,
                "output_raw": self._read_output(prepared.workdir)}

    def collect(self, prepared: Prepared, raw: dict, duracao: float = 0.0) -> RunResult:
        try:
            if raw["cancelled"]:
                payload = {"erro": "cancelado"}
                if raw["output_raw"]:
                    payload["output"] = raw["output_raw"]
                return RunResult(RESULT_ERRO_LOGICO, payload, raw["stderr"],
                                 duracao, raw["exit_code"], cancelled=True)
            if raw["exit_code"] == 0:
                output = dataplane.resolve_outputs(raw["output_raw"], self.data_store,
                                                   prepared.workdir)
                return RunResult(RESULT_OK, output, raw["stderr"], duracao, 0)
            return RunResult(RESULT_ERRO_LOGICO, raw["output_raw"], raw["stderr"],
                             duracao, raw["exit_code"])
        finally:
            workdir.cleanup_workdir(prepared.workdir)

    def run(self, order: dict, interpreter: str, entrypoint: str,
            cancel_event: threading.Event | None = None) -> RunResult:
        prepared = self.prepare(order)
        start = time.monotonic()
        raw = self.execute(prepared, interpreter, entrypoint, cancel_event)
        return self.collect(prepared, raw, time.monotonic() - start)

    # ---- spawn + supervisão --------------------------------------------
    def _spawn(self, wd: str, interpreter: str, entrypoint: str,
               cancel_event: threading.Event | None) -> tuple[int | None, str, bool]:
        # stdout/stderr vão para arquivos (evita deadlock de buffer de pipe; o
        # dado real não usa stdout — vai em arquivo no workdir).
        out_path = os.path.join(wd, ".stdout")
        err_path = os.path.join(wd, ".stderr")
        cancelled = False
        with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
            proc = Popen([interpreter, entrypoint], cwd=wd,
                         stdin=PIPE, stdout=out_f, stderr=err_f)
            # O filho recebe só o apontador do workdir pelo stdin.
            proc.stdin.write((json.dumps({"workdir": wd}) + "\n").encode())
            proc.stdin.flush()
            proc.stdin.close()
            while True:
                rc = proc.poll()
                if rc is not None:
                    break
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    self._kill(proc)
                    rc = proc.returncode
                    break
                time.sleep(_POLL_INTERVAL_S)
        stderr = self._read_text(err_path)
        return rc, stderr, cancelled

    @staticmethod
    def _kill(proc: Popen) -> None:
        proc.terminate()
        try:
            proc.wait(timeout=_TERMINATE_GRACE_S)
        except Exception:
            proc.kill()
            proc.wait()

    @staticmethod
    def _read_output(wd: str) -> dict:
        path = os.path.join(wd, "output.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _read_text(path: str) -> str:
        try:
            with open(path, "rb") as f:
                return f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
