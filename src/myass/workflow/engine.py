"""Motor de workflow Nassi — o interpretador que dirige o encadeamento.

O Scheduler dirige o encadeamento: o resultado de uma atividade é o "tick" que
avança o cursor da ocorrência e enfileira a próxima (ver *Rotinas & encadeamento*
em CLAUDE.md). Este motor é a outra fatia do Scheduler — pluga-se nos callbacks
``on_complete``/``on_logical_failure`` (que recebem o lease) e:

- **block** = sequência linear (sync); **action** = enfileira um script e espera o
  RESULT; **decision** = um script que retorna um LABEL → roteia para a subárvore
  mapeada; **loop** = foreach com **fan-out** (uma cópia do corpo por item, async
  em paralelo) e **join** (array de retornos quando todas terminam).
- **catch** segue a estrutura: um erro **borbulha de dentro para fora** por cada
  escopo (nó da ação → bloco → loop/decision → … → workflow); o primeiro com
  disposição ``ignorar`` engole (e, num loop, substitui o item no join); sem
  handler, a ocorrência falha. (Disposição ``tratar`` com script: extensão futura;
  hoje cai em ``subir``.)

Estado da ocorrência: uma **árvore de frames** (cada frame executa um bloco, com
cursor + ``prev``), persistida no MongoDB via ``OccurrenceStore``; um lock por
ocorrência serializa as conclusões concorrentes do fan-out. Atividades em voo são
mapeadas em ``inflight[atividade_id] -> frame``.
"""

from __future__ import annotations

import threading
import time
import uuid

from .. import errlog
from .inputs import InputError, validate_inputs  # noqa: F401  (reexport p/ callers)
from .template import ROOT_PATH, node_at, template_hash

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


class OccurrenceStore:
    def __init__(self, db):
        self.col = db["occurrences"]

    def get(self, occurrence_id: str) -> dict | None:
        return self.col.find_one({"_id": occurrence_id})

    def put(self, occ: dict) -> None:
        self.col.replace_one({"_id": occ["_id"]}, occ, upsert=True)

    def recent(self, limit: int = 50) -> list[dict]:
        """Resumo das ocorrências de topo (para o admin acompanhar execuções).
        Exclui as internas (``origin == "internal"``, ex.: o workflow do VAI) —
        só ocorrências iniciadas por um humano aparecem no painel."""
        out = []
        for d in self.col.find({"origin": {"$ne": "internal"}},
                               {"status": 1, "result": 1, "fail": 1, "created_at": 1,
                                "template.nome": 1, "template.versao": 1}
                               ).sort("created_at", -1).limit(limit):
            tmpl = d.get("template") or {}
            out.append({"occurrence_id": d["_id"], "status": d["status"],
                        "workflow": f"{tmpl.get('nome', '?')} v{tmpl.get('versao', '')}".strip(),
                        "result": d.get("result"), "fail": d.get("fail")})
        return out

    def recent_for(self, client_id: str, limit: int = 50) -> list[dict]:
        """Ocorrências de um cliente da web (para a lista que ele lê do Locutus),
        **por ordem de chegada DESC** (mais recente primeiro)."""
        out = []
        for d in self.col.find({"client_id": client_id},
                               {"status": 1, "template.nome": 1, "template.versao": 1,
                                "created_at": 1}).sort("created_at", -1).limit(limit):
            tmpl = d.get("template") or {}
            out.append({"occurrence_id": d["_id"], "status": d["status"],
                        "workflow": f"{tmpl.get('nome', '?')} v{tmpl.get('versao', '')}".strip()})
        return out

    def detail(self, occ_id: str) -> dict | None:
        """Detalhe curado de uma ocorrência (para a tela de informações do admin):
        status, workflow, inputs, resultado/falha, saídas por nó nomeado, o
        ``template`` (p/ desenhar o estrutograma), um ``node_status`` por nó
        (``done``/``running``/``failed``, p/ colorir o diagrama) e o
        ``template_hash`` (p/ re-executar). Não expõe os frames internos."""
        d = self.col.find_one({"_id": occ_id})
        if d is None:
            return None
        tmpl = d.get("template") or {}
        node_outputs = d.get("node_outputs") or {}
        fail = d.get("fail")
        # status por nó: feito (tem saída) < executando (em voo) < falhou.
        node_status = {name: "done" for name in node_outputs}
        for inf in (d.get("inflight") or {}).values():
            try:
                nm = node_at(tmpl, inf["nid_path"]).get("nome")
            except Exception:  # noqa: BLE001
                nm = None
            if nm and nm not in node_status:
                node_status[nm] = "running"
        if fail and fail.get("_node"):
            node_status[fail["_node"]] = "failed"
        return {
            "occurrence_id": d["_id"],
            "status": d.get("status"),
            "workflow": {"nome": tmpl.get("nome"), "versao": tmpl.get("versao")},
            "template": tmpl,
            "template_hash": template_hash(tmpl) if tmpl else None,
            "inputs": d.get("inputs"),
            "result": d.get("result"),
            "fail": fail,
            "node_outputs": node_outputs,
            "node_status": node_status,
        }


