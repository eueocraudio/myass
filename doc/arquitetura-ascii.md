# Arquitetura myass — diagramas ASCII

Desenho textual da arquitetura especificada em `CLAUDE.md`, em três níveis:
inter-quadrante, um quadrante por dentro, e o fluxo de um pedido. Complementa os
diagramas renderizados em `doc/diagrama-arquitetura-tecnico.svg`/`.png`.

**Status de implementação:** `✅ feito` · `🟡 parcial` · `⬜ pendente`.
O diagrama do quadrante (nível 2) e a tabela ao final estão anotados.

> Lembrete: o `CLAUDE.md` é o **design-alvo**. O que roda hoje em `/opt/myass`
> (drone `bot_cve`) é a implementação legada, distinta (ver memória
> `existing-bot-implementation`). Os marcadores abaixo referem-se ao código novo
> neste repositório (`src/myass/`).

---

## 1. Visão macro — muitos quadrantes (o "subspace relay")

```
        ┌──────────────┐                                  ┌──────────────┐
        │  QUADRANTE A │                                  │  QUADRANTE B │
        │  (Rainha A)  │                                  │  (Rainha B)  │
        └──────┬───────┘                                  └──────┬───────┘
               │  deposita REQUEST  / puxa RESPONSE              │
               │      (X3DH + Noise, E2E, uma via)              │
               ▼                                                ▼
        ╔════════════════════════════════════════════════════════════╗
        ║   bdd  — BLIND DEAD DROP   (serviço .onion sobre Tor)  ⬜   ║
        ║   servidor CEGO: blobs opacos em endereços 64-hex           ║
        ║   channel(A→B)=BLAKE2s(...)  parts: request / response      ║
        ╚════════════════════════════════════════════════════════════╝
               ▲                                                ▲
               │              … QUADRANTE C, D, …  (malha)      │
               └────────────────────────────────────────────────┘
   pull-based · store-and-forward · decifra só DENTRO de cada núcleo
   ⬜ integração no myass pendente (o repo irmão `bdd` já existe)
```

---

## 2. Visão de um quadrante (o zoom) — anotado por status

```
╔═══════════════════════════════════════ QUADRANTE ═══════════════════════════════════════╗
║                                                                                          ║
║   WAN                                 │            NÚCLEO CONFIÁVEL (a Rainha)            ║
║                                       │                                                  ║
║  ┌─────────┐            ┌──────────┐  │  pull  ┌──────────┐    ┌────────────────────┐    ║
║  │ CLIENTE │  blob E2E  │ LOCUTUS  │  │◀───────│ ✅ GET   │──▶ │   ✅ BROKER        │    ║
║  │   ⬜    │──ChaCha20─▶│  🟡 cego │  │  push  │  poll()  │    │  (fila multinível) │    ║
║  │(codec ✅│◀───────────│ store ✅ │  │◀──────▶┌──────────┐    │ ✅ classes  MEM×CPU│    ║
║  │ de ref.)│  resposta  │ host ⬜  │  │        │ ✅ SET   │◀──▶│ ✅ ring     W/R    │    ║
║  └─────────┘            └──────────┘  │        │send_resp │    │ ✅ store    pymongo│    ║
║       │                               │        └──────────┘    │ ✅ requeue (regen.)│    ║
║  ✅ edge/crypto (AEAD por cliente)    │   borda ✅ edge/        └─────────┬──────────┘    ║
║  ✅ dedup request_id (anti-replay)    │                                  │ enqueue/dequeue║
║                                       │                        ┌─────────┴──────────┐    ║
║                                       │   ┌──────────┐         │  🟡 SCHEDULER      │    ║
║                                       │   │ ⬜ Mongo │◀───────▶│ ✅ despacho/lease  │    ║
║                                       │   │  server  │  leases │ ✅ regeneração     │    ║
║                                       │   │ (GridFS) │  invent.│ ✅ RESULT idemp.   │    ║
║                                       │   │  ✅ store│  audit  │ ✅ timeout/tentat. │    ║
║                                       │   │   code   │  seen   │ ⬜ motor workflow  │    ║
║                                       │   └──────────┘         │    (Nassi/cursor/  │    ║
║                                       │                        │     decision/loop/ │    ║
║                                       │                        │     catch)         │    ║
║                                       │                        └─────────┬──────────┘    ║
║  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │ ⬜ Noise KKpsk0 SOBRE TOR ─ ─ ─ │ ─ ─ ─ ─ ─ ─    ║
║                                       │     ╔════════════════════════════╪═══════════╗   ║
║                                       │   ┌─┴────────┐  ┌──────────┐  ┌──┴───────────┐   ║
║                                       │   │ ⬜ BLOCK │  │ ⬜ BLOCK │…│ ⬜ BLOCK      │   ║
║                                       │   │ Executor │  │ Executor │  │  Executor    │   ║
║                                       │   │  + BOTs  │  │  + BOTs  │  │   + BOTs      │   ║
║                                       │   └──────────┘  └──────────┘  └──────────────┘   ║
╚═══════════════════════════════════════════════════════════════════════════════════════════╝

  Transversal:  ✅ CANAL DE ERROS (errlog — anel circular, ponteiro único, Print() reverso)
                └─ plugado no ✅ Broker, ✅ Scheduler e ✅ borda GET

  Três muros da Rainha:  1) MASCARADA (Locutus cego)  2) ESCONDIDA (Tor)  3) DISTRIBUÍDA (Mongo)
```

