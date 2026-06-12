"""X3DH (Extended Triple Diffie-Hellman) — acordo de chaves Rainha↔Rainha.

O handshake assíncrono do Signal, adaptado ao subspace relay (ver *Comunicação
inter-quadrante* em CLAUDE.md): compra autenticação mútua **e** forward secrecy
mesmo contra o comprometimento da chave de longo prazo do destinatário (que
pré-contribui aleatoriedade de uso único — a OPK — e depois a destrói).

Primitivos não-NIST, todos auditados (lib `cryptography`): **DH X25519**, **HKDF
-BLAKE2s**, **AEAD ChaCha20-Poly1305**. Divergência registrada da spec: ela pede
**XEd25519** (a mesma IK assina); como a lib não o expõe e escrevê-lo à mão
vazaria canais laterais, a identidade carrega um par **Ed25519 dedicado** (`IK_sig`)
para assinar o bundle, além do par **X25519** (`IK_dh`) para DH.

``SK = HKDF-BLAKE2s(salt = PSK do par, ikm = DH1‖DH2‖DH3‖[DH4], info=…)``::

    DH1 = DH(IK_dh_A, SPK_B)   DH2 = DH(EK_A, IK_dh_B)
    DH3 = DH(EK_A, SPK_B)      DH4 = DH(EK_A, OPK_B)   (omitido no fallback)
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)
from cryptography.exceptions import InvalidSignature

_INFO = "myass/subspace-relay/x3dh/v1"


# ---- helpers de primitivo ---------------------------------------------
def _x_pub(priv: X25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _x_priv_bytes(priv: X25519PrivateKey) -> bytes:
    return priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def _dh(priv: X25519PrivateKey, pub: bytes) -> bytes:
    return priv.exchange(X25519PublicKey.from_public_bytes(pub))


def _hkdf_blake2s(salt: bytes, ikm: bytes, info: bytes, length: int = 32) -> bytes:
    if not salt:
        salt = b"\x00" * 32
    prk = _hmac.new(salt, ikm, hashlib.blake2s).digest()
    okm, t, i = b"", b"", 1
    while len(okm) < length:
        t = _hmac.new(prk, t + info + bytes([i]), hashlib.blake2s).digest()
        okm += t
        i += 1
    return okm[:length]


def _msg_key(sk: bytes, label: bytes) -> bytes:
    person = (label + b"\x00" * 8)[:8]
    return hashlib.blake2s(b"myass/relay/msgkey", key=sk, person=person,
                           digest_size=32).digest()


def seal(sk: bytes, label: bytes, counter: int, plaintext: bytes, ad: bytes) -> bytes:
    nonce = counter.to_bytes(12, "big")
    return ChaCha20Poly1305(_msg_key(sk, label)).encrypt(nonce, plaintext, ad)


def open_(sk: bytes, label: bytes, counter: int, ciphertext: bytes, ad: bytes) -> bytes:
    nonce = counter.to_bytes(12, "big")
    return ChaCha20Poly1305(_msg_key(sk, label)).decrypt(nonce, ciphertext, ad)


# ---- identidade da Rainha ---------------------------------------------
@dataclass
class Identity:
    ik_dh: X25519PrivateKey
    ik_sig: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> "Identity":
        return cls(X25519PrivateKey.generate(), Ed25519PrivateKey.generate())

    @property
    def ik_dh_pub(self) -> bytes:
        return _x_pub(self.ik_dh)

    @property
    def ik_sig_pub(self) -> bytes:
        return self.ik_sig.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    @property
    def quadrante_id(self) -> str:
        return "qd:" + hashlib.blake2s(self.ik_dh_pub).hexdigest()[:24]


# ---- prekeys (lado do destinatário) -----------------------------------
class PrekeyVault:
    """Guarda a SPK e o lote de OPK do destinatário e produz o bundle assinado."""

    def __init__(self, identity: Identity, n_opks: int = 16):
        self.identity = identity
        self.spk = X25519PrivateKey.generate()
        self.spk_sig = identity.ik_sig.sign(_x_pub(self.spk))
        self.opks: dict[str, X25519PrivateKey] = {}
        self.refill(n_opks)

    def refill(self, n: int) -> None:
        for _ in range(n):
            self.opks["opk:" + os.urandom(6).hex()] = X25519PrivateKey.generate()

    def bundle(self) -> dict:
        body = {
            "quadrante_id": self.identity.quadrante_id,
            "ik_dh_pub": self.identity.ik_dh_pub.hex(),
            "ik_sig_pub": self.identity.ik_sig_pub.hex(),
            "spk_pub": _x_pub(self.spk).hex(),
            "spk_sig": self.spk_sig.hex(),
            "opks": [{"id": oid, "pub": _x_pub(p).hex()}
                     for oid, p in self.opks.items()],
        }
        body["bundle_sig"] = self.identity.ik_sig.sign(_canon(body)).hex()
        return body

    def take_opk(self, opk_id: str | None) -> X25519PrivateKey | None:
        """Consome (apaga) a OPK — uso único: re-enviar um opk_id já gasto torna
        a SK irrecuperável (forte proteção anti-replay do REQUEST)."""
        if opk_id is None:
            return None
        return self.opks.pop(opk_id, None)


def _canon(bundle_without_sig: dict) -> bytes:
    b = {k: v for k, v in bundle_without_sig.items() if k != "bundle_sig"}
    return json.dumps(b, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_bundle(bundle: dict, expected_ik_sig_pub: bytes) -> None:
    """Verifica o bundle contra a IK de assinatura conhecida (pré-trocada
    out-of-band). Levanta ``InvalidSignature`` se algo não bate."""
    if bytes.fromhex(bundle["ik_sig_pub"]) != expected_ik_sig_pub:
        raise InvalidSignature("ik_sig_pub não é a esperada")
    sig_pub = Ed25519PublicKey.from_public_bytes(expected_ik_sig_pub)
    sig_pub.verify(bytes.fromhex(bundle["bundle_sig"]), _canon(bundle))
    sig_pub.verify(bytes.fromhex(bundle["spk_sig"]), bytes.fromhex(bundle["spk_pub"]))


# ---- acordo X3DH ------------------------------------------------------
def agree_sender(me: Identity, their_bundle: dict, psk: bytes) -> tuple[bytes, dict]:
    """Lado A (deposita o REQUEST). Retorna ``(SK, header)``; ``header`` viaja
    no payload para B recomputar a SK."""
    ik_b = bytes.fromhex(their_bundle["ik_dh_pub"])
    spk_b = bytes.fromhex(their_bundle["spk_pub"])
    ek = X25519PrivateKey.generate()

    ikm = _dh(me.ik_dh, spk_b) + _dh(ek, ik_b) + _dh(ek, spk_b)
    opk_id = None
    if their_bundle.get("opks"):
        opk = their_bundle["opks"][0]
        opk_id = opk["id"]
        ikm += _dh(ek, bytes.fromhex(opk["pub"]))

    info = f"{_INFO}|{me.quadrante_id}|{their_bundle['quadrante_id']}".encode()
    sk = _hkdf_blake2s(psk, ikm, info)
    header = {"ik_dh_pub": me.ik_dh_pub.hex(), "ek_pub": _x_pub(ek).hex(),
              "opk_id": opk_id, "from": me.quadrante_id}
    return sk, header


def agree_receiver(me: Identity, vault: PrekeyVault, header: dict, psk: bytes) -> bytes:
    """Lado B (puxa o REQUEST). Recomputa a SK e **apaga a OPK** (uso único)."""
    ik_a = bytes.fromhex(header["ik_dh_pub"])
    ek_a = bytes.fromhex(header["ek_pub"])

    ikm = _dh(vault.spk, ik_a) + _dh(me.ik_dh, ek_a) + _dh(vault.spk, ek_a)
    opk = vault.take_opk(header.get("opk_id"))
    if header.get("opk_id") is not None:
        if opk is None:
            raise InvalidSignature("opk_id desconhecida/já consumida")
        ikm += _dh(opk, ek_a)

    info = f"{_INFO}|{header['from']}|{me.quadrante_id}".encode()
    return _hkdf_blake2s(psk, ikm, info)
