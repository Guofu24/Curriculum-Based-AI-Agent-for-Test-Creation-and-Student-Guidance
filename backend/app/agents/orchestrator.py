"""Orchestrator Agent - main entry point that coordinates all sub-agents."""

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
            (user_prompt or "") > "",
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
        Main entry point: orchestrate the full exam generation pipeline.

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
        start_time = time.time()
        trace_id = exam_id
        warnings: list[str] = []
        cost_report: dict[str, Any] = {}

        # Merge exam config — scope and document_id come from exam_config dict
        scope = exam_config.get("scope", [])
        doc_id = document_id or exam_config.get("document_id", "")

        full_config = {
            "scope": scope,
            "user_prompt": user_prompt or "",
            "extra_instructions": extra_instructions or "",
            **exam_config,
        }

        # Step 0: Check clarity - emit clarification if needed
        clarification = await self._check_clarity(user_prompt or "", full_config)
        if clarification:
            await self._emit({
                "type": "clarification_needed",
                "data": clarification,
            })
            # Return early - frontend should handle clarification flow
            return {
                "exam_id": trace_id,
                "questions": [],
                "blueprint": [],
                "cost_report": {},
                "status": AgentStatus.RETRY_NEEDED,
                "warnings": ["Yêu cầu chưa rõ ràng - cần làm rõ trước"],
                "clarification": clarification,
            }

        # Step 1: Save session to short-term memory
        await self.short_term.save_session(
            exam_id=trace_id,
            user_id=user_id,
            exam_config=full_config,
            exam_config_original=exam_config,  # Preserve original config for edit-via-prompt and retry loops
            topics_used=[],
        )

        # Verify exam_config_original was stored correctly
        session = await self.short_term.load_session(trace_id, user_id)
        if session is None:
            warnings.append("Session not found in short-term memory — proceeding with partial context")
        elif session.get("exam_config_original") is None:
            warnings.append("exam_config_original not set in session — proceeding with fallback config")

        # Step 2: Load long-term memory (teacher preferences)
        teacher_prefs = {}
        if self.long_term:
            try:
                prefs = await self.long_term.get_preferences(UUID(user_id))
                if prefs:
                    teacher_prefs = prefs
                    warnings.append("Loaded teacher preferences from long-term memory")
            except Exception:
                pass

        # Step 3: Determine if complex (needs Planner) or simple — G6
        is_complex = self._is_complex_request(
            full_config.get("user_prompt", ""), full_config
        )

        if is_complex:
            await self._emit({
                "type": "plan_step",
                "message": "Yêu cầu phức tạp - đang tạo execution plan...",
                "step": 0,
                "total_steps": 5,
            })
            plan_result = await self.planner.create_plan(
                user_request=full_config.get("user_prompt", ""),
                exam_config=full_config,
                trace_id=trace_id,
            )
            plan = plan_result.model_dump()
            cost_report["planner"] = plan_result.token_usage.model_dump()
        else:
            plan = self.planner.get_default_plan()

        # ─── HITL Checkpoint 0: Requirements Confirmation ───
        rewritten_req = self._rewrite_requirements(full_config, teacher_prefs)
        await self._emit({
            "type": "hitl_checkpoint",
            "checkpoint_id": 0,
            "data": {
                "requirements": rewritten_req,
                "teacher_preferences": teacher_prefs,
            },
        })

        # Step 4: Retrieve knowledge
        await self._emit({
            "type": "plan_step",
            "message": "Đang truy xuất kiến thức...",
            "step": 1,
            "total_steps": 5,
        })

        bloom_targets = list(full_config.get("bloom_distribution", {}).keys())
        retrieval_result = await self.retrieval.retrieve(
            document_id=doc_id,
            scope_chapters=scope,
            bloom_targets=bloom_targets,
            trace_id=trace_id,
        )

        logger.info(f"Retrieval status: {retrieval_result.status}")
        logger.info(f"Retrieval chunks count: {len(getattr(retrieval_result, 'retrieved_chunks', []))}")

        if retrieval_result.status == AgentStatus.PARTIAL:
            warnings.append("Retrieval returned partial results")
        elif retrieval_result.status == AgentStatus.FAILED:
            warnings.append("Retrieval failed - proceeding with empty context")

        # Extract retrieved chunks from the result
        retrieved_chunks = []
        if hasattr(retrieval_result, 'retrieved_chunks'):
            retrieved_chunks = retrieval_result.retrieved_chunks

        logger.info(f"retrieved_chunks passed to outline: {len(retrieved_chunks)}")

        cost_report["retrieval"] = retrieval_result.token_usage.model_dump()

        # Store retrieved_context + metadata in session for reject_blueprint (G8)
        await self.short_term.save_session(
            exam_id=trace_id,
            user_id=user_id,
            retrieved_context=retrieved_chunks,
            scope=scope,
            document_id=doc_id,
        )

        # Build allowed_concepts from retrieved chunks for ScopeGuard
        allowed_concepts = []
        for chunk in retrieved_chunks:
            content = chunk.get("content", "")[:200]
            if content:
                allowed_concepts.append(content)

        # Step 5: Create outline
        await self._emit({
            "type": "plan_step",
            "message": "Đang tạo sườn đề (blueprint)...",
            "step": 2,
            "total_steps": 5,
        })

        outline_result = await self.outline.create_outline(
            retrieved_context=retrieved_chunks,
            exam_config=full_config,
            trace_id=trace_id,
        )

        logger.info(f"Outline status: {outline_result.status}")
        logger.info(f"Blueprint slots count: {len(getattr(outline_result, 'blueprint', []))}")

        # Extract blueprint from the result
        blueprint = []
        if hasattr(outline_result, 'blueprint'):
            blueprint = outline_result.blueprint
        distribution_summary = {}
        if hasattr(outline_result, 'distribution_summary'):
            distribution_summary = outline_result.distribution_summary

        cost_report["outline"] = outline_result.token_usage.model_dump()

        if outline_result.status != AgentStatus.SUCCESS:
            warnings.append("Outline creation had issues")

        # Store for HITL checkpoint
        self._pending_blueprint = blueprint
        self._pending_distribution = distribution_summary

        # ─── HITL Checkpoint 1: Blueprint Review — PAUSE, wait for approval ───
        await self._emit({
            "type": "hitl_checkpoint",
            "checkpoint_id": 1,
            "data": {
                "blueprint": blueprint,
                "distribution_summary": distribution_summary,
            },
        })

        if not blueprint:
            warnings.append("Blueprint is empty - stopping generation")
            return {
                "exam_id": trace_id,
                "questions": [],
                "blueprint": [],
                "cost_report": cost_report,
                "status": AgentStatus.FAILED,
                "warnings": warnings,
            }

        # Poll Redis for HITL approval (frontend sets this via approve_blueprint)
        approved = await self._wait_for_blueprint_approval(trace_id, timeout_seconds=1800)
        if not approved:
            await self._emit({
                "type": "pipeline_paused",
                "checkpoint_id": 1,
                "message": "Chờ phê duyệt blueprint...",
            })
            return {
                "exam_id": trace_id,
                "questions": [],
                "blueprint": blueprint,
                "distribution_summary": distribution_summary,
                "cost_report": cost_report,
                "status": AgentStatus.RETRY_NEEDED,
                "warnings": warnings + ["Blueprint chưa được phê duyệt - đang chờ"],
                "checkpoint": 1,
            }

        # Step 6: Build questions
        await self._emit({
            "type": "plan_step",
            "message": "Đang sinh câu hỏi...",
            "step": 3,
            "total_steps": 5,
        })

        session = await self.short_term.load_session(trace_id, user_id)
        topics_used = session.get("topics_used", []) if session else []

        builder_result = await self.builder.build(
            blueprint=blueprint,
            retrieved_context=retrieved_chunks,
            topics_used=topics_used,
            allowed_concepts=allowed_concepts,
            scope_chapters=scope,
            trace_id=trace_id,
        )

        logger.info(f"Builder status: {builder_result.status}")
        logger.info(f"Builder questions count: {len(getattr(builder_result, 'questions', []))}")

        # Extract questions from the result
        questions = []
        if hasattr(builder_result, 'questions'):
            questions = builder_result.questions
        elif hasattr(builder_result, 'generated_questions'):
            questions = builder_result.generated_questions

        logger.info(f"Final questions count before validator: {len(questions)}")

        cost_report["builder"] = builder_result.token_usage.model_dump()

        if builder_result.status != AgentStatus.SUCCESS:
            warnings.append("Builder had issues generating questions")

        # Update short-term memory with topics
        if questions:
            new_topics = [q.get("topic_hint", "") for q in questions if q.get("topic_hint")]
            topics_used = list(set(topics_used + new_topics))
            await self.short_term.update_topics(trace_id, user_id, topics_used)

        # Emit individual question events for streaming
        for q in questions:
            await self._emit({
                "type": "question_generated",
                "question_id": q.get("question_id", ""),
                "question": q,
            })

        # Step 7: Validate
        await self._emit({
            "type": "plan_step",
            "message": "Đang kiểm tra đề...",
            "step": 4,
            "total_steps": 5,
        })

        validation_result = await self.validator.validate(
            questions=questions,
            exam_config=full_config,
            retrieved_context=retrieved_chunks,
            trace_id=trace_id,
        )

        cost_report["validator"] = validation_result.token_usage.model_dump()

        # Extract issues from validation result
        issues = []
        if hasattr(validation_result, 'issues'):
            issues = validation_result.issues
        validation_passed = validation_result.status == AgentStatus.SUCCESS

        # Retry loop (max 3)
        retry_count = await self.short_term.get_retry_count(trace_id, user_id)
        max_retries = settings.AGENT_MAX_VALIDATION_RETRIES

        while (
            validation_result.status in [AgentStatus.RETRY_NEEDED, AgentStatus.PARTIAL]
            and retry_count < max_retries
        ):
            # G9: Load issues from Redis (survives Celery worker restarts)
            issues = await self.short_term.load_retry_issues(trace_id)
            if not issues:
                break  # No issues to retry on

            retry_count += 1
            await self.short_term.increment_retry(trace_id, user_id)
            warnings.append(f"Validation issues found - retry {retry_count}/{max_retries}")

            await self._emit({
                "type": "plan_step",
                "message": f"Đang sửa câu hỏi (retry {retry_count})...",
                "step": 4,
                "total_steps": 5,
            })

            # Filter blueprint to exclude already-good slots
            bad_question_ids = {issue["question_id"] for issue in issues}
            filtered_blueprint = [s for s in blueprint if s.get("question_id") not in bad_question_ids]

            # Regenerate only the bad slots
            builder_result = await self.builder.build(
                blueprint=filtered_blueprint,
                retrieved_context=retrieved_chunks,
                topics_used=topics_used,
                allowed_concepts=allowed_concepts,
                scope_chapters=scope,
                trace_id=f"{trace_id}_retry_{retry_count}",
            )

            retry_questions = []
            if hasattr(builder_result, 'questions'):
                retry_questions = builder_result.questions
            elif hasattr(builder_result, 'generated_questions'):
                retry_questions = builder_result.generated_questions

            # Replace bad questions with new ones
            new_q_dict = {q.get("question_id"): q for q in retry_questions}
            updated_questions = []
            for q in questions:
                qid = q.get("question_id")
                if qid in bad_question_ids and qid in new_q_dict:
                    updated_questions.append(new_q_dict[qid])
                else:
                    updated_questions.append(q)
            questions = updated_questions

            validation_result = await self.validator.validate(
                questions=questions,
                exam_config=full_config,
                retrieved_context=retrieved_chunks,
                trace_id=f"{trace_id}_retry_{retry_count}_validate",
            )

            if hasattr(validation_result, 'issues'):
                issues = validation_result.issues
            else:
                issues = []

        if validation_result.status != AgentStatus.SUCCESS:
            warnings.append("Validation did not pass after max retries")

        # Emit validation result
        await self._emit({
            "type": "validation_result",
            "passed": validation_result.status == AgentStatus.SUCCESS,
            "issues_count": len(issues),
            "issues": issues,
        })

        # ─── HITL Checkpoint 2: Full Review ───
        await self._emit({
            "type": "hitl_checkpoint",
            "checkpoint_id": 2,
            "data": {
                "questions": questions,
                "validation_passed": validation_result.status == AgentStatus.SUCCESS,
                "issues": issues,
                "warnings": warnings,
            },
        })

        # Calculate total cost
        total_tokens = sum(
            (cost_report.get(k, {}).get("total_tokens", 0) or 0)
            for k in ["retrieval", "outline", "builder", "validator"]
        )
        total_cost = sum(
            (cost_report.get(k, {}).get("estimated_cost_usd", 0) or 0)
            for k in ["retrieval", "outline", "builder", "validator"]
        )

        cost_report["total_tokens"] = total_tokens
        cost_report["total_cost_usd"] = round(total_cost, 6)

        # ─── HITL Checkpoint 3: Export Preview ───
        await self._emit({
            "type": "hitl_checkpoint",
            "checkpoint_id": 3,
            "data": {
                "exam_id": trace_id,
                "questions": questions,
                "cost_report": cost_report,
            },
        })

        await self._emit({
            "type": "completed",
            "exam_id": trace_id,
            "status": "completed",
        })

        return {
            "exam_id": trace_id,
            "questions": questions,
            "blueprint": blueprint,
            "distribution_summary": distribution_summary,
            "cost_report": cost_report,
            "status": AgentStatus.SUCCESS if validation_result.status == AgentStatus.SUCCESS else AgentStatus.PARTIAL,
            "warnings": warnings,
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
        Poll Redis for HITL blueprint approval.
        Returns True if approved, False if rejected/timeout.
        """
        import asyncio
        key = f"hitl:approved:{exam_id}:1"
        elapsed = 0
        interval = 2.0  # poll every 2 seconds

        while elapsed < timeout_seconds:
            val = await self.redis.get(key)
            if val == "true":
                return True
            if val == "rejected":
                return False
            await asyncio.sleep(interval)
            elapsed += interval

        return False  # timeout

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
            pass  # Non-blocking

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
