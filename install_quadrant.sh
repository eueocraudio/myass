#!/usr/bin/env bash
#
# install_quadrant.sh — instala um quadrante myass (núcleo + drone) sobre infra
# real, de forma idempotente e SEM assistência do Claude. Reproduz o deploy de
# produção: MongoDB 8.0 + Tor + pacote myass em venv + unidades systemd.
#
# RODE NO PRÓPRIO HOST ALVO (Debian 12/13), como um usuário COM sudo, a partir
# da raiz do repositório (a pasta que contém pyproject.toml). TURNKEY:
#
#     ./install_quadrant.sh
#
# NÃO exige passos manuais: se ``./quadrante/`` não existir, o script **provisiona
# sozinho** (a parteira: cunha a estática do Scheduler + chaves/PSK de drone e
# admin + segredo de cliente) e segue. Pré-requisitos: Debian com apt, sudo e
# acesso à internet (apt + pip).
#
# Configurável por variáveis de ambiente (defaults turnkey numa máquina só):
#
#     ROLES="core drone"     papéis a instalar neste host (core / drone / ambos)
#     INSTALL_DIR=/opt/myass mantenedor do código + venv + configs
#     SERVICE_USER=<você>    usuário que roda os serviços systemd (default: $USER)
#     MONGO_VERSION=8.0      canal do repo oficial do MongoDB
#     MONGO_DISTRO=bookworm  distro do repo MongoDB (trixie usa bookworm: compatível)
#     PROV_HOST=127.0.0.1    host que o provision grava (loopback p/ tudo-numa-máquina;
#                            use o IP da LAN se o admin/drone for em outra máquina)
#     PORT=8400              porta Noise do núcleo
#     DRONES=1 ADMINS=1      quantos provisionar
#     CLIENTS="web"          clientes (segredo por cliente) a cunhar
#     LOCUTUS_URL=           URL do Locutus público (opcional; pode setar depois no core.json)
#     CORE_CONFIG / DRONE_CONFIG  caminho dos JSON (default ./quadrante/*)
#
# Núcleo e drone co-localizados conversam por loopback (transporte "direct",
# sem Tor entre eles). Tor é instalado/garantido para egress de BOTs e onion.
# Instalação só-drone (ROLES=drone) NÃO provisiona: precisa do drone-N.json
# vindo do provision do núcleo (out-of-band).
#
set -euo pipefail

# ---- parâmetros ------------------------------------------------------------
ROLES="${ROLES:-core drone}"
INSTALL_DIR="${INSTALL_DIR:-/opt/myass}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "$SERVICE_USER")}"
MONGO_VERSION="${MONGO_VERSION:-8.0}"
MONGO_DISTRO="${MONGO_DISTRO:-bookworm}"
MONGO_URI="${MONGO_URI:-mongodb://127.0.0.1:27017/}"
MONGO_DB="${MONGO_DB:-myass}"
# parâmetros do auto-provision (parteira), usados só se ./quadrante/ não existir:
PROV_HOST="${PROV_HOST:-127.0.0.1}"
PORT="${PORT:-8400}"
DRONES="${DRONES:-1}"
ADMINS="${ADMINS:-1}"
CLIENTS="${CLIENTS:-web}"
LOCUTUS_URL="${LOCUTUS_URL:-}"

# raiz do repo = a pasta deste script (contém pyproject.toml)
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
CORE_CONFIG="${CORE_CONFIG:-$REPO_DIR/quadrante/core.json}"
DRONE_CONFIG="${DRONE_CONFIG:-$REPO_DIR/quadrante/drone-0.json}"

