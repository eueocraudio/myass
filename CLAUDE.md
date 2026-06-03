# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Pre-implementation. The repository currently holds only `README.md`, this file, and the founding design document under `doc/`. There is **no source code, build tooling, or chosen build commands yet** — those sections will be filled in as the project is scaffolded. This document is the authoritative architecture spec; it is self-contained and does not depend on the founding PDF.

## What the project is

**myass** ("Assistente Pessoal Local") is an **orchestration platform** that runs entirely on the user's own private, closed infrastructure (no personal data sent to any cloud). Its job is to **orchestrate the execution of routines, including AI routines** — coordinating specialized "Vertical AI" (VAI) models and ordinary automation routines, rather than relying on a single general AI.

## Guiding principle: always the most secure path

**Always choose the most secure option, even if it is harder or more work.** When security trades off against convenience, effort, or simplicity, security wins by default — propose and build the stronger option without being asked, and only fall back if the owner explicitly decides otherwise.

### Threat model

The adversary is a **nation-state with broad reach** ("the government has access to everything"); myass is a personal privacy / anti-surveillance system. Consequences that shape every decision:

- **Non-NIST primitives** are preferred (the privacy-community stack): X25519, ChaCha20-Poly1305, BLAKE2 — all by djb/peers, used by Signal/WireGuard/Tor.
- **Crypto primitives must be audited, reproducible-build implementations — never hand-rolled.** A self-written cipher leaks the side-channels a state adversary exploits. Writing the *protocol/framing* by hand is fine and intended; writing the *primitives* by hand is not.
- The real state-level risks live in **endpoints, metadata/traffic analysis, key handling, and physical access** — not in the choice of cipher.

## Hard architectural requirements

Firm constraints — any design or implementation must satisfy all three:

- **Distributed.** Work runs across multiple nodes, not a single machine.
- **Fault-resilient.** Tolerate node/component failure and keep operating — no single point of failure; routines must survive and recover.
- **No inbound connections (toward the WAN).** Nothing may initiate a connection from the outside Internet into the infrastructure. All connections originate inside-out; external work is *pulled* by inside nodes (polling), never pushed in. No listening ports/services exposed to the outside.

## Scope decisions (explicitly out)

- **No RabbitMQ (or any third-party broker).** The coordination mechanism is still a queue/broker, but it is the project's **own broker, implemented as a service in Python** (see *Broker* below).
- **No HSM.** Hardware Security Module designs are not implemented.
- **No security/CVE case study.** Out of scope.

## Topology

Two zones:

- **Trusted core:** the `GET`/`SET` edge, the custom Python **broker**, internal **storage (MongoDB)**, and the **Scheduler (Escalonador)**. Internal links inside the core use their own secure channel (see *Internal core links*).
- **Distributable block = Executor + its BOTs/routines:** self-contained, runs on its own machine outside the core, **accepts no inbound**. **Blocks are the unit of distribution** — replicate blocks to scale and to tolerate failure (lose one block, the others continue). Each block's Executor **dials out** to the Scheduler.

Inside-out edge: **`GET`** polls a public store (on the WAN) for requests, decrypts, and enqueues them; **`SET`** pushes results back out. The infrastructure never listens for inbound connections.

```
   WAN            │              TRUSTED CORE
 ┌────────┐  pull │  ┌─────┐   ┌──────────┐   ┌─────────┐
 │ public │◀──────┼──│ GET │──▶│  BROKER  │◀─▶│ MongoDB │
 │ store  │──────▶┼  └─────┘   │ (Python) │   └─────────┘
 └────────┘  push │  ┌─────┐   └────┬─────┘
      ▲           │  │ SET │◀───────┤
      └───────────┼  └─────┘   ┌────┴──────┐
                  │            │ SCHEDULER │
                  │            └────┬──────┘
                  │     Noise KKpsk0 │  ← Executors dial out (exposed link)
                  │   ╔══════════════╪═══════════════╗
                  │ ┌─┴──────┐  ┌────┴───┐  ┌─────────┴┐
                  │ │ BLOCK  │  │ BLOCK  │…│ BLOCK     │  (Executor + BOTs;
                  │ │ Exec+  │  │ Exec+  │ │ Exec+     │   replicate for scale
                  │ │ BOTs   │  │ BOTs   │ │ BOTs      │   & fault tolerance)
                  │ └────────┘  └────────┘ └───────────┘
```

