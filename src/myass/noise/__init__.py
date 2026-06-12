"""Canal sub-espacial — protocolo Noise próprio sobre TCP (sem TLS, sem HTTP).

Implementa a suíte ``Noise_KKpsk0_25519_ChaChaPoly_BLAKE2s`` (framework e
enquadramento à mão; primitivos da lib auditada ``cryptography``) e o transporte
plugável direto/LAN × Tor para o link Executor↔Scheduler. Ver *Canais seguros*
em CLAUDE.md.
"""

from .channel import (
    AuthError, NoiseChannel, connect, connect_direct, connect_tor, initiate,
    listen, respond, respond_trial,
)
from .handshake import PROTOCOL_NAME, HandshakeState
from .tor import OnionService, client_auth_line, gen_client_auth

__all__ = [
    "HandshakeState", "PROTOCOL_NAME", "NoiseChannel", "AuthError",
    "initiate", "respond", "respond_trial",
    "connect", "connect_direct", "connect_tor", "listen",
    "OnionService", "gen_client_auth", "client_auth_line",
]
