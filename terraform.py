#!/usr/bin/env python3
"""terraform.py — orquestrador turnkey do myass.

Pergunta todos os dados necessários, grava no ``~/.env``, **testa os serviços e
acessos** e — SÓ se tudo o que é obrigatório passar — chama os instaladores
``.sh`` (núcleo+drone, admin) e o deploy da web pública.

Só stdlib (``ftplib``/``urllib``/``socket``/``subprocess``) — coerente com o
projeto (sem dependências). Rode como **usuário comum** (os .sh usam ``sudo``):

    python3 terraform.py
"""
from __future__ import annotations

import ftplib
import getpass
import os
import socket
import subprocess
import sys
import urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
ENVF = os.path.expanduser("~/.env")

# ---- UI -------------------------------------------------------------------
def info(m): print(f"\n\033[1;36m==> {m}\033[0m")
def okmsg(m): print(f"  \033[1;32m✓\033[0m {m}")
def errmsg(m): print(f"  \033[1;31m✗ {m}\033[0m")
def die(m): errmsg(m); sys.exit(1)


def ask(prompt, default=None, secret=False):
    sfx = f" [{default}]" if default not in (None, "") else ""
    while True:
        raw = (getpass.getpass if secret else input)(f"{prompt}{sfx}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default


def yesno(prompt, default=True):
    d = "S/n" if default else "s/N"
    v = input(f"{prompt} [{d}]: ").strip().lower()
    return default if not v else v.startswith(("s", "y"))


# ---- ~/.env (atualiza sem destruir o resto) -------------------------------
def env_update(updates: dict):
    lines = open(ENVF, encoding="utf-8").read().splitlines() if os.path.exists(ENVF) else []
    seen, out = set(), []
    for ln in lines:
        if "=" in ln and not ln.lstrip().startswith("#"):
            k = ln.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}"); seen.add(k); continue
        out.append(ln)
    extra = [k for k in updates if k not in seen]
    if extra:
        out.append("# myass — gerado por terraform.py")
        out += [f"{k}={updates[k]}" for k in extra]
    open(ENVF, "w", encoding="utf-8").write("\n".join(out).rstrip("\n") + "\n")
    os.chmod(ENVF, 0o600)


# ---- testes de acesso (preflight) -----------------------------------------
def t_sudo():
    if subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
        return True
    print("  (sudo precisa de senha — valide agora)")
    return subprocess.run(["sudo", "true"]).returncode == 0


def t_http(url, timeout=12):
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True                      # respondeu (404/403 etc.) = alcançável
    except Exception:
        return False


def t_venv():
    try:
        import venv  # noqa: F401
        return True
    except Exception:
        return False


def t_ftp(w):
    try:
        host = w["FTP_HOST"].replace("ftp://", "").replace("ftps://", "").strip("/")
        ftp = ftplib.FTP_TLS(host) if w["FTP_TLS"] == "1" else ftplib.FTP(host)
        ftp.login(w["FTP_USER"], w["FTP_PASS"])
        if w["FTP_TLS"] == "1":
            ftp.prot_p()
        ftp.cwd(w["FTP_DIR"])
        ftp.quit()
        return True
    except Exception as e:
        errmsg(f"FTP: {e}")
        return False


def run_sh(script, env_extra):
    env = {**os.environ, **{k: str(v) for k, v in env_extra.items()}}
    info(f"Executando {script}  ({' '.join(f'{k}={v}' for k, v in env_extra.items())})")
    r = subprocess.run(["bash", os.path.join(REPO, script)], env=env)
    if r.returncode != 0:
        die(f"{script} falhou (código {r.returncode}).")


