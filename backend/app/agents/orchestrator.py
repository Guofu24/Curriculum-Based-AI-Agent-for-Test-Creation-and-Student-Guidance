"""Orchestrator Agent - main entry point that coordinates all sub-agents."""

import asyncio
import logging
import time
import uuid
import json
from typing import Any, Callable, Awaitable
from uuid import UUID

logger = logging.getLogger("app.agents.orchestrator")

from app.agents.base import AgentBaseOutput, AgentStatus, TokenUsage
from app.agents.retrieval import RetrievalAgent
from app.agents.outline import OutlineAgent
from app.agents.builder import BuilderAgent
from app.agents.validator import ValidatorAgent
from app.agents.planner import PlannerAgent
from app.agents.memory import ShortTermMemory, LongTermMemory
from app.agents.skills.bloom_classifier import BloomClassifierSkill
from app.agents.skills.scope_checker import ScopeCheckerSkill
from app.observability.tracer import get_tracer
from app.core.redis_client import RedisClient
from app.core.config import get_settings

settings = get_settings()


# Callback type for streaming events
StreamingCallback = Callable[[dict], Awaitable[None]]


class OrchestratorAgent:
    """
    Agent 0: Orchestrator Agent

    Role: The ONLY agent that directly interacts with the user.
    All sub-agents are exposed as tools.

    Flow:
    1. Parse & Clarify: if requirements unclear → ask ≤3 questions
    2. Rewrite Requirements: structured format → confirm with teacher
    3. Load Long-term Memory: teacher preferences from PostgreSQL
    4. Dispatch: complex → Planner; simple → default plan
    5. Execute: retrieve → outline → HITL1 → build → validate → retry (max 3)
    6. Output: complete exam + plan reasoning stream

    Features:
    - Streaming: emit real-time plan steps via WebSocket
    - HITL Checkpoints: 3 checkpoints for human review
    """

    CLARIFY_SYSTEM_PROMPT = """Bạn là giảng viên đang giao nhiệm vụ tạo đề kiểm tra.

Nếu yêu cầu chưa rõ ràng, hãy đặt tối đa 3 câu hỏi làm rõ:
- Scope (phạm vi bài kiểm tra)
- Số lượng và loại câu hỏi
- Mức độ phân bổ Bloom
- Yêu cầu đặc biệt nào khác

Trả về JSON:
{
  "clarification_questions": [
    {"question_id": "q1", "question": "..."}
  ],
  "requirements_clear": true/false
}"""

    def __init__(self, redis: RedisClient, db_session=None):
        self.redis = redis
        self.db_session = db_session
        self.short_term = ShortTermMemory(redis)
        self.long_term = LongTermMemory(db_session) if db_session else None
        self.retrieval = RetrievalAgent(redis)
        self.outline = OutlineAgent()
        self.builder = BuilderAgent(redis)
        self.validator = ValidatorAgent(redis)
        self.planner = PlannerAgent()
        self.graph = None
        self._stream_callback: StreamingCallback | None = None
        self._pending_blueprint: list[dict] = []
        self._pending_distribution: dict = {}

    def set_stream_callback(self, callback: StreamingCallback) -> None:
        """Set callback for streaming events to WebSocket."""
        self._stream_callback = callback

    async def _emit(self, event: dict) -> None:
        """Emit a streaming event."""
        if self._stream_callback:
            await self._stream_callback(event)

    # ── G6: _is_complex_request ─────────────────────────────────────────────────

    def _is_complex_request(self, user_prompt: str, exam_config: dict) -> bool:
        """
        Determine if request is complex enough to need Planner Agent.
        G6: Returns True when sum(signals) >= 2.

        Signals:
        1. Prompt length > 200 characters
        2. Contains special keywords (tập trung, thực tế, ưu tiên, hạn chế, tránh)
        3. Has extra_instructions (non-empty)
        4. Has bloom_distribution AND prompt > 100 chars
        """
        signals = [
            bool(user_prompt and user_prompt.strip()),
            len(user_prompt or "") > 200,
            any(kw in (user_prompt or "") for kw in ["tập trung", "thực tế", "ưu tiên", "hạn chế", "tránh"]),
            exam_config.get("extra_instructions") not in (None, ""),
            exam_config.get("bloom_distribution") is not None and len(user_prompt or "") > 100,
        ]
        return sum(signals) >= 2

    async def _check_clarity(self, user_prompt: str, exam_config: dict) -> dict | None:
        """Check if requirements are clear, return clarification questions if not."""
        clarity_prompt = f"""Yêu cầu hiện tại:
Prompt: {user_prompt}
Config: {json.dumps(exam_config, ensure_ascii=False, indent=2)}

Xác định xem yêu cầu đã rõ ràng chưa."""

        messages = [
            {"role": "system", "content": self.CLARIFY_SYSTEM_PROMPT},
            {"role": "user", "content": clarity_prompt},
        ]

        try:
            from app.agents.llm import get_llm_client
            client = get_llm_client()
            response = await client.chat(
                messages=messages,
                role="planner",
                max_tokens=1000,
                temperature=0.3,
            )
            result = json.loads(response)
            if not result.get("requirements_clear", True):
                questions = result.get("clarification_questions", [])
                if questions:
                    return {"clarification_questions": questions[:3]}
        except Exception:
            pass
        return None

    async def generate_exam(
        self,
        exam_id: str,
        user_id: str,
        exam_config: dict,
        user_prompt: str | None = None,
        extra_instructions: str | None = None,
        document_id: str | None = None,
    ) -> dict:
        """
        Main entry point: orchestrate the full exam generation pipeline via LangGraph.

        Uses the LangGraph StateGraph instead of the manual if/elif flow.
        Handles HITL interrupts by running a loop:
          1. Run graph.ainvoke() until interrupt or completion
          2. If interrupt: save state and return pause status
          3. Frontend calls approve_blueprint/reject_blueprint to resume

        Returns:
            {
                "exam_id": str,
                "questions": [...],
                "blueprint": {...},
                "cost_report": {...},
                "status": AgentStatus,
                "warnings": [...],
            }
        """
        if self.graph is None:
            from app.agents.graph.builder import build_exam_graph
            self.graph = build_exam_graph()

        config = {"configurable": {"thread_id": exam_id, "recursion_limit": 500}}
        logger.info("Starting graph with recursion_limit=500 for exam_id=%s", exam_id)

        initial_state = {

        initial_state = {
            "exam_id": exam_id,
            "user_id": user_id,
            "document_id": document_id,
            "exam_config": exam_config,
            "user_prompt": user_prompt,
            "extra_instructions": extra_instructions,
            # NOTE: redis and db_session are NOT stored in graph state — nodes
            # retrieve them directly via get_redis_client() / async_session_maker()
            # to avoid msgpack serialization errors with non-serializable objects.
        }

        # Run the graph
        return await self._run_graph(initial_state, config)

    async def _run_graph(self, initial_state: dict, config: dict) -> dict:
        """
        Run the LangGraph and handle interrupts.

        Runs graph.ainvoke() until completion or interrupt.
        - Newer LangGraph (>=0.4): ainvoke() returns {"__interrupt__": [...]} on interrupt.
        - Older LangGraph (<0.4): ainvoke() raises GraphInterrupt(BaseException).
        Both cases mean the graph paused — Celery task returns, HTTP endpoint resumes.
        """
        from langgraph.types import Command
        import time

        try:
            result = await self.graph.ainvoke(initial_state, config)
        except BaseException as e:
            # Handle GraphInterrupt (raised by older LangGraph when interrupt() is called).
            # The graph state is saved in the checkpointer; HTTP endpoint resumes it.
            try:
                from langgraph.types import GraphInterrupt as _GI
                is_interrupt = isinstance(e, _GI)
            except ImportError:
                is_interrupt = False

            if is_interrupt:
                return {
                    "exam_id": initial_state.get("exam_id"),
                    "questions": [],
                    "blueprint": initial_state.get("blueprint") or [],
                    "distribution_summary": initial_state.get("distribution_summary") or {},
                    "cost_report": {},
                    "status": AgentStatus.RETRY_NEEDED,
                    "warnings": initial_state.get("warnings", []) + ["Pipeline paused at checkpoint 1"],
                    "pipeline_paused": True,
                    "interrupt_type": "checkpoint_1",
                }
            raise

        # Handle interrupt in newer LangGraph (returns dict with __interrupt__ key)
        if result.get("__interrupt__"):
            interrupt_type = result.get("__interrupt__", [{}])[0].get("interrupt_type", "")
            checkpoint_id = 1 if "checkpoint_1" in str(interrupt_type) else 2
            return {
                "exam_id": result.get("exam_id"),
                "questions": [],
                "blueprint": result.get("blueprint") or [],
                "distribution_summary": result.get("distribution_summary") or {},
                "cost_report": result.get("cost_report") or {},
                "status": AgentStatus.RETRY_NEEDED,
                "warnings": result.get("warnings", []) + [f"Pipeline paused at checkpoint {checkpoint_id}"],
                "pipeline_paused": True,
                "interrupt_type": interrupt_type,
            }

        # Graph completed normally
        return {
            "exam_id": result.get("exam_id"),
            "questions": result.get("questions") or [],
            "blueprint": result.get("blueprint") or [],
            "distribution_summary": result.get("distribution_summary") or {},
            "cost_report": result.get("cost_report") or {},
            "status": result.get("pipeline_status") == "completed" and AgentStatus.SUCCESS or AgentStatus.PARTIAL,
            "warnings": result.get("warnings", []),
        }

    def _rewrite_requirements(self, exam_config: dict, teacher_prefs: dict) -> dict:
        """Rewrite requirements in structured format for teacher confirmation."""
        scope = exam_config.get("scope", [])
        bloom_dist = exam_config.get("bloom_distribution", {})
        mcq_count = exam_config.get("mcq_count", 40)
        essay_count = exam_config.get("essay_count", 5)
        user_prompt = exam_config.get("user_prompt", "")
        extra = exam_config.get("extra_instructions", "")

        # Build structured summary
        total = sum(bloom_dist.values()) if bloom_dist else 100
        summary_parts = []
        if bloom_dist:
            for level, pct in bloom_dist.items():
                if pct > 0:
                    summary_parts.append(f"- {level}: {pct}%")
        else:
            summary_parts.append("- Bloom distribution: default (20/30/30/20)")

        # Suggest bloom distribution from teacher prefs if available
        suggested_bloom = ""
        if teacher_prefs.get("preferred_bloom_distribution"):
            suggested_bloom = f" (gợi ý từ sở thích giảng viên: {teacher_prefs['preferred_bloom_distribution']})"

        return {
            "scope": scope,
            "total_questions": mcq_count + essay_count,
            "mcq_count": mcq_count,
            "essay_count": essay_count,
            "bloom_distribution_summary": "\n".join(summary_parts) + suggested_bloom,
            "user_prompt": user_prompt,
            "extra_instructions": extra,
            "suggested_exam_type": exam_config.get("exam_type", "mixed"),
        }

    async def _wait_for_blueprint_approval(
        self,
        exam_id: str,
        timeout_seconds: int = 1800,
    ) -> bool:
        """
        Wait for HITL blueprint approval via Redis pub/sub (not polling).

        This is event-driven: instead of polling Redis every 2s (which blocks
        the event loop and prevents WebSocket messages from being received),
        we subscribe to the exam channel and BLOCK until a message arrives.
        """
        import asyncio
        channel = f"exam:{exam_id}"

        # Quick check: if already approved (e.g. from a previous call), return True
        key = f"hitl:approved:{exam_id}:1"
        val = await self.redis.get(key)
        if val is not None:
            normalized = val.decode() if isinstance(val, bytes) else str(val)
            normalized = normalized.strip().lower()
            if normalized == "true":
                logger.info(f"Blueprint already approved for exam {exam_id}")
                return True
            if normalized == "rejected":
                logger.info(f"Blueprint already rejected for exam {exam_id}")
                return False

        # Subscribe to the exam channel and wait for an approval/rejection message
        try:
            sub = self.redis.client.pubsub()
            await sub.subscribe(channel)
            logger.info(f"Subscribed to channel '{channel}', waiting for blueprint approval...")

            start_time = time.time()
            while True:
                elapsed = time.time() - start_time
                if elapsed >= timeout_seconds:
                    logger.warning(f"Blueprint approval timeout for exam {exam_id}")
                    break

                # Wait for message on channel with a short timeout
                msg = await sub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                if msg and msg.get("type") == "message":
                    data = msg.get("data", "")
                    # Parse the approval event
                    try:
                        event = json.loads(data)
                        if event.get("type") in ("blueprint_approved", "hitl_approved"):
                            logger.info(f"Blueprint approved via pub/sub for exam {exam_id}")
                            break
                        if event.get("type") in ("blueprint_rejected", "hitl_rejected"):
                            logger.info(f"Blueprint rejected via pub/sub for exam {exam_id}")
                            return False
                    except Exception:
                        pass

                # Also check Redis key periodically (belt-and-suspenders)
                val = await self.redis.get(key)
                if val is not None:
                    normalized = val.decode() if isinstance(val, bytes) else str(val)
                    normalized = normalized.strip().lower()
                    if normalized == "true":
                        logger.info(f"Blueprint approved via Redis key for exam {exam_id}")
                        break
                    if normalized == "rejected":
                        logger.info(f"Blueprint rejected via Redis key for exam {exam_id}")
                        return False

            await sub.unsubscribe(channel)
            await sub.aclose()
        except Exception as e:
            logger.warning(f"Pub/sub wait failed, falling back to Redis key polling: {e}")
            # Fallback to simple polling
            elapsed = 0
            interval = 2.0
            while elapsed < timeout_seconds:
                val = await self.redis.get(key)
                if val is not None:
                    normalized = val.decode() if isinstance(val, bytes) else str(val)
                    normalized = normalized.strip().lower()
                    if normalized == "true":
                        return True
                    if normalized == "rejected":
                        return False
                await asyncio.sleep(interval)
                elapsed += interval

        # Check final state
        val = await self.redis.get(key)
        if val is not None:
            normalized = val.decode() if isinstance(val, bytes) else str(val)
            normalized = normalized.strip().lower()
            return normalized == "true"
        return False

    async def reject_blueprint(
        self,
        exam_id: str,
        user_id: str,
        feedback: str,
    ) -> dict:
        """
        G8: Re-generate outline with HITL feedback.
        Saves rejection history into Redis session.
        Dispatches a new Celery task to re-run the pipeline from the beginning.
        Frontend receives updated blueprint immediately via WebSocket.
        """
        session = await self.short_term.load_session(exam_id, user_id)
        if not session:
            return {
                "status": "failed",
                "error": "Session not found. Cannot reject blueprint.",
            }

        original_config = session.get("exam_config_original", {})
        if not original_config:
            original_config = session.get("exam_config", {})

        # Store feedback as additional instruction
        original_config["outline_feedback"] = feedback

        # Save rejection history in Redis
        history_key = f"hitl:rejection_history:{exam_id}"
        try:
            import json
            existing = await self.redis.get(history_key)
            history = json.loads(existing) if existing else []
            history.append({"feedback": feedback, "timestamp": time.time()})
            await self.redis.set(history_key, json.dumps(history), ttl=3600)
        except Exception:
            pass

        # Emit updated HITL checkpoint 1 with new blueprint immediately
        # (Celery task will re-run and emit via WebSocket again)
        # For immediate response: re-run outline now and emit result
        try:
            outline_result = await self.outline.create_outline(
                retrieved_context=session.get("retrieved_context", []),
                exam_config=original_config,
                trace_id=f"{exam_id}_outline_reject",
            )

            blueprint = []
            distribution_summary = {}
            if hasattr(outline_result, 'blueprint'):
                blueprint = outline_result.blueprint
            if hasattr(outline_result, 'distribution_summary'):
                distribution_summary = outline_result.distribution_summary
        except Exception:
            blueprint = []
            distribution_summary = {}

        # Emit new HITL checkpoint 1 with updated blueprint
        await self._emit({
            "type": "hitl_checkpoint",
            "checkpoint_id": 1,
            "data": {
                "blueprint": blueprint,
                "distribution_summary": distribution_summary,
                "rejection_history": feedback,
            },
        })

        # Dispatch Celery task to re-run full pipeline from scratch
        try:
            from app.tasks.exam_task import generate_exam_task
            generate_exam_task.delay(
                exam_id=exam_id,
                user_id=user_id,
                document_id=session.get("document_id"),
                scope=session.get("scope", []),
                exam_config={**original_config},
                user_prompt=original_config.get("user_prompt", ""),
                extra_instructions=original_config.get("extra_instructions", ""),
            )
        except Exception:
            logger.error("Failed to dispatch Celery task for reject_blueprint, exam_id=%s", exam_id)

        return {
            "status": "rejected_with_feedback",
            "blueprint": blueprint,
            "distribution_summary": distribution_summary,
            "message": "Blueprint đã được điều chỉnh theo phản hồi của bạn. Đề đang được sinh lại.",
        }

    async def approve_blueprint(
        self,
        exam_id: str,
        user_id: str,
    ) -> None:
        """
        Unblock pipeline at HITL checkpoint 1.
        Saves Redis key: hitl:approved:{exam_id}:1
        Called by frontend after teacher reviews the blueprint.
        """
        key = f"hitl:approved:{exam_id}:1"
        await self.redis.set(key, "true", ttl=3600)

    async def submit_review(
        self,
        exam_id: str,
        user_id: str,
        approved: bool,
        feedback: str | None = None,
        direct_edits: list[dict] | None = None,
    ) -> dict:
        """
        Handle full exam review submission from HITL checkpoint 2.

        Args:
            exam_id: The exam being reviewed
            user_id: The reviewing user
            approved: Whether the user approves the exam
            feedback: Optional feedback/revision request
            direct_edits: Optional direct question edits
        """
        session = await self.short_term.load_session(exam_id, user_id)
        if not session:
            return {
                "status": "failed",
                "error": "Session not found. Please start a new generation.",
            }

        if approved:
            # G14: Persist teacher preferences to long-term memory after approval
            if self.long_term:
                try:
                    exam_config = session.get("exam_config_original", {})
                    await self.long_term.save_preferences(
                        user_id=UUID(user_id),
                        preferred_bloom_distribution=exam_config.get("bloom_distribution"),
                        preferred_exam_types={"types": [exam_config.get("exam_type", "mixed")]},
                        subject_focus=",".join(exam_config.get("scope", [])),
                    )
                except Exception:
                    pass  # Non-blocking — preferences save failure shouldn't block approval

            # Snapshot exam_history with change_type='published'
            history_key = f"exam_history:{exam_id}"
            try:
                import json as _json
                history_entry = {
                    "change_type": "published",
                    "timestamp": time.time(),
                    "user_id": user_id,
                    "exam_config": session.get("exam_config_original", {}),
                    "topics_used": session.get("topics_used", []),
                    "questions_count": len(session.get("questions", [])) if session.get("questions") else 0,
                }
                existing_hist = await self.redis.get(history_key)
                hist_list = _json.loads(existing_hist) if existing_hist else []
                hist_list.append(history_entry)
                await self.redis.set(history_key, _json.dumps(hist_list), ttl=86400)
            except Exception:
                pass

            await self.short_term.save_session(exam_id, user_id, {
                "exam_config_original": session.get("exam_config_original", {}),
                "topics_used": session.get("topics_used", []),
                "conversation_history": session.get("conversation_history", []),
                "retry_count": session.get("retry_count", 0),
                "review_approved": True,
                "review_feedback": feedback,
            })

            # HITL Checkpoint 2: Set Redis key so orchestrator's poll loop unblocks
            await self.redis.set(f"hitl:approved:{exam_id}:2", "true", ttl=3600)

            return {
                "status": "approved",
                "message": "Đề đã được phê duyệt và sẵn sàng xuất.",
                "exam_id": exam_id,
            }
        else:
            # G8 (checkpoint 2 reject): Queue Celery task for regeneration
            original_config = session.get("exam_config_original", {})
            if feedback:
                original_config["review_feedback"] = feedback
            if direct_edits:
                original_config["direct_edits"] = direct_edits

            # Store the review feedback for the regeneration task
            await self.short_term.save_session(exam_id, user_id, {
                **session,
                "review_feedback": feedback,
                "direct_edits": direct_edits,
            })

            # Dispatch Celery task — do NOT call generate_exam directly (would block HTTP)
            try:
                from app.tasks.exam_task import generate_exam_task
                generate_exam_task.delay(
                    exam_id=exam_id,
                    user_id=user_id,
                    document_id=session.get("document_id"),
                    scope=session.get("scope", []),
                    exam_config={**original_config, "review_feedback": feedback},
                    user_prompt=original_config.get("user_prompt", ""),
                    extra_instructions=feedback,
                )
            except Exception:
                pass  # Non-blocking

            return {
                "status": "regenerating",
                "message": "Đề đang được sinh lại theo phản hồi của bạn.",
                "checkpoint": 2,
            }

    async def edit_via_prompt(
        self,
        exam_id: str,
        user_id: str,
        prompt: str,
    ) -> dict:
        """
        Handle prompt-based editing.
        Load session from Redis, build full context, process edit.
        """
        # Load session from Redis
        session = await self.short_term.load_session(exam_id, user_id)
        if not session:
            return {
                "status": "failed",
                "error": "Session not found. Please start a new generation.",
            }

        # Build full context for LLM
        exam_config_original = session.get("exam_config_original", {})
        topics_used = session.get("topics_used", [])
        conversation_history = session.get("conversation_history", [])

        # Append user prompt to history
        await self.short_term.append_history(exam_id, user_id, "user", prompt)

        # Build edit prompt
        history_str = "\n".join(
            f"[{h.get('role')}]: {h.get('content')}"
            for h in conversation_history[-5:]
        )

        edit_prompt = f"""Yêu cầu chỉnh sửa từ giảng viên:
"{prompt}"

## Cấu hình gốc của đề:
{json.dumps(exam_config_original, ensure_ascii=False, indent=2)}

## Lịch sử hội thoại gần đây:
{history_str}

## Topics đã sử dụng:
{json.dumps(topics_used, ensure_ascii=False)}

Hãy phân tích yêu cầu chỉnh sửa và quyết định:
1. Câu nào cần sửa?
2. Sửa theo hướng nào?
3. Có cần gọi lại Builder Agent không?

Trả về JSON:
{{
  "edit_plan": {{
    "target_question_ids": ["MCQ_001"],
    "edit_type": "regenerate",
    "regenerate_prompt": "..."
  }},
  "direct_edits": []
}}"""

        try:
            from app.agents.llm import get_llm_client
            client = get_llm_client()
            response = await client.chat(
                messages=[
                    {"role": "system", "content": "Bạn là chuyên gia phân tích yêu cầu chỉnh sửa đề kiểm tra."},
                    {"role": "user", "content": edit_prompt},
                ],
                role="builder",
                max_tokens=2000,
                temperature=0.3,
            )
            edit_plan = json.loads(response)
        except Exception as e:
            return {
                "status": "partial",
                "error": f"Failed to parse edit request: {str(e)}",
            }

        # Process the edit plan (simplified)
        response_msg = f"Đã xử lý yêu cầu: {edit_plan.get('edit_plan', {}).get('edit_type', 'unknown')}"
        await self.short_term.append_history(exam_id, user_id, "assistant", response_msg)

        return {
            "status": "success",
            "message": response_msg,
            "edit_plan": edit_plan,
        }
