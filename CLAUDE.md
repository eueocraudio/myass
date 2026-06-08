# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Pre-implementation. The repository currently holds only `README.md`, this file, and the design artifacts under `doc/`. There is **no source code, build tooling, or chosen build commands yet** — those sections will be filled in as the project is scaffolded. This document is the authoritative architecture spec; it is self-contained and does not depend on the founding PDF.

### Reference artifacts in `doc/`

- `doc/diagrama-arquitetura.svg` / `.png` — friend-facing rendered architecture (simplified vocabulary; predates the hidden-Queen/Tor/quadrante refinements).
- `doc/diagrama-arquitetura-tecnico.svg` / `.png` — current technical architecture: the quadrante, the hidden Queen, Locutus, the Tor subspace channel, Noise patterns, and the (undefined) inter-quadrante link.
- `doc/diagrama-fluxo.svg` / `.png` — execution/flow diagram.
- `doc/myass-apresentacao.pdf` / `.html` — friend-facing presentation of the project.
- `doc/analise-tanenbaum.md`, `doc/analise-monero.md`, `doc/redesign-minimum-knowledge-core.md` — theory cross-analyses and the proposed redesign (see *Theoretical analysis* below).

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

## Filosofia Borg: a Rainha escondida

The project's organizing metaphor is the Borg collective. The collective **does** have a Queen — but she is **hidden, never reachable from the outside.** (This refines the earlier "coletivo sem Rainha" slogan: there *is* a Queen; there is simply no Queen the adversary can **find or reach**.) Adopted as the guiding philosophy.

**Tese:** *the adversary's prize is a Queen he can find and coerce.* The collective survives a nation-state by ensuring the central mind is never locatable or reachable from the WAN: her only face to the world is a **blind mouthpiece (Locutus)**, she herself lives **hidden** behind the Tor subspace channel, and she is **distributed** so she is no single point of failure. She is allowed to *know* — she is not allowed to be *reached*.

### Vocabulary (Borg ↔ arquitetura)

- **drone = block** (Executor + BOTs) — the replaceable, specialized unit of the collective; the unit of distribution.
- **designação (designation) = `block_name` = `BLAKE2(static pubkey)`** — the drone's cryptographic identity (see *Identity & traceability*).
- **assimilação (assimilation) = the provisioning payload** that stands up a brand-new drone (see below).
- **regeneração (regeneration) = broker lease/redelivery** — a drone dies, its work returns to the queue and is redelivered (the *infra* failure layer).
- **adaptação (adaptation) = catch chains + redelivery** — the collective absorbs failure and keeps running.
- **canal sub-espacial (subspace channel) = the Executor↔Scheduler link, carried over Tor** — the location-hidden link between drones and the core (see *Secure channels*).
- **Rainha (Queen) = Broker + Scheduler** — the central orchestrating mind: reads the client's request and drives the drones. Hidden, not blind (see below).
- **Locutus = the public store** — the Queen's *blind mouthpiece*: the conversation-bridge on the WAN between a human-language client and the hidden Queen. Holds only opaque ciphertext. (The "Locutus invertido": the canon Locutus knew the collective's mind and so doomed it — ours knows nothing, so capturing it yields a bucket of opaque bytes.)

### A Rainha — escondida, não cega (postura adotada)

**Owner decision:** the collective has a Queen — **the Rainha = Broker + Scheduler** — the central mind that reads the client's request and orchestrates the drones. She is **not** a blind router: you cannot orchestrate what you cannot read, and turning a human-language request into activities/`bot_ref`s is inherently a knowing act. (Deliberate divergence from the redesign's blind-router idea — see *Theoretical analysis*.)

Because she *knows*, she is protected by **three walls** instead of by blindness:

1. **Masked** — her only face to the WAN is **Locutus** (the public store), which is *blind*. Capture the mouthpiece → opaque blobs, not the mind. `GET`/`SET` decrypt only **inside** the hidden core, never at Locutus.
2. **Hidden** — she lives behind the Tor subspace channel (location-hidden onion); there is no IP/port to scan or raid. You cannot raid a Queen you cannot locate.
3. **Distributed** — replicated/stateless-over-MongoDB so she is no single point of *failure* (the Tanenbaum SPOF), even though she remains a single point of *knowledge*.

