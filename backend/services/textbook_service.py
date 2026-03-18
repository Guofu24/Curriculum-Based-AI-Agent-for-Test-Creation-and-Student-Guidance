"""
Document service built on top of the legacy Textbook table.

The existing app still uses "textbook" naming, but the service now exposes
document-oriented behavior close to the curriculum-based system spec.
"""
import hashlib
import uuid
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.document_processor import DocumentProcessorAgent
from config import settings
from core.mvp import normalize_mvp_language, normalize_physics_subject, require_pdf_extension
from models.course import CourseMembership
from models.curriculum import LearningObjective, Section
from models.textbook import ProcessingStatus, Textbook, TextbookChapter, TextbookChunk
from services.course_service import CourseService
from services.rag_service import RAGService


class TextbookService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.course_service = CourseService(db)

    async def upload_textbook(
        self,
        user_id: str,
        title: str,
        file_name: str,
        file_content: bytes,
        file_type: str,
        course_id: str | None = None,
        language: str = "vi",
    ) -> Textbook:
        """Upload and process a document, persisting curriculum structure."""
        if course_id and not await self.course_service.has_course_access(course_id, user_id):
            raise ValueError("Course not found or access denied")
        require_pdf_extension(file_type)
        language = normalize_mvp_language(language)
        if course_id:
            course = await self.course_service.get_course(course_id, user_id)
            if not course:
                raise ValueError("Course not found or access denied")
            normalize_physics_subject(course.subject)

        file_hash = hashlib.sha256(file_content).hexdigest()
        duplicate = await self._find_duplicate_document(
            user_id=user_id,
            course_id=course_id,
            file_hash=file_hash,
        )
        if duplicate:
            return duplicate

        textbook_id = str(uuid.uuid4())
        upload_dir = Path(settings.UPLOAD_DIR).resolve() / user_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(file_name).suffix
        file_path = upload_dir / f"{textbook_id}{ext}"
        file_path.write_bytes(file_content)

        textbook = Textbook(
            id=textbook_id,
            owner_id=user_id,
            course_id=course_id,
            title=title,
            file_name=file_name,
            file_path=str(file_path),
            file_storage_url=str(file_path),
            file_type=file_type,
            file_size=len(file_content),
            file_hash=file_hash,
            language=language,
            status=ProcessingStatus.PARSING,
            curriculum_tree_json=[],
        )
        self.db.add(textbook)
        await self.db.flush()

        try:
            rag = RAGService.get_instance()
            vector_store = rag.get_vector_store(namespace=textbook_id)
            processor = DocumentProcessorAgent(vector_store=vector_store, db_session=self.db)
            result = await processor.process_document(
                file_path=str(file_path),
                textbook_id=textbook_id,
            )

            await self._replace_chapters(textbook_id, result.get("chapters", []))
            await self._replace_sections(textbook_id, result.get("sections", []))
            await self._upsert_learning_objectives(course_id, result.get("sections", []), textbook_id)

            textbook.status = ProcessingStatus.INDEXED
            textbook.total_chunks = result.get("total_chunks", 0)
            textbook.total_pages_or_slides = result.get("total_pages", 0)
            textbook.curriculum_tree_json = self._build_curriculum_tree(result.get("sections", []))
            textbook.parse_error_message = None
        except Exception as exc:
            textbook.status = ProcessingStatus.FAILED
            textbook.parse_error_message = str(exc)
            raise

        await self.db.commit()
        refreshed = await self.get_textbook(textbook_id, user_id)
        return refreshed

    async def get_textbooks(
        self,
        user_id: str,
        course_id: str | None = None,
    ) -> list[Textbook]:
        result = await self.db.execute(
            self._accessible_textbook_query(user_id=user_id, course_id=course_id)
            .order_by(Textbook.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def get_textbook(self, textbook_id: str, user_id: str) -> Textbook | None:
        result = await self.db.execute(
            self._accessible_textbook_query(user_id=user_id)
            .where(Textbook.id == textbook_id)
        )
        return result.scalar_one_or_none()

    async def delete_textbook(self, textbook_id: str, user_id: str) -> bool:
        textbook = await self.get_textbook(textbook_id, user_id)
        if not textbook:
            return False

        course_role = None
        if textbook.course_id:
            course_role = await self.course_service.get_course_role(textbook.course_id, user_id)
        if textbook.owner_id != user_id and course_role not in {"lecturer", "teaching_assistant"}:
            return False

        rag = RAGService.get_instance()
        rag.delete_textbook_chunks(textbook_id)

        chunk_result = await self.db.execute(
            select(TextbookChunk).where(TextbookChunk.textbook_id == textbook_id)
        )
        for chunk in chunk_result.scalars().all():
            await self.db.delete(chunk)

        file_path = Path(textbook.file_path)
        if file_path.exists():
            file_path.unlink()

        await self.db.delete(textbook)
        await self.db.commit()
        return True

    async def get_textbook_metadata(self, textbook_id: str, user_id: str) -> dict:
        textbook = await self.get_textbook(textbook_id, user_id)
        if not textbook:
            return {}

        return {
            "title": textbook.title,
            "course_id": textbook.course_id,
            "status": textbook.status.value,
            "total_pages_or_slides": textbook.total_pages_or_slides,
            "total_chunks": textbook.total_chunks,
            "curriculum_tree": textbook.curriculum_tree_json or [],
            "chapters": [
                {
                    "chapter_number": ch.chapter_number,
                    "title": ch.title,
                    "start_page": ch.start_page,
                    "end_page": ch.end_page,
                }
                for ch in textbook.chapters
            ],
            "sections": [
                {
                    "id": section.id,
                    "title": section.section_title,
                    "section_type": section.section_type,
                    "page_from": section.page_from,
                    "page_to": section.page_to,
                    "scope_label": section.scope_label,
                    "metadata": section.metadata_json or {},
                }
                for section in textbook.sections
            ],
        }

    async def get_document_status(self, document_id: str, user_id: str) -> dict | None:
        textbook = await self.get_textbook(document_id, user_id)
        if not textbook:
            return None
        return {
            "id": textbook.id,
            "course_id": textbook.course_id,
            "status": textbook.status.value,
            "parse_error_message": textbook.parse_error_message,
            "total_pages_or_slides": textbook.total_pages_or_slides,
            "total_chunks": textbook.total_chunks,
            "updated_at": textbook.updated_at,
        }

    async def get_curriculum_tree(self, document_id: str, user_id: str) -> list[dict] | None:
        textbook = await self.get_textbook(document_id, user_id)
        if not textbook:
            return None
        if textbook.curriculum_tree_json:
            return list(textbook.curriculum_tree_json)

        sections = [
            {
                "id": section.id,
                "title": section.section_title,
                "section_type": section.section_type,
                "section_order": section.section_order,
                "chapter_number": int((section.metadata_json or {}).get("chapter_number", 0) or 0),
                "page_from": section.page_from,
                "page_to": section.page_to,
                "scope_label": section.scope_label,
                "summary": section.summary,
                "metadata": section.metadata_json,
                "parent_key": section.parent_section_id,
            }
            for section in textbook.sections
        ]
        return self._build_curriculum_tree(sections)

    async def update_curriculum_tree(
        self,
        document_id: str,
        user_id: str,
        curriculum_tree: list[dict],
    ) -> Textbook | None:
        textbook = await self.get_textbook(document_id, user_id)
        if not textbook:
            return None

        textbook.curriculum_tree_json = curriculum_tree
        await self._replace_sections_from_tree(document_id, curriculum_tree)
        await self.db.flush()
        return textbook

    def _accessible_textbook_query(self, user_id: str, course_id: str | None = None):
        membership_subquery = (
            select(CourseMembership.course_id)
            .where(CourseMembership.user_id == user_id)
        )
        query = (
            select(Textbook)
            .where(
                or_(
                    Textbook.owner_id == user_id,
                    Textbook.course_id.in_(membership_subquery),
                )
            )
            .options(
                selectinload(Textbook.chapters),
                selectinload(Textbook.sections),
                selectinload(Textbook.course),
            )
        )
        if course_id:
            query = query.where(Textbook.course_id == course_id)
        return query

    async def _find_duplicate_document(
        self,
        user_id: str,
        course_id: str | None,
        file_hash: str,
    ) -> Textbook | None:
        query = self._accessible_textbook_query(user_id=user_id, course_id=course_id).where(
            Textbook.file_hash == file_hash
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _replace_chapters(self, textbook_id: str, chapters: list[dict]) -> None:
        existing = await self.db.execute(
            select(TextbookChapter).where(TextbookChapter.textbook_id == textbook_id)
        )
        for row in existing.scalars().all():
            await self.db.delete(row)

        for chapter in chapters:
            self.db.add(
                TextbookChapter(
                    textbook_id=textbook_id,
                    chapter_number=int(chapter.get("chapter_number") or 0),
                    title=chapter.get("title") or f"Chapter {chapter.get('chapter_number', 0)}",
                    start_page=chapter.get("start_page"),
                    end_page=chapter.get("end_page"),
                    summary=chapter.get("summary"),
                    key_concepts=chapter.get("key_concepts"),
                )
            )

    async def _replace_sections(self, textbook_id: str, sections: list[dict]) -> None:
        existing = await self.db.execute(
            select(Section).where(Section.document_id == textbook_id)
        )
        for row in existing.scalars().all():
            await self.db.delete(row)
        await self.db.flush()

        key_to_id: dict[str, str] = {}
        pending = []
        for section in sections:
            section_id = str(uuid.uuid4())
            key = section.get("section_key") or section_id
            key_to_id[key] = section_id
            pending.append((section_id, section))

        for section_id, section in pending:
            parent_key = section.get("parent_key")
            self.db.add(
                Section(
                    id=section_id,
                    document_id=textbook_id,
                    parent_section_id=key_to_id.get(parent_key) if parent_key else None,
                    section_title=section.get("section_title") or "Untitled Section",
                    section_type=section.get("section_type") or "topic",
                    section_order=int(section.get("section_order") or 0),
                    page_from=section.get("page_from"),
                    page_to=section.get("page_to"),
                    scope_label=section.get("scope_label"),
                    summary=section.get("summary"),
                    metadata_json=section.get("metadata") or {},
                )
            )

    async def _replace_sections_from_tree(self, textbook_id: str, curriculum_tree: list[dict]) -> None:
        flattened: list[dict] = []

        def visit(node: dict, parent_key: str | None = None, index: int = 0):
            node_id = node.get("id") or f"tree:{len(flattened) + 1}"
            flattened.append(
                {
                    "section_key": node_id,
                    "parent_key": parent_key,
                    "section_title": node.get("title") or "Untitled Section",
                    "section_type": node.get("section_type") or "topic",
                    "section_order": int(node.get("section_order") or index),
                    "page_from": node.get("page_from"),
                    "page_to": node.get("page_to"),
                    "scope_label": node.get("scope_label"),
                    "summary": node.get("summary"),
                    "metadata": node.get("metadata") or {"chapter_number": node.get("chapter_number", 0)},
                }
            )
            for child_index, child in enumerate(node.get("children") or [], start=1):
                visit(child, parent_key=node_id, index=child_index)

        for index, node in enumerate(curriculum_tree, start=1):
            visit(node, parent_key=None, index=index)

        await self._replace_sections(textbook_id, flattened)

    async def _upsert_learning_objectives(
        self,
        course_id: str | None,
        sections: list[dict],
        textbook_id: str,
    ) -> None:
        if not course_id:
            return

        existing = await self.db.execute(
            select(LearningObjective)
            .where(LearningObjective.course_id == course_id)
        )
        existing_rows = list(existing.scalars().all())
        if existing_rows:
            existing_texts = {row.objective_text for row in existing_rows}
        else:
            existing_texts = set()

        section_rows = await self.db.execute(
            select(Section).where(Section.document_id == textbook_id)
        )
        section_by_title = {
            (section.section_title or "").strip().lower(): section.id
            for section in section_rows.scalars().all()
            if (section.section_title or "").strip()
        }

        chapter_topics: set[str] = set()
        for section in sections:
            if section.get("section_type") != "topic":
                continue
            title = (section.get("section_title") or "").strip()
            if not title:
                continue
            objective_text = f"Master the concept: {title}"
            if objective_text in existing_texts or objective_text in chapter_topics:
                continue
            chapter_topics.add(objective_text)
            self.db.add(
                LearningObjective(
                    course_id=course_id,
                    section_id=section_by_title.get(title.lower()),
                    objective_text=objective_text,
                    objective_level="topic",
                    tags_json=[section.get("scope_label")] if section.get("scope_label") else [],
                )
            )

    def _build_curriculum_tree(self, sections: list[dict]) -> list[dict]:
        nodes: dict[str, dict] = {}
        roots: list[dict] = []

        for section in sections:
            key = section.get("section_key") or section.get("id") or str(uuid.uuid4())
            nodes[key] = {
                "id": key,
                "title": section.get("section_title") or section.get("title") or "Untitled Section",
                "section_type": section.get("section_type") or "topic",
                "section_order": int(section.get("section_order", 0) or 0),
                "chapter_number": int((section.get("metadata") or {}).get("chapter_number", 0) or 0),
                "page_from": section.get("page_from"),
                "page_to": section.get("page_to"),
                "scope_label": section.get("scope_label"),
                "summary": section.get("summary"),
                "metadata": section.get("metadata"),
                "children": [],
            }

        for section in sections:
            key = section.get("section_key") or section.get("id")
            parent_key = section.get("parent_key")
            if parent_key and parent_key in nodes:
                nodes[parent_key]["children"].append(nodes[key])
            else:
                roots.append(nodes[key])

        return roots
