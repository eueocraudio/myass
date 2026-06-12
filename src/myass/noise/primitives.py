"""Primitivos do Noise — todos da lib auditada ``cryptography`` (nunca à mão).

Suíte do myass: **X25519 / ChaCha20-Poly1305 / BLAKE2s** (não-NIST, djb/pares).
Só os *primitivos* vêm da lib; o *framework* Noise e o *enquadramento* são nossos
(decisão da spec: escrever o protocolo à mão é proposital; os primitivos, não).
"""

from __future__ import annotations

import hashlib
import hmac as _hmac

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

DHLEN = 32
HASHLEN = 32
TAGLEN = 16


# ---- DH (X25519) -------------------------------------------------------
def generate_keypair():
    priv = X25519PrivateKey.generate()
    return priv, public_bytes(priv)


def public_bytes(priv: X25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def private_bytes(priv: X25519PrivateKey) -> bytes:
    return priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def load_private(raw: bytes) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(raw)


def dh(priv: X25519PrivateKey, pub: bytes) -> bytes:
    return priv.exchange(X25519PublicKey.from_public_bytes(pub))


# ---- HASH / HKDF (BLAKE2s) --------------------------------------------
def hash_(data: bytes) -> bytes:
    return hashlib.blake2s(data).digest()


def hmac_hash(key: bytes, data: bytes) -> bytes:
    return _hmac.new(key, data, hashlib.blake2s).digest()


def hkdf(chaining_key: bytes, ikm: bytes, num_outputs: int):
    """HKDF do Noise (HMAC-BLAKE2s). Retorna ``num_outputs`` (2 ou 3) saídas."""
    temp_key = hmac_hash(chaining_key, ikm)
    o1 = hmac_hash(temp_key, b"\x01")
    o2 = hmac_hash(temp_key, o1 + b"\x02")
    if num_outputs == 2:
        return o1, o2
    o3 = hmac_hash(temp_key, o2 + b"\x03")
    return o1, o2, o3


# ---- AEAD (ChaCha20-Poly1305) -----------------------------------------
def _nonce(n: int) -> bytes:
    # 96 bits = 32 bits de zeros || n em little-endian de 64 bits (spec Noise).
    return b"\x00\x00\x00\x00" + n.to_bytes(8, "little")


def aead_encrypt(key: bytes, n: int, ad: bytes, plaintext: bytes) -> bytes:
    return ChaCha20Poly1305(key).encrypt(_nonce(n), plaintext, ad)


def aead_decrypt(key: bytes, n: int, ad: bytes, ciphertext: bytes) -> bytes:
    return ChaCha20Poly1305(key).decrypt(_nonce(n), ciphertext, ad)
