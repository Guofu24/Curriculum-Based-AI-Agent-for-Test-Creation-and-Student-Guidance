"""
Blueprint Agent — Deterministic Quota Allocation

Replaces LLM-based blueprint creation with a pure-Python algorithm that:
1. Maps difficulty levels to Bloom's Taxonomy
2. Distributes question quotas across chapters (proportional to chunk count)
3. Over-generates by ~30% to allow pruning of low-quality results
4. Assigns specific chunks to question slots for micro-prompting

This eliminates one LLM call and ensures predictable, token-efficient behavior.
"""
import math
import random
import logging
import re

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from agents.state import ExamBlueprint, QuestionSlot, ChunkAssignment
from agents.retrieval import rank_supporting_chunks
from models.textbook import TextbookChunk


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Bloom's Taxonomy ↔ Difficulty mapping
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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

OVERGENERATION_FACTOR = 1.3  # Generate 30% more than needed
MAX_SINGLE_PER_CHUNK = 2
MULTI_CHUNK_EXTRA = 2


class BlueprintAgent:
    """Plans the structural blueprint of an exam using deterministic allocation."""

    def __init__(self, llm=None):
        # LLM is no longer needed for blueprint creation, kept for API compat
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
    ) -> ExamBlueprint:
        """
        Create an exam blueprint deterministically (no LLM call).

        Uses Bloom's Taxonomy mapping + proportional chapter distribution
        + 30% over-generation.
        """
        # 1. Compute original quota per difficulty
        mcq_dist = question_distribution.get("mcq", {})
        essay_dist = question_distribution.get("essay", {})

        original_quota = {
            "easy": mcq_dist.get("easy", 0) + essay_dist.get("easy", 0),
            "medium": mcq_dist.get("medium", 0) + essay_dist.get("medium", 0),
            "hard": mcq_dist.get("hard", 0) + essay_dist.get("hard", 0),
        }

        # 2. Over-generate by 30%
        over_quota = {
            diff: math.ceil(count * OVERGENERATION_FACTOR)
            for diff, count in original_quota.items()
        }

        # 3. Get chapter info for distribution
        available_chapters = chapters if chapters else []
        if not available_chapters and textbook_metadata.get("chapters"):
            available_chapters = [
                ch["chapter_number"] for ch in textbook_metadata["chapters"]
            ]

        # 4. Distribute across chapters
        chapter_quotas = self._distribute_across_chapters(
            over_quota, available_chapters, textbook_metadata
        )

        # 5. Build blueprint slots
        slots = self._build_slots(
            chapter_quotas=chapter_quotas,
            exam_type=exam_type,
            mcq_dist=mcq_dist,
            essay_dist=essay_dist,
            constraints=constraints,
            gradually_increasing=gradually_increasing,
        )

        # 6. Sort if gradually increasing
        if gradually_increasing:
            slots.sort(key=lambda s: s.difficulty_score)

        # Re-number slots
        for i, slot in enumerate(slots):
            slot.slot_number = i + 1

        # 7. Compute distributions
        difficulty_dist = {}
        bloom_dist = {}
        for slot in slots:
            if slot.difficulty_score <= 0.3:
                bucket = "easy"
            elif slot.difficulty_score <= 0.6:
                bucket = "medium"
            else:
                bucket = "hard"
            difficulty_dist[bucket] = difficulty_dist.get(bucket, 0) + 1
            bloom_dist[slot.bloom_level] = bloom_dist.get(slot.bloom_level, 0) + 1

        title = f"Exam - {textbook_metadata.get('title', 'Untitled')}"

        blueprint = ExamBlueprint(
            title=title,
            total_questions=len(slots),
            slots=slots,
            difficulty_distribution=difficulty_dist,
            bloom_distribution=bloom_dist,
        )

        logger.info(
            f"Deterministic blueprint created: {len(slots)} slots "
            f"(original={sum(original_quota.values())}, "
            f"over-gen={sum(over_quota.values())}), "
            f"difficulty={difficulty_dist}, bloom={bloom_dist}"
        )

        return blueprint, original_quota

    def _distribute_across_chapters(
        self,
        over_quota: dict,
        chapters: list[int],
        textbook_metadata: dict,
    ) -> dict:
        """
        Distribute question quota across chapters.

        Returns: {chapter_number: {easy: N, medium: N, hard: N}}
        If no chapters, uses chapter=0 for the whole textbook.
        """
        if not chapters:
            return {0: dict(over_quota)}

        num_chapters = len(chapters)

        # Distribute each difficulty level across chapters
        chapter_quotas = {ch: {"easy": 0, "medium": 0, "hard": 0} for ch in chapters}

        for diff, total in over_quota.items():
            if total == 0:
                continue

            # Base allocation: divide evenly
            base = total // num_chapters
            remainder = total % num_chapters

            # Distribute base to each chapter
            for ch in chapters:
                chapter_quotas[ch][diff] = base

            # Distribute remainder round-robin
            shuffled = list(chapters)
            random.shuffle(shuffled)
            for i in range(remainder):
                chapter_quotas[shuffled[i]][diff] += 1

        return chapter_quotas

    def _build_slots(
        self,
        chapter_quotas: dict,
        exam_type: str,
        mcq_dist: dict,
        essay_dist: dict,
        constraints: dict,
        gradually_increasing: bool,
    ) -> list[QuestionSlot]:
        """Build QuestionSlot list from chapter quotas."""

        allowed_blooms = constraints.get(
            "bloom_levels", ["remember", "understand", "apply", "analyze"]
        )
        slots = []
        slot_num = 1

        # Determine question type split
        total_mcq = sum(mcq_dist.values()) if isinstance(mcq_dist, dict) else 0
        total_essay = sum(essay_dist.values()) if isinstance(essay_dist, dict) else 0
        total = total_mcq + total_essay

        for chapter, quotas in chapter_quotas.items():
            for diff_level, count in quotas.items():
                for _ in range(count):
                    # Pick bloom level
                    bloom_pool = [
                        b for b in DIFFICULTY_TO_BLOOM[diff_level]
                        if b in allowed_blooms
                    ]
                    if not bloom_pool:
                        bloom_pool = DIFFICULTY_TO_BLOOM[diff_level]
                    bloom = random.choice(bloom_pool)

                    # Determine question type
                    if exam_type == "mcq":
                        q_type = "mcq"
                    elif exam_type == "essay":
                        q_type = "essay"
                    else:
                        # Mixed: proportional
                        if total > 0:
                            q_type = "mcq" if random.random() < (total_mcq / total) else "essay"
                        else:
                            q_type = "mcq"

                    # Determine chunk mode using a soft heuristic rather than a rigid rule.
                    chunk_mode = _choose_chunk_mode(
                        diff_level=diff_level,
                        bloom_level=bloom,
                        question_type=q_type,
                        constraints=constraints,
                    )

                    slots.append(QuestionSlot(
                        slot_number=slot_num,
                        question_type=q_type,
                        bloom_level=bloom,
                        difficulty_score=BLOOM_DIFFICULTY_SCORE.get(bloom, 0.5),
                        target_chapter=chapter,
                        target_topics=[],
                        chunk_mode=chunk_mode,
                    ))
                    slot_num += 1

        return slots


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Chunk Assignment — map chunks to question generation tasks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def assign_chunks_to_slots(
    blueprint: ExamBlueprint,
    textbook_id: str,
    db_session: AsyncSession,
) -> list[ChunkAssignment]:
    """
    For each chapter in the blueprint, select chunks from the DB and create
    ChunkAssignment objects for question generation.

    Chunk mode handling (Phase 3):
    - **single** (easy): 1 chunk → 1-2 question tasks  (same as before)
    - **multi** (medium/hard): 1 primary chunk + 1-2 adjacent chunks →
      1 synthesis question per bundle.  Gives the LLM cross-chunk context
      so it can write questions that require combining information.

    Returns: list of ChunkAssignment objects ready for sequential LLM calls.
    """
    # Group slots by chapter
    chapter_slots: dict[int, list[QuestionSlot]] = {}
    for slot in blueprint.slots:
        ch = slot.target_chapter
        chapter_slots.setdefault(ch, []).append(slot)

    assignments: list[ChunkAssignment] = []

    for chapter, slots in chapter_slots.items():
        # Query chunks for this chapter from PostgreSQL
        chunks = await _get_chapter_chunks(textbook_id, chapter, db_session)

        if not chunks:
            logger.warning(
                f"No chunks found for chapter {chapter}, textbook {textbook_id}. "
                f"Skipping {len(slots)} slots."
            )
            continue

        # Split slots by chunk_mode
        single_slots = [s for s in slots if s.chunk_mode == "single"]
        multi_slots = [s for s in slots if s.chunk_mode == "multi"]

        # ── Single-chunk assignments (easy) ─────────────────────────
        if single_slots:
            single_assignments = _assign_single_chunk_slots(
                single_slots, chunks, chapter,
            )
            assignments.extend(single_assignments)

        # ── Multi-chunk bundle assignments (medium/hard) ────────────
        if multi_slots:
            multi_assignments = _assign_multi_chunk_slots(
                multi_slots, chunks, chapter,
            )
            assignments.extend(multi_assignments)

    total_tasks = sum(len(a.assignments) for a in assignments)
    multi_count = sum(1 for a in assignments if a.context_chunks)
    logger.info(
        f"Chunk assignment complete: {len(assignments)} assignments "
        f"({multi_count} multi-chunk bundles), "
        f"total question tasks: {total_tasks}"
    )

    return assignments


