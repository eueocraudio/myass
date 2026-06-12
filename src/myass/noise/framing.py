"""Enquadramento sobre TCP — dois níveis (ver *Enquadramento sobre TCP* em CLAUDE.md).

Um *record* = uma mensagem de aplicação.

- **Fio:** ``record_len (4B BE)`` + corpo. O corpo é uma sequência de blocos Noise,
  cada um ``blk_len (2B BE)`` + mensagem Noise (``ciphertext + tag 16B``).
- **Plaintext do record:** ``real_len (4B) || payload || zero-pad até múltiplo de
  256``. Fatiado em chunks de <= 65280 (255×256), cada um cifrado como mensagem de
  transporte Noise; o nonce contador por direção avança por bloco.

O padding (dentro do AEAD) esconde o tamanho exato: um observador vê só tamanhos
grosseiros, já em múltiplos de 256.
"""

from __future__ import annotations

from .symmetric import CipherState

PAD_TO = 256
MAX_CHUNK = 255 * PAD_TO  # 65280
TAGLEN = 16


def frame(cs: CipherState, payload: bytes) -> bytes:
    """Cifra um record e devolve o fio completo (``record_len`` + corpo)."""
    pt = len(payload).to_bytes(4, "big") + payload
    pad = (-len(pt)) % PAD_TO
    pt += b"\x00" * pad

    body = bytearray()
    for i in range(0, len(pt), MAX_CHUNK):
        ct = cs.encrypt_with_ad(b"", pt[i:i + MAX_CHUNK])
        body += len(ct).to_bytes(2, "big") + ct
    return len(body).to_bytes(4, "big") + bytes(body)


def unframe(cs: CipherState, body: bytes) -> bytes:
    """Decifra o corpo de um record (sem o ``record_len``) e devolve o payload."""
    pt = bytearray()
    off = 0
    while off < len(body):
        blk_len = int.from_bytes(body[off:off + 2], "big")
        off += 2
        ct = body[off:off + blk_len]
        off += blk_len
        pt += cs.decrypt_with_ad(b"", ct)
    real_len = int.from_bytes(pt[:4], "big")
    return bytes(pt[4:4 + real_len])
