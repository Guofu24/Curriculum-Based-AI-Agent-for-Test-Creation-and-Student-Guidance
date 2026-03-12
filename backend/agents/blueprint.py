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

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from agents.state import ExamBlueprint, QuestionSlot, ChunkAssignment
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

                    # Determine chunk mode: easy → single, medium/hard → multi
                    chunk_mode = "single" if diff_level == "easy" else "multi"

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
    """Assign single-chunk slots — max 2 tasks per chunk (original logic)."""
    shuffled = list(chunks)
    random.shuffle(shuffled)

    MAX_PER_CHUNK = 2
    chunk_idx = 0
    chunk_assignment_map: dict[str, ChunkAssignment] = {}

    for slot in slots:
        attempts = 0
        while attempts < len(shuffled):
            chunk = shuffled[chunk_idx % len(shuffled)]
            chunk_key = chunk["chunk_id"]

            if chunk_key not in chunk_assignment_map:
                chunk_assignment_map[chunk_key] = ChunkAssignment(
                    chunk_id=chunk["chunk_id"],
                    chunk_text=chunk["content"],
                    chapter=chapter,
                    assignments=[],
                )

            ca = chunk_assignment_map[chunk_key]
            if len(ca.assignments) < MAX_PER_CHUNK:
                ca.assignments.append({
                    "difficulty": _score_to_difficulty(slot.difficulty_score),
                    "bloom_level": slot.bloom_level,
                    "question_type": slot.question_type,
                    "slot_number": slot.slot_number,
                })
                chunk_idx = (chunk_idx + 1) % len(shuffled)
                break

            chunk_idx = (chunk_idx + 1) % len(shuffled)
            attempts += 1
        else:
            # All chunks at max capacity, overflow to current chunk
            chunk = shuffled[chunk_idx % len(shuffled)]
            chunk_key = chunk["chunk_id"]
            if chunk_key not in chunk_assignment_map:
                chunk_assignment_map[chunk_key] = ChunkAssignment(
                    chunk_id=chunk["chunk_id"],
                    chunk_text=chunk["content"],
                    chapter=chapter,
                    assignments=[],
                )
            chunk_assignment_map[chunk_key].assignments.append({
                "difficulty": _score_to_difficulty(slot.difficulty_score),
                "bloom_level": slot.bloom_level,
                "question_type": slot.question_type,
                "slot_number": slot.slot_number,
            })

    return list(chunk_assignment_map.values())


# Number of extra context chunks for multi-chunk mode
MULTI_CHUNK_EXTRA = 2


def _assign_multi_chunk_slots(
    slots: list[QuestionSlot],
    chunks: list[dict],
    chapter: int,
) -> list[ChunkAssignment]:
    """
    Assign multi-chunk slots — each slot gets its own ChunkAssignment
    with a primary chunk + 1-2 adjacent context chunks for synthesis.

    Adjacent chunks are preferred because they are topically coherent
    (no embedding calls needed).
    """
    assignments: list[ChunkAssignment] = []

    # Build index for adjacency lookup
    chunk_list = list(chunks)  # preserve DB order (page / position)
    num_chunks = len(chunk_list)

    if num_chunks == 0:
        return []

    # Rotate starting index so different slots get different primary chunks
    start_idx = 0

    for slot in slots:
        primary_idx = start_idx % num_chunks
        primary = chunk_list[primary_idx]

        # Gather adjacent chunks (before + after primary)
        extra: list[dict] = []
        for offset in range(1, MULTI_CHUNK_EXTRA + 1):
            # After primary
            after_idx = primary_idx + offset
            if after_idx < num_chunks:
                c = chunk_list[after_idx]
                extra.append({
                    "chunk_id": c["chunk_id"],
                    "chunk_text": c["content"],
                })
            # Before primary (fallback if we ran out of "after" chunks)
            if len(extra) >= MULTI_CHUNK_EXTRA:
                break
            before_idx = primary_idx - offset
            if before_idx >= 0:
                c = chunk_list[before_idx]
                extra.append({
                    "chunk_id": c["chunk_id"],
                    "chunk_text": c["content"],
                })
            if len(extra) >= MULTI_CHUNK_EXTRA:
                break

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
            context_chunks=extra[:MULTI_CHUNK_EXTRA],
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
