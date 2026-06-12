"""Handshake Noise ``KKpsk0`` — o canal sub-espacial Executor↔Scheduler.

Suíte: ``Noise_KKpsk0_25519_ChaChaPoly_BLAKE2s``.

- **KK**: as estáticas das duas partes são conhecidas de antemão (pré-trocadas
  out-of-band no provisionamento) — não viajam no fio, removendo a superfície de
  MITM. Iniciador = Executor; Respondedor = Scheduler.
- **psk0**: a PSK por par é misturada no início (token ``psk`` no começo da 1ª
  mensagem). Em modo PSK, o token ``e`` também faz ``MixKey`` (além de ``MixHash``).

Padrão::

    -> s            (pré-mensagem: estática do iniciador, conhecida do respondedor)
    <- s            (pré-mensagem: estática do respondedor, conhecida do iniciador)
    ...
    -> psk, e, es, ss
    <- e, ee, se
"""

from __future__ import annotations

from . import primitives as P
from .symmetric import SymmetricState

PROTOCOL_NAME = b"Noise_KKpsk0_25519_ChaChaPoly_BLAKE2s"

_MESSAGES = (("psk", "e", "es", "ss"), ("e", "ee", "se"))


class HandshakeState:
    def __init__(self, initiator: bool, prologue: bytes, s_priv, s_pub: bytes,
                 rs_pub: bytes, psk: bytes):
        self.ss = SymmetricState(PROTOCOL_NAME)
        self.initiator = initiator
        self.psk = psk
        self.s_priv, self.s_pub = s_priv, s_pub  # estática local
        self.rs = rs_pub                          # estática remota (conhecida, KK)
        self.e_priv = self.e_pub = None           # efêmera local
        self.re: bytes | None = None              # efêmera remota
        self._index = 0

        self.ss.mix_hash(prologue)
        # Pré-mensagens KK, na ordem (-> s, depois <- s):
        if initiator:
            self.ss.mix_hash(self.s_pub)  # -> s (própria)
            self.ss.mix_hash(self.rs)     # <- s (respondedor)
        else:
            self.ss.mix_hash(self.rs)     # -> s (iniciador, remoto p/ respondedor)
            self.ss.mix_hash(self.s_pub)  # <- s (própria)

    def _dh(self, token: str) -> bytes:
        if token == "ee":
            return P.dh(self.e_priv, self.re)
        if token == "ss":
            return P.dh(self.s_priv, self.rs)
        if token == "es":
            return P.dh(self.e_priv, self.rs) if self.initiator else P.dh(self.s_priv, self.re)
        if token == "se":
            return P.dh(self.s_priv, self.re) if self.initiator else P.dh(self.e_priv, self.rs)
        raise ValueError(f"token DH desconhecido: {token}")

    def write_message(self, payload: bytes = b""):
        buf = bytearray()
        for token in _MESSAGES[self._index]:
            if token == "psk":
                self.ss.mix_key_and_hash(self.psk)
            elif token == "e":
                self.e_priv, self.e_pub = P.generate_keypair()
                buf += self.e_pub
                self.ss.mix_hash(self.e_pub)
                self.ss.mix_key(self.e_pub)  # modo PSK: 'e' também faz MixKey
            else:
                self.ss.mix_key(self._dh(token))
        buf += self.ss.encrypt_and_hash(payload)
        return bytes(buf), self._advance()

    def read_message(self, message: bytes):
        mv = memoryview(message)
        off = 0
        for token in _MESSAGES[self._index]:
            if token == "psk":
                self.ss.mix_key_and_hash(self.psk)
            elif token == "e":
                self.re = bytes(mv[off:off + P.DHLEN])
                off += P.DHLEN
                self.ss.mix_hash(self.re)
                self.ss.mix_key(self.re)
            else:
                self.ss.mix_key(self._dh(token))
        payload = self.ss.decrypt_and_hash(bytes(mv[off:]))
        return payload, self._advance()

    def _advance(self):
        self._index += 1
        return self.ss.split() if self._index == len(_MESSAGES) else None

    def handshake_hash(self) -> bytes:
        return self.ss.h