# ---- main -----------------------------------------------------------------
def main():
    print("\033[1mmyass · terraform.py — provisionamento turnkey\033[0m")
    if os.geteuid() == 0:
        die("rode como usuário comum (NÃO root) — os .sh usam sudo quando preciso.")

    # 1) o que instalar
    do_core = yesno("Instalar NÚCLEO + DRONE nesta máquina?", True)
    do_admin = yesno("Instalar o PAINEL ADMIN + comando 'madmin' nesta máquina?", True)
    do_web = yesno("Implantar a WEB pública (Locutus PHP+MySQL) por FTP?", False)

    core = {}
    if do_core:
        info("Dados do núcleo/drone")
        core["PROV_HOST"] = ask("Host que o núcleo escuta (127.0.0.1 = tudo nesta máquina; ou IP da LAN)", "127.0.0.1")
        core["PORT"] = ask("Porta Noise do núcleo", "8400")
        core["DRONES"] = ask("Quantos drones provisionar", "1")
        core["CLIENTS"] = ask("Clientes (segredos) a cunhar (separados por espaço)", "web")
        core["INSTALL_DIR"] = ask("Diretório de instalação", "/opt/myass")
        if do_web:
            core["LOCUTUS_URL"] = ""     # preenchido abaixo

    web = {}
    if do_web:
        info("Dados da web pública (Locutus)")
        web["LOCUTUS_URL"] = ask("URL pública do Locutus (ex.: https://seu-dominio)")
        web["FTP_HOST"] = ask("FTP host (IP ou domínio)")
        web["FTP_USER"] = ask("FTP user")
        web["FTP_PASS"] = ask("FTP pass", secret=True)
        web["FTP_DIR"] = ask("FTP dir (webroot)", "/public_html")
        web["FTP_TLS"] = "1" if yesno("FTP com TLS (FTPS)?", True) else "0"
        web["DB_HOST"] = ask("MySQL host visto pelo app PHP (use 127.0.0.1 no mesmo servidor)", "127.0.0.1")
        web["DB_NAME"] = ask("MySQL database")
        web["DB_USER"] = ask("MySQL user")
        web["DB_PASS"] = ask("MySQL pass", secret=True)
        web["BLOB_TTL"] = ask("TTL dos blobs em segundos", "86400")
        if do_core:
            core["LOCUTUS_URL"] = web["LOCUTUS_URL"]

    # 2) grava no ~/.env (master) + client/web/.env (runtime do deploy.py)
    info(f"Gravando configuração em {ENVF} (0600)")
    upd = {}
    if do_web:
        upd.update({"MYASS_LOCUTUS_URL": web["LOCUTUS_URL"],
                    "FTP_HOST_MYASS": web["FTP_HOST"], "FTP_USER_MYASS": web["FTP_USER"],
                    "FTP_PASS_MYASS": web["FTP_PASS"], "FTP_DIR_MYASS": web["FTP_DIR"],
                    "FTP_TLS_MYASS": web["FTP_TLS"],
                    "MYSQL_HOST_MYASS": web["DB_HOST"], "MYSQL_DATA_MYASS": web["DB_NAME"],
                    "MYSQL_USER_MYASS": web["DB_USER"], "MYSQL_PASS_MYASS": web["DB_PASS"]})
        # .env de runtime que o deploy.py lê (DB_HOST=127.0.0.1 foge do limite remoto)
        wenv = (f"DB_HOST={web['DB_HOST']}\nDB_NAME={web['DB_NAME']}\n"
                f"DB_USER={web['DB_USER']}\nDB_PASS={web['DB_PASS']}\n"
                f"BLOB_TTL={web['BLOB_TTL']}\n\nFTP_HOST={web['FTP_HOST']}\n"
                f"FTP_USER={web['FTP_USER']}\nFTP_PASS={web['FTP_PASS']}\n"
                f"FTP_DIR={web['FTP_DIR']}\nFTP_TLS={web['FTP_TLS']}\n")
        p = os.path.join(REPO, "client", "web", ".env")
        open(p, "w", encoding="utf-8").write(wenv); os.chmod(p, 0o600)
        okmsg(f"client/web/.env gravado ({len(wenv)} bytes)")
    env_update(upd)
    okmsg(f"{ENVF} atualizado")

    # 3) PREFLIGHT — testa serviços e acesso (obrigatórios gateiam a instalação)
    info("Preflight — testando serviços e acesso")
    checks = []  # (nome, ok, obrigatório)
    checks.append(("sudo", t_sudo(), True))
    checks.append(("python3-venv", t_venv(), True))
    checks.append(("internet · pypi.org", t_http("https://pypi.org"), True))
    if do_core:
        checks.append(("internet · repo.mongodb.org", t_http("https://repo.mongodb.org"), True))
        checks.append(("install_quadrant.sh presente", os.path.isfile(os.path.join(REPO, "install_quadrant.sh")), True))
    if do_admin:
        checks.append(("install_admin.sh presente", os.path.isfile(os.path.join(REPO, "install_admin.sh")), True))
    if do_web:
        checks.append(("FTP login + cwd", t_ftp(web), True))
        checks.append(("Locutus URL alcançável", t_http(web["LOCUTUS_URL"]), False))  # pode não existir ainda

    for nome, passed, mand in checks:
        (okmsg if passed else errmsg)(f"{nome}{'' if passed else '  (FALHOU)'}{'' if mand else '  (opcional)'}")
    reprovados = [n for n, p, m in checks if m and not p]
    if reprovados:
        die("Preflight reprovado em: " + ", ".join(reprovados) + ". NADA foi instalado.")
    okmsg("Preflight OK — todos os testes obrigatórios passaram.")

    # 4) só agora chama os instaladores .sh
    if do_core:
        roles = "core drone"
        run_sh("install_quadrant.sh", {k: v for k, v in {
            "ROLES": roles, "PROV_HOST": core["PROV_HOST"], "PORT": core["PORT"],
            "DRONES": core["DRONES"], "CLIENTS": core["CLIENTS"],
            "INSTALL_DIR": core["INSTALL_DIR"],
            "LOCUTUS_URL": core.get("LOCUTUS_URL", ""),
        }.items() if v != ""})
    if do_admin:
        env_admin = {}
        # admin noutra máquina que o núcleo? aponte madmin para o host certo.
        if do_core and core["PROV_HOST"] not in ("127.0.0.1", "localhost"):
            env_admin["CORE_HOST"] = core["PROV_HOST"]
        run_sh("install_admin.sh", env_admin)
    if do_web:
        info("Deploy da web (FTP + setup.php cria a tabela no MySQL)")
        r = subprocess.run([sys.executable, os.path.join(REPO, "client", "web", "deploy.py"), "--setup"])
        if r.returncode != 0:
            die("deploy da web falhou.")
        # valida o MySQL de verdade: setup.php conecta no DB e cria a tabela
        url = web["LOCUTUS_URL"].rstrip("/") + "/setup.php"
        try:
            body = urllib.request.urlopen(url, timeout=20).read().decode("utf-8", "replace")
            (okmsg if "OK" in body else errmsg)(f"setup.php → {body.splitlines()[0] if body else '(vazio)'}")
        except Exception as e:
            errmsg(f"não consegui acionar {url}: {e} (rode-o no navegador uma vez)")

    info("Concluído. ✅")
    if do_core:
        print("  systemctl status myass-core myass-drone")
    if do_admin:
        print("  madmin            # abre o painel conectado")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("cancelado.")
