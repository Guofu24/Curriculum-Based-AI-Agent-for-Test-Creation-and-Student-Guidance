"""WebSocket connection manager for real-time streaming."""

import json
from typing import Any
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.redis_client import RedisClient


class ConnectionManager:
    """
    Manages WebSocket connections and pub/sub for streaming events.
    """

    def __init__(self, redis: RedisClient | None = None):
        # Map: exam_id -> list of WebSocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.redis = redis

    async def connect(self, websocket: WebSocket, exam_id: str) -> None:
        """Accept and register a WebSocket connection for an exam."""
        await websocket.accept()
        if exam_id not in self.active_connections:
            self.active_connections[exam_id] = []
        self.active_connections[exam_id].append(websocket)

    async def disconnect(self, websocket: WebSocket, exam_id: str) -> None:
        """Remove a WebSocket connection."""
        if exam_id in self.active_connections:
            if websocket in self.active_connections[exam_id]:
                self.active_connections[exam_id].remove(websocket)
            if not self.active_connections[exam_id]:
                del self.active_connections[exam_id]

    async def emit(self, exam_id: str, event: dict) -> None:
        """
        Send an event to all connections for an exam.
        Also publishes to Redis pub/sub for multi-instance support.
        """
        # Send to local connections
        if exam_id in self.active_connections:
            disconnected = []
            for websocket in self.active_connections[exam_id]:
                try:
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_json(event)
                    else:
                        disconnected.append(websocket)
                except Exception:
                    disconnected.append(websocket)

            # Clean up disconnected
            for ws in disconnected:
                await self.disconnect(ws, exam_id)

        # Publish to Redis for multi-instance
        if self.redis:
            channel = f"exam:{exam_id}"
            await self.redis.publish(channel, event)

    async def broadcast(self, exam_id: str, event: dict) -> None:
        """Broadcast (alias for emit)."""
        await self.emit(exam_id, event)


# Singleton
_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    """Get the singleton ConnectionManager."""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


# ── Event Types ────────────────────────────────────────────────────────────────

class SSEvent:
    """Streaming event factory."""

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
    def validation_result(passed: bool, issues_count: int, issues: list[dict] | None = None) -> dict:
        return {
            "type": "validation_result",
            "passed": passed,
            "issues_count": issues_count,
            "issues": issues or [],
        }

    @staticmethod
    def completed(exam_id: str) -> dict:
        return {
            "type": "completed",
            "exam_id": exam_id,
        }

    @staticmethod
    def error(message: str, agent: str | None = None) -> dict:
        return {
            "type": "error",
            "message": message,
            "agent": agent,
        }

    @staticmethod
    def hitl_checkpoint(checkpoint_id: int, data: dict) -> dict:
        return {
            "type": "hitl_checkpoint",
            "checkpoint_id": checkpoint_id,
            "data": data,
        }

    @staticmethod
    def progress(progress_percent: int, message: str) -> dict:
        return {
            "type": "progress",
            "progress_percent": progress_percent,
            "message": message,
        }

    @staticmethod
    def blueprint_ready(blueprint: list[dict], distribution_summary: dict) -> dict:
        return {
            "type": "blueprint_ready",
            "blueprint": blueprint,
            "distribution_summary": distribution_summary,
        }