def _assign_single_chunk_slots(
    slots: list[QuestionSlot],
    chunks: list[dict],
    chapter: int,
) -> list[ChunkAssignment]:
    """Assign single-chunk slots with light diversity and reuse control.

    Keeps the old single-chunk behavior, but prefers chunks that:
    - have lower reuse count
    - have not already been used for the same question signature
    - belong to less-used topic signatures
    """
    shuffled = list(chunks)
    random.shuffle(shuffled)

    chunk_assignment_map: dict[str, ChunkAssignment] = {}
    chunk_tag_map: dict[str, set[tuple[str, str, str]]] = {}
    concept_usage: dict[str, int] = {}

    for slot in slots:
        desired_tag = (
            _score_to_difficulty(slot.difficulty_score),
            slot.bloom_level,
            slot.question_type,
        )
        selected_chunk, selected_assignment = _pick_single_chunk_assignment(
            slot=slot,
            desired_tag=desired_tag,
            shuffled_chunks=shuffled,
            chapter=chapter,
            chunk_assignment_map=chunk_assignment_map,
            chunk_tag_map=chunk_tag_map,
            concept_usage=concept_usage,
        )

        selected_assignment.assignments.append({
            "difficulty": _score_to_difficulty(slot.difficulty_score),
            "bloom_level": slot.bloom_level,
            "question_type": slot.question_type,
            "slot_number": slot.slot_number,
        })
        chunk_tag_map.setdefault(selected_chunk["chunk_id"], set()).add(desired_tag)
        concept_key = _chunk_topic_signature(selected_chunk)
        concept_usage[concept_key] = concept_usage.get(concept_key, 0) + 1
        selected_assignment.reuse_count = max(0, len(selected_assignment.assignments) - 1)
        if len(selected_assignment.assignments) > 1:
            selected_assignment.assignment_reason = (
                "single-slot reuse with diversity control"
            )

    return list(chunk_assignment_map.values())


