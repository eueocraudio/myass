# CLAUDE.md

Este arquivo orienta o Claude Code (claude.ai/code) ao trabalhar com o código deste repositório.

## Estado do projeto

Implementação inicial em curso. Este documento é a especificação de arquitetura autoritativa; é autocontido e não depende do PDF fundador.

**Convenções DEFINIDAS:** tudo em **Python** (alvo 3.14; sem containers/stacks web). Layout `src/myass/`, testes com **`unittest`** da stdlib em `tests/`, `pyproject.toml` (setuptools), `install.sh`. Dependência runtime atual: `pymongo` (lastro do broker); `mongomock` só para teste. Rodar a suíte: `PYTHONPATH=src python3 -m unittest discover -s tests` (ou `./install.sh`).

**Já implementado:**
- **broker** em `src/myass/broker/` — `classes.py` (tabela MEM×CPU: `classify`/`eligible_classes`), `ring.py` (ring buffer W/R), `store.py` (lastro `pymongo` + `requeue` para a regeneração), `broker.py` (enqueue/dequeue + carga preguiçosa do ring, ≤1 carga em voo por nó, warm-up na partida, `requeue`).
- **scheduler** (fatia *despacho + lease/regeneração*) em `src/myass/scheduler/` — `states.py` (máquina de estados da atividade), `store.py` (`LeaseStore`: leases + inventário + auditoria no Mongo, stateless-sobre-MongoDB), `scheduler.py` (`hello`/`request_work`/`beat`/`result`/`release`/`reap`; lease renovado por beat, redelivery por expiração, RESULT idempotente "primeiro vence", `timeout_total`, `max_tentativas`→falha lógica; o encadeamento de workflow se pluga via `on_complete`/`on_logical_failure`). **Falta a fatia do motor de workflow Nassi** (árvore, cursor, decision/loop/catch).
- **borda do núcleo (GET/SET)** em `src/myass/edge/` — `crypto.py` (AEAD ChaCha20-Poly1305 da lib `cryptography`; segredo de 32 bytes por cliente → chaves+endereços de dead drop derivados por BLAKE2s, padrão cego), `locutus.py` (`LocutusStore`: `MemoryLocutus` + `HttpLocutus` banal HTTPS), `registry.py` (`ClientRegistry` + `SeenRequests`: dedup de `request_id` no Mongo), `gateway.py` (`Gateway`: **GET** = `poll()` puxa/decifra/dedup/entrega via `on_request`; **SET** = `send_response` cifra e empurra). Sem conexão de entrada. Falta: laço de polling periódico e transporte Tor real do `HttpLocutus`.
- **executor (drone)** em `src/myass/executor/` — `workdir.py` (workdir efêmero modo 700 no tmpfs, `cleanup_workdir` no finally, `sweep_orphans` na partida; workdir LUKS para `workdir_mb` é ponto de extensão), `dataplane.py` (tradução `$file`↔`$data`, `data_ref=blake2:…`, `DataStore`/`MemoryDataStore`, verificação de hash + bloqueio de path traversal), `runner.py` (`ActivityRunner`: contrato Executor↔script SEM sandbox — mkdtemp → input.json → spawn com stdin `{workdir}` → exit 0/≠0 → output.json → rmtree; cancelamento via `cancel_event`), `agent.py` (`ExecutorAgent`: **laço de protocolo** — disca pelo transporte plugável, handshake KKpsk0, `HELLO`, `WORK_GET`→spawn→`WORK_BEAT`→`RESULT`, reconexão por backoff; `Resolver`/`MappingResolver` injetável), `project.py` (**gestão de projeto/venv**: `tree_hash`/verificação, `pack`/`extract` defensivo `filter='data'`, `ProjectCache` imutável `~/.myass/projects|envs/<hash>/` com venv `pip --require-hashes`, `ProjectResolver` que implementa `Resolver` baixando via `Source` e recomputando o hash do entrypoint antes do spawn; `DirSource` local). **Fonte de rede sobre o fio:** `agent.py` traz `WireSource` (PROJECT_GET→tar) e `WireDataStore` (DATA_PUT/DATA_GET content-addressed); o runner foi separado em `prepare`/`execute`/`collect` para o plano de dados usar o canal **só no laço principal** (fora da thread do filho — sem contenção com os beats). O servidor (`scheduler/server.py`) serve PROJECT_GET/DATA_GET/DATA_PUT do GridFS/`CoreDataStore`. Coberto por `test_wire_transfer` (drone baixa o projeto e roda; DATA round-trip). **Executor sem pendências.**
- **motor de workflow Nassi** em `src/myass/workflow/` — `template.py` (forma canônica, `template_hash`, navegação por path), `engine.py` (`WorkflowEngine` + `OccurrenceStore`): executa a árvore **block/action/decision/loop** com **catch**; cria a ocorrência (árvore de frames com cursor + `prev`, persistida no Mongo, lock por ocorrência), dirige o "tick" a cada RESULT, faz **fan-out/join** nos loops, roteia decisions por label, e **borbulha erros** pela cadeia de catch (`ignorar` engole / substitui item no join; `subir` propaga; sem handler → ocorrência falha). Pluga-se nos callbacks do Scheduler (`on_scheduler_complete`/`on_scheduler_failure`); resolve refs de dados (`$prev`/`$item`/`$input`/`$node`). Coberto por `test_workflow` (incl. o showcase com a forma do `bot_cve`: Task01→loop(Task03..08, Task06 catch ignorar)→join→Task09→Task10). **Falta:** disposição de catch `tratar` (handler como atividade) e persistência stateless multi-réplica (hoje lock in-process).
- **protocolo de aplicação** em `src/myass/proto/envelope.py` (`header_len`+JSON+corpo; tipos HELLO/WORK_GET/WORK/NO_WORK/WORK_BEAT/BEAT_ACK/WORK_CANCEL/RESULT/RESULT_ACK/WORK_RELEASE/PING/PONG) e o **servidor da Rainha** em `src/myass/scheduler/server.py` (`SchedulerServer`: aceita conexões, `respond_trial` descobre o drone pela estática+PSK que casa no handshake — identidade do handshake, nunca auto-reportada —, roteia o protocolo para `hello`/`request_work`/`beat`/`result`/`release`). O ciclo enqueue→dispatch→executa→RESULT→conclui é coberto por `test_protocol_e2e` (drone real ↔ Noise ↔ Scheduler ↔ broker, in-process).
- **canal sub-espacial (Noise)** em `src/myass/noise/` — `primitives.py` (X25519/ChaCha20-Poly1305/BLAKE2s + HKDF/HMAC, todos da lib `cryptography`), `symmetric.py` (CipherState/SymmetricState do framework Noise), `handshake.py` (`HandshakeState` do padrão **`KKpsk0`**: `Noise_KKpsk0_25519_ChaChaPoly_BLAKE2s`, com `e` fazendo MixKey em modo PSK), `framing.py` (records sobre TCP: `real_len`+padding até 256, chunks ≤65280, blocos `blk_len`), `channel.py` (`NoiseChannel` + `initiate`/`respond`/`respond_trial` + **transporte plugável**: `connect_direct` LAN/localhost, `connect_tor` SOCKS5, `connect(endpoint)` pela topologia, `listen`), `tor.py` (**serviço onion Tor v3** via `stem`: `OnionService` publica um HS efêmero `onion:porta→127.0.0.1:local` com **client-auth v3**, `.onion` estável por chave persistida; `gen_client_auth`/`client_auth_line` para os pares de auth dos drones). Dep opcional `stem` (extra `tor`); partes puras em `test_tor`, integração com `skipUnless` (Tor real).
- **cliente (as duas partes)** —
  - *Parte I, núcleo+lógica:* registro de publicação em `src/myass/publish/registry.py` (`PublishRegistry`: append-only, revalida o tar contra o `project_hash`, valida manifesto, imutabilidade `(nome,versao)→hash`, GridFS; `is_approved`/`catalog`), roteamento por **papel** no `scheduler/server.py` (executor vs **publicador**; `DENIED` cross-role), e `src/myass/client/admin.py` (`AdminClient`: `publish_bot[_dir]`/`publish_workflow`/`catalog`/`start_occurrence`/`list_occurrences`/`environment` sobre o canal Noise). Mensagens em `proto/envelope.py` (PUBLISH/CATALOG_GET/START_OCCURRENCE/LIST_OCCURRENCES/ENVIRONMENT + acks). Coberto por `test_admin_e2e`.
  - *Parte I, GUI:* `src/myass/client/admin_gui.py` (PySide6 — publicar/catálogo/ocorrências/ambiente; autoria por JSON do template; canvas Nassi gráfico é refinamento). Dep opcional `PySide6` (extra `admin`). Smoke em `test_admin_gui` (offscreen).
  - *Parte II, web pública:* `client/web/` (PHP+MySQL) — `index.php` é o **Locutus blob-store puro** (`GET`/`PUT`/`DELETE` de blobs 64-hex, compatível com o `HttpLocutus`), `db/schema.sql`, `.htaccess`, `index.html` + `js/app.js` + **`js/myass-crypto.js`** (gêmeo de `edge/crypto.py` via `@noble`; **cripto client-side, PHP cego**). **O catálogo também é blob E2E** (decifrado no JS) — o PHP fica cego até dos rótulos, superando o trade-off de metadado. Compat Python↔JS validada (mesmos endereços + decifração cruzada). Deploy FTP via `.env`.
- **núcleo montado** em `src/myass/core/core.py` (`Core` + `ReplyStore`) — liga a borda ao motor: `gateway.on_request` recebe o pedido estruturado do cliente (`{action:"start_occurrence", workflow_hash, inputs}`), valida o workflow no registro e chama `engine.start`; guarda `occurrence_id → (client_id, request_id)` e, quando o motor sinaliza fim (`engine.on_finished`), devolve o resultado pelo SET. **Slot de resposta é write-once** — não há "running" intermediário; o cliente faz polling até a resposta final. Coberto por `test_core_e2e` (cliente→GET→ocorrência→SET→cliente). **Pedido em linguagem natural (drone VAI) implementado:** action `interpret` → o Core roda o workflow interpretador (BOT VAI, com o catálogo nos inputs) → o VAI devolve o PLANO `{workflow_hash, inputs}` → a Rainha **valida no registro** e só então dispara o workflow real (saída do VAI é sugestão; hash não aprovado não executa). Coberto por `test_vai_e2e`.
- **operação / deploy** em `src/myass/ops/` — `provision.py` (`provision_quadrante`: a parteira que cunha a estática do Scheduler + par X25519/PSK por drone e admin + segredo por cliente, e emite as configs JSON do núcleo/drones/admins/clientes com a tabela de peers e papéis), `nodes.py` (`CoreNode` monta e fia o núcleo inteiro a partir da config — stores Mongo/GridFS, broker, Scheduler+motor de workflow com os callbacks ligados, registro, borda+Core, servidor Noise, laços de reap/poll; `DroneNode` monta o `ExecutorAgent`), `cli.py`/`__main__.py` (`python -m myass.ops provision|core|drone|admin`). O `install.sh` instala tudo (apt: tor/MongoDB/MariaDB+PHP/Qt; pip3: o pacote + extras `test`/`admin`/`tor`). **Quadrante inteiro montado e testado fim-a-fim em `test_quadrant_e2e`** (in-process), e **rodado sobre INFRA REAL** via `examples/run_real_quadrant.py` (MongoDB real + núcleo e drone como **processos separados** + sockets TCP reais + GridFS real: admin publica → inicia ocorrência → drone baixa o BOT por `PROJECT_GET` e executa → resultado volta).
- **camada de armazenamento** em `src/myass/storage/` — `db.py` (conexão Mongo central via env `MYASS_MONGO_URI`/`MYASS_MONGO_DB` + `open_stores`: fia todos os stores do núcleo sobre um database), `blobstore.py` (`BlobStore`: `GridFSBlobStore` produção/`MemoryBlobStore` teste; `CoreDataStore` content-addressed `data_ref` com dedup + integridade na leitura — o **lastro GridFS** de projetos e artefatos do plano de dados, que passam de 16 MB). Servidor `mongod`/replica set é dependência operacional (testes usam mongomock; GridFS real é teste condicional com `skipUnless`).
- **subspace relay (inter-quadrante)** em `src/myass/relay/` — `x3dh.py` (acordo **X3DH** Rainha↔Rainha: `Identity` (IK_dh X25519 + **IK_sig Ed25519** — divergência da spec: XEd25519 não está em lib auditada, então Ed25519 dedicado p/ assinar), `PrekeyVault` (SPK assinada + lote de OPK), `bundle`/`verify_bundle`, `agree_sender`/`agree_receiver` com `SK = HKDF-BLAKE2s(salt=PSK, DH1‖DH2‖DH3‖[DH4])`, seal/open ChaCha20-Poly1305; OPK de uso único), `relay.py` (`SubspaceRelay`: endereçamento por `channel`/`prekey_channel` BLAKE2s dos `quadrante_id`s, `RelayTransport` (`MemoryRelayTransport` + adapter `bdd` futuro), fluxo `publish_prekeys`/`send_request`/`receive_requests`/`send_response`/`receive_responses` com anti-replay contador+`request_id`). Coberto por `test_relay`. **Adapter sobre o `bdd` real:** `bdd_transport.py` (`BddRelayTransport`: mapeia os `channel`s do relay para o `bdd` via um `client_factory` desacoplado — o `DeadDropClient` do projeto `bdd`); **validado de ponta a ponta sobre um `bdd` real (HTTPS)** — Rainha↔Rainha, X3DH+Noise por dentro, transporte cego por fora. Pendente só: cover traffic/metadados (pesquisa).
- **canal de erros** em `src/myass/errlog.py` (`ErrorRing`) — *decisão do dono:* anel circular de **ponteiro único** (só escrita), capacidade 1000, que **sobrescreve** as posições mais antigas ao dar a volta (nunca cresce, sem limpeza). `record(item)` grava; `Print()` despeja **de trás para frente** (erro mais recente primeiro). Instância global de processo + helpers de módulo. Distinto do ring W/R do broker (lá os itens são *consumidos*; aqui são *sobrescritos*). **Plugado:** o Scheduler registra cada `FALHA_LOGICA`; o broker registra exceções da thread carregadora (que sumiriam silenciosamente).

