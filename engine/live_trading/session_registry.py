"""
Global registry of active live trading sessions.

Holds references to LiveSession instances so that API endpoints can query
in-memory state (open trades, equity, balance) from the running engines
without relying solely on stale database records.
"""
from __future__ import annotations

from typing import Dict, Optional, Any


# Map session_id -> LiveSession instance (or any object with session_id attr)
_sessions: Dict[int, Any] = {}


def register(session: Any) -> None:
    """Register a running session."""
    _sessions[session.session_id] = session


def unregister(session_id: int) -> None:
    """Remove a stopped session."""
    _sessions.pop(session_id, None)


def get(session_id: int) -> Optional[Any]:
    """Get a running session by ID."""
    return _sessions.get(session_id)


def list_all() -> list:
    """List all registered sessions."""
    return list(_sessions.values())
