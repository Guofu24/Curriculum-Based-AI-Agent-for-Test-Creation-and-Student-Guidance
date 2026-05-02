# Backend Overview

Backend FastAPI cho ExamAI — hệ thống tạo đề kiểm tra tự động.

## Cấu trúc

```
backend/
├── app/
│   ├── agents/              # Multi-agent AI pipeline (Orchestrator, Retrieval, Outline, Builder, Validator)
│   │   ├── graph/          # LangGraph nodes & state
│   │   ├── skills/         # Bloom classifier, dedup, difficulty, latex
│   │   └── memory/         # Short-term (Redis) + Long-term (PostgreSQL)
│   ├── routers/            # API endpoints (auth, documents, exams, generate)
│   ├── services/          # Business logic (auth, exam, document)
│   ├── rag/               # RAG pipeline (parser, chunker, embedder, vector_store)
│   ├── models/            # SQLAlchemy models
│   ├── schemas/           # Pydantic schemas
│   ├── tasks/             # Celery tasks
│   ├── websocket/         # WebSocket manager
│   ├── core/             # Config, database, redis
│   ├── observability/     # Langfuse, tracer, cost
│   └── utils/             # Storage (S3/MinIO), export
├── migrations/             # Alembic migrations
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Entry Points

- `app/main.py` — FastAPI app
- `app/routers/generate.py` — Khởi tạo sinh đề
- `app/tasks/exam_task.py` — Celery task cho exam generation

## Chạy

```bash
# Development
uvicorn app.main:app --reload --port 8000

# Celery worker
celery -A app.tasks.celery_app worker --loglevel=info

# Docker
docker-compose up -d
```