Coberto por `tests/test_{classes,ring,broker,scheduler,errlog,edge_crypto,edge_gateway,executor,noise,protocol_e2e,project,workflow,storage,admin_e2e,admin_gui,core_e2e,wire_transfer,tor,quadrant_e2e,relay,vai_e2e}.py` (171 testes).

**BOT de exemplo:** `bots/bot_cve/` — reescrita do `bot_cve` legado na arquitetura nova (extrai CVEs → enriquece com MITRE + CISA KEV + exploit-db + refs + NER → PDF). Usa o **contrato novo** dos scripts (stdin `{workdir}` + input/output.json), `manifest.json`/`workflow.json` (template Nassi) gerados por `build.py` com hashes BLAKE2, e um **plano de teste sem Rainha** (`test/run_pipeline.py`) que encadeia tudo via subprocess (cursor/loop/join/catch simulados). Dependência zero (PDF em `lib/minipdf.py` stdlib; spaCy é capacidade opcional com fallback). É o alvo concreto do motor de workflow Nassi + canal de dados.

### Artefatos de referência em `doc/`

- `doc/diagrama-arquitetura.svg` / `.png` — arquitetura renderizada para amigos (vocabulário simplificado; anterior aos refinamentos Rainha-escondida/Tor/quadrante).
- `doc/diagrama-arquitetura-tecnico.svg` / `.png` — arquitetura técnica atual: o quadrante, a Rainha escondida, o Locutus, o canal sub-espacial sobre Tor, os padrões Noise e o link inter-quadrante (subspace relay).
- `doc/diagrama-fluxo.svg` / `.png` — diagrama de execução/fluxo.
- `doc/myass-apresentacao.pdf` / `.html` — apresentação do projeto para amigos.
- `doc/analise-tanenbaum.md`, `doc/analise-monero.md`, `doc/redesign-minimum-knowledge-core.md` — análises cruzadas teóricas e o redesign proposto (ver *Análise teórica* abaixo).

## O que é o projeto

**myass** ("Assistente Pessoal Local") é uma **plataforma de orquestração** que roda inteiramente na infraestrutura privada e fechada do próprio usuário (nenhum dado pessoal enviado a qualquer nuvem). Seu trabalho é **orquestrar a execução de rotinas, incluindo rotinas de IA** — coordenando modelos especializados de "Vertical AI" (VAI) e rotinas comuns de automação, em vez de depender de uma única IA geral.

## Princípio orientador: sempre o caminho mais seguro

**Sempre escolha a opção mais segura, mesmo que seja mais difícil ou dê mais trabalho.** Quando segurança colide com conveniência, esforço ou simplicidade, segurança vence por padrão — proponha e construa a opção mais forte sem que peçam, e só recue se o dono decidir explicitamente o contrário.

### Modelo de ameaça

O adversário é um **Estado-nação de amplo alcance** ("o governo tem acesso a tudo"); o myass é um sistema pessoal de privacidade / anti-vigilância. Consequências que moldam cada decisão:

- **Primitivos não-NIST** são preferidos (a pilha da comunidade de privacidade): X25519, ChaCha20-Poly1305, BLAKE2 — todos de djb/pares, usados por Signal/WireGuard/Tor.
- **Primitivos criptográficos têm de ser implementações auditadas, de build reprodutível — nunca feitos à mão.** Uma cifra escrita por nós vaza os canais laterais que um adversário estatal explora. Escrever o *protocolo/enquadramento* à mão é aceitável e proposital; escrever os *primitivos* à mão, não.
- Os riscos reais em nível estatal vivem em **endpoints, análise de metadados/tráfego, manuseio de chaves e acesso físico** — não na escolha da cifra.

## Requisitos arquiteturais rígidos

Restrições firmes — qualquer design ou implementação deve satisfazer as três:

- **Distribuído.** O trabalho roda em múltiplos nós, não numa máquina só.
- **Resiliente a falhas.** Tolerar falha de nó/componente e continuar operando — sem ponto único de falha; rotinas têm de sobreviver e se recuperar.
- **Sem conexões de entrada (em direção à WAN).** Nada pode iniciar uma conexão da Internet externa para dentro da infraestrutura. Toda conexão nasce de dentro para fora; trabalho externo é *puxado* pelos nós internos (polling), nunca empurrado para dentro. Nenhuma porta/serviço de escuta exposto para fora.

## Decisões de escopo (explicitamente fora)

- **Sem RabbitMQ (ou qualquer broker de terceiros).** O mecanismo de coordenação continua sendo uma fila/broker, mas é o **broker próprio do projeto, implementado como serviço em Python** (ver *Broker* abaixo).
- **Sem HSM.** Designs de Hardware Security Module não são implementados.
- **Sem estudo de caso de segurança/CVE.** Fora de escopo.

## Filosofia Borg: a Rainha escondida

A metáfora organizadora do projeto é o coletivo Borg. O coletivo **tem** uma Rainha — mas ela é **escondida, jamais alcançável de fora.** (Isso refina o slogan anterior "coletivo sem Rainha": *existe* uma Rainha; simplesmente não há Rainha que o adversário consiga **achar ou alcançar**.) Adotado como filosofia orientadora.

**Tese:** *o prêmio do adversário é uma Rainha que ele consiga achar e coagir.* O coletivo sobrevive a um Estado-nação garantindo que a mente central nunca seja localizável ou alcançável a partir da WAN: sua única face para o mundo é um **porta-voz cego (Locutus)**, ela mesma vive **escondida** atrás do canal sub-espacial Tor, e é **distribuída** para não ser ponto único de falha. Ela pode *saber* — só não pode ser *alcançada*.

### Vocabulário (Borg ↔ arquitetura)

- **drone = block** (Executor + BOTs) — a unidade substituível e especializada do coletivo; a unidade de distribuição.
- **designação = `block_name` = `BLAKE2(pubkey estática)`** — a identidade criptográfica do drone (ver *Identidade & rastreabilidade*).
- **assimilação = o payload de provisionamento** que ergue um drone novinho (ver abaixo).
- **regeneração = lease/redelivery do broker** — um drone morre, seu trabalho volta para a fila e é reentregue (a camada de falha de *infra*).
- **adaptação = cadeias de catch + redelivery** — o coletivo absorve a falha e segue funcionando.
- **canal sub-espacial = o link Executor↔Scheduler, transportado sobre Tor** — o link de localização oculta entre drones e o núcleo (ver *Canais seguros*).
- **Rainha = Broker + Scheduler** — a mente orquestradora central: lê o pedido do cliente e dirige os drones. Escondida, não cega (ver abaixo).
- **Locutus = o armazém público** — o *porta-voz cego* da Rainha: a ponte de conversa na WAN entre um cliente em linguagem humana e a Rainha escondida. Guarda só ciphertext opaco. (O "Locutus invertido": o Locutus do cânone conhecia a mente do coletivo e por isso a condenou — o nosso não sabe nada, então capturá-lo rende um balde de bytes opacos.)

### A Rainha — escondida, não cega (postura adotada)

**Decisão do dono:** o coletivo tem uma Rainha — **a Rainha = Broker + Scheduler** — a mente central que lê o pedido do cliente e orquestra os drones. Ela **não** é um roteador cego: não se orquestra o que não se pode ler, e transformar um pedido em linguagem humana em atividades/`bot_ref`s é, inerentemente, um ato de quem sabe. (Divergência deliberada em relação à ideia de roteador cego do redesign — ver *Análise teórica*.)

Como ela *sabe*, é protegida por **três muros** em vez de pela cegueira:

1. **Mascarada** — sua única face para a WAN é o **Locutus** (o armazém público), que é *cego*. Capturar o porta-voz → blobs opacos, não a mente. `GET`/`SET` decifram só **dentro** do núcleo escondido, nunca no Locutus.
2. **Escondida** — ela vive atrás do canal sub-espacial Tor (onion de localização oculta); não há IP/porta para escanear ou invadir. Não se invade uma Rainha que não se consegue localizar.
3. **Distribuída** — replicada/stateless-sobre-MongoDB para não ser ponto único de *falha* (o SPOF de Tanenbaum), ainda que permaneça ponto único de *conhecimento*.

**Risco residual, dito com honestidade:** uma Rainha *localizada e coagida* é o jackpot (conteúdo + auditoria + inventário). Esta postura se apoia fortemente no Tor + na cegueira do Locutus; é o trade-off escolhido (a orquestração centralizada em linguagem natural vale a pena), não um descuido.

- **Rainha-parteira efêmera — a estação de provisionamento** (cunha identidades de drone; ver assimilação). **Tolerada** porque é momentânea, não soberana: air-gapped, uso único por drone, não retém chaves após a cunhagem, nunca online. Uma parteira de um instante não é uma soberana.

**Interpretador de linguagem humana (DEFINIDO — decisão do dono): despachado a um drone VAI.** O interpretador é um BOT comum (publicado no registro, `bot_ref`, manifesto exigindo capacidade de VAI) — nenhum LLM dentro do núcleo; a interpretação é uma atividade como outra qualquer: o `GET` decifra o pedido → a Rainha enfileira a atividade *interpretar* com o texto como param → o drone VAI devolve o **plano** (qual workflow + params, ou pedido de esclarecimento) → a Rainha cria a ocorrência. **A saída do VAI é sugestão, nunca ordem:** a Rainha só agenda `bot_ref`/`template_hash` aprovados no registro de publicação — alucinação ou prompt injection no pedido não tem como executar hash não aprovado. Trade-off dito: o drone interpretador vê o conteúdo do pedido (como qualquer drone vê os params da sua atividade); a Rainha segue sendo o único ponto que vê tudo.

