"""
Exam Service

Explicit MVP pipeline:
upload -> parse -> curriculum -> scope -> exam spec -> blueprint ->
scoped retrieval -> generate -> verify -> review/edit -> versioning
"""
import logging
import uuid
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.exam_planning.blueprint_service import BlueprintService, assign_chunks_to_slots
from app.services.verification.grounding_checker import GroundingChecker
from app.services.generation.llm_router import create_llm
from app.services.retrieval.retrieval_engine import RetrievalEngine
from app.core.runtime_models import BlueprintCell, ExamBlueprint, ExamSpec, GeneratedQuestion, ScopeUnit
from app.models.course import CourseMembership
from app.models.exam import (
    BloomLevel,
    BlueprintCellRecord,
    DifficultyLevel,
    EditOperation,
    Exam,
    ExamQuestion,
    ExamSpecRecord,
    ExamSpecScopeRecord,
    ExamStatus,
    ExamType,
    ExamVersion,
    QuestionType,
)
from app.repositories.document_repository import DocumentRepository
from app.schemas.exam import ExamGenerationRequest, ExamPartialRegenerateRequest
from app.services.curriculum.scope_service import CurriculumScopeService
from app.services.documents.service import DocumentService
from app.services.review.review_edit_service import ReviewEditService
from app.services.exam_planning.spec_service import ExamSpecService
from app.services.feedback.feedback_event_service import FeedbackEventService
from app.services.generation.mcq_generation_service import MCQGenerationService
from app.services.playbook.retrieval_service import PlaybookRetrievalService
from app.services.retrieval.rag_service import RAGService
from app.services.retrieval.scoped_retrieval_service import ScopedRetrievalService
from app.services.verification.mcq_verifier_service import MCQVerifierService
from app.services.verification.validator import QuestionValidator
from app.utils.bloom_levels import normalize_bloom_level

logger = logging.getLogger(__name__)