def _assign_multi_chunk_slots(
    slots: list[QuestionSlot],
    chunks: list[dict],
    chapter: int,
) -> list[ChunkAssignment]:
    """
    Assign multi-chunk slots using lightweight bundle planning.

    The primary chunk still anchors the assignment, but supporting chunks are
    selected using heading/topic coherence first and adjacency second.
    """
    assignments: list[ChunkAssignment] = []

    # Build index for lightweight bundle planning.
    chunk_list = list(chunks)  # preserve DB order (page / position)
    num_chunks = len(chunk_list)

    if num_chunks == 0:
        return []

    # Rotate starting index so different slots get different primary chunks
    start_idx = 0

    for slot in slots:
        primary_idx = start_idx % num_chunks
        primary = chunk_list[primary_idx]

        bundle_strategy = _choose_bundle_strategy(slot)
        supporting = _select_supporting_chunks(
            slot=slot,
            primary=primary,
            primary_idx=primary_idx,
            chunk_list=chunk_list,
            max_extra=MULTI_CHUNK_EXTRA,
            strategy=bundle_strategy,
        )
        bundle_score, score_report = compute_bundle_score(
            slot=slot,
            primary=primary,
            supporting=supporting,
            primary_idx=primary_idx,
            chunk_list=chunk_list,
            strategy=bundle_strategy,
        )
        validation_report = validate_bundle_quality(
            slot=slot,
            primary=primary,
            supporting=supporting,
            bundle_score=bundle_score,
            score_report=score_report,
            strategy=bundle_strategy,
        )
        evidence_roles = {primary["chunk_id"]: "primary"}
        for support in supporting:
            evidence_roles[support["chunk_id"]] = support.get("role", "support")

        ca = ChunkAssignment(
            chunk_id=primary["chunk_id"],
            chunk_text=primary["content"],
            chapter=chapter,
            assignments=[{
                "difficulty": _score_to_difficulty(slot.difficulty_score),
                "bloom_level": slot.bloom_level,
                "question_type": slot.question_type,
                "slot_number": slot.slot_number,
            }],
            context_chunks=supporting[:MULTI_CHUNK_EXTRA],
            chunk_mode=slot.chunk_mode,
            bundle_strategy=bundle_strategy,
            supporting_chunks=supporting[:MULTI_CHUNK_EXTRA],
            bundle_score=bundle_score,
            assignment_reason=validation_report["summary"],
            evidence_roles=evidence_roles,
            estimated_context_tokens=_estimate_bundle_tokens(primary, supporting),
            bundle_validation_report=validation_report,
        )
        assignments.append(ca)

        # Advance starting index to spread across chunks
        start_idx += 1

    return assignments


