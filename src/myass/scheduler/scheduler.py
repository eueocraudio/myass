"""O Scheduler (parte da Rainha): despacho de atividades e a máquina de estados
com lease/regeneração.

O Scheduler nunca *adivinha* se uma atividade "demorou" ou "falhou" — observa
dois sinais e um relógio (ver *Máquina de estados da atividade* em ``CLAUDE.md``):

- ``WORK_BEAT`` chegando = drone vivo, filho rodando (lento != morto);
- ``RESULT`` chegando = desfecho real;
- ``lease_expira_em`` (renovado a cada beat) = o relógio. Beat parou -> lease
  vence -> morte de *infra* declarada sem prova -> regeneração.

Esta camada cuida do *lado dos drones* (despacho/lease). O avanço do cursor do
workflow (o "tick") e a cadeia de catch são plugados via os callbacks
``on_complete`` / ``on_logical_failure`` — o motor de workflow (outra fatia) os
fornece. Sem eles, o desfecho fica registrado na auditoria.

Identidade vem sempre do handshake (``block_hash``), nunca auto-reportada; aqui
ela é passada às operações pelo chamador (o laço de protocolo a obtém do Noise).
"""

from __future__ import annotations

import time
from typing import Callable

from .. import errlog
from ..broker.broker import Broker
from . import states
from .store import LeaseStore

DEFAULT_LEASE_S = 120
DEFAULT_MAX_TENTATIVAS = 3


