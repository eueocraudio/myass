"""Cripto da borda do cliente — o selo E2E entre cliente e a Rainha escondida.

Decisão do dono (ver *Borda do cliente* em ``CLAUDE.md``): AEAD
**ChaCha20-Poly1305** (não AES — a pilha é não-NIST e o cliente é de baixa
capacidade, sem AES-NI), **simétrico puro, sem DH**: um **segredo de 32 bytes por
cliente**, cunhado na parteira e provisionado out-of-band. Os primitivos vêm da
lib auditada ``cryptography`` — **nunca feitos à mão** (um AEAD caseiro vaza os
canais laterais que um Estado-nação explora).

Do segredo derivam-se, por BLAKE2s com chaveamento + *person* (separação de
domínio), quatro coisas independentes — duas chaves de cifra e dois endereços de
dead drop (request/response), no padrão cego do Locutus (o endereço não revela a
chave; o servidor guarda só blob opaco em endereço opaco)::

    k_req   = BLAKE2s(key=secret, person="k-req")     # cifra do pedido
    k_resp  = BLAKE2s(key=secret, person="k-resp")    # cifra da resposta
    a_req   = BLAKE2s(key=secret, person="a-req")     # endereço do pedido (64-hex)
    a_resp  = BLAKE2s(key=secret, person="a-resp")    # endereço da resposta

Limites honestos (registrados, não escondidos): sem DH e sem catraca, um segredo
vazado decifra todo o tráfego daquele cliente; o nonce é aleatório (sem contador
no dispositivo). O replay é neutralizado **do lado do núcleo** pela dedup
idempotente de ``request_id`` (ver ``gateway``/``registry``), custo zero para o
cliente. Tudo isto é o estado final aceito para um cliente "que pode ser um
Arduino".
"""

from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

SECRET_LEN = 32
NONCE_LEN = 12

# Separação de domínio do AEAD (autenticada como AAD, presa à direção + versão).
_AAD_REQ = b"myass/edge/v1|req"
_AAD_RESP = b"myass/edge/v1|resp"
_AAD_CAT = b"myass/edge/v1|cat"
_AAD_OCC = b"myass/edge/v1|occ"      # índice de ocorrências do cliente
_AAD_OCCD = b"myass/edge/v1|occd"    # detalhe de uma ocorrência

# Rótulos BLAKE2s 'person' (<= 8 bytes).
_P_KEY_REQ = b"k-req"
_P_KEY_RESP = b"k-resp"
_P_KEY_CAT = b"k-cat"
_P_ADDR_REQ = b"a-req"
_P_ADDR_RESP = b"a-resp"
_P_ADDR_CAT = b"a-cat"
_P_KEY_OCC = b"k-occ"
_P_ADDR_OCC = b"a-occ"
_P_KEY_OCCD = b"k-occd"
_P_ADDR_OCCD = b"a-occd"


def _derive(secret: bytes, person: bytes) -> bytes:
    """32 bytes derivados do segredo do cliente, separados por ``person``."""
    if len(secret) != SECRET_LEN:
        raise ValueError(f"segredo do cliente deve ter {SECRET_LEN} bytes")
    return hashlib.blake2s(b"myass/edge/v1", key=secret, person=person,
                           digest_size=32).digest()


def request_key(secret: bytes) -> bytes:
    return _derive(secret, _P_KEY_REQ)


def response_key(secret: bytes) -> bytes:
    return _derive(secret, _P_KEY_RESP)


def request_address(secret: bytes) -> str:
    return _derive(secret, _P_ADDR_REQ).hex()


def response_address(secret: bytes) -> str:
    return _derive(secret, _P_ADDR_RESP).hex()


def catalog_key(secret: bytes) -> bytes:
    return _derive(secret, _P_KEY_CAT)


def catalog_address(secret: bytes) -> str:
    """Endereço onde o núcleo publica o catálogo de workflows do cliente, cifrado
    E2E — o servidor público (Locutus) fica cego até dos rótulos."""
    return _derive(secret, _P_ADDR_CAT).hex()


def seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """``nonce(12) || ciphertext+tag``. Nonce aleatório por mensagem."""
    nonce = os.urandom(NONCE_LEN)
    return nonce + ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)


def open_(key: bytes, blob: bytes, aad: bytes) -> bytes:
    """Inverso de :func:`seal`. Levanta ``InvalidTag`` se adulterado/chave errada."""
    if len(blob) < NONCE_LEN + 16:
        raise ValueError("blob curto demais")
    nonce, ct = blob[:NONCE_LEN], blob[NONCE_LEN:]
    return ChaCha20Poly1305(key).decrypt(nonce, ct, aad)


# Conveniências de alto nível (servem tanto ao cliente quanto ao núcleo): selam
# um pedido para depositar em request_address, e abrem a resposta de
# response_address. O AAD de direção garante que um blob de resposta nunca abre
# como pedido e vice-versa.

def seal_request(req_key: bytes, plaintext: bytes) -> bytes:
    return seal(req_key, plaintext, _AAD_REQ)


def open_request(req_key: bytes, blob: bytes) -> bytes:
    return open_(req_key, blob, _AAD_REQ)


def seal_response(resp_key: bytes, plaintext: bytes) -> bytes:
    return seal(resp_key, plaintext, _AAD_RESP)


def open_response(resp_key: bytes, blob: bytes) -> bytes:
    return open_(resp_key, blob, _AAD_RESP)


def seal_catalog(cat_key: bytes, plaintext: bytes) -> bytes:
    return seal(cat_key, plaintext, _AAD_CAT)


def open_catalog(cat_key: bytes, blob: bytes) -> bytes:
    return open_(cat_key, blob, _AAD_CAT)


# --- ocorrências (índice por cliente + detalhe por ocorrência) -----------
# O núcleo (SET) publica esses blobs selados no Locutus; a web lê e decifra. O
# detalhe tem um endereço por ``occ_id`` (não cabe no 'person' de 8 bytes), então
# usa BLAKE2s **chaveado** por um segredo derivado, com o ``occ_id`` como dado.

def occ_index_key(secret: bytes) -> bytes:
    return _derive(secret, _P_KEY_OCC)


def occ_index_address(secret: bytes) -> str:
    return _derive(secret, _P_ADDR_OCC).hex()


def occ_detail_key(secret: bytes) -> bytes:
    return _derive(secret, _P_KEY_OCCD)


def occ_detail_address(secret: bytes, occ_id: str) -> str:
    base = _derive(secret, _P_ADDR_OCCD)
    return hashlib.blake2s(occ_id.encode("utf-8"), key=base, digest_size=32).hexdigest()


def seal_occ_index(key: bytes, plaintext: bytes) -> bytes:
    return seal(key, plaintext, _AAD_OCC)


def open_occ_index(key: bytes, blob: bytes) -> bytes:
    return open_(key, blob, _AAD_OCC)


def seal_occ_detail(key: bytes, plaintext: bytes) -> bytes:
    return seal(key, plaintext, _AAD_OCCD)


def open_occ_detail(key: bytes, blob: bytes) -> bytes:
    return open_(key, blob, _AAD_OCCD)


def new_secret() -> bytes:
    """Cunha um segredo de cliente (uso da parteira; provisionado out-of-band)."""
    return os.urandom(SECRET_LEN)