---

## 3. Fluxo de um pedido (cliente → resultado)

```
 1. CLIENTE cifra pedido em linguagem humana (ChaCha20, segredo por cliente)  ✅ codec
        └─▶ deposita blob opaco no LOCUTUS

 2. ✅ GET (núcleo) faz polling no Locutus ─▶ decifra DENTRO do núcleo ─▶ dedup request_id
        └─▶ entrega o pedido à Rainha (on_request)

 3. RAINHA interpreta:  enfileira atividade "interpretar" ─▶ drone VAI devolve PLANO   ⬜
        (qual workflow + params)   ! saída do VAI é SUGESTÃO, nunca ordem
        └─▶ Scheduler só agenda bot_ref/template_hash APROVADOS no registro de publicação

 4. ⬜ Cria OCORRÊNCIA do template (árvore Nassi) ─▶ cursor avança passo a passo
        cada passo = ORDEM DE ATIVIDADE {atividade_id, occurrence_id, bot_ref, params, lease}

 5. ✅ BROKER classifica por MEM×CPU ─▶ escreve na fila (W)
        ✅ SCHEDULER entrega via WORK_GET ─▶ cria lease (EXECUTANDO)

 6. ⬜ EXECUTOR:  baixa projeto (PROJECT_GET) se frio ─▶ verifica project_hash (árvore)
        ─▶ venv por hash ─▶ spawn do SCRIPT (workdir tmpfs/LUKS)
        ✅ WORK_BEAT renova lease · ✅ RESULT idempotente ("1º vence") · ✅ regeneração

 7. ⬜ Artefato grande: DATA_PUT (content-addressed data_ref) ─▶ GridFS ─▶ DATA_GET no próximo

 8. Resultado final ─▶ ✅ SET cifra e empurra ao LOCUTUS ─▶ CLIENTE puxa a resposta

   Falhas:  ✅ infra (morte/timeout) -> LEASE/regeneração   ⬜ lógica (script) -> cadeia de CATCH
```

---

## Tabela de status

| Componente | Status | Onde / observação |
|---|---|---|
| Borda GET/SET | ✅ | `src/myass/edge/` — crypto (AEAD por cliente), gateway (poll/send_response), registry (dedup), locutus (Memory/Http) |
| Broker | ✅ | `src/myass/broker/` — classes MEM×CPU, ring W/R, store pymongo, carga preguiçosa, requeue |
| Scheduler | 🟡 | `src/myass/scheduler/` — despacho/lease/regeneração ✅ · motor de workflow Nassi ⬜ |
| Canal de erros | ✅ | `src/myass/errlog.py` — plugado no broker, scheduler e borda |
| Persistência (código) | ✅ | pymongo/`LeaseStore`/`seen` · **servidor Mongo/GridFS** em si ⬜ (infra) |
| Locutus | 🟡 | código de acesso ✅ · hosting HTTPS real ⬜ |
| Cliente | ⬜ | codec de referência (`edge/crypto`) ✅ para Arduino-class |
| Noise + transporte Tor | ⬜ | canal Executor↔Scheduler |
| Executor / blocks (drones) | ⬜ | |
| Subspace relay (inter-quadrante) | ⬜ | `bdd` é repo irmão; integração pendente |

_Suíte atual: 79 testes (`broker`, `ring`, `classes`, `scheduler`, `errlog`, `edge_crypto`, `edge_gateway`)._
