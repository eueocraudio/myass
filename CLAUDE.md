# CLAUDE.md

Este arquivo orienta o Claude Code (claude.ai/code) ao trabalhar com o código deste repositório.

## Estado do projeto

Pré-implementação. O repositório hoje contém apenas `README.md`, este arquivo e os artefatos de design em `doc/`. **Ainda não há código-fonte, ferramental de build, nem comandos de build escolhidos** — essas seções serão preenchidas conforme o projeto for estruturado. Este documento é a especificação de arquitetura autoritativa; é autocontido e não depende do PDF fundador.

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

*Em aberto:* se o interpretador de linguagem humana (pedido → plano, ele mesmo uma rotina de IA) roda **dentro da Rainha** ou é despachado para um **drone VAI** — pendente. Lastro físico do Locutus (object storage / IPFS / espelhos rotativos) — pendente.

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
  - **Ainda em aberto:** **endereçamento** — mapear a identidade do quadrante (`BLAKE2(pubkey estática da Rainha)`) nos channels/segredos do `bdd` + uma tabela de roteamento (o segredo-raiz do `bdd` + a alocação de channels são provisionados out-of-band por par de Rainhas, junto com as estáticas Noise + a PSK); metadados inter-quadrante / cover traffic.

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
  - **Log de auditoria append-only:** por execução `(block_hash, bot_ref, occurrence_id, quando, refs de entrada/saída, status)` — mantido **só no núcleo central**.

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
- **`apis`**: declaração de egress externo (convenção: sai via Tor); `[]` = não toca a rede.
- **Schema de `params` mínimo próprio** — `tipo | obrigatorio | default | descricao`, tipos `str|int|float|bool|list|dict`; validável em stdlib, alimenta o auto-preenchimento do editor; evoluível via `manifest_version`. (JSON Schema completo foi descartado por ora.)
- **`retorno` é opcional e só para autoria** (o editor valida que decision/join consomem campos que existem na saída anterior); em runtime ninguém o valida — o `output.json` é livre.

### Ordem de atividade — o segundo JSON

O que o Scheduler manda ao Executor pelo canal sub-espacial. Vidas opostas: o manifesto é imutável dentro do tar; a ordem muda a cada atividade/ocorrência.

```json
{
  "occurrence_id": "occ-…",
  "bot_ref": { "project_hash": "blake2:…", "script_hash": "blake2:…" },
  "params": { "…": "…" },
  "lease_s": 300
}
```

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
- Bônus do `/tmp` tmpfs: dado de atividade em **RAM, nunca no disco** (alinha com o risco de acesso físico do modelo de ameaça). Artefato gigante de VAI: refinamento futuro — workdir alternativo na partição LUKS, declarado via manifesto.
- Um script é trivial de testar fora do sistema: `echo '{"workdir": "…"}' | python script.py`.

### Distribuição — pelo canal sub-espacial existente

- **Sem canal novo, sem endpoint novo:** o Executor pede (`PROJECT_GET {project_hash}`), o Scheduler serve (`PROJECT_DATA {seq, bytes, fim}` — chunks dentro do enquadramento/records já definidos), lastro durável em **MongoDB GridFS**. Pull sempre — honra o *sem entrada*.
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
- **Quem publica é identidade, não posição de rede:** o editor é **provisionado como cliente do canal sub-espacial, igual a um drone** (par X25519 estático cunhado na assimilação, Noise `KKpsk0`, client-auth do onion), com papel **publicador** (drones são executores). O `publicado_por` vem do handshake, nunca auto-reportado.
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
- **Duas camadas de falha — não confundir:** falhas de *infra* (executor morreu, timeout) → tratadas pelo **lease/redelivery** do broker (resiliência = *regeneração*); falhas *lógicas* (script deu erro / label não mapeado) → tratadas pelas cadeias de **catch**.

## Editor de workflow (ferramenta de autoria)

