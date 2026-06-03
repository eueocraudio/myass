# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Pre-implementation. The repo currently holds only `README.md` and `doc/PROJETO Assistente Pessoal.pdf` (the founding design document). There is no source code, build tooling, or chosen language/framework committed yet, and the project structure described in the PDF **will be entirely redone** — do not treat its module/directory table as authoritative.

## What the project is

**myass** ("Assistente Pessoal Local") is an **orchestration platform** that runs on the user's own private/closed infrastructure (no personal data sent to the cloud). Its job is to **orchestrate the execution of routines, including AI routines** — coordinating specialized "Vertical AI" (VAI) models and ordinary automation routines rather than relying on a single general AI.

## Hard architectural requirements

These are firm constraints — any design or implementation must satisfy them:

- **Distributed.** Work runs across multiple nodes, not a single machine.
- **Fault-resilient.** The system must tolerate node/component failures and keep operating (no single point of failure; routines must survive and recover).
- **No inbound connections (toward the WAN).** Nothing may initiate a connection from the outside Internet into the infrastructure. All connections originate inside-out; external work is pulled by inside nodes (e.g. polling), never pushed in. No listening ports/services exposed to the outside.

## Identity & traceability

Blocks and BOTs are named by hashes, and the system must keep tamper-evident traceability of them:

- **A BOT is a project (many files) containing multiple scripts.** What an activity runs is identified by a **dual signature called `bot_ref`** = `{ project_hash, script_hash }`. Named components: **assinatura do projeto** = `project_hash = BLAKE2(whole project)` (the download/dedup unit) + **assinatura do script** = `script_hash = BLAKE2(the internal script)` (the entry point the activity runs). Each workflow step (and each `decision` `label → flow` target) points to an activity identified by its `bot_ref`. One workflow can reference scripts across several projects → downloads multiple projects (each fetched once, deduped by `project_hash`). The Executor downloads each project, verifies it against `project_hash`, runs the script for `script_hash`. Both hashes go in the audit log. Content-addressing doubles as integrity proof (tampered project/script ⇒ hash changes).
- **Manifest inside each project** (so it's covered by `project_hash` → tamper-evident). Declares, per script: `script_hash`, the **parameter schema** (fields/attributes/types), **requirements** (incl. the MEM/CPU hardware *exigência* used to classify the activity into the broker, plus dependencies), and **APIs** used. The editor's "rich catalog of bots/scripts" is just an index built from manifests (convenience); the authoritative source is the in-project hashed manifest. The editor auto-populates an activity's schema from the manifest; the user supplies/overrides values.
- **Block name = `BLAKE2(block's Noise static public key)`** — the name *is* the block's cryptographic identity, authenticated by the Noise `KK` handshake (a forged block name fails the handshake; no need to trust a self-reported name).
- All hashes use **BLAKE2** (same as the channel suite — non-NIST, fast).
- **Traceability lives only in the trusted core**, maintained by the Scheduler:
  - **Inventory registry:** `block_hash → { available bot_refs }`.
  - **Append-only audit log:** per execution `(block_hash, bot_ref, occurrence_id, when, input/output refs, status)` — kept **only in the central core**. `bot_ref` records both the assinatura do projeto and the assinatura do script.

## Routines & chaining (encadeamento)

A routine is an **activity tree** (a Nassi-Shneiderman workflow). The tree is an immutable **template**; running it creates an **ocorrência (occurrence)** — a live instance that carries the execution **cursor** (position, loop/join state, partial results, status, an occurrence id). The **Scheduler** drives chaining: an activity's returned result is the "tick" that advances the occurrence's cursor and enqueues the next activity. Each step / decision route points to an activity by its `bot_ref`.

- **Concurrency:** **synchronous within a single Nassi diagram** (activities in sequence); parallelism = **multiple diagrams running at once (async)**.
- **block:** linear (sync) sequence of activities.
- **action:** a unit that goes to the broker and runs a script; its return advances the cursor.
- **decision (N-way):** the condition is itself a **script that returns a LABEL** (a normal content-addressed, hardware-classified, async activity); the author maps **label → flow** (N routes); visual = downward triangle; flows converge back to the linear sequence.
- **loop (foreach + fan-out):** foreach over an array; body = a **fixed inner Nassi diagram**; each iteration is a **copy of that diagram** fed the item's data; all copies run **async in parallel** (sync within each). **`parent_id`**: each child copy references its parent (the loop) → execution tree; the parent **waits while any child runs**; the **join** returns an **array of returns** (one per iteration) as the loop's output. `parent_id`/join is general to any fan-out.
- **Error handling — nested `catch` following the structure:** every scope (decision, block, loop, workflow) may have a `catch`; errors **bubble innermost-first outward** until handled (else the occurrence fails → audit). Within a scope, handlers are ordered most-specific-at-top; **topmost match wins**; each handler is a script. A catch that handles a child's failure substitutes its return into the join array for that item.
- **Per-error disposition (author's choice, 3 options):** **handle with a script** / **propagate up** (subir) / **ignore** (swallow). The **default is propagate up** (errors surface and bubble; safest). **Ignore is explicit opt-in** (silently swallowing is dangerous — must be deliberate).
- **Two failure layers (don't conflate):** *infra* (executor died, timeout) → broker lease/redelivery; *logical* (script errored / unmapped label) → the catch chains.

## Workflow editor (authoring tool)

- **PySide6 desktop app on Linux** — the authoring tool for routines (replaces the PDF's Mobile/Nassi authoring, which is dropped). The thing it edits is called a **workflow** = the activity-tree template.
- **Linear authoring, Nassi-Shneiderman style** (vertical sequence), not a free node-graph. `loop`/`decision` constructs nest within the sequence. (Async loop is a *runtime* semantic; the authoring layout stays linear.)
- **Structured canvas** (Nassi is inherently structured — no free-floating arrows; flow is contiguous boxes + nesting). Built on **`QGraphicsView` + `QGraphicsScene`**, each node type a `QGraphicsItem` subclass (action = box, decision = downward triangle + columns, loop = container box wrapping the inner diagram, block = vertical stack). The user **inserts/snaps blocks** (not free drawing); the canvas auto-lays-out and **is just the render of the activity tree**, so it stays always-valid and **serializes directly to the template** (each visual block = one tree node).
- In a workflow the user defines **activities**; each activity has a rich, user-defined schema — **fields, attributes, requirements, APIs, etc.** — plus the BOT it runs and its parameters/input.
- A **BOT is a whole project (many files) with multiple scripts**, not a single script. An activity selects a project + a script inside it via its **`bot_ref`** (assinatura do projeto + assinatura do script — see *Identity & traceability*). The Executor downloads the project, verifies it against the assinatura do projeto, and runs the chosen script.

## Guiding principle: always the most secure path

**Always choose the most secure option, even if it is harder or more work.** When security trades off against convenience, effort, or simplicity, security wins by default — propose and build the stronger option without being asked, and only fall back if the owner explicitly decides so.

## Architecture decisions

**Topology.** Two zones:
- **Trusted core:** GET, SET, the custom Python broker (distributed, fault-resilient), internal storage, **and the Scheduler (Escalonador)**. Internal core links use their own secure channel (see below).
- **Distributable block = Executor + its BOTs/routines:** self-contained, runs on its own machine outside the core, accepts no inbound. **Blocks are the unit of distribution** — replicate blocks to scale and to tolerate failure (lose one block, the others continue). Each block's Executor *dials out* to the Scheduler in the core.

> **Scope of the secure channel below:** the Noise/framing design specified here applies **only to the Executor↔Scheduler link** — the single exposed/"vulnerable" part (Executor in a block, on a different machine, connecting to the Scheduler in the core). Other links (within the trusted core, the GET/SET edge, the broker) have their own communication schemes, defined separately (TBD).

- **Executor → Scheduler (Escalonador) connection.** The Executor *initiates* the connection to the Scheduler (so Executors accept no inbound). Executors may run on different machines.
- **Scheduler is the central intermediary.** The Scheduler brokers *all* communication — Executors do not talk directly to the broker, storage, or each other; everything passes through the Scheduler.
- **Raw socket, custom protocol.** This channel is a **TCP stream socket** (`SOCK_STREAM`, *not* `SOCK_RAW`) — referred to as "raw" — with no classic application protocols (no HTTP, etc.). A custom protocol sits on top of the socket, chosen for security.
- **No TLS — handshake copied from the Noise Protocol Framework.** The Executor↔Scheduler handshake/encryption copies the proven **Noise `KKpsk0`** pattern (rather than inventing crypto from scratch). Cipher suite: **`Noise_KKpsk0_25519_ChaChaPoly_BLAKE2s`** — X25519 (DH), ChaCha20-Poly1305 (AEAD cipher), BLAKE2s (hash). All non-NIST primitives (anti-state-surveillance threat model). The protocol/framing is the project's own; the crypto pattern is copied from Noise.
  - **`KK`** = both parties' static public keys are known in advance (provisioned **physically**, out-of-band — this is what "physical key exchange" means now).
  - **`psk0`** = an additional pre-shared symmetric key, also provisioned physically, mixed in at the start (belt-and-suspenders auth).
  - Initiator = **Executor** (it dials out); Responder = **Scheduler**.
  - Ephemeral keys per session give **forward secrecy**; transport phase uses ChaCha20-Poly1305 with a per-direction **counter nonce** (always unique → also anti-replay) and the Poly1305 tag for per-message integrity.
- **Framing over TCP — two levels (decision (b)).** A **record** = one application message:
  - Wire: `record_len (4B BE)` + record body. Body = a sequence of Noise blocks, each `blk_len (2B BE)` + Noise message (`ciphertext + 16B tag`). `blk_len` is needed because each block is decrypted individually; a single Noise block is still capped at 65535 bytes (AEAD limit).
  - Record plaintext (before chunking/encrypting): `real_len (4B) || payload || zero-pad to next multiple of 256`. Then split into chunks of ≤ **65280 bytes** (255×256, multiple of 256 and ≤ 65519), each encrypted as a Noise transport message. The per-direction counter nonce advances per block.
  - Receiver: read `record_len`; read body; loop `blk_len`→read→Noise-decrypt→append; concatenate chunks → record plaintext; read `real_len`; take payload; discard padding.
- **Size-hiding padding (block).** Padding lives at the record level (above): plaintext padded to a multiple of **256 bytes** inside the AEAD, so an observer sees only coarse padded sizes. (Secure form of the PDF's "despistar o tamanho" — padding inside the AEAD, not cleartext.)
- **No cleartext fingerprint.** No magic header / cleartext protocol marker — a Noise handshake starts with an ephemeral key (random-looking), so the wire is not trivially DPI-identifiable. The protocol **version goes in the Noise `prologue`** (authenticated in the handshake hash, never sent in clear), not in a cleartext header.
- **Primitives must be audited, not hand-rolled.** Per the most-secure-path rule and the nation-state threat model, the Noise *primitives* (X25519/ChaChaPoly/BLAKE2s) should come from an open, auditable, reproducible-build implementation — not reimplemented by hand (hand-rolled primitives leak side-channels a state adversary exploits). Implementing the *protocol/framing* by hand is fine and intended.

### Internal core links (Scheduler↔Broker, Broker↔Storage, GET/SET↔Broker)

Separate from the exposed Executor↔Scheduler channel; these run inside the trusted core but still use a secure channel:

- **Handshake: Noise `NNpsk0`** — ephemeral keys on both sides (dynamic per-session key → forward secrecy), authenticated by a **pre-shared key set at install time**. No per-component static identities (`NN`, not `KK`).
- **Per-pair PSK.** Each pair of core components has its own install-time PSK (smaller blast radius if one leaks).
- The install PSK only *authenticates* the handshake; it does not encrypt traffic — so a leaked `.env` does not expose past sessions (forward secrecy). The PSK may live in `.env` with safeguards: on the LUKS partition, `chmod 600`, gitignored.
- **Same primitives and framing as the external channel** (X25519 / ChaCha20-Poly1305 / BLAKE2s; 4B record + 2B block framing). **Padding is kept** on internal links too.

## Design notes from the PDF — with corrections

The PDF (`doc/PROJETO Assistente Pessoal.pdf`) is a draft; parts marked in red are author notes and several sections are unfinished. The following corrections from the project owner override the document:

- **No RabbitMQ — a custom queue/broker instead.** The coordination mechanism is a **queue/broker**, but it is the project's **own broker, implemented as a service in Python** (not RabbitMQ or any third-party product). It must satisfy the distributed + fault-resilient + inside-out requirements below. (Not yet committed to this repo.)
- **No HSM.** The Hardware Security Module design (Thales/SafeNet, RS-232/USB isolation, physical-intrusion defenses) will not be implemented.
- **No case study.** The Security/CVE pipeline (NIST, CVEDetails, Vulmon; chapter 4) is out of scope.
- **Structure will be rebuilt.** Ignore the projects/directories/languages table on page 36.

Still relevant from the PDF as background intent: closed-infrastructure security posture (all connections originate inside-out), a Scheduler/Executor model running routines as subprocesses, and routines described as JSON activity trees (action / loop / block).

## Guidance for future work

The first substantive changes will define the project's conventions. As they land:

- Record the chosen language, framework, package manager, and build/lint/test commands here.
- Replace this status section with real architecture notes once code exists.
