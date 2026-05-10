"""LLM router for assigning exercise groups to canonical heading_tree sections."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.core.redis_client import RedisClient
from app.rag.exercise_grouper import ExerciseGroup
from app.rag.gemini_key_pool import GeminiKeyPool

logger = logging.getLogger("app.rag.alignment")

ALIGNMENT_PROMPT_VERSION = "v1.0"
ALIGNMENT_BATCH_SIZE = 5
_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


class ExerciseAlignment(BaseModel):
    group_id: str
    chapter_id: str = ""
    section_id: str = ""
    confidence: Literal["high", "medium", "unknown"] = "unknown"
    reason: str = ""


class AlignmentBatch(BaseModel):
    alignments: list[ExerciseAlignment] = Field(default_factory=list)


@dataclass
class AlignmentReport:
    groups_detected: int = 0
    cache_hits: int = 0
    batches_called: int = 0
    llm_aligned: int = 0
    unknown: int = 0
    invalid_ids: int = 0
    skipped_no_key: int = 0
    errors: list[str] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)


def _sha256(text: str | bytes) -> str:
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def heading_tree_hash(heading_tree: dict) -> str:
    raw = json.dumps(heading_tree or {}, ensure_ascii=False, sort_keys=True)
    return _sha256(raw)


def _cache_dir() -> Path:
    path = Path(__file__).resolve().parents[2] / ".cache" / "alignment"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _alignment_cache_key(group: ExerciseGroup, tree_hash: str, model: str) -> str:
    raw = json.dumps(
        {
            "group_id": group.group_id,
            "problem_text": group.problem_text,
            "solution_text": group.solution_text or "",
            "part_label": group.part_label,
            "major_heading": group.major_heading,
            "exercise_number": group.exercise_number,
            "tree_hash": tree_hash,
            "prompt_version": ALIGNMENT_PROMPT_VERSION,
            "model": model,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"alignment_cache:{_sha256(raw)}"


async def _cache_get(redis: RedisClient | None, key: str) -> ExerciseAlignment | None:
    if redis is not None:
        try:
            cached = await redis.get(key)
            if cached:
                return ExerciseAlignment.model_validate_json(cached)
        except Exception:
            pass

    file_path = _cache_dir() / f"{key.split(':', 1)[-1]}.json"
    if file_path.exists():
        try:
            return ExerciseAlignment.model_validate_json(file_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


async def _cache_set(redis: RedisClient | None, key: str, alignment: ExerciseAlignment) -> None:
    payload = alignment.model_dump_json()
    if redis is not None:
        try:
            await redis.set(key, payload, ttl=_CACHE_TTL_SECONDS)
        except Exception:
            pass
    try:
        (_cache_dir() / f"{key.split(':', 1)[-1]}.json").write_text(payload, encoding="utf-8")
    except Exception as exc:
        logger.debug("Alignment file cache write skipped: %s", exc)


def _tree_maps(heading_tree: dict) -> tuple[dict[str, str], dict[str, dict[str, str]], dict[str, str]]:
    chapter_titles: dict[str, str] = {}
    section_titles: dict[str, str] = {}
    valid_sections_by_chapter: dict[str, dict[str, str]] = {}
    for chapter in heading_tree.get("chapters", []):
        ch_id = chapter.get("chapter_id", "")
        if not ch_id:
            continue
        chapter_titles[ch_id] = chapter.get("title", "")
        valid_sections_by_chapter[ch_id] = {}
        for section in chapter.get("sections", []):
            sec_id = section.get("section_id", "")
            if not sec_id:
                continue
            title = section.get("title", "")
            valid_sections_by_chapter[ch_id][sec_id] = title
            section_titles[sec_id] = title
    return chapter_titles, valid_sections_by_chapter, section_titles


def _validate_alignment(
    alignment: ExerciseAlignment,
    heading_tree: dict,
) -> tuple[ExerciseAlignment | None, int]:
    chapter_titles, valid_sections_by_chapter, _ = _tree_maps(heading_tree)
    if alignment.confidence != "high":
        invalid = 0
        if alignment.chapter_id and alignment.chapter_id not in chapter_titles:
            invalid += 1
        elif alignment.chapter_id and alignment.section_id:
            valid_sections = valid_sections_by_chapter.get(alignment.chapter_id, {})
            if alignment.section_id not in valid_sections:
                invalid += 1
        return alignment.model_copy(update={"confidence": "unknown"}), invalid

    if alignment.chapter_id not in chapter_titles:
        return None, 1

    valid_sections = valid_sections_by_chapter.get(alignment.chapter_id, {})
    if alignment.section_id not in valid_sections:
        if alignment.section_id:
            return None, 1
        return alignment.model_copy(update={"confidence": "unknown"}), 0

    if not alignment.section_id:
        return alignment.model_copy(update={"confidence": "unknown"}), 0

    return alignment, 0


def _json_from_response(text: str) -> str:
    clean = (text or "").strip()
    if clean.startswith("```"):
        lines = [ln for ln in clean.splitlines() if not ln.strip().startswith("```")]
        clean = "\n".join(lines).strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        return clean[start:end + 1]
    return clean


def _balance_json_fragment(text: str) -> str:
    """Append missing JSON closers for common truncated-but-otherwise-valid output."""
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()

    repaired = text.rstrip()
    while repaired.endswith(","):
        repaired = repaired[:-1].rstrip()
    if in_string:
        repaired += '"'
    repaired += "".join(reversed(stack))
    return repaired


def _parse_alignment_batch(payload: str) -> AlignmentBatch:
    try:
        return AlignmentBatch.model_validate_json(payload)
    except ValidationError:
        try:
            obj, _idx = json.JSONDecoder().raw_decode(payload)
            return AlignmentBatch.model_validate(obj)
        except Exception:
            repaired = _balance_json_fragment(payload)
            if repaired != payload:
                try:
                    return AlignmentBatch.model_validate_json(repaired)
                except ValidationError:
                    obj, _idx = json.JSONDecoder().raw_decode(repaired)
                    return AlignmentBatch.model_validate(obj)
            raise


def _heading_tree_prompt(heading_tree: dict) -> str:
    lines: list[str] = []
    for chapter in heading_tree.get("chapters", []):
        ch_id = chapter.get("chapter_id", "")
        ch_title = chapter.get("title", "")
        lines.append(f"- {ch_id}: {ch_title}")
        for section in chapter.get("sections", []):
            sec_id = section.get("section_id", "")
            sec_title = section.get("title", "")
            lines.append(f"  - {sec_id}: {sec_title}")
    return "\n".join(lines)


def _groups_payload(groups: list[ExerciseGroup]) -> list[dict]:
    return [
        {
            "group_id": group.group_id,
            "inherited_chapter_id": group.chapter_id,
            "part_label": group.part_label,
            "major_heading": group.major_heading,
            "exercise_number": group.exercise_number,
            "problem_text": group.problem_text,
            "solution_text": group.solution_text or "",
        }
        for group in groups
    ]


def _build_messages(groups: list[ExerciseGroup], heading_tree: dict) -> list[dict]:
    schema = {
        "alignments": [
            {
                "group_id": "same group_id from input",
                "chapter_id": "one valid chapter_id from heading tree, or empty if unknown",
                "section_id": "one valid section_id under chapter_id, or empty if unknown",
                "confidence": "high | medium | unknown",
                "reason": "short Vietnamese reason, <= 12 words",
            }
        ]
    }
    system = (
        "You are a strict curriculum router. Classify each exercise group into the "
        "existing heading_tree IDs only. Do not create new IDs. If the exercise "
        "uses multiple sections or evidence is weak, return confidence='unknown' "
        "with empty chapter_id/section_id. Return only valid JSON."
    )
    user = (
        "Canonical heading_tree:\n"
        f"{_heading_tree_prompt(heading_tree)}\n\n"
        "Exercise groups to classify:\n"
        f"{json.dumps(_groups_payload(groups), ensure_ascii=False, indent=2)}\n\n"
        "Rules:\n"
        "- Use problem_text and solution_text together when available.\n"
        "- Prefer section-level match; v1 accepts only confidence='high'.\n"
        "- If unsure, multi-topic, or no exact curriculum section fits, use unknown.\n"
        "- Output compact JSON exactly like this schema, no markdown, no prose:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _call_gemini_json(api_key: str, model: str, messages: list[dict]) -> AlignmentBatch:
    from openai import AsyncOpenAI

    async with AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        max_retries=0,
    ) as client:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            max_tokens=8000,
        )
    content = response.choices[0].message.content or ""
    payload = _json_from_response(content)
    return _parse_alignment_batch(payload)


def _apply_alignment(
    chunks: list[dict],
    group: ExerciseGroup,
    alignment: ExerciseAlignment,
    heading_tree: dict,
) -> int:
    chapter_titles, _, section_titles = _tree_maps(heading_tree)
    chunk_ids = group.all_chunk_ids
    changed = 0
    for chunk in chunks:
        if chunk.get("chunk_id") not in chunk_ids:
            continue
        chunk["chapter_id"] = alignment.chapter_id
        chunk["chapter"] = chapter_titles.get(alignment.chapter_id, chunk.get("chapter", ""))
        chunk["chapter_confidence"] = "llm_inferred"
        chunk["section_id"] = alignment.section_id
        chunk["section"] = section_titles.get(alignment.section_id, chunk.get("section", ""))
        chunk["section_confidence"] = "llm_inferred"
        chunk["alignment_reason"] = alignment.reason
        chunk["alignment_group_id"] = group.group_id
        chunk["alignment_confidence"] = alignment.confidence
        changed += 1
    return changed


async def align_exercise_groups(
    chunks: list[dict],
    groups: list[ExerciseGroup],
    heading_tree: dict,
    pool: GeminiKeyPool,
    redis: RedisClient | None = None,
    model: str | None = None,
    batch_size: int = ALIGNMENT_BATCH_SIZE,
) -> tuple[list[dict], AlignmentReport]:
    """Align exercise groups and mutate chunk metadata for accepted high matches."""
    report = AlignmentReport(groups_detected=len(groups))
    if not groups or not heading_tree.get("chapters"):
        report.unknown = len(groups)
        return chunks, report

    settings = get_settings()
    resolved_model = model or settings.GEMINI_ALIGNMENT_MODEL or settings.GEMINI_MODEL
    tree_hash = heading_tree_hash(heading_tree)
    accepted_by_group: dict[str, ExerciseAlignment] = {}
    group_by_id = {group.group_id: group for group in groups}
    uncached: list[ExerciseGroup] = []

    for group in groups:
        cache_key = _alignment_cache_key(group, tree_hash, resolved_model)
        cached = await _cache_get(redis, cache_key)
        if cached is None:
            uncached.append(group)
            continue
        report.cache_hits += 1
        validated, invalid = _validate_alignment(cached, heading_tree)
        report.invalid_ids += invalid
        if validated and validated.confidence == "high" and validated.section_id:
            accepted_by_group[group.group_id] = validated

    for i in range(0, len(uncached), batch_size):
        batch_groups = uncached[i:i + batch_size]
        batch_result: AlignmentBatch | None = None
        last_error: Exception | None = None

        for _attempt in range(max(1, len(pool.keys))):
            key = await pool.get_available_key()
            if key is None:
                report.skipped_no_key += len(batch_groups)
                break
            try:
                batch_result = await _call_gemini_json(
                    key,
                    resolved_model,
                    _build_messages(batch_groups, heading_tree),
                )
                await pool.mark_used(key)
                report.batches_called += 1
                break
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                await pool.mark_used(key)
                report.errors.append(f"parse_failed:{str(exc)[:120]}")
                break
            except Exception as exc:
                last_error = exc
                await pool.mark_error(key, exc)
                report.errors.append(f"llm_failed:{str(exc)[:120]}")
                await asyncio.sleep(0.2)

        if batch_result is None:
            if last_error:
                logger.warning("Alignment batch skipped after error: %s", last_error)
            continue

        returned_ids = set()
        for raw_alignment in batch_result.alignments:
            group = group_by_id.get(raw_alignment.group_id)
            if group is None:
                continue
            returned_ids.add(group.group_id)
            cache_key = _alignment_cache_key(group, tree_hash, resolved_model)
            validated, invalid = _validate_alignment(raw_alignment, heading_tree)
            report.invalid_ids += invalid
            if validated is None:
                validated = ExerciseAlignment(
                    group_id=group.group_id,
                    confidence="unknown",
                    reason="Invalid chapter_id or section_id",
                )
            await _cache_set(redis, cache_key, validated)
            if validated and validated.confidence == "high" and validated.section_id:
                accepted_by_group[group.group_id] = validated

        for group in batch_groups:
            if group.group_id not in returned_ids:
                unknown = ExerciseAlignment(
                    group_id=group.group_id,
                    confidence="unknown",
                    reason="LLM did not return this group",
                )
                await _cache_set(redis, _alignment_cache_key(group, tree_hash, resolved_model), unknown)

    for group_id, alignment in accepted_by_group.items():
        group = group_by_id[group_id]
        changed = _apply_alignment(chunks, group, alignment, heading_tree)
        if changed:
            report.llm_aligned += 1
            if len(report.samples) < 10:
                report.samples.append(
                    {
                        "group_id": group_id,
                        "chapter_id": alignment.chapter_id,
                        "section_id": alignment.section_id,
                        "reason": alignment.reason,
                    }
                )

    report.unknown = max(0, len(groups) - report.llm_aligned)
    return chunks, report
