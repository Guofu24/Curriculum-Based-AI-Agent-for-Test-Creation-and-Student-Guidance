# Backend Directory Map

## Active Package

```text
backend/app/
  api/
    routers/         FastAPI HTTP endpoints
    serializers/     API response shaping
  core/              config, database, MVP rules, shared runtime models
  models/            SQLAlchemy models
  repositories/      narrow data access helpers
  schemas/           Pydantic request/response models
  services/
    analytics/       quality summaries and error categorization
    courses/         course access and CRUD helpers
    curriculum/      scope resolution and section logic
    documents/       upload + parse + curriculum persistence
    exam_planning/   spec normalization + blueprint planning
    exams/           end-to-end exam orchestration and versioning
    feedback/        workflow event logging and feedback store
    generation/      LLM routing and MCQ generation
    playbook/        bullet storage, retrieval, reflection, warmup export
    retrieval/       vector/BM25 retrieval and scope filtering
    review/          edit / regenerate orchestration helpers
    verification/    rule checks and grounding checks
  utils/             small shared helpers
```

## Supporting Folders

- [alembic](e:/Đồ án/Project/backend/alembic): schema migrations
- [evals](e:/Đồ án/Project/backend/evals): offline evaluation scripts and datasets
- [tests](e:/Đồ án/Project/backend/tests): smoke, quality, and foundation validation scripts
- [legacy](e:/Đồ án/Project/backend/legacy): non-critical-path legacy code kept off the mounted runtime
- [docs](e:/Đồ án/Project/backend/docs): backend-local architecture and maintenance docs

## Reading Order For New Developers

1. [main.py](e:/Đồ án/Project/backend/app/main.py)
2. [documents/service.py](e:/Đồ án/Project/backend/app/services/documents/service.py)
3. [exams/service.py](e:/Đồ án/Project/backend/app/services/exams/service.py)
4. [exam_planning/blueprint_service.py](e:/Đồ án/Project/backend/app/services/exam_planning/blueprint_service.py)
5. [retrieval/scoped_retrieval_service.py](e:/Đồ án/Project/backend/app/services/retrieval/scoped_retrieval_service.py)
6. [generation/question_generator.py](e:/Đồ án/Project/backend/app/services/generation/question_generator.py)
7. [verification/mcq_verifier_service.py](e:/Đồ án/Project/backend/app/services/verification/mcq_verifier_service.py)
