"""Shared opaque identifiers for the GPT liveness read-only routes."""
from __future__ import annotations

import re
import secrets


OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{8,72}\Z")
"""Compatibility-preserving syntax for GPT-liveness session/turn IDs."""



def new_chat_id() -> str:
    """Return a 128-bit cryptographic random routing ID, not an auth token."""
    return "chat_" + secrets.token_hex(16)


def new_session_id() -> str:
    """Return an opaque bounded enrollment ID."""
    return "session_" + secrets.token_hex(16)


def new_turn_id() -> str:
    """Return an opaque collision-resistant ID for one active turn."""
    return "turn_" + secrets.token_hex(16)

