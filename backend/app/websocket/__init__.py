"""WebSocket package — real-time streaming via WebSocket + Redis pub/sub."""

from app.websocket.manager import (
    ConnectionManager,
    SSEvent,
    get_connection_manager,
)

__all__ = [
    "ConnectionManager",
    "SSEvent",
    "get_connection_manager",
]