**Residual risk, stated honestly:** a Queen who is *located and coerced* is the jackpot (content + audit + inventory). This posture leans hard on Tor + Locutus' blindness; it is the chosen trade-off (centralized natural-language orchestration is worth it), not an oversight.

- **Rainha-parteira efêmera — the provisioning station** (mints drone identities; see assimilation). **Tolerated** because it is momentary, not sovereign: air-gapped, single-use per drone, retains no keys after minting, never online. A midwife of an instant is not a ruler.

*Open:* whether the human-language interpreter (request → plan, itself an AI routine) runs **inside the Queen** or is dispatched to a **VAI drone** — pending. Physical backing of Locutus (object storage / IPFS / rotating mirrors) — pending.

### Assimilação (provisioning a drone) — adopted model

**Owner decision: the keypair is minted at provisioning and embedded in the payload (one-shot assimilation).** Running the payload turns a fresh machine into a drone that can immediately dial out and complete the Noise `KK` handshake — because its pubkey was already registered in the Inventory at minting time. (This is the convenience path, chosen deliberately over the more-secure "key born on the drone" path, so it ships **with** the hardening rules below.)

What the payload does on the target: check the hardware *exigência*; install the Executor runtime + pinned deps **verifying hashes** (reproducible build — otherwise you assimilate a poisoned drone); install the embedded X25519 static private key + the Scheduler static pubkey + the `KKpsk0` PSK; compute its **designação** `BLAKE2(pubkey)`; configure dial-out (no listening port — honours *no inbound*).

Because the payload **carries a secret** (static private key + PSK) it is sensitive material; these rules hold together:

1. **One key per drone, never reused** — each payload is unique; designation is unique.
2. **Provisioning station offline / air-gapped, under LUKS** — the only organ that briefly knows private keys (the ephemeral midwife-Queen).
3. **Payload is single-use and short-lived** — minimal window if intercepted.
4. **On the target:** move the private key to LUKS / `chmod 600`; **destroy/zero the payload media** after install.

**Vector follows by force:** since the payload carries a private key, it travels **out-of-band on physical media (USB)** — never on the public store in clear.

## Topology

**Outermost unit — the quadrante.** Everything below (the WAN edge / Locutus, the trusted core / Rainha, and the blocks) lives inside one big box called a **quadrante**. The system is composed of **many quadrantes**; a single quadrante is a complete, self-sufficient instance of the architecture described here. Rendered in `doc/diagrama-arquitetura-tecnico.svg`.

**Inter-quadrante communication — the `subspace relay` (relé de subespaço), a blind REQUEST/RESPONSE dead drop between Queens (adopted).** The cross-quadrante link is named the **subspace relay** (Star-Trek-consistent with the intra-quadrante *canal sub-espacial*). Quadrantes talk **Queen-to-Queen** (Rainha ↔ Rainha, plural) through a **blind dead drop** that holds only opaque ciphertext: one Queen *deposits* a REQUEST, the peer Queen *pulls* it; RESPONSEs travel back the same way. This is **Locutus between Queens** — the same blind dead-drop pattern as the WAN edge, applied between cores. **Pull-based and carried over Tor**, so it honours *no inbound* and never reveals one core's location to another; decryption happens only inside each hidden core. Because the deposit is **asynchronous store-and-forward**, the interactive Noise handshakes used elsewhere (`KK`/`NN`) do **not** apply.

  - **Implementation: the `bdd` (Blind Dead Drop) project at `../bdd`** — its own generic repo, consumed by myass (see its `CLAUDE.md`). `bdd` is a stdlib HTTPS/HTTP service whose **server is blind**: opaque blobs at opaque 64-hex addresses; it can neither read content nor link the two parts/parties. It already models our exact shape — a **channel** (int) with two **parts, `request` and `response`**, whose addresses + keys derive from *different* `HKDF` labels so the server can't correlate them — plus **long-poll** (`?wait=N`) for pull, **TTL buckets** to blunt temporal metadata, and a `--no-tls` mode meant to run **behind a Tor onion service** (content is already E2E). So the deposit, Tor transport, blindness, and request/response slots are **done** in `bdd`.
    - **Live `bdd` onion endpoint (stable):** `http://46xhzbennzgxolftzlufl27yzwx4gdfb3xmv5wsuw46tbd74tv6tbjad.onion:8081` (no TLS — content is E2E and the `.onion` is itself the access credential).

  - **Crypto delta to reconcile (owner decision).** `bdd`'s client-side crypto is **symmetric**: a shared 32-byte root secret → `HKDF-SHA256` → per-part address + a ChaCha20-Poly1305 message key. Two gaps vs. the myass threat model: (1) **no forward secrecy and no public-key sender auth** — a leaked root secret exposes past *and* future messages on that channel and lets either holder forge; (2) derivation uses **SHA-256** (NIST/SHA2), whereas myass *prefers* non-NIST (BLAKE2). **Recommended reconciliation:** treat `bdd` as the dumb blind transport and layer myass's own **one-way Noise between the Queens' static keys** (`Noise_K`/`Kpsk0`, ephemeral per message → FS, mutual pubkey auth) *inside* the blob `bdd` carries — keeps `bdd` generic and gives myass FS + asymmetric auth on top. AEAD is consistent either way (ChaCha20-Poly1305).
  - **Still open:** REQUEST/RESPONSE **idempotency** + **anti-replay** (a dead drop invites replay); **addressing** — map quadrante identity (`BLAKE2(Queen static pubkey)`) onto `bdd` channels/secrets + a routing table; cross-quadrante metadata / cover traffic.

