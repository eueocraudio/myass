"""O armazém público (Locutus) visto pelo núcleo — um dead drop cego de blobs.

O Locutus é o *porta-voz cego* da Rainha: guarda só ciphertext opaco em endereços
opacos (64-hex), nunca decifra nada. Decisão do dono: **hosting banal HTTPS** com
PUT/GET de blobs — a segurança não depende do hosting (o conteúdo é E2E; ver
``crypto``), então o lastro é descartável/substituível.

Aqui modelamos só o que o núcleo precisa: ``get`` / ``put`` / ``delete`` de um
blob por endereço. ``MemoryLocutus`` é para testes; ``HttpLocutus`` fala com um
armazém HTTPS comum (deve rodar via Tor preferencialmente — ver *Transporte*).
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from typing import Protocol


class LocutusStore(Protocol):
    def get(self, addr: str) -> bytes | None: ...
    def put(self, addr: str, blob: bytes) -> None: ...
    def delete(self, addr: str) -> None: ...


class MemoryLocutus:
    """Armazém em memória (testes / dev). Thread-safe."""

    def __init__(self):
        self._d: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def get(self, addr: str) -> bytes | None:
        with self._lock:
            return self._d.get(addr)

    def put(self, addr: str, blob: bytes) -> None:
        with self._lock:
            self._d[addr] = blob

    def delete(self, addr: str) -> None:
        with self._lock:
            self._d.pop(addr, None)


class HttpLocutus:
    """Armazém HTTPS banal: ``GET``/``PUT``/``DELETE`` de ``<base>/<addr>``.

    Sem TLS próprio nem cripto de transporte — o conteúdo já é E2E. Em produção o
    ``opener`` deve sair via Tor (SOCKS) por padrão (surface permitida). Não é
    exercitado pelos testes (precisa de um servidor).
    """

    def __init__(self, base_url: str, timeout: float = 30.0,
                 opener: urllib.request.OpenerDirector | None = None):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener or urllib.request.build_opener()

    def _url(self, addr: str) -> str:
        return f"{self.base}/{addr}"

    def get(self, addr: str) -> bytes | None:
        req = urllib.request.Request(self._url(addr), method="GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def put(self, addr: str, blob: bytes) -> None:
        req = urllib.request.Request(
            self._url(addr), data=blob, method="PUT",
            headers={"Content-Type": "application/octet-stream"},
        )
        with self._opener.open(req, timeout=self.timeout):
            pass

    def delete(self, addr: str) -> None:
        req = urllib.request.Request(self._url(addr), method="DELETE")
        try:
            with self._opener.open(req, timeout=self.timeout):
                pass
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
