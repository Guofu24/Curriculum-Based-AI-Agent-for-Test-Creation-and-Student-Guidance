"""
Blueprint planning and chunk-assignment utilities.

This module is intentionally deterministic and auditable:
- normalize the request into an ExamSpec
- create BlueprintCells before any question generation
- build QuestionSlots from cells with explicit over-generation
- attach retrieved evidence bundles to each slot
"""
import math
import logging
from collections import defaultdict

from agents.retrieval import rank_supporting_chunks
from agents.state import (
    BlueprintCell,
    ChunkAssignment,
    ExamBlueprint,
    ExamSpec,
    QuestionSlot,
    RetrievedContext,
    ScopeUnit,
)

logger = logging.getLogger(__name__)

DIFFICULTY_TO_BLOOM = {
    "easy": ["remember", "understand"],
    "medium": ["apply", "analyze"],
    "hard": ["evaluate", "create"],
}

BLOOM_DIFFICULTY_SCORE = {
    "remember": 0.15,
    "understand": 0.25,
    "apply": 0.45,
    "analyze": 0.60,
    "evaluate": 0.80,
    "create": 0.95,
}

OVERGENERATION_FACTOR = 1.3
MAX_SUPPORTING_CHUNKS = 2


class BlueprintAgent:
    """Builds an exam spec + blueprint matrix before generation."""

    def __init__(self, llm=None):
        self.llm = llm

    async def create_blueprint(
        self,
        prompt: str,
        exam_type: str,
        difficulty: str,
        chapters: list[int],
        question_distribution: dict,
        gradually_increasing: bool,
        constraints: dict,
        textbook_metadata: dict,
        scope: list[dict] | None = None,
        time_limit_minutes: int | None = None,
        output_language: str = "vi",
        instructions: str = "",
        bloom_distribution: dict | None = None,
        formatting_preferences: dict | None = None,
        strict_scope: bool | None = None,
    ) -> tuple[ExamBlueprint, dict]:
        scope_units = self._build_scope_units(
            scope=scope or [],
            chapters=chapters or [],
            textbook_metadata=textbook_metadata or {},
        )
        question_mix = self._build_question_mix(question_distribution)
        total_questions = sum(question_mix.values())
        effective_strict_scope = (
            constraints.get("strict_scope", True)
            if strict_scope is None
            else bool(strict_scope)
        )
        normalized_bloom = self._normalize_bloom_distribution(
            question_distribution=question_distribution,
            explicit_distribution=bloom_distribution or {},
            total_questions=total_questions,
            allowed_blooms=constraints.get("bloom_levels", list(BLOOM_DIFFICULTY_SCORE)),
        )

        exam_spec = ExamSpec(
            exam_type=exam_type,
            total_questions=total_questions,
            time_limit_minutes=time_limit_minutes,
            output_language=output_language or "vi",
            instructions=instructions.strip(),
            strict_scope_flag=effective_strict_scope,
            selected_scope=scope_units,
            bloom_distribution=normalized_bloom,
            question_mix=question_mix,
            formatting_preferences=formatting_preferences or {},
            source_prompt=(prompt or "").strip(),
        )

        blueprint_cells = self._build_blueprint_cells(
            exam_spec=exam_spec,
            question_distribution=question_distribution,
        )
        slots = self._build_slots(blueprint_cells)

        if gradually_increasing:
            slots.sort(key=lambda slot: slot.difficulty_score)
            for index, slot in enumerate(slots, start=1):
                slot.slot_number = index

        difficulty_dist = self._count_by_bucket(slots)
        bloom_dist = defaultdict(int)
        original_quota = {}
        for cell in blueprint_cells:
            bloom_dist[cell.bloom_level] += cell.overgenerate_count
            original_quota[cell.cell_id] = cell.target_count

        title = f"Exam - {textbook_metadata.get('title', 'Untitled')}"
        blueprint = ExamBlueprint(
            title=title,
            exam_spec=exam_spec,
            total_questions=len(slots),
            cells=blueprint_cells,
            slots=slots,
            difficulty_distribution=difficulty_dist,
            bloom_distribution=dict(bloom_dist),
        )

        logger.info(
            "Blueprint created: %s scope units, %s cells, %s slots, strict_scope=%s",
            len(scope_units),
            len(blueprint_cells),
            len(slots),
            exam_spec.strict_scope_flag,
        )
        return blueprint, original_quota

    def _build_scope_units(
        self,
        scope: list[dict],
        chapters: list[int],
        textbook_metadata: dict,
    ) -> list[ScopeUnit]:
        if scope:
            scope_units = []
            for item in scope:
                chapter_number = int(item.get("chapter_number") or 0)
                scope_id = item.get("scope_id") or self._scope_id_from_item(item, chapter_number)
                title = item.get("title") or (
                    f"Chapter {chapter_number}" if chapter_number > 0 else "Textbook"
                )
                tags = list(item.get("tags") or [])
                if chapter_number > 0 and f"chapter:{chapter_number}" not in tags:
                    tags.append(f"chapter:{chapter_number}")
                scope_units.append(
                    ScopeUnit(
                        scope_id=scope_id,
                        scope_type=item.get("scope_type", "chapter"),
                        title=title,
                        chapter_number=chapter_number,
                        page_from=item.get("page_from"),
                        page_to=item.get("page_to"),
                        tags=tags,
                    )
                )
            return scope_units

        if chapters:
            return [
                ScopeUnit(
                    scope_id=f"chapter:{chapter}",
                    scope_type="chapter",
                    title=f"Chapter {chapter}",
                    chapter_number=int(chapter),
                    tags=[f"chapter:{int(chapter)}"],
                )
                for chapter in chapters
            ]

        chapter_rows = textbook_metadata.get("chapters") or []
        if chapter_rows:
            return [
                ScopeUnit(
                    scope_id=f"chapter:{int(ch['chapter_number'])}",
                    scope_type="chapter",
                    title=ch.get("title") or f"Chapter {int(ch['chapter_number'])}",
                    chapter_number=int(ch["chapter_number"]),
                    page_from=ch.get("start_page"),
                    page_to=ch.get("end_page"),
                    tags=[f"chapter:{int(ch['chapter_number'])}"],
                )
                for ch in chapter_rows
            ]

        return [
            ScopeUnit(
                scope_id="textbook:all",
                scope_type="course",
                title=textbook_metadata.get("title", "Textbook"),
                tags=["textbook:all"],
            )
        ]

    def _scope_id_from_item(self, item: dict, chapter_number: int) -> str:
        scope_type = item.get("scope_type", "chapter")
        if chapter_number > 0:
            return f"{scope_type}:{chapter_number}"
        title = (item.get("title") or scope_type).strip().lower().replace(" ", "-")
        return f"{scope_type}:{title}"

    def _build_question_mix(self, question_distribution: dict) -> dict[str, int]:
        mix = {}
        for question_type in ("mcq", "essay"):
            dist = question_distribution.get(question_type, {}) or {}
            mix[question_type] = int(dist.get("easy", 0)) + int(dist.get("medium", 0)) + int(dist.get("hard", 0))
        return mix

    def _normalize_bloom_distribution(
        self,
        question_distribution: dict,
        explicit_distribution: dict,
        total_questions: int,
        allowed_blooms: list[str],
    ) -> dict[str, int]:
        if explicit_distribution:
            normalized = {
                bloom: int(count)
                for bloom, count in explicit_distribution.items()
                if bloom in BLOOM_DIFFICULTY_SCORE and int(count) > 0
            }
            if sum(normalized.values()) == total_questions:
                return normalized

        allowed = [bloom for bloom in allowed_blooms if bloom in BLOOM_DIFFICULTY_SCORE]
        if not allowed:
            allowed = list(BLOOM_DIFFICULTY_SCORE)

        bloom_counts = defaultdict(int)
        for question_type in ("mcq", "essay"):
            dist = question_distribution.get(question_type, {}) or {}
            for difficulty_bucket, blooms in DIFFICULTY_TO_BLOOM.items():
                count = int(dist.get(difficulty_bucket, 0))
                active_blooms = [bloom for bloom in blooms if bloom in allowed] or list(blooms)
                for offset in range(count):
                    bloom_counts[active_blooms[offset % len(active_blooms)]] += 1

        return dict(bloom_counts)

    def _build_blueprint_cells(
        self,
        exam_spec: ExamSpec,
        question_distribution: dict,
    ) -> list[BlueprintCell]:
        if not exam_spec.selected_scope:
            return []

        cells: list[BlueprintCell] = []
        priority = 1

        for question_type in ("mcq", "essay"):
            difficulty_dist = question_distribution.get(question_type, {}) or {}
            for difficulty_bucket in ("easy", "medium", "hard"):
                requested = int(difficulty_dist.get(difficulty_bucket, 0))
                if requested <= 0:
                    continue

                bloom_targets = self._split_count_evenly(
                    requested,
                    DIFFICULTY_TO_BLOOM[difficulty_bucket],
                )
                for bloom_level, bloom_count in bloom_targets.items():
                    scope_targets = self._split_count_evenly_for_sequence(
                        bloom_count,
                        exam_spec.selected_scope,
                    )
                    for scope_unit, target_count in scope_targets:
                        if target_count <= 0:
                            continue
                        cell_id = f"{scope_unit.scope_id}|{question_type}|{bloom_level}"
                        cells.append(
                            BlueprintCell(
                                cell_id=cell_id,
                                scope_unit=scope_unit,
                                question_type=question_type,
                                bloom_level=bloom_level,
                                target_count=target_count,
                                priority=priority,
                                overgenerate_count=max(
                                    target_count,
                                    math.ceil(target_count * OVERGENERATION_FACTOR),
                                ),
                            )
                        )
                        priority += 1

        return cells

    def _split_count_evenly(self, total: int, buckets: list | tuple) -> dict:
        if total <= 0 or not buckets:
            return {}
        base = total // len(buckets)
        remainder = total % len(buckets)
        results = {}
        for index, bucket in enumerate(buckets):
            results[bucket] = base + (1 if index < remainder else 0)
        return results

    def _split_count_evenly_for_sequence(self, total: int, buckets: list | tuple) -> list[tuple]:
        if total <= 0 or not buckets:
            return []
        base = total // len(buckets)
        remainder = total % len(buckets)
        results: list[tuple] = []
        for index, bucket in enumerate(buckets):
            results.append((bucket, base + (1 if index < remainder else 0)))
        return results

    def _build_slots(self, cells: list[BlueprintCell]) -> list[QuestionSlot]:
        slots: list[QuestionSlot] = []
        slot_number = 1
        for cell in cells:
            for _ in range(cell.overgenerate_count):
                scope_tags = list(cell.scope_unit.tags)
                if cell.scope_unit.chapter_number > 0:
                    chapter_tag = f"chapter:{cell.scope_unit.chapter_number}"
                    if chapter_tag not in scope_tags:
                        scope_tags.append(chapter_tag)
                slots.append(
                    QuestionSlot(
                        slot_number=slot_number,
                        blueprint_cell_key=cell.cell_id,
                        question_type=cell.question_type,
                        bloom_level=cell.bloom_level,
                        difficulty_score=BLOOM_DIFFICULTY_SCORE.get(cell.bloom_level, 0.5),
                        target_chapter=cell.scope_unit.chapter_number,
                        target_topics=[cell.scope_unit.title],
                        scope_tags=scope_tags,
                        chunk_mode=self._choose_chunk_mode(
                            bloom_level=cell.bloom_level,
                            question_type=cell.question_type,
                        ),
                        preferred_query=self._build_slot_query(cell),
                    )
                )
                slot_number += 1
        return slots

    def _choose_chunk_mode(self, bloom_level: str, question_type: str) -> str:
        if question_type == "essay":
            return "multi"
        if bloom_level in {"apply", "analyze", "evaluate", "create"}:
            return "multi"
        return "single"

    def _build_slot_query(self, cell: BlueprintCell) -> str:
        parts = [cell.scope_unit.title, cell.question_type, cell.bloom_level]
        if cell.scope_unit.chapter_number > 0:
            parts.append(f"chapter {cell.scope_unit.chapter_number}")
        return " ".join(part for part in parts if part).strip()

    def _count_by_bucket(self, slots: list[QuestionSlot]) -> dict[str, int]:
        buckets = defaultdict(int)
        for slot in slots:
            if slot.difficulty_score <= 0.3:
                buckets["easy"] += 1
            elif slot.difficulty_score <= 0.6:
                buckets["medium"] += 1
            else:
                buckets["hard"] += 1
        return dict(buckets)


