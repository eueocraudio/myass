"""Scheduler (Escalonador) — parte da Rainha.

Esta fatia implementa o *lado dos drones*: o despacho de atividades e a máquina
de estados com lease/regeneração (ver *Máquina de estados da atividade* em
``CLAUDE.md``). O encadeamento de workflow (a árvore Nassi, o cursor, as cadeias
de catch) é uma fatia separada que se pluga via os callbacks do ``Scheduler``.
"""

from . import states
from .scheduler import Scheduler
from .server import SchedulerServer
from .store import LeaseStore

__all__ = ["Scheduler", "SchedulerServer", "LeaseStore", "states"]
