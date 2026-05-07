"""
Agent-to-agent message bus using Redis Streams.

Agents publish typed messages directly to each other (not via shared LangGraph state).
This enables true peer-to-peer communication independent of the state machine.

Usage:
    bus = AgentMessageBus(redis_client)
    await bus.publish(exam_id, sender="retrieval", recipient="outline",
                      message_type="coverage_report", payload={...})
    messages = await bus.consume(exam_id, recipient="outline")
"""

import json
import time
import logging
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("app.agents.messaging")

# Redis stream key pattern per exam + recipient
_STREAM_KEY = "agent_msg:{exam_id}:{recipient}"
# Auto-expire streams after 2 hours (same as session TTL)
_STREAM_TTL_SECONDS = 7200
# Max messages per stream (trim to prevent unbounded growth)
_MAX_LEN = 100


@dataclass
class AgentMessage:
    sender: str
    recipient: str
    exam_id: str
    message_type: str
    payload: dict
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_redis_entry(cls, entry: dict) -> "AgentMessage":
        return cls(
            sender=entry.get("sender", ""),
            recipient=entry.get("recipient", ""),
            exam_id=entry.get("exam_id", ""),
            message_type=entry.get("message_type", ""),
            payload=json.loads(entry.get("payload", "{}")),
            timestamp=float(entry.get("timestamp", 0)),
        )


class AgentMessageBus:
    """
    Redis Streams-backed message bus for peer-to-peer agent communication.

    Each exam has one stream per recipient agent. Publishers XADD to the
    recipient's stream; consumers XRANGE to read all pending messages.

    Accepts either a raw redis.asyncio.Redis or a RedisClient wrapper.
    Always accesses the raw .client for stream commands (xadd/xrange) since
    the RedisClient wrapper only exposes basic key-value helpers.
    """

    def __init__(self, redis_client):
        # Support both raw redis.asyncio.Redis and RedisClient wrapper
        if hasattr(redis_client, "client"):
            # RedisClient wrapper — use the underlying raw client
            self._raw = redis_client.client
        else:
            self._raw = redis_client

    def _stream_key(self, exam_id: str, recipient: str) -> str:
        return _STREAM_KEY.format(exam_id=exam_id, recipient=recipient)

    async def publish(
        self,
        exam_id: str,
        sender: str,
        recipient: str,
        message_type: str,
        payload: dict,
    ) -> bool:
        """Publish a message to a recipient agent's stream. Returns True on success."""
        if not self._raw:
            return False
        try:
            key = self._stream_key(exam_id, recipient)
            entry = {
                "sender": sender,
                "recipient": recipient,
                "exam_id": exam_id,
                "message_type": message_type,
                "payload": json.dumps(payload, ensure_ascii=False),
                "timestamp": str(time.time()),
            }
            await self._raw.xadd(key, entry, maxlen=_MAX_LEN)
            await self._raw.expire(key, _STREAM_TTL_SECONDS)
            logger.debug(
                "AgentMessageBus: %s → %s [%s] exam=%s",
                sender, recipient, message_type, exam_id,
            )
            return True
        except Exception as exc:
            logger.warning("AgentMessageBus.publish failed (non-critical): %s", exc)
            return False

    async def consume(
        self,
        exam_id: str,
        recipient: str,
        message_types: list[str] | None = None,
    ) -> list[AgentMessage]:
        """
        Read all messages for a recipient from the stream.

        Optionally filter by message_type. Does NOT delete entries — streams
        are auto-expired after TTL. Idempotent: safe to call multiple times.
        """
        if not self._raw:
            return []
        try:
            key = self._stream_key(exam_id, recipient)
            raw_entries = await self._raw.xrange(key, "-", "+")
            messages: list[AgentMessage] = []
            for _entry_id, entry_data in raw_entries:
                # Decode bytes keys/values if needed (pool may have decode_responses=False)
                decoded: dict = {}
                for k, v in entry_data.items():
                    dk = k.decode() if isinstance(k, bytes) else k
                    dv = v.decode() if isinstance(v, bytes) else v
                    decoded[dk] = dv
                msg = AgentMessage.from_redis_entry(decoded)
                if message_types is None or msg.message_type in message_types:
                    messages.append(msg)
            return messages
        except Exception as exc:
            logger.warning("AgentMessageBus.consume failed (non-critical): %s", exc)
            return []

    async def clear(self, exam_id: str, recipient: str) -> None:
        """Delete a recipient's stream for an exam (cleanup after pipeline ends)."""
        if not self._raw:
            return
        try:
            key = self._stream_key(exam_id, recipient)
            await self._raw.delete(key)
        except Exception as exc:
            logger.debug("AgentMessageBus.clear failed (non-critical): %s", exc)
