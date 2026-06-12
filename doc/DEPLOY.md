# Deploy / Operação — rodar um quadrante (e a malha) sobre infra real

A **lógica** está completa e testada em código (`tests/`, 171 testes) e já foi
**comprovadamente executada sobre infra real** (ver `examples/run_real_quadrant.py`).
Este guia cobre subir os serviços e fiar os processos. Tudo em Python; sem
containers.

## 0. Instalar

```bash
./install.sh            # apt: tor, MongoDB, MariaDB+PHP, Qt; pip3: o pacote + extras
```

## 1. Serviços de infra

- **MongoDB** (lastro + GridFS). Single node ou replica set (recomendado em prod,
  para o *stateless-sobre-MongoDB*):
  ```bash
  mongod --dbpath /var/lib/myass --bind_ip 127.0.0.1            # single
  # replica set: --replSet rs0 nos nós, depois rs.initiate(); use a URI:
  #   export MYASS_MONGO_URI="mongodb://h1,h2,h3/?replicaSet=rs0"
  ```
- **Tor** (canal sub-espacial via onion; só para travessia de WAN — LAN/localhost
  usa transporte direto). Habilite ControlPort:
  ```
  # /etc/tor/torrc
  ControlPort 9051
  CookieAuthentication 1
  ```
- **MariaDB + PHP** (Locutus web, Cliente Parte II): ver `client/web/README.md`
  (criar o banco com `db/schema.sql`, deploy por FTP, `.env`).

## 2. Provisionar (estação parteira, offline)

```bash
python -m myass.ops provision --out ./quadrante \
    --drones 2 --admins 1 --clients alice bob --host 0.0.0.0 --port 8400
```
Gera `quadrante/core.json`, `drone-*.json`, `admin-*.json`, `clients.json`. As
**chaves privadas** estão nas configs — distribua-as **out-of-band** (mídia física)
para cada nó. Opcional: inclua `interpreter_workflow_hash` no `core.json` para
habilitar pedidos em linguagem natural (drone VAI).

## 3. Subir o núcleo e os drones

```bash
# núcleo (a Rainha):
python -m myass.ops core --config quadrante/core.json --onion   # --onion: publica o HS v3

# cada drone (em sua máquina; o endpoint do core na config):
python -m myass.ops drone --config quadrante/drone-0.json
```

## 4. Publicar e operar (admin)

```bash
python -m myass.ops admin --config quadrante/admin-0.json publish-bot ./bots/bot_cve
python -m myass.ops admin --config quadrante/admin-0.json publish-workflow ./wf.json
python -m myass.ops admin --config quadrante/admin-0.json start <workflow_hash> '{"texto":"..."}'
python -m myass.ops admin --config quadrante/admin-0.json list
```

O usuário final usa a **web PHP** (informa a chave, vê os workflows, cria
ocorrências); a cifra é client-side, o PHP é cego.

## 5. Malha inter-quadrante (subspace relay)

Cada Rainha fala com as parceiras pelo `bdd` (dead drop cego sobre Tor). Provisione
a tabela de roteamento por par (`{quadrante_id → {endpoint onion do bdd, segredo
-raiz, PSK, IK_sig}}`) out-of-band e use `relay.bdd_transport.BddRelayTransport`
com o `DeadDropClient` do projeto `bdd`. Validado de ponta a ponta sobre um `bdd`
real (HTTPS) — X3DH + Noise por dentro, transporte cego por fora.

## Pendências de pesquisa (não-bloqueantes)

- **Cover traffic / timing** (intra e inter-quadrante) — segue como item de
  pesquisa (defesas estilo stem-and-fluff); ver *Pontos em aberto* em `CLAUDE.md`.
- **Bridges + pluggable transports** (obfs4/meek) para drone atrás de rede hostil.
