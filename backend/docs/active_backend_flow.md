# Active Backend Flow

## Startup

- App entrypoint: [main.py](e:/Đồ án/Project/backend/app/main.py)
- Mounted routers:
  - [auth.py](e:/Đồ án/Project/backend/app/api/routers/auth.py)
  - [courses.py](e:/Đồ án/Project/backend/app/api/routers/courses.py)
  - [documents.py](e:/Đồ án/Project/backend/app/api/routers/documents.py)
  - [generation.py](e:/Đồ án/Project/backend/app/api/routers/generation.py)
  - [exams.py](e:/Đồ án/Project/backend/app/api/routers/exams.py)
  - [playbook.py](e:/Đồ án/Project/backend/app/api/routers/playbook.py)

## Document Pipeline

1. Upload enters [documents router](e:/Đồ án/Project/backend/app/api/routers/documents.py).
2. [DocumentService.upload_document](e:/Đồ án/Project/backend/app/services/documents/service.py) validates the file and course access, stores the PDF, and creates the document row.
3. [DocumentProcessor.process_document](e:/Đồ án/Project/backend/app/services/documents/processor.py) partitions the PDF, chunks content, derives sections, and attaches `section_id` to chunks.
4. [RAGService](e:/Đồ án/Project/backend/app/services/retrieval/rag_service.py) stores retrieval-ready vector data while chunk records also stay in SQL for deterministic/BM25 fallback.
5. Document chapters, sections, curriculum tree, and learning objectives are persisted.

## Exam Generation Pipeline

1. Generate request enters [generation router](e:/Đồ án/Project/backend/app/api/routers/generation.py).
2. [ExamService.generate_exam](e:/Đồ án/Project/backend/app/services/exams/service.py) resolves the document and selected scope.
3. [CurriculumScopeService](e:/Đồ án/Project/backend/app/services/curriculum/scope_service.py) hardens scope selection to persisted sections.
4. [ExamSpecService](e:/Đồ án/Project/backend/app/services/exam_planning/spec_service.py) normalizes the contract and runtime payload.
5. [BlueprintService](e:/Đồ án/Project/backend/app/services/exam_planning/blueprint_service.py) builds cells and slots before any LLM generation.
6. [ScopedRetrievalService](e:/Đồ án/Project/backend/app/services/retrieval/scoped_retrieval_service.py) calls the [RetrievalEngine](e:/Đồ án/Project/backend/app/services/retrieval/retrieval_engine.py) and filters evidence back down to the selected section IDs.
7. [MCQGenerationService](e:/Đồ án/Project/backend/app/services/generation/mcq_generation_service.py) calls the [QuestionGeneratorService](e:/Đồ án/Project/backend/app/services/generation/question_generator.py) through [llm_router.py](e:/Đồ án/Project/backend/app/services/generation/llm_router.py).
8. [MCQVerifierService](e:/Đồ án/Project/backend/app/services/verification/mcq_verifier_service.py) runs structural checks and grounding checks via [QuestionValidator](e:/Đồ án/Project/backend/app/services/verification/validator.py) and [grounding_checker.py](e:/Đồ án/Project/backend/app/services/verification/grounding_checker.py).
9. [ExamService](e:/Đồ án/Project/backend/app/services/exams/service.py) selects final questions, persists the version, and records feedback events.

## Review And Regenerate

1. Review and partial regenerate requests enter [generation router](e:/Đồ án/Project/backend/app/api/routers/generation.py).
2. [ReviewEditService](e:/Đồ án/Project/backend/app/services/review/review_edit_service.py) normalizes edit instructions and determines which slots must regenerate.
3. The same scoped retrieval and generation path runs again for only the affected slots.
4. A new exam version is persisted and linked as current.

## Feedback And Playbook

- [FeedbackEventService](e:/Đồ án/Project/backend/app/services/feedback/feedback_event_service.py) writes structured workflow events.
- [store_service.py](e:/Đồ án/Project/backend/app/services/feedback/store_service.py) exposes queryable feedback views for UI and analytics.
- [PlaybookRetrievalService](e:/Đồ án/Project/backend/app/services/playbook/retrieval_service.py) supports `off`, `shadow`, and `limited` retrieval modes.
- [ReflectionCandidateService](e:/Đồ án/Project/backend/app/services/playbook/reflection_service.py) builds candidate bullets from feedback patterns.
- [WarmupExportService](e:/Đồ án/Project/backend/app/services/playbook/warmup_service.py) exports exam/question/feedback datasets for ACE warmup.