async def _get_chapter_chunks(
    textbook_id: str,
    chapter: int,
    db_session: AsyncSession,
) -> list[dict]:
    """Get chunks from PostgreSQL for a specific chapter."""
    import json as _json

    query = select(TextbookChunk).where(
        TextbookChunk.textbook_id == textbook_id
    )

    # Filter by chapter if specified (chapter > 0)
    if chapter > 0:
        # Match chapter number in the 'chapter' field
        # Chapter field stores values like "Chương 3: ..." or "Chapter 3: ..."
        query = query.where(
            TextbookChunk.chapter.ilike(f"%{chapter}%")
        )

    result = await db_session.execute(query)
    rows = list(result.scalars().all())

    return [
        {
            "chunk_id": r.chunk_id,
            "content": r.content,
            "page": r.page,
            "chapter": r.chapter,
            "parent_heading": r.parent_heading,
        }
        for r in rows
    ]


def _score_to_difficulty(score: float) -> str:
    """Convert difficulty score to difficulty label."""
    if score <= 0.3:
        return "easy"
    elif score <= 0.6:
        return "medium"
    else:
        return "hard"


def _choose_bundle_strategy(slot: QuestionSlot) -> str:
    """Default bundle strategy heuristic.

    Phase 1 keeps the old easy/medium/hard intuition, but makes the strategy
    explicit so later phases can override it with stronger retrieval signals.
    """
    difficulty = _score_to_difficulty(slot.difficulty_score)
    if difficulty == "hard":
        return "semantic_multi"
    if difficulty == "medium":
        return "local_multi"
    return "single"


def _choose_chunk_mode(
    diff_level: str,
    bloom_level: str,
    question_type: str,
    constraints: dict,
) -> str:
    """Choose chunk mode using the current heuristic as a default.

    Rules are intentionally soft:
    - easy still prefers single
    - hard still prefers multi
    - medium can stay single for simpler factual MCQ patterns
    - essay/applied/analyze-style prompts lean multi earlier
    """
    if diff_level == "easy":
        return "single"
    if diff_level == "hard":
        return "multi"

    if question_type == "essay":
        return "multi"
    if bloom_level in {"analyze", "evaluate", "create"}:
        return "multi"
    if constraints.get("allow_applied_questions", True):
        return "multi"
    return "single"


