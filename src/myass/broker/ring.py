"""Nível 2 do broker: um ring buffer (lista circular) por nó.

Dois ponteiros monotônicos: **W** (write/produtor) e **R** (read/consumidor).
A *janela de leitura* ``W - R`` é a quantidade de atividades disponíveis. O
índice físico no buffer é ``ptr % capacity``.

O ring é um cache de tamanho fixo: uma janela em memória sobre o backlog durável
no MongoDB. Ele nunca é a fonte da verdade — só guarda os itens mais antigos
ainda não consumidos que couberam. Quem o preenche é a thread carregadora do
``Broker`` (avança W); quem o esvazia é o ``dequeue`` (avança R).

Thread-safe: um único ``Lock`` protege os ponteiros e o buffer. As operações são
todas não-bloqueantes (o comportamento de "janela vazia retorna imediatamente"
vive no broker, não aqui).
"""

from __future__ import annotations

import threading
from typing import Any


class RingBuffer:
    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity deve ser positiva")
        self.capacity = capacity
        self._buf: list[Any] = [None] * capacity
        self._w = 0  # total já escrito (monotônico)
        self._r = 0  # total já lido (monotônico)
        self._lock = threading.Lock()

    def available(self) -> int:
        """Tamanho da janela de leitura ``W - R`` (itens prontos para consumir)."""
        with self._lock:
            return self._w - self._r

    def free_space(self) -> int:
        """Quantos itens ainda cabem antes de a janela encostar na capacidade."""
        with self._lock:
            return self.capacity - (self._w - self._r)

    def is_empty(self) -> bool:
        with self._lock:
            return self._w == self._r

    def is_full(self) -> bool:
        with self._lock:
            return (self._w - self._r) >= self.capacity

    def push(self, item: Any) -> bool:
        """Escreve um item e avança W. Retorna False se a janela está cheia
        (o item não é escrito — fica para o backlog do Mongo)."""
        with self._lock:
            if (self._w - self._r) >= self.capacity:
                return False
            self._buf[self._w % self.capacity] = item
            self._w += 1
            return True

    def pop(self) -> Any | None:
        """Lê o item mais antigo e avança R. Retorna ``None`` se a janela está
        vazia (não-bloqueante)."""
        with self._lock:
            if self._w == self._r:
                return None
            idx = self._r % self.capacity
            item = self._buf[idx]
            self._buf[idx] = None  # não segura referência morta
            self._r += 1
            return item

    @property
    def pointers(self) -> tuple[int, int]:
        """``(W, R)`` — útil para introspecção/depuração e testes."""
        with self._lock:
            return self._w, self._r
