"""GET HTTP simples em stdlib (urllib).

Convenção do myass: BOT que fala com serviço externo declara em ``apis`` e sai
**via Tor** (não entrega o IP do drone). Aqui o egress é direto por padrão; se a
env ``MYASS_PROXY`` estiver setada (ex. um http proxy sobre Tor), roteia por ela.
Sem dependências externas.
"""

import json
import os
import urllib.request

_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
DEFAULT_TIMEOUT = 30.0


def _opener():
    proxy = os.environ.get("MYASS_PROXY")
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def get_bytes(url, timeout=DEFAULT_TIMEOUT, headers=None):
    h = {"User-Agent": _UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with _opener().open(req, timeout=timeout) as resp:
        return resp.read()


def get_text(url, timeout=DEFAULT_TIMEOUT, headers=None):
    return get_bytes(url, timeout, headers).decode("utf-8", errors="replace")


def get_json(url, timeout=DEFAULT_TIMEOUT, headers=None):
    return json.loads(get_text(url, timeout, headers))


def put_bytes(url, data, headers=None, timeout=DEFAULT_TIMEOUT):
    """PUT cru (ex.: S3 presigned / WebDAV). Retorna (status, corpo bytes)."""
    h = {"User-Agent": _UA, "Content-Type": "application/octet-stream"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="PUT")
    with _opener().open(req, timeout=timeout) as resp:
        return getattr(resp, "status", 200), resp.read()


def post_multipart(url, field, filename, data, content_type="application/octet-stream",
                   headers=None, timeout=DEFAULT_TIMEOUT):
    """POST multipart/form-data de um arquivo (stdlib, sem deps). (status, corpo)."""
    boundary = "----myass" + os.urandom(8).hex()
    body = b"".join([
        ("--" + boundary + "\r\n").encode(),
        ('Content-Disposition: form-data; name="' + field + '"; filename="'
         + filename + '"\r\n').encode(),
        ("Content-Type: " + content_type + "\r\n\r\n").encode(),
        data, b"\r\n", ("--" + boundary + "--\r\n").encode(),
    ])
    h = {"User-Agent": _UA, "Content-Type": "multipart/form-data; boundary=" + boundary}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with _opener().open(req, timeout=timeout) as resp:
        return getattr(resp, "status", 200), resp.read()
