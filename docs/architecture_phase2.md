# Phase 2 Architecture

## Active product boundary

- Subject: Physics only
- Output language: Vietnamese only
- Input document: PDF only
- Question type: single-answer MCQ only
- Scope model: chapter / lesson / topic / subtopic
- Review flow: verify -> edit / regenerate -> version -> publish

## Critical path

1. Upload a PDF through `/api/v1/documents`.
2. Parse the PDF and derive curriculum sections.
3. Chunk content inside each section and persist `chunk.section_id`.
4. Build the curriculum tree shown in the UI.
5. Resolve user scope into concrete section IDs.
6. Convert the teacher request into an `ExamSpec`.
7. Convert the spec into a `Blueprint`.
8. Retrieve evidence inside the selected section IDs.
9. Generate MCQ questions only.
10. Verify scope, evidence, answerability, and duplication.
11. Review, edit, regenerate, and save a new version.
12. Publish only after all questions still have valid evidence and no failed verifier status.

## Domain model

Active concepts:

- users
- courses
- documents
- sections
- chunks
- exam_specs
- exam_spec_scopes
- blueprint_cells
- exam_versions
- question_items (`exam_questions`)
- edit_operations
- feedback_events

Compatibility note:

- The database still uses historical `textbooks` / `textbook_chunks` tables.
- Active services and repositories expose the document-first domain through aliases such as `DocumentRecord` and `DocumentChunkRecord`.
- This compatibility layer is intentional until a dedicated persistence rename is scheduled.

## Phase 2 additions

- Structured `feedback_events` for retrieval summaries, verifier warnings/failures, regenerate actions, human edits, and publish actions.
- Minimal eval dataset and runner under `backend/evals/`.
- Stronger backend regression checks under `backend/tests/phase2_hardening_checks.py`.
- UI cleanup focused on `documents -> generate -> review`.

## Explicitly out of scope

- ACE core
- student guidance
- essay generation
- mixed question types
- DOCX / PPTX ingestion
- multi-subject support
- unrestricted multi-agent orchestration
