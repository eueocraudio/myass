"""Motor de workflow Nassi — a fatia de encadeamento do Scheduler.

Executa o template (árvore block/action/decision/loop com catch): cria uma
ocorrência, dirige o cursor pelo "tick" de cada RESULT, faz fan-out/join nos
loops e borbulha erros pela cadeia de catch. Pluga-se nos callbacks do
``Scheduler`` (``on_complete``/``on_logical_failure``).
"""

from . import template
from .engine import (
    STATUS_DONE, STATUS_FAILED, STATUS_RUNNING, OccurrenceStore, WorkflowEngine,
)

__all__ = [
    "WorkflowEngine", "OccurrenceStore", "template",
    "STATUS_RUNNING", "STATUS_DONE", "STATUS_FAILED",
]
