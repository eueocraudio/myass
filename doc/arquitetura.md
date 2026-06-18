# Arquitetura do myass (estado atual)

Desenho autoritativo da arquitetura **como está implementada e implantada**.
Para o detalhe de cada decisão de design, ver `../CLAUDE.md`.

## Visão geral

O myass é uma plataforma de orquestração que roda na infra privada do dono. A
metáfora é o coletivo Borg: existe uma **Rainha** (a mente que lê o pedido e
dirige os drones), mas ela é **escondida** (atrás do canal Noise, sem face na
WAN), **cega para fora** (sua única face pública é o **Locutus**, que só vê
ciphertext) e **distribuída** (estado no MongoDB).

Três zonas: o **navegador** do usuário, o **Locutus público** (host descartável)
e a **zona de confiança** (LAN fechada) com a Rainha + drones.

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  WAN / INTERNET PÚBLICA                                                                ║
║                                                                                        ║
║   👤 Navegador (SPA)                              ☁ Locutus  (hosting PHP+MySQL)        ║
║   ┌──────────────────────────────┐               ┌──────────────────────────────────┐ ║
║   │ index.html + jQuery (local)   │   HTTPS       │ index.php — blob store 64-hex     │ ║
║   │ app.js (módulo)               │◀═════════════▶│  GET ?wait=N (long-poll)/PUT/DEL  │ ║
║   │ myass-crypto.js — cifra E2E   │  só blobs     │  + serve a SPA estática           │ ║
║   │ (ChaCha20; chave nunca sai)   │  opacos       │  MySQL via 127.0.0.1 (foge do     │ ║
║   │ nome.chave →                  │               │  teto de conexões remoto)         │ ║
║   │  PUT request · lê catálogo/   │               │  tabela blobs (ciphertext) —      │ ║
║   │  ocorrências/resposta (E2E)   │               │  servidor CEGO ao conteúdo        │ ║
║   └──────────────────────────────┘               └──────▲────────────────┬───────────┘ ║
╚══════════════════════════════════════════════════════════╪════════════════╪════════════╝
                                       GET (long-poll ~20s)  │   SET (por evento)
                                       puxa REQUEST           │   publica RESPOSTA +
                              ── só SAI para a WAN ───────────┘   CATÁLOGO + ÍNDICE/
                                 (nunca escuta)            │      DETALHE de ocorrências
╔═════════════════════════════════════════════════════════╪══════════════════════════════╗
║  ZONA DE CONFIANÇA — LAN fechada   (sem entrada vinda da WAN)                            ║
║                                          ┌───────────────┴──────────────────────────┐   ║
║                                          │        myass-core  —  a RAINHA            │   ║
║                                          │  EDGE GET/SET · registro de clientes +    │   ║
║                                          │  autorização · BROKER (MEM×CPU + ring +   │   ║
║                                          │  Mongo) · SCHEDULER (lease/regeneração) · │   ║
║                                          │  motor WORKFLOW (Nassi) · publish_registry│   ║
║                                          │  escuta Noise KKpsk0 :8400 (só na LAN)    │   ║
║                                          └──────▲────────────────▲──────────┬────────┘   ║
║                         Noise KKpsk0 (publicador)│   Noise (executor)│       │ Mongo      ║
║              ┌───────────────────────────────┐  │   ┌──────────────┴──┐   ┌─┴──────────┐ ║
║              │ 🖥 madmin (PySide6)             │──┘   │ myass-drone      │   │ MongoDB    │ ║
║              │  publica BOT/workflow          │      │ (block)          │   │ broker/    │ ║
║              │  cria/edita CHAVES (nome.chave)│      │ Executor + BOTs  │   │ leases/    │ ║
║              │  acompanha ocorrências         │      │ disca p/ a Rainha│   │ occurrences│ ║
║              └────────────────────────────────┘      │ roda bot_cve     │   │ /clients/  │ ║
║                  (NÃO fala com o drone)               │ egress via Tor   │   │ audit +    │ ║
║                                                       └──────────────────┘   │ GridFS     │ ║
║              ┌────────────────────┐                  (NÃO aceita entrada)    └────────────┘ ║
║              │ Tor (onion/egress) │                                                         ║
║              └────────────────────┘                                                         ║
╚═══════════════════════════════════════════════════════════════════════════════════════════╝

  madmin e drone são PEERS DISTINTOS que DISCAM para a Rainha (:8400) — nunca um para o
  outro. O papel (publicador vs executor) vem do handshake Noise (estática+PSK), nunca
  auto-reportado.
