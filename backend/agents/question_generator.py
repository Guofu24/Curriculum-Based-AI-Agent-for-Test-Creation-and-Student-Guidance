"""
Question generator for the active MVP runtime.

Scope:
- Physics PDFs only
- Vietnamese output
- MCQ single-answer only
- Strict grounding against retrieved chunks
- Regenerate through the same scoped evidence path
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import ChunkAssignment, GeneratedQuestion, QuestionSlot, RetrievedContext
from config import settings
from utils.bloom_levels import normalize_bloom_level

logger = logging.getLogger(__name__)
DEFAULT_OPTION_LABELS = ["A", "B", "C", "D"]


MCQ_SYSTEM_PROMPT = """You write Vietnamese Physics multiple-choice questions.

Hard rules:
1. Use only the provided source text.
2. Do not add outside knowledge.
3. Return valid JSON only.
4. Each question must have exactly 4 options labeled A, B, C, D.
5. There must be exactly one correct answer.
6. The explanation must point back to the source material.

Return JSON:
{
  "content": "...",
  "options": [
    {"label": "A", "text": "..."},
    {"label": "B", "text": "..."},
    {"label": "C", "text": "..."},
    {"label": "D", "text": "..."}
  ],
  "correct_answer": "A",
  "explanation": "..."
}"""


MICRO_PROMPT_SYSTEM = """Ban la chuyen gia ra de thi Vat ly bang tieng Viet.

Chi tao cau hoi MCQ 4 lua chon, 1 dap an dung, dua duy nhat vao doan van ban duoc cung cap.
Moi item trong JSON array phai co:
- question_type = "mcq"
- difficulty = "easy" | "medium" | "hard"
- bloom_level
- content
- options
- correct_answer
- explanation

Chi tra ve JSON array, khong them van ban khac."""


MULTI_CHUNK_SYSTEM_PROMPT = """Ban la chuyen gia ra de thi Vat ly bang tieng Viet.

Ban nhan nhieu doan van ban va phai tao cau hoi MCQ tong hop thong tin tu cac doan do.
Chi dung thong tin co trong cac doan van ban duoc cung cap.
Moi item trong JSON array phai co:
- question_type = "mcq"
- difficulty = "medium" | "hard"
- bloom_level
- content
- options
- correct_answer
- explanation