def _pick_single_chunk_assignment(
    slot: QuestionSlot,
    desired_tag: tuple[str, str, str],
    shuffled_chunks: list[dict],
    chapter: int,
    chunk_assignment_map: dict[str, ChunkAssignment],
    chunk_tag_map: dict[str, set[tuple[str, str, str]]],
    concept_usage: dict[str, int],
) -> tuple[dict, ChunkAssignment]:
    """Pick the best chunk for a single-slot assignment.

    Preference order:
    1. chunks under capacity and unused for the same slot signature
    2. chunks with lower topic reuse
    3. chunks with fewer assigned tasks
    4. fallback to under-capacity chunks, then overflow reuse
    """
    preferred: list[tuple[int, int, int, dict, ChunkAssignment]] = []
    relaxed: list[tuple[int, int, int, dict, ChunkAssignment]] = []

    for order_idx, chunk in enumerate(shuffled_chunks):
        chunk_key = chunk["chunk_id"]
        concept_key = _chunk_topic_signature(chunk)
        ca = chunk_assignment_map.setdefault(
            chunk_key,
            ChunkAssignment(
                chunk_id=chunk["chunk_id"],
                chunk_text=chunk["content"],
                chapter=chapter,
                assignments=[],
                chunk_mode="single",
                bundle_strategy="single",
                bundle_score=1.0,
                assignment_reason="single-slot assignment from one chunk",
                evidence_roles={chunk["chunk_id"]: "primary"},
                estimated_context_tokens=_estimate_tokens(chunk["content"]),
            ),
        )
        existing_tags = chunk_tag_map.setdefault(chunk_key, set())
        if len(ca.assignments) >= MAX_SINGLE_PER_CHUNK:
            continue

        rank_key = (
            concept_usage.get(concept_key, 0),
            len(ca.assignments),
            order_idx,
            chunk,
            ca,
        )
        relaxed.append(rank_key)
        if desired_tag not in existing_tags:
            preferred.append(rank_key)

    if preferred:
        _, _, _, chunk, ca = min(preferred, key=lambda item: item[:3])
        return chunk, ca
    if relaxed:
        _, _, _, chunk, ca = min(relaxed, key=lambda item: item[:3])
        return chunk, ca

    overflow_chunk = shuffled_chunks[0]
    overflow_key = overflow_chunk["chunk_id"]
    overflow_assignment = chunk_assignment_map.setdefault(
        overflow_key,
        ChunkAssignment(
            chunk_id=overflow_chunk["chunk_id"],
            chunk_text=overflow_chunk["content"],
            chapter=chapter,
            assignments=[],
            chunk_mode="single",
            bundle_strategy="single",
            bundle_score=1.0,
            assignment_reason="single-slot overflow reuse",
            evidence_roles={overflow_chunk["chunk_id"]: "primary"},
            estimated_context_tokens=_estimate_tokens(overflow_chunk["content"]),
        ),
    )
    overflow_assignment.assignment_reason = "single-slot overflow reuse"
    return overflow_chunk, overflow_assignment


