"""Subspace relay — comunicação inter-quadrante (Rainha↔Rainha) sobre dead drop.

E2E via X3DH (``x3dh``); transporte cego via ``RelayTransport`` (memória/`bdd`).
"""

from .relay import (
    MemoryRelayTransport, RelayTransport, SubspaceRelay, channel, prekey_channel,
)
from .x3dh import Identity, PrekeyVault, verify_bundle

__all__ = [
    "SubspaceRelay", "RelayTransport", "MemoryRelayTransport",
    "channel", "prekey_channel", "Identity", "PrekeyVault", "verify_bundle",
]
