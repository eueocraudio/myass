# install_quadrant.sh — guia de instalação de um quadrante

Instalação reproduzível e **sem assistência** de um quadrante myass (núcleo +
drone) sobre infra real, via `install_quadrant.sh`. Documenta exatamente o deploy
de produção (host `192.168.3.3`): **MongoDB 8.0 + Tor + pacote myass em venv +
unidades systemd**.

> Terminologia: **núcleo** = a Rainha (broker + scheduler + motor de workflow +
> borda GET/SET); **drone** = um block (Executor + BOTs). Ver `CLAUDE.md`.

## O que o script faz

Roda **no próprio host alvo** (Debian 12/13), como um usuário **com sudo**, a
partir da raiz do repositório, e executa 7 passos idempotentes:

1. **Pré-requisitos** — `gnupg`, `curl`, `python3-venv`, `python3-full`.
2. **MongoDB** (só se o núcleo roda neste host) — adiciona o repo oficial, instala
   `mongodb-org`, habilita e sobe o serviço (`127.0.0.1:27017`).
3. **Tor** — garante instalado e configura `ControlPort 9051` + `CookieAuthentication`
   no `/etc/tor/torrc` (para onion/egress); habilita e sobe.
4. **Pacote myass** — copia `src/`, `pyproject.toml`, `README.md` para `INSTALL_DIR`,
   cria um **venv** e instala `myass[tor]` (= `pymongo` + `cryptography` + `stem`).
   Valida os imports.
5. **Segredos** — copia os JSON de provisionamento (com chaves privadas estáticas)
   para `INSTALL_DIR/quadrante/` com `chmod 700/600`.
6. **systemd** — escreve `myass-core.service` e/ou `myass-drone.service`
   (`Restart=on-failure`, `PYTHONUNBUFFERED=1`, sobem no boot), habilita e sobe.
7. **Verificação** — confere serviços ativos, núcleo escutando `:8400`, e quantos
   drones se registraram no inventário do Mongo.

> **Idempotente:** reexecutar é seguro — não duplica o repo do Mongo, a linha do
> `ControlPort`, nem o venv; só reconcilia o que faltar.

## Pré-requisitos no host

- **Debian** com `apt` e um usuário com **sudo**.
- **Acesso à internet** (apt baixa Mongo/Tor; pip baixa as libs).
- **Nada mais.** Se `./quadrante/` **não existir**, o script **provisiona sozinho**
  (a parteira: cunha a estática do Scheduler + chaves/PSK de drone e admin +
  segredo de cliente) — `--host 127.0.0.1` por padrão (tudo numa máquina). Esses
  JSON **carregam chaves privadas** e ficam só em `./quadrante/` (gitignored).
  - Para **admin/drone em outra máquina**: provisione com `PROV_HOST=<IP da LAN>`
    e leve `admin-N.json`/`drone-N.json` **out-of-band** à outra máquina.
  - Instalação **só-drone** (`ROLES=drone`) não provisiona: precisa do
    `drone-N.json` vindo do provision do núcleo.

## Uso

Do diretório raiz do repo, **no host alvo**:

```bash
./install_quadrant.sh
```

### Variáveis de ambiente (defaults = o deploy atual)

| Variável | Default | Para quê |
|---|---|---|
| `ROLES` | `core drone` | papéis neste host: `core`, `drone`, ou ambos |
| `INSTALL_DIR` | `/opt/myass` | código + venv + configs |
| `SERVICE_USER` | `$USER` atual | usuário que roda as units systemd |
| `MONGO_VERSION` | `8.0` | canal do repo MongoDB |
| `MONGO_DISTRO` | `bookworm` | distro do repo (trixie usa bookworm: compatível) |
| `MONGO_URI` | `mongodb://127.0.0.1:27017/` | URI passada ao núcleo |
| `MONGO_DB` | `myass` | database |
| `CORE_CONFIG` | `./quadrante/core.json` | origem do JSON do núcleo |
| `DRONE_CONFIG` | `./quadrante/drone-0.json` | origem do JSON do drone |

### Exemplos

