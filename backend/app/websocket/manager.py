"""WebSocket connection manager for real-time streaming.

Design (Phase 14 — G19, G7):
- store_event: save every emitted event to Redis LIST ws_events:{exam_id} (TTL 3600s)
- replay_events: on connect(), replay missed events from Redis LIST so reconnecting
  clients see full history from the beginning of the generation session
- listen_redis: subscribe to Redis pub/sub channel exam:{exam_id} and forward
  all incoming messages to connected WebSocket clients
- emit() is async and does:
    1. store_event() — always save first so event survives client disconnect
    2. send_json() to every connected local WebSocket
    3. redis.publish() to exam:{exam_id} — other app instances pick it up via listen_redis
"""

import asyncio
import json
import logging
import redis.asyncio as async_redis
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.redis_client import RedisClient

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections per exam_id and bridges them with Redis pub/sub.

    G19 — event replay on reconnect:
        Every event is stored in Redis LIST ws_events:{exam_id} before being sent.
        When a new WebSocket connects, replay_events() replays all stored events
        so the client catches up to the current state instantly.

    G19 — Redis pub/sub fan-out:
        Events are also published to Redis channel exam:{exam_id}.
        listen_redis() subscribes to that channel and fans out received messages
        to all local WebSocket connections — enabling multi-instance deployments.
    """

    _EVENT_LIST_TTL = 3600  # 1 hour TTL for stored events

    def __init__(self, redis: Optional[RedisClient] = None):
        # Map: exam_id -> list of WebSocket connections
        self.active: dict[str, list[WebSocket]] = {}
        self._redis = redis

        # Per-exam listener tasks (so we can cancel on shutdown)
        self._listener_tasks: dict[str, asyncio.Task[None]] = {}

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, exam_id: str) -> None:
        """
        Accept a new WebSocket connection and register it.
        MUST be called before listen_redis() so replay happens first (G19).
        """
        await websocket.accept()
        self.active.setdefault(exam_id, []).append(websocket)

        # G19: Replay all stored events so the client catches up immediately
        await self.replay_events(exam_id, websocket)

    async def disconnect(self, websocket: WebSocket, exam_id: str) -> None:
        """Remove a WebSocket connection."""
        connections = self.active.get(exam_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            del self.active[exam_id]
            # Cancel the Redis listener for this exam if no connections remain
            task = self._listener_tasks.pop(exam_id, None)
            if task and not task.done():
                task.cancel()

    # ── Core emit pipeline ────────────────────────────────────────────────────

    async def emit(self, exam_id: str, event: dict) -> None:
        """
        Primary emit method — called by exam_task.py.

        G19 guarantees:
            1. store_event FIRST — event is persisted before any send
            2. send_json to local WebSocket clients
            3. redis.publish to exam:{exam_id} for multi-instance fan-out
        """
        # Step 1: ALWAYS store before sending (G19)
        await self.store_event(exam_id, event)

        # Step 2: Send to all connected local WebSocket clients
        if exam_id in self.active:
            stale: list[WebSocket] = []
            for ws in self.active[exam_id]:
                try:
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.send_json(event)
                    else:
                        stale.append(ws)
                except Exception:
                    stale.append(ws)

            for ws in stale:
                await self.disconnect(ws, exam_id)

        # Step 3: Publish to Redis for other app instances (multi-instance fan-out)
        if self._redis:
            channel = f"exam:{exam_id}"
            await self._redis.publish(channel, event)

    # ── G19: Event persistence for replay ────────────────────────────────────

    async def store_event(self, exam_id: str, event: dict) -> None:
        """
        G19: Save event to Redis LIST ws_events:{exam_id} with TTL 3600s.
        This list is the source of truth for replay on reconnect.
        """
        if self._redis is None:
            return

        key = f"ws_events:{exam_id}"
        try:
            # Use rpush to append to list, expire to auto-cleanup after 1 hour
            await self._redis.client.rpush(key, json.dumps(event, ensure_ascii=False))
            await self._redis.client.expire(key, self._EVENT_LIST_TTL)
        except Exception as e:
            logger.warning(f"Failed to store event in Redis: {e}")

    async def replay_events(
        self,
        exam_id: str,
        websocket: WebSocket,
        from_index: int = 0,
    ) -> None:
        """
        G19: Replay stored events to a single WebSocket on connect/reconnect.
        by default replays ALL events (from_index=0).

        Client can pass ?last_event_index=N to resume from a specific position.
        """
        if self._redis is None:
            return

        key = f"ws_events:{exam_id}"
        try:
            events_raw = await self._redis.client.lrange(key, from_index, -1)
            for raw in events_raw:
                try:
                    await websocket.send_text(raw)
                except Exception:
                    # If send fails (client disconnected during replay), abort
                    break
        except Exception as e:
            logger.warning(f"Failed to replay events from Redis: {e}")

    # ── G19: Redis pub/sub listener ───────────────────────────────────────────

    async def listen_redis(self, exam_id: str) -> None:
        """
        Subscribe to Redis channel exam:{exam_id} and forward every message
        to all connected WebSocket clients for this exam.

        This is the fan-out path for multi-instance deployments:
        exam_task.py publishes to exam:{exam_id} → all instances that have
        clients listening receive the message via this listener.
        """
        if self._redis is None:
            logger.warning("listen_redis called but Redis is not configured")
            return

        channel = f"exam:{exam_id}"

        try:
            # Redis pub/sub: get a new connection for subscribing (pub/sub uses
            # a separate connection from the regular Redis client)
            pubsub = self._redis.client.pubsub()
            await pubsub.subscribe(channel)
            logger.info(f"Subscribed to Redis channel: {channel}")

            try:
                async for raw_message in pubsub.listen():
                    # Skip internal subscribe/unsubscribe confirmation messages
                    if raw_message.get("type") != "message":
                        continue

                    payload = raw_message.get("data", "")
                    if not payload:
                        continue

                    event = json.loads(payload)
                    # Forward to local WebSocket clients (do NOT re-store/re-publish)
                    await self._forward_to_websockets(exam_id, event)
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
        except asyncio.CancelledError:
            logger.debug(f"Redis listener cancelled for exam: {exam_id}")
            raise
        except Exception as e:
            logger.error(f"Redis listener error for exam {exam_id}: {e}")

    async def _forward_to_websockets(self, exam_id: str, event: dict) -> None:
        """Forward a Redis message to all local WebSocket clients (no re-publish)."""
        if exam_id not in self.active:
            return

        stale: list[WebSocket] = []
        for ws in self.active[exam_id]:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(event)
                else:
                    stale.append(ws)
            except Exception:
                stale.append(ws)

        for ws in stale:
            await self.disconnect(ws, exam_id)

    # ── Aliases ───────────────────────────────────────────────────────────────

    async def broadcast(self, exam_id: str, event: dict) -> None:
        """Alias for emit() — broadcast an event to all clients."""
        await self.emit(exam_id, event)

    async def start_listener(self, exam_id: str) -> None:
        """
        Start the Redis listener for an exam as a background task.
        Safe to call multiple times — only one listener per exam_id runs at a time.
        """
        if exam_id in self._listener_tasks and not self._listener_tasks[exam_id].done():
            return  # Already listening

        task = asyncio.create_task(self.listen_redis(exam_id))
        self._listener_tasks[exam_id] = task

    async def stop_listener(self, exam_id: str) -> None:
        """Stop the Redis listener for an exam."""
        task = self._listener_tasks.pop(exam_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Cancel all running Redis listeners on app shutdown."""
        for exam_id in list(self._listener_tasks.keys()):
            await self.stop_listener(exam_id)


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get the singleton ConnectionManager with async Redis initialized."""
    global _manager
    if _manager is None:
        from app.core.config import get_settings
        from app.core.redis_client import RedisClient
        settings = get_settings()
        _manager = ConnectionManager(redis=RedisClient(async_redis.from_url(settings.REDIS_URL)))
    return _manager


# ── SSEvent factory ────────────────────────────────────────────────────────────

class SSEvent:
    """
    Streaming event factory for all WebSocket event types.

    Event types matching Phase 14 spec + G7 HitlEvent payload requirements:
      - plan_step          → pipeline progress
      - question_generated → per-question streaming
      - validation_result  → validation completion
      - hitl_checkpoint    → HITL pauses (checkpoint 0/1/2/3)
      - completed          → final success
      - error              → any error
    """

    @staticmethod
    def plan_step(message: str, step: int, total_steps: int) -> dict:
        return {
            "type": "plan_step",
            "message": message,
            "step": step,
            "total_steps": total_steps,
        }

    @staticmethod
    def question_generated(question_id: str, question: dict) -> dict:
        return {
            "type": "question_generated",
            "question_id": question_id,
            "question": question,
        }

    @staticmethod
    def validation_result(
        passed: bool,
        issues_count: int,
        issues: Optional[list[dict]] = None,
    ) -> dict:
        return {
            "type": "validation_result",
            "passed": passed,
            "issues_count": issues_count,
            "issues": issues or [],
        }

    @staticmethod
    def completed(exam_id: str, total_cost_usd: Optional[float] = None) -> dict:
        """
        Emitted when exam generation completes successfully.
        G7: must include total_cost_usd in payload.
        """
        payload: dict[str, Any] = {
            "type": "completed",
            "exam_id": exam_id,
        }
        if total_cost_usd is not None:
            payload["total_cost_usd"] = round(total_cost_usd, 6)
        return payload

    @staticmethod
    def error(message: str, agent: Optional[str] = None) -> dict:
        return {
            "type": "error",
            "message": message,
            "agent": agent,
        }

    @staticmethod
    def hitl_checkpoint(checkpoint_id: int, data: dict) -> dict:
        """
        HITL checkpoint event.

        G7 spec payload requirements:
        - checkpoint_id 1: data MUST contain blueprint + distribution_summary
        - checkpoint_id 2: data MUST contain exam_id
        - checkpoint_id 3: data contains exam_id + questions + cost_report
        """
        return {
            "type": "hitl_checkpoint",
            "checkpoint_id": checkpoint_id,
            "data": data,
        }

    @staticmethod
    def blueprint_ready(blueprint: list[dict], distribution_summary: dict) -> dict:
        """
        Convenience alias for HITL checkpoint 1 data.
        G7: blueprint must be a list of BlueprintSlot dicts.
        """
        return {
            "type": "blueprint_ready",
            "blueprint": blueprint,
            "distribution_summary": distribution_summary,
        }

    @staticmethod
    def progress(progress_percent: int, message: str) -> dict:
        return {
            "type": "progress",
            "progress_percent": progress_percent,
            "message": message,
        }
