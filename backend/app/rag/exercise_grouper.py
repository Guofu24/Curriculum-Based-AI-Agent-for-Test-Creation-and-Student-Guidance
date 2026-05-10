"""Group exercise chunks before section alignment.

The chunker deliberately marks exercise/solution regions as section_unknown.
This module groups those chunks into problem+solution units so an LLM router can
classify a whole exercise instead of one arbitrary chunk at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata


_RE_PART_LABEL = re.compile(r"\bphan\s+([ivxlcdm]+|[a-z]|\d+)\b", re.IGNORECASE)
_RE_MAJOR_HEADING = re.compile(r"^(?:[ivxlcdm]+|[a-z])[\.\)]\s+.{3,}$", re.IGNORECASE)
_RE_EXERCISE_NUM = re.compile(r"\b(?:bai|cau)\s+(?:so\s*)?(\d{1,3})\b", re.IGNORECASE)
_RE_SOLUTION_HDR = re.compile(
    r"huong\s*dan|dap\s*so|loi\s*giai|bai\s*giai|\bhd\b",
    re.IGNORECASE,
)

_MAX_TEXT_CHARS = 1200


@dataclass
class ExerciseGroup:
    group_id: str
    chunk_ids: list[str] = field(default_factory=list)
    solution_chunk_ids: list[str] = field(default_factory=list)
    problem_text: str = ""
    solution_text: str | None = None
    part_label: str = ""
    major_heading: str = ""
    exercise_number: int = 0
    chapter_id: str = ""

    @property
    def all_chunk_ids(self) -> set[str]:
        return set(self.chunk_ids) | set(self.solution_chunk_ids)


def _strip_diacritics(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _norm(text: str) -> str:
    text = _strip_diacritics(text or "").lower()
    text = re.sub(r"[^\w\s]+", " ", text)
    return re.sub(r"\s+", "_", text).strip("_")


def _short_text(parts: list[str], limit: int = _MAX_TEXT_CHARS) -> str:
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0].strip() or text[:limit].strip()


def _first_lines(text: str, limit: int = 6) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()][:limit]


def _extract_part_label(text: str) -> str | None:
    for line in _first_lines(text, 8):
        match = _RE_PART_LABEL.search(_strip_diacritics(line).lower())
        if match:
            return match.group(1).upper()
    return None


def _extract_major_heading(text: str) -> str | None:
    for line in _first_lines(text, 4):
        plain = _strip_diacritics(line).lower().strip()
        if len(plain) > 140:
            continue
        if _RE_EXERCISE_NUM.search(plain) or _RE_SOLUTION_HDR.search(plain):
            continue
        if _RE_MAJOR_HEADING.match(plain):
            return line
    return None


def _extract_exercise_number(text: str) -> int | None:
    match = _RE_EXERCISE_NUM.search(_strip_diacritics(text).lower())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _is_solution_chunk(text: str) -> bool:
    return bool(_RE_SOLUTION_HDR.search(_strip_diacritics(text).lower()))


def _group_id(doc_id: str, part_label: str, major_heading: str, exercise_number: int) -> str:
    part = _norm(part_label) or "part_unknown"
    major = _norm(major_heading) or "major_unknown"
    return f"{doc_id}_{part}_{major}_bai_{exercise_number}"


def _unique_problem_lookup(groups: dict[str, ExerciseGroup]) -> dict[tuple[str, int], ExerciseGroup | None]:
    by_part_num: dict[tuple[str, int], ExerciseGroup | None] = {}
    for group in groups.values():
        key = (group.part_label, group.exercise_number)
        if key in by_part_num:
            by_part_num[key] = None
        else:
            by_part_num[key] = group
    return by_part_num


def build_exercise_groups(chunks: list[dict], doc_id: str) -> list[ExerciseGroup]:
    """Build exercise groups from section-unknown chunks.

    Input must preserve document order. The function does not mutate chunks.
    Only chunks with section_confidence="unknown" are considered; canonical
    theory chunks are intentionally ignored.
    """
    groups: dict[str, ExerciseGroup] = {}
    problem_parts: dict[str, list[str]] = {}
    solution_parts: dict[str, list[str]] = {}

    current_part = ""
    current_major = ""
    current_problem: ExerciseGroup | None = None
    current_solution_group: ExerciseGroup | None = None
    solution_mode = False

    for chunk in chunks:
        if chunk.get("section_confidence", "unknown") != "unknown":
            continue

        content = (chunk.get("content") or "").strip()
        chunk_id = chunk.get("chunk_id", "")
        if not content or not chunk_id:
            continue

        is_solution = _is_solution_chunk(content)
        part = _extract_part_label(content)
        if part:
            current_part = part
            current_problem = None
            current_solution_group = None
            if is_solution:
                current_major = ""
            else:
                solution_mode = False

        major = _extract_major_heading(content)
        if major:
            current_major = major
            current_problem = None
            current_solution_group = None
            if not is_solution:
                solution_mode = False

        if is_solution:
            solution_mode = True
            current_problem = None

        exercise_number = _extract_exercise_number(content)
        if exercise_number is not None:
            gid = _group_id(doc_id, current_part, current_major, exercise_number)

            if solution_mode:
                group = groups.get(gid)
                if group is None:
                    by_part_num = _unique_problem_lookup(groups)
                    group = by_part_num.get((current_part, exercise_number))
                if group is not None:
                    group.solution_chunk_ids.append(chunk_id)
                    solution_parts.setdefault(group.group_id, []).append(content)
                    current_solution_group = group
                    continue
                current_solution_group = None
                continue

            group = groups.get(gid)
            if group is None:
                group = ExerciseGroup(
                    group_id=gid,
                    part_label=current_part,
                    major_heading=current_major,
                    exercise_number=exercise_number,
                    chapter_id=chunk.get("chapter_id", "") or "",
                )
                groups[gid] = group
            group.chunk_ids.append(chunk_id)
            problem_parts.setdefault(gid, []).append(content)
            current_problem = group
            current_solution_group = None
            continue

        if solution_mode and current_solution_group is not None:
            current_solution_group.solution_chunk_ids.append(chunk_id)
            solution_parts.setdefault(current_solution_group.group_id, []).append(content)
        elif not solution_mode and current_problem is not None:
            current_problem.chunk_ids.append(chunk_id)
            problem_parts.setdefault(current_problem.group_id, []).append(content)

    result: list[ExerciseGroup] = []
    for group in groups.values():
        group.problem_text = _short_text(problem_parts.get(group.group_id, []))
        solution_text = _short_text(solution_parts.get(group.group_id, []))
        group.solution_text = solution_text or None
        if group.problem_text:
            result.append(group)
    return result
