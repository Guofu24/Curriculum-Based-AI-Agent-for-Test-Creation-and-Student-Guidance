# Backend Phase 2

This backend is hard-locked to the active Physics exam-generation product and now includes the Phase 2 hardening layer.

## Active boundary

- Subject: Physics only
- Output language: Vietnamese only
- Input format: PDF only
- Question type: single-answer MCQ only
- Scope selection: chapter / lesson / topic only
- Flow: review, edit, regenerate, versioning, publish
- Required: strict scope grounding and source evidence per question

Not in the active production path:

- ACE core
- student guidance
- essay / mixed exams
- DOCX / PPTX ingestion
- export runtime
- free-form multi-agent orchestration

## Production routers

Mounted at startup:

- `/api/v1/auth`
- `/api/v1/courses`
- `/api/v1/documents`
- `/api/v1/exams`
- `/api/v1/generate`

Kept on disk but not mounted:

- `legacy/routers/guidance.py`
- `legacy/routers/export.py`
- `legacy/routers/textbooks.py`

## Active service path

The active API surface is document-first:

- `DocumentService` + `documents` router are the production-facing names
- review/edit/regenerate/versioning are handled through the exam + generation services
- persistence still uses historical `textbooks` / `textbook_chunks` tables through compatibility aliases such as `DocumentRecord` and `DocumentChunkRecord`

## Deterministic flow

1. Upload a PDF through the documents router.
2. Parse text and derive curriculum sections.
3. Attach a deterministic `section_id` to every new chunk.
4. Persist sections, chunks, and embeddings.
5. Resolve user scope into concrete `selected_section_ids`.
6. Build `ExamSpec` with `strict_scope_flag=true`.
7. Build `Blueprint` from the spec before any generation.
8. Retrieve evidence for each blueprint slot using section-aware filtering.
9. Generate MCQ questions only.
10. Verify scope adherence, MCQ validity, answerability, and duplicates.
11. Review / edit / regenerate.
12. Save a new exam version and publish when ready.

## Hard enforcement

### Strict scope

- Request-level `strict_scope` is deprecated and ignored.
- Constraint-level `constraints.strict_scope` is deprecated and ignored.
- Runtime payloads are normalized to `strict_scope=true`.
- Stored `ExamSpec.strict_scope_flag` is always `true` in the active path.
- Invalid explicit scope does not expand to the whole document.

### Section-based retrieval

- New chunks must carry a persisted `chunk.section_id`.
- Blueprint cells and slots preserve `section_id`.
- Retrieval first filters vector/BM25 results by `section_id`.
- DB fallback queries chunks by `section_id` directly.
- Heuristic chunk-to-section matching is only a temporary fallback for legacy rows with no `section_id`.
- Documents without persisted sections are rejected from active generation/regeneration until reprocessed.

### Legacy runtime cut-off

- Non-MCQ exams are rejected from active regenerate/publish paths.
- Non-section-scoped legacy exams are rejected from active regenerate/publish paths.
- Startup wiring does not depend on guidance/export/orchestrator modules.

## Phase 2 additions

- Structured `feedback_events` for:
  - retrieval summaries
  - verifier warnings and failures
  - regenerate actions
  - human edits
  - publish actions
- Minimal evaluation runner under `evals/`
- Stronger backend regression checks under `tests/`

## Validation commands

From the `backend` directory:

```bash
conda activate graduation
python tests/mvp_smoke_checks.py
python tests/phase2_hardening_checks.py
python evals/run_phase2_eval.py
```

## Supporting docs

- `../docs/architecture_phase2.md`
- `../docs/evaluation.md`
- `../docs/ui_flow.md`
