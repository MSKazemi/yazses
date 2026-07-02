"""Glasses↔Desktop Bridge — pairing + session state machine (pure) — ADR-v2-013.

Models the companion↔desktop lifecycle: begin pairing → accept a token → activate
streaming → close. Token comparison is constant-time. Pure; the socket transport
(reusing ``remote/``) drives this state machine but lives elsewhere.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import Enum


class BridgeState(str, Enum):
    IDLE = "idle"
    PENDING = "pending"       # awaiting a companion to present the pairing token
    PAIRED = "paired"         # token accepted; not yet streaming
    ACTIVE = "active"         # companion is streaming audio
    CLOSED = "closed"


def _tokens_equal(a: str, b: str) -> bool:
    """Constant-time token comparison (avoids trivial timing leaks)."""
    return hmac.compare_digest(str(a), str(b))


@dataclass
class BridgeSession:
    token: str
    device_name: str = ""
    state: BridgeState = BridgeState.IDLE

    def begin_pairing(self) -> None:
        """Open the pairing window (IDLE/CLOSED → PENDING)."""
        self.state = BridgeState.PENDING

    def try_pair(self, presented_token: str, device_name: str = "") -> bool:
        """Accept a companion iff its token matches while pairing is open.

        Only valid from PENDING; an empty configured token never matches (pairing
        stays closed). Returns True and moves to PAIRED on success.
        """
        if self.state != BridgeState.PENDING:
            return False
        if not self.token or not _tokens_equal(presented_token, self.token):
            return False
        self.device_name = device_name
        self.state = BridgeState.PAIRED
        return True

    def activate(self) -> bool:
        """Begin streaming (PAIRED → ACTIVE). No-op/False from any other state."""
        if self.state != BridgeState.PAIRED:
            return False
        self.state = BridgeState.ACTIVE
        return True

    def close(self) -> None:
        self.state = BridgeState.CLOSED

    @property
    def can_stream(self) -> bool:
        return self.state == BridgeState.ACTIVE
