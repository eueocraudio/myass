"""O broker: junta a tabela de classes, um ring por nó e o lastro Mongo.

Fluxo de escrita (``enqueue``): classifica a atividade pela *exigência*, persiste
no Mongo (durável) e dispara uma carga para trazê-la ao ring do nó.

Fluxo de leitura (``dequeue``): para cada nó de que o block pode ler (casamento
MEM x CPU), entrega itens da janela em ordem FIFO. **Janela vazia retorna
imediatamente** (``[]``/``NO_WORK``) e, em paralelo, dispara a thread carregadora
que reabastece aquele nó a partir do Mongo. Guarda: no máximo **uma carga em voo
por nó**, e *back off* quando o Mongo daquele nó também está vazio.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any

from .. import errlog
from .classes import ClassTable
from .ring import RingBuffer
from .store import BacklogStore

DEFAULT_RING_CAPACITY = 1024
DEFAULT_LOAD_BACKOFF_S = 1.0


class Broker:
    def __init__(
        self,
        store: BacklogStore,
        classes: ClassTable | None = None,
        ring_capacity: int = DEFAULT_RING_CAPACITY,
        load_backoff_s: float = DEFAULT_LOAD_BACKOFF_S,
        async_load: bool = True,
    ):
        self.store = store
        self.classes = classes or ClassTable()
        self.load_backoff_s = load_backoff_s
        # async_load=True dispara a carga numa thread (produção). False roda a
        # carga inline no trigger — útil para testes determinísticos (a janela
        # vazia ainda devolve [] no dequeue corrente; o ring fica pronto para o
        # próximo).
        self.async_load = async_load

        # Um ring por nó da tabela.
        self.rings: dict[str, RingBuffer] = {
            cid: RingBuffer(ring_capacity) for cid in self.classes.class_ids
        }

        self._lock = threading.Lock()
        self._inflight: dict[str, bool] = {cid: False for cid in self.classes.class_ids}
        self._backoff_until: dict[str, float] = {cid: 0.0 for cid in self.classes.class_ids}
        self._loaders: list[threading.Thread] = []

        # Recuperação: o ring em RAM começa vazio, então nada pode estar 'buffered'.
        self.store.reset_buffered()
        # Aquecimento: preenche a janela de cada nó a partir do backlog durável,
        # para que o trabalho que sobreviveu a um restart fique disponível sem
        # esperar um primeiro dequeue ocioso por nó.
        for cid in self.classes.class_ids:
            self._trigger_load(cid)

    # ---- escrita -------------------------------------------------------
    def enqueue(self, activity: dict) -> str:
        """Persiste uma atividade e a encaminha ao nó da sua classe. Retorna o
        ``class_id`` escolhido. ``activity`` deve conter ``atividade_id`` e, para
        classificação, ``exigencia`` (mem_mb/cpu_cores); ausente cai no nó base.
        """
        atividade_id = activity["atividade_id"]
        class_id = self.classes.classify(activity.get("exigencia"))
        self.store.append(class_id, atividade_id, activity)
        # Chegou trabalho novo: reabre um nó que tinha entrado em back off por
        # Mongo vazio, e puxa para o ring.
        with self._lock:
            self._backoff_until[class_id] = 0.0
        self._trigger_load(class_id)
        return class_id

    def requeue(self, atividade_id: str) -> bool:
        """Reenfileira uma atividade entregue (regeneração: lease vencido,
        release limpo). Volta ao fim da fila do seu nó e reaquece o ring.
        Retorna False se a atividade não existe no backlog."""
        class_id = self.store.requeue(atividade_id)
        if class_id is None:
            return False
        with self._lock:
            self._backoff_until[class_id] = 0.0
        self._trigger_load(class_id)
        return True

    # ---- leitura -------------------------------------------------------
    def dequeue(self, profile: dict, max_n: int = 1) -> list[dict]:
        """Entrega até ``max_n`` ordens de atividade para um block com este perfil
        de hardware. Pode devolver ``[]`` (NO_WORK) — não bloqueia.

        Percorre os nós elegíveis na ordem da tabela; ao esvaziar um nó, dispara
        sua carga e segue para o próximo.
        """
        out: list[dict] = []
        for class_id in self.classes.eligible_classes(profile):
            ring = self.rings[class_id]
            while len(out) < max_n:
                doc = ring.pop()
                if doc is None:
                    break
                self.store.mark_taken(doc["_id"])
                out.append(doc["activity"])
            if ring.is_empty():
                self._trigger_load(class_id)
            if len(out) >= max_n:
                break
        return out

    # ---- carga (reabastecimento do ring) -------------------------------
    def _trigger_load(self, class_id: str) -> None:
        """Agenda uma carga para o nó, respeitando <= 1 em voo e o back off."""
        with self._lock:
            if self._inflight[class_id]:
                return
            if time.monotonic() < self._backoff_until[class_id]:
                return
            self._inflight[class_id] = True

        if self.async_load:
            t = threading.Thread(target=self._run_load, args=(class_id,), daemon=True)
            with self._lock:
                self._loaders.append(t)
            t.start()
        else:
            self._run_load(class_id)

    def _run_load(self, class_id: str) -> None:
        try:
            ring = self.rings[class_id]
            space = ring.free_space()
            if space <= 0:
                return
            docs = self.store.load_ready(class_id, space)
            if not docs:
                # Mongo também vazio para este nó: back off para não martelar.
                with self._lock:
                    self._backoff_until[class_id] = time.monotonic() + self.load_backoff_s
                return
            for doc in docs:
                ring.push(doc)  # cabe: limit = space
        except Exception:
            # A carga roda numa thread daemon; sem isto a exceção sumiria. O
            # canal de erros guarda o trace para um Print() posterior.
            errlog.record(f"broker: falha ao carregar o nó {class_id}\n{traceback.format_exc()}")
        finally:
            with self._lock:
                self._inflight[class_id] = False

    # ---- ciclo de vida / introspecção ----------------------------------
    def wait_for_loaders(self, timeout: float | None = None) -> None:
        """Aguarda as cargas em voo terminarem (útil em testes/shutdown)."""
        with self._lock:
            loaders = list(self._loaders)
        for t in loaders:
            t.join(timeout)
        with self._lock:
            self._loaders = [t for t in self._loaders if t.is_alive()]

    def window(self, class_id: str) -> int:
        """Tamanho atual da janela de leitura do nó (itens prontos no ring)."""
        return self.rings[class_id].available()