Within a quadrante there are two zones:

- **Trusted core:** the `GET`/`SET` edge, the custom Python **broker**, internal **storage (MongoDB)**, and the **Scheduler (Escalonador)**. The **broker + Scheduler together are the Rainha** — the hidden orchestrating mind (see *Filosofia Borg*). Internal links inside the core use their own secure channel (see *Internal core links*).
- **Distributable block (= drone) = Executor + its BOTs/routines:** self-contained, runs on its own machine outside the core, **accepts no inbound**. **Blocks are the unit of distribution** — replicate blocks to scale and to tolerate failure (lose one block, the others continue). Each block's Executor **dials out** to the Scheduler.

Inside-out edge: **`GET`** polls **Locutus** (the public store on the WAN) for requests and enqueues them — decrypting only **inside the hidden core** (Locutus stays *blind*); **`SET`** pushes results back out to Locutus. The infrastructure never listens for inbound connections.

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

- **Block name (the drone's *designação*) = `BLAKE2(block's Noise static public key)`.** The name *is* the block's cryptographic identity, authenticated by the Noise `KK` handshake — a forged block name fails the handshake, so a self-reported name is never trusted.
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
- **Two failure layers — do not conflate:** *infra* failures (executor died, timeout) → handled by broker **lease/redelivery** (resilience = *regeneração*); *logical* failures (script errored / unmapped label) → handled by the **catch** chains.

## Workflow editor (authoring tool)

- **PySide6 desktop app on Linux** — the authoring tool for routines. The artifact it edits is a **workflow** = the activity-tree template.
- **Structured canvas** (Nassi is inherently structured — no free-floating arrows; flow is contiguous boxes + nesting). Built on **`QGraphicsView` + `QGraphicsScene`**, each node type a `QGraphicsItem` subclass: action = box, decision = downward triangle + columns, loop = container box wrapping the inner diagram, block = vertical stack. The user **inserts/snaps blocks** (no free drawing); the canvas auto-lays-out and is **just the render of the activity tree**, so it stays always-valid and **serializes directly to the template** (one visual block = one tree node).
- In a workflow the user defines **activities**; each activity has a rich, user-defined schema — **fields, attributes, requirements, APIs, etc.** — plus the BOT (`bot_ref`) it runs and its parameters/input. The schema is **auto-populated from the project manifest**; the user supplies/overrides values.

## Secure channels

All channels use a **custom protocol over a raw TCP stream socket** (`SOCK_STREAM`, *not* `SOCK_RAW`) — no HTTP or other classic application protocol. There is **no TLS**; the handshake/encryption **copies the Noise Protocol Framework** (proven design, implemented by us over our own framing). Primitives: **X25519 / ChaCha20-Poly1305 / BLAKE2s** (all non-NIST), from an audited reproducible-build library.

### External channel — Executor ↔ Scheduler (the exposed link)

This is the **single exposed/"vulnerable" link** (Executor in a block, on a different machine, dialing the Scheduler in the core) — and it is now **location-hidden over Tor** (see *Transport* below), so there is no public IP/port to find.

- **Pattern: Noise `KKpsk0`** → suite `Noise_KKpsk0_25519_ChaChaPoly_BLAKE2s`.
  - **`KK`** = both parties' static public keys are known in advance, **provisioned physically (out-of-band)** — this is what "physical key exchange" means. No in-band key negotiation, removing the over-the-wire MITM surface.
  - **`psk0`** = an additional pre-shared key, also provisioned physically, mixed in at the start (belt-and-suspenders auth).
  - Initiator = **Executor** (dials out); Responder = **Scheduler**.
  - Ephemeral keys per session → **forward secrecy**. Transport uses ChaCha20-Poly1305 with a per-direction **counter nonce** (always unique → also anti-replay) and the Poly1305 tag for per-message integrity.
- **No cleartext fingerprint:** no magic header — a Noise handshake opens with a random-looking ephemeral key, so the wire is not trivially DPI-identifiable. The **protocol version goes in the Noise `prologue`** (authenticated in the handshake hash, never sent in clear).

#### Transport: over Tor (the *subspace channel*) — adopted

The external channel rides **inside the Tor network** (onion routing), not the clearnet:

- **Scheduler = Tor v3 onion service.** Drones (Executors) dial the `.onion`; the Scheduler's IP is never revealed. **No clearnet listening port** — inbound arrives via Tor's rendezvous, so this still honours *no inbound toward the WAN* (there is no public IP/port to scan or raid). Location-hiding the core directly blunts the "single point of surveillance/coercion": you cannot raid a core you cannot locate.
- **Onion client authorization** — only provisioned drones hold the descriptor's client-auth key, so unauthorized parties cannot even reach the rendezvous. This sits *under* Noise `KKpsk0`: Tor gets you to the onion; Noise authenticates the actual Scheduler static key + the drone + mixes the PSK. Defense in depth — neither layer is trusted alone.
- **Noise runs over Tor's SOCKS5** — the raw `SOCK_STREAM` connects through Tor's SOCKS proxy to the `.onion`; framing and primitives are unchanged. (Manage the onion service / circuits with `stem`.)
- **Drones are Tor clients** — their IPs are hidden from the core and from observers; the metadata/traffic-analysis surface shrinks on both ends.
- **Nation-state caveat:** the adversary may *block* Tor → plan for **bridges + pluggable transports (obfs4 / meek)** so a drone behind hostile networking can still reach the rendezvous. Cover traffic / timing defenses remain a redesign item.
- **Scope:** Tor is for this exposed subspace channel. **Internal core links stay local** (NNpsk0 over the core's own network, not Tor). The GET/SET public-store polling *should* also go over Tor (hides that the core is fetching) — recommended extension.

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

**Relation to the Borg thesis:** the design adopts a **hidden Queen, not a blind router** (see *Filosofia Borg → A Rainha*). So this redesign's headline **blind-router / E2E-to-executor** idea is **deliberately NOT adopted for content**: the Queen (Broker+Scheduler) reads the request in order to orchestrate it. What *is* taken from here: **location-hiding** (Tor — adopted), **distribution / no-SPOF**, the **ephemeral midwife**, **idempotency**, and **Locutus as a blind edge**. **Network anonymity is partly settled:** the subspace channel over Tor (onion service + client auth) is **adopted** (see *Secure channels → Transport*); cover traffic / stem-and-fluff timing defenses stay open. The other redesign items remain per-item pending.

## Guidance for future work

The first substantive changes will define the project's conventions. As they land:

- Record the chosen language(s), framework, package manager, and the build/lint/test commands here.
- Replace the "Project status" note once real code exists.
- Keep terminology consistent: **Scheduler (Escalonador)**, **block** (= Executor + BOTs unit; Borg **drone**), **BOT** (= a project), **script**, **`bot_ref`** (assinatura do projeto + assinatura do script), **occurrence (ocorrência)**, **exigência** (hardware requirement), **quadrante** (= outermost unit; a full instance of the architecture), **subspace relay** (= inter-quadrante link; blind dead drop between Queens, implemented on `bdd`).
- Borg vocabulary (see *Filosofia Borg*): **drone** (= block), **assimilação** (provisioning payload; model B = key embedded in payload), **designação** (= `block_name`), **regeneração** (= lease/redelivery), **canal sub-espacial** (= external Executor↔Scheduler channel, carried over Tor), **Rainha** (= Broker + Scheduler, the central orchestrating mind — kept but **hidden, not blind**; "Rainha escondida"), **Locutus** (= public store, the Queen's *blind mouthpiece* on the WAN).
