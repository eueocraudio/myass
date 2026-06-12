#!/usr/bin/env bash
# install.sh — instala TUDO que o myass precisa (pacotes de sistema via apt +
# dependências Python via pip3) e roda os testes.
#
# Sistema (apt):  python3/pip/venv, tor, MongoDB, MariaDB+PHP (Locutus web),
#                 e bibliotecas Qt para a GUI do admin (PySide6).
# Python (pip3):  o pacote myass + pymongo, cryptography, stem, PySide6, mongomock.
#
# Uso:  ./install.sh [opções]
#   --no-apt      não instala pacotes de sistema (só pip + testes)
#   --no-test     não roda a suíte de testes
#   --user        pip install no site do usuário (~/.local) em vez de venv
#   --system      pip install no site do sistema
#   --no-venv     não cria .venv (usa --user/--system ou PYTHONPATH)
#   -h, --help    mostra esta ajuda
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"

MODE="venv"; DO_APT=1; DO_TEST=1
for arg in "$@"; do case "$arg" in
  --no-apt) DO_APT=0 ;; --no-test) DO_TEST=0 ;;
  --user) MODE="user" ;; --system) MODE="system" ;; --no-venv) MODE="none" ;;
  -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
  *) echo "opção desconhecida: $arg (--help)"; exit 64 ;;
esac; done

if [[ -t 1 ]]; then B="\033[1m"; G="\033[32m"; Y="\033[33m"; R="\033[31m"; X="\033[0m"
else B=""; G=""; Y=""; R=""; X=""; fi
step(){ printf "\n${B}==> %s${X}\n" "$*"; }
ok(){ printf "  ${G}✓${X} %s\n" "$*"; }
warn(){ printf "  ${Y}!${X} %s\n" "$*"; }
die(){ printf "  ${R}✗ %s${X}\n" "$*" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
SUDO=""; [[ $EUID -ne 0 ]] && have sudo && SUDO="sudo"

# ---- 1. pacotes de sistema (apt) --------------------------------------
if [[ $DO_APT -eq 1 ]]; then
  step "Instalando pacotes de sistema (apt)"
  if have apt-get; then
    PKGS=(
      python3 python3-pip python3-venv
      tor                                   # canal sub-espacial (serviço onion)
      mariadb-server php-cli php-mysql       # Locutus web (Cliente, Parte II)
      git curl
      # bibliotecas para a GUI Qt do admin (PySide6)
      libgl1 libegl1 libxkbcommon0 libdbus-1-3 fontconfig
    )
    $SUDO apt-get update -y
    $SUDO apt-get install -y "${PKGS[@]}" || warn "alguns pacotes apt falharam"
    # MongoDB: o pacote varia por distro (mongodb / mongodb-org / mongodb-server).
    if $SUDO apt-get install -y mongodb-server 2>/dev/null \
       || $SUDO apt-get install -y mongodb 2>/dev/null; then
      ok "MongoDB instalado via apt"
    else
      warn "MongoDB não está nos repos apt — instale o 'mongodb-org' (repo oficial):"
      warn "  https://www.mongodb.com/docs/manual/installation/"
    fi
    ok "pacotes de sistema instalados"
  else
    warn "apt-get não encontrado — pulando pacotes de sistema (instale-os à mão)."
  fi
fi

# ---- 2. pré-requisito Python ------------------------------------------
step "Checando Python"
have python3 || die "python3 é obrigatório."
PYV="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
python3 -c 'import sys;raise SystemExit(0 if sys.version_info>=(3,13) else 1)' \
  || die "python $PYV; é exigido >= 3.13 (alvo 3.14)."
ok "python $PYV"

# ---- 3. dependências Python (pip3) ------------------------------------
step "Instalando o pacote myass + dependências (pip3)"
PYBIN="python3"
if [[ "$MODE" == "venv" ]]; then
  if python3 -m venv --system-site-packages .venv >/tmp/myass_venv.log 2>&1; then
    PYBIN="$ROOT/.venv/bin/python"; ok "virtualenv em .venv"
  else warn "venv falhou — usando --user"; MODE="user"; fi
fi
EXTRA=(); [[ "$MODE" == "user" ]] && EXTRA+=("--user")
# Extras: test (mongomock), admin (PySide6), tor (stem). cryptography+pymongo são base.
if "$PYBIN" -m pip install "${EXTRA[@]}" -e ".[test,admin,tor]" >/tmp/myass_pip.log 2>&1; then
  ok "instalado myass + pymongo, cryptography, stem, PySide6, mongomock"
else
  warn "pip -e .[...] falhou (ver /tmp/myass_pip.log); tentando deps avulsas"
  "$PYBIN" -m pip install "${EXTRA[@]}" pymongo cryptography stem PySide6 mongomock \
    >/tmp/myass_pip.log 2>&1 || die "pip falhou (ver /tmp/myass_pip.log)."
fi
PYTHONPATH="$ROOT/src" "$PYBIN" -c 'import myass; from myass.ops import provision_quadrante' \
  && ok "pacote importa" || die "o pacote falhou ao importar."

# ---- 4. testes --------------------------------------------------------
if [[ $DO_TEST -eq 1 ]]; then
  step "Rodando a suíte de testes"
  if QT_QPA_PLATFORM=offscreen PYTHONPATH="$ROOT/src" "$PYBIN" \
       -m unittest discover -s tests >/tmp/myass_test.log 2>&1; then
    ok "$(tail -3 /tmp/myass_test.log | grep -E '^(OK|Ran)' | tr '\n' ' ')"
  else tail -25 /tmp/myass_test.log >&2; die "testes falharam (/tmp/myass_test.log)"; fi
fi

# ---- 5. próximos passos -----------------------------------------------
step "Pronto — próximos passos"
cat <<EOF
  1) Suba os serviços de infra:
       sudo systemctl start mongod        # ou: mongod --dbpath ...
       sudo systemctl start tor           # ControlPort 9051 p/ o serviço onion
  2) Provisione um quadrante (estação parteira, offline):
       python -m myass.ops.provision  ...    # cunha chaves/configs (ver ops/)
  3) Suba o núcleo e os drones a partir das configs (ver src/myass/ops/nodes.py:
       CoreNode / DroneNode). Locutus web: ver client/web/ (deploy FTP).

  Rodar os testes manualmente:
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 -m unittest discover -s tests
EOF