def _select_supporting_chunks(
    slot: QuestionSlot,
    primary: dict,
    primary_idx: int,
    chunk_list: list[dict],
    max_extra: int,
    strategy: str,
) -> list[dict]:
    """Select supporting chunks using lightweight coherence heuristics.

    Signals used in Phase 1:
    - same parent heading
    - heading/topic lexical overlap
    - chapter proximity
    - adjacency only as a secondary signal
    """
    # Prefer retrieval ranking helper if available (heading/chapter/lexical/
    # score signals). Keep a local fallback to avoid breaking old flow.
    ranked_by_retrieval = rank_supporting_chunks(
        primary_chunk=primary,
        chunk_list=chunk_list,
        strategy=strategy,
        primary_idx=primary_idx,
        max_extra=max_extra,
        enforce_diversity=True,
    )

    if ranked_by_retrieval:
        supporting: list[dict] = []
        for item in ranked_by_retrieval:
            candidate = item["chunk"]
            idx = item["index"]
            supporting.append({
                "chunk_id": candidate["chunk_id"],
                "chunk_text": candidate["content"],
                "parent_heading": candidate.get("parent_heading"),
                "relatedness_score": item["score"],
                "relatedness_features": item["features"],
                "role": _infer_support_role(primary, candidate, primary_idx, idx),
            })
        return supporting

    ranked: list[tuple[float, dict, int]] = []
    primary_heading = _normalize_heading(primary.get("parent_heading", ""))
    primary_signature = _chunk_topic_signature(primary)

    for idx, candidate in enumerate(chunk_list):
        if idx == primary_idx:
            continue

        candidate_heading = _normalize_heading(candidate.get("parent_heading", ""))
        candidate_signature = _chunk_topic_signature(candidate)
        heading_match = 1.0 if primary_heading and primary_heading == candidate_heading else 0.0
        lexical_overlap = _lexical_overlap(primary_heading, candidate_heading)
        topic_overlap = _lexical_overlap(primary_signature, candidate_signature)
        distance = abs(idx - primary_idx)
        proximity = 1.0 / (1.0 + distance)
        chapter_match = 1.0 if primary.get("chapter") == candidate.get("chapter") else 0.0

        if strategy == "semantic_multi":
            score = (
                0.32 * heading_match
                + 0.28 * topic_overlap
                + 0.20 * lexical_overlap
                + 0.12 * chapter_match
                + 0.08 * proximity
            )
        else:
            score = (
                0.28 * heading_match
                + 0.24 * lexical_overlap
                + 0.20 * topic_overlap
                + 0.18 * chapter_match
                + 0.10 * proximity
            )

        ranked.append((score, candidate, idx))

    ranked.sort(key=lambda item: item[0], reverse=True)

    supporting: list[dict] = []
    seen_support_groups: set[str] = set()
    for _, candidate, idx in ranked:
        group_key = _support_group_key(candidate)
        if group_key in seen_support_groups and len(ranked) > max_extra:
            continue
        supporting.append({
            "chunk_id": candidate["chunk_id"],
            "chunk_text": candidate["content"],
            "parent_heading": candidate.get("parent_heading"),
            "role": _infer_support_role(primary, candidate, primary_idx, idx),
        })
        seen_support_groups.add(group_key)
        if len(supporting) >= max_extra:
            break

    return supporting


def compute_bundle_score(
    slot: QuestionSlot,
    primary: dict,
    supporting: list[dict],
    primary_idx: int,
    chunk_list: list[dict],
    strategy: str,
) -> tuple[float, dict]:
    """Compute a lightweight bundle quality score for multi-chunk assignments."""
    if not supporting:
        return 0.25, {
            "support_count": 0,
            "heading_proximity_score": 0.0,
            "concept_overlap_score": 0.0,
            "distance_score": 0.0,
            "strategy_fit": 0.5,
        }

    index_map = {c["chunk_id"]: idx for idx, c in enumerate(chunk_list)}
    primary_heading = _normalize_heading(primary.get("parent_heading", ""))

    heading_scores: list[float] = []
    lexical_scores: list[float] = []
    topic_scores: list[float] = []
    distance_scores: list[float] = []
    duplicate_penalties = 0.0
    diversity_bonus = 0.0
    primary_signature = _chunk_topic_signature(primary)
    seen_groups: set[str] = set()

    for support in supporting:
        support_heading = _normalize_heading(support.get("parent_heading", ""))
        support_signature = _chunk_topic_signature(support)
        heading_scores.append(1.0 if primary_heading and support_heading == primary_heading else 0.0)
        lexical_scores.append(_lexical_overlap(primary_heading, support_heading))
        topic_scores.append(_lexical_overlap(primary_signature, support_signature))
        support_idx = index_map.get(support["chunk_id"], primary_idx)
        distance_scores.append(1.0 / (1.0 + abs(support_idx - primary_idx)))
        if support_heading and support_heading == primary_heading:
            duplicate_penalties += 0.05
        group_key = _support_group_key(support)
        if group_key not in seen_groups:
            seen_groups.add(group_key)
            diversity_bonus += 0.03

    heading_proximity_score = sum(heading_scores) / len(heading_scores)
    concept_overlap_score = sum(lexical_scores) / len(lexical_scores)
    topic_overlap_score = sum(topic_scores) / len(topic_scores)
    distance_score = sum(distance_scores) / len(distance_scores)
    strategy_fit = 1.0 if strategy == _choose_bundle_strategy(slot) else 0.7

    bundle_score = (
        0.28 * heading_proximity_score
        + 0.22 * concept_overlap_score
        + 0.18 * topic_overlap_score
        + 0.20 * distance_score
        + 0.20 * strategy_fit
        - duplicate_penalties
        + diversity_bonus
    )
    bundle_score = max(0.0, min(1.0, round(bundle_score, 3)))

    return bundle_score, {
        "support_count": len(supporting),
        "heading_proximity_score": round(heading_proximity_score, 3),
        "concept_overlap_score": round(concept_overlap_score, 3),
        "topic_overlap_score": round(topic_overlap_score, 3),
        "distance_score": round(distance_score, 3),
        "strategy_fit": round(strategy_fit, 3),
        "duplicate_penalty": round(duplicate_penalties, 3),
        "diversity_bonus": round(diversity_bonus, 3),
    }


