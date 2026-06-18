"""04_publish — publica o PDF num endpoint HTTP próprio e devolve a URL.

**Só executa o upload se houver path E token** configurados no env do drone;
senão **pula sem falhar** (a ocorrência conclui com o PDF disponível inline).

Configuração no env do drone (nada vai no pedido):
    MYASS_UPLOAD_URL     destino (path do upload). Sem ele → pula.
    MYASS_UPLOAD_AUTH    token / cabeçalho Authorization (ex.: "Bearer …"). Sem ele → pula.
    MYASS_UPLOAD_METHOD  PUT (default) | POST
    MYASS_UPLOAD_FIELD   nome do campo no POST multipart (default "file")
    MYASS_UPLOAD_APPEND_NAME  "1" → no PUT anexa "/<nome>" à URL (endpoint tipo
                              diretório/WebDAV). Default: PUT na URL EXATA (presigned).

PUT: sobe os bytes crus na URL exata (ideal p/ S3 presigned). POST: multipart/
form-data; a URL pública costuma vir no corpo. Sempre repassa o ``pdf`` (o painel
também visualiza/salva inline).
"""

import base64
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.http import post_multipart, put_bytes  # noqa: E402
from lib.io import run  # noqa: E402


def main(params, occ):
    pdf = (params or {}).get("pdf") or {}
    out = {"nome": pdf.get("nome", "relatorio_ips.pdf"), "total": params.get("total"),
           "gerado_em": params.get("gerado_em"), "pdf": pdf,
           "upload_url": None, "uploaded": False}

    url = os.environ.get("MYASS_UPLOAD_URL")
    token = os.environ.get("MYASS_UPLOAD_AUTH")
    if not url or not token:
        out["upload_nota"] = "upload desabilitado (faltam MYASS_UPLOAD_URL e/ou MYASS_UPLOAD_AUTH)"
        return out
    b64 = pdf.get("$b64")
    if not b64:
        out["upload_nota"] = "sem PDF para publicar"
        return out

    data = base64.b64decode(b64)
    nome = out["nome"]
    headers = {"Authorization": token}
    method = (os.environ.get("MYASS_UPLOAD_METHOD") or "PUT").upper()
    if method == "POST":
        field = os.environ.get("MYASS_UPLOAD_FIELD", "file")
        status, body = post_multipart(url, field, nome, data, "application/pdf", headers)
        public = body.decode("utf-8", "replace").strip() or url
    else:
        append = os.environ.get("MYASS_UPLOAD_APPEND_NAME", "").lower() in ("1", "true", "yes")
        target = (url.rstrip("/") + "/" + nome) if append else url
        status, _ = put_bytes(target, data, {**headers, "Content-Type": "application/pdf"})
        public = target

    out.update({"upload_url": public, "http_status": status, "uploaded": True})
    return out


if __name__ == "__main__":
    run(main)