async def assign_chunks_to_slots(
    blueprint: ExamBlueprint,
    retrieved_contexts: list[RetrievedContext],
) -> list[ChunkAssignment]:
    """Convert retrieved contexts into chunk assignments for generation."""

    contexts_by_slot = {context.slot_number: context for context in retrieved_contexts}
    assignments: list[ChunkAssignment] = []

    for slot in blueprint.slots:
        context = contexts_by_slot.get(slot.slot_number)
        if not context or not context.chunks:
            logger.warning("No retrieved context for slot %s", slot.slot_number)
            continue

        normalized_chunks = [_normalize_retrieved_chunk(chunk) for chunk in context.chunks]
        primary = normalized_chunks[0]
        supporting = _select_supporting_chunks(
            slot=slot,
            primary=primary,
            chunk_list=normalized_chunks,
            max_extra=MAX_SUPPORTING_CHUNKS,
        )
        bundle_score = _compute_bundle_score(primary, supporting)
        evidence_roles = {primary["chunk_id"]: "primary"}
        for support in supporting:
            evidence_roles[support["chunk_id"]] = support.get("role", "support")

        assignment_payload = {
            "difficulty": _score_to_difficulty(slot.difficulty_score),
            "bloom_level": slot.bloom_level,
            "question_type": slot.question_type,
            "slot_number": slot.slot_number,
            "blueprint_cell_key": slot.blueprint_cell_key,
            "scope_tags": list(slot.scope_tags),
        }
        assignments.append(
            ChunkAssignment(
                chunk_id=primary["chunk_id"],
                chunk_text=primary["content"],
                chapter=int(primary.get("chapter_number") or slot.target_chapter or 0),
                assignments=[assignment_payload],
                context_chunks=supporting,
                chunk_mode=slot.chunk_mode,
                bundle_strategy="single" if slot.chunk_mode == "single" else "semantic_multi",
                supporting_chunks=supporting,
                bundle_score=bundle_score,
                assignment_reason=(
                    "hybrid retrieval bundle"
                    if supporting
                    else "hybrid retrieval primary chunk"
                ),
                evidence_roles=evidence_roles,
                estimated_context_tokens=_estimate_bundle_tokens(primary, supporting),
                bundle_validation_report={
                    "valid": True,
                    "support_count": len(supporting),
                    "query": context.query,
                },
            )
        )

    logger.info("Built %s chunk assignments from retrieved contexts", len(assignments))
    return assignments


