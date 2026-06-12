"""CipherState e SymmetricState do Noise Protocol Framework.

Implementação fiel do framework (noiseprotocol.org, rev 34) sobre os nossos
primitivos. CipherState = chave + nonce contador; SymmetricState = chaining key
+ hash do handshake + um CipherState.
"""

from __future__ import annotations

from . import primitives as P

_EMPTY = b""


class CipherState:
    def __init__(self):
        self.k: bytes | None = None
        self.n = 0

    def initialize_key(self, key: bytes | None) -> None:
        self.k = key
        self.n = 0

    def has_key(self) -> bool:
        return self.k is not None

    def set_nonce(self, n: int) -> None:
        self.n = n

    def encrypt_with_ad(self, ad: bytes, plaintext: bytes) -> bytes:
        if self.k is None:
            return plaintext
        ct = P.aead_encrypt(self.k, self.n, ad, plaintext)
        self.n += 1
        return ct

    def decrypt_with_ad(self, ad: bytes, ciphertext: bytes) -> bytes:
        if self.k is None:
            return ciphertext
        pt = P.aead_decrypt(self.k, self.n, ad, ciphertext)
        self.n += 1
        return pt


class SymmetricState:
    def __init__(self, protocol_name: bytes):
        if len(protocol_name) <= P.HASHLEN:
            self.h = protocol_name + b"\x00" * (P.HASHLEN - len(protocol_name))
        else:
            self.h = P.hash_(protocol_name)
        self.ck = self.h
        self.cs = CipherState()

    def mix_key(self, ikm: bytes) -> None:
        self.ck, temp_k = P.hkdf(self.ck, ikm, 2)
        self.cs.initialize_key(temp_k)

    def mix_hash(self, data: bytes) -> None:
        self.h = P.hash_(self.h + data)

    def mix_key_and_hash(self, ikm: bytes) -> None:
        self.ck, temp_h, temp_k = P.hkdf(self.ck, ikm, 3)
        self.mix_hash(temp_h)
        self.cs.initialize_key(temp_k)

    def encrypt_and_hash(self, plaintext: bytes) -> bytes:
        ct = self.cs.encrypt_with_ad(self.h, plaintext)
        self.mix_hash(ct)
        return ct

    def decrypt_and_hash(self, ciphertext: bytes) -> bytes:
        pt = self.cs.decrypt_with_ad(self.h, ciphertext)
        self.mix_hash(ciphertext)
        return pt

    def split(self) -> tuple[CipherState, CipherState]:
        temp_k1, temp_k2 = P.hkdf(self.ck, _EMPTY, 2)
        c1, c2 = CipherState(), CipherState()
        c1.initialize_key(temp_k1)
        c2.initialize_key(temp_k2)
        return c1, c2