def validate_bundle_quality(
    slot: QuestionSlot,
    primary: dict,
    supporting: list[dict],
    bundle_score: float,
    score_report: dict,
    strategy: str,
) -> dict:
    """Validate whether a bundle is coherent enough before generation."""
    issues: list[str] = []

    if slot.chunk_mode == "multi" and not supporting:
        issues.append("multi slot has no supporting chunks")
    if strategy == "semantic_multi" and len(supporting) < 2:
        issues.append("hard slot has limited supporting evidence")
    if bundle_score < 0.45:
        issues.append("bundle coherence is weak")
    if score_report.get("heading_proximity_score", 0.0) < 0.2 and score_report.get("concept_overlap_score", 0.0) < 0.2:
        issues.append("supporting chunks look weakly related to primary chunk")

    summary = (
        f"{strategy} bundle for slot {slot.slot_number}: "
        f"primary={primary['chunk_id'][:12]}..., supports={len(supporting)}, score={bundle_score:.2f}"
    )

    return {
        "valid": len(issues) == 0,
        "summary": summary,
        "issues": issues,
        "metrics": score_report,
    }


def _normalize_heading(text: str | None) -> str:
    """Normalize headings for cheap lexical comparison."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def _lexical_overlap(left: str, right: str) -> float:
    """Jaccard overlap over heading tokens."""
    left_tokens = set(_normalize_heading(left).split())
    right_tokens = set(_normalize_heading(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _chunk_topic_signature(chunk: dict) -> str:
    """Create a lightweight concept signature from heading + content prefix."""
    heading = _normalize_heading(chunk.get("parent_heading") or chunk.get("chapter") or "")
    if heading:
        return heading

    content = _normalize_heading(chunk.get("content") or chunk.get("chunk_text") or "")
    if not content:
        return "unknown"

    tokens = [token for token in content.split() if len(token) > 3]
    if not tokens:
        tokens = content.split()
    return " ".join(tokens[:8]) if tokens else "unknown"


def _support_group_key(chunk: dict) -> str:
    """Group supporting chunks by heading/topic to avoid redundant bundles."""
    heading = _normalize_heading(chunk.get("parent_heading", ""))
    if heading:
        return f"heading:{heading}"
    return f"topic:{_chunk_topic_signature(chunk)}"


def _infer_support_role(primary: dict, support: dict, primary_idx: int, support_idx: int) -> str:
    """Assign a simple evidence role for prompt formatting."""
    primary_heading = _normalize_heading(primary.get("parent_heading", ""))
    support_heading = _normalize_heading(support.get("parent_heading", ""))
    if primary_heading and support_heading == primary_heading:
        return "support"
    if abs(support_idx - primary_idx) <= 1:
        return "example"
    return "contrast"


def _estimate_tokens(text: str) -> int:
    """Cheap token estimate for prompt budgeting."""
    return max(1, math.ceil(len(text) / 4))


def _estimate_bundle_tokens(primary: dict, supporting: list[dict]) -> int:
    """Estimate total prompt tokens consumed by a bundle."""
    total_chars = len(primary.get("content", ""))
    total_chars += sum(len(chunk.get("chunk_text", "")) for chunk in supporting)
    return max(1, math.ceil(total_chars / 4))
