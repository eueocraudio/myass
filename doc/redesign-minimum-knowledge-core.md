# Re-design proposto: "núcleo de conhecimento mínimo"

> **STATUS: PROPOSTA — pendente de decisão do dono.** Nada aqui está adotado.
> Surgiu do cruzamento Tanenbaum + Monero (ver `analise-tanenbaum.md`, `analise-monero.md`).
> As decisões firmes atuais continuam valendo (ver `CLAUDE.md`).

## Axioma do re-design
Tanenbaum e Monero apontam para o **mesmo ponto fraco — o núcleo central** (Tanenbaum: gargalo/SPOF de escala; Monero: ponto único de vigilância/coerção). Eixo: **manter a centralização que o dono quer, mas o núcleo passa a saber o mínimo e falhar o mínimo.**

Preserva as decisões firmes: inside-out, broker próprio Python, Noise (KKpsk0/NNpsk0), chave física, identidade por hash, workflow/ocorrência, editor PySide6.

## Camadas repensadas (NOVO marcado)

**0. Substrato de anonimato de rede (NOVO — Monero §1):** Tor/I2P em GET/SET↔store e bloco↔Escalonador; indireção stem/fluff (Dandelion++) no caminho bloco→núcleo; cover traffic imitando a distribuição real (timing/tamanho).

**1. Canais seguros (PRESERVA + estende):** Noise + framing + chave física mantidos. NOVO: a identidade que **autentica** (chave estática) ≠ a identidade que **aparece/loga**.

**2. Identidade/nomeação (Monero §3/§4 + Tanenbaum §5):** PRESERVA `bot_ref` content-addressed e chave estática como raiz de auth. NOVO: **handle one-time rotativo** por sessão (dono reconhece via view-key; observador/log veem handles rotativos) → acaba linkabilidade. NOVO: **anti-replay key-image-like** (determinístico mas não-linkável).

**3. Núcleo como ROTEADOR CEGO (maior mudança — Monero §0/§5):** NOVO criptografia **fim-a-fim requisitante→bloco executor**; Escalonador **roteia sem ler conteúdo**. Requisição leva **cabeçalho de roteamento mínimo** (classe MEM×CPU) em claro (ou provado por ZK) + **corpo cifrado p/ o executor**. Apreender o núcleo vaza metadado de roteamento, não a vida do usuário. NOVO/futuro: ZK p/ validar sem ler.

**4. Broker e coordenação (Tanenbaum §6/§8):** PRESERVA messageria multi-nível + Mongo. NOVO: **consenso/eleição apoiados no replica set do MongoDB** (herda Raft); **broker e Escalonador stateless sobre o Mongo** → qualquer instância cai e outra assume (ataca o SPOF lógico).

**5. Execução e verificação (Tanenbaum §8 Byzantine):** PRESERVA blocos/Executor/virtualização/verificação por `bot_ref`. NOVO: **votação N-blocos opcional** p/ atividades **críticas** (mesma `bot_ref`+entrada em N blocos, compara/vota; determinismo do content-addressing viabiliza). NOVO: **idempotência como invariante obrigatória** (chaveada por passo da ocorrência + key-image).

**6. Orquestração (PRESERVA + checkpoint):** workflow/ocorrência/encadeamento/catch/fan-out mantidos. NOVO: **checkpoint formal após cada tick** (recuperação a estado consistente).

**7. Confiança e auditoria (Monero §6):** NOVO **separação ver×agir** (view/act capabilities; formaliza participante×usuário). Log append-only legível por view-key, guardando **key-images+metadados, não conteúdo**. PRESERVA log append-only com **escritor único no núcleo** (garante ordenação total — fecha lacuna de relógios sem Lamport).

## Decisões em aberto (o dono precisa escolher)
1. **Roteador cego (E2E até o executor)** — aceitar núcleo que roteia sem ler (perde inspeção de conteúdo sem ZK)?
2. **Identidade rotativa + key-image** — adotar unlinkability (some `block_hash` persistente do fio/log)?
3. **Votação N-blocos** anti-bizantina — ligar p/ atividades críticas (custo N×) ou fora?
4. **Tor/I2P + cover traffic** — obrigatórios na borda ou configuráveis?
5. **Stateless sobre Mongo** — deixar o Mongo ser âncora de consenso e Escalonador/broker descartáveis?
