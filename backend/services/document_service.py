"""
Document service for the active MVP runtime.

The persistence layer still uses the existing textbook tables, but the
production-facing service is document-first:
- upload PDF
- parse and persist sections/chunks
- expose curriculum tree
- delete vectors and source file when removing a document
"""
from __future__ import annotations

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
from models.document import (
    DocumentChapterRecord,
    DocumentChunkRecord,
    DocumentProcessingStatus,
    DocumentRecord,
)
from services.course_service import CourseService
from services.rag_service import RAGService


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.course_service = CourseService(db)

    async def upload_document(
        self,
        user_id: str,
        title: str,
        file_name: str,
        file_content: bytes,
        file_type: str,
        course_id: str | None = None,
        language: str = "vi",
    ) -> DocumentRecord:
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

        document_id = str(uuid.uuid4())
        upload_dir = Path(settings.UPLOAD_DIR).resolve() / user_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(file_name).suffix
        file_path = upload_dir / f"{document_id}{ext}"
        file_path.write_bytes(file_content)

        document = DocumentRecord(
            id=document_id,
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
            status=DocumentProcessingStatus.PROCESSING,
            curriculum_tree_json=[],
        )
        self.db.add(document)
        await self.db.flush()

        try:
            rag = RAGService.get_instance()
            vector_store = rag.get_vector_store(namespace=document_id)
            processor = DocumentProcessorAgent(vector_store=vector_store, db_session=self.db)
            result = await processor.process_document(
                file_path=str(file_path),
                document_id=document_id,
            )

            await self._replace_chapters(document_id, result.get("chapters", []))
            await self._replace_sections(document_id, result.get("sections", []))
            await self._upsert_learning_objectives(
                course_id=course_id,
                sections=result.get("sections", []),
                document_id=document_id,
            )

            document.status = DocumentProcessingStatus.PROCESSED
            document.total_chunks = result.get("total_chunks", 0)
            document.total_pages_or_slides = result.get("total_pages", 0)
            document.curriculum_tree_json = self._build_curriculum_tree(result.get("sections", []))
            document.parse_error_message = None
        except Exception as exc:
            document.status = DocumentProcessingStatus.FAILED
            document.parse_error_message = str(exc)
            raise

        await self.db.commit()
        refreshed = await self.get_document(document_id, user_id)
        return refreshed

    async def list_documents(
        self,
        user_id: str,
        course_id: str | None = None,
    ) -> list[DocumentRecord]:
        result = await self.db.execute(
            self._accessible_document_query(user_id=user_id, course_id=course_id)
            .order_by(DocumentRecord.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def get_document(self, document_id: str, user_id: str) -> DocumentRecord | None:
        result = await self.db.execute(
            self._accessible_document_query(user_id=user_id)
            .where(DocumentRecord.id == document_id)
        )
        return result.scalar_one_or_none()

    async def delete_document(self, document_id: str, user_id: str) -> bool:
        document = await self.get_document(document_id, user_id)
        if not document:
            return False

        course_role = None
        if document.course_id:
            course_role = await self.course_service.get_course_role(document.course_id, user_id)
        if document.owner_id != user_id and course_role not in {"lecturer", "teaching_assistant"}:
            return False

        rag = RAGService.get_instance()
        rag.delete_document_chunks(document_id)

        chunk_result = await self.db.execute(
            select(DocumentChunkRecord).where(DocumentChunkRecord.textbook_id == document_id)
        )
        for chunk in chunk_result.scalars().all():
            await self.db.delete(chunk)

        file_path = Path(document.file_path)
        if file_path.exists():
            file_path.unlink()

        await self.db.delete(document)
        await self.db.commit()
        return True

    async def get_document_metadata(self, document_id: str, user_id: str) -> dict:
        document = await self.get_document(document_id, user_id)
        if not document:
            return {}

        return {
            "title": document.title,
            "course_id": document.course_id,
            "status": document.status.value,
            "total_pages_or_slides": document.total_pages_or_slides,
            "total_chunks": document.total_chunks,
            "curriculum_tree": document.curriculum_tree_json or [],
            "chapters": [
                {
                    "chapter_number": chapter.chapter_number,
                    "title": chapter.title,
                    "start_page": chapter.start_page,
                    "end_page": chapter.end_page,
                }
                for chapter in document.chapters
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
                for section in document.sections
            ],
        }

    async def get_document_status(self, document_id: str, user_id: str) -> dict | None:
        document = await self.get_document(document_id, user_id)
        if not document:
            return None
        return {
            "id": document.id,
            "course_id": document.course_id,
            "status": document.status.value,
            "parse_error_message": document.parse_error_message,
            "total_pages_or_slides": document.total_pages_or_slides,
            "total_chunks": document.total_chunks,
            "updated_at": document.updated_at,
        }

    async def get_curriculum_tree(self, document_id: str, user_id: str) -> list[dict] | None:
        document = await self.get_document(document_id, user_id)
        if not document:
            return None
        if document.curriculum_tree_json:
            return list(document.curriculum_tree_json)

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
            for section in document.sections
        ]
        return self._build_curriculum_tree(sections)

    async def update_curriculum_tree(
        self,
        document_id: str,
        user_id: str,
        curriculum_tree: list[dict],
    ) -> DocumentRecord | None:
        document = await self.get_document(document_id, user_id)
        if not document:
            return None

        document.curriculum_tree_json = curriculum_tree
        await self._replace_sections_from_tree(document_id, curriculum_tree)
        await self.db.flush()
        return document

    def _accessible_document_query(self, user_id: str, course_id: str | None = None):
        membership_subquery = select(CourseMembership.course_id).where(
            CourseMembership.user_id == user_id
        )
        query = (
            select(DocumentRecord)
            .where(
                or_(
                    DocumentRecord.owner_id == user_id,
                    DocumentRecord.course_id.in_(membership_subquery),
                )
            )
            .options(
                selectinload(DocumentRecord.chapters),
                selectinload(DocumentRecord.sections),
                selectinload(DocumentRecord.course),
            )
        )
        if course_id:
            query = query.where(DocumentRecord.course_id == course_id)
        return query

    async def _find_duplicate_document(
        self,
        user_id: str,
        course_id: str | None,
        file_hash: str,
    ) -> DocumentRecord | None:
        query = self._accessible_document_query(user_id=user_id, course_id=course_id).where(
            DocumentRecord.file_hash == file_hash
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _replace_chapters(self, document_id: str, chapters: list[dict]) -> None:
        existing = await self.db.execute(
            select(DocumentChapterRecord).where(DocumentChapterRecord.textbook_id == document_id)
        )
        for row in existing.scalars().all():
            await self.db.delete(row)

        for chapter in chapters:
            self.db.add(
                DocumentChapterRecord(
                    textbook_id=document_id,
                    chapter_number=int(chapter.get("chapter_number") or 0),
                    title=chapter.get("title") or f"Chapter {chapter.get('chapter_number', 0)}",
                    start_page=chapter.get("start_page"),
                    end_page=chapter.get("end_page"),
                    summary=chapter.get("summary"),
                    key_concepts=chapter.get("key_concepts"),
                )
            )

    async def _replace_sections(self, document_id: str, sections: list[dict]) -> None:
        existing = await self.db.execute(select(Section).where(Section.document_id == document_id))
        for row in existing.scalars().all():
            await self.db.delete(row)
        await self.db.flush()

        key_to_id: dict[str, str] = {}
        pending: list[tuple[str, dict]] = []
        for section in sections:
            key = section.get("section_key") or section.get("id") or str(uuid.uuid4())
            section_id = self._compose_section_id(document_id, key)
            key_to_id[key] = section_id
            key_to_id[section_id] = section_id
            pending.append((section_id, section))

        for section_id, section in pending:
            parent_key = section.get("parent_section_id") or section.get("parent_key")
            self.db.add(
                Section(
                    id=section_id,
                    document_id=document_id,
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

    async def _replace_sections_from_tree(
        self,
        document_id: str,
        curriculum_tree: list[dict],
    ) -> None:
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

        await self._replace_sections(document_id, flattened)

    async def _upsert_learning_objectives(
        self,
        course_id: str | None,
        sections: list[dict],
        document_id: str,
    ) -> None:
        if not course_id:
            return

        existing = await self.db.execute(
            select(LearningObjective).where(LearningObjective.course_id == course_id)
        )
        existing_rows = list(existing.scalars().all())
        existing_texts = {row.objective_text for row in existing_rows} if existing_rows else set()

        section_rows = await self.db.execute(select(Section).where(Section.document_id == document_id))
        section_by_title = {
            (section.section_title or "").strip().lower(): section.id
            for section in section_rows.scalars().all()
            if (section.section_title or "").strip()
        }

        topic_objectives: set[str] = set()
        for section in sections:
            if section.get("section_type") != "topic":
                continue
            title = (section.get("section_title") or "").strip()
            if not title:
                continue
            objective_text = f"Master the concept: {title}"
            if objective_text in existing_texts or objective_text in topic_objectives:
                continue
            topic_objectives.add(objective_text)
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
            key = (
                section.get("section_id")
                or section.get("section_key")
                or section.get("id")
                or str(uuid.uuid4())
            )
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
            key = section.get("section_id") or section.get("section_key") or section.get("id")
            parent_key = section.get("parent_section_id") or section.get("parent_key")
            if parent_key and parent_key in nodes:
                nodes[parent_key]["children"].append(nodes[key])
            else:
                roots.append(nodes[key])

        return roots

    def _compose_section_id(self, document_id: str, section_key: str) -> str:
        normalized_key = str(section_key or "").strip()
        prefix = f"{document_id}:"
        if normalized_key.startswith(prefix):
            return normalized_key
        return f"{prefix}{normalized_key}"