class WorkflowEngine:
    def __init__(self, broker, store: OccurrenceStore, exigencia_for=None,
                 on_finished=None, params_for=None):
        self.broker = broker
        self.store = store
        self.exigencia_for = exigencia_for or (lambda bot_ref: None)
        # schema de params do script (p/ validar os inputs na partida). Sem ele,
        # a validação é no-op (não há tipos conhecidos para checar).
        self.params_for = params_for or (lambda bot_ref: None)
        # Chamado uma vez quando uma ocorrência atinge estado terminal (done/failed)
        # — é o gancho que o núcleo usa para devolver o resultado ao cliente (SET).
        self.on_finished = on_finished
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _maybe_finish(self, occ) -> bool:
        if occ["status"] in (STATUS_DONE, STATUS_FAILED) and not occ.get("notified"):
            occ["notified"] = True
            return True
        return False

    def _lock(self, occurrence_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(occurrence_id, threading.Lock())

    # ---- início -------------------------------------------------------
    def start(self, template: dict, inputs: dict, occurrence_id: str | None = None,
              origin: str = "user", client_id: str | None = None) -> str:
        # valida os inputs contra o schema de tipos derivado do template; um
        # pedido sem os valores esperados sobe InputError e NÃO cria ocorrência.
        validate_inputs(template, inputs or {}, self.params_for)
        occ_id = occurrence_id or "occ-" + uuid.uuid4().hex[:12]
        occ = {
            # origin="user": ocorrência de topo (humana, via painel/web) — aparece
            # no painel. origin="internal": criada pelo núcleo p/ tratativa (ex.: o
            # workflow interpretador do VAI) — NÃO aparece no painel.
            # client_id: qual chave de cliente a criou (p/ a web listar as suas).
            "_id": occ_id, "template": template, "status": STATUS_RUNNING,
            "origin": origin, "client_id": client_id, "created_at": time.time(),
            "inputs": inputs, "node_outputs": {}, "result": None, "fail": None,
            "frames": {}, "inflight": {}, "next_fid": 0, "root_fid": None,
        }
        root = self._new_frame(occ, parent=None, container_path=ROOT_PATH,
                               item=None, prev=None, ret=None)
        occ["root_fid"] = root
        with self._lock(occ_id):
            self._drive(occ, root)
            finished = self._maybe_finish(occ)
            self.store.put(occ)
            if finished and self.on_finished:
                self.on_finished(occ)
        return occ_id

    # ---- callbacks do Scheduler ---------------------------------------
    def on_scheduler_complete(self, lease: dict, output: dict) -> None:
        self.activity_completed(lease["occurrence_id"], lease["_id"], output or {})

    def on_scheduler_failure(self, lease: dict, motivo: str, payload: dict) -> None:
        self.activity_failed(lease["occurrence_id"], lease["_id"], motivo, payload or {})

    def activity_completed(self, occurrence_id: str, atividade_id: str, output: dict) -> None:
        with self._lock(occurrence_id):
            occ = self.store.get(occurrence_id)
            if occ is None or occ["status"] != STATUS_RUNNING:
                return
            info = occ["inflight"].pop(atividade_id, None)
            if info is None:
                return  # desconhecida/duplicada
            self._on_completed(occ, info, output)
            finished = self._maybe_finish(occ)
            self.store.put(occ)
            if finished and self.on_finished:
                self.on_finished(occ)

    def activity_failed(self, occurrence_id: str, atividade_id: str,
                        motivo: str, payload: dict) -> None:
        with self._lock(occurrence_id):
            occ = self.store.get(occurrence_id)
            if occ is None or occ["status"] != STATUS_RUNNING:
                return
            info = occ["inflight"].pop(atividade_id, None)
            if info is None:
                return
            self._on_failed(occ, info, {"motivo": motivo, **(payload or {})})
            finished = self._maybe_finish(occ)
            self.store.put(occ)
            if finished and self.on_finished:
                self.on_finished(occ)

    # ---- frames -------------------------------------------------------
    def _new_frame(self, occ, parent, container_path, item, prev, ret) -> int:
        fid = occ["next_fid"]
        occ["next_fid"] += 1
        occ["frames"][str(fid)] = {
            "fid": fid, "parent": parent, "container_path": container_path,
            "cursor": 0, "prev": prev, "item": item, "ret": ret, "waiting": None,
        }
        return fid

    def _frame(self, occ, fid):
        return occ["frames"][str(fid)]

    # ---- avanço (o tick) ----------------------------------------------
    def _drive(self, occ, fid) -> None:
        """Avança um frame até suspender (enfileirar) ou completar."""
        while True:
            frame = self._frame(occ, fid)
            container = node_at(occ["template"], frame["container_path"])
            filhos = container.get("filhos", [])
            if frame["cursor"] >= len(filhos):
                self._return_to_parent(occ, fid, frame["prev"])
                return
            nid_path = frame["container_path"] + ["filhos", frame["cursor"]]
            node = node_at(occ["template"], nid_path)
            tipo = node["tipo"]

            if tipo == "action":
                self._dispatch(occ, fid, nid_path, node, decision=False)
                return
            if tipo == "decision":
                self._dispatch(occ, fid, nid_path, node, decision=True)
                return
            if tipo == "block":
                child = self._new_frame(occ, parent=fid, container_path=nid_path,
                                        item=frame["item"], prev=frame["prev"],
                                        ret={"parent": fid, "kind": "block"})
                frame["waiting"] = {"kind": "block"}
                self._drive(occ, child)
                return
            if tipo == "loop":
                self._start_loop(occ, fid, nid_path, node)
                return
            raise ValueError(f"tipo de nó desconhecido: {tipo}")

    def _dispatch(self, occ, fid, nid_path, node, decision: bool) -> None:
        frame = self._frame(occ, fid)
        params = self._resolve(occ, frame, node.get("params", {}))
        aid = "atv-" + uuid.uuid4().hex[:12]
        activity = {"atividade_id": aid, "occurrence_id": occ["_id"],
                    "bot_ref": node["bot_ref"], "params": params}
        ex = self.exigencia_for(node["bot_ref"])
        if ex:
            activity["exigencia"] = ex
        for opt in ("max_tentativas", "timeout_total"):
            if node.get(opt) is not None:
                activity[opt] = node[opt]
        occ["inflight"][aid] = {"fid": fid, "nid_path": nid_path, "decision": decision}
        self.broker.enqueue(activity)

    def _start_loop(self, occ, fid, nid_path, node) -> None:
        frame = self._frame(occ, fid)
        items = self._resolve(occ, frame, node["array"]) or []
        loop_name = node["nome"]
        if not items:
            occ["node_outputs"][loop_name] = {"join": []}
            frame["cursor"] += 1
            self._drive(occ, fid)
            return
        frame["waiting"] = {"kind": "loop", "loop_name": loop_name,
                            "results": [None] * len(items), "pending": len(items)}
        corpo_path = nid_path + ["corpo"]
        for i, item in enumerate(items):
            child = self._new_frame(occ, parent=fid, container_path=corpo_path,
                                    item=item, prev=None,
                                    ret={"parent": fid, "kind": "loop", "index": i})
            self._drive(occ, child)

    def _return_to_parent(self, occ, fid, value) -> None:
        frame = self._frame(occ, fid)
        ret = frame["ret"]
        if ret is None:  # frame raiz: ocorrência concluída
            occ["status"] = STATUS_DONE
            occ["result"] = value
            return
        parent = self._frame(occ, ret["parent"])
        kind = ret["kind"]
        if kind in ("block", "decision"):
            parent["prev"] = value
            parent["waiting"] = None
            parent["cursor"] += 1
            self._drive(occ, ret["parent"])
        elif kind == "loop":
            w = parent["waiting"]
            w["results"][ret["index"]] = value
            w["pending"] -= 1
            if w["pending"] == 0:
                occ["node_outputs"][w["loop_name"]] = {"join": w["results"]}
                parent["waiting"] = None
                parent["cursor"] += 1
                self._drive(occ, ret["parent"])

    # ---- conclusão de uma atividade -----------------------------------
    def _on_completed(self, occ, info, output) -> None:
        fid = info["fid"]
        frame = self._frame(occ, fid)
        node = node_at(occ["template"], info["nid_path"])
        occ["node_outputs"][node["nome"]] = output

        if info["decision"]:
            label = output.get("label") if isinstance(output, dict) else output
            rotas = node.get("rotas", {})
            if label not in rotas:
                self._on_failed(occ, info, {"erro": f"label não mapeado: {label}"})
                return
            child = self._new_frame(occ, parent=fid,
                                    container_path=info["nid_path"] + ["rotas", label],
                                    item=frame["item"], prev=frame["prev"],
                                    ret={"parent": fid, "kind": "decision"})
            frame["waiting"] = {"kind": "decision"}
            self._drive(occ, child)
        else:
            frame["prev"] = output
            frame["cursor"] += 1
            self._drive(occ, fid)

    # ---- falha lógica: borbulha pela cadeia de catch ------------------
    def _on_failed(self, occ, info, payload) -> None:
        fid = info["fid"]
        # 1) catch no próprio nó da ação que falhou
        node = node_at(occ["template"], info["nid_path"])
        payload = dict(payload or {})
        payload.setdefault("_node", node.get("nome"))  # nó de origem da falha (p/ o painel)
        if self._catch_disp(node, payload) == "ignorar":
            frame = self._frame(occ, fid)
            frame["cursor"] += 1  # engole: segue a sequência com o prev inalterado
            self._drive(occ, fid)
            return
        self._fail_frame(occ, fid, payload)

    def _fail_frame(self, occ, fid, payload) -> None:
        frame = self._frame(occ, fid)
        # 2) catch no bloco que este frame executa
        container = node_at(occ["template"], frame["container_path"])
        if self._catch_disp(container, payload) == "ignorar":
            self._return_to_parent(occ, fid, frame["prev"])
            return
        ret = frame["ret"]
        if ret is None:  # workflow inteiro sem handler -> ocorrência falha
            occ["status"] = STATUS_FAILED
            occ["fail"] = payload
            return
        # 3) catch no nó que gerou este frame (loop/decision), no pai
        if ret["kind"] in ("loop", "decision"):
            parent = self._frame(occ, ret["parent"])
            spawn = node_at(occ["template"],
                            parent["container_path"] + ["filhos", parent["cursor"]])
            if self._catch_disp(spawn, payload) == "ignorar":
                # substitui o retorno deste filho (no join, para loop) e segue
                self._return_to_parent(occ, fid, payload)
                return
        self._fail_frame(occ, ret["parent"], payload)

    @staticmethod
    def _catch_disp(node, payload) -> str:
        """Disposição do primeiro handler que casa. Sem catch -> 'subir' (default)."""
        for handler in node.get("catch", []):
            match = handler.get("match", "*")
            if match == "*" or match in str(payload):
                disp = handler.get("disposicao", "subir")
                if disp == "tratar":
                    errlog.record("workflow: catch 'tratar' ainda não suportado; "
                                  "tratando como 'subir'")
                    return "subir"
                return disp
        return "subir"

    # ---- resolução de referências de dados ----------------------------
    def _resolve(self, occ, frame, value):
        if isinstance(value, str) and value.startswith("$"):
            return self._resolve_ref(occ, frame, value)
        if isinstance(value, dict):
            return {k: self._resolve(occ, frame, v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve(occ, frame, v) for v in value]
        return value

    def _resolve_ref(self, occ, frame, ref):
        parts = ref[1:].split(".")
        head, nav = parts[0], parts[1:]
        if head == "prev":
            base = frame["prev"]
        elif head == "item":
            base = frame["item"]
        elif head == "input":
            base = occ["inputs"]
        elif head == "node":
            base = occ["node_outputs"]
        else:
            return ref  # referência desconhecida -> literal
        for p in nav:
            base = base.get(p) if isinstance(base, dict) else None
        return base