Chi tra ve JSON array, khong them van ban khac."""


APPLIED_QUESTION_PROMPT = """Additionally, this is an APPLIED question. Create a realistic scenario
that still relies only on the provided source text."""


@dataclass
class BundleContext:
    primary_chunk_id: str
    primary_chunk_text: str
    bundle_strategy: str
    chunk_mode: str
    supporting_chunks: list[dict] = field(default_factory=list)
    source_chunk_ids: list[str] = field(default_factory=list)
    evidence_roles: dict[str, str] = field(default_factory=dict)
    bundle_score: float = 0.0
    assignment_reason: str = ""


class QuestionGeneratorAgent:
    """MCQ-only generator for the active MVP path."""

    def __init__(self, llm):
        self.llm = llm

    def _playbook_instruction(self, constraints: dict) -> str:
        lines = [
            str(item).strip()
            for item in (constraints.get("_playbook_lines") or [])
            if str(item).strip()
        ]
        if not lines:
            return ""
        formatted_lines = "\n".join(f"- {line}" for line in lines)
        return (
            "\n\nPLAYBOOK GUIDANCE:\n"
            "Apply these internal operating bullets only if they are compatible with the provided source text.\n"
            f"{formatted_lines}"
        )

    def _normalize_bundle_context(self, chunk_assignment: ChunkAssignment) -> BundleContext:
        primary = getattr(chunk_assignment, "primary_chunk", None) or {
            "chunk_id": chunk_assignment.chunk_id,
            "chunk_text": chunk_assignment.chunk_text,
        }
        primary_chunk_id = primary.get("chunk_id", chunk_assignment.chunk_id)
        primary_chunk_text = primary.get("chunk_text", chunk_assignment.chunk_text)

        supporting_chunks = list(chunk_assignment.get_supporting_chunks())
        evidence_roles = dict(getattr(chunk_assignment, "evidence_roles", {}) or {})
        if primary_chunk_id:
            evidence_roles.setdefault(primary_chunk_id, "primary")

        explicit_source_chunks = list(getattr(chunk_assignment, "source_chunks", []) or [])
        if explicit_source_chunks:
            source_chunk_ids = explicit_source_chunks
        else:
            source_chunk_ids = [primary_chunk_id] if primary_chunk_id else []
            for chunk in supporting_chunks:
                chunk_id = chunk.get("chunk_id")
                if chunk_id and chunk_id not in source_chunk_ids:
                    source_chunk_ids.append(chunk_id)

        return BundleContext(
            primary_chunk_id=primary_chunk_id,
            primary_chunk_text=primary_chunk_text,
            bundle_strategy=getattr(chunk_assignment, "bundle_strategy", "single") or "single",
            chunk_mode=getattr(chunk_assignment, "chunk_mode", "single") or "single",
            supporting_chunks=supporting_chunks,
            source_chunk_ids=source_chunk_ids,
            evidence_roles=evidence_roles,
            bundle_score=getattr(chunk_assignment, "bundle_score", 0.0) or 0.0,
            assignment_reason=getattr(chunk_assignment, "assignment_reason", "") or "",
        )

    def _format_bundle_segments(
        self,
        bundle: BundleContext,
        max_chars: int,
    ) -> tuple[list[str], list[str], list[str]]:
        segments: list[str] = []
        all_chunk_ids: list[str] = []
        all_chunk_texts: list[str] = []

        primary_text = bundle.primary_chunk_text[:max_chars]
        segments.append(f"=== PRIMARY CHUNK ===\n\n{primary_text}")
        all_chunk_ids.append(bundle.primary_chunk_id)
        all_chunk_texts.append(bundle.primary_chunk_text[:500])

        for index, extra in enumerate(bundle.supporting_chunks, start=1):
            extra_text = (extra.get("chunk_text", "") or "")[:max_chars]
            chunk_id = extra.get("chunk_id", f"support-{index}")
            role = bundle.evidence_roles.get(chunk_id, extra.get("role", "support"))
            segments.append(f"=== SUPPORT {index} ({role}) ===\n\n{extra_text}")
            if chunk_id not in all_chunk_ids:
                all_chunk_ids.append(chunk_id)
                all_chunk_texts.append((extra.get("chunk_text", "") or "")[:500])

        return segments, all_chunk_ids, all_chunk_texts

    def _build_single_source_evidence(self, chunk_assignment: ChunkAssignment) -> list[dict]:
        return [
            {
                "chunk_id": chunk_assignment.chunk_id,
                "chapter_number": chunk_assignment.chapter,
                "role": "primary",
                "text_preview": chunk_assignment.chunk_text[:500],
            }
        ]

    def _build_bundle_source_evidence(self, bundle: BundleContext) -> list[dict]:
        evidence = [
            {
                "chunk_id": bundle.primary_chunk_id,
                "role": "primary",
                "text_preview": bundle.primary_chunk_text[:500],
            }
        ]
        for chunk in bundle.supporting_chunks:
            evidence.append(
                {
                    "chunk_id": chunk.get("chunk_id", ""),
                    "chapter_number": chunk.get("chapter_number"),
                    "page": chunk.get("page"),
                    "parent_heading": chunk.get("parent_heading"),
                    "role": bundle.evidence_roles.get(
                        chunk.get("chunk_id", ""),
                        chunk.get("role", "support"),
                    ),
                    "score": chunk.get("relatedness_score"),
                    "text_preview": (chunk.get("chunk_text", "") or "")[:500],
                }
            )
        return evidence

    def _build_context_source_evidence(self, context: RetrievedContext) -> list[dict]:
        evidence: list[dict] = []
        for chunk in context.chunks:
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            evidence.append(
                {
                    "chunk_id": chunk.get("id", ""),
                    "chapter_number": metadata.get("chapter_number"),
                    "page": metadata.get("page"),
                    "parent_heading": metadata.get("parent_heading"),
                    "role": "primary",
                    "score": chunk.get("score"),
                    "text_preview": (chunk.get("text", "") or "")[:500],
                }
            )
        return evidence

    def _normalize_rubric(self, question_type: str, payload: dict) -> dict | None:
        _ = question_type
        rubric = payload.get("rubric")
        return rubric if isinstance(rubric, dict) else None

    def _normalize_options(self, raw_options) -> list[dict] | None:
        if raw_options is None:
            return None

        if isinstance(raw_options, dict):
            normalized_from_dict: list[dict] = []
            for label in DEFAULT_OPTION_LABELS:
                value = raw_options.get(label)
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    normalized_from_dict.append({"label": label, "text": text})
            raw_options = normalized_from_dict

        if not isinstance(raw_options, list):
            return None

        normalized: list[dict] = []
        for index, item in enumerate(raw_options[:4]):
            fallback_label = DEFAULT_OPTION_LABELS[index]
            option = self._normalize_single_option(item, fallback_label)
            if option is not None:
                normalized.append(option)

        if len(normalized) != 4:
            return normalized or None

        relabeled: list[dict] = []
        for index, option in enumerate(normalized):
            relabeled.append(
                {
                    "label": DEFAULT_OPTION_LABELS[index],
                    "text": str(option.get("text", "")).strip(),
                }
            )
        return relabeled

    def _normalize_single_option(self, raw_option, fallback_label: str) -> dict | None:
        if isinstance(raw_option, dict):
            label = str(raw_option.get("label") or fallback_label).strip().upper()
            text = str(raw_option.get("text") or "").strip()
            if not text:
                return None
            if label not in DEFAULT_OPTION_LABELS:
                label = fallback_label
            return {"label": label, "text": text}

        if raw_option is None:
            return None

        text = str(raw_option).strip()
        if not text:
            return None

        prefixed = re.match(r"^\s*([A-D])[\)\.\:\-]\s*(.+)$", text, re.IGNORECASE)
        if prefixed:
            return {
                "label": prefixed.group(1).upper(),
                "text": prefixed.group(2).strip(),
            }

        return {"label": fallback_label, "text": text}

    def _normalize_correct_answer(self, raw_answer, options: list[dict] | None) -> str:
        text = str(raw_answer or "").strip()
        if not text:
            return ""

        answer_label_match = re.match(r"^\s*([A-D])(?:[\)\.\:\-].*)?$", text, re.IGNORECASE)
        if answer_label_match:
            return answer_label_match.group(1).upper()

        normalized_options = [item for item in (options or []) if isinstance(item, dict)]
        answer_text = re.sub(r"^\s*([A-D])[\)\.\:\-]\s*", "", text, flags=re.IGNORECASE).strip().lower()
        for option in normalized_options:
            option_label = str(option.get("label") or "").strip().upper()
            option_text = str(option.get("text") or "").strip().lower()
            if answer_text and answer_text == option_text:
                return option_label

        return text.upper()

    def _normalize_payload_bloom_level(self, raw_level, fallback_level: str) -> str:
        return normalize_bloom_level(raw_level, fallback=fallback_level)

    def _assert_mcq_only_assignments(self, assignments: list[dict]) -> None:
        for assignment in assignments:
            question_type = str(assignment.get("question_type") or "").strip().lower()
            if question_type != "mcq":
                raise ValueError("Active MVP runtime only supports MCQ generation assignments")

    def _build_bundle_user_message(
        self,
        assignments: list[dict],
        bundle: BundleContext,
        combined_text: str,
    ) -> str:
        self._assert_mcq_only_assignments(assignments)
        task_descriptions = []
        for assignment in assignments:
            difficulty = assignment["difficulty"]
            if difficulty == "medium":
                bloom_desc = "tong hop, so sanh, hoac lien ket thong tin"
            else:
                bloom_desc = "phan tich sau, danh gia, hoac ket hop nhieu y"
            task_descriptions.append(
                f"- 1 cau hoi MCQ 4 lua chon, do kho {difficulty.upper()} ({bloom_desc})"
            )

        source_summary = ", ".join(bundle.source_chunk_ids)
        task_list = "\n".join(task_descriptions)
        return (
            f"Hay tao chinh xac {len(assignments)} cau hoi MCQ tong hop.\n\n"
            f"Bundle strategy: {bundle.bundle_strategy}\n"
            f"Traceable source chunks: {source_summary}\n"
            f"Assignment reason: {bundle.assignment_reason or 'n/a'}\n\n"
            f"{task_list}\n\n"
            f"{combined_text}\n\n"
            f"Tra ve JSON array dung {len(assignments)} item."
        )

    async def generate_from_single_chunk(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        assignments = chunk_assignment.assignments
        if not assignments:
            return []
        self._assert_mcq_only_assignments(assignments)

        chunk_text = chunk_assignment.chunk_text[: settings.MAX_CHUNK_CHARS]
        task_descriptions = []
        for assignment in assignments:
            difficulty = assignment["difficulty"]
            if difficulty == "easy":
                bloom_desc = "remember/understand"
            elif difficulty == "medium":
                bloom_desc = "apply/analyze"
            else:
                bloom_desc = "evaluate/create"
            task_descriptions.append(
                f"- 1 MCQ 4 lua chon, do kho {difficulty.upper()} ({bloom_desc})"
            )

        user_message = (
            f"Hay tao chinh xac {len(assignments)} cau hoi dua duy nhat vao doan van ban sau.\n\n"
            f"{chr(10).join(task_descriptions)}\n\n"
            f"=== SOURCE TEXT ===\n\n{chunk_text}\n\n=== END SOURCE TEXT ===\n\n"
            f"Tra ve JSON array dung {len(assignments)} item."
        )

        extra = ""
        if constraints.get("strict_grounding", True):
            extra = (
                "\n\nSTRICT GROUNDING: every fact in the question must be directly supported "
                "by the provided source text."
            )
        extra += self._playbook_instruction(constraints)

        messages = [
            SystemMessage(content=MICRO_PROMPT_SYSTEM + extra),
            HumanMessage(content=user_message),
        ]
        questions_data = await self._invoke_with_retry(messages, chunk_assignment.chunk_id)

        generated: list[GeneratedQuestion] = []
        source_evidence = self._build_single_source_evidence(chunk_assignment)
        for index, payload in enumerate(questions_data):
            if index >= len(assignments):
                break
            assignment = assignments[index]
            options = self._normalize_options(payload.get("options"))
            generated.append(
                GeneratedQuestion(
                    slot_number=assignment.get("slot_number", 0),
                    blueprint_cell_key=assignment.get("blueprint_cell_key", ""),
                    question_type="mcq",
                    bloom_level=self._normalize_payload_bloom_level(
                        payload.get("bloom_level"),
                        assignment["bloom_level"],
                    ),
                    difficulty_score=self._difficulty_to_score(
                        payload.get("difficulty", assignment["difficulty"])
                    ),
                    content=payload.get("content", ""),
                    options=options,
                    correct_answer=self._normalize_correct_answer(
                        payload.get("correct_answer", ""),
                        options,
                    ),
                    rubric=self._normalize_rubric("mcq", payload),
                    explanation=payload.get("explanation", ""),
                    source_chunks=[chunk_assignment.chunk_id],
                    source_texts=[chunk_assignment.chunk_text[:500]],
                    source_evidence=list(source_evidence),
                    scope_tags=list(assignment.get("scope_tags") or []),
                )
            )

        logger.debug(
            "Chunk %s generated %s/%s questions",
            chunk_assignment.chunk_id,
            len(generated),
            len(assignments),
        )
        return generated

    async def generate_from_chunk(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        return await self.generate_from_single_chunk(chunk_assignment, constraints)

    async def generate_from_context_bundle(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        assignments = chunk_assignment.assignments
        if not assignments:
            return []
        self._assert_mcq_only_assignments(assignments)

        bundle = self._normalize_bundle_context(chunk_assignment)
        segments, all_chunk_ids, all_chunk_texts = self._format_bundle_segments(
            bundle=bundle,
            max_chars=settings.MAX_CHUNK_CHARS,
        )
        combined_text = "\n\n".join(segments)
        user_message = self._build_bundle_user_message(assignments, bundle, combined_text)

        extra = ""
        if constraints.get("strict_grounding", True):
            extra = (
                "\n\nSTRICT GROUNDING: every fact in the question must be directly supported "
                "by the provided source text."
            )
        extra += self._playbook_instruction(constraints)

        messages = [
            SystemMessage(content=MULTI_CHUNK_SYSTEM_PROMPT + extra),
            HumanMessage(content=user_message),
        ]
        questions_data = await self._invoke_with_retry(messages, chunk_assignment.chunk_id)

        generated: list[GeneratedQuestion] = []
        source_evidence = self._build_bundle_source_evidence(bundle)
        for index, payload in enumerate(questions_data):
            if index >= len(assignments):
                break
            assignment = assignments[index]
            options = self._normalize_options(payload.get("options"))
            generated.append(
                GeneratedQuestion(
                    slot_number=assignment.get("slot_number", 0),
                    blueprint_cell_key=assignment.get("blueprint_cell_key", ""),
                    question_type="mcq",
                    bloom_level=self._normalize_payload_bloom_level(
                        payload.get("bloom_level"),
                        assignment["bloom_level"],
                    ),
                    difficulty_score=self._difficulty_to_score(
                        payload.get("difficulty", assignment["difficulty"])
                    ),
                    content=payload.get("content", ""),
                    options=options,
                    correct_answer=self._normalize_correct_answer(
                        payload.get("correct_answer", ""),
                        options,
                    ),
                    rubric=self._normalize_rubric("mcq", payload),
                    explanation=payload.get("explanation", ""),
                    source_chunks=all_chunk_ids,
                    source_texts=all_chunk_texts,
                    source_evidence=list(source_evidence),
                    scope_tags=list(assignment.get("scope_tags") or []),
                )
            )

        logger.debug(
            "Bundle %s generated %s/%s questions",
            bundle.primary_chunk_id,
            len(generated),
            len(assignments),
        )
        return generated

    async def generate_from_local_bundle(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        return await self.generate_from_context_bundle(chunk_assignment, constraints)

    async def generate_from_semantic_bundle(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        return await self.generate_from_context_bundle(chunk_assignment, constraints)

    async def _invoke_with_retry(
        self,
        messages: list,
        chunk_id: str,
        max_retries: int = 4,
    ) -> list[dict]:
        for attempt in range(max_retries):
            try:
                response = await self.llm.ainvoke(messages)
                return self._parse_array_response(response.content)
            except Exception as exc:
                error_text = str(exc)
                is_rate_limit = "429" in error_text or "rate" in error_text.lower()
                if is_rate_limit and attempt < max_retries - 1:
                    wait_seconds = 8 * (2 ** attempt)
                    logger.warning(
                        "Rate limit for chunk %s, retry %s/%s in %ss",
                        chunk_id,
                        attempt + 1,
                        max_retries,
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)
                    continue
                logger.error(
                    "Question generation failed for chunk %s (attempt %s): %s",
                    chunk_id,
                    attempt + 1,
                    exc,
                )
                return []
        return []

    async def generate_from_chunks_parallel(
        self,
        chunk_assignments: list[ChunkAssignment],
        constraints: dict,
        max_concurrency: int = 1,
    ) -> list[GeneratedQuestion]:
        _ = max_concurrency
        delay = settings.LLM_REQUEST_DELAY
        all_questions: list[GeneratedQuestion] = []

        for index, chunk_assignment in enumerate(chunk_assignments):
            bundle = self._normalize_bundle_context(chunk_assignment)
            supporting_chunks = bundle.supporting_chunks
            mode = bundle.bundle_strategy or ("multi-chunk" if supporting_chunks else "single")
            logger.info(
                "Generating assignment %s/%s (%s, chunk=%s, tasks=%s)",
                index + 1,
                len(chunk_assignments),
                mode,
                chunk_assignment.chunk_id[:16],
                len(chunk_assignment.assignments),
            )

            try:
                if not supporting_chunks or mode == "single":
                    questions = await self.generate_from_single_chunk(chunk_assignment, constraints)
                else:
                    questions = await self.generate_from_context_bundle(chunk_assignment, constraints)
                all_questions.extend(questions)
            except Exception as exc:
                logger.error("Chunk generation error: %s", exc)

            if index < len(chunk_assignments) - 1:
                await asyncio.sleep(delay)

        return all_questions

    async def generate_questions(
        self,
        slots: list[QuestionSlot],
        contexts: list[RetrievedContext],
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        questions: list[GeneratedQuestion] = []
        for slot, context in zip(slots, contexts):
            questions.append(await self._generate_single(slot, context, constraints))
        return questions

    async def _generate_single(
        self,
        slot: QuestionSlot,
        context: RetrievedContext,
        constraints: dict,
    ) -> GeneratedQuestion:
        if slot.question_type != "mcq":
            raise ValueError("Active MVP runtime only supports MCQ generation")

        system_prompt = MCQ_SYSTEM_PROMPT
        if constraints.get("allow_applied_questions") and slot.difficulty_score >= 0.6:
            system_prompt += "\n\n" + APPLIED_QUESTION_PROMPT
        if constraints.get("strict_grounding", True):
            system_prompt += (
                "\n\nSTRICT GROUNDING: use only the provided context and do not add outside knowledge."
            )
        system_prompt += self._playbook_instruction(constraints)

        edit_prompt = (constraints.get("_edit_prompt") or "").strip()
        edit_instruction = ""
        if edit_prompt:
            edit_instruction = (
                "\n\nEdit guidance to preserve while regenerating:\n"
                f"{edit_prompt}\n"
                "Keep the same scope, answerability requirements, and question family."
            )

        user_message = f"""Generate a MCQ question with these specifications:

Chapter: {slot.target_chapter}
Topics: {', '.join(slot.target_topics) if slot.target_topics else 'General'}
Bloom's Level: {slot.bloom_level}
Difficulty: {slot.difficulty_score:.2f}
Question Number: {slot.slot_number}
Scope Tags: {', '.join(getattr(slot, 'scope_tags', []) or [])}

=== TEXTBOOK CONTEXT (use ONLY this information) ===

{context.combined_text}

=== END CONTEXT ===

Generate the question now.{edit_instruction}"""

        response = await self.llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
        )
        question_data = self._parse_response(response.content)
        options = self._normalize_options(question_data.get("options"))

        return GeneratedQuestion(
            slot_number=slot.slot_number,
            blueprint_cell_key=getattr(slot, "blueprint_cell_key", ""),
            question_type="mcq",
            bloom_level=self._normalize_payload_bloom_level(
                question_data.get("bloom_level"),
                slot.bloom_level,
            ),
            difficulty_score=slot.difficulty_score,
            content=question_data.get("content", ""),
            options=options,
            correct_answer=self._normalize_correct_answer(
                question_data.get("correct_answer", ""),
                options,
            ),
            rubric=self._normalize_rubric("mcq", question_data),
            explanation=question_data.get("explanation", ""),
            source_chunks=[chunk["id"] for chunk in context.chunks],
            source_texts=[chunk["text"] for chunk in context.chunks],
            source_evidence=self._build_context_source_evidence(context),
            scope_tags=list(getattr(slot, "scope_tags", []) or []),
        )

    def _parse_response(self, response_text: str) -> dict:
        text = response_text.strip()
        if not text:
            return {}

        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            text = code_block.group(1)
        elif not text.startswith("{"):
            brace_match = re.search(r"\{.*\}", text, re.DOTALL)
            if brace_match:
                text = brace_match.group(0)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("QuestionGen JSON parse failed: %s. Raw: %s", exc, text[:200])
            return {}

    def _parse_array_response(self, response_text: str) -> list[dict]:
        text = response_text.strip()
        if not text:
            return []

        code_block = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if code_block:
            text = code_block.group(1)
        elif not text.startswith("["):
            bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
            if bracket_match:
                text = bracket_match.group(0)
            else:
                brace_match = re.search(r"\{.*\}", text, re.DOTALL)
                if brace_match:
                    text = f"[{brace_match.group(0)}]"

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("MicroPrompt JSON parse failed: %s. Raw: %s", exc, text[:200])
            return []

        if isinstance(parsed, dict):
            return [parsed]
        return parsed if isinstance(parsed, list) else []

    def _difficulty_to_score(self, difficulty: str) -> float:
        return {
            "easy": 0.2,
            "medium": 0.5,
            "hard": 0.85,
        }.get(difficulty, 0.5)

    async def regenerate_single(
        self,
        original_question: GeneratedQuestion,
        context: RetrievedContext,
        constraints: dict,
        edit_prompt: str = "",
    ) -> GeneratedQuestion:
        slot = QuestionSlot(
            slot_number=original_question.slot_number,
            question_type="mcq",
            bloom_level=original_question.bloom_level,
            difficulty_score=original_question.difficulty_score,
            target_chapter=0,
            target_topics=[],
            blueprint_cell_key=original_question.blueprint_cell_key,
            scope_tags=list(original_question.scope_tags or []),
        )
        if edit_prompt:
            constraints = {**constraints, "_edit_prompt": edit_prompt}

        regenerated = await self._generate_single(slot, context, constraints)
        regenerated.is_locked = original_question.is_locked
        return regenerated