want() { case " $ROLES " in *" $1 "*) return 0;; *) return 1;; esac; }
log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mERRO: %s\033[0m\n' "$*" >&2; exit 1; }

[ -f "$REPO_DIR/pyproject.toml" ] || die "rode da raiz do repo (pyproject.toml não encontrado em $REPO_DIR)"
command -v sudo  >/dev/null || die "sudo é necessário"
command -v apt-get >/dev/null || die "este script é para Debian/apt"
# Núcleo ausente → provisionamos depois (após o venv). Drone-só (sem core neste
# host) NÃO pode provisionar: o drone-N.json tem de vir do provision do núcleo.
if want drone && ! want core && [ ! -f "$DRONE_CONFIG" ]; then
  die "instalação só-drone exige $DRONE_CONFIG (copie do provision do núcleo, out-of-band)"
fi

log "Plano: ROLES='$ROLES' · INSTALL_DIR=$INSTALL_DIR · SERVICE_USER=$SERVICE_USER"

# ---- 1. pré-requisitos de sistema -----------------------------------------
log "Pré-requisitos (gnupg, curl, python3-venv)"
sudo apt-get install -y -q gnupg curl python3-venv python3-full >/dev/null

# ---- 2. MongoDB (só se o núcleo roda aqui) --------------------------------
if want core; then
  if ! command -v mongod >/dev/null; then
    log "Instalando MongoDB $MONGO_VERSION (repo oficial, canal $MONGO_DISTRO)"
    curl -fsSL "https://www.mongodb.org/static/pgp/server-${MONGO_VERSION}.asc" \
      | sudo gpg --yes -o "/usr/share/keyrings/mongodb-server-${MONGO_VERSION}.gpg" --dearmor
    echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-${MONGO_VERSION}.gpg ] https://repo.mongodb.org/apt/debian ${MONGO_DISTRO}/mongodb-org/${MONGO_VERSION} main" \
      | sudo tee "/etc/apt/sources.list.d/mongodb-org-${MONGO_VERSION}.list" >/dev/null
    sudo apt-get update -q
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q mongodb-org
  else
    log "MongoDB já instalado ($(mongod --version | head -1))"
  fi
  sudo systemctl enable --now mongod
fi

# ---- 3. Tor (ControlPort para onion/egress) -------------------------------
log "Tor (ControlPort 9051 + CookieAuthentication)"
if ! command -v tor >/dev/null; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q tor
fi
if ! sudo grep -qE '^ControlPort 9051' /etc/tor/torrc; then
  printf '\n# myass: canal sub-espacial (onion control)\nControlPort 9051\nCookieAuthentication 1\n' \
    | sudo tee -a /etc/tor/torrc >/dev/null
  sudo systemctl restart tor
fi
sudo systemctl enable --now tor

# ---- 4. pacote myass em venv ----------------------------------------------
log "Instalando o pacote myass em $INSTALL_DIR (venv, extra [tor])"
sudo mkdir -p "$INSTALL_DIR"
sudo chown "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
# copia o código (sem .git, caches, segredos crus, venv antigo)
rsync -a --delete \
  --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'venv' --exclude 'quadrante' \
  "$REPO_DIR/src" "$REPO_DIR/pyproject.toml" "$REPO_DIR/README.md" "$INSTALL_DIR/" \
  2>/dev/null || {
    # fallback sem rsync
    sudo -u "$SERVICE_USER" cp -r "$REPO_DIR/src" "$REPO_DIR/pyproject.toml" "$REPO_DIR/README.md" "$INSTALL_DIR/"
  }
[ -d "$INSTALL_DIR/venv" ] || python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -q "$INSTALL_DIR"'[tor]'
"$INSTALL_DIR/venv/bin/python" -c 'import myass, pymongo, cryptography, stem; from myass.ops import nodes; print("imports OK")'

# ---- 4b. provisionar (parteira) se ainda não há configs -------------------
# Turnkey: sem ./quadrante/, o próprio script cunha as identidades/segredos
# (core + drones + admins + clientes). Já com o venv, usamos o myass instalado.
if want core && [ ! -f "$CORE_CONFIG" ]; then
  log "Provisionando o quadrante (parteira) → $REPO_DIR/quadrante  (host=$PROV_HOST:$PORT)"
  "$INSTALL_DIR/venv/bin/python" -m myass.ops provision \
    --out "$REPO_DIR/quadrante" --drones "$DRONES" --admins "$ADMINS" \
    --clients $CLIENTS --host "$PROV_HOST" --port "$PORT" \
    ${LOCUTUS_URL:+--locutus "$LOCUTUS_URL"}
  chmod 700 "$REPO_DIR/quadrante" 2>/dev/null || true
  echo "  configs geradas (chaves privadas — distribua drone-N/admin-N out-of-band se forem outras máquinas)"