- **App desktop PySide6 no Linux** — a ferramenta de autoria de rotinas. O artefato que ela edita é um **workflow** = o template de árvore de atividades.
- **Canvas estruturado** (Nassi é inerentemente estruturado — sem setas soltas; o fluxo é caixas contíguas + aninhamento). Construído sobre **`QGraphicsView` + `QGraphicsScene`**, cada tipo de nó uma subclasse de `QGraphicsItem`: action = caixa, decision = triângulo para baixo + colunas, loop = caixa-contêiner envolvendo o diagrama interno, block = pilha vertical. O usuário **insere/encaixa blocos** (sem desenho livre); o canvas se auto-organiza e é **apenas o render da árvore de atividades**, então fica sempre válido e **serializa direto para o template** (um bloco visual = um nó da árvore).
- Num workflow o usuário define **atividades**; cada atividade tem um schema rico, definido pelo usuário — **campos, atributos, requisitos, APIs, etc.** — mais o BOT (`bot_ref`) que ela roda e seus parâmetros/entrada. O schema é **auto-preenchido a partir do manifesto do projeto**; o usuário fornece/sobrescreve valores.

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
- **Ressalva Estado-nação:** o adversário pode *bloquear* o Tor → planejar **bridges + pluggable transports (obfs4 / meek)** para um drone atrás de rede hostil ainda alcançar o rendezvous. Defesas de cover traffic / timing seguem como item de redesign.
- **Escopo:** o Tor é para este canal sub-espacial exposto. **Os links internos do núcleo ficam locais** (NNpsk0 sobre a rede própria do núcleo, não Tor). O polling GET/SET no armazém público *deveria* sair também por Tor (esconde que o núcleo está buscando) — extensão recomendada.

### Links internos do núcleo — Scheduler↔Broker, Broker↔Storage, GET/SET↔Broker

Dentro do núcleo confiável, mas ainda assim cifrados.

- **Padrão: Noise `NNpsk0`** — chaves efêmeras dos dois lados (chave dinâmica por sessão → forward secrecy), autenticadas por uma **chave pré-compartilhada definida no momento da instalação**. Sem identidades estáticas por componente.
- **PSK por par** — cada par de componentes do núcleo tem sua própria PSK de instalação (raio de dano pequeno se uma vazar).
- A PSK de instalação só *autentica* o handshake; não cifra o tráfego, então uma chave vazada não expõe sessões passadas (forward secrecy). Pode viver em `.env` com salvaguardas: na partição LUKS, `chmod 600`, no gitignore.
- Mesmos primitivos e enquadramento do canal externo; **o padding é mantido** aqui também.

### Enquadramento sobre TCP — dois níveis

Um **record** = uma mensagem de aplicação.

- **Fio:** `record_len (4B BE)` + corpo do record. O corpo é uma sequência de blocos Noise, cada um `blk_len (2B BE)` + mensagem Noise (`ciphertext + tag de 16B`). O `blk_len` é necessário porque cada bloco é decifrado individualmente; um único bloco Noise é limitado a 65535 bytes (limite do AEAD).
- **Plaintext do record** (antes de fatiar/cifrar): `real_len (4B) || payload || zero-pad até o próximo múltiplo de 256`. Depois fatiado em chunks de ≤ **65280 bytes** (255×256, múltiplo de 256 e ≤ 65519), cada um cifrado como uma mensagem de transporte Noise; o nonce contador por direção avança por bloco.
- **Receptor:** lê `record_len`; lê o corpo; itera `blk_len` → lê → decifra Noise → anexa; concatena chunks → plaintext do record; lê `real_len`; pega o payload; descarta o padding.
- **Padding que esconde tamanho (bloco):** o padding até um múltiplo de 256 vive *dentro* do AEAD (nível do record), então um observador vê só tamanhos grosseiros já com padding.

### Camada de aplicação — Executor ↔ Scheduler (parcialmente definida)

- **Escalonamento por capacidade (confirmado):** o `HELLO` do Executor carrega o **perfil de hardware** do block (nome do OS, MEM, CPU/arch+cores); o Scheduler o casa com as classes de recurso do broker (porteira de MEM e CPU) para escolher a atividade que melhor encaixa. Com as decisões de BOT, o `HELLO` carrega também as **capacidades** do block (ollama, GPU…) e os **`project_hash` em cache** — o Scheduler casa exigência + capacidades e prefere drone quente (ver *BOT — anatomia e ciclo de vida*).
- **Pull + work-lease (direção proposta):** o Executor puxa trabalho; cada concessão carrega um lease; se o Executor morre, o lease expira e o broker reentrega (esta é a camada de falha de *infra*). Resultados são idempotentes, chaveados por `occurrence_id`/id do trabalho; o Executor verifica o projeto BOT contra o `bot_ref` antes de rodar; a identidade vem do handshake Noise, nunca auto-reportada. *(O conjunto concreto de mensagens / codificação ainda está em aberto.)*

