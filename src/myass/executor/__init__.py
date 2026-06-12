"""Executor — o cérebro de um block (drone).

Esta fatia implementa o *runner local*: o contrato Executor <-> script (spawn,
workdir efêmero, input/output.json, exit codes, limpeza estrutural) e a tradução
do plano de dados (``$file`` <-> ``$data``). O laço de protocolo (HELLO/WORK_GET/
WORK_BEAT/RESULT sobre o canal sub-espacial Noise) e a gestão de projeto/venv são
fatias separadas.
"""

from . import dataplane, project, workdir
from .agent import (
    ExecutorAgent, MappingResolver, ProtocolError, Resolver, WireDataStore, WireSource,
)
from .dataplane import DataStore, MemoryDataStore, compute_ref
from .project import (
    DirSource, IntegrityError, ProjectCache, ProjectMissing, ProjectResolver,
)
from .runner import RESULT_ERRO_LOGICO, RESULT_OK, ActivityRunner, RunResult

__all__ = [
    "ActivityRunner", "RunResult", "RESULT_OK", "RESULT_ERRO_LOGICO",
    "DataStore", "MemoryDataStore", "compute_ref", "dataplane", "workdir", "project",
    "ExecutorAgent", "MappingResolver", "Resolver", "ProtocolError",
    "ProjectCache", "ProjectResolver", "DirSource", "ProjectMissing", "IntegrityError",
]
