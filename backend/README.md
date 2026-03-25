# Backend Overview

This backend is the active runtime for the Physics exam-generation MVP.

## Active Product Boundary

- Subject: Physics only
- Language: Vietnamese only
- Input: PDF only
- Output: single-answer MCQ only
- Scope: chapter / lesson / topic sections only
- Review flow: verify, edit, regenerate, version, publish
- Grounding: strict scope + source evidence per question

Not in the active path:

- student guidance
- essay runtime
- DOCX / PPTX runtime ingestion
- multi-subject generation
- ACE adaptive runtime

## Active Code Path

All active backend code now lives under [app](e:/Đồ án/Project/backend/app):

```text
backend/
  app/
    api/
    core/
    models/
    repositories/
    schemas/
    services/
    utils/
  alembic/
  docs/
  evals/
  legacy/
  tests/
```

The old top-level modules such as `backend/services/*`, `backend/agents/*`, `backend/models/*`, `backend/config.py`, and `backend/main.py` are now compatibility shims that forward imports to `backend/app/*`.

## Runtime Flow

1. Upload document: router -> document service -> document processor -> sections/chunks/curriculum persistence.
2. Generate exam: router -> exam service -> scope resolution -> exam spec -> blueprint -> scoped retrieval -> MCQ generation -> verification -> version persistence.
3. Review/regenerate: edit service -> targeted retrieval -> regenerate -> reverify -> new exam version.
4. Publish/quality/playbook: analytics, feedback store, reflection candidates, warmup export, playbook retrieval modes.

Primary entrypoints:

- [main.py](e:/Đồ án/Project/backend/app/main.py)
- [documents service](e:/Đồ án/Project/backend/app/services/documents/service.py)
- [exam service](e:/Đồ án/Project/backend/app/services/exams/service.py)

## Validation Commands

Run from the repo root:

```bash
python backend/verify_imports.py
python backend/tests/mvp_smoke_checks.py
python backend/tests/phase3_quality_checks.py
python backend/tests/phase4_foundation_checks.py
python backend/evals/run_phase3_eval.py --split dev
python backend/evals/run_error_analysis.py --split dev
python backend/evals/export_warmup_dataset.py --output backend/evals/output/warmup_dataset.json
```

## Backend Docs

- [active_backend_flow.md](e:/Đồ án/Project/backend/docs/active_backend_flow.md)
- [backend_directory_map.md](e:/Đồ án/Project/backend/docs/backend_directory_map.md)
- [compatibility_zones.md](e:/Đồ án/Project/backend/docs/compatibility_zones.md)
- [service_responsibilities.md](e:/Đồ án/Project/backend/docs/service_responsibilities.md)

Supporting product docs remain in the repo-level [docs](e:/Đồ án/Project/docs) folder.