**Lastro físico do Locutus (DEFINIDO — decisão do dono): app web PHP + MySQL, deploy banal por FTP.** Concretizado como a **interface web pública** (ver *Cliente — duas partes → Parte II*): um projeto PHP com as APIs de acesso + um **MySQL público** como banco, publicado por FTP (credenciais em `.env`). A segurança não depende do hosting: o conteúdo é E2E (ChaCha20, ver *Borda do cliente*) e o servidor é cego ao **conteúdo** por construção (catálogo de workflows por cliente é metadado conhecido — trade-off em *Parte II*). O hosting é **descartável/substituível** (blobs efêmeros com TTL; trocar de provedor não custa nada). O provedor vê metadado de acesso (IPs de clientes, padrões), nunca conteúdo — aceito. Polling do núcleo: Tor preferencial, surface permitida (ver *Canais seguros → Transporte*).

### Assimilação (provisionar um drone) — modelo adotado

**Decisão do dono: o par de chaves é cunhado no provisionamento e embarcado no payload (assimilação de um disparo).** Rodar o payload transforma uma máquina nova num drone que já pode discar para fora e completar o handshake Noise `KK` — porque sua pubkey já foi registrada no Inventory no momento da cunhagem. (É o caminho da conveniência, escolhido deliberadamente em vez do caminho mais seguro "chave nasce no drone", então vem **acompanhado** das regras de endurecimento abaixo.)

O que o payload faz no alvo: checar a *exigência* de hardware; instalar o runtime do Executor + dependências fixadas **verificando hashes** (build reprodutível — senão você assimila um drone envenenado); instalar a chave privada estática X25519 embarcada + a pubkey estática do Scheduler + a PSK `KKpsk0`; computar sua **designação** `BLAKE2(pubkey)`; configurar o dial-out (sem porta de escuta — honra o *sem entrada*).

Como o payload **carrega um segredo** (chave privada estática + PSK), é material sensível; estas regras valem em conjunto:

1. **Uma chave por drone, nunca reutilizada** — cada payload é único; a designação é única.
2. **Estação de provisionamento offline / air-gapped, sob LUKS** — o único órgão que conhece brevemente chaves privadas (a Rainha-parteira efêmera).
3. **Payload de uso único e vida curta** — janela mínima se interceptado.
4. **No alvo:** mover a chave privada para LUKS / `chmod 600`; **destruir/zerar a mídia do payload** após a instalação.

**O vetor decorre por força:** como o payload carrega uma chave privada, ele viaja **out-of-band em mídia física (USB)** — nunca no armazém público em claro.

## Topologia

**Unidade mais externa — o quadrante.** Tudo abaixo (a borda da WAN / Locutus, o núcleo confiável / Rainha, e os blocks) vive dentro de uma caixa grande chamada **quadrante**. O sistema é composto de **muitos quadrantes**; um único quadrante é uma instância completa e autossuficiente da arquitetura aqui descrita. Renderizado em `doc/diagrama-arquitetura-tecnico.svg`.

**Comunicação inter-quadrante — o `subspace relay` (relé de subespaço), um dead drop cego de REQUEST/RESPONSE entre Rainhas (adotado).** O link entre quadrantes se chama **subspace relay** (coerente com Star Trek e com o *canal sub-espacial* intra-quadrante). Quadrantes conversam **Rainha-a-Rainha** (Rainha ↔ Rainha, plural) por um **dead drop cego** que guarda só ciphertext opaco: uma Rainha *deposita* um REQUEST, a Rainha parceira o *puxa*; RESPONSEs voltam pelo mesmo caminho. É o **Locutus entre Rainhas** — o mesmo padrão de dead drop cego da borda da WAN, aplicado entre núcleos. **Baseado em pull e transportado sobre Tor**, então honra o *sem entrada* e nunca revela a localização de um núcleo para o outro; a decifração só acontece dentro de cada núcleo escondido. Como o depósito é **assíncrono, store-and-forward**, os handshakes Noise interativos usados em outros lugares (`KK`/`NN`) **não** se aplicam.

  - **Implementação: o projeto `bdd` (Blind Dead Drop) em `../bdd`** — repo genérico próprio, consumido pelo myass (ver o `CLAUDE.md` dele). O `bdd` é um serviço HTTPS/HTTP em stdlib cujo **servidor é cego**: blobs opacos em endereços opacos de 64-hex; não consegue ler conteúdo nem ligar as duas partes/partes. Ele já modela exatamente o nosso formato — um **channel** (int) com duas **parts, `request` e `response`**, cujos endereços + chaves derivam de labels `HKDF` *diferentes* para o servidor não correlacionar — além de **long-poll** (`?wait=N`) para pull, **TTL buckets** para diluir metadado temporal, e um modo `--no-tls` pensado para rodar **atrás de um serviço onion Tor** (o conteúdo já é E2E). Ou seja, o depósito, o transporte Tor, a cegueira e os slots request/response estão **prontos** no `bdd`.
    - **Endpoint onion do `bdd` (estável):** `http://46xhzbennzgxolftzlufl27yzwx4gdfb3xmv5wsuw46tbd74tv6tbjad.onion:8081` (sem TLS — o conteúdo é E2E e o `.onion` é, ele próprio, a credencial de acesso).

  - **Camadas de cripto (DEFINIDO) — o `bdd` é o transporte cego burro; o myass é dono do E2E.** A cripto própria do `bdd` é simétrica (segredo-raiz de 32 bytes compartilhado → `HKDF-SHA256` → endereço por part + chave ChaCha20-Poly1305); o myass **não** depende dela para confidencialidade ou autenticação. Em vez disso, dois selos aninhados:
    1. **Interna (E2E do myass — a segurança que importa).** *Forma mínima de base (sem prekeys) — agora atualizada para o X3DH abaixo, que a supera no caminho de dados.* Cada REQUEST/RESPONSE é **uma mensagem Noise de uma via** entre as chaves X25519 **estáticas** das duas Rainhas — suíte **`Noise_Kpsk0_25519_ChaChaPoly_BLAKE2s`**, padrão **`K`** (as estáticas de ambas conhecidas de antemão, pré-trocadas **out-of-band** como no provisionamento de drone). A Rainha que deposita é iniciadora/remetente, a que puxa é respondedora/destinatária; REQUEST e RESPONSE são mensagens de uma via **independentes**, com os papéis trocados. Uma **PSK por par** (`psk0`) e um **efêmero novo por mensagem** entram na mistura. O **prologue** prende versão do protocolo + `quadrante_id` do remetente/destinatário + channel `bdd` + part (autenticado no hash do handshake, nunca em claro), pregando um blob ao seu slot pretendido. Os bytes Noise (`e_pub || ciphertext+tag`) são o payload opaco entregue ao `bdd`.
    2. **Externa (transporte cego `bdd`).** O `bdd` re-sela esse payload com a chave do channel num endereço não-correlacionável → cegueira do servidor + impossibilidade de ligar parts/partes. Se o segredo-raiz do `bdd` vazar, o atacante ainda só obtém ciphertext Noise.
    - **Primitivos seguem não-NIST de ponta a ponta na camada interna** (X25519 / ChaCha20-Poly1305 / BLAKE2s); o SHA-256 do `bdd` é então apenas metadado de transporte, não proteção de conteúdo — então a preocupação com hash NIST não se aplica ao conteúdo.
    - **Limite honesto de FS (confidencialidade grau 2 do Noise para padrões de uma via):** o efêmero por mensagem dá forward secrecy contra comprometimento da estática do **remetente**, mas **não** da estática do **destinatário** — a chave estática vazada de uma Rainha decifra todos os REQUESTs passados enviados a ela, e (KCI) permite a um atacante forjar mensagens *para* ela (a PSK também tem de ser roubada). Isso é inerente à entrega de uma via **quando o destinatário não contribui material de chave** — exatamente o que os prekeys X3DH (abaixo, adotados) corrigem. Dito, não escondido.
    - **Anti-replay / idempotência (Noise de uma via é, por si só, vulnerável a replay):** o payload autenticado carrega um **contador monotônico por direção** + um `request_id` único; o destinatário mantém uma marca d'água por remetente, rejeita `contador ≤ visto` (estilo key-image, cf. `doc/analise-monero.md`), e processa cada `request_id` **uma vez**. Os slots write-once + os TTL buckets do `bdd` são uma rede de segurança, não o mecanismo.
  - **Forward secrecy assíncrona VERDADEIRA — prekeys X3DH (ADOTADO; supera o Noise de uma via de base no caminho de dados).** O acordo de chaves da camada interna é o **X3DH** (Extended Triple Diffie-Hellman — o handshake assíncrono do Signal), adaptado a Rainha↔Rainha sobre o `bdd`. Mesmos primitivos não-NIST: DH X25519, assinaturas **XEd25519**, KDF **BLAKE2s**, AEAD ChaCha20-Poly1305. Compra autenticação mútua **e** FS *mesmo contra o comprometimento da chave de longo prazo do destinatário*, porque o destinatário pré-contribui aleatoriedade de uso único que depois destrói.
    - **Chaves.** Cada Rainha tem uma **chave de identidade** X25519 `IK` (sua identidade; `quadrante_id = BLAKE2s(IK_pub)`; pré-trocada out-of-band). O destinatário mantém ainda uma **signed prekey** `SPK` rotacionada (assinada sob `IK` via XEd25519 — um único par de chaves faz DH *e* assina) e um lote reabastecido de **one-time prekeys** `OPK[i]`.
    - **Bundle de prekeys — publicado num "prekey" part dedicado do `bdd`:** `{ IK_pub, SPK_pub, Sig_IK(SPK_pub), OPK_pub[i]+ids }`, o **bundle inteiro assinado sob `IK`**. Como `IK` é provisionada **fisicamente out-of-band**, o bundle é plenamente autenticado mesmo com o `bdd` cego/não confiável — o remetente verifica a assinatura contra a `IK` conhecida, então um relé cego não consegue substituir chaves (pior caso = DoS → fallback). Assinar a lista de OPK (além do X3DH clássico) fecha o vetor de troca de OPK num relé não confiável.
    - **Remetente, REQUEST A→B:** busca + verifica o bundle de B, escolhe um `OPK`, gera o efêmero `EK_A`; computa `DH1=DH(IK_A,SPK_B)`, `DH2=DH(EK_A,IK_B)`, `DH3=DH(EK_A,SPK_B)`, `DH4=DH(EK_A,OPK_B)`; `SK = HKDF-BLAKE2s(salt = PSK por par, ikm = DH1‖DH2‖DH3‖DH4, info = "myass/subspace-relay/x3dh/v1|<id_A>|<id_B>")` (a PSK-como-salt incorpora o reforço cinto-e-suspensório do `psk0`). Sela o REQUEST com ChaCha20-Poly1305 sob `KDF(SK,"req")`, AD = versão + `quadrante_id`s + channel + part + `opk_id` + contador. Payload `bdd` = `IK_A_pub ‖ EK_A_pub ‖ opk_id ‖ ciphertext` (depois re-selado pela camada externa do `bdd`).
    - **Destinatário B:** recomputa `SK` a partir das suas privadas + `IK_A`,`EK_A`, então **apaga `OPK_i`** (uso único) → REQUESTs passados permanecem secretos mesmo que `IK_B`/`SPK_B` vazem depois. Responde sob `KDF(SK,"resp")` — **sem um segundo X3DH** (B já tem `SK`): **um X3DH por par request/response**.
    - **Propriedades:** com um `OPK`, a FS vale contra o comprometimento de longo prazo de **ambas** as partes (a chave de uso único destruída); DH1/DH2 prendem ambas as identidades → autenticação mútua, resistente a KCI; **apagar o OPK também é forte proteção contra replay** do REQUEST (re-enviar um `opk_id` consumido → `SK` irrecuperável). O contador + `request_id` ainda protegem o RESPONSE e o fallback de OPK esgotado.
    - **Fallback (OPKs esgotados):** X3DH só com `SPK` (descarta DH4) → FS limitada pela rotação da `SPK`, não perfeita. B monitora e **reabastece** os lotes de OPK e rotaciona a `SPK` periodicamente (mantém a `SPK` privada antiga por pouco tempo para mensagens em trânsito, depois apaga). **Nunca reutilizar um `OPK`.**
  - **Endereçamento (DEFINIDO) — o `quadrante_id` determina os channels do `bdd` (decisão do dono).** O número do channel nunca chega ao servidor `bdd` (ele só vê o endereço 64-hex derivado), então codificar identidade no channel não vaza nada. **`channel(A→B) = int(BLAKE2s("myass/relay/ch|" + id_A + id_B))`**, par **ordenado**: REQUESTs de A→B na part `request` desse channel, RESPONSEs de volta na part `response`; B iniciando conversa usa `channel(B→A)` — cada direção com seu próprio par de slots, determinístico, **zero coordenação**. **Bundle de prekeys X3DH:** channel dedicado `BLAKE2s("myass/relay/prekey|" + id_B + id_A)` — B publica na part `request`, A lê. **Tabela de roteamento por Rainha, provisionada out-of-band** (junto das estáticas Noise + PSK): `quadrante_id → { endpoint onion do bdd, segredo-raiz do par, PSK, IK_pub }` — channels não constam, derivam dos ids.
  - **Ainda em aberto:** metadados inter-quadrante / cover traffic.

