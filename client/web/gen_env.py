#!/usr/bin/env python3
"""gen_env.py — gera client/web/.env a partir de ~/.env (vars *_WELLINGTON_TEC_BR).

Uso único, local. Não contém segredos (lê de ~/.env). Pode apagar depois.
"""
import os
import stat

src = os.path.expanduser("~/.env")
env = {}
for line in open(src, encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip()

S = "_WELLINGTON_TEC_BR"
ftp_host = env["FTP_HOST" + S].replace("ftp://", "").replace("ftps://", "").strip("/")
out = (
    "# GERADO de ~/.env — NAO comitar (gitignored). Locutus web -> wellington.tec.br\n"
    # O app PHP roda no MESMO servidor do MySQL (Hostinger), então conecta por
    # 127.0.0.1 — o IP remoto (MYSQL_HOST) passa por um caminho/proxy com teto de
    # conexões por hora; localhost foge disso. O IP remoto fica só no ~/.env, para
    # ferramentas externas (ex.: diagnóstico).
    "DB_HOST=127.0.0.1\n"
    f"DB_NAME={env['MYSQL_DATA' + S]}\n"
    f"DB_USER={env['MYSQL_USER' + S]}\n"
    f"DB_PASS={env['MYSQL_PASS' + S]}\n"
    "BLOB_TTL=86400\n\n"
    f"FTP_HOST={ftp_host}\n"
    f"FTP_USER={env['FTP_USER' + S]}\n"
    f"FTP_PASS={env['FTP_PASS' + S]}\n"
    "FTP_DIR=/public_html\n"
    "FTP_TLS=1\n"
)
dst = os.path.join(os.path.dirname(__file__), ".env")
with open(dst, "w", encoding="utf-8") as f:
    f.write(out)
os.chmod(dst, stat.S_IRUSR | stat.S_IWUSR)  # 0600

print("client/web/.env gerado (0600). Chaves (sem expor valores):")
for ln in out.splitlines():
    if "=" in ln and not ln.startswith("#"):
        k, _, v = ln.partition("=")
        print(f"  {k:9} = " + ("<vazio>" if not v else f"<set, {len(v)} chars>"))
