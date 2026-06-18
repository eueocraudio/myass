#!/usr/bin/env bash
#
# install_admin.sh — instala o cliente Admin (Cliente Parte I) numa máquina,
# de forma idempotente e SEM assistência do Claude. É o painel do publicador/
# administrador: publica BOTs/workflows, inicia e acompanha ocorrências, autora
# workflows (GUI PySide6). Fala com o núcleo pelo canal Noise (transporte direto
# na LAN, ou .onion via Tor).
#
# RODE NA MÁQUINA DO ADMIN, como o usuário comum (NÃO root — o venv fica do
# usuário), a partir da raiz do repositório (contém pyproject.toml e quadrante/):
#
#     ./install_admin.sh                       # usa quadrante/admin-0.json como está
#     CORE_HOST=192.168.3.3 ./install_admin.sh # aponta o admin para o núcleo na LAN
#
# TURNKEY: além do venv, instala o comando global **madmin** (abre o painel já
# conectado) e grava as vars MADMIN_* no ~/.env — sem passos manuais.
#
# Pré-requisito: a config do admin em ./quadrante/admin-0.json — gerada pelo
# install_quadrant.sh (que auto-provisiona) na MESMA máquina, ou copiada
# out-of-band do provision do núcleo se o admin for noutra máquina. (Não dá para
# auto-provisionar o admin aqui: as chaves têm de ser as MESMAS do núcleo.)
#
# Configurável por variáveis de ambiente:
#
#     VENV=.venv                 caminho do virtualenv (do usuário)
#     ADMIN_CONFIG=./quadrante/admin-0.json   config do admin
#     CORE_HOST=<vazio>          se setado, reescreve o endpoint p/ direct CORE_HOST:CORE_PORT
#     CORE_PORT=8400             porta do núcleo
#     SYSTEM_SITE=1              venv com --system-site-packages (reusa PySide6 do sistema)
#     INSTALL_MADMIN=1           instala o comando global `madmin` (0 desliga)
#
set -euo pipefail

VENV="${VENV:-.venv}"
ADMIN_CONFIG="${ADMIN_CONFIG:-./quadrante/admin-0.json}"
CORE_HOST="${CORE_HOST:-}"
CORE_PORT="${CORE_PORT:-8400}"
SYSTEM_SITE="${SYSTEM_SITE:-1}"
INSTALL_MADMIN="${INSTALL_MADMIN:-1}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mERRO: %s\033[0m\n' "$*" >&2; exit 1; }

[ -f pyproject.toml ] || die "rode da raiz do repo (pyproject.toml não encontrado em $REPO_DIR)"
[ -f "$ADMIN_CONFIG" ] || die "config do admin ausente: $ADMIN_CONFIG (rode o provision --admins)"
[ "$(id -u)" -ne 0 ] || die "rode como usuário comum, NÃO root (o venv deve ser do usuário)"

# ---- 1. pré-req de venv ----------------------------------------------------
if ! python3 -c 'import venv' 2>/dev/null; then
  log "Instalando python3-venv (sudo)"
  sudo apt-get install -y -q python3-venv python3-full >/dev/null
fi

