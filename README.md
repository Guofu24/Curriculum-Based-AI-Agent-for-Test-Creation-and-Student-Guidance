# ExamAI Physics ACE Foundation

This repo now targets the **Phase 4 baseline** of a narrow internal product for grounded Physics MCQ generation in Vietnamese.

## Active scope

- Subject: Physics only
- Language: Vietnamese only
- Input: PDF only
- Output: single-answer MCQ only
- Scope: chapter / lesson / topic selection only
- Workflow: generate, verify, review, edit, regenerate, version, publish
- Requirement: strict scope grounding with source evidence on every question

## Active flow

1. Upload a PDF through the documents flow.
2. Parse text and derive curriculum sections.
3. Build a curriculum tree and persist section-aware chunks.
4. Resolve the teacher-selected scope into section IDs.
5. Build `ExamSpec`.
6. Build `Blueprint`.
7. Retrieve evidence inside the allowed section IDs.
8. Generate MCQ questions.
9. Verify scope, evidence, answerability, and duplication.
10. Review warnings, source evidence, and question activity.
11. Edit or regenerate questions, then save a new version.
12. Publish only after the review state is acceptable.

## Phase 4 focus

- richer `feedback_events` that are queryable by exam, version, question, stage, source, actor, and error category
- a persisted **playbook bullet store** with approved, candidate, archived, and rejected lifecycle states
- a **reflection candidate** layer that turns feedback + eval patterns into promotable playbook items
- an **offline warmup export** for accepted exams, question history, feedback cases, and playbook seeds
- **feature-flagged playbook retrieval** for generator/verifier:
  - `off`
  - `shadow`
  - `limited`
- UI and docs that make it clear this is ACE foundation, not ACE core

## Not in the active runtime

- ACE core online adaptation
- autonomous prompt rewriting loops
- student guidance
- essay or mixed-question exams
- DOCX or PPTX ingestion
- multi-subject support
- legacy runtime reactivation

## Key docs

- [backend/README.md](backend/README.md)
- [docs/evaluation.md](docs/evaluation.md)
- [docs/ace_foundation.md](docs/ace_foundation.md)
- [docs/playbook_model.md](docs/playbook_model.md)
- [docs/feedback_store.md](docs/feedback_store.md)
- [docs/warmup_data.md](docs/warmup_data.md)
- [docs/phase3_eval_workflow.md](docs/phase3_eval_workflow.md)
- [docs/error_analysis.md](docs/error_analysis.md)
- [docs/data_curation.md](docs/data_curation.md)
- [docs/ui_flow.md](docs/ui_flow.md)
- [docs/codebase_cleanup.md](docs/codebase_cleanup.md)
- [docs/architecture_phase2.md](docs/architecture_phase2.md)
