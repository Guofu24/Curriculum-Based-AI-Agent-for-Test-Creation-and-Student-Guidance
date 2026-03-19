# Backend Phase 4

This backend is hard-locked to the active Physics exam-generation product and now exposes the **ACE foundation** workflow needed for Phase 4.

## Active boundary

- Subject: Physics only
- Output language: Vietnamese only
- Input format: PDF only
- Question type: single-answer MCQ only
- Scope selection: chapter / lesson / topic only
- Review flow: verify, edit, regenerate, version, publish
- Required: strict scope grounding and source evidence per question

Not in the active path:

- ACE core online adaptation
- student guidance
- essay or mixed exams
- DOCX or PPTX ingestion
- export runtime for students
- unrestricted agent orchestration

## Production routers

Mounted at startup:

- `/api/v1/auth`
- `/api/v1/courses`
- `/api/v1/documents`
- `/api/v1/exams`
- `/api/v1/generate`
- `/api/v1/playbook`

Phase 4 feedback + playbook endpoints:

- `GET /api/v1/exams/quality-summary`
- `GET /api/v1/exams/feedback-summary`
- `GET /api/v1/exams/feedback-store`
- `GET /api/v1/exams/{exam_id}/feedback`
- `GET /api/v1/playbook/overview`
- `GET /api/v1/playbook/bullets`
- `GET /api/v1/playbook/candidates`
- `POST /api/v1/playbook/candidates/generate`
- `POST /api/v1/playbook/candidates/{candidate_id}/promote`
- `POST /api/v1/playbook/candidates/{candidate_id}/reject`
- `GET /api/v1/playbook/warmup-preview`

Kept on disk but not mounted:

- `legacy/routers/guidance.py`
- `legacy/routers/export.py`
- `legacy/routers/textbooks.py`

## Phase 4 additions

- hardened `feedback_events` with:
  - `event_stage`
  - `source_type`
  - `source_ref`
  - `error_categories_json`
  - `before_snapshot_ref`
  - `after_snapshot_ref`
  - `linked_eval_sample_id`
- `playbook_bullets` persistence with seed approved bullets
- `reflection_candidates` persistence and promote/reject lifecycle
- feature-flagged playbook retrieval for generator/verifier:
  - `PLAYBOOK_RETRIEVAL_MODE=off|shadow|limited`
  - `PLAYBOOK_RETRIEVAL_LIMIT`
- warmup export service and script
- UI-facing playbook / feedback / warmup APIs
- resilient embedding startup:
  - default backend still prefers `sentence-transformers`
  - if the local HuggingFace embedding stack is broken, dev mode can fall back to deterministic hash embeddings via `EMBEDDING_ALLOW_FALLBACK=true`
  - fallback keeps upload/index/retrieval alive for local work, but retrieval quality is lower than the intended semantic embedding path
  - when fallback embeddings are active, the runtime automatically disables Pinecone vector I/O and uses BM25/local chunk retrieval to avoid slow retry loops against cloud vector search

## Validation commands

From the `backend` directory:

```bash
conda activate graduation
python tests/mvp_smoke_checks.py
python tests/phase3_quality_checks.py
python tests/phase4_foundation_checks.py
python evals/run_phase3_eval.py --split dev
python evals/run_error_analysis.py --split dev
python evals/export_warmup_dataset.py --output evals/output/warmup_dataset.json
```

## Supporting docs

- `../docs/evaluation.md`
- `../docs/ace_foundation.md`
- `../docs/playbook_model.md`
- `../docs/feedback_store.md`
- `../docs/warmup_data.md`
- `../docs/error_analysis.md`
- `../docs/data_curation.md`
- `../docs/ui_flow.md`
- `../docs/codebase_cleanup.md`