Dentro de um quadrante há duas zonas:

- **Núcleo confiável:** a borda `GET`/`SET`, o **broker** próprio em Python, o **armazenamento interno (MongoDB)** e o **Scheduler (Escalonador)**. O **broker + Scheduler juntos são a Rainha** — a mente orquestradora escondida (ver *Filosofia Borg*). Os links internos dentro do núcleo usam seu próprio canal seguro (ver *Links internos do núcleo*).
- **Block distribuível (= drone) = Executor + seus BOTs/rotinas:** autocontido, roda na própria máquina fora do núcleo, **não aceita entrada**. **Blocks são a unidade de distribuição** — replique blocks para escalar e tolerar falha (perca um block, os outros continuam). O Executor de cada block **disca para fora** até o Scheduler.

Borda de dentro para fora: o **`GET`** faz polling no **Locutus** (o armazém público na WAN) por pedidos e os enfileira — decifrando só **dentro do núcleo escondido** (o Locutus continua *cego*); o **`SET`** empurra resultados de volta ao Locutus. A infraestrutura nunca escuta conexões de entrada.

```
   WAN            │              NÚCLEO CONFIÁVEL
 ┌────────┐  pull │  ┌─────┐   ┌──────────┐   ┌─────────┐
 │ armazém│◀──────┼──│ GET │──▶│  BROKER  │◀─▶│ MongoDB │
 │ público│──────▶┼  └─────┘   │ (Python) │   └─────────┘
 └────────┘  push │  ┌─────┐   └────┬─────┘
      ▲           │  │ SET │◀───────┤
      └───────────┼  └─────┘   ┌────┴──────┐
                  │            │ SCHEDULER │
                  │            └────┬──────┘
                  │     Noise KKpsk0 │  ← Executores discam (link exposto)
                  │   ╔══════════════╪═══════════════╗
                  │ ┌─┴──────┐  ┌────┴───┐  ┌─────────┴┐
                  │ │ BLOCK  │  │ BLOCK  │…│ BLOCK     │  (Executor + BOTs;
                  │ │ Exec+  │  │ Exec+  │ │ Exec+     │   replique para escalar
                  │ │ BOTs   │  │ BOTs   │ │ BOTs      │   e tolerar falha)
                  │ └────────┘  └────────┘ └───────────┘
```

## Identidade & rastreabilidade

Tudo é nomeado por hashes de conteúdo/identidade (todos **BLAKE2**, não-NIST), dando rastreabilidade à prova de adulteração.

- **Nome do block (a *designação* do drone) = `BLAKE2(pubkey estática Noise do block)`.** O nome *é* a identidade criptográfica do block, autenticada pelo handshake Noise `KK` — um nome de block forjado falha no handshake, então um nome auto-reportado nunca é confiável.
- **Um BOT é um projeto (muitos arquivos) contendo múltiplos scripts.** O que uma atividade roda é identificado por uma **assinatura dupla `bot_ref` = `{ project_hash, script_hash }`**:
  - **assinatura do projeto** = `project_hash = BLAKE2(projeto inteiro)` — a unidade de download/dedup. (Forma canônica: **hash em árvore** — ver *BOT — anatomia e ciclo de vida*.)
  - **assinatura do script** = `script_hash = BLAKE2(o script interno)` — o ponto de entrada que a atividade roda.
  - Um workflow pode referenciar scripts de vários projetos → múltiplos projetos baixados (cada um buscado uma vez, deduplicado por `project_hash`). O Executor baixa um projeto, **verifica contra o `project_hash` antes de rodar**, e então roda o script do `script_hash`. O endereçamento por conteúdo serve também de prova de integridade (qualquer adulteração muda o hash).
- **Manifesto dentro de cada projeto** (assim é coberto pelo `project_hash` → à prova de adulteração). Declara `nome`/`versao` do BOT, as dependências de pacote pinadas com hash e, por script: `script_hash`, o **schema de parâmetros** (campos/tipos), a **exigência** de hardware MEM/CPU (classificação no broker), as **capacidades** exigidas (recursos do block, ex. ollama) e as **APIs** usadas. O catálogo de bots/scripts do editor é só um índice montado a partir dos manifestos; a fonte autoritativa é o manifesto hasheado dentro do projeto. (Forma completa: ver *BOT — anatomia e ciclo de vida*.)
- **A rastreabilidade vive só no núcleo confiável**, mantida pelo Scheduler:
  - **Registro de inventário (Inventory):** `block_hash → { bot_refs disponíveis }`.
  - **Log de auditoria append-only:** por execução `(block_hash, bot_ref, occurrence_id, quando, refs de entrada/saída, status)` — mantido **só no núcleo central**. As refs de entrada/saída são os **`data_ref`s** do *Plano de dados* — linhagem content-addressed à prova de adulteração.

## BOT — anatomia e ciclo de vida (DEFINIDO)

Decisões do dono, fechadas item a item. Esta seção é a forma autoritativa do BOT; o resumo em *Identidade & rastreabilidade* aponta para cá.

### Identidade — hash em árvore + tar como transporte

- **Hash por arquivo** = `BLAKE2(conteúdo)`; **`project_hash` = BLAKE2 da lista ordenada de `(caminho normalizado, hash do arquivo)`**. Só caminho + conteúdo entram — nada de mtime/dono/permissões (metadado de filesystem tornaria o hash irreprodutível). Hashes por arquivo permitem verificação incremental e dedup fino.
- **Container: `.tar.gz` como veículo de transporte apenas.** A identidade **não** depende dos bytes do tar (mtime/ordem/dono dentro do archive são irrelevantes): quem recebe **extrai e recomputa a árvore**. Extração defensiva com `tarfile filter='data'` (rejeita caminho absoluto, `../`, symlink, device). Artefato nomeado `<nome>_<versao>.tar.gz` — conveniência humana; o sistema nunca confia em nome de arquivo.
- **`nome` + `versao` vivem no manifesto** (cobertos pelo hash) e são para humanos (catálogo, auditoria legível). O elo com a identidade real é o **registro imutável no núcleo: `(nome, versao) → project_hash`, append-only** — versão publicada nunca re-aponta; mudou um byte, é obrigatoriamente versão nova. `versao` é string opaca para o sistema.

### Invariante de pulverização — 1 execução = 1 script

**O projeto é unidade de *empacotamento*; o script é a unidade de *execução*; o encadeamento é monopólio do Scheduler.**

- Um spawn = um script = uma atividade; o Executor **nunca** roda sequência. Script **não chama script**: toda composição vive na árvore Nassi do workflow — sequência = duas atividades, cada uma classificada/roteada independentemente (podendo cair em drones diferentes).
- Vários scripts moram no mesmo projeto por **código e ambiente compartilhados** (lib interna importada pelos scripts, um venv, um download, um hash) — empacotamento, não execução.
- **Consequência: scripts não compartilham estado local** — nem arquivo no workdir (apagado por execução), nem nada na máquina; a próxima atividade pode rodar em outro drone. **Dado só viaja pelo workflow:** o `output.json` de um vira parâmetro do próximo, via Scheduler. Script que assume "o anterior rodou aqui e deixou um arquivo" está quebrado por definição.
- É por isso que `exigencia`/`capacidades` são **por script**: um script pesado de VAI e um leve de pós-processamento no mesmo projeto vão para drones diferentes.

### Manifesto — `manifest.json` na raiz

**JSON canônico na escrita** (UTF-8, chaves ordenadas, indentação 2, `\n` final): a integridade vem da árvore, mas o canonicalismo garante que republicar o mesmo conteúdo gere byte a byte o mesmo manifesto → mesmo hash. **Quem escreve é o editor/ferramenta de publicação**, validando coerência antes de empacotar (cada `script_hash` confere com o arquivo, cada `entrypoint` existe, `(nome, versao)` respeita a imutabilidade).

```json
{
  "manifest_version": 1,
  "nome": "ocr-notas",
  "versao": "1.2",
  "descricao": "…",
  "requirements": {
    "pillow": { "versao": "10.4.0", "hashes": ["blake2:…", "sha256:…"] }
  },
  "scripts": {
    "extrair-texto": {
      "entrypoint": "scripts/extrair_texto.py",
      "script_hash": "blake2:…",
      "exigencia": { "mem_mb": 8192, "cpu_cores": 4 },
      "capacidades": ["ollama:llama3.1-8b"],
      "apis": [],
      "params": { "imagem_b64": { "tipo": "str", "obrigatorio": true } },
      "retorno": { "texto": { "tipo": "str" } }
    }
  }
}
```

- **`requirements` é por projeto** (um venv por `project_hash` — ver *Dependências*); o BLAKE2 é o hash autoritativo nosso, o sha256 acompanha porque `pip --require-hashes` só fala SHA-256.
- **`exigencia` e `capacidades` são por script** (é a atividade que o broker classifica e o Scheduler roteia).
- **`workdir_mb` (opcional, por script):** declara o tamanho do workdir para artefato gigante — dispara o **workdir LUKS efêmero** em vez do tmpfs (ver *Execução*); o valor declarado é o compromisso de "acertar no tamanho".
- **`apis`**: declaração de egress externo (convenção: sai via Tor); `[]` = não toca a rede.
- **Schema de `params` mínimo próprio** — `tipo | obrigatorio | default | descricao`, tipos `str|int|float|bool|list|dict`; validável em stdlib, alimenta o auto-preenchimento do editor; evoluível via `manifest_version`. (JSON Schema completo foi descartado por ora.)
- **`retorno` é opcional e só para autoria** (o editor valida que decision/join consomem campos que existem na saída anterior); em runtime ninguém o valida — o `output.json` é livre.

### Ordem de atividade — o segundo JSON

O que o Scheduler manda ao Executor pelo canal sub-espacial. Vidas opostas: o manifesto é imutável dentro do tar; a ordem muda a cada atividade/ocorrência.

```json
{
  "atividade_id": "atv-…",
  "occurrence_id": "occ-…",
  "bot_ref": { "project_hash": "blake2:…", "script_hash": "blake2:…" },
  "params": { "…": "…" },
  "lease_s": 300
}
```

