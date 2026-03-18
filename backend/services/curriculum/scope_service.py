from __future__ import annotations

from dataclasses import dataclass, field

from agents.state import ScopeUnit
from models.curriculum import Section
from repositories.document_repository import DocumentRepository


@dataclass
class ResolvedScope:
    selected_scope: list[ScopeUnit] = field(default_factory=list)
    selected_sections: list[Section] = field(default_factory=list)
    selected_section_ids: list[str] = field(default_factory=list)
    chapter_numbers: list[int] = field(default_factory=list)
    section_by_id: dict[str, Section] = field(default_factory=dict)


class CurriculumScopeService:
    def __init__(self, repository: DocumentRepository):
        self.repository = repository

    async def resolve_scope(
        self,
        document_id: str,
        requested_scope: list[dict] | None = None,
        requested_chapters: list[int] | None = None,
    ) -> ResolvedScope:
        sections = await self.repository.get_document_sections(document_id)
        if not sections:
            fallback_scope = self._fallback_scope_units(document_id, requested_chapters or [])
            return ResolvedScope(
                selected_scope=fallback_scope,
                selected_sections=[],
                selected_section_ids=[item.section_id for item in fallback_scope if item.section_id],
                chapter_numbers=sorted(
                    {
                        int(item.chapter_number)
                        for item in fallback_scope
                        if int(item.chapter_number or 0) > 0
                    }
                ),
                section_by_id={},
            )

        section_by_id = {section.id: section for section in sections}
        children_by_parent: dict[str | None, list[Section]] = {}
        for section in sections:
            children_by_parent.setdefault(section.parent_section_id, []).append(section)

        for child_list in children_by_parent.values():
            child_list.sort(key=lambda item: (item.section_order or 0, item.section_title or ""))

        requested_ids = {
            str(item.get("scope_id") or item.get("section_id") or "").strip()
            for item in (requested_scope or [])
            if str(item.get("scope_id") or item.get("section_id") or "").strip()
        }
        requested_chapter_numbers = {
            int(chapter)
            for chapter in (requested_chapters or [])
            if isinstance(chapter, int) and chapter > 0
        }
        explicit_scope_requested = bool(requested_ids or requested_chapter_numbers)

        selected_roots: list[Section] = []
        if requested_ids:
            for section in sections:
                if section.id in requested_ids:
                    selected_roots.append(section)
        elif requested_chapter_numbers:
            for section in sections:
                chapter_number = self._section_chapter_number(section)
                if chapter_number in requested_chapter_numbers and section.section_type == "chapter":
                    selected_roots.append(section)
            if not selected_roots:
                for section in sections:
                    if self._section_chapter_number(section) in requested_chapter_numbers:
                        selected_roots.append(section)
        else:
            selected_roots = list(children_by_parent.get(None) or sections)

        generation_sections: list[Section] = []
        seen: set[str] = set()
        for section in selected_roots:
            for resolved in self._collect_generation_sections(section, children_by_parent):
                if resolved.id in seen:
                    continue
                seen.add(resolved.id)
                generation_sections.append(resolved)

        if not generation_sections and not explicit_scope_requested:
            generation_sections = list(sections)

        scope_units = [self._section_to_scope_unit(section) for section in generation_sections]
        chapter_numbers = sorted(
            {
                self._section_chapter_number(section)
                for section in generation_sections
                if self._section_chapter_number(section) > 0
            }
        )

        return ResolvedScope(
            selected_scope=scope_units,
            selected_sections=generation_sections,
            selected_section_ids=[section.id for section in generation_sections],
            chapter_numbers=chapter_numbers,
            section_by_id=section_by_id,
        )

    def chunk_matches_section(self, metadata: dict, section: Section | None) -> bool:
        if section is None:
            return True
        if not isinstance(metadata, dict):
            return False

        chapter_number = metadata.get("chapter_number")
        if isinstance(chapter_number, str) and chapter_number.isdigit():
            chapter_number = int(chapter_number)
        if not isinstance(chapter_number, int):
            chapter_number = 0

        expected_chapter = self._section_chapter_number(section)
        if expected_chapter > 0 and chapter_number not in {0, expected_chapter}:
            return False

        page = metadata.get("page") or metadata.get("page_number")
        if isinstance(page, str) and page.isdigit():
            page = int(page)
        if isinstance(page, int):
            if section.page_from is not None and page < section.page_from:
                return False
            if section.page_to is not None and page > section.page_to:
                return False

        expected_heading = (section.scope_label or section.section_title or "").strip().lower()
        candidate_heading = str(metadata.get("parent_heading") or "").strip().lower()
        if section.section_type in {"lesson", "topic", "subtopic"} and expected_heading:
            if not candidate_heading:
                return False
            if expected_heading not in candidate_heading and candidate_heading not in expected_heading:
                return False

        return True

    def _collect_generation_sections(
        self,
        section: Section,
        children_by_parent: dict[str | None, list[Section]],
    ) -> list[Section]:
        children = list(children_by_parent.get(section.id) or [])
        concrete_children = [
            child
            for child in children
            if child.section_type in {"lesson", "topic", "subtopic", "unknown"}
        ]
        if concrete_children:
            results: list[Section] = []
            for child in concrete_children:
                results.extend(self._collect_generation_sections(child, children_by_parent))
            return results

        if children:
            results: list[Section] = []
            for child in children:
                results.extend(self._collect_generation_sections(child, children_by_parent))
            return results or [section]

        return [section]

    def _fallback_scope_units(
        self,
        document_id: str,
        requested_chapters: list[int],
    ) -> list[ScopeUnit]:
        if requested_chapters:
            return [
                ScopeUnit(
                    scope_id=f"chapter:{chapter}",
                    section_id=None,
                    scope_type="chapter",
                    title=f"Chapter {chapter}",
                    chapter_number=int(chapter),
                    tags=[f"chapter:{int(chapter)}"],
                )
                for chapter in requested_chapters
            ]
        return [
            ScopeUnit(
                scope_id=f"document:{document_id}",
                section_id=None,
                scope_type="unknown",
                title="Toàn bộ tài liệu",
                chapter_number=0,
                tags=[f"document:{document_id}"],
            )
        ]

    def _section_to_scope_unit(self, section: Section) -> ScopeUnit:
        chapter_number = self._section_chapter_number(section)
        tags = [
            f"section:{section.id}",
            f"section_type:{section.section_type}",
        ]
        if chapter_number > 0:
            tags.append(f"chapter:{chapter_number}")
        return ScopeUnit(
            scope_id=section.id,
            section_id=section.id,
            scope_type=section.section_type or "unknown",
            title=section.section_title or "Untitled Section",
            chapter_number=chapter_number,
            page_from=section.page_from,
            page_to=section.page_to,
            tags=tags,
        )

    def _section_chapter_number(self, section: Section) -> int:
        metadata = section.metadata_json or {}
        chapter_number = metadata.get("chapter_number", 0)
        try:
            return int(chapter_number or 0)
        except (TypeError, ValueError):
            return 0
