# Legacy Modules

These modules are intentionally outside the active production MVP path.

Kept on disk for reference or backward compatibility only:

- `routers/guidance.py`
- `routers/export.py`
- `routers/textbooks.py`
- `services/guidance_service.py`
- `services/export_service.py`
- `services/textbook_service.py`
- `agents/orchestrator.py`
- `agents/requirement_parser.py`
- `agents/reviewer.py`
- `agents/pruning.py`
- `agents/quality_judge.py`
- `agents/dedup_filter.py`
- `agents/scope_auditor.py`
- `agents/bloom_auditor.py`
- `agents/review_impact.py`
- `agents/guidance_agent.py`
- `models/student.py`
- `schemas/textbook.py`

Production startup mounts only the routers exported by `backend/routers/__init__.py`.
Active generation/edit runtime is driven by `ExamService`, `BlueprintAgent`,
`ScopedRetrievalService`, `MCQGenerationService`, and `MCQVerifierService`.
