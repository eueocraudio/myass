"""Canal de erros — um anel circular de ponteiro único que se sobrescreve.

Um log de erros leve e de tamanho fixo, sempre em memória. Diferente do ring
buffer do broker (que tem W **e** R e cujos itens são *consumidos*), aqui há um
**único ponteiro** (só escrita): nada é lido/consumido, as posições mais antigas
são simplesmente **sobrescritas** quando o anel dá a volta. É um "últimos N
erros" barato — nunca cresce, nunca precisa de limpeza.

- ``record(item)`` grava na posição do ponteiro e o avança (``% capacity``).
- ``Print()`` despeja de **trás para frente** (o erro mais recente primeiro), que
  é como se quer ler um log de erros: o que acabou de acontecer no topo.

Capacidade default: 1000. Thread-safe (erros chegam de várias threads — loaders
do broker, laços de protocolo, etc.). Há uma instância global pronta (o "canal
de erros" do processo) com helpers de módulo ``record`` / ``dump`` / ``Print``.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

DEFAULT_CAPACITY = 1000


class ErrorRing:
    def __init__(self, capacity: int = DEFAULT_CAPACITY, with_timestamp: bool = True):
        if capacity <= 0:
            raise ValueError("capacity deve ser positiva")
        self.capacity = capacity
        self.with_timestamp = with_timestamp
        self._buf: list[Any] = [None] * capacity
        self._w = 0  # total já registrado (monotônico; passa de capacity)
        self._lock = threading.Lock()

    def record(self, item: Any) -> None:
        """Grava um erro e avança o ponteiro, sobrescrevendo o mais antigo se cheio."""
        if self.with_timestamp:
            item = (time.time(), item)
        with self._lock:
            self._buf[self._w % self.capacity] = item
            self._w += 1

    def dump(self, n: int | None = None) -> list[Any]:
        """Os erros do mais recente ao mais antigo (de trás para frente), no
        máximo ``n`` (ou todos os disponíveis)."""
        with self._lock:
            count = min(self._w, self.capacity)
            if n is not None:
                count = min(count, max(0, n))
            return [self._buf[(self._w - i) % self.capacity] for i in range(1, count + 1)]

    def Print(self, n: int | None = None, file=sys.stderr) -> None:
        """Imprime os erros de trás para frente (recente primeiro)."""
        for item in self.dump(n):
            if self.with_timestamp and isinstance(item, tuple) and len(item) == 2:
                ts, msg = item
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}] {msg}",
                      file=file)
            else:
                print(item, file=file)

    def clear(self) -> None:
        with self._lock:
            self._buf = [None] * self.capacity
            self._w = 0

    def __len__(self) -> int:
        """Quantos erros estão disponíveis agora (até ``capacity``)."""
        with self._lock:
            return min(self._w, self.capacity)

    @property
    def total(self) -> int:
        """Total já registrado desde sempre, inclusive os já sobrescritos."""
        with self._lock:
            return self._w


# O canal de erros do processo + helpers de conveniência.
errors = ErrorRing()


def record(item: Any) -> None:
    errors.record(item)


def dump(n: int | None = None) -> list[Any]:
    return errors.dump(n)


def Print(n: int | None = None, file=sys.stderr) -> None:
    errors.Print(n, file=file)
