# myass

**Assistente Pessoal Local** — plataforma de orquestração de rotinas (inclusive de
IA) que roda inteiramente na infraestrutura privada e fechada do usuário. Filosofia
Borg: uma **Rainha escondida** (broker + scheduler + motor de workflow) que lê o
pedido e dirige **drones** (executores), com um **Locutus** público e cego como
única face na WAN. Arquitetura completa em [`doc/arquitetura.md`](doc/arquitetura.md);
especificação autoritativa de design em [`CLAUDE.md`](CLAUDE.md).

## Estado

Sistema implementado por inteiro em **Python** (suíte com **191 testes**; rodado
sobre infra real — MongoDB + processos separados + sockets + Locutus PHP/MySQL +
`bdd` HTTPS). Um **quadrante** completo está montado e em produção: Rainha
(broker/scheduler/Nassi) + borda GET/SET + canal Noise/Tor + drone + cliente admin
PySide6 (`madmin`) + web pública (PHP/MySQL) com painel de ocorrências (estrutograma
Nassi colorido + PDF inline).

## Instalar tudo — turnkey (recomendado)

Um único orquestrador pergunta os dados, grava no `~/.env`, **testa serviços e
acessos** e só então chama os instaladores:

```bash
git clone <repo> myass && cd myass
python3 terraform.py
```

O `terraform.py` (só stdlib):
1. pergunta o que instalar (núcleo+drone / admin+`madmin` / web pública) e os dados;
2. grava no `~/.env` (e gera o `client/web/.env` de runtime);
3. **preflight**: `sudo`, internet (apt/pip/Mongo repo), `python3-venv`, login FTP
   (web), presença dos scripts — **se algo obrigatório falhar, nada é instalado**;
4. chama os `.sh` (que fazem o resto sozinhos) e implanta a web.

## Instalar por partes (manual)

Os instaladores são **idempotentes** e **auto-suficientes** (auto-provisionam):

```bash
# 1) Núcleo + drone (Debian + sudo). Se ./quadrante/ não existir, PROVISIONA sozinho
#    (cunha chaves/segredos). Instala MongoDB 8.0 + Tor + venv + unidades systemd.
./install_quadrant.sh
#    Tudo numa máquina = loopback (default). Admin/drone remoto: PROV_HOST=<IP da LAN>.
#    Detalhes e variáveis: install_quadrant.md

# 2) Painel admin + comando global `madmin` (na máquina do admin)
./install_admin.sh
#    Instala o venv [admin], o comando `madmin` e grava MADMIN_* no ~/.env.
#    Detalhes: install_admin.md

# 3) Web pública (Locutus PHP+MySQL) — precisa de hosting próprio (PHP+MySQL+FTP)
cd client/web
python3 gen_env.py        # gera client/web/.env a partir do ~/.env (ou use o terraform.py)
python3 deploy.py --setup # sobe por FTPS + cria a tabela (setup.php, uso único)
```

Operar:
```bash
systemctl status myass-core myass-drone     # serviços
madmin                                       # painel admin conectado (vars no ~/.env)
python3 -m myass.ops admin --config quadrante/admin-0.json publish-bot ./bots/bot_cve
```

## O que cada parte é

- **Núcleo (Rainha)** `python -m myass.ops core` — broker + scheduler + motor de
  workflow + borda GET/SET + autorização. Escuta Noise só na LAN; só **sai** para a WAN.
- **Drone (block)** `python -m myass.ops drone` — Executor + BOTs; disca para a Rainha.
- **Admin** `madmin` / `python -m myass.ops admin` — publica BOTs/workflows, cria/edita
  **chaves de cliente** (`nome.chave` + workflows permitidos) e acompanha ocorrências.
- **Web (Locutus)** `client/web/` — face pública PHP+MySQL: a pessoa informa a chave,
  vê seus workflows e cria ocorrências; a cifra é **no browser**, o servidor é **cego**.

## Desenvolvimento

```bash
# suíte completa (offscreen é obrigatório por causa do test_admin_gui)
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 -m unittest discover -s tests

./install.sh   # apt + pip extras + roda a suíte (dev)
```

Os testes usam `mongomock`/in-process e **não exigem** MongoDB/Tor rodando.
Demo fim-a-fim sobre infra real: `examples/run_real_quadrant.py`.

## Estrutura

```
terraform.py        orquestrador turnkey (pergunta → testa → instala)
install_quadrant.sh núcleo + drone + mongo + tor (auto-provisiona) · install_quadrant.md
install_admin.sh    painel admin + comando madmin                  · install_admin.md
src/myass/
  broker/      fila multinível (classes MEM×CPU + ring + lastro Mongo)
  scheduler/   despacho + lease/regeneração + servidor Noise (a Rainha)
  workflow/    motor Nassi (block/action/decision/loop + catch) + validação de inputs
  edge/        borda GET/SET (AEAD ChaCha20, long-poll) + Locutus + registro de clientes
  executor/    drone (workdir, runner, plano de dados, projeto/venv)
  noise/       canal sub-espacial (Noise KKpsk0/NNpsk0 + Tor)
  proto/       protocolo de aplicação (envelope)
  publish/     registro de publicação (imutável, (nome,versao)→hash)
  core/        montagem do núcleo (GET→engine→SET) + chaves de cliente + autorização
  relay/       inter-quadrante (X3DH + subspace relay sobre o bdd)
  client/      admin.py + admin_gui.py (PySide6: Tela de Workflow, ocorrências, PDF)
  ops/         provision + nodes + CLI (python -m myass.ops ...)
  storage/     Mongo/GridFS
bots/bot_cve/  BOT de exemplo (relatório PDF rico de CVEs) — ver seu README
bots/bot_ip/   BOT de exemplo (IPs de WAN → Shodan + AbuseIPDB → PDF → upload) — ver seu README
client/web/    Locutus web (PHP + MySQL): SPA + blob store cego + deploy por FTP
tests/         unittest (191)
doc/           arquitetura.md, DEPLOY.md, diagramas, análises
```
