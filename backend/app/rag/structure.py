"""Structure detection: heading tree building from markdown."""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubsectionNode:
    """A subsection within a section."""
    section_id: str
    title: str


@dataclass
class SectionNode:
    """A section within a chapter."""
    section_id: str
    title: str
    subsections: list[SubsectionNode] = field(default_factory=list)


@dataclass
class ChapterNode:
    """A chapter in the document."""
    chapter_id: str
    title: str
    sections: list[SectionNode] = field(default_factory=list)


def detect_heading_tree(markdown: str) -> dict:
    """
    Parse markdown heading tags (#, ##, ###) into a nested heading tree.

    Returns a dict with chapters/sections/subsections hierarchy per spec:
    {
      "chapters": [
        {
          "chapter_id": "ch1",
          "title": "Chương 1: Động lực học",
          "sections": [
            {"section_id": "ch1_sec1", "title": "1.1 Lực và phân loại lực", "subsections": []}
          ]
        }
      ]
    }
    """
    lines = markdown.split("\n")
    chapters: list[ChapterNode] = []
    current_chapter: ChapterNode | None = None
    current_section: SectionNode | None = None

    chapter_counter = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if not heading_match:
            continue

        level = len(heading_match.group(1))
        title = heading_match.group(2).strip()

        if level == 1:
            chapter_counter += 1
            current_chapter = ChapterNode(
                chapter_id=f"ch{chapter_counter}",
                title=title,
                sections=[],
            )
            chapters.append(current_chapter)
            current_section = None

        elif level == 2:
            if current_chapter is None:
                chapter_counter = 1
                current_chapter = ChapterNode(
                    chapter_id=f"ch{chapter_counter}",
                    title="",
                    sections=[],
                )
                chapters.append(current_chapter)

            base = current_chapter.chapter_id
            current_section = SectionNode(
                section_id=f"{base}_sec{len(current_chapter.sections) + 1}",
                title=title,
                subsections=[],
            )
            current_chapter.sections.append(current_section)

        elif level == 3:
            if current_chapter is None:
                chapter_counter = 1
                current_chapter = ChapterNode(
                    chapter_id=f"ch{chapter_counter}",
                    title="",
                    sections=[],
                )
                chapters.append(current_chapter)

            if current_section is None:
                base = current_chapter.chapter_id
                current_section = SectionNode(
                    section_id=f"{base}_sec{len(current_chapter.sections) + 1}",
                    title="",
                    subsections=[],
                )
                current_chapter.sections.append(current_section)

            sub = SubsectionNode(
                section_id=f"{current_section.section_id}_sub{len(current_section.subsections) + 1}",
                title=title,
            )
            current_section.subsections.append(sub)

    return {
        "chapters": [
            {
                "chapter_id": ch.chapter_id,
                "title": ch.title,
                "sections": [
                    {
                        "section_id": s.section_id,
                        "title": s.title,
                        "subsections": [
                            {"section_id": sub.section_id, "title": sub.title}
                            for sub in s.subsections
                        ],
                    }
                    for s in ch.sections
                ],
            }
            for ch in chapters
        ]
    }


def flatten_heading_tree(tree: dict) -> list[dict]:
    """
    Flatten heading tree into a list of all heading units (chapters, sections, subsections)
    for scope selection.

    Each entry has: id, title, level (1=chapter, 2=section, 3=subsection), chapter_id, path
    """
    result: list[dict] = []
    for chapter in tree.get("chapters", []):
        result.append({
            "id": chapter["chapter_id"],
            "title": chapter["title"],
            "level": 1,
            "chapter_id": chapter["chapter_id"],
            "path": chapter["title"],
        })
        for section in chapter.get("sections", []):
            result.append({
                "id": section["section_id"],
                "title": section["title"],
                "level": 2,
                "chapter_id": chapter["chapter_id"],
                "path": f"{chapter['title']} > {section['title']}",
            })
            for sub in section.get("subsections", []):
                result.append({
                    "id": sub["section_id"],
                    "title": sub["title"],
                    "level": 3,
                    "chapter_id": chapter["chapter_id"],
                    "path": f"{chapter['title']} > {section['title']} > {sub['title']}",
                })
    return result