## Identity & traceability

Everything is named by content/identity hashes (all **BLAKE2**, non-NIST), giving tamper-evident traceability.

- **Block name = `BLAKE2(block's Noise static public key)`.** The name *is* the block's cryptographic identity, authenticated by the Noise `KK` handshake — a forged block name fails the handshake, so a self-reported name is never trusted.
- **A BOT is a project (many files) containing multiple scripts.** What an activity runs is identified by a **dual signature `bot_ref` = `{ project_hash, script_hash }`**:
  - **assinatura do projeto** = `project_hash = BLAKE2(whole project)` — the download/dedup unit.
  - **assinatura do script** = `script_hash = BLAKE2(the internal script)` — the entry point the activity runs.
  - One workflow may reference scripts across several projects → multiple projects downloaded (each fetched once, deduped by `project_hash`). The Executor downloads a project, **verifies it against `project_hash` before running**, then runs the script for `script_hash`. Content-addressing doubles as an integrity proof (any tamper changes the hash).
- **Manifest inside each project** (so it is covered by `project_hash` → tamper-evident). Declares, per script: `script_hash`, the **parameter schema** (fields/attributes/types), **requirements** (the MEM/CPU hardware *exigência* used to classify the activity in the broker, plus dependencies), and **APIs** used. The editor's catalog of bots/scripts is just an index built from manifests; the authoritative source is the in-project hashed manifest.
- **Traceability lives only in the trusted core**, maintained by the Scheduler:
  - **Inventory registry:** `block_hash → { available bot_refs }`.
  - **Append-only audit log:** per execution `(block_hash, bot_ref, occurrence_id, when, input/output refs, status)` — kept **only in the central core**.

## Broker (multi-level messageria)

The project's own queue/broker, a Python service, distributed and fault-resilient. Two levels:

- **Level 1 — linked list of nodes, one node per resource class.** Classes come from an arbitrary classification table over **MEM × CPU** (e.g. C1 baixa/baixa, C2 baixa/alta, C3 alta/baixa, C4 alta/alta). The table is *not* severity-ordered.
- **Level 2 — a ring buffer (circular list) per node**, with two pointers: **W (write/producer)** and **R (read/consumer)**. The **read window = W − R** = activities available to consume.
- **Empty window (W − R = 0):** return `[]` **immediately** (non-blocking) and, **in parallel**, spawn a loader thread that refills that node from MongoDB. Guard: at most **one load in flight per node** (and back off when MongoDB is also empty).
- **Durable backing store: MongoDB** (scalable). The ring is an **in-memory window over the persisted backlog** — durability/fault-tolerance live in MongoDB; the ring is the fast cache.
- **Where an activity is written (W):** into the node whose class matches the activity's *exigência* (declared in the project manifest).
- **How a block reads:** the Scheduler matches the block's hardware profile (from `HELLO`) against the classes it satisfies — a class is eligible only if the block satisfies **both MEM and CPU**. (Reverted from an earlier severity-ordered scan; the match is the only rule.)

## Routines & chaining (encadeamento)

A routine is an **activity tree** (a Nassi-Shneiderman workflow) with node types **block / action / decision / loop**. The tree is an immutable **template**; running it creates an **ocorrência (occurrence)** — a live instance carrying the execution **cursor** (position in the tree, the `parent_id` execution tree, loop/join state, partial results, status, an `occurrence_id`). The **Scheduler drives the chaining**: an activity's returned result is the "tick" that advances the occurrence's cursor and enqueues the next activity. Many occurrences of one template run independently. Each step / decision route targets an activity by its `bot_ref`.

