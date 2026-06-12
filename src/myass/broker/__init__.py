"""Broker — a fila/messageria multinível do myass (parte da Rainha).

Dois níveis (ver *Broker* em ``CLAUDE.md``):

- **Nível 1** — um nó por *classe de recurso*, classificada sobre MEM x CPU
  (``classes.py``). A tabela não é ordenada por severidade; o casamento
  hardware-do-block x classe é a única regra de elegibilidade.
- **Nível 2** — um *ring buffer* por nó (``ring.py``), com ponteiros W (escrita)
  e R (leitura); a janela de leitura ``W - R`` são as atividades disponíveis.

A durabilidade vive no MongoDB (``store.py``); o ring é apenas uma janela em
memória sobre o backlog persistido. Janela vazia retorna ``[]`` imediatamente
(não-bloqueante) e dispara, em paralelo, uma carga que reabastece o nó a partir
do Mongo (``broker.py``).
"""

from .broker import Broker
from .classes import ClassTable, HwClass
from .ring import RingBuffer
from .store import BacklogStore

__all__ = ["Broker", "ClassTable", "HwClass", "RingBuffer", "BacklogStore"]
