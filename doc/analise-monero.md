# Análise: myass × Rede Monero (privacidade)

Cruzamento do myass com a arquitetura de rede/privacidade do Monero (CryptoNote + RingCT + camada de rede). Domínio diferente (não é criptomoeda), mas **mesmo modelo de ameaça** (adversário de vigilância poderoso) — as técnicas transferem. Política monetária = N/A.

## 0. Filosofia: a tensão central
Monero resiste a "o governo vê tudo" com **descentralização radical + nenhuma parte confiável** (nenhum nó é onisciente). myass resolve o mesmo problema com a estratégia **oposta**: um **núcleo fechado confiável**.
⚠️ **Cruzamento mais importante:** no myass o **núcleo é onisciente** — descriptografa (vê texto claro), guarda log de auditoria, inventário, chaves. Doutrina Monero: esse núcleo é o que o Estado apreende/coage; caído ele, a privacidade colapsa. Não virar descentralizado, mas **reduzir o que o núcleo (e a rede) sabe**.

## 1. Privacidade de rede — Dandelion++, Tor/I2P (maior lição)
Monero: **Dandelion++** (stem único antes de fluff broadcast) desvincula transação do IP de origem; **Tor/I2P** escondem IPs.
myass cifra conteúdo e tamanho, mas **vaza quem-fala-com-quem-e-quando**. Lição: **Tor/I2P em GET/SET e bloco↔Escalonador**; **indireção stem/fluff** no caminho bloco→núcleo; **cover traffic**. **Maior buraco de privacidade atual.**

## 2. Untraceability do emissor — ring signatures / decoys → cover traffic
Ring: entrada real assinada junto a decoys, observador não sabe qual é real.
Mapeamento: **cover traffic** (decoys via GET/SET e no canal) p/ não distinguir trabalho real de ruído. ⚠️ Decoy precisa **imitar a distribuição estatística real** (timing/tamanho) — seleção de decoys do Monero usa distribuição gama; decoy ingênuo é deanonimizável.

## 3. Unlinkability — stealth/one-time addresses → identidade rotativa
Monero: cada transação gera endereço one-time; ninguém liga duas ao mesmo destinatário.
⚠️ Fraqueza do myass: `block_hash = BLAKE2(chave estática)` é **identificador persistente, linkável no tempo** (mesmo cifrado). Lição: **identificadores one-time/rotativos por sessão** — a chave estática **autentica** por dentro, mas o que aparece no fio/log **rotaciona** (estilo stealth). Estende forward secrecy de chave para **identidade**.

## 4. Key image — dedup/anti-duplo-uso sem revelar identidade
Monero: key image = valor determinístico único do output gasto; rede impede double-spend mas **não liga** a key image ao output (unicidade sem revelação).
🎯 Conexão: a intuição antiga do dono ("hash aleatória, ver se já processou") + nosso nonce anti-replay + `occurrence_id` ≈ key image. Lição: o tag de dedup/replay pode ser **determinístico porém não-linkável** — anti-replay **sem** registrar identificador correlacionável.

## 5. RingCT / Pedersen + Bulletproofs — provar sem revelar (ZK)
Monero esconde valores (compromissos de Pedersen) e prova validade em zero-knowledge.
Mapeamento (futuro/avançado): **provar propriedades sem revelar** — bloco prova que está autorizado a uma classe / requisição bem-formada / dentro de cota, **sem o núcleo ler**. Ataca o "núcleo onisciente" (§0). Custo alto; direção futura.

## 6. View key × spend key — separar auditar de executar
Monero separa ver (view key) de gastar (spend key).
✅ Mapeamento imediato: **ver × agir**. O modelo participante×usuário do projeto já é isso. Log de auditoria legível por view-key, **guardando key-images+metadados, não conteúdo** — auditável sem aumentar superfície de coerção.

## 7. Sybil resistance — PoW/RandomX × chave física
Monero é permissionless ⇒ precisa de PoW (RandomX) p/ Sybil/consenso.
✅ Divergência limpa: myass é permissioned — **chave provisionada fisicamente JÁ é a resistência a Sybil**. Sem PoW, sem custo energético.

## 8. Fungibilidade / indistinguibilidade
Monero: tudo privado ⇒ moedas fungíveis, nada "marcável".
Alvo no myass: **toda requisição/trabalho parecer igual**. Padding 256 = passo. Faltam timing uniforme + cover traffic.

## 9. Linhagem criptográfica (já alinhados)
Monero: Ed25519/Curve25519 + Keccak + ring sigs + Bulletproofs. myass: X25519 + BLAKE2 + ChaCha20-Poly1305. ✅ Mesma família de curva (Curve25519, djb), linhagem não-NIST. Monero usa Keccak (SHA-3/NIST); myass usa BLAKE2 (não-NIST) — escolha até mais purista.

## 10. Nó remoto / metadados
Monero: nó remoto não rouba fundos (chaves locais) mas aprende metadados / pode mentir. Mitiga com nó próprio + Tor.
Mapeamento: Escalonador ("nó remoto") aprende metadados do bloco. Reforça §1 (Tor/I2P) e §3 (identidade rotativa).

## Síntese — lacunas priorizadas
1. Privacidade de rede (§1) — Tor/I2P + relay stem/fluff; *a maior*.
2. Núcleo onisciente (§0) — reduzir o que sabe; ZK (§5); log sem conteúdo.
3. Identidade persistente linkável (§3) — handles one-time/rotativos.
4. Anti-replay unlinkable (§4) — tag key-image-like.
5. Cover traffic com distribuição realista (§2/§8).
6. Separação ver×agir (§6).

**Meta-lição:** Tanenbaum cobra o núcleo como SPOF de escala; Monero cobra o núcleo como ponto único de vigilância/coerção. As duas críticas apontam para o **mesmo lugar — o núcleo**.