# ---- 2. limpar resíduo de instalação com sudo (venv/egg-info de root) ------
# Um 'sudo pip install -e' anterior deixa esses caminhos como root → o pip do
# usuário cai para --user e a build editable falha. Toma posse se preciso.
for p in "$VENV" src/*.egg-info; do
  if [ -e "$p" ] && [ ! -O "$p" ]; then
    log "Tomando posse de $p (estava de outro dono)"
    sudo chown -R "$(id -un):$(id -gn)" "$p"
  fi
done

# ---- 3. venv ---------------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  log "Criando venv em $VENV (SYSTEM_SITE=$SYSTEM_SITE)"
  if [ "$SYSTEM_SITE" = "1" ]; then python3 -m venv --system-site-packages "$VENV"
  else python3 -m venv "$VENV"; fi
else
  log "Reusando venv existente em $VENV"
fi

# ---- 4. instalar o pacote com o extra admin (PySide6) ----------------------
log "Instalando myass[admin] (editable)"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e ".[admin]"
"$VENV/bin/python" -c 'import myass, pymongo, cryptography, PySide6; from myass.client import admin, admin_gui; print("admin + GUI OK · PySide6", PySide6.__version__)'

# ---- 5. apontar o admin para o núcleo (opcional) ---------------------------
if [ -n "$CORE_HOST" ]; then
  log "Apontando o endpoint do admin p/ direct $CORE_HOST:$CORE_PORT"
  "$VENV/bin/python" - "$ADMIN_CONFIG" "$CORE_HOST" "$CORE_PORT" <<'PY'
import json, sys
f, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
d = json.load(open(f))
d["endpoint"] = {"transport": "direct", "host": host, "port": port}
json.dump(d, open(f, "w"), ensure_ascii=False, indent=1)
print("endpoint ->", d["endpoint"])
PY
fi

# ---- 6. teste de handshake (best-effort) -----------------------------------
log "Testando handshake contra o núcleo (catalog)"
if "$VENV/bin/python" -m myass.ops admin --config "$ADMIN_CONFIG" catalog 2>/tmp/admin_test.err; then
  echo "  handshake OK — o admin alcança o núcleo."
else
  echo "  (núcleo inalcançável agora — instalação OK, mas confira o endpoint/núcleo)"
  sed 's/^/    /' /tmp/admin_test.err 2>/dev/null | tail -4 || true
fi
rm -f /tmp/admin_test.err

# ---- 7. comando global `madmin` (turnkey) ---------------------------------
if [ "$INSTALL_MADMIN" = "1" ]; then
  log "Instalando o comando 'madmin' (abre o painel já conectado)"
  case "$VENV" in /*) ABS_VENV="$VENV";; *) ABS_VENV="$REPO_DIR/$VENV";; esac
  ABS_CFG="$(cd "$(dirname "$ADMIN_CONFIG")" && pwd)/$(basename "$ADMIN_CONFIG")"
  EP="$("$VENV/bin/python" - "$ABS_CFG" <<'PY'
import json, sys
e = (json.load(open(sys.argv[1])).get("endpoint") or {})
print(e.get("host", "127.0.0.1"), e.get("port", 8400))
PY
)"
  MH="${EP%% *}"; MP="${EP##* }"
  [ -n "$CORE_HOST" ] && MH="$CORE_HOST"
  sudo mkdir -p /usr/local/lib/myass
  sudo tee /usr/local/lib/myass/madmin_launch.py >/dev/null <<'PY'
#!/usr/bin/env python3
"""madmin — abre o Painel do Administrador conectado ao núcleo (lê MADMIN_*)."""
import json, os, sys
from myass.client.admin import AdminClient
from myass.client import admin_gui
from myass.noise import primitives as P
cfg = json.load(open(os.environ["MADMIN_CONFIG"], encoding="utf-8"))
ep = dict(cfg.get("endpoint") or {}); ep.setdefault("transport", "direct")
if os.environ.get("MADMIN_HOST"): ep["host"] = os.environ["MADMIN_HOST"]
if os.environ.get("MADMIN_PORT"): ep["port"] = int(os.environ["MADMIN_PORT"])
client = AdminClient(ep, bytes.fromhex(cfg["prologue"]),
    P.load_private(bytes.fromhex(cfg["static_priv"])),
    bytes.fromhex(cfg["static_pub"]), bytes.fromhex(cfg["scheduler_pub"]),
    bytes.fromhex(cfg["psk"]))
with client:
    sys.exit(admin_gui.main(client))
PY
  sudo tee /usr/local/bin/madmin >/dev/null <<SH
#!/usr/bin/env bash
set -euo pipefail
ENVF="\${HOME}/.env"
if [ -f "\$ENVF" ]; then
  while IFS= read -r line; do
    case "\$line" in
      MADMIN_*=*) k=\${line%%=*}; [ -z "\${!k:-}" ] && export "\$line" || true ;;
    esac
  done < "\$ENVF"
fi
exec "$ABS_VENV/bin/python" /usr/local/lib/myass/madmin_launch.py "\$@"
SH
  sudo chmod 755 /usr/local/bin/madmin
  ENVF="$HOME/.env"; touch "$ENVF"
  if ! grep -q '^MADMIN_CONFIG=' "$ENVF"; then
    printf '\n# myass madmin (Painel do Administrador)\nMADMIN_CONFIG=%s\nMADMIN_HOST=%s\nMADMIN_PORT=%s\n' \
      "$ABS_CFG" "$MH" "$MP" >> "$ENVF"
  fi
  echo "  'madmin' instalado · config=$ABS_CFG · núcleo=$MH:$MP"
fi

log "Pronto. Admin instalado em $VENV."
cat <<EOF
  Comando: madmin            # abre o painel conectado (vars no ~/.env)
  Uso (CLI):
    $VENV/bin/python -m myass.ops admin --config $ADMIN_CONFIG catalog
    $VENV/bin/python -m myass.ops admin --config $ADMIN_CONFIG publish-bot ./bots/bot_cve
    $VENV/bin/python -m myass.ops admin --config $ADMIN_CONFIG publish-workflow ./wf.json
    $VENV/bin/python -m myass.ops admin --config $ADMIN_CONFIG start <workflow_hash> '{"texto":"..."}'
    $VENV/bin/python -m myass.ops admin --config $ADMIN_CONFIG list
  Uso (GUI PySide6):
    $VENV/bin/python -c "from myass.client import admin_gui; admin_gui.main()"
EOF