class Scheduler:
    def __init__(
        self,
        broker: Broker,
        store: LeaseStore,
        default_lease_s: int = DEFAULT_LEASE_S,
        max_tentativas: int = DEFAULT_MAX_TENTATIVAS,
        poll_interval_s: int = 5,
        on_complete: Callable[[dict, dict], None] | None = None,
        on_logical_failure: Callable[[dict, str, dict], None] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.broker = broker
        self.store = store
        self.default_lease_s = default_lease_s
        self.max_tentativas = max_tentativas
        self.poll_interval_s = poll_interval_s
        # Ganchos do encadeamento (motor de workflow). Recebem o lease doc.
        self.on_complete = on_complete
        self.on_logical_failure = on_logical_failure
        # Relógio em epoch (persistível/comparável entre réplicas); injetável p/ teste.
        self.clock = clock

    # ---- abertura de sessão (HELLO) ------------------------------------
    def hello(self, block_hash: str, profile: dict, capabilities: list | None = None,
              project_hashes: list | None = None) -> dict:
        """Registra/atualiza o block no inventário e devolve a config da sessão
        (``HELLO_OK``)."""
        self.store.upsert_inventory(
            block_hash, profile, capabilities or [], project_hashes or [], self.clock()
        )
        return {
            "poll_interval_s": self.poll_interval_s,
            "lease_s": self.default_lease_s,
        }

    # ---- pull de trabalho (WORK_GET) -----------------------------------
    def request_work(self, block_hash: str, slots: int) -> list[dict]:
        """Entrega até ``slots`` ordens de atividade para o block. ``[]`` = NO_WORK.

        O perfil de hardware vem do inventário (HELLO prévio). Cada entrega cria
        ou atualiza o lease em ``EXECUTANDO`` com este block como portador.
        """
        inv = self.store.get_inventory(block_hash)
        if inv is None:
            raise ValueError(f"block desconhecido (sem HELLO): {block_hash}")
        if slots <= 0:
            return []

        acts = self.broker.dequeue(inv["profile"], max_n=slots)
        now = self.clock()
        orders: list[dict] = []
        for act in acts:
            aid = act["atividade_id"]
            lease = self.store.get_lease(aid)

            # RESULT tardio já resolveu esta atividade (ela voltou à fila por uma
            # regeneração, mas um portador concluiu nesse meio-tempo): descarta a
            # entrada reciclada em vez de re-executar.
            if lease is not None and lease["state"] in states.TERMINAIS:
                self.broker.store.mark_taken(aid)
                continue

            tentativa = (lease["tentativa"] + 1) if lease else 1
            max_t = int(act.get("max_tentativas") or self.max_tentativas)

            # timeout_total é fixado no primeiro despacho (não renova com o lease).
            if lease is not None and lease.get("timeout_em") is not None:
                timeout_em = lease["timeout_em"]
            elif act.get("timeout_total") is not None:
                timeout_em = now + float(act["timeout_total"])
            else:
                timeout_em = None

            lease_s = self.default_lease_s
            self.store.put_lease({
                "_id": aid,
                "occurrence_id": act.get("occurrence_id"),
                "state": states.EXECUTANDO,
                "tentativa": tentativa,
                "max_tentativas": max_t,
                "lease_s": lease_s,
                "lease_expira_em": now + lease_s,
                "timeout_em": timeout_em,
                "carrier_block": block_hash,
                "bot_ref": act.get("bot_ref"),
                "params": act.get("params"),
                "result": None,
                "motivo": None,
            })
            self.store.audit_append(aid, "despacho", now, block=block_hash,
                                    tentativa=tentativa)
            orders.append({
                "atividade_id": aid,
                "occurrence_id": act.get("occurrence_id"),
                "bot_ref": act.get("bot_ref"),
                "params": act.get("params"),
                "lease_s": lease_s,
            })
        return orders

    # ---- heartbeat (WORK_BEAT) -----------------------------------------
    def beat(self, block_hash: str, atividade_id: str) -> str:
        """Renova o lease. Retorna ``BEAT_ACK`` ou ``WORK_CANCEL`` (o canal natural
        de cancelamento, sem push)."""
        now = self.clock()
        lease = self.store.get_lease(atividade_id)
        if lease is None or lease["state"] != states.EXECUTANDO:
            return states.WORK_CANCEL  # desconhecida ou já terminal/reenfileirada
        if lease["carrier_block"] != block_hash:
            return states.WORK_CANCEL  # portador antigo (perdeu o lease)
        if lease.get("timeout_em") is not None and now >= lease["timeout_em"]:
            # Script pendurado para sempre: o lease nunca pegaria isso (o beat
            # renova). timeout_total é a rede que pega — vira falha lógica.
            self._finish_logical(lease, states.MOTIVO_TIMEOUT,
                                 {"erro": "timeout_total estourou"})
            return states.WORK_CANCEL
        self.store.set_fields(atividade_id, lease_expira_em=now + lease["lease_s"])
        return states.BEAT_ACK

    # ---- resultado (RESULT) --------------------------------------------
    def result(self, block_hash: str, atividade_id: str, status: str,
               output: dict | None = None, stderr: str = "",
               duracao: float | None = None) -> str:
        """Entrega idempotente. **O primeiro RESULT vence**, mesmo de um portador
        antigo (o trabalho é idempotente por invariante). RESULT duplicado ->
        re-ACK sem reprocessar."""
        lease = self.store.get_lease(atividade_id)
        if lease is None:
            return states.RESULT_ACK  # desconhecida: ACK e segue
        if lease["state"] in states.TERMINAIS:
            return states.RESULT_ACK  # duplicado -> re-ACK, sem reprocessar

        if status == states.RESULT_OK:
            self._finish_complete(lease, output or {}, stderr, duracao)
        else:
            self._finish_logical(lease, states.MOTIVO_ERRO_LOGICO,
                                 output or {}, stderr, duracao)
        return states.RESULT_ACK

    # ---- devolução limpa (WORK_RELEASE) --------------------------------
    def release(self, block_hash: str, atividade_id: str) -> str:
        """Shutdown gracioso de um drone: reentrega imediata, sem esperar o lease
        expirar. Não conta como tentativa (é cooperativo, não falha)."""
        now = self.clock()
        lease = self.store.get_lease(atividade_id)
        if (lease is not None and lease["state"] == states.EXECUTANDO
                and lease["carrier_block"] == block_hash):
            self.store.set_fields(atividade_id, state=states.ENFILEIRADA)
            self.broker.requeue(atividade_id)
            self.store.audit_append(atividade_id, "release", now, block=block_hash)
        return states.RELEASE_ACK

    # ---- varredura periódica (regeneração) -----------------------------
    def reap(self) -> dict:
        """Varre leases vencidos e aplica a regeneração. Idempotente e seguro de
        rodar em qualquer réplica. Retorna estatísticas do ciclo."""
        now = self.clock()
        stats = {"reenfileiradas": 0, "esgotadas": 0, "timeouts": 0}
        for lease in self.store.find_expired(now):
            aid = lease["_id"]
            # Um script pendurado que também parou de bater: timeout vira falha
            # lógica (não é falha de infra, não reentrega).
            if lease.get("timeout_em") is not None and now >= lease["timeout_em"]:
                self._finish_logical(lease, states.MOTIVO_TIMEOUT,
                                     {"erro": "timeout_total estourou"})
                stats["timeouts"] += 1
                continue
            if lease["tentativa"] < lease["max_tentativas"]:
                # Falha de infra: reempilha (caminho normal, barato).
                self.store.set_fields(aid, state=states.ENFILEIRADA)
                self.broker.requeue(aid)
                self.store.audit_append(aid, "lease_vencido", now,
                                        tentativa=lease["tentativa"])
                stats["reenfileiradas"] += 1
            else:
                # Esgotada: promove a falha lógica (ponto de conversão).
                self._finish_logical(lease, states.MOTIVO_ESGOTADA,
                                     {"erro": "max_tentativas esgotadas"})
                stats["esgotadas"] += 1
        return stats

    # ---- desfechos terminais (internos) --------------------------------
    def _finish_complete(self, lease: dict, output: dict, stderr: str,
                         duracao: float | None) -> None:
        aid = lease["_id"]
        now = self.clock()
        self.store.set_fields(
            aid, state=states.CONCLUIDA,
            result={"output": output, "stderr": stderr, "duracao": duracao},
        )
        self.store.audit_append(aid, "concluida", now, duracao=duracao)
        lease = self.store.get_lease(aid)
        if self.on_complete is not None:
            self.on_complete(lease, output)

    def _finish_logical(self, lease: dict, motivo: str, payload: dict,
                        stderr: str = "", duracao: float | None = None) -> None:
        aid = lease["_id"]
        now = self.clock()
        self.store.set_fields(
            aid, state=states.FALHA_LOGICA, motivo=motivo,
            result={"output": payload, "stderr": stderr, "duracao": duracao},
        )
        self.store.audit_append(aid, "falha_logica", now, motivo=motivo)
        errlog.record(
            f"falha_logica atv={aid} occ={lease.get('occurrence_id')} "
            f"motivo={motivo}: {payload}"
        )
        lease = self.store.get_lease(aid)
        if self.on_logical_failure is not None:
            self.on_logical_failure(lease, motivo, payload)
