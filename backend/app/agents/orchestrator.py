"""Orchestrator Agent - main entry point that coordinates all sub-agents."""

import time
import uuid
import json
from typing import Any, Callable, Awaitable
from uuid import UUID

from app.agents.base import AgentBaseOutput, AgentStatus, TokenUsage
from app.agents.retrieval import RetrievalAgent
from app.agents.outline import OutlineAgent
from app.agents.builder import BuilderAgent
from app.agents.validator import ValidatorAgent
from app.agents.planner import PlannerAgent
from app.agents.memory import ShortTermMemory, LongTermMemory
from app.agents.skills.bloom_classifier import BloomClassifierSkill
from app.agents.skills.scope_checker import ScopeCheckerSkill
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
        self.validator = ValidatorAgent()
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
                model=settings.OPENAI_MODEL_PLANNER,
                response_format={"type": "json_object"},
                max_tokens=1000,
                temperature=0.3,
            )
            result = json.loads(response["content"])
            if not result.get("requirements_clear", True):
                questions = result.get("clarification_questions", [])
                if questions:
                    return {"clarification_questions": questions[:3]}
        except Exception:
            pass
        return None

    async def generate_exam(
        self,
        user_id: str,
        document_id: str,
        scope: list[str],
        exam_config: dict,
        user_prompt: str | None = None,
        extra_instructions: str | None = None,
        trace_id: str = "",
    ) -> dict:
        """
        Main entry point: orchestrate the full exam generation pipeline.

        Returns:
            {
                "exam_id": UUID,
                "questions": [...],
                "blueprint": {...},
                "cost_report": {...},
                "status": AgentStatus,
                "warnings": [...],
            }
        """
        trace_id = trace_id or str(uuid.uuid4())
        start_time = time.time()
        warnings: list[str] = []
        cost_report: dict[str, Any] = {}

        # Merge exam config
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
            exam_config_original=full_config,
            topics_used=[],
            conversation_history=[],
            retry_count=0,
        )

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

        # Step 3: Determine if complex (needs Planner) or simple
        is_complex = self.planner.is_complex_request(
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
            document_id=document_id,
            scope_chapters=scope,
            bloom_targets=bloom_targets,
            trace_id=trace_id,
        )

        if retrieval_result.status == AgentStatus.PARTIAL:
            warnings.append("Retrieval returned partial results")
        elif retrieval_result.status == AgentStatus.FAILED:
            warnings.append("Retrieval failed - proceeding with empty context")

        retrieved_chunks = []
        if hasattr(retrieval_result, 'retrieved_chunks'):
            retrieved_chunks = retrieval_result.retrieved_chunks

        cost_report["retrieval"] = retrieval_result.token_usage.model_dump()

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

        blueprint = []
        if hasattr(outline_result, 'blueprint'):
            blueprint = outline_result.blueprint
        distribution_summary = {}
        if hasattr(outline_result, 'distribution_summary'):
            distribution_summary = outline_result.distribution_summary

        cost_report["outline"] = outline_result.token_usage.model_dump()

        if outline_result.status != AgentStatus.SUCCESS:
            warnings.append("Outline creation had issues")

        self._pending_blueprint = blueprint
        self._pending_distribution = distribution_summary

        # ─── HITL Checkpoint 1: Blueprint Review ───
        await self._emit({
            "type": "hitl_checkpoint",
            "checkpoint_id": 1,
            "data": {
                "blueprint": blueprint,
                "distribution_summary": distribution_summary,
            },
        })

        blueprint_approved = True
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

        questions = []
        if hasattr(builder_result, 'questions'):
            questions = builder_result.questions
        elif hasattr(builder_result, 'generated_questions'):
            questions = builder_result.generated_questions

        cost_report["builder"] = builder_result.token_usage.model_dump()

        if builder_result.status != AgentStatus.SUCCESS:
            warnings.append("Builder had issues generating questions")

        if questions:
            new_topics = [q.get("topic_hint", "") for q in questions if q.get("topic_hint")]
            topics_used = list(set(topics_used + new_topics))
            await self.short_term.update_topics(trace_id, user_id, topics_used)

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
            and issues
        ):
            retry_count += 1
            await self.short_term.increment_retry(trace_id, user_id)
            warnings.append(f"Validation issues found - retry {retry_count}/{max_retries}")

            await self._emit({
                "type": "plan_step",
                "message": f"Đang sửa câu hỏi (retry {retry_count})...",
                "step": 4,
                "total_steps": 5,
            })

            bad_question_ids = {issue["question_id"] for issue in issues}
            filtered_blueprint = [s for s in blueprint if s.get("question_id") not in bad_question_ids]

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

        total = sum(bloom_dist.values()) if bloom_dist else 100
        summary_parts = []
        if bloom_dist:
            for level, pct in bloom_dist.items():
                if pct > 0:
                    summary_parts.append(f"- {level}: {pct}%")
        else:
            summary_parts.append("- Bloom distribution: default (20/30/30/20)")

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

    async def approve_blueprint(
        self,
        exam_id: str,
        user_id: str,
        approved: bool,
        feedback: str | None = None,
    ) -> dict:
        """Handle blueprint approval/rejection from HITL checkpoint 1."""
        if not approved and feedback:
            session = await self.short_term.load_session(exam_id, user_id)
            if session:
                original_config = session.get("exam_config_original", {})
                original_config["outline_feedback"] = feedback

                outline_result = await self.outline.create_outline(
                    retrieved_context=[],
                    exam_config=original_config,
                    trace_id=f"{exam_id}_outline_regen",
                )

                blueprint = []
                if hasattr(outline_result, 'blueprint'):
                    blueprint = outline_result.blueprint

                return {
                    "status": "rejected_with_feedback",
                    "blueprint": blueprint,
                    "message": "Blueprint đã được điều chỉnh theo phản hồi của bạn",
                }

        return {
            "status": "approved",
            "message": "Blueprint đã được phê duyệt. Bắt đầu sinh câu hỏi.",
        }

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
            await self.short_term.save_session(exam_id, user_id, {
                **session,
                "review_approved": True,
                "review_feedback": feedback,
            })
            return {
                "status": "approved",
                "message": "Đề đã được phê duyệt và sẵn sàng xuất.",
                "exam_id": exam_id,
            }
        else:
            original_config = session.get("exam_config_original", {})
            if feedback:
                original_config["review_feedback"] = feedback
            if direct_edits:
                original_config["direct_edits"] = direct_edits

            await self.short_term.save_session(exam_id, user_id, {
                **session,
                "review_feedback": feedback,
                "direct_edits": direct_edits,
            })

            try:
                result = await self.generate_exam(
                    user_id=user_id,
                    document_id=session.get("document_id"),
                    scope=session.get("scope", []),
                    exam_config=original_config,
                    user_prompt=original_config.get("user_prompt", ""),
                    extra_instructions=feedback,
                )
                return {
                    "status": "regenerating",
                    "message": "Đề đang được sinh lại theo phản hồi của bạn.",
                    "result": result,
                }
            except Exception as e:
                return {
                    "status": "failed",
                    "error": f"Regeneration failed: {str(e)}",
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
        session = await self.short_term.load_session(exam_id, user_id)
        if not session:
            return {
                "status": "failed",
                "error": "Session not found. Please start a new generation.",
            }

        exam_config_original = session.get("exam_config_original", {})
        topics_used = session.get("topics_used", [])
        conversation_history = session.get("conversation_history", [])

        await self.short_term.append_history(exam_id, user_id, "user", prompt)

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
                model=settings.OPENAI_MODEL_BUILDER,
                response_format={"type": "json_object"},
                max_tokens=2000,
                temperature=0.3,
            )
            edit_plan = json.loads(response["content"])
        except Exception as e:
            return {
                "status": "partial",
                "error": f"Failed to parse edit request: {str(e)}",
            }

        response_msg = f"Đã xử lý yêu cầu: {edit_plan.get('edit_plan', {}).get('edit_type', 'unknown')}"
        await self.short_term.append_history(exam_id, user_id, "assistant", response_msg)

        return {
            "status": "success",
            "message": response_msg,
            "edit_plan": edit_plan,
        }
