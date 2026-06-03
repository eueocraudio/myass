# Análise: myass × Tanenbaum (Sistemas Distribuídos)

Cruzamento do desenho do myass com o arcabouço de *Distributed Systems: Principles and Paradigms* / *Distributed Operating Systems* (Tanenbaum). Em cada tema: alinhamento, divergência e lacuna/risco exposto pela teoria.

## 0. Classificação (DOS × NOS × Middleware)
myass é um **sistema baseado em middleware** — não um DOS (sem kernel único / single-system-image). Camada de orquestração sobre máquinas autônomas (blocos), com visão coerente de rotinas/ocorrências. Correto, mas sem as garantias de um DOS (escalonamento global, DSM).

## 1. Metas: transparência, abertura, escalabilidade
**Transparência (8 formas):** acesso ✅, localização ✅ (nomes por hash, Escalonador resolve), migração ✅ (BOT baixado sob demanda), relocação ⚠️ (não tratamos mover execução viva), replicação ✅ (blocos = unidade replicável; BOTs content-addressed idênticos), concorrência ✅, falha ⚠️ (parcial: lease/redelivery + catch), persistência ✅ (Mongo+ring).
**Abertura:** protocolo próprio fechado = divergência consciente (segurança/sigilo sobre interoperabilidade).
**Escalabilidade:** usa as 3 técnicas de Tanenbaum — esconder latência (broker retorna `[]` + loader async), distribuição (partição por classe MEM×CPU), replicação/cache (ring sobre Mongo; blocos replicados).
⚠️ **Crítica central:** componentes centralizados limitam escala. myass tem **Escalonador e broker centrais** = gargalo/SPOF lógico, adotado de propósito (intermediação=segurança). Mitigação: Mongo é escalável; o Escalonador é o ponto a vigiar sob carga.
**Falácias:** acerta ao rejeitar "a rede é segura". Vigiar "topologia não muda" (blocos entram/saem), latência/banda (padding+fan-out aumentam tráfego).

## 2. Arquiteturas
Estilo event/shared-data + message-queuing; request-reply sobre filas. Híbrido (núcleo central + blocos na borda), não P2P. **Inversão cliente-servidor:** Executor disca e puxa — padrão canônico de Tanenbaum para atravessar firewall/NAT e conectividade assimétrica. ✅ Forte alinhamento com "sem inbound".

## 3. Processos, virtualização, migração de código
**Code migration:** BOT-projeto baixado e executado = code-on-demand / weak mobility, receiver-initiated (applets). ✅ `bot_ref` resolve integridade do código migrado. **Virtualização:** guest/venv/docker = níveis de Tanenbaum. ⚠️ Só weak mobility (não move execução viva — strong mobility).

## 4. Comunicação
**MOM / message-queuing:** o broker é comunicação **persistente assíncrona** (mensagem sobrevive no Mongo; emissor/receptor não precisam estar ativos juntos). Mapeamento ~1:1. **Semântica RPC sob falha:** at-least-once + idempotência (resultado por `occurrence_id`) — aceitável porque idempotente, exatamente a justificativa da teoria. ⚠️ Sem comunicação em grupo/multicast (tudo em estrela pelo Escalonador) — perde propriedades úteis p/ replicação/tolerância.

## 5. Nomeação (forte aderência)
`block_hash = BLAKE2(chave pública)` = **self-certifying name** (SFS/secure naming). `bot_ref` = **content-addressed naming** (autovalidável). Manifesto+inventário = **attribute-based naming** (descoberta por atributos de hardware). ⚠️ Resolução de nomes flat **centralizada no Escalonador** (vs DHT descentralizado) — simples, mas central.

## 6. Coordenação
**Relógios/ordenação:** causalidade natural (resultado→próxima = happens-before). Log append-only **só no núcleo** ⇒ ordenação total por serialização central; lacuna de Lamport **menor que parece** *se o núcleo for o único escritor*. **Eleição/mutex:** indefinidos para réplicas do broker/Escalonador. ⚠️ Lacuna — mitigada apoiando no **replica set do MongoDB** (herda Raft/eleição). **Barreira:** `parent_id`+junção do loop = barrier synchronization. ✅

## 7. Consistência e replicação
Ring = cache/réplica em memória sobre Mongo ⇒ consistência fraca/eventual (janela; `[]`+loader trata). Blocos replicados + Mongo (sharding/replica set). BOTs content-addressed ⇒ workers **determinísticos/intercambiáveis** (requisito de replicação correta). ⚠️ Estado da ocorrência: janela de inconsistência se o Escalonador cair no tick — coberto por at-least-once+idempotência+lease, não transação forte.

## 8. Tolerância a falhas (cruzamento crítico)
Crash/omission ✅ (lease→redelivery). ⚠️⚠️ **Byzantine:** bloco comprometido está autenticado e roda o BOT certo, mas **pode mentir no resultado** — myass autentica/verifica código, não a correção do resultado. Teoria (BFT: replicação+votação/n-version) existiria; não usamos. Maior lacuna frente ao adversário estatal. Mitigação: execução replicada + votação p/ atividades críticas (determinismo via `bot_ref` viabiliza). **Commit distribuído:** não usamos 2PC (evita bloqueio do coordenador) — at-least-once+idempotência; idempotência vira **obrigatória**. **Recuperação:** ocorrência persistida = checkpoint; broker durável + log = message logging. ✅ Garantir persistência em pontos bem definidos (após cada tick).

## 9. Segurança (myass brilha)
**Canal seguro:** Noise KKpsk0 = autenticação mútua + chave de sessão efêmera (forward secrecy) + ChaCha20-Poly1305. Aderência total. **Distribuição de chaves:** rejeita KDC/PKI; usa troca física out-of-band — divergência justificada (elimina terceiro confiável). ⚠️ Custo: não escala (N² por par); mitigado com PSK por par, mas provisionamento físico pesa com crescimento. **Controle de acesso:** `bot_ref`/identidade ≈ capabilities. **Auditoria:** log append-only.

## Síntese — lacunas priorizadas
1. Falha bizantina / verificação de resultado (§8) — maior gap.
2. Coordenação de réplicas broker/Escalonador (§6) — apoiar no replica set do Mongo.
3. Componente central = gargalo/SPOF de escala (§1).
4. Escala da distribuição física de chaves (§9).
5. Atomicidade do "tick" sem 2PC ⇒ idempotência obrigatória + checkpoints (§8).
6. Ordenação do log — ok *se* o núcleo for único escritor (§6).