- **Concurrency:** **synchronous within a single Nassi diagram** (activities run in sequence); parallelism = **multiple diagrams running at once (asynchronous)**.
- **block:** a linear (sync) sequence of activities.
- **action:** a unit that goes to the broker and runs a script; its return advances the cursor.
- **decision (N-way):** the condition is itself a **script that returns a LABEL** (a normal content-addressed, hardware-classified, async activity); the author maps **label → flow** (N routes) in the editor; visual = a downward triangle. The cursor runs the condition-script → gets the label → routes to the mapped flow; flows converge back to the linear sequence.
- **loop (foreach + fan-out):** foreach over an **array**; the body is a **fixed inner Nassi diagram**, and each iteration is a **copy of that same diagram** fed the item's data (each array item = different input). Copies run **async in parallel** (sync within each). Each child copy carries its **`parent_id`** (the loop) → execution tree; the parent **waits while any child is still running**; the **join** returns an **array of returns** (one per iteration) as the loop's output. `parent_id`/join is general to any fan-out.
- **Error handling — nested `catch` following the structure.** Every scope (decision, block, loop, workflow) may register a `catch`. An error **bubbles innermost-first outward** through each enclosing scope until one handles it (else the occurrence fails → audit). Within a scope, handlers are ordered most-specific-at-top; **topmost match wins**; each handler is a script. When a catch handles a child's failure, its return is substituted into the join's array for that item.
- **Per-error disposition (author's choice, 3 options):** **handle with a script** / **propagate up (subir)** / **ignore (swallow)**. The **default is propagate up** (errors surface and bubble — safest). **Ignore is explicit opt-in** (silently swallowing an error is dangerous and must be deliberate).
- **Two failure layers — do not conflate:** *infra* failures (executor died, timeout) → handled by broker **lease/redelivery** (resilience); *logical* failures (script errored / unmapped label) → handled by the **catch** chains.

## Workflow editor (authoring tool)

- **PySide6 desktop app on Linux** — the authoring tool for routines. The artifact it edits is a **workflow** = the activity-tree template.
- **Structured canvas** (Nassi is inherently structured — no free-floating arrows; flow is contiguous boxes + nesting). Built on **`QGraphicsView` + `QGraphicsScene`**, each node type a `QGraphicsItem` subclass: action = box, decision = downward triangle + columns, loop = container box wrapping the inner diagram, block = vertical stack. The user **inserts/snaps blocks** (no free drawing); the canvas auto-lays-out and is **just the render of the activity tree**, so it stays always-valid and **serializes directly to the template** (one visual block = one tree node).
- In a workflow the user defines **activities**; each activity has a rich, user-defined schema — **fields, attributes, requirements, APIs, etc.** — plus the BOT (`bot_ref`) it runs and its parameters/input. The schema is **auto-populated from the project manifest**; the user supplies/overrides values.

## Secure channels

All channels use a **custom protocol over a raw TCP stream socket** (`SOCK_STREAM`, *not* `SOCK_RAW`) — no HTTP or other classic application protocol. There is **no TLS**; the handshake/encryption **copies the Noise Protocol Framework** (proven design, implemented by us over our own framing). Primitives: **X25519 / ChaCha20-Poly1305 / BLAKE2s** (all non-NIST), from an audited reproducible-build library.

### External channel — Executor ↔ Scheduler (the exposed link)

This is the **single exposed/"vulnerable" link** (Executor in a block, on a different machine, dialing the Scheduler in the core).

- **Pattern: Noise `KKpsk0`** → suite `Noise_KKpsk0_25519_ChaChaPoly_BLAKE2s`.
  - **`KK`** = both parties' static public keys are known in advance, **provisioned physically (out-of-band)** — this is what "physical key exchange" means. No in-band key negotiation, removing the over-the-wire MITM surface.
  - **`psk0`** = an additional pre-shared key, also provisioned physically, mixed in at the start (belt-and-suspenders auth).
  - Initiator = **Executor** (dials out); Responder = **Scheduler**.
  - Ephemeral keys per session → **forward secrecy**. Transport uses ChaCha20-Poly1305 with a per-direction **counter nonce** (always unique → also anti-replay) and the Poly1305 tag for per-message integrity.
- **No cleartext fingerprint:** no magic header — a Noise handshake opens with a random-looking ephemeral key, so the wire is not trivially DPI-identifiable. The **protocol version goes in the Noise `prologue`** (authenticated in the handshake hash, never sent in clear).

### Internal core links — Scheduler↔Broker, Broker↔Storage, GET/SET↔Broker

Inside the trusted core, but still encrypted.

- **Pattern: Noise `NNpsk0`** — ephemeral keys on both sides (dynamic per-session key → forward secrecy), authenticated by a **pre-shared key set at install time**. No per-component static identities.
- **Per-pair PSK** — each pair of core components has its own install-time PSK (small blast radius if one leaks).
- The install PSK only *authenticates* the handshake; it does not encrypt traffic, so a leaked key does not expose past sessions (forward secrecy). It may live in `.env` with safeguards: on the LUKS partition, `chmod 600`, gitignored.
- Same primitives and framing as the external channel; **padding is kept** here too.

### Framing over TCP — two levels

A **record** = one application message.

- **Wire:** `record_len (4B BE)` + record body. The body is a sequence of Noise blocks, each `blk_len (2B BE)` + Noise message (`ciphertext + 16B tag`). `blk_len` is needed because each block is decrypted individually; a single Noise block is capped at 65535 bytes (AEAD limit).
- **Record plaintext** (before chunking/encrypting): `real_len (4B) || payload || zero-pad to the next multiple of 256`. Then split into chunks of ≤ **65280 bytes** (255×256, a multiple of 256 and ≤ 65519), each encrypted as one Noise transport message; the per-direction counter nonce advances per block.
- **Receiver:** read `record_len`; read the body; loop `blk_len` → read → Noise-decrypt → append; concatenate chunks → record plaintext; read `real_len`; take the payload; discard padding.
- **Size-hiding padding (block):** padding to a multiple of 256 lives *inside* the AEAD (record level), so an observer sees only coarse padded sizes.

### Application layer — Executor ↔ Scheduler (partially defined)

- **Capability-based scheduling (confirmed):** the Executor's `HELLO` carries the block's **hardware profile** (OS name, MEM, CPU/arch+cores); the Scheduler matches it against broker resource classes (MEM and CPU gate) to pick the best-fit activity.
- **Pull + work-lease (proposed direction):** the Executor pulls work; each grant carries a lease; if the Executor dies, the lease expires and the broker redelivers (this is the *infra* failure layer). Results are idempotent, keyed by `occurrence_id`/work id; the Executor verifies the BOT project against `bot_ref` before running; identity comes from the Noise handshake, never self-reported. *(The concrete message set / encoding is still open.)*

## Theoretical analysis & proposed redesign (not yet adopted)

The design was cross-referenced against **Tanenbaum** (distributed systems) and **Monero** (privacy network). Both converge on the same weak point: the **central core** (Tanenbaum: scalability bottleneck / logical SPOF; Monero: single point of surveillance/coercion — the core decrypts everything and holds the audit log/inventory/keys). See:

- `doc/analise-tanenbaum.md` — distributed-systems cross-analysis.
- `doc/analise-monero.md` — privacy/network cross-analysis.
- `doc/redesign-minimum-knowledge-core.md` — a proposed "minimum-knowledge core" redesign.

**The redesign is a PROPOSAL pending the owner's per-item decision — do not treat it as adopted.** Headline ideas: blind-router core (E2E to the executor), rotating/one-time identities + key-image-like anti-replay, network anonymity (Tor/I2P + stem/fluff + cover traffic), stateless-over-MongoDB (lean on the replica set for consensus), optional N-block voting for Byzantine-critical work, idempotency as an invariant, view/act key separation. Five open decisions are listed in the redesign doc.

## Guidance for future work

The first substantive changes will define the project's conventions. As they land:

- Record the chosen language(s), framework, package manager, and the build/lint/test commands here.
- Replace the "Project status" note once real code exists.
- Keep terminology consistent: **Scheduler (Escalonador)**, **block** (= Executor + BOTs unit), **BOT** (= a project), **script**, **`bot_ref`** (assinatura do projeto + assinatura do script), **occurrence (ocorrência)**, **exigência** (hardware requirement).