- **`atividade_id` é único por despacho** — a chave do lease, do `RESULT` e da linha de auditoria; `occurrence_id` é o contexto (uma ocorrência despacha muitas atividades ao longo da vida — lease/idempotência não podem chavear por ele).
- **Seleção pelo `script_hash`, nunca pelo nome** — nome é etiqueta de humano; em runtime só hash tem autoridade.
- Executor, antes do spawn: projeto fora do cache → baixa/extrai/recomputa a árvore; o `script_hash` da ordem **tem de constar no manifesto** (senão rejeita — a Rainha pediu o que o projeto não declara); **recomputa o BLAKE2 do entrypoint** (defesa final entre download e execução); valida `params` contra o schema; venv pronto; capacidades vivas (fail-fast: ollama responde?).

### Dependências — duas classes (Environment)

- **Classe A — pacotes Python → venv por projeto.** `~/.myass/envs/<project_hash>/`, criado no primeiro uso com **`pip install --require-hashes`** (pacotes pinados no manifesto — PyPI trocar/comprometer um pacote = instalação **falha**, não drone envenenado; mesma regra de hashes da assimilação). Mesmo projeto → um venv para todos os scripts; hash novo → venv novo; nunca há conflito de versões entre BOTs. Convenção: o pip do drone sai **via Tor**.
- **Classe B — recursos da máquina (ollama, GPU, ffmpeg…) → capacidade do block, não instalável em runtime.** Faz parte do *corpo* do drone, instalada na **assimilação**. O manifesto **declara** (`"capacidades": ["ollama:llama3.1-8b"]`), o `HELLO` **anuncia**, o Scheduler **casa** (a porteira MEM×CPU ganha essa dimensão), o Executor **verifica fail-fast** (recurso morto → erro de *infra* → lease reentrega a outro block). **Pesos de modelos VAI não viajam no tar** — são capacidade do block.

### Execução — contrato Executor ↔ script (decisão do dono: SEM sandbox)

**Sem isolamento de runtime** — o script roda como processo filho comum do Executor, mesmo usuário (todas as máquinas são do dono; sandbox só traria complexidade). **Trade-off honesto:** um BOT com bug grave tem tudo do drone, incluindo a chave estática e a PSK. O raio de dano é um drone (uma chave por drone; revoga no Inventory; o handshake `KK` rejeita; a regeneração reentrega o trabalho) e **o muro de segurança fica inteiro na cadeia de publicação** (ver *Publicação e autorização*). Convenção mantida: BOT que fala com serviço externo declara em `apis` e sai via Tor (não entrega o IP do drone).

```
EXECUTOR                                          PROCESSO FILHO (script BOT)
   mkdtemp /tmp/myass-<occ>-XXXX/  (modo 700)
   grava input.json {occurrence_id, params}
   spawn ── stdin: {"workdir": "…"} ──▶           lê    workdir/input.json
                                                  grava workdir/output.json (+ artefatos)
   ◀── exit 0 = sucesso · exit ≠ 0 = erro lógico ──
   lê output.json, envia ao Scheduler (o "tick")  stderr → capturado p/ auditoria
   finally: rmtree(workdir)
```

- **Dado de verdade vai em arquivo no workdir** (payload grande de VAI sem sufoco; stdout do protocolo livre de poluição de libs); o stdin carrega só o apontador.
- **`exit ≠ 0` = falha *lógica*** (matéria das cadeias de `catch`, com o JSON de erro como payload); **travamento não é erro lógico** — é assunto do lease/regeneração. As duas camadas de falha não se misturam.
- **Limpeza estrutural, não de memória:** `finally` → `rmtree` em todos os caminhos (sucesso, erro lógico, desistência de lease) + **varredura de `/tmp/myass-*` órfãos na partida do Executor** (cobre morte no meio; o trabalho em si o lease já reentregou).
- **O filho não recebe nada além de `occurrence_id` + `params`** — sem `bot_ref`, sem lease, sem chaves, sem contexto do canal. O `lease_s` morre na fronteira do spawn.
- Bônus do `/tmp` tmpfs: dado de atividade em **RAM, nunca no disco** (alinha com o risco de acesso físico do modelo de ameaça).
- **Artefato gigante de VAI — workdir LUKS efêmero (DEFINIDO — decisão do dono).** Script que declara `workdir_mb` no manifesto ganha, em vez do tmpfs, um **volume LUKS descartável dimensionado pela declaração** (*acertar no tamanho* é obrigação do manifesto): o Executor cria o arquivo-container do tamanho declarado, `luksFormat` com **chave aleatória só em RAM** (nunca gravada), monta como workdir, roda a atividade e — **obrigatório** — desmonta, `luksClose` e **remove o container** no mesmo `finally` da limpeza estrutural; a varredura de órfãos na partida também desmonta/remove containers abandonados. Chave descartada + container removido = dado criptograficamente irrecuperável. Espaço em disco insuficiente → erro de *infra* → lease reentrega a outro block.
- Um script é trivial de testar fora do sistema: `echo '{"workdir": "…"}' | python script.py`.

### Distribuição — pelo canal sub-espacial existente

- **Sem canal novo, sem endpoint novo:** o Executor pede (`PROJECT_GET {project_hash}`), o Scheduler serve (`PROJECT_DATA {seq, fim}` + corpo binário cru — chunks no envelope da camada de aplicação; ver *Camada de aplicação*), lastro durável em **MongoDB GridFS**. Pull sempre — honra o *sem entrada*.
- **Cache imutável no block:** `~/.myass/projects/<project_hash>/` (árvore extraída e verificada) + `~/.myass/envs/<project_hash>/` — nunca invalida, só cresce (versão nova = hash novo). **Uma transferência em voo por `project_hash`** (mesma regra do carregador do broker). Limpeza: nenhuma por ora; LRU por último uso se apertar.
- **O `HELLO` anuncia os `project_hash` em cache** → é o que alimenta o Inventory (`block → bot_refs disponíveis`) de verdade; o Scheduler **prefere drone quente**; drone frio continua válido, paga o download na primeira vez.
- **Lease de estreia** (drone frio): lease normal + margem fixa configurável — cobre download + criação do venv + execução; senão a regeneração reentregaria trabalho saudável no meio do `pip install`.
- **Verificação sempre local e total**, mesmo vindo do canal autenticado: recomputa a árvore inteira + o entrypoint antes do spawn. O canal protege o transporte; o hash protege o conteúdo — nenhuma camada confiada sozinha.
- **Descartado:** distribuir código via Locutus (código na WAN, mesmo cifrado, é metadado desnecessário) e espelho HTTP interno (superfície nova à toa).

### Publicação e autorização — o muro que substitui o sandbox

Hash dá integridade; o **registro de publicação** dá legitimidade. Coleção **append-only** no MongoDB, espelhada na auditoria:

```
{ project_hash, nome, versao, manifesto (cópia indexável),
  publicado_em, publicado_por, status: ativo | revogado }
```

- **A Rainha só agenda `bot_ref` aprovado:** `project_hash` ativo **e** `script_hash` constando no manifesto registrado. A porteira fecha na origem — um drone nunca vê ordem com hash não aprovado.
- **Revogação existe, reuso não:** `status: revogado` para o agendamento na hora (ocorrências em voo terminam ou caem no catch); o vínculo `(nome, versao)` fica queimado para sempre; o histórico permanece na auditoria.
- **A cópia do manifesto no registro é o catálogo do editor** e a fonte de `exigencia`/`capacidades` para o Scheduler sem abrir o tar (a fonte autoritativa continua sendo o manifesto hasheado dentro do projeto).
- **Quem publica é identidade, não posição de rede:** o editor é **provisionado como cliente do canal sub-espacial, igual a um drone** (par X25519 estático cunhado na assimilação, Noise `KKpsk0`, client-auth do onion), com papel **publicador** (drones são executores). O `publicado_por` vem do handshake, nunca auto-reportado. Mensagens: `PUBLISH`/`PUBLISH_ACK` e `CATALOG_GET`/`CATALOG` (ver a tabela da *Camada de aplicação*).
- **Validação dupla:** o editor valida ao empacotar (erro cedo, UX); o **núcleo revalida ao receber** (cliente não se confia, mesmo sendo do dono): recomputa a árvore do tar recebido contra o `project_hash` alegado; manifesto coerente (`script_hash` × arquivo, entrypoints existem, schema bem-formado, requirements com hashes); imutabilidade de `(nome, versao)`. Tudo ok → GridFS + registro + auditoria atomicamente; qualquer falha → rejeição integral, nada parcial.
- **A cadeia tem três verificações independentes** — publicação (núcleo revalida), agendamento (Rainha só agenda aprovado), execução (Executor recomputa árvore + entrypoint) — nenhuma confiando na anterior. É este o muro que, pela decisão *sem sandbox* acima, faz o papel do isolamento de runtime.

## Broker (messageria multinível)

A fila/broker própria do projeto, um serviço Python, distribuído e resiliente a falhas. Dois níveis:

- **Nível 1 — lista encadeada de nós, um nó por classe de recurso.** As classes vêm de uma tabela de classificação arbitrária sobre **MEM × CPU** (ex.: C1 baixa/baixa, C2 baixa/alta, C3 alta/baixa, C4 alta/alta). A tabela *não* é ordenada por severidade.
- **Nível 2 — um ring buffer (lista circular) por nó**, com dois ponteiros: **W (write/produtor)** e **R (read/consumidor)**. A **janela de leitura = W − R** = atividades disponíveis para consumir.
- **Janela vazia (W − R = 0):** retorna `[]` **imediatamente** (não-bloqueante) e, **em paralelo**, dispara uma thread carregadora que reabastece aquele nó a partir do MongoDB. Guarda: no máximo **uma carga em voo por nó** (e back off quando o MongoDB também estiver vazio).
- **Armazenamento durável de lastro: MongoDB** (escalável). O ring é uma **janela em memória sobre o backlog persistido** — durabilidade/tolerância a falhas vivem no MongoDB; o ring é o cache rápido.
- **Onde uma atividade é escrita (W):** no nó cuja classe casa com a *exigência* da atividade (declarada no manifesto do projeto).
- **Como um block lê:** o Scheduler casa o perfil de hardware do block (do `HELLO`) com as classes que ele satisfaz — uma classe só é elegível se o block satisfaz **MEM e CPU**. (Revertido de uma varredura ordenada por severidade anterior; o casamento é a única regra.)

## Rotinas & encadeamento

Uma rotina é uma **árvore de atividades** (um workflow Nassi-Shneiderman) com tipos de nó **block / action / decision / loop**. A árvore é um **template** imutável; rodá-la cria uma **ocorrência** — uma instância viva carregando o **cursor** de execução (posição na árvore, a árvore de execução `parent_id`, estado de loop/join, resultados parciais, status, um `occurrence_id`). O **Scheduler dirige o encadeamento**: o resultado retornado por uma atividade é o "tick" que avança o cursor da ocorrência e enfileira a próxima atividade. Muitas ocorrências de um template rodam independentemente. Cada passo / rota de decisão mira uma atividade pelo seu `bot_ref`.