def _normalize_retrieved_chunk(chunk: dict) -> dict:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    chapter_number = metadata.get("chapter_number")
    if isinstance(chapter_number, str) and chapter_number.isdigit():
        chapter_number = int(chapter_number)
    elif not isinstance(chapter_number, int):
        chapter_number = 0

    return {
        "chunk_id": chunk.get("id") or metadata.get("chunk_id") or "",
        "content": chunk.get("text", ""),
        "chapter": metadata.get("chapter") or "",
        "chapter_number": chapter_number,
        "parent_heading": metadata.get("parent_heading") or "",
        "page": metadata.get("page"),
        "score": chunk.get("score", 0.0),
        "metadata": metadata,
    }


def _select_supporting_chunks(
    slot: QuestionSlot,
    primary: dict,
    chunk_list: list[dict],
    max_extra: int,
) -> list[dict]:
    if slot.chunk_mode == "single" or len(chunk_list) <= 1:
        return []

    primary_idx = next(
        (index for index, chunk in enumerate(chunk_list) if chunk["chunk_id"] == primary["chunk_id"]),
        0,
    )
    ranked = rank_supporting_chunks(
        primary_chunk=primary,
        chunk_list=chunk_list,
        strategy="semantic_multi" if slot.bloom_level in {"evaluate", "create"} else "local_multi",
        primary_idx=primary_idx,
        max_extra=max_extra,
        enforce_diversity=True,
    )
    results = []
    for item in ranked:
        candidate = item["chunk"]
        results.append(
            {
                "chunk_id": candidate["chunk_id"],
                "chunk_text": candidate["content"],
                "parent_heading": candidate.get("parent_heading"),
                "chapter_number": candidate.get("chapter_number"),
                "page": candidate.get("page"),
                "relatedness_score": item["score"],
                "relatedness_features": item["features"],
                "role": "support",
            }
        )
    return results


def _compute_bundle_score(primary: dict, supporting: list[dict]) -> float:
    if not supporting:
        return 1.0
    total = 0.0
    for chunk in supporting:
        total += float(chunk.get("relatedness_score", 0.0) or 0.0)
    return round(min(1.0, max(0.25, total / len(supporting))), 3)


def _estimate_bundle_tokens(primary: dict, supporting: list[dict]) -> int:
    total_chars = len(primary.get("content", ""))
    total_chars += sum(len(chunk.get("chunk_text", "")) for chunk in supporting)
    return max(1, math.ceil(total_chars / 4))


def _score_to_difficulty(score: float) -> str:
    if score <= 0.3:
        return "easy"
    if score <= 0.6:
        return "medium"
    return "hard"