class ExamService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _serialize_dataclass(self, value):
        if value is None:
            return None
        if isinstance(value, list):
            return [self._serialize_dataclass(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._serialize_dataclass(item)
                for key, item in value.items()
            }
        if isinstance(value, (str, int, float, bool)):
            return value
        return asdict(value)

    def _scope_to_dict(self, scope_unit: ScopeUnit) -> dict:
        return {
            "scope_id": scope_unit.scope_id,
            "section_id": scope_unit.section_id,
            "scope_type": scope_unit.scope_type,
            "title": scope_unit.title,
            "chapter_number": scope_unit.chapter_number,
            "page_from": scope_unit.page_from,
            "page_to": scope_unit.page_to,
            "tags": list(scope_unit.tags or []),
        }

    def _question_snapshot(self, question: GeneratedQuestion | ExamQuestion) -> dict:
        if isinstance(question, GeneratedQuestion):
            return {
                "question_number": question.slot_number,
                "content": question.content,
                "question_type": question.question_type,
                "bloom_level": question.bloom_level,
                "correct_answer": question.correct_answer,
                "options": question.options,
                "rubric": question.rubric,
                "explanation": question.explanation,
                "source_chunks": list(question.source_chunks or []),
                "source_evidence": list(question.source_evidence or []),
                "scope_tags": list(question.scope_tags or []),
                "is_locked": bool(question.is_locked),
            }
        return {
            "question_number": question.question_number,
            "content": question.content,
            "question_type": question.question_type.value,
            "bloom_level": question.bloom_level.value,
            "correct_answer": question.correct_answer,
            "options": question.options,
            "rubric": question.rubric_json,
            "explanation": question.explanation,
            "source_chunks": list(question.source_chunks or []),
            "source_evidence": list(question.source_evidence_json or []),
            "scope_tags": list(question.scope_tags_json or []),
            "is_locked": bool(question.is_locked),
        }

    def _question_to_db(
        self,
        exam_id: str,
        exam_version_id: str,
        question: GeneratedQuestion,
        quality_by_slot: dict[int, dict],
        grounding_by_slot: dict[int, dict],
    ) -> ExamQuestion:
        normalized_bloom = BloomLevel(
            normalize_bloom_level(question.bloom_level, fallback="understand")
        )
        return ExamQuestion(
            id=str(uuid.uuid4()),
            exam_id=exam_id,
            exam_version_id=exam_version_id,
            question_number=question.slot_number,
            blueprint_cell_key=question.blueprint_cell_key or None,
            question_type=QuestionType.MCQ,
            bloom_level=normalized_bloom,
            difficulty_score=question.difficulty_score,
            content=question.content,
            options=question.options,
            correct_answer=question.correct_answer,
            rubric_json=question.rubric,
            explanation=question.explanation,
            source_chunks=question.source_chunks,
            source_evidence_json=question.source_evidence,
            scope_tags_json=question.scope_tags,
            warnings_json=question.warnings,
            verification_status=question.verification_status,
            is_human_edited=question.is_human_edited,
            is_locked=question.is_locked,
            is_validated=question.is_validated,
            validation_notes=question.validation_notes,
            quality_score_json=quality_by_slot.get(question.slot_number),
            grounding_report_json=grounding_by_slot.get(question.slot_number),
        )

    def _db_question_to_generated(self, question: ExamQuestion) -> GeneratedQuestion:
        source_evidence = list(question.source_evidence_json or [])
        source_texts = [
            (item.get("text_preview") or "")
            for item in source_evidence
            if isinstance(item, dict)
        ]
        return GeneratedQuestion(
            slot_number=question.question_number,
            blueprint_cell_key=question.blueprint_cell_key or "",
            question_type=question.question_type.value,
            bloom_level=question.bloom_level.value,
            difficulty_score=question.difficulty_score,
            content=question.content,
            options=question.options,
            correct_answer=question.correct_answer,
            rubric=question.rubric_json,
            explanation=question.explanation or "",
            source_chunks=list(question.source_chunks or []),
            source_texts=source_texts,
            source_evidence=source_evidence,
            scope_tags=list(question.scope_tags_json or []),
            warnings=list(question.warnings_json or []),
            verification_status=question.verification_status or "pending",
            is_human_edited=bool(question.is_human_edited),
            is_locked=bool(question.is_locked),
            is_validated=bool(question.is_validated),
            validation_notes=question.validation_notes or "",
        )

    def _normalize_question_id_to_slot(
        self,
        raw_id: str,
        id_to_slot: dict[str, int],
    ) -> int | None:
        if raw_id in id_to_slot:
            return id_to_slot[raw_id]
        try:
            slot = int(raw_id)
            return slot if slot > 0 else None
        except (TypeError, ValueError):
            return None

    def _enum_value(self, value) -> str:
        return value.value if hasattr(value, "value") else value

    def _ensure_mvp_exam_runtime(self, exam: Exam) -> None:
        exam_type = str(self._enum_value(exam.exam_type) or "").strip().lower()
        if exam_type != "mcq":
            raise ValueError("Legacy non-MCQ exams are outside the active MVP runtime")
        if not bool(exam.strict_scope_flag):
            raise ValueError("Legacy exams without strict_scope=true are outside the active MVP runtime")
        if str(exam.output_language or "").strip().lower() not in {"", "vi"}:
            raise ValueError("Legacy exams with non-Vietnamese output are outside the active MVP runtime")
        selected_scope = [
            item for item in (exam.selected_scope_json or [])
            if isinstance(item, dict)
        ]
        if not selected_scope or any(not str(item.get("section_id") or "").strip() for item in selected_scope):
            raise ValueError("Legacy exams without persisted section_id scope are outside the active MVP runtime")
        for question in (exam.current_version.questions if exam.current_version else []) or []:
            question_type = str(self._enum_value(question.question_type) or "").strip().lower()
            if question_type != "mcq":
                raise ValueError("Legacy non-MCQ question versions cannot be edited in the MVP runtime")

    async def _resolve_document(
        self,
        user_id: str,
        request: ExamGenerationRequest,
    ) -> tuple[str, str | None, dict]:
        document_service = DocumentService(self.db)

        if request.document_id:
            metadata = await document_service.get_document_metadata(request.document_id, user_id)
            if not metadata:
                raise ValueError("Document not found or not processed")
            course_id = request.course_id or metadata.get("course_id")
            return request.document_id, course_id, metadata

        if request.course_id:
            documents = await document_service.list_documents(user_id=user_id, course_id=request.course_id)
            processed = [
                document for document in documents
                if document.status.value in {"indexed", "processed"}
            ]
            if len(processed) == 1:
                metadata = await document_service.get_document_metadata(processed[0].id, user_id)
                return processed[0].id, request.course_id, metadata
            if not processed:
                raise ValueError("No processed documents found for course")
            raise ValueError("Course has multiple documents; provide document_id")

        raise ValueError("Document not found or not processed")

    async def _create_exam_version(
        self,
        exam: Exam,
        user_id: str,
        version_number: int,
        status: str,
        parent_version_id: str | None = None,
        change_summary: str | None = None,
    ) -> ExamVersion:
        version = ExamVersion(
            exam_id=exam.id,
            version_number=version_number,
            status=status,
            created_by=user_id,
            parent_version_id=parent_version_id,
            change_summary=change_summary,
        )
        self.db.add(version)
        await self.db.flush()
        return version

    async def _persist_exam_spec_records(
        self,
        exam: Exam,
        user_id: str,
        course_id: str | None,
        document_id: str,
        exam_spec: ExamSpec,
        blueprint: ExamBlueprint,
    ) -> None:
        spec_record = ExamSpecRecord(
            exam_id=exam.id,
            course_id=course_id,
            document_id=document_id,
            creator_user_id=user_id,
            exam_type=exam_spec.exam_type,
            question_type=exam_spec.question_type,
            time_limit_minutes=exam_spec.time_limit_minutes,
            language=exam_spec.output_language,
            instructions=exam_spec.instructions,
            normalized_instructions=exam_spec.normalized_instructions,
            strict_scope_flag=exam_spec.strict_scope_flag,
            bloom_distribution_json=exam_spec.bloom_distribution,
            question_mix_json=exam_spec.question_mix,
            formatting_preferences_json=exam_spec.formatting_preferences,
            total_questions=exam_spec.total_questions,
            selected_scope_json=self._serialize_dataclass(exam_spec.selected_scope),
            source_prompt=exam_spec.source_prompt,
            status="generated",
        )
        self.db.add(spec_record)
        await self.db.flush()

        for scope_item in exam_spec.selected_scope:
            self.db.add(
                ExamSpecScopeRecord(
                    exam_spec_id=spec_record.id,
                    section_id=scope_item.section_id,
                    scope_id=scope_item.scope_id,
                    scope_type=scope_item.scope_type,
                    title=scope_item.title,
                    chapter_number=int(scope_item.chapter_number or 0),
                    page_from=scope_item.page_from,
                    page_to=scope_item.page_to,
                    tags_json=list(scope_item.tags or []),
                )
            )

        for cell in blueprint.cells:
            self.db.add(
                BlueprintCellRecord(
                    exam_spec_id=spec_record.id,
                    section_id=cell.scope_unit.section_id,
                    cell_key=cell.cell_id,
                    scope_unit_json=self._serialize_dataclass(cell.scope_unit),
                    question_type=cell.question_type,
                    bloom_level=cell.bloom_level,
                    target_count=cell.target_count,
                    generated_count=cell.generated_count,
                    priority=cell.priority,
                    overgenerate_count=cell.overgenerate_count,
                )
            )

    async def _persist_edit_operations(
        self,
        exam_version_id: str,
        user_id: str,
        edit_requests: list[dict],
        old_questions: list[ExamQuestion],
        new_questions: list[GeneratedQuestion],
    ) -> None:
        old_by_slot = {question.question_number: question for question in old_questions}
        new_by_slot = {question.slot_number: question for question in new_questions}

        for edit in edit_requests:
            targeted_slots: set[int] = set()
            for raw_id in edit.get("question_ids", []):
                try:
                    targeted_slots.add(int(raw_id))
                except (TypeError, ValueError):
                    continue
            if edit.get("range_start") is not None and edit.get("range_end") is not None:
                for slot in range(int(edit["range_start"]), int(edit["range_end"]) + 1):
                    if slot > 0:
                        targeted_slots.add(slot)

            old_values = [
                self._question_snapshot(old_by_slot[slot])
                for slot in sorted(targeted_slots)
                if slot in old_by_slot
            ]
            new_values = [
                self._question_snapshot(new_by_slot[slot])
                for slot in sorted(targeted_slots)
                if slot in new_by_slot
            ]

            self.db.add(
                EditOperation(
                    exam_version_id=exam_version_id,
                    actor_id=user_id,
                    edit_type=edit.get("edit_type", "regenerate"),
                    target_question_id=",".join(str(slot) for slot in sorted(targeted_slots)) or None,
                    old_value={"questions": old_values} if old_values else None,
                    new_value={"questions": new_values} if new_values else None,
                    prompt_used=edit.get("edit_prompt"),
                )
            )

    def _get_llm(self):
        return create_llm(temperature=0.2)

    def _build_pipeline(
        self,
        document_id: str,
        section_by_id: dict[str, object],
    ):
        llm = self._get_llm()
        rag = RAGService.get_instance()
        vector_store = rag.get_vector_store(namespace=document_id)
        document_repository = DocumentRepository(self.db)
        scope_service = CurriculumScopeService(document_repository)
        retrieval_engine = RetrievalEngine(vector_store, db_session=self.db)
        retrieval_service = ScopedRetrievalService(
            retrieval_agent=retrieval_engine,
            repository=document_repository,
            scope_service=scope_service,
            section_by_id=section_by_id,
        )
        generation_service = MCQGenerationService(llm)
        verifier_service = MCQVerifierService(
            QuestionValidator(grounding_checker=GroundingChecker())
        )
        return scope_service, retrieval_service, generation_service, verifier_service

    def _enrich_source_evidence(
        self,
        questions: list[GeneratedQuestion],
        chunk_metadata_index: dict[str, dict],
        document_id: str,
    ) -> None:
        for question in questions:
            enriched_items: list[dict] = []
            inferred_section_id = self._infer_section_id(question.scope_tags)
            for item in question.source_evidence or []:
                if not isinstance(item, dict):
                    continue
                chunk_id = str(item.get("chunk_id") or "")
                metadata = dict(chunk_metadata_index.get(chunk_id) or {})
                enriched_item = dict(item)
                enriched_item["document_id"] = document_id
                if metadata.get("section_id") and not enriched_item.get("section_id"):
                    enriched_item["section_id"] = metadata.get("section_id")
                if inferred_section_id and not enriched_item.get("section_id"):
                    enriched_item["section_id"] = inferred_section_id
                for key in ("chapter_number", "page", "parent_heading"):
                    if metadata.get(key) is not None and enriched_item.get(key) is None:
                        enriched_item[key] = metadata.get(key)
                enriched_items.append(enriched_item)
            question.source_evidence = enriched_items

    def _select_final_questions(
        self,
        questions: list[GeneratedQuestion],
        blueprint: ExamBlueprint,
    ) -> list[GeneratedQuestion]:
        grouped: dict[str, list[GeneratedQuestion]] = {}
        for question in questions:
            grouped.setdefault(question.blueprint_cell_key, []).append(question)

        selected: list[GeneratedQuestion] = []
        for cell in blueprint.cells:
            candidates = grouped.get(cell.cell_id, [])
            candidates.sort(
                key=lambda item: (
                    not item.is_validated,
                    len(item.warnings or []),
                    item.slot_number,
                )
            )
            chosen = candidates[: cell.target_count]
            cell.generated_count = len(chosen)
            selected.extend(chosen)

        selected.sort(key=lambda item: item.slot_number)
        for index, question in enumerate(selected, start=1):
            question.slot_number = index
        blueprint.total_questions = len(selected)
        return selected

    def _quality_map(self, payload: list[dict]) -> dict[int, dict]:
        return {
            int(item["slot_number"]): item
            for item in payload
            if isinstance(item, dict) and item.get("slot_number") is not None
        }

    def _grounding_map(self, payload: list[dict]) -> dict[int, dict]:
        return {
            int(item["slot_number"]): item
            for item in payload
            if isinstance(item, dict) and item.get("slot_number") is not None
        }

    def _question_id_by_slot(self, questions: list[ExamQuestion]) -> dict[int, str]:
        return {
            int(question.question_number): question.id
            for question in questions
            if question.question_number is not None and question.id
        }

    def _playbook_scope_units(self, scope_items: list[ScopeUnit]) -> list[dict]:
        return [self._scope_to_dict(item) for item in scope_items or []]

    def _normalize_edit_requests(
        self,
        current_questions: list[ExamQuestion],
        request: ExamPartialRegenerateRequest,
    ) -> list[dict]:
        id_to_slot = {str(question.id): int(question.question_number) for question in current_questions}
        edit_requests: list[dict] = []

        for edit in request.edits:
            normalized_ids: list[str] = []
            for raw_id in edit.question_ids:
                slot = self._normalize_question_id_to_slot(raw_id, id_to_slot)
                if slot is not None:
                    normalized_ids.append(str(slot))

            range_start = edit.range_start
            range_end = edit.range_end
            if isinstance(range_start, int) and isinstance(range_end, int) and range_start > range_end:
                range_start, range_end = range_end, range_start

            edit_requests.append(
                {
                    "question_ids": normalized_ids,
                    "range_start": range_start,
                    "range_end": range_end,
                    "edit_prompt": edit.edit_prompt,
                    "edit_type": edit.edit_type,
                    "new_content": edit.new_content,
                    "new_options": [item.model_dump() for item in edit.new_options] if edit.new_options else None,
                    "new_correct_answer": edit.new_correct_answer,
                    "new_bloom_level": edit.new_bloom_level,
                }
            )

        return edit_requests

    def _infer_section_id(self, scope_tags: list[str]) -> str | None:
        for tag in scope_tags or []:
            if not isinstance(tag, str) or not tag.startswith("section:"):
                continue
            _, _, section_id = tag.partition(":")
            if section_id:
                return section_id
        return None

    def _restore_blueprint(
        self,
        exam: Exam,
        questions: list[GeneratedQuestion],
    ) -> ExamBlueprint:
        blueprint_json = dict(exam.blueprint_json or {})
        raw_cells = list(blueprint_json.get("cells") or [])
        if raw_cells:
            cells: list[BlueprintCell] = []
            for raw_cell in raw_cells:
                raw_scope = raw_cell.get("scope_unit") or {}
                cells.append(
                    BlueprintCell(
                        cell_id=raw_cell.get("cell_id") or raw_cell.get("cell_key") or "",
                        scope_unit=ScopeUnit(
                            scope_id=raw_scope.get("scope_id") or raw_scope.get("section_id") or "",
                            section_id=raw_scope.get("section_id") or self._infer_section_id(raw_scope.get("tags") or []),
                            scope_type=raw_scope.get("scope_type", "topic"),
                            title=raw_scope.get("title") or "Untitled Section",
                            chapter_number=int(raw_scope.get("chapter_number") or 0),
                            page_from=raw_scope.get("page_from"),
                            page_to=raw_scope.get("page_to"),
                            tags=list(raw_scope.get("tags") or []),
                        ),
                        question_type=raw_cell.get("question_type", "mcq"),
                        bloom_level=raw_cell.get("bloom_level", "understand"),
                        target_count=int(raw_cell.get("target_count") or 1),
                        generated_count=int(raw_cell.get("generated_count") or 0),
                        priority=int(raw_cell.get("priority") or 0),
                        overgenerate_count=int(raw_cell.get("overgenerate_count") or 1),
                    )
                )
            spec = ExamSpec(
                exam_type="mcq",
                total_questions=len(questions),
                question_type="mcq_single_answer",
            )
            return ExamBlueprint(
                title=blueprint_json.get("title") or exam.title,
                exam_spec=spec,
                total_questions=len(questions),
                cells=cells,
            )

        cells_by_key: dict[str, BlueprintCell] = {}
        for question in questions:
            section_id = self._infer_section_id(question.scope_tags)
            chapter_number = 0
            for tag in question.scope_tags:
                if isinstance(tag, str) and tag.startswith("chapter:") and tag.partition(":")[2].isdigit():
                    chapter_number = int(tag.partition(":")[2])
                    break
            cell_key = question.blueprint_cell_key or f"slot:{question.slot_number}"
            if cell_key in cells_by_key:
                continue
            cells_by_key[cell_key] = BlueprintCell(
                cell_id=cell_key,
                scope_unit=ScopeUnit(
                    scope_id=section_id or cell_key,
                    section_id=section_id,
                    scope_type="topic",
                    title=section_id or cell_key,
                    chapter_number=chapter_number,
                    tags=list(question.scope_tags or []),
                ),
                question_type="mcq",
                bloom_level=question.bloom_level,
                target_count=1,
                generated_count=1,
                priority=question.slot_number,
                overgenerate_count=1,
            )
        spec = ExamSpec(
            exam_type="mcq",
            total_questions=len(questions),
            question_type="mcq_single_answer",
        )
        return ExamBlueprint(
            title=exam.title,
            exam_spec=spec,
            total_questions=len(questions),
            cells=list(cells_by_key.values()),
        )

    async def generate_exam(
        self,
        user_id: str,
        request: ExamGenerationRequest,
    ) -> Exam:
        document_id, course_id, document_metadata = await self._resolve_document(user_id, request)
        document_repository = DocumentRepository(self.db)
        scope_service = CurriculumScopeService(document_repository)
        resolved_scope = await scope_service.resolve_scope(
            document_id=document_id,
            requested_scope=[item.model_dump() for item in request.scope],
            requested_chapters=list(request.chapters or []),
        )
        if not resolved_scope.selected_section_ids:
            raise ValueError("Document must be reprocessed to persist curriculum sections before MVP generation")
        spec_service = ExamSpecService()
        exam_spec = spec_service.build_exam_spec(
            request=request,
            course_id=course_id,
            document_id=document_id,
            resolved_scope=resolved_scope,
        )

        exam = Exam(
            id=str(uuid.uuid4()),
            owner_id=user_id,
            course_id=course_id,
            textbook_id=document_id,
            title=f"Exam - {document_metadata.get('title', 'Untitled')}",
            exam_type=ExamType.MCQ,
            difficulty=DifficultyLevel.CUSTOM,
            status=ExamStatus.GENERATING,
            chapters=list(resolved_scope.chapter_numbers),
            config=request.to_mvp_runtime_payload(),
            instructions=exam_spec.instructions,
            output_language=exam_spec.output_language,
            strict_scope_flag=True,
            selected_scope_json=[self._scope_to_dict(item) for item in exam_spec.selected_scope],
            edit_history_json=[],
        )
        self.db.add(exam)
        await self.db.flush()

        try:
            blueprint_service = BlueprintService()
            blueprint, _ = await blueprint_service.create_blueprint(
                prompt=exam_spec.source_prompt,
                exam_type="mcq",
                difficulty="custom",
                chapters=list(resolved_scope.chapter_numbers),
                question_distribution=spec_service.build_question_distribution(exam_spec.total_questions),
                gradually_increasing=False,
                constraints={
                    "strict_scope": True,
                    "strict_grounding": True,
                    "allow_applied_questions": False,
                    "max_concurrency": 1,
                    "bloom_levels": list(exam_spec.bloom_distribution) or ["remember", "understand", "apply", "analyze"],
                },
                document_metadata=document_metadata,
                scope=[self._scope_to_dict(item) for item in exam_spec.selected_scope],
                time_limit_minutes=exam_spec.time_limit_minutes,
                output_language=exam_spec.output_language,
                instructions=exam_spec.normalized_instructions,
                bloom_distribution=exam_spec.bloom_distribution,
                formatting_preferences=exam_spec.formatting_preferences,
            )

            _, retrieval_service, generation_service, verifier_service = self._build_pipeline(
                document_id=document_id,
                section_by_id=resolved_scope.section_by_id,
            )
            playbook_service = PlaybookRetrievalService(self.db)
            retrieved_contexts, chunk_metadata_index, retrieval_stats = await retrieval_service.retrieve_for_blueprint(
                blueprint=blueprint,
                document_id=document_id,
                strict_scope=True,
            )
            chunk_assignments = await assign_chunks_to_slots(blueprint, retrieved_contexts)
            if not chunk_assignments:
                raise ValueError("No scoped evidence available for the selected curriculum units")

            generation_playbook = await playbook_service.retrieve(
                stage="generation",
                language=exam_spec.output_language,
                question_type=exam_spec.question_type,
                scope_units=self._playbook_scope_units(exam_spec.selected_scope),
            )
            generated_questions = await generation_service.generate(
                chunk_assignments=chunk_assignments,
                strict_scope=True,
                playbook_lines=generation_playbook.as_prompt_lines(),
            )
            self._enrich_source_evidence(generated_questions, chunk_metadata_index, document_id)
            verification_playbook = await playbook_service.retrieve(
                stage="verification",
                language=exam_spec.output_language,
                question_type=exam_spec.question_type,
                scope_units=self._playbook_scope_units(exam_spec.selected_scope),
            )
            verified_questions, _, _, _, _ = await verifier_service.verify(
                questions=generated_questions,
                blueprint=blueprint,
                resolved_scope=resolved_scope,
                playbook_lines=verification_playbook.as_prompt_lines(),
            )
            final_questions = self._select_final_questions(verified_questions, blueprint)
            final_questions, validation_summary, quality_scores, grounding_reports, duplicate_groups = await verifier_service.verify(
                questions=final_questions,
                blueprint=blueprint,
                resolved_scope=resolved_scope,
                playbook_lines=verification_playbook.as_prompt_lines(),
            )

            version = await self._create_exam_version(
                exam=exam,
                user_id=user_id,
                version_number=1,
                status="generated",
                change_summary="Initial generation",
            )
            quality_by_slot = self._quality_map(quality_scores)
            grounding_by_slot = self._grounding_map(grounding_reports)
            persisted_questions: list[ExamQuestion] = []
            for question in final_questions:
                db_question = self._question_to_db(
                    exam_id=exam.id,
                    exam_version_id=version.id,
                    question=question,
                    quality_by_slot=quality_by_slot,
                    grounding_by_slot=grounding_by_slot,
                )
                self.db.add(db_question)
                persisted_questions.append(db_question)
            await self.db.flush()

            feedback_service = FeedbackEventService(self.db)
            feedback_service.queue_retrieval_summary(
                exam_id=exam.id,
                exam_version_id=version.id,
                actor_id=user_id,
                payload={
                    **retrieval_stats,
                    "selected_scope_units": len(exam_spec.selected_scope or []),
                    "selected_section_ids": list(exam_spec.selected_section_ids or []),
                    "retrieved_contexts": len(retrieved_contexts),
                    "chunk_assignments": len(chunk_assignments),
                },
            )
            feedback_service.queue_verifier_events(
                exam_id=exam.id,
                exam_version_id=version.id,
                actor_id=user_id,
                questions=persisted_questions,
            )
            if generation_playbook.mode != "off":
                feedback_service.queue_playbook_shadow_event(
                    exam_id=exam.id,
                    exam_version_id=version.id,
                    actor_id=user_id,
                    stage="generation",
                    payload={
                        **generation_playbook.as_event_payload(),
                        "question_count": len(persisted_questions),
                    },
                )
            if verification_playbook.mode != "off":
                feedback_service.queue_playbook_shadow_event(
                    exam_id=exam.id,
                    exam_version_id=version.id,
                    actor_id=user_id,
                    stage="verification",
                    payload={
                        **verification_playbook.as_event_payload(),
                        "question_count": len(persisted_questions),
                    },
                )

            await self._persist_exam_spec_records(
                exam=exam,
                user_id=user_id,
                course_id=course_id,
                document_id=document_id,
                exam_spec=exam_spec,
                blueprint=blueprint,
            )

            exam.current_version_id = version.id
            exam.status = ExamStatus.GENERATED
            exam.total_questions = len(final_questions)
            exam.exam_spec_json = self._serialize_dataclass(exam_spec)
            exam.blueprint_json = self._serialize_dataclass(blueprint)
            exam.quality_score = validation_summary.get("pass_rate", 0.0) * 100
            exam.quality_scores_json = quality_scores or None
            exam.grounding_reports_json = grounding_reports or None
            exam.duplicate_groups_json = duplicate_groups or None
            exam.provider_logs_json = None
            exam.edit_impact_level = None
        except Exception as exc:
            exam.status = ExamStatus.FAILED
            logger.error("Exam generation failed: %s", exc)
            raise

        return await self.get_exam(exam.id, user_id)

    async def partial_regenerate(
        self,
        user_id: str,
        request: ExamPartialRegenerateRequest,
    ) -> Exam:
        exam = await self.get_exam(request.exam_id, user_id)
        if not exam:
            raise ValueError("Exam not found")
        self._ensure_mvp_exam_runtime(exam)
        if not exam.current_version:
            raise ValueError("Exam has no current version")

        current_questions = list(exam.current_version.questions or [])
        if not current_questions:
            raise ValueError("Exam has no questions to edit")

        edit_requests = self._normalize_edit_requests(current_questions, request)
        existing_generated = [self._db_question_to_generated(question) for question in current_questions]
        original_by_slot = {question.slot_number: question for question in existing_generated}

        edit_service = ReviewEditService()
        question_map, regenerate_targets = edit_service.apply_edits(
            existing_questions=existing_generated,
            edit_requests=edit_requests,
        )

        document_repository = DocumentRepository(self.db)
        scope_service = CurriculumScopeService(document_repository)
        resolved_scope = await scope_service.resolve_scope(
            document_id=exam.textbook_id,
            requested_scope=list(exam.selected_scope_json or []),
            requested_chapters=list(exam.chapters or []),
        )
        if not resolved_scope.selected_section_ids:
            raise ValueError("Document must have persisted curriculum sections before MVP review/regeneration")
        blueprint = self._restore_blueprint(exam, list(question_map.values()) or existing_generated)
        _, retrieval_service, generation_service, verifier_service = self._build_pipeline(
            document_id=exam.textbook_id,
            section_by_id=resolved_scope.section_by_id,
        )
        playbook_service = PlaybookRetrievalService(self.db)
        review_playbook = await playbook_service.retrieve(
            stage="review",
            language=exam.output_language,
            question_type="mcq_single_answer",
            scope_units=list(exam.selected_scope_json or []),
        )

        chunk_metadata_index: dict[str, dict] = {}
        retrieval_summaries: list[dict] = []
        for slot_number, edit_prompt in sorted(regenerate_targets):
            current_question = question_map.get(slot_number)
            original_question = original_by_slot.get(slot_number)
            if current_question is None or original_question is None:
                continue
            if current_question.is_locked:
                continue

            query = f"{original_question.content}\n{original_question.bloom_level}\nmcq"
            context, metadata_index, retrieval_stats = await retrieval_service.retrieve_for_single_question(
                query=query,
                document_id=exam.textbook_id,
                scope_tags=list(current_question.scope_tags or original_question.scope_tags or []),
                strict_scope=True,
            )
            chunk_metadata_index.update(metadata_index)
            retrieval_summaries.append(
                {
                    "slot_number": slot_number,
                    "query": query,
                    **retrieval_stats,
                }
            )
            regenerated = await generation_service.regenerate_question(
                original_question=original_question,
                context=context,
                edit_prompt=edit_prompt,
                playbook_lines=review_playbook.as_prompt_lines(),
            )
            regenerated.is_locked = current_question.is_locked
            regenerated.scope_tags = list(current_question.scope_tags or original_question.scope_tags or [])
            regenerated.blueprint_cell_key = original_question.blueprint_cell_key
            question_map[slot_number] = regenerated

        final_questions = edit_service.renumber(question_map)
        self._enrich_source_evidence(final_questions, chunk_metadata_index, exam.textbook_id)
        verification_playbook = await playbook_service.retrieve(
            stage="verification",
            language=exam.output_language,
            question_type="mcq_single_answer",
            scope_units=list(exam.selected_scope_json or []),
        )
        final_questions, validation_summary, quality_scores, grounding_reports, duplicate_groups = await verifier_service.verify(
            questions=final_questions,
            blueprint=blueprint,
            resolved_scope=resolved_scope,
            playbook_lines=verification_playbook.as_prompt_lines(),
        )

        new_version = await self._create_exam_version(
            exam=exam,
            user_id=user_id,
            version_number=(exam.current_version.version_number or 0) + 1,
            status="generated",
            parent_version_id=exam.current_version.id,
            change_summary="Review/edit update",
        )
        quality_by_slot = self._quality_map(quality_scores)
        grounding_by_slot = self._grounding_map(grounding_reports)
        persisted_questions: list[ExamQuestion] = []
        for question in final_questions:
            db_question = self._question_to_db(
                exam_id=exam.id,
                exam_version_id=new_version.id,
                question=question,
                quality_by_slot=quality_by_slot,
                grounding_by_slot=grounding_by_slot,
            )
            self.db.add(db_question)
            persisted_questions.append(db_question)
        await self.db.flush()

        await self._persist_edit_operations(
            exam_version_id=new_version.id,
            user_id=user_id,
            edit_requests=edit_requests,
            old_questions=current_questions,
            new_questions=final_questions,
        )
        feedback_service = FeedbackEventService(self.db)
        feedback_service.queue_retrieval_summary(
            exam_id=exam.id,
            exam_version_id=new_version.id,
            actor_id=user_id,
            payload={
                "regenerated_slots": sorted(slot for slot, _ in regenerate_targets),
                "retrieval_runs": retrieval_summaries,
                "edited_question_count": len(final_questions),
            },
        )
        feedback_service.queue_edit_events(
            exam_id=exam.id,
            exam_version_id=new_version.id,
            parent_version_id=exam.current_version.id,
            actor_id=user_id,
            edit_requests=edit_requests,
            question_id_by_slot=self._question_id_by_slot(persisted_questions),
        )
        feedback_service.queue_verifier_events(
            exam_id=exam.id,
            exam_version_id=new_version.id,
            actor_id=user_id,
            questions=persisted_questions,
        )
        if review_playbook.mode != "off":
            feedback_service.queue_playbook_shadow_event(
                exam_id=exam.id,
                exam_version_id=new_version.id,
                actor_id=user_id,
                stage="review",
                payload={
                    **review_playbook.as_event_payload(),
                    "regenerated_slots": sorted(slot for slot, _ in regenerate_targets),
                },
            )
        if verification_playbook.mode != "off":
            feedback_service.queue_playbook_shadow_event(
                exam_id=exam.id,
                exam_version_id=new_version.id,
                actor_id=user_id,
                stage="verification",
                payload={
                    **verification_playbook.as_event_payload(),
                    "question_count": len(persisted_questions),
                },
            )

        history = list(exam.edit_history_json or [])
        history.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "request": request.model_dump(),
                "parent_version_id": exam.current_version.id,
                "new_version_id": new_version.id,
            }
        )
        exam.edit_history_json = history
        exam.current_version_id = new_version.id
        exam.status = ExamStatus.GENERATED
        exam.total_questions = len(final_questions)
        exam.quality_score = validation_summary.get("pass_rate", 0.0) * 100
        exam.quality_scores_json = quality_scores or None
        exam.grounding_reports_json = grounding_reports or None
        exam.duplicate_groups_json = duplicate_groups or None

        return await self.get_exam(exam.id, user_id)

    def _exam_query(self, user_id: str, include_versions: bool = True):
        membership_subquery = (
            select(CourseMembership.course_id)
            .where(CourseMembership.user_id == user_id)
        )
        options = [
            selectinload(Exam.exam_spec_record).selectinload(ExamSpecRecord.scopes),
            selectinload(Exam.exam_spec_record).selectinload(ExamSpecRecord.blueprint_cells),
            selectinload(Exam.feedback_events),
            selectinload(Exam.current_version).selectinload(ExamVersion.questions),
            selectinload(Exam.current_version).selectinload(ExamVersion.edit_operations),
            selectinload(Exam.current_version).selectinload(ExamVersion.feedback_events),
        ]
        if include_versions:
            options.extend(
                [
                    selectinload(Exam.versions).selectinload(ExamVersion.questions),
                    selectinload(Exam.versions).selectinload(ExamVersion.edit_operations),
                    selectinload(Exam.versions).selectinload(ExamVersion.feedback_events),
                ]
            )
        return (
            select(Exam)
            .where(
                or_(
                    Exam.owner_id == user_id,
                    Exam.course_id.in_(membership_subquery),
                )
            )
            .options(*options)
        )

    async def get_exam(self, exam_id: str, user_id: str) -> Exam | None:
        result = await self.db.execute(
            self._exam_query(user_id=user_id, include_versions=True)
            .where(Exam.id == exam_id)
        )
        return result.scalar_one_or_none()

    async def get_exams(self, user_id: str) -> list[Exam]:
        result = await self.db.execute(
            self._exam_query(user_id=user_id, include_versions=False)
            .order_by(Exam.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def delete_exam(self, exam_id: str, user_id: str) -> bool:
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            return False
        await self.db.delete(exam)
        return True

    async def publish_exam(self, exam_id: str, user_id: str) -> Exam:
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            raise ValueError("Exam not found")
        self._ensure_mvp_exam_runtime(exam)
        if not exam.current_version:
            raise ValueError("Exam has no current version")

        questions = list(exam.current_version.questions or [])
        if not questions:
            raise ValueError("Exam has no questions to publish")

        invalid_questions = [
            question for question in questions
            if not question.source_evidence_json
            or (question.verification_status or "").lower() == "failed"
        ]
        if invalid_questions:
            raise ValueError("Exam still has unverified questions or missing evidence")

        exam.status = ExamStatus.PUBLISHED
        exam.published_at = datetime.utcnow()
        exam.current_version.status = "published"
        FeedbackEventService(self.db).queue_publish_event(
            exam_id=exam.id,
            exam_version_id=exam.current_version.id,
            actor_id=user_id,
            payload={
                "published_at": exam.published_at.isoformat(),
                "question_count": len(questions),
                "version_number": exam.current_version.version_number,
            },
        )
        return exam