- **Concorrência:** **síncrona dentro de um único diagrama Nassi** (atividades rodam em sequência); paralelismo = **múltiplos diagramas rodando ao mesmo tempo (assíncrono)**.
- **block:** uma sequência linear (sync) de atividades.
- **action:** uma unidade que vai ao broker e roda um script; seu retorno avança o cursor.
- **decision (N-vias):** a condição é, ela mesma, um **script que retorna um LABEL** (uma atividade normal, endereçada por conteúdo, classificada por hardware, async); o autor mapeia **label → fluxo** (N rotas) no editor; visual = um triângulo apontando para baixo. O cursor roda o script-condição → obtém o label → roteia para o fluxo mapeado; os fluxos convergem de volta à sequência linear.
- **loop (foreach + fan-out):** foreach sobre um **array**; o corpo é um **diagrama Nassi interno fixo**, e cada iteração é uma **cópia desse mesmo diagrama** alimentada com os dados do item (cada item do array = entrada diferente). As cópias rodam **async em paralelo** (sync dentro de cada uma). Cada cópia-filha carrega seu **`parent_id`** (o loop) → árvore de execução; o pai **espera enquanto qualquer filho ainda estiver rodando**; o **join** retorna um **array de retornos** (um por iteração) como saída do loop. `parent_id`/join é geral a qualquer fan-out.
- **Tratamento de erros — `catch` aninhado seguindo a estrutura.** Todo escopo (decision, block, loop, workflow) pode registrar um `catch`. Um erro **borbulha de dentro para fora** por cada escopo envolvente até um tratá-lo (senão a ocorrência falha → auditoria). Dentro de um escopo, os handlers são ordenados do mais específico no topo; **o match do topo vence**; cada handler é um script. Quando um catch trata a falha de um filho, seu retorno é substituído no array do join para aquele item.
- **Disposição por erro (escolha do autor, 3 opções):** **tratar com um script** / **propagar para cima (subir)** / **ignorar (engolir)**. O **padrão é propagar para cima** (erros aparecem e borbulham — mais seguro). **Ignorar é opt-in explícito** (engolir um erro em silêncio é perigoso e tem de ser deliberado).
- **Duas camadas de falha — não confundir:** falhas de *infra* (executor morreu, timeout) → tratadas pelo **lease/redelivery** do broker (resiliência = *regeneração*); falhas *lógicas* (script deu erro / label não mapeado) → tratadas pelas cadeias de **catch**. **O ponto de conversão entre as camadas é o esgotamento de `max_tentativas`:** falha de infra crônica é promovida a falha lógica e entra no trilho do catch (ver *Camada de aplicação → Máquina de estados da atividade*).
- **Serialização do template (DEFINIDA — decisão do dono):** o template é **JSON canônico** (mesmas regras do manifesto: UTF-8, chaves ordenadas, indent 2) da árvore Nassi — um nó por bloco visual do editor: `{tipo: block|action|decision|loop, …}`. `action` carrega `bot_ref`, params (valores inline / `$data` / referências a saídas anteriores) e os opcionais `timeout_total`/`max_tentativas`; `decision` carrega o `bot_ref` do script-condição + o mapa `label → subárvore`; `loop` carrega o param do array + a subárvore-corpo; todo escopo pode carregar seu `catch`. **`template_hash = BLAKE2(JSON canônico)`** — template imutável, endereçado por conteúdo como tudo; mudou um byte, é template novo. **Publicado pelo mesmo trilho dos BOTs:** `PUBLISH` com `tipo: workflow`; o registro versiona `(nome, versao) → template_hash` com a mesma imutabilidade; a ocorrência referencia o `template_hash` que roda — a auditoria sabe exatamente qual versão executou.

## Plano de dados (DEFINIDO)

Como um artefato binário grande sai de uma atividade e vira entrada de outra (possivelmente em outro drone — a invariante de pulverização proíbe "deixa no disco que o próximo pega"). Decisões do dono, fechadas item a item. Nenhum canal novo, identidade nova ou serviço novo — tudo nos trilhos existentes.

- **O núcleo é o hub de dados — sem drone-a-drone.** Drones não aceitam entrada e não se conhecem (canal novo = superfície e metadado novos); dado via Locutus/`bdd` misturaria o plano interno com a borda WAN. Todo artefato **sobe ao núcleo e desce do núcleo** pelo canal sub-espacial existente — coerente com a *Rainha escondida, não cega*. Lastro: **GridFS** (junto dos projetos).
- **Identidade: `data_ref = blake2:<hash do conteúdo>`** — content-addressed como tudo no projeto. De graça: integridade verificável em qualquer ponta, dedup (mesmo conteúdo = mesmo ref = um upload), e as "refs de entrada/saída" da auditoria viram **linhagem à prova de adulteração** (quais bytes entraram/saíram de cada execução, para sempre).
- **Mensagens:** `DATA_PUT` / `DATA_ACK` e `DATA_GET` / `DATA_CHUNK` / `DATA_MISS` — já incluídas na tabela da *Camada de aplicação*; mesmo envelope/chunking do `PROJECT_*`; o receptor sempre recomputa o BLAKE2 antes de aceitar.
- **Contrato com o script — arquivos no workdir, refs no JSON; quem traduz é o Executor:**

  ```
  SAÍDA   script grava saida.png no workdir
          output.json: {"imagem": {"$file": "saida.png"}}
          Executor: BLAKE2(saida.png) → DATA_PUT → substitui no JSON:
                    {"imagem": {"$data": "blake2:9f3a…", "tamanho": 4194304}}
          → é esse JSON-com-refs que o RESULT entrega e o Scheduler vê

  ENTRADA ordem traz params: {"imagem": {"$data": "blake2:9f3a…"}}
          Executor: DATA_GET → confere hash → grava workdir/in/imagem.bin
          input.json do filho: {"imagem": {"$file": "in/imagem.bin"}}
  ```

  Dado pequeno continua inline no JSON puro; **o autor escolhe pelo gesto** (valor inline ou arquivo `$file`) — sem threshold mágico. O script continua trivial: lê/escreve arquivo local no workdir.
- **Cache no drone + localidade no Scheduler.** Cache local imutável por `data_ref` com **LRU e orçamento de tamanho** (dado é grande, ao contrário de projeto), **na partição LUKS** que o drone já tem pela assimilação (artefato não fica em disco aberto). O Scheduler sabe qual block produziu cada ref (origem do `RESULT`) e **prefere agendar a atividade consumidora no mesmo block** → `DATA_GET` bate no cache local, transferência zero (mesma lógica do "drone quente" de projetos). O upload ao núcleo acontece **sempre** (durabilidade: o produtor pode morrer e a reentrega cair em outro drone); a localidade só elimina a perna de descida.
- **Honestidade sobre o custo:** tudo viaja por Tor (~poucos MB/s por circuito). Workflow de dados pesados será lento — é o preço da arquitetura de núcleo escondido; a localidade acima é o que o torna suportável.
- **Retenção — GC por TTL, auditoria eterna.** Artefato amarrado às ocorrências que o referenciam; ocorrência em estado terminal → quarentena com **TTL configurável (default: 7 dias)** → GC apaga do GridFS. A **auditoria guarda os refs para sempre** (hashes são pequenos; a linhagem sobrevive ao dado). Resultado final ao cliente sai pelo `SET`/Locutus antes do GC, como sempre.

## Cliente — duas partes (DEFINIDO — decisão do dono)

O "cliente" do sistema se divide em **dois programas distintos**, com papéis e públicos diferentes:

### Parte I — Painel do administrador (app desktop)

O **app desktop PySide6 no Linux** (papel **publicador/admin** no canal sub-espacial, provisionado como cliente Noise — ver *Publicação e autorização*). Faz tudo o que é privilegiado:

- **Autoria de workflows.** Canvas estruturado Nassi (sem setas soltas; caixas contíguas + aninhamento) sobre **`QGraphicsView` + `QGraphicsScene`**, cada tipo de nó uma subclasse de `QGraphicsItem`: action = caixa, decision = triângulo + colunas, loop = caixa-contêiner, block = pilha vertical. Insere/encaixa blocos; o canvas é só o render da árvore e **serializa direto para o template** (um bloco visual = um nó). Cada atividade tem schema rico **auto-preenchido a partir do manifesto** do projeto.
- **Publicação de BOTs e workflows** (`PUBLISH`/`PUBLISH_ACK`, `CATALOG_GET`/`CATALOG`).
- **Observabilidade:** obter informações do ambiente (Inventory, capacidades dos blocks) e **acompanhar as ocorrências** de execução dos workflows (status, auditoria, linhagem).
- Fala com a Rainha pelo **canal sub-espacial Noise** (mesmo transporte plugável direto/Tor), não pela borda pública.

### Parte II — Interface web pública (PHP)

A face para o **usuário final comum**: uma **aplicação web em PHP**. O fluxo: a pessoa informa uma **chave criptográfica** (seu segredo de cliente) → o sistema exibe os **workflows referentes àquela chave** e a opção de **criar novas ocorrências**. É um cliente comum (sem Tor, sem desktop), aplicação banal na surface.

- **Esta aplicação PHP É o Locutus** (o armazém público cego da Rainha): as **APIs ficam neste projeto PHP**, e o **banco público é um MySQL** acessado por essas APIs. (Refina o "hosting banal HTTPS": o lastro do Locutus é concretamente um app PHP + MySQL.)
- **Deploy:** publicação no ambiente web por **FTP**, com as credenciais em um `.env` do projeto PHP.
- **Cripto client-side, PHP cego ao conteúdo (DEFINIDO — decisão do dono):** a cifra/decifra (ChaCha20, segredo por cliente) acontece **no browser, em JavaScript** — a chave criptográfica que a pessoa informa **nunca chega ao servidor PHP**. O PHP só serve o **catálogo de workflows** da chave (metadado de rótulos) e movimenta **blobs opacos** request/response; **nunca vê o conteúdo das ocorrências**. Cifrar server-side (a evitar) foi descartado.
- **Trade-off de cegueira (dito, não escondido):** exibir "os workflows da chave" implica que o lado público conhece o **catálogo de workflows por cliente** (metadado de rótulos), não só blobs opacos — é menos cego que o dead-drop puro quanto a *metadado*; o **conteúdo** permanece E2E e ilegível ao PHP (item acima).

## Canais seguros

Todos os canais usam um **protocolo próprio sobre um socket TCP de stream cru** (`SOCK_STREAM`, *não* `SOCK_RAW`) — sem HTTP ou outro protocolo de aplicação clássico. **Não há TLS**; o handshake/criptografia **copia o Noise Protocol Framework** (design comprovado, implementado por nós sobre o nosso próprio enquadramento). Primitivos: **X25519 / ChaCha20-Poly1305 / BLAKE2s** (todos não-NIST), de uma biblioteca auditada de build reprodutível.

### Canal externo — Executor ↔ Scheduler (o link exposto)

Este é o **único link exposto/"vulnerável"** (Executor num block, em outra máquina, discando para o Scheduler no núcleo) — e agora está **com localização oculta sobre Tor** (ver *Transporte* abaixo), então não há IP/porta pública para achar.

- **Padrão: Noise `KKpsk0`** → suíte `Noise_KKpsk0_25519_ChaChaPoly_BLAKE2s`.
  - **`KK`** = as chaves públicas estáticas de ambas as partes são conhecidas de antemão, **provisionadas fisicamente (out-of-band)** — é o que significa "troca física de chave". Sem negociação de chave in-band, removendo a superfície de MITM sobre o fio.
  - **`psk0`** = uma chave pré-compartilhada adicional, também provisionada fisicamente, misturada no início (autenticação cinto-e-suspensório).
  - Iniciador = **Executor** (disca para fora); Respondedor = **Scheduler**.
  - Chaves efêmeras por sessão → **forward secrecy**. O transporte usa ChaCha20-Poly1305 com um **nonce contador** por direção (sempre único → também anti-replay) e a tag Poly1305 para integridade por mensagem.
- **Sem fingerprint em claro:** sem header mágico — um handshake Noise abre com uma chave efêmera de aparência aleatória, então o fio não é trivialmente identificável por DPI. A **versão do protocolo vai no `prologue` do Noise** (autenticada no hash do handshake, nunca enviada em claro).

#### Transporte: sobre Tor (o *canal sub-espacial*) — adotado

O canal externo cavalga **dentro da rede Tor** (onion routing), não na clearnet:

- **Scheduler = serviço onion Tor v3.** Drones (Executores) discam o `.onion`; o IP do Scheduler nunca é revelado. **Sem porta de escuta na clearnet** — a entrada chega via rendezvous do Tor, então isso ainda honra o *sem entrada em direção à WAN* (não há IP/porta pública para escanear ou invadir). Ocultar a localização do núcleo embota diretamente o "ponto único de vigilância/coerção": não se invade um núcleo que não se consegue localizar.
- **Autorização de cliente onion** — só drones provisionados têm a chave de client-auth do descritor, então partes não autorizadas nem alcançam o rendezvous. Isto fica *sob* o Noise `KKpsk0`: o Tor te leva ao onion; o Noise autentica a chave estática real do Scheduler + o drone + mistura a PSK. Defesa em profundidade — nenhuma camada é confiável sozinha.
- **O Noise roda sobre o SOCKS5 do Tor** — o `SOCK_STREAM` cru conecta pelo proxy SOCKS do Tor até o `.onion`; enquadramento e primitivos não mudam. (Gerenciar o serviço onion / circuitos com `stem`.)
- **Drones são clientes Tor** — seus IPs ficam ocultos do núcleo e de observadores; a superfície de metadados/análise de tráfego encolhe nas duas pontas.
- **Transporte plugável — escolhido pela topologia (decisão do dono).** O Noise `KKpsk0` é **independente do transporte**: o mesmo handshake/cifra/autenticação roda tanto sobre o SOCKS5 do Tor quanto sobre um `SOCK_STREAM` cru direto (`host:porta`). A regra é a topologia, não "Tor sempre":
  - **Mesma máquina (localhost) ou LAN da zona de confiança → socket direto, sem Tor.** Tor de localhost↔localhost é só overhead absurdo (montar circuito para falar com a própria máquina/rack); drones co-localizados com o núcleo discam direto o IP/porta, ganhando a velocidade cheia da LAN (importa muito no plano de dados pesado).
  - **Travessia de WAN / rede hostil → Tor** (serviço onion + client-auth + bridges/obfs4). É aí que o sigilo de localização do núcleo importa de verdade.
  - **Como é decidido:** o endpoint de cada drone (`host:porta` direto *ou* `.onion`) vem na **tabela de roteamento provisionada out-of-band** (junto da pubkey estática do Scheduler + PSK). Opcional: tentar LAN e cair para Tor (fallback).
  - **A segurança NÃO enfraquece com o caminho direto:** o Noise `KKpsk0` é idêntico — o atacante ainda precisa da chave estática + PSK; endurecer com **allowlist/firewall** dos IPs de drones (o núcleo não escuta para qualquer um). Só o **sigilo de localização** muda: um endpoint direto revela o IP do núcleo a quem o usa, e um drone é *sem sandbox* — por isso o caminho direto fica **restrito à zona de confiança** (mesma infra do dono, já isolada da WAN), onde quem está na LAN já está dentro; **drone atrás de rede hostil nunca recebe IP direto, só `.onion`**.
- **Ressalva Estado-nação:** o adversário pode *bloquear* o Tor → planejar **bridges + pluggable transports (obfs4 / meek)** para um drone atrás de rede hostil ainda alcançar o rendezvous. Defesas de cover traffic / timing seguem como item de redesign.
- **Escopo:** o Tor é para este canal sub-espacial exposto. **Os links internos do núcleo ficam locais** (NNpsk0 sobre a rede própria do núcleo, não Tor). **O polling GET/SET no armazém público: Tor preferencial, surface permitida (decisão do dono).** Tor por padrão (esconde que o núcleo está consultando — é a localização da Rainha que está em jogo); a clearnet fica permitida porque as restrições do lastro público não são controláveis (um object storage comercial pode bloquear exits do Tor / limitar taxa). Trade-off dito: polling pela surface revela o IP do núcleo ao provedor do armazém e a observadores da rota — quando a surface for necessária, a escolha de provedor/mitigação (VPN, host Tor-friendly) vira critério de seleção do lastro físico do Locutus (decidido: hosting banal HTTPS — ver *Filosofia Borg → A Rainha*).

### Links internos do núcleo — Scheduler↔Broker, Broker↔Storage, GET/SET↔Broker

Dentro do núcleo confiável, mas ainda assim cifrados.

- **Padrão: Noise `NNpsk0`** — chaves efêmeras dos dois lados (chave dinâmica por sessão → forward secrecy), autenticadas por uma **chave pré-compartilhada definida no momento da instalação**. Sem identidades estáticas por componente.
- **PSK por par** — cada par de componentes do núcleo tem sua própria PSK de instalação (raio de dano pequeno se uma vazar).
- A PSK de instalação só *autentica* o handshake; não cifra o tráfego, então uma chave vazada não expõe sessões passadas (forward secrecy). Pode viver em `.env` com salvaguardas: na partição LUKS, `chmod 600`, no gitignore.
- Mesmos primitivos e enquadramento do canal externo; **o padding é mantido** aqui também.

### Borda do cliente — cliente ↔ Locutus ↔ Rainha (DEFINIDA)

O esquema E2E da primeira perna (cliente em linguagem humana → Locutus → núcleo). Decisão do dono:

- **AEAD: ChaCha20-Poly1305 — não AES.** Duas razões: AES é NIST (a pilha é não-NIST de ponta a ponta) e o cliente é de **baixa capacidade** — sem AES-NI, AES em software é 2–3× mais lento que ChaCha20 e vaza timing por cache (tabelas de lookup); o ChaCha20 foi desenhado para ser rápido e constant-time em software puro. Cliente fraco é o caso de uso do ChaCha, não do AES.
- **Simétrico puro, sem DH no cliente:** **um segredo de 32 bytes por cliente**, cunhado na estação parteira e provisionado **out-of-band** (QR code / USB — nunca pela rede; uma "assimilação-lite"). Um segredo por cliente, nunca reutilizado; **revogar um cliente = esquecer um segredo**; raio de dano de um vazamento = um cliente.
- **Limites honestos (registrados, não escondidos):** sem DH e — por ora — sem catraca, um segredo vazado decifra **todo o tráfego passado gravado e o futuro** daquele cliente até a revogação; sem contador, replay de blob antigo é possível. Trade-off aceito pela baixa capacidade do cliente e porque os clientes são do dono.
- **Locutus = app web PHP + MySQL (decisão do dono; `bdd` rejeitado para esta borda):** os clientes são **aplicações comuns, sem Tor**; a borda pública é a **interface web PHP** (ver *Cliente — duas partes → Parte II*) com as APIs no próprio projeto PHP e um **MySQL público** como banco, deploy por FTP (`.env`). O que permanece do padrão dead-drop é a **cegueira ao conteúdo** (blobs E2E request/response; o servidor não lê o conteúdo das ocorrências), com a ressalva de que o catálogo de workflows por cliente é metadado conhecido pela web. (O `bdd` segue sendo o transporte do *subspace relay* inter-quadrante, não desta borda de cliente.)
- **FECHADO (decisão do dono): nada além disso no cliente — ele pode ser um Arduino.** Sem catraca de FS, sem contador anti-replay no dispositivo; os limites honestos acima são o estado final aceito, não pendência. Única salvaguarda, **do lado do núcleo, custo zero para o cliente**: a Rainha processa cada `request_id` **uma vez** (dedup idempotente — já invariante do sistema), então replay de blob capturado vira no-op, não re-execução. O formato do blob/enquadramento da borda é detalhe de implementação, não decisão de design.

### Enquadramento sobre TCP — dois níveis

Um **record** = uma mensagem de aplicação.

- **Fio:** `record_len (4B BE)` + corpo do record. O corpo é uma sequência de blocos Noise, cada um `blk_len (2B BE)` + mensagem Noise (`ciphertext + tag de 16B`). O `blk_len` é necessário porque cada bloco é decifrado individualmente; um único bloco Noise é limitado a 65535 bytes (limite do AEAD).
- **Plaintext do record** (antes de fatiar/cifrar): `real_len (4B) || payload || zero-pad até o próximo múltiplo de 256`. Depois fatiado em chunks de ≤ **65280 bytes** (255×256, múltiplo de 256 e ≤ 65519), cada um cifrado como uma mensagem de transporte Noise; o nonce contador por direção avança por bloco.
- **Receptor:** lê `record_len`; lê o corpo; itera `blk_len` → lê → decifra Noise → anexa; concatena chunks → plaintext do record; lê `real_len`; pega o payload; descarta o padding.
- **Padding que esconde tamanho (bloco):** o padding até um múltiplo de 256 vive *dentro* do AEAD (nível do record), então um observador vê só tamanhos grosseiros já com padding.

### Camada de aplicação — Executor ↔ Scheduler (DEFINIDA)

Decisões do dono, fechadas item a item. Roda por dentro do enquadramento de records Noise (acima); o Executor sempre inicia; a identidade vem do handshake, nunca auto-reportada.

- **Sessão persistente.** Montar circuito Tor + rendezvous custa segundos, então a conexão fica viva e tudo flui por ela (poll, download, beats). Caiu → reconecta com backoff + jitter, refaz handshake e `HELLO`; **trabalho em voo sobrevive à reconexão** — o filho continua rodando, os beats retomam, o resultado é entregue (aceito se o lease ainda vale; senão a idempotência descarta o duplicado).
- **Envelope dentro de cada record:** `header_len (4B BE) ‖ header JSON ‖ corpo (bytes crus, opcional)`. Header sempre JSON: `{"t": tipo, "id": seq do remetente, "re": id sendo respondido, …campos}` — o `re` permite intercalar (um beat no meio de uma transferência de projeto). Corpo cru só para binário (`PROJECT_DATA`); mensagens de controle vão com corpo vazio. Evita base64 de 33% no download de projetos, mantendo JSON legível em todo o resto.
- **Conjunto de mensagens:**

| Executor → Scheduler | Scheduler → Executor | Função |
|---|---|---|
| `HELLO` {perfil hw (OS, MEM, CPU/arch+cores), capacidades, `project_hash`es em cache, slots} | `HELLO_OK` {config: intervalo de poll, lease padrão} | abertura de sessão; alimenta Inventory + escalonamento (porteira MEM×CPU + capacidades; prefere drone quente) |
| `WORK_GET` {slots_livres} | `WORK` {ordem de atividade} ou `NO_WORK` | pull; `NO_WORK` é imediato (espelha o `[]` não-bloqueante do broker) → backoff no Executor |
| `PROJECT_GET` {project_hash} | `PROJECT_DATA` {seq, fim} + corpo binário · ou `PROJECT_MISS` | download de projeto em chunks com remontagem por `seq`; `MISS` = hash não aprovado/inexistente |
| `DATA_PUT` {data_ref, tamanho, seq, fim} + corpo binário | `DATA_ACK` | upload de artefato em chunks; **ref já existente → ACK imediato sem transferir** (dedup) |
| `DATA_GET` {data_ref} | `DATA_CHUNK` {seq, fim} + corpo binário · ou `DATA_MISS` | download de artefato; receptor recomputa o BLAKE2 (ver *Plano de dados*) |
| `WORK_BEAT` {atividade_id} | `BEAT_ACK` ou `WORK_CANCEL` | heartbeat renova o lease; o ACK é o canal natural de cancelamento (sem push) |
| `RESULT` {atividade_id, status: ok\|erro_logico, output, stderr, duracao} | `RESULT_ACK` | entrega idempotente; `RESULT` duplicado → re-ACK, sem reprocessar |
| `WORK_RELEASE` {atividade_id} | `RELEASE_ACK` | devolução limpa (shutdown gracioso) → reentrega imediata, sem esperar o lease expirar |
| `PING` | `PONG` | liveness da sessão ociosa (Tor mata conexão parada) |
| `PUBLISH` {tipo: bot\|workflow, nome, versao, hash, tamanho, seq, fim} + corpo binário (tar do BOT ou JSON do template, em chunks) | `PUBLISH_ACK` {hash, status: aceito\|rejeitado, motivo} | publicação — **papel publicador apenas** (drone executor que tenta → rejeitado); o núcleo revalida tudo antes do `aceito` (transação GridFS + registro + auditoria) |
| `CATALOG_GET` | `CATALOG` {manifestos e templates ativos do registro} | o índice de BOTs/scripts/workflows para autoria no editor |