```bash
# Tudo numa máquina (o caso atual: núcleo + drone + mongo + tor)
./install_quadrant.sh

# Só o núcleo (instala Mongo); drones ficam noutras máquinas
ROLES=core ./install_quadrant.sh

# Só um drone (não instala Mongo); editar o endpoint no drone-N.json p/ o IP do núcleo
ROLES=drone DRONE_CONFIG=./quadrante/drone-1.json ./install_quadrant.sh
```

## Topologia: direto vs Tor

Quando **núcleo e drone estão na mesma máquina** (ou na mesma LAN da zona de
confiança), eles conversam por **transporte direto** (loopback/LAN) — sem Tor
entre eles, ganhando velocidade cheia. É a topologia das configs atuais
(`host 127.0.0.1`, `port 8400`, `transport: direct`).

O **Tor** é instalado mesmo assim porque serve a:
- **egress de BOTs** (atividades que declaram `apis` saem via Tor — não entregam o IP do drone);
- **serviço onion do núcleo** (`python -m myass.ops core --onion`), necessário só
  para **drones atrás de rede hostil/WAN** (aí o endpoint do drone vira o `.onion`).

**Drone em máquina separada:** ajuste `endpoint.host`/`port` no `drone-N.json` para
o IP/`.onion` do núcleo, e no `core.json` use `host: 0.0.0.0` (escuta na LAN) +
allowlist/firewall dos IPs dos drones. Ver *Canais seguros → Transporte* em `CLAUDE.md`.

## Layout instalado

```
/opt/myass/
├── src/myass/…            # o pacote
├── pyproject.toml
├── venv/                  # venv com myass[tor]
└── quadrante/             # chmod 700
    ├── core.json          # chmod 600 (chave privada do Scheduler)
    └── drone-0.json       # chmod 600 (chave privada estática do drone)

/etc/systemd/system/myass-core.service
/etc/systemd/system/myass-drone.service
```

## Operação

```bash
# estado e logs
systemctl status myass-core myass-drone
journalctl -u myass-core -f
journalctl -u myass-drone -f

# reiniciar / parar
sudo systemctl restart myass-drone
sudo systemctl stop myass-core

# checar o link e o inventário
ss -tnp | grep 8400                              # conexão drone<->núcleo ESTABLISHED
mongosh myass --quiet --eval 'db.inventory.find().toArray()'
```

## Próximo passo: publicar trabalho

A instalação sobe a infra e a malha núcleo↔drone, mas o drone começa **sem BOTs**
(`project_hashes: []`). Para rodar workflows é preciso o **cliente admin** (papel
publicador) publicar um BOT/workflow no núcleo:

```bash
python -m myass.ops admin --config ./quadrante/admin-0.json publish-bot ./bots/bot_cve
python -m myass.ops admin --config ./quadrante/admin-0.json publish-workflow ./wf.json
python -m myass.ops admin --config ./quadrante/admin-0.json start <workflow_hash> '{"texto":"..."}'
python -m myass.ops admin --config ./quadrante/admin-0.json list
```

O admin pode rodar de qualquer máquina provisionada como publicador (extra
`admin` p/ a GUI PySide6). O usuário final comum usa a **web PHP** (Cliente Parte
II), que informa a chave e cria ocorrências — cifra client-side, PHP cego.

## Solução de problemas

| Sintoma | Causa provável / ação |
|---|---|
| `provision não gerou core.json` | o auto-provision falhou; rode à mão `venv/bin/python -m myass.ops provision --out ./quadrante …` e veja o erro |
| `myass-core não subiu` | `journalctl -u myass-core` — em geral Mongo fora do ar ou URI errada |
| núcleo `NÃO escutando :8400` | veja o log; porta em uso? `host` na config? |
| `inventário: 0 drone(s)` | drone não fechou o handshake — confira `psk`/`scheduler_pub` baterem entre `core.json` e `drone-0.json`, e o `endpoint` do drone |
| drone reiniciando | `journalctl -u myass-drone` — endpoint inalcançável ou handshake recusado |
| Mongo não instala (trixie) | o canal `bookworm` é compatível; cheque egress p/ `repo.mongodb.org` |

Ver também `doc/DEPLOY.md` (operação manual e malha inter-quadrante) e `CLAUDE.md`
(arquitetura autoritativa).