```

## Componentes

| Componente | Onde | Papel |
|---|---|---|
| **Navegador (SPA)** | máquina do usuário | informa `nome.chave`; cifra/decifra **tudo** no browser (ChaCha20); deposita pedidos e lê catálogo/ocorrências/resposta como blobs E2E |
| **Locutus** | hosting público (PHP+MySQL) | armazém cego de blobs 64-hex (`GET ?wait=N`/`PUT`/`DELETE`) + serve a SPA; nunca lê conteúdo. MySQL acessado por `127.0.0.1` |
| **myass-core (Rainha)** | zona de confiança | EDGE (GET/SET) + registro de clientes + autorização + BROKER + SCHEDULER + motor de WORKFLOW + registro de publicação. Escuta Noise só na LAN |
| **myass-drone (block)** | zona de confiança / LAN | Executor + BOTs; disca para a Rainha, puxa trabalho, roda scripts; egress via Tor |
| **madmin** | máquina do admin | painel PySide6: publica BOTs/workflows, cria/edita chaves, acompanha ocorrências |
| **MongoDB** | junto da Rainha | lastro: broker, leases, ocorrências, clientes, auditoria, GridFS (projetos/dados) |
| **Tor** | junto da Rainha | serviço onion (WAN) + egress dos BOTs |

## Fluxos

**Usuário cria ocorrência → recebe resultado:**
```
browser ──PUT request selado──▶ Locutus[a-req]
core EDGE-GET (long-poll ~20s) ──puxa──▶ decifra ──▶ motor.start ──▶ broker
        ──▶ drone (Noise, puxa WORK) ──▶ executa ──RESULT──▶ scheduler ──▶ motor
core EDGE-SET (por evento) ──publica──▶ Locutus[a-resp] + [a-occ-índice] + [a-occ-detalhe]
browser ──lê/decifra──▶ lista (ordem de chegada DESC) + detalhe (Nassi colorido) + PDF inline
```

**Admin cria uma chave de cliente:**
```
madmin ──Noise(publicador)──▶ Rainha.create_client ──▶ Mongo(clients)
                              ──▶ core EDGE-SET ──publica catálogo selado──▶ Locutus[a-cat]
```

## Endereços de blob (derivados do segredo do cliente, BLAKE2s)

Cada cliente tem um segredo de 32 bytes; dele derivam endereços/​chaves de
dead-drop independentes (o servidor não correlaciona):

| Slot | Quem escreve | Quem lê |
|---|---|---|
| `a-req` (request) | navegador | core GET (long-poll) |
| `a-resp` (response) | core SET | navegador |
| `a-cat` (catálogo) | core SET (ao criar/editar chave) | navegador |
| `a-occ` (índice de ocorrências) | core SET (criar/concluir) | navegador |
| `a-occ-detalhe` (por `occ_id`) | core SET | navegador |

## Invariantes (por que é seguro)

- **Sem entrada na WAN.** A Rainha só **sai** (GET puxa / SET empurra no Locutus);
  só escuta Noise na **LAN fechada**. Drone e madmin **discam** para a Rainha;
  nenhum aceita conexão de entrada.
- **Locutus cego.** PHP/MySQL veem só blobs opacos; cifra/decifra **só** no
  navegador e dentro da Rainha (E2E ChaCha20). O host público é descartável.
- **GET por long-poll** (≈1 conexão por janela de ~20s) — não martela o MySQL
  (evita ban por conexões/hora). **SET por evento** — só conecta quando há o que
  publicar (resposta/catálogo/ocorrência); um único laço temporizado (catálogo,
  6h) é só rede de segurança contra o TTL do blob.
- **Autorização na Rainha.** A chave de cliente só executa workflow da sua
  allow-list (o muro real, independe do que a web mostra).
- **Identidade por hash de conteúdo** (BLAKE2): `block_name`, `bot_ref`
  (`project_hash`+`script_hash`), `template_hash`, `data_ref`. Tudo
  endereçado/verificado por conteúdo.
- **Primitivos não-NIST auditados:** X25519 / ChaCha20-Poly1305 / BLAKE2s
  (canal Noise `KKpsk0`/`NNpsk0`; borda do cliente ChaCha20; relé inter-quadrante
  X3DH).

## Inter-quadrante (subspace relay)

Quadrantes conversam Rainha-a-Rainha por um **dead drop cego** (o projeto `bdd`),
com **X3DH** por dentro (forward secrecy assíncrona) e transporte cego por fora.
Ver `../CLAUDE.md → Topologia → subspace relay`.

## Diagramas renderizados

- `diagrama-arquitetura-tecnico.svg`/`.png` — arquitetura técnica (Rainha
  escondida, Locutus, Tor, Noise, relé inter-quadrante).
- `diagrama-fluxo.svg`/`.png` — fluxo de execução.
- `diagrama-arquitetura.svg`/`.png` — versão simplificada (vocabulário antigo).