- **`atividade_id` — a chave de despacho.** Uma ocorrência executa muitas atividades (o cursor avança), então lease e idempotência **não** chaveiam por `occurrence_id`: cada despacho gera um `atividade_id` único — chave do lease, do `RESULT` e da linha de auditoria; `occurrence_id` segue como contexto. (A ordem de atividade em *BOT* carrega ambos.)
- **Lease de atividade longa: o heartbeat estende.** Prever duração de VAI no manifesto é chute; em vez disso, lease curto (ex. 120s) renovado por `WORK_BEAT` (ex. a cada 30s). Drone morto para de bater → lease expira → regeneração, como sempre; script legítimo de horas nunca é reentregue à toa.
- **Concorrência por block: slots.** O `HELLO` anuncia quantas atividades em paralelo o block aceita (default 1); o `WORK_GET` pede até os slots livres; cada atividade vive independente pelo seu `atividade_id`. Drone sequencial e drone paralelo falam o mesmo protocolo.
- **O plano de dados está DEFINIDO em seção própria** (ver *Plano de dados*): artefato grande viaja content-addressed (`data_ref`) via `DATA_PUT`/`DATA_GET`; dado pequeno segue inline no JSON de params/output.

#### Máquina de estados da atividade (DEFINIDA)

O Scheduler nunca adivinha se uma atividade "demorou muito" ou "falhou" — ele observa **dois sinais e um relógio**: `WORK_BEAT` chegando = drone vivo, filho rodando (lento ≠ morto; não há teto por padrão); `RESULT` chegando = desfecho real; `lease_expira_em` (renovado a cada beat) = o relógio — beat parou → lease vence → morte de *infra* declarada sem prova.

```
                        ┌─────────────┐
         broker grava   │ ENFILEIRADA │◀──────────────────────────┐
                        └──────┬──────┘                           │
                               │ WORK entregue (lease, tentativa N)│
                               ▼                                  │
                        ┌─────────────┐   lease venceu (sem beat) │
                        │ EXECUTANDO  │───────────────────────────┤
                        │ beat renova │     tentativa < max?  sim─┘
                        └──┬───┬───┬──┘     tentativa = max? ──▶ ESGOTADA ──┐
                  RESULT ok│   │   │                                        │
                           │   │   │ timeout_total estourou                 │
                           ▼   │   └─▶ WORK_CANCEL ──▶ erro "timeout" ──┐   │
                  ┌──────────┐ │ RESULT erro_logico                     ▼   ▼
                  │ CONCLUÍDA│ └─────────────────────────────▶ ┌──────────────┐
                  │ (tick ▶) │                                 │ FALHA LÓGICA │
                  └──────────┘                                 └──────┬───────┘
                                                                      ▼
                                                          cadeia de catch da ocorrência
                                                          (tratar / subir / engolir)
```

- **Reempilhar é o caminho normal, não exceção:** lease venceu → `tentativa + 1` → volta à fila → outro drone pega. Falha de infra é esperada e barata (*regeneração*).
- **`max_tentativas` (default global 3, sobrescrevível pelo autor por atividade no workflow):** esgotou → o broker **dropa a atividade** (nunca mais reempilha) — mas **dropar não é sumir em silêncio**: a falha de infra crônica é **promovida a falha lógica** e entra no trilho normal de erros (catch: tratar/subir/engolir; sem catch → ocorrência falha). A auditoria registra o histórico completo de tentativas (quais drones, quando, por quê parou). É o ponto de conversão entre as duas camadas de falha.
- **`timeout_total` opcional por atividade (do autor, no workflow — não no manifesto):** pega o caso que o lease não pega, o script *pendurado para sempre* (vivo, batendo, nunca termina). Estourou → o Scheduler responde o próximo beat com `WORK_CANCEL` → Executor mata o filho → vira erro lógico "timeout" → catch decide. Sem `timeout_total`, atividade lenta legítima roda indefinidamente.
- **Mesmo `atividade_id` em todas as tentativas** (ele identifica o passo do cursor; `tentativa` é só contador). Beat de portador antigo (perdeu o lease, já reentregue) → `WORK_CANCEL`.
- **Primeiro `RESULT` vence**, mesmo vindo do portador antigo — trabalho é idempotente por invariante, resultado válido é resultado válido; o Scheduler conclui, cancela o outro portador, re-ACKa duplicatas sem reprocessar.
- **Todo o estado vive no MongoDB, transição escrita antes do ACK** — qualquer réplica da Rainha varre leases vencidos e retoma o controle (stateless-sobre-MongoDB valendo para o estado de despacho; sem isso, a morte de uma réplica órfã as atividades em voo).

## Análise teórica & redesign proposto (ainda não adotado)

O design foi cruzado com **Tanenbaum** (sistemas distribuídos) e **Monero** (rede de privacidade). Ambos convergem no mesmo ponto fraco: o **núcleo central** (Tanenbaum: gargalo de escalabilidade / SPOF lógico; Monero: ponto único de vigilância/coerção — o núcleo decifra tudo e detém o log de auditoria/inventário/chaves). Ver:

- `doc/analise-tanenbaum.md` — análise cruzada de sistemas distribuídos.
- `doc/analise-monero.md` — análise cruzada de privacidade/rede.
- `doc/redesign-minimum-knowledge-core.md` — um redesign proposto de "núcleo de conhecimento mínimo".

**O redesign é uma PROPOSTA pendente de decisão item-a-item do dono — não o trate como adotado.** Ideias-chave: núcleo roteador cego (E2E até o executor), identidades rotativas/de uso único + anti-replay estilo key-image, anonimato de rede (Tor/I2P + stem/fluff + cover traffic), stateless-sobre-MongoDB (apoiar-se no replica set para consenso), votação opcional de N-blocks para trabalho crítico bizantino, idempotência como invariante, separação de chaves view/act. Cinco decisões em aberto estão listadas no doc de redesign.

**Relação com a tese Borg:** o design adota uma **Rainha escondida, não um roteador cego** (ver *Filosofia Borg → A Rainha*). Então a ideia-chave deste redesign de **roteador cego / E2E-até-o-executor** é **deliberadamente NÃO adotada para conteúdo**: a Rainha (Broker+Scheduler) lê o pedido para poder orquestrá-lo. O que *é* aproveitado daqui: **ocultação de localização** (Tor — adotado), **distribuição / sem-SPOF**, a **parteira efêmera**, **idempotência** e o **Locutus como borda cega**. **Anonimato de rede está parcialmente resolvido:** o canal sub-espacial sobre Tor (serviço onion + client auth) está **adotado** (ver *Canais seguros → Transporte*); defesas de cover traffic / timing estilo stem-and-fluff seguem em aberto. Os demais itens do redesign permanecem pendentes item-a-item.

## Pontos em aberto (registro vivo)

A lista consolidada do que ainda não tem decisão. **Mantenha-a atualizada:** fechou uma decisão → remova daqui e registre na seção correspondente; surgiu pendência nova → entre aqui.

### Segurança / protocolo

1. **Cover traffic / metadados** — intra-quadrante (timing do canal sub-espacial) e inter-quadrante (padrão de depósitos no subspace relay).
2. **Bridges + pluggable transports (obfs4/meek)** — para drone atrás de rede hostil; planejado, sem forma.
3. **Redesign teórico, item a item** (decisão do dono pendente; ver *Análise teórica*): identidades rotativas/de uso único, votação de N-blocks para trabalho crítico (bizantino), separação de chaves view/act.

### Refinamentos registrados (baixa urgência)

4. LRU/limpeza do cache de projetos nos blocks (hoje cresce sem limite, de propósito).
5. Parâmetros concretos de operação: a tabela de classes MEM×CPU do broker, defaults do `HELLO_OK` (intervalo de poll, lease padrão), TTL do GC de dados.

### Implementação (degrau zero)

6. **Convenções e primeiro componente DEFINIDOS.** **Linguagem (decisão do dono): tudo em Python** — para **evitar containers / stacks web** (sem HTTP, sem broker de terceiros, sem orquestração de containers; tudo roda como processo Python sobre socket TCP cru, alinhado ao *protocolo próprio* dos *Canais seguros*). **Versão: Python 3.14** (última estável; dev atual 3.13.5 — alinhar). **Layout/ferramental (decisão do dono, espelha o `bdd`):** `src/myass/`, `tests/` com `unittest` da stdlib, `pyproject.toml`, `install.sh`. **Implementados: broker + Scheduler completo + executor completo + canal Noise + protocolo + borda GET/SET + armazenamento (Mongo/GridFS) + cliente (admin PySide6 + web PHP) + núcleo montado (GET→engine→SET) + canal de erros** (ver *Estado do projeto*). Ciclos cobertos fim-a-fim: drone (`test_protocol_e2e`), encadeamento (`test_workflow`), admin (`test_admin_e2e`), usuário final (`test_core_e2e`), transferência de projeto/dados (`test_wire_transfer`), **quadrante inteiro montado (`test_quadrant_e2e`)**. **Um quadrante está completo, montado e COMPROVADAMENTE RODANDO sobre infra real** (lógica + transporte Noise/Tor + operação `provision`/`CoreNode`/`DroneNode` + CLIs `python -m myass.ops.*` + `install.sh` apt/pip3; demo real em `examples/run_real_quadrant.py` com mongod + 2 processos + sockets). **Inter-quadrante (subspace relay sobre `bdd` real) e drone VAI implementados.** **Tudo implementado e testado em código (171 testes)** e comprovadamente rodado sobre infra real (mongod + 2 processos + sockets; `bdd` real HTTPS). Deploy em `doc/DEPLOY.md`. **Resta apenas pesquisa (não-bloqueante):** cover traffic/timing e bridges/pluggable-transports (obfs4/meek) — ver *Pontos em aberto*.

## Orientação para trabalho futuro

As primeiras mudanças substantivas vão definir as convenções do projeto. Conforme elas chegarem:

- Registre aqui a(s) linguagem(ns), framework, gerenciador de pacotes e os comandos de build/lint/test escolhidos.
- Substitua a nota de "Estado do projeto" assim que houver código real.
- Mantenha a terminologia consistente: **Scheduler (Escalonador)**, **block** (= unidade Executor + BOTs; **drone** Borg), **BOT** (= um projeto), **script** (= a unidade de execução; 1 spawn = 1 script), **`bot_ref`** (assinatura do projeto + assinatura do script), **ocorrência**, **exigência** (requisito de hardware), **capacidade** (recurso de máquina do block, ex. ollama — dependência classe B), **manifesto** (`manifest.json` canônico na raiz do projeto), **ordem de atividade** (o JSON Scheduler→Executor: `{atividade_id, occurrence_id, bot_ref, params, lease_s}`), **`atividade_id`** (único por despacho; chave de lease/resultado/auditoria), **registro de publicação** (`(nome, versao) → project_hash` imutável no núcleo), **`data_ref`** (artefato content-addressed `blake2:<hash>` no GridFS — ver *Plano de dados*), **`template_hash`** (BLAKE2 do JSON canônico do template de workflow), **quadrante** (= unidade mais externa; uma instância completa da arquitetura), **subspace relay** (= link inter-quadrante; dead drop cego entre Rainhas, implementado no `bdd`).
- Vocabulário Borg (ver *Filosofia Borg*): **drone** (= block), **assimilação** (payload de provisionamento; modelo B = chave embarcada no payload), **designação** (= `block_name`), **regeneração** (= lease/redelivery), **canal sub-espacial** (= canal externo Executor↔Scheduler, transportado sobre Tor), **Rainha** (= Broker + Scheduler, a mente orquestradora central — mantida, mas **escondida, não cega**; "Rainha escondida"), **Locutus** (= armazém público, o *porta-voz cego* da Rainha na WAN).
