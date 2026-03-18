# Curriculum-Based AI Agent

This repo is now focused on a narrow Physics exam-generation product with a document-first Phase 2 baseline.

## Active product scope

- Subject: Physics only
- Output language: Vietnamese only
- Input document: PDF only
- Question type: single-answer MCQ only
- Scope-driven generation by chapter / lesson / topic
- Review, edit, regenerate, versioning, and publish
- Strict grounding with source evidence on every question

## Active flow

1. Upload PDFs through the `documents` API.
2. Parse text, build sections, and persist section-aware chunks.
3. Build the curriculum tree.
4. Resolve user scope into section IDs.
5. Create `ExamSpec`.
6. Create `Blueprint`.
7. Retrieve evidence by persisted `section_id`.
8. Generate MCQ questions.
9. Verify scope adherence, evidence, answerability, and duplication.
10. Review, edit, regenerate, save versions, and publish.

## Phase 2 hardening

- document-first naming on the active API/service surface
- structured `feedback_events` for retrieval, verifier, edit, regenerate, and publish signals
- minimal eval infrastructure under `backend/evals/`
- stronger backend regression scripts under `backend/tests/`
- cleaned Phase-2 UI flow under `UI/app/dashboard/`

## Not in the active production path

- ACE core
- student guidance
- essay / mixed exams
- DOCX / PPTX ingestion
- free-form multi-agent orchestration
- advanced export flows

Legacy and phase-later backend modules remain under `backend/legacy/` and are not mounted into the active app.

## Key docs

- [backend/README.md](backend/README.md)
- [docs/architecture_phase2.md](docs/architecture_phase2.md)
- [docs/evaluation.md](docs/evaluation.md)
- [docs/ui_flow.md](docs/ui_flow.md)
