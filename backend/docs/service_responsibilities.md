# Service Responsibilities

## Documents

- [service.py](e:/Đồ án/Project/backend/app/services/documents/service.py): upload, dedupe, persistence, deletion
- [processor.py](e:/Đồ án/Project/backend/app/services/documents/processor.py): PDF parsing, chunking, section derivation

## Curriculum

- [scope_service.py](e:/Đồ án/Project/backend/app/services/curriculum/scope_service.py): resolve requested scope against persisted sections

## Retrieval

- [retrieval_engine.py](e:/Đồ án/Project/backend/app/services/retrieval/retrieval_engine.py): vector + BM25 retrieval
- [scoped_retrieval_service.py](e:/Đồ án/Project/backend/app/services/retrieval/scoped_retrieval_service.py): section-aware filtering and retrieval stats
- [rag_service.py](e:/Đồ án/Project/backend/app/services/retrieval/rag_service.py): embedding/vector store setup

## Exam Planning

- [spec_service.py](e:/Đồ án/Project/backend/app/services/exam_planning/spec_service.py): request normalization into exam spec
- [blueprint_service.py](e:/Đồ án/Project/backend/app/services/exam_planning/blueprint_service.py): cells, slots, and chunk assignment

## Generation

- [llm_router.py](e:/Đồ án/Project/backend/app/services/generation/llm_router.py): provider selection
- [llm_backend.py](e:/Đồ án/Project/backend/app/services/generation/llm_backend.py): instrumented model wrapper
- [question_generator.py](e:/Đồ án/Project/backend/app/services/generation/question_generator.py): prompt assembly and JSON normalization
- [mcq_generation_service.py](e:/Đồ án/Project/backend/app/services/generation/mcq_generation_service.py): MCQ-only orchestration

## Verification

- [validator.py](e:/Đồ án/Project/backend/app/services/verification/validator.py): rule-based question validation
- [grounding_checker.py](e:/Đồ án/Project/backend/app/services/verification/grounding_checker.py): evidence overlap and answer support heuristics
- [mcq_verifier_service.py](e:/Đồ án/Project/backend/app/services/verification/mcq_verifier_service.py): aggregate verification results

## Review

- [review_edit_service.py](e:/Đồ án/Project/backend/app/services/review/review_edit_service.py): normalize edits, regenerate targets, renumbering

## Exams

- [service.py](e:/Đồ án/Project/backend/app/services/exams/service.py): end-to-end orchestration, version persistence, publish flow

## Feedback And Analytics

- [feedback_event_service.py](e:/Đồ án/Project/backend/app/services/feedback/feedback_event_service.py): structured event logging
- [store_service.py](e:/Đồ án/Project/backend/app/services/feedback/store_service.py): feedback store queries and summaries
- [question_quality.py](e:/Đồ án/Project/backend/app/services/analytics/question_quality.py): quality/error categorization
- [quality_summary_service.py](e:/Đồ án/Project/backend/app/services/analytics/quality_summary_service.py): dashboard-style quality summaries

## Playbook

- [store_service.py](e:/Đồ án/Project/backend/app/services/playbook/store_service.py): bullet persistence and listing
- [retrieval_service.py](e:/Đồ án/Project/backend/app/services/playbook/retrieval_service.py): stage-aware playbook retrieval
- [reflection_service.py](e:/Đồ án/Project/backend/app/services/playbook/reflection_service.py): candidate bullet generation
- [warmup_service.py](e:/Đồ án/Project/backend/app/services/playbook/warmup_service.py): warmup export assembly
