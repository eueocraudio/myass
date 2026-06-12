"""Core — a montagem do núcleo: liga a borda (GET/SET) ao motor de workflow.

Fecha o caminho do usuário final (estruturado, sem linguagem natural):

    cliente → Locutus → GET decifra → on_request → engine.start (cria ocorrência)
    ... drones executam (Scheduler) ...
    ocorrência conclui → engine.on_finished → SET cifra o resultado → Locutus → cliente

O `Gateway` (borda) decifra dentro do núcleo e chama `on_request`; o `Core`
interpreta o pedido estruturado, valida o workflow no registro de publicação e
dispara a ocorrência, guardando a quem responder. Quando o motor sinaliza o fim
da ocorrência, o `Core` devolve o resultado pelo SET. (Pedido em linguagem
natural via drone VAI fica como caminho opcional/futuro.)
"""

from __future__ import annotations

import threading

from .. import errlog


class ReplyStore:
    """Mapa ``occurrence_id -> (client_id, request_id)`` para saber a quem
    devolver o resultado quando a ocorrência terminar (persistido no Mongo)."""

    def __init__(self, db):
        self.col = db["occ_replies"]

    def put(self, occ_id: str, client_id: str, request_id: str,
            kind: str = "final") -> None:
        self.col.replace_one(
            {"_id": occ_id},
            {"_id": occ_id, "client_id": client_id, "request_id": request_id,
             "kind": kind},
            upsert=True)

    def get(self, occ_id: str) -> dict | None:
        return self.col.find_one({"_id": occ_id})

    def delete(self, occ_id: str) -> None:
        self.col.delete_one({"_id": occ_id})


class Core:
    def __init__(self, gateway, engine, registry, replies: ReplyStore,
                 interpreter_workflow_hash: str | None = None):
        self.gateway = gateway
        self.engine = engine
        self.registry = registry
        self.replies = replies
        # workflow de interpretação (1 atividade VAI) — habilita pedidos em
        # linguagem natural (action "interpret"). None = só pedidos estruturados.
        self.interpreter_workflow_hash = interpreter_workflow_hash
        gateway.on_request = self._on_request
        engine.on_finished = self._on_finished

    # ---- entrada: pedido do cliente (via GET) -------------------------
    def _on_request(self, client_id: str, request_id: str, msg: dict) -> None:
        action = msg.get("action")
        if action == "start_occurrence":
            self._start_workflow(client_id, request_id, msg.get("workflow_hash", ""),
                                 msg.get("inputs", {}))
        elif action == "interpret":
            self._start_interpret(client_id, request_id, msg.get("texto", ""))
        else:
            self.gateway.send_response(client_id, request_id,
                                       {"erro": f"ação desconhecida: {action}"})

    def _start_workflow(self, client_id, request_id, workflow_hash, inputs,
                        kind="final"):
        template = self.registry.get_workflow(workflow_hash)
        if template is None:
            self.gateway.send_response(client_id, request_id,
                                       {"erro": "workflow não aprovado"})
            return None
        occ_id = self.engine.start(template, inputs)
        self.replies.put(occ_id, client_id, request_id, kind=kind)
        occ = self.engine.store.get(occ_id)  # write-once: só respondemos no fim
        if occ and occ["status"] != "running":
            self._on_finished(occ)
        return occ_id

    def _start_interpret(self, client_id, request_id, texto):
        """Pedido em linguagem natural: roda o BOT VAI (workflow interpretador) que
        devolve o PLANO (qual workflow + inputs). A saída do VAI é **sugestão** —
        a Rainha só agenda workflow aprovado (validado em `_on_finished`)."""
        if self.interpreter_workflow_hash is None:
            self.gateway.send_response(client_id, request_id,
                                       {"erro": "interpretação não habilitada"})
            return
        template = self.registry.get_workflow(self.interpreter_workflow_hash)
        if template is None:
            self.gateway.send_response(client_id, request_id,
                                       {"erro": "interpretador não aprovado"})
            return
        inputs = {"texto": texto,
                  "catalogo": self.registry.catalog().get("workflows", [])}
        occ_id = self.engine.start(template, inputs)
        self.replies.put(occ_id, client_id, request_id, kind="interpret")

    # ---- saída: ocorrência concluída (→ SET) --------------------------
    def _on_finished(self, occ: dict) -> None:
        m = self.replies.get(occ["_id"])
        if not m:
            return
        if m.get("kind") == "interpret":
            self._on_interpreted(occ, m)
        else:
            self._respond(occ)

    def _on_interpreted(self, occ, m):
        """O VAI terminou: valida o plano e dispara o workflow real (ou devolve a
        sugestão/esclarecimento). Hallucination/prompt-injection no texto não
        executa hash não aprovado — `_start_workflow` rejeita o que não está no
        registro."""
        self.replies.delete(occ["_id"])
        plano = occ.get("result") or {}
        wfh = plano.get("workflow_hash") if isinstance(plano, dict) else None
        if wfh and self.registry.get_workflow(wfh) is not None:
            # encadeia: a ocorrência real responde o mesmo cliente/request
            self._start_workflow(m["client_id"], m["request_id"], wfh,
                                 plano.get("inputs", {}), kind="final")
        else:
            # plano inválido ou pedido de esclarecimento → devolve ao cliente
            self.gateway.send_response(m["client_id"], m["request_id"],
                                       {"interpretacao": plano})

    def _respond(self, occ: dict) -> None:
        m = self.replies.get(occ["_id"])
        if not m:
            return
        body = {"occurrence_id": occ["_id"], "status": occ["status"],
                "result": occ.get("result"), "fail": occ.get("fail")}
        try:
            self.gateway.send_response(m["client_id"], m["request_id"], body)
        except Exception as e:  # noqa: BLE001
            errlog.record(f"core: falha ao responder occ {occ['_id']}: {e!r}")
            return
        self.replies.delete(occ["_id"])

    # ---- laço de polling da borda -------------------------------------
    def poll_once(self) -> int:
        return self.gateway.poll()

    def run(self, stop_event: threading.Event, interval: float = 2.0) -> None:
        """Faz polling do Locutus em laço até ``stop_event``."""
        while not stop_event.is_set():
            try:
                self.poll_once()
            except Exception as e:  # noqa: BLE001
                errlog.record(f"core: erro no polling da borda: {e!r}")
            stop_event.wait(interval)
