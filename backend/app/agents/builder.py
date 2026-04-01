"""Builder Agent - generates actual questions from blueprint slots."""

import time
import json
import asyncio
from typing import Any

from app.agents.base import AgentBaseOutput, AgentStatus, AgentMetrics, TokenUsage, BuilderOutput
from app.agents.llm import get_llm_client
from app.agents.guardrails import GuardrailsPipeline, ScopeGuard
from app.agents.skills.bloom_classifier import BloomClassifierSkill
from app.agents.skills.dedup_checker import DedupCheckerSkill
from app.agents.skills.difficulty_estimator import DifficultyEstimatorSkill
from app.agents.skills.latex_renderer import LatexRendererSkill
from app.observability.tracer import get_tracer
from app.utils.search import search_similar_problems
from app.core.config import get_settings

settings = get_settings()
tracer = get_tracer()


class BuilderAgent:
    """
    Agent 3: Builder Agent

    Role: Generate actual questions from blueprint slots.
    Produces MCQ and Essay questions with full details.

    Flow:
    1. Generate in chunks: 5-10 questions per LLM call
    2. Each question: bloom_classifier → dedup_checker → content_filter
    3. van_dung_cao: web_search tool → adapt into scope
    4. Formula: text + LaTeX parallel output
    5. Append topics_used to Redis

    Rules:
    - MCQ: 4 options, 1 correct, 3 distractors with logic
    - Essay: must have grading rubric
    """

    BUILDER_SYSTEM_PROMPT = """Bạn là chuyên gia sinh câu hỏi kiểm tra chất lượng cao.

Nhiệm vụ:
1. Sinh câu hỏi MCQ và Essay từ blueprint slots
2. Đảm bảo câu hỏi đúng mức Bloom đã khai báo
3. MCQ: 4 lựa chọn, 1 đáp án đúng, 3 mồi nhử có logic (không lộ liễu)
4. Essay: có rubric chấm điểm rõ ràng
5. Công thức: output dạng text + LaTeX song song
6. Không trùng lặp chủ đề với câu đã sinh
7. Chỉ dùng kiến thức trong phạm vi cho phép

MCQ Format:
{
  "question_id": "MCQ_001",
  "type": "mcq",
  "stem": "Câu hỏi...",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correct_answer": "B",
  "explanation": "Giải thích ngắn gọn...",
  "bloom_level": "thong_hieu",
  "chapter": "Chương 1",
  "section": "1.2 Định luật Newton",
  "latex_content": "F = ma"
}

Essay Format:
{
  "question_id": "ESSAY_001",
  "type": "essay",
  "stem": "Câu hỏi tự luận...",
  "rubric": [
    {"score": 4, "description": "Hoàn toàn đúng..."},
    {"score": 3, "description": "Đúng nhưng thiếu..."},
    {"score": 2, "description": "Sai sót..."},
    {"score": 1, "description": "Sai nhiều..."}
  ],
  "bloom_level": "van_dung_cao",
  "chapter": "Chương 2",
  "estimated_solve_time_minutes": 10
}

Trả về JSON:
{
  "questions": [q1, q2, ...]
}"""

    # Chunk size: questions per LLM call
    CHUNK_SIZE = 8

    def __init__(self, redis_client=None):
        self.llm = get_llm_client()
        self.guardrails = GuardrailsPipeline()
        self.bloom_skill = BloomClassifierSkill()
        self.dedup_skill = DedupCheckerSkill()
        self.difficulty_skill = DifficultyEstimatorSkill()
        self.latex_skill = LatexRendererSkill()
        self.redis = redis_client

    @tracer.agent_span("builder_agent")
    async def build(
        self,
        blueprint: list[dict],
        retrieved_context: list[dict],
        topics_used: list[str] | None = None,
        allowed_concepts: list[str] | None = None,
        scope_chapters: list[str] | None = None,
        trace_id: str = "",
    ) -> BuilderOutput:
        """Build questions from blueprint."""
        start_time = time.time()
        trace_id = trace_id or str(time.time())
        metrics = AgentMetrics(trace_id=trace_id)
        warnings: list[str] = []
        topics_used = topics_used or []
        all_questions: list[dict] = []
        chunks_referenced: list[str] = []

        try:
            # Build context for generation
            context_for_llm = self._build_context_for_llm(retrieved_context)

            # Get scope restriction prompt
            scope_guard = ScopeGuard(
                allowed_concepts=allowed_concepts or [],
                scope_chapters=scope_chapters or [],
            )
            scope_restriction = (
                scope_guard.get_allowed_concepts_prompt()
                + "\n"
                + scope_guard.get_scope_restriction_prompt()
            )

            # Process blueprint in chunks
            blueprint_chunks = [
                blueprint[i:i + self.CHUNK_SIZE]
                for i in range(0, len(blueprint), self.CHUNK_SIZE)
            ]

            for chunk_idx, chunk in enumerate(blueprint_chunks):
                # Check token budget
                budget_status = self.guardrails.check_budget(8000)
                if budget_status == "stop":
                    warnings.append("Token budget exhausted. Stopping generation.")
                    break

                # Generate questions for this chunk
                questions, chunk_warnings = await self._generate_chunk(
                    chunk=chunk,
                    context=context_for_llm,
                    scope_restriction=scope_restriction,
                    topics_used=topics_used,
                )

                warnings.extend(chunk_warnings)

                # Validate each question
                validated = self.guardrails.validate_batch(questions)

                for q in validated:
                    if not q.get("filter_passed", True):
                        warnings.append(
                            f"Question {q.get('question_id')} failed filter: {q.get('filter_error')}"
                        )
                        continue

                    all_questions.append(q)

                    # Track topics
                    if q.get("topic_hint"):
                        topics_used.append(q["topic_hint"])

                    # Track referenced chunks
                    if q.get("evidence_chunks"):
                        chunks_referenced.extend(q["evidence_chunks"])

                # Record token usage
                metrics.completion_tokens += len(questions) * 50  # Estimate

            # Build output
            elapsed_ms = int((time.time() - start_time) * 1000)
            usage = metrics.prompt_tokens + metrics.completion_tokens

            return BuilderOutput(
                status=AgentStatus.SUCCESS,
                agent_name="builder",
                execution_time_ms=elapsed_ms,
                token_usage=TokenUsage(
                    prompt_tokens=metrics.prompt_tokens,
                    completion_tokens=metrics.completion_tokens,
                    total_tokens=usage,
                ),
                warnings=warnings,
                trace_id=trace_id,
                questions=all_questions,
                topics_used=topics_used,
                chunks_referenced=chunks_referenced,
            )

        except Exception as e:
            warnings.append(f"Builder failed: {str(e)}")

            return BuilderOutput(
                status=AgentStatus.PARTIAL,
                agent_name="builder",
                execution_time_ms=int((time.time() - start_time) * 1000),
                token_usage=TokenUsage(),
                warnings=warnings,
                trace_id=trace_id,
                questions=all_questions,
                topics_used=topics_used,
                chunks_referenced=chunks_referenced,
            )

    async def _generate_chunk(
        self,
        chunk: list[dict],
        context: str,
        scope_restriction: str,
        topics_used: list[str],
    ) -> tuple[list[dict], list[str]]:
        """Generate questions for a single blueprint chunk."""
        warnings = []

        # Build prompt for this chunk
        blueprint_json = json.dumps(chunk, ensure_ascii=False, indent=2)

        # G4: For van_dung_cao slots, fetch web search context
        van_dung_cao_slots = [s for s in chunk if s.get("bloom_level") == "van_dung_cao"]
        search_context = ""
        if van_dung_cao_slots:
            for slot in van_dung_cao_slots:
                topic = slot.get("topic_hint", "")
                if topic:
                    try:
                        search_results = await search_similar_problems(
                            query=f"{topic} bài toán vận dụng cao vật lý",
                            subject="physics",
                            num_results=3,
                        )
                        if search_results:
                            refs = "\n".join(
                                f"- {r['title']}: {r['snippet']}" for r in search_results
                            )
                            search_context += f"\n## Bối cảnh mở rộng cho '{topic}':\n{refs}\n"
                    except Exception:
                        pass  # Non-blocking search failure

        user_prompt = f"""Sinh câu hỏi cho các blueprint slots sau:

{blueprint_json}

## Kiến thức nền (chỉ dùng kiến thức từ đây):
{context[:8000]}
{search_context}

## Ràng buộc:
{scope_restriction}

## Topics đã dùng (tránh trùng lặp):
{json.dumps(topics_used[-10:], ensure_ascii=False) if topics_used else "Chưa có câu nào."}

Sinh câu hỏi:"""

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.BUILDER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                role="builder",
                max_tokens=8000,
                temperature=0.7,
            )

            result = json.loads(response)
            questions = result.get("questions", [])

            # G4: Apply skill pipeline to each generated question
            for q in questions:
                # bloom_classifier.run()
                try:
                    bloom_result = await self.bloom_skill.run(
                        question_stem=q.get("stem", ""),
                        question_type=q.get("type", "mcq"),
                    )
                    q["bloom_classified"] = bloom_result.get("bloom_level")
                except Exception:
                    pass

                # difficulty_estimator.run()
                try:
                    diff_result = await self.difficulty_skill.run(
                        question_stem=q.get("stem", ""),
                        bloom_level=q.get("bloom_level", "thong_hieu"),
                    )
                    q["difficulty_score"] = diff_result.get("difficulty_score", 0.5)
                except Exception:
                    pass

                # dedup_checker.run()
                try:
                    dedup_result = await self.dedup_skill.run(
                        new_question_topic=q.get("stem", ""),
                        existing_topics=topics_used,
                    )
                    if dedup_result.get("is_duplicate"):
                        q["dedup_warning"] = dedup_result.get("suggestion")
                except Exception:
                    pass

                # latex_renderer.run() for formula content
                if q.get("latex_content"):
                    try:
                        latex_result = self.latex_skill.run(raw_formula=q["latex_content"])
                        q["latex_rendered"] = latex_result
                    except Exception:
                        pass

            return questions, warnings

        except json.JSONDecodeError as e:
            warnings.append(f"Failed to parse questions JSON: {e}")
            return [], warnings

        except Exception as e:
            warnings.append(f"LLM call failed: {str(e)}")
            return [], warnings

    def _build_context_for_llm(self, retrieved_context: list[dict]) -> str:
        """Build a context string for the LLM prompt."""
        parts = []

        # Group by chapter
        by_chapter: dict[str, list[str]] = {}
        for chunk in retrieved_context:
            chapter = chunk.get("chapter", "Unknown")
            if chapter not in by_chapter:
                by_chapter[chapter] = []
            content = chunk.get("content", "")
            latex = chunk.get("latex_repr")
            if latex:
                content = f"{content}\n[Formula: {latex}]"
            by_chapter[chapter].append(content)

        for chapter, contents in by_chapter.items():
            parts.append(f"### {chapter}")
            for c in contents[:5]:  # Max 5 excerpts per chapter
                parts.append(f"- {c[:500]}")
            parts.append("")

        return "\n".join(parts)