## Análise teórica & redesign proposto (ainda não adotado)

O design foi cruzado com **Tanenbaum** (sistemas distribuídos) e **Monero** (rede de privacidade). Ambos convergem no mesmo ponto fraco: o **núcleo central** (Tanenbaum: gargalo de escalabilidade / SPOF lógico; Monero: ponto único de vigilância/coerção — o núcleo decifra tudo e detém o log de auditoria/inventário/chaves). Ver:

- `doc/analise-tanenbaum.md` — análise cruzada de sistemas distribuídos.
- `doc/analise-monero.md` — análise cruzada de privacidade/rede.
- `doc/redesign-minimum-knowledge-core.md` — um redesign proposto de "núcleo de conhecimento mínimo".

**O redesign é uma PROPOSTA pendente de decisão item-a-item do dono — não o trate como adotado.** Ideias-chave: núcleo roteador cego (E2E até o executor), identidades rotativas/de uso único + anti-replay estilo key-image, anonimato de rede (Tor/I2P + stem/fluff + cover traffic), stateless-sobre-MongoDB (apoiar-se no replica set para consenso), votação opcional de N-blocks para trabalho crítico bizantino, idempotência como invariante, separação de chaves view/act. Cinco decisões em aberto estão listadas no doc de redesign.

**Relação com a tese Borg:** o design adota uma **Rainha escondida, não um roteador cego** (ver *Filosofia Borg → A Rainha*). Então a ideia-chave deste redesign de **roteador cego / E2E-até-o-executor** é **deliberadamente NÃO adotada para conteúdo**: a Rainha (Broker+Scheduler) lê o pedido para poder orquestrá-lo. O que *é* aproveitado daqui: **ocultação de localização** (Tor — adotado), **distribuição / sem-SPOF**, a **parteira efêmera**, **idempotência** e o **Locutus como borda cega**. **Anonimato de rede está parcialmente resolvido:** o canal sub-espacial sobre Tor (serviço onion + client auth) está **adotado** (ver *Canais seguros → Transporte*); defesas de cover traffic / timing estilo stem-and-fluff seguem em aberto. Os demais itens do redesign permanecem pendentes item-a-item.

## Orientação para trabalho futuro

As primeiras mudanças substantivas vão definir as convenções do projeto. Conforme elas chegarem:

- Registre aqui a(s) linguagem(ns), framework, gerenciador de pacotes e os comandos de build/lint/test escolhidos.
- Substitua a nota de "Estado do projeto" assim que houver código real.
- Mantenha a terminologia consistente: **Scheduler (Escalonador)**, **block** (= unidade Executor + BOTs; **drone** Borg), **BOT** (= um projeto), **script** (= a unidade de execução; 1 spawn = 1 script), **`bot_ref`** (assinatura do projeto + assinatura do script), **ocorrência**, **exigência** (requisito de hardware), **capacidade** (recurso de máquina do block, ex. ollama — dependência classe B), **manifesto** (`manifest.json` canônico na raiz do projeto), **ordem de atividade** (o JSON Scheduler→Executor: `{occurrence_id, bot_ref, params, lease_s}`), **registro de publicação** (`(nome, versao) → project_hash` imutável no núcleo), **quadrante** (= unidade mais externa; uma instância completa da arquitetura), **subspace relay** (= link inter-quadrante; dead drop cego entre Rainhas, implementado no `bdd`).
- Vocabulário Borg (ver *Filosofia Borg*): **drone** (= block), **assimilação** (payload de provisionamento; modelo B = chave embarcada no payload), **designação** (= `block_name`), **regeneração** (= lease/redelivery), **canal sub-espacial** (= canal externo Executor↔Scheduler, transportado sobre Tor), **Rainha** (= Broker + Scheduler, a mente orquestradora central — mantida, mas **escondida, não cega**; "Rainha escondida"), **Locutus** (= armazém público, o *porta-voz cego* da Rainha na WAN).
