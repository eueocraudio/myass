#!/usr/bin/env python3
"""deploy.py — sobe o Locutus web (Cliente, Parte II) por FTP/FTPS.

Lê as credenciais do `.env` (ao lado deste arquivo), conecta no host (FTPS se
FTP_TLS=1, senão FTP puro) e envia APENAS os arquivos de runtime para FTP_DIR:

    index.php  lib.php  .htaccess  index.html  js/app.js  js/myass-crypto.js

O `.env` que vai ao servidor é SANITIZADO: só as variáveis que o index.php usa em
runtime (DB_*, BLOB_TTL). As credenciais de FTP NUNCA sobem ao servidor público.

Uso:
    python3 deploy.py            # sobe tudo
    python3 deploy.py --dry-run  # só mostra o que faria
    python3 deploy.py --env /caminho/para/.env

Sem dependências externas — só a stdlib (ftplib).
"""
from __future__ import annotations

import argparse
import ftplib
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Arquivos de runtime servidos pelo host. (path local relativo, path remoto)
RUNTIME_FILES = [
    "index.php",
    "lib.php",
    ".htaccess",
    "index.html",
    "js/app.js",
    "js/myass-crypto.js",
]

# Variáveis do .env que o index.php precisa em runtime — só estas sobem ao servidor.
SERVER_ENV_KEYS = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS", "BLOB_TTL")


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        sys.exit(f"erro: {path} não existe. Copie .env.example para .env e preencha.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        # tira comentário inline e espaços
        env[k.strip()] = v.split("#", 1)[0].strip()
    return env


def require(env: dict[str, str], *keys: str) -> None:
    missing = [k for k in keys if not env.get(k) or env[k] == "trocar"]
    if missing:
        sys.exit("erro: preencha no .env: " + ", ".join(missing))


def sanitized_env_bytes(env: dict[str, str]) -> bytes:
    """O .env que vai ao servidor: só DB_*/BLOB_TTL, nunca FTP_*."""
    lines = [f"{k}={env[k]}" for k in SERVER_ENV_KEYS if env.get(k)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def connect(env: dict[str, str]) -> ftplib.FTP:
    host = env["FTP_HOST"].replace("ftp://", "").replace("ftps://", "").strip("/")
    user, pw = env["FTP_USER"], env["FTP_PASS"]
    if env.get("FTP_TLS", "1") not in ("0", "false", "no", ""):
        ftp: ftplib.FTP = ftplib.FTP_TLS(host)
        ftp.login(user, pw)
        ftp.prot_p()  # protege também o canal de dados
        print(f"  conectado (FTPS) a {host}")
    else:
        ftp = ftplib.FTP(host)
        ftp.login(user, pw)
        print(f"  conectado (FTP puro — sem TLS) a {host}")
    return ftp


def ensure_dir(ftp: ftplib.FTP, path: str) -> None:
    """cd até `path`, criando os diretórios que faltarem."""
    if not path or path == "/":
        if path == "/":
            ftp.cwd("/")
        return
    if path.startswith("/"):
        ftp.cwd("/")
    for part in path.strip("/").split("/"):
        try:
            ftp.cwd(part)
        except ftplib.error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def upload(ftp: ftplib.FTP, data: bytes, remote: str, dry: bool) -> None:
    print(f"  {'[dry] ' if dry else ''}→ {remote} ({len(data)} bytes)")
    if dry:
        return
    # cria subdir (js/) se necessário
    if "/" in remote:
        sub, _, _ = remote.rpartition("/")
        cur = ftp.pwd()
        ensure_dir(ftp, sub)
        ftp.storbinary(f"STOR {remote.rsplit('/', 1)[1]}", io.BytesIO(data))
        ftp.cwd(cur)
    else:
        ftp.storbinary(f"STOR {remote}", io.BytesIO(data))


def main() -> None:
    ap = argparse.ArgumentParser(description="deploy do Locutus web por FTP/FTPS")
    ap.add_argument("--env", default=str(HERE / ".env"), help="caminho do .env")
    ap.add_argument("--dry-run", action="store_true", help="não envia, só mostra")
    ap.add_argument("--setup", action="store_true",
                    help="sobe também setup.php (cria a tabela; autoremove no 1º acesso)")
    args = ap.parse_args()

    env = load_env(Path(args.env))
    require(env, "FTP_HOST", "FTP_USER", "FTP_PASS", "DB_USER", "DB_PASS")
    remote_dir = env.get("FTP_DIR", "/public_html")

    # confere que os arquivos locais existem antes de conectar
    payload: list[tuple[str, bytes]] = []
    for rel in RUNTIME_FILES:
        f = HERE / rel
        if not f.is_file():
            sys.exit(f"erro: arquivo local ausente: {f}")
        payload.append((rel, f.read_bytes()))
    if args.setup:
        payload.append(("setup.php", (HERE / "setup.php").read_bytes()))
    payload.append((".env", sanitized_env_bytes(env)))  # .env sanitizado por último

    print(f"deploy → {env['FTP_HOST']}:{remote_dir}  ({len(payload)} arquivos)")
    if args.dry_run:
        for rel, data in payload:
            upload(None, data, rel, dry=True)  # type: ignore[arg-type]
        print("dry-run: nada foi enviado.")
        return

    ftp = connect(env)
    try:
        ensure_dir(ftp, remote_dir)
        for rel, data in payload:
            upload(ftp, data, rel, dry=False)
    finally:
        ftp.quit()
    print("deploy concluído.")


if __name__ == "__main__":
    main()