fi
want core  && { [ -f "$CORE_CONFIG" ]  || die "provision não gerou $CORE_CONFIG"; }
want core  && { [ -f "$DRONE_CONFIG" ] || die "provision não gerou $DRONE_CONFIG (DRONES>=1?)"; }

# ---- 5. segredos (configs com chaves privadas estáticas) ------------------
log "Copiando configs para $INSTALL_DIR/quadrante (chmod 700/600)"
mkdir -p "$INSTALL_DIR/quadrante"; chmod 700 "$INSTALL_DIR/quadrante"
want core  && install -m 600 "$CORE_CONFIG"  "$INSTALL_DIR/quadrante/core.json"
want drone && install -m 600 "$DRONE_CONFIG" "$INSTALL_DIR/quadrante/drone-0.json"

# ---- 6. unidades systemd ---------------------------------------------------
mk_unit() {  # $1=arquivo  $2=conteúdo
  echo "$2" | sudo tee "/etc/systemd/system/$1" >/dev/null
}

if want core; then
  log "Unidade systemd: myass-core"
  mk_unit myass-core.service "[Unit]
Description=myass nucleo (Rainha: broker + scheduler + workflow + borda)
After=network-online.target mongod.service
Wants=network-online.target
Requires=mongod.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
Environment=PYTHONUNBUFFERED=1
Environment=MYASS_MONGO_URI=$MONGO_URI
Environment=MYASS_MONGO_DB=$MONGO_DB
ExecStart=$INSTALL_DIR/venv/bin/python -m myass.ops core --config $INSTALL_DIR/quadrante/core.json
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target"
fi

if want drone; then
  log "Unidade systemd: myass-drone"
  # se o núcleo está noutra máquina, o drone só depende da rede
  DRONE_AFTER="network-online.target"
  DRONE_WANTS="network-online.target"
  if want core; then DRONE_AFTER="$DRONE_AFTER myass-core.service"; DRONE_WANTS="$DRONE_WANTS myass-core.service"; fi
  mk_unit myass-drone.service "[Unit]
Description=myass drone (Executor + BOTs)
After=$DRONE_AFTER
Wants=$DRONE_WANTS

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$INSTALL_DIR/venv/bin/python -m myass.ops drone --config $INSTALL_DIR/quadrante/drone-0.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target"
fi

sudo systemctl daemon-reload
want core  && sudo systemctl enable --now myass-core
want core  && sleep 4
want drone && sudo systemctl enable --now myass-drone
sleep 5

# ---- 7. verificação --------------------------------------------------------
log "Verificação"
want core  && { systemctl is-active --quiet mongod      && echo "  mongod      : active" || die "mongod não subiu"; }
systemctl is-active --quiet tor && echo "  tor         : active" || echo "  tor         : INATIVO (verifique)"
if want core; then
  systemctl is-active --quiet myass-core && echo "  myass-core  : active" || die "myass-core não subiu (journalctl -u myass-core)"
  ss -ltn 2>/dev/null | grep -q ':8400' && echo "  núcleo      : escutando :8400" || echo "  núcleo      : NÃO escutando :8400"
fi
if want drone; then
  systemctl is-active --quiet myass-drone && echo "  myass-drone : active" || die "myass-drone não subiu (journalctl -u myass-drone)"
fi
if want core && command -v mongosh >/dev/null; then
  n=$(mongosh "$MONGO_DB" --quiet --eval 'db.inventory.countDocuments({})' 2>/dev/null || echo '?')
  echo "  inventário  : $n drone(s) registrado(s)"
fi

log "Pronto. Quadrante instalado em $INSTALL_DIR."
cat <<EOF
  Operação:
    systemctl status myass-core myass-drone
    journalctl -u myass-core -f
  Próximo passo p/ rodar trabalho: publicar um BOT/workflow via o cliente admin
    (módulo 3), ex.: python -m myass.ops admin --config <admin.json> publish-bot ./bots/bot_cve
EOF
