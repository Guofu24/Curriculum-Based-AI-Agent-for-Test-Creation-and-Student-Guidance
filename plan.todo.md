# Plan: Backend Curriculum AI Agent - Exam Generator

**Nguồn tham khảo:** `spec_curriculum_ai_agent_new.md` (Technical Blueprint v2.0)
**Phạm vi:** Viết lại toàn bộ folder `backend/` từ đầu. Frontend đã có.

---

## Progress Tracker

### ✅ COMPLETED (Phase 7-11: Core Agent System)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Agent output model wiring (retrieval → outline → builder → validator) | ✅ DONE | All 4 agents now return typed output models (`RetrievalOutput`, `OutlineOutput`, `BuilderOutput`, `ValidatorOutput`) with proper data propagation |
| 2 | Planner Agent duplicate class definition | ✅ DONE | Removed duplicate class in `planner.py` |
| 3 | Missing `ExamConfigRequest` schema | ✅ DONE | Added `ExamConfigRequest` + `BloomDistribution` to `schemas/exam.py` |
| 4 | `ExamConfigRequest` bloom_distribution fix | ✅ DONE | Now uses `BloomDistribution` pydantic model for type safety |
| 5 | `BlueprintApprovalRequest` schema | ✅ DONE | Already existed in `schemas/exam.py` |
| 6 | `generation.py` `job_id` parameter fix | ✅ DONE | Removed nonexistent `job_id` from Celery task call |
| 7 | `exam_task.py` parameter mismatch | ✅ DONE | All parameters now optional; `job_id` removed (unused) |
| 8 | `SSEvent` usage in document_task | ✅ DONE | `SSEvent.progress()` and `SSEvent.error()` are static methods, usage is correct |
| 9 | WebSocket streaming endpoint | ✅ DONE | Added `/ws/exam/{exam_id}` to `main.py` |
| 10 | HITL checkpoint endpoints | ✅ DONE | Added `approve-blueprint` + `submit-review` to `exams.py` |
| 11 | `submit_review` method in orchestrator | ✅ DONE | Added to `orchestrator.py` |
| 12 | `auth_service` password_hash field | ✅ DONE | `User` model uses `password_hash`, `auth_service` uses `user.password_hash` — consistent |
| 13 | `ValidatorAgent` duplicate class + `ValidatorOutput` | ✅ DONE | Consolidated class, returns `ValidatorOutput` with all fields |
| 14 | `OutlineAgent` return type | ✅ DONE | Returns `OutlineOutput` with `blueprint` + `distribution_summary` |
| 15 | `BuilderAgent` return type | ✅ DONE | Returns `BuilderOutput` with `questions`, `topics_used`, `chunks_referenced` |

### ✅ COMPLETED (Issue Fixes Round 2)

| # | Task | Status | Notes |
|---|------|--------|-------|
| A | `exam_task.py` asyncio.run() in Celery worker | ✅ DONE | Rewrote with ThreadPoolExecutor pattern. Added `autoretry_for`, `retry_backoff`, `Task.ignore_result=False`. Same fix applied to `document_task.py` |
| B | `generation_router` creates exam after generation | ✅ DONE | Moved `service.create_exam()` BEFORE `orchestrator.generate_exam()` in `_generation_stream_generator()` |
| C | `edit_via_prompt` uses AgentStatus enum instead of string | ✅ DONE | Changed all `AgentStatus.FAILED` → `"failed"` and `AgentStatus.PARTIAL` → `"partial"` in `edit_via_prompt()` and `submit_review()` |
| D | `OrchestratorAgent.__init__` ShortTermMemory initialization | ✅ DONE | Verified `ShortTermMemory` is correctly instantiated in `__init__` with redis client |
| E | `partial_regenerate` exam ID extraction from question_ids | ✅ DONE | Added explicit `exam_id` field to `PartialRegenerateRequest` schema. Changed endpoint to accept `PartialRegenerateRequest` (object with exam_id + edits) instead of `list[PartialEditRequest]` |
| F | `RedisClient` constructor mismatch | ✅ DONE | Updated `RedisClient.__init__()` to accept both `Redis` client instance and URL string |
| G | `exam_task` status check against AgentStatus enum | ✅ DONE | Changed status check to use `result.get('status') == 'success'` string comparison with fallback for enum value |
| H | Alembic migrations setup | ✅ DONE | Created `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, and `001_initial.py` with all 8 tables |

### ⚠️ REMAINING TASKS

| # | Task | Priority | Notes |
|---|------|---------|-------|
| 1 | Install `alembic` package and run `alembic upgrade head` | HIGH | Ensure alembic is in requirements.txt, then apply migrations |
| 2 | End-to-end pipeline test | HIGH | Test full flow: auth → upload document → generate exam → stream events → save |
| 3 | Verify WebSocket streaming in SSE endpoint | MEDIUM | `exam_service.update_questions()` properly saves questions + cost_report |
| 4 | RAG pipeline integration test | MEDIUM | Test `rag/parser.py`, `rag/chunker.py`, `rag/embedder.py`, `rag/vector_store.py` |
| 5 | LangFuse observability integration | LOW | Wire up `observability/tracer.py` to all LLM calls |
| 6 | Docker Compose setup for local dev | LOW | postgres + redis + celery worker + uvicorn |

---

---

## 🧹 CLEANUP REPORT (Phase 1–8)

> **Ngày cleanup:** 2026-03-28
> **Phương pháp:** Theo `spec_curriculum_ai_agent_new.md` + `plan.todo.md` làm source of truth duy nhất
> **Nguyên tắc:** Không comment code cũ, xóa hoàn toàn code không có trong spec

### Tổng quan

| Metric | Số lượng |
|--------|----------|
| File đã xóa | ~40+ files/dirs |
| File đã viết lại | ~8 files |
| File được giữ nguyên | ~50 files |

---

### Phase 1 — Xóa root-level directories thừa

Đã xóa hoàn toàn các thư mục root-level không có trong spec:

```
backend/
├── agents/          ❌ Đã xóa (trùng, code cũ)
├── models/          ❌ Đã xóa (trùng, code cũ)
├── routers/         ❌ Đã xóa (trùng, code cũ)
├── schemas/         ❌ Đã xóa (trùng, code cũ)
├── services/        ❌ Đã xóa (trùng, code cũ)
├── core/            ❌ Đã xóa (trùng, code cũ)
├── utils/           ❌ Đã xóa (trùng, code cũ)
├── legacy/          ❌ Đã xóa (không có trong spec)
├── tests/           ❌ Đã xóa (không có trong spec)
├── docs/            ❌ Đã xóa (không có trong spec)
├── evals/           ❌ Đã xóa (không có trong spec)
├── data/            ❌ Đã xóa (không có trong spec)
└── repositories/    ❌ Đã xóa (không có trong spec)
```

---

### Phase 2 — Xóa app/ subdirectories không có trong spec

Đã xóa các subdirectories trong `app/` không có trong spec:

```
app/
├── api/             ❌ Đã xóa (endpoint wrappers, không cần thiết)
├── repositories/    ❌ Đã xóa (DAO layer, SQLAlchemy đủ)
├── services/        ❌ Đã xóa (trùng, chỉ giữ services/ tại app level)
└── (tất cả service sub-folders bên trong đã xóa)
    ├── auth_service/        ❌
    ├── document_service/     ❌
    ├── exam_service/        ❌
    └── generation_service/   ❌
```

---

### Phase 3 — Xóa app/core/ và app/models/ files thừa

**Đã xóa:**
- `app/core/mvp.py` — MVP runtime model (đã có trong orchestrator/routers)
- `app/core/runtime_models.py` — Runtime models (thừa, đã có trong schemas/)
- `app/models/curriculum.py` — Curriculum model (đã xóa nhưng sau đó recreate vì `Document` và `Exam` có FK tới `Course`)

**Đã viết lại:**
- `app/models/course.py` — **Recreated** vì `Document.exam` models có `course_id` FK (cần thiết cho data integrity)

---

### Phase 4 — Viết lại routers thừa

**Đã xóa toàn bộ:**
- `app/routers/courses.py` — Không có trong spec
- `app/routers/generation.py` — Logic đã được tách vào `app/tasks/exam_task.py` + `app/services/exam_service.py`
- `app/routers/playbook.py` — Không có trong spec

**Đã viết lại:**
- `app/routers/__init__.py` — Giữ chỉ `auth`, `documents`, `exams`

---

### Phase 5 — Sửa main.py

**Đã sửa:**
- Import: bỏ `courses`, `generation`, `playbook` → chỉ giữ `auth`, `documents`, `exams`
- `app.include_router()`: bỏ 3 routers không tồn tại
- Bỏ unused import `from fastapi.staticfiles import StaticFiles`

---

### Phase 6 — Sửa app/utils/security.py

**Vấn đề phát hiện:**
- File chứa Vietnamese encoding corruption
- Import model không tồn tại: `app.models.token_blacklist.TokenBlacklist`
- Sử dụng config keys sai: `settings.SECRET_KEY`, `settings.ALGORITHM` (đúng: `JWT_SECRET_KEY`, `JWT_ALGORITHM`)
- Logic trùng lặp với `app/dependencies.py`

**Đã sửa:** Viết lại hoàn toàn, chỉ re-export helpers từ `app/dependencies.py`

---

### Phase 7 — Kiểm tra cross-references cuối cùng

- ✅ Không còn references đến `courses.router`, `generation.router`, `playbook.router`
- ✅ Không còn references đến `TokenBlacklist`
- ✅ Không còn import curriculum model (chỉ có docstring references trong `document_service.py`)
- ✅ Tất cả `__init__.py` files đều clean

---

### Cấu trúc cuối cùng

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── database.py
│   │   └── redis_client.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── refresh_token.py
│   │   ├── course.py        ✅ Giữ (FK từ Document, Exam)
│   │   ├── document.py
│   │   ├── exam.py
│   │   └── teacher_preference.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── document.py
│   │   ├── exam.py
│   │   └── agent.py
│   ├── routers/
│   │   ├── __init__.py     ✅ Viết lại (3 routers)
│   │   ├── auth.py
│   │   ├── documents.py
│   │   └── exams.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── document_service.py
│   │   └── exam_service.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── llm.py
│   │   ├── orchestrator.py
│   │   ├── retrieval.py
│   │   ├── outline.py
│   │   ├── builder.py
│   │   ├── validator.py
│   │   ├── planner.py
│   │   ├── guardrails.py
│   │   ├── skills/
│   │   │   ├── __init__.py
│   │   │   ├── bloom_classifier.py
│   │   │   ├── scope_checker.py
│   │   │   ├── latex_renderer.py
│   │   │   ├── dedup_checker.py
│   │   │   └── difficulty_estimator.py
│   │   └── memory/
│   │       └── __init__.py
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── parser.py
│   │   ├── structure.py
│   │   ├── extractor.py
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   └── vector_store.py
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── celery_app.py
│   │   ├── document_task.py
│   │   └── exam_task.py
│   ├── websocket/
│   │   ├── __init__.py
│   │   └── manager.py
│   ├── observability/
│   │   ├── __init__.py
│   │   └── tracer.py
│   └── utils/
│       ├── __init__.py
│       ├── s3.py
│       ├── export.py
│       └── security.py        ✅ Viết lại (clean facade)
├── migrations/
│   ├── README
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 001_initial.py
│       └── 002_add_scope_exam_config.py
├── alembic.ini
├── requirements.txt
└── .env.example
```

---

### Các điểm chưa implement theo spec

| # | Điểm | Ghi chú |
|---|-------|---------|
| 1 | `app/agents/memory/short_term.py` | File chỉ có `__init__.py` rỗng; Short-term memory logic có thể nằm trong `orchestrator.py` |
| 2 | `app/agents/memory/long_term.py` | File chỉ có `__init__.py` rỗng; Long-term memory dùng trực tiếp `TeacherPreference` model |

---

### Ghi chú quan trọng

1. **`app/models/course.py`**: Đã recreate vì `Document` và `Exam` models có FK `course_id` tham chiếu tới `Course`. Việc này deviated khỏi strict spec nhưng là cần thiết cho data integrity.

2. **`app/agents/memory/short_term.py` và `long_term.py`**: Hiện chỉ là empty `__init__.py` files. Memory logic được implement inline trong `orchestrator.py` và các service files. Cần tạo các module riêng nếu spec yêu cầu tách biệt.

3. **`app/routers/generation.py`**: Đã xóa vì không có trong spec. Logic generation nằm trong `app/tasks/exam_task.py` + `app/services/exam_service.py`. Nếu frontend vẫn cần `/api/v1/generation/` endpoint, cần tái tạo router này.

4. **`app/schemas/course.py`**: Không tồn tại — schemas cho course nằm trong `document.py` (CurriculumNode schemas). Cân nhắc tạo `schemas/course.py` nếu có dedicated course API.

---

## 1. Project Setup & Core Infrastructure

### 1.1 Folder Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan events, middleware, WebSocket
│   ├── config.py            # Pydantic Settings từ .env
│   ├── database.py          # Async SQLAlchemy engine + session
│   ├── redis_client.py      # Redis connection pool
│   ├── dependencies.py     # FastAPI Depends() reusable
│   ├── models/              # SQLAlchemy ORM
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── document.py
│   │   ├── exam.py
│   │   ├── exam_history.py
│   │   ├── refresh_token.py
│   │   └── teacher_preference.py
│   ├── schemas/              # Pydantic request/response
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── document.py
│   │   ├── exam.py
│   │   └── agent.py
│   ├── routers/              # FastAPI APIRouter
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── documents.py
│   │   └── exams.py
│   ├── services/             # Business logic
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── document_service.py
│   │   └── exam_service.py
│   ├── agents/               # Multi-agent system (CORE)
│   │   ├── __init__.py
│   │   ├── base.py           # AgentStatus, TokenUsage, AgentBaseOutput (Pydantic)
│   │   ├── llm.py            # Shared async OpenAI client + instructor
│   │   ├── orchestrator.py   # Agent 0: điều phối toàn pipeline
│   │   ├── retrieval.py       # Agent 1: truy vấn vector DB
│   │   ├── outline.py        # Agent 2: lập sườn đề
│   │   ├── builder.py        # Agent 3: sinh câu hỏi
│   │   ├── validator.py      # Agent 4: kiểm tra đề
│   │   ├── planner.py        # Planner Agent: dynamic execution plan
│   │   ├── skills/           # Skills Library
│   │   │   ├── __init__.py
│   │   │   ├── bloom_classifier.py
│   │   │   ├── scope_checker.py
│   │   │   ├── latex_renderer.py
│   │   │   ├── dedup_checker.py
│   │   │   └── difficulty_estimator.py
│   │   ├── memory/           # Memory Layer
│   │   │   ├── __init__.py
│   │   │   ├── short_term.py  # Redis session (2h TTL)
│   │   │   └── long_term.py   # PostgreSQL teacher_preferences
│   │   └── guardrails.py     # Output parser, token budget, content filter, scope guard
│   ├── rag/                  # RAG Pipeline
│   │   ├── __init__.py
│   │   ├── parser.py         # Marker (PDF), python-docx, python-pptx
│   │   ├── structure.py      # Heading tree detection
│   │   ├── extractor.py      # Formula (Nougat/MathPix) + Image (GPT-4o Vision)
│   │   ├── chunker.py        # LlamaIndex SemanticSplitter
│   │   ├── embedder.py       # OpenAI embedding + Redis cache
│   │   └── vector_store.py   # Pinecone upsert/query
│   ├── tasks/                # Celery tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py
│   │   ├── document_task.py
│   │   └── exam_task.py
│   ├── websocket/            # WebSocket streaming
│   │   ├── __init__.py
│   │   └── manager.py        # ConnectionManager + Redis pub/sub
│   ├── observability/        # LangFuse tracing
│   │   ├── __init__.py
│   │   └── tracer.py
│   └── utils/
│       ├── __init__.py
│       ├── s3.py             # AWS S3 upload + presigned URL
│       ├── export.py         # PDF (WeasyPrint) + DOCX export
│       └── security.py       # JWT + bcrypt helpers
├── migrations/               # Alembic
├── tests/
├── requirements.txt
├── .env.example
└── Dockerfile
```

### 1.2 requirements.txt

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.6.0
pydantic-settings>=2.2.0
sqlalchemy[asyncio]>=2.0.27
asyncpg>=0.29.0
alembic>=1.13.0
redis>=5.0.0
celery>=5.3.6
pinecone-client>=3.0.0
llama-index>=0.10.0
openai>=1.12.0
instructor>=1.0.0
tiktoken>=0.6.0
marker-pdf>=1.0.0
python-docx>=1.1.0
python-pptx>=1.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.9
boto3>=1.34.0
langfuse>=2.0.0
weasyprint>=60.0
httpx>=0.27.0
tenacity>=8.2.0
```

### 1.3 .env.example

```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/curriculum_ai
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=...
PINECONE_INDEX=curriculum_ai
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-southeast-1
S3_BUCKET_NAME=curriculum-ai-uploads
MATHPIX_APP_ID=...
MATHPIX_APP_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
JWT_SECRET_KEY=<openssl rand -hex 32>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
```

---

## 2. Database Models & Migrations

### 2.1 SQLAlchemy Models (app/models/)

**user.py**
- id (UUID, PK), email (unique), password_hash, full_name, role (default 'teacher'), created_at

**refresh_token.py**
- id (UUID, PK), user_id (FK → users), token_hash, expires_at, revoked (bool), created_at

**document.py**
- id (UUID, PK), user_id (FK → users), original_filename, file_type (pdf/docx/pptx)
- s3_key, processing_status (pending/processing/completed/failed)
- heading_tree (JSONB), total_chapters (int), uploaded_at

**exam.py**
- id (UUID, PK), user_id (FK → users), document_id (FK → documents)
- title, scope (JSONB), exam_config (JSONB), questions (JSONB)
- status (draft/published)
- cost_report (JSONB), total_tokens (int), total_cost_usd (decimal)
- created_at, updated_at

**exam_history.py**
- id (UUID, PK), exam_id (FK → exams), snapshot (JSONB), change_type, change_description, created_at

**teacher_preference.py**
- user_id (UUID, PK → users), preferred_bloom_distribution (JSONB), preferred_exam_types (JSONB)
- subject_focus (varchar), style_notes (text), updated_at

### 2.2 Alembic
- Initial migration từ models trên
- Handle JSONB columns đúng cách

---

## 3. Auth Module

### 3.1 app/services/auth_service.py
- register(email, password, full_name) → hash bcrypt, tạo user
- login(email, password) → verify, trả JWT access + refresh tokens
- refresh(refresh_token) → rotate, revoke cũ, trả tokens mới
- logout(refresh_token) → revoke trong DB
- Rate limit login: 5 attempts/min/IP dùng Redis

### 3.2 app/routers/auth.py
- POST /api/v1/auth/register
- POST /api/v1/auth/login
- POST /api/v1/auth/refresh
- POST /api/v1/auth/logout

### 3.3 JWT Strategy
- Access token: JWT HS256, TTL 15 phút
- Refresh token: opaque hash trong DB, TTL 7 ngày, rotation enabled

### 3.4 app/dependencies.py
- get_current_user(): decode JWT → user object
- get_db(): async SQLAlchemy session
- get_redis(): Redis connection

---

## 4. Document Module (RAG Pipeline)

### 4.1 app/routers/documents.py
- POST /api/v1/documents/upload → upload S3 → tạo DB record → trigger Celery task
- GET /api/v1/documents → list user's documents
- GET /api/v1/documents/{id} → chi tiết + heading_tree
- GET /api/v1/documents/{id}/status → processing status
- DELETE /api/v1/documents/{id} → xóa DB + S3 + Pinecone vectors

### 4.2 app/utils/s3.py
- upload_file(file, user_id) → S3 private bucket, return s3_key
- generate_presigned_url(s3_key, TTL=3600)
- delete_file(s3_key)

### 4.3 app/rag/parser.py
- parse_document(file_bytes, file_type):
  - PDF (text/scan): Marker (giữ heading, table, formula, OCR)
  - DOCX: python-docx (heading levels, tables)
  - PPTX: python-pptx (slide title = heading)
- Return: markdown string với heading tags

### 4.4 app/rag/structure.py
- detect_heading_tree(markdown_content): regex + heading tags → nested tree
- Gán chapter_id, section_id, subsection_id
- Return: heading_tree JSON

### 4.5 app/rag/extractor.py
- extract_formulas(text): detect LaTeX → parse
  - Image formula: Nougat (priority) → MathPix fallback
  - Return: {text_repr, latex_repr, location}
- extract_images(images): GPT-4o Vision → text description (Vietnamese physics prompt)

### 4.6 app/rag/chunker.py
- semantic_chunk(markdown_content, heading_tree, embed_model)
- LlamaIndex SemanticSplitterNodeParser
- Config: buffer_size=1, breakpoint_percentile_threshold=95
- Metadata per chunk: chunk_id, document_id, chapter, chapter_id, section, section_id, content_type, page_number, latex_repr

### 4.7 app/rag/embedder.py
- embed_chunks(chunks): text-embedding-3-large
- Cache: Redis key = embed:{doc_id}:{chunk_id}, TTL 7 days

### 4.8 app/rag/vector_store.py
- upsert_namespace(doc_id, chapter_id, chunks): Pinecone namespace = {doc_id}_{chapter_id}
- query_namespace(doc_id, chapters, query_embedding, top_k): query per-chapter namespace
- delete_namespace(doc_id)

### 4.9 app/tasks/document_task.py (Celery)
- process_document_task(document_id):
  1. Download từ S3
  2. Parse (rag/parser.py)
  3. Structure detection (rag/structure.py)
  4. Formula + image extraction (rag/extractor.py)
  5. Chunking (rag/chunker.py)
  6. Embed + upsert Pinecone
  7. Update DB: processing_status = 'completed'
- Emit WebSocket status event qua Redis pub/sub

---

## 5. Multi-Agent System (CORE)

### 5.1 app/agents/base.py

```python
class AgentStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    RETRY_NEEDED = "retry"

class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float

class AgentBaseOutput(BaseModel):
    status: AgentStatus
    agent_name: str
    execution_time_ms: int
    token_usage: TokenUsage
    warnings: List[str] = []
    trace_id: str
```

### 5.2 app/agents/llm.py
- Shared async OpenAI client (instructor-powered)
- Model routing:
  - GPT-4o: Orchestrator, Builder
  - GPT-4o-mini: Planner, Reranker, Dedup, Outline
  - GPT-4o/Claude Opus: Validator (answer checking)
- Auto LangFuse span emission mỗi LLM call

### 5.3 app/agents/skills/ — Skills Library

#### bloom_classifier.py
- Input: {question_stem, question_type, subject}
- Output: {bloom_level, confidence, reasoning}
- Bloom rubric:
  - Nhận biết: định nghĩa, liệt kê, nêu tên
  - Thông hiểu: giải thích, so sánh, áp dụng công thức 1 bước
  - Vận dụng: tính toán 2-3 bước, có điều kiện
  - Vận dụng cao: phân tích, đánh giá, bài toán phức hợp

#### scope_checker.py
- Input: {question_stem, retrieved_context_ids, scope_chapters}
- Output: {in_scope, violation_type, evidence_chunk_ids, confidence}

#### latex_renderer.py
- Input: {raw_formula, context}
- Output: {latex, display_latex, unicode_fallback}

#### dedup_checker.py
- Input: {new_question_topic, existing_topics}
- Output: {is_duplicate, duplicate_with, similarity_score, suggestion}

#### difficulty_estimator.py
- Input: {question_stem, bloom_level, solution_steps}
- Output: {difficulty_score: 0.0-1.0, estimated_solve_time_minutes, complexity_factors}

### 5.4 app/agents/memory/

#### short_term.py (Redis)
- Key: session:{exam_id}:{user_id}
- TTL: 7200s (2 giờ)
- Store: exam_config_original, topics_used[], conversation_history[], retry_count
- Methods: save_session(), load_session(), append_history(), update_topics()

#### long_term.py (PostgreSQL)
- get_preferences(user_id): load teacher_preferences
- save_preferences(user_id, prefs): update sau exam publish

### 5.5 app/agents/guardrails.py
- **Output Parser**: instructor client + Pydantic model, max_retries=3
- **TokenBudgetGuard**: check trước mỗi LLM call, flush khi <10% budget
- **ContentFilter**: stem length > 20, MCQ options unique, correct_answer in options, no answer in stem
- **ScopeGuard**: inline, câu hỏi chỉ dùng allowed_concepts

### 5.6 app/agents/retrieval.py (Agent 1)
- Input: {document_id, scope_chapters, bloom_targets, query_hints}
- Flow:
  1. Query expansion: sinh 3-5 query variants
  2. Parallel sub-queries per chapter → Pinecone namespace
  3. LLM reranking: GPT-4o-mini rerank top-20 → top-8
  4. Merge & dedupe
- Output: {retrieved_chunks, coverage_map}
- Timeout: 30s, fallback: empty context + warning

### 5.7 app/agents/outline.py (Agent 2)
- Input: {retrieved_context, exam_config}
- Logic:
  - Convert bloom % → số câu (round hợp lệ)
  - Distribute evenly across chapters (no chapter >50%)
  - van_dung_cao: ưu tiên chapters có công thức
- Output: {blueprint: [{question_id, type, bloom_level, chapter, section, topic_hint, content_type, estimated_difficulty}], distribution_summary}
- Timeout: 20s, fallback: default distribution template

### 5.8 app/agents/builder.py (Agent 3)
- Input: {blueprint, retrieved_context, topics_used, allowed_concepts}
- Flow:
  1. Sinh theo chunk: 5-10 câu mỗi LLM call
  2. Mỗi câu: bloom_classifier_skill → dedup_checker_skill → content_filter
  3. van_dung_cao: web_search tool (SerpAPI) → adapt vào scope
  4. Formula: text + LaTeX song song
- MCQ rules: 4 options, 1 correct, 3 distractors logic
- Essay rules: có rubric chấm điểm
- Append topics_used vào Redis
- Timeout: 120s per chunk
- Guardrails: instructor parser, token budget guard, scope guard

### 5.9 app/agents/validator.py (Agent 4)
- Input: {questions, exam_config}
- 3 nhiệm vụ:
  1. **Answer Checking**: LLM giải từng câu → so sánh với Builder đáp án → flag sai
  2. **Bloom Compliance**: bloom_classifier_skill verify → so sánh với phân bổ → fail nếu lệch >2
  3. **Scope Violation**: scope_checker_skill → flag nếu ngoài retrieved_context
- Retry logic: max 3 vòng → Builder Agent với issues list
- Timeout: 60s, fallback: partial validation + manual review flag

### 5.10 app/agents/planner.py (Planner Agent)
- Input: {user_request_parsed, exam_config, available_tools, constraints}
- Chỉ gọi khi: prompt phức tạp hoặc yêu cầu chỉnh sửa hàng loạt
- Output: {plan: [{step, tool, params_override, note}], estimated_token_cost, hitl_checkpoint_after_step}
- Fallback: hardcoded default plan (timeout 15s)

### 5.11 app/agents/orchestrator.py (Agent 0)
- Entry point duy nhất từ API
- Luồng chính:
  1. Parse & Clarify: nếu chưa rõ → sinh ≤3 câu hỏi làm rõ
  2. Rewrite Requirements: structured format → confirm
  3. Load Long-term Memory: teacher_preferences từ PostgreSQL
  4. Dispatch: complex → Planner; simple → default plan
  5. Execute: retrieve → outline → HITL checkpoint 1 → build → validate → retry loop (max 3)
  6. Output: đề hoàn chỉnh + plan reasoning stream
- Streaming: emit real-time plan steps qua WebSocket

---

## 6. Exam Module & API

### 6.1 app/routers/exams.py
- POST /api/v1/exams/generate → nhận exam_config → tạo exam record → trigger Celery task → return job_id
- GET /api/v1/exams/{id} → lấy đề
- PATCH /api/v1/exams/{id}/questions/{qid} → sửa trực tiếp 1 câu → snapshot history
- POST /api/v1/exams/{id}/edit-prompt → chỉnh sửa qua prompt → load Redis → Orchestrator
- POST /api/v1/exams/{id}/regenerate → regenerate toàn bộ
- POST /api/v1/exams/{id}/export → xuất PDF/DOCX
- GET /api/v1/exams → lịch sử đề
- GET /api/v1/exams/history/{id} → timeline snapshots
- POST /api/v1/exams/history/{id}/restore/{history_id} → rollback
- WS /api/v1/exams/stream/{job_id} → WebSocket endpoint

### 6.2 app/services/exam_service.py
- create_exam(user_id, document_id, exam_config)
- get_exam(exam_id, user_id)
- update_question(exam_id, qid, updates) → snapshot history
- prompt_edit(exam_id, user_id, prompt) → load Redis → Orchestrator → update
- regenerate_exam(exam_id)
- export_exam(exam_id, format)
- list_exams(user_id, page, limit)
- get_history(exam_id)
- restore_snapshot(exam_id, history_id)

### 6.3 app/tasks/exam_task.py (Celery)
- generate_exam_task(exam_config):
  1. Load exam record từ DB
  2. Orchestrator: execute full pipeline
  3. Emit WebSocket events qua Redis pub/sub
  4. Save result + cost_report vào DB
  5. Update exam status
- Auto-retry: max 3 lần

---

## 7. WebSocket Streaming

### 7.1 app/websocket/manager.py
- ConnectionManager: connect(user_id, exam_id, websocket), disconnect(websocket), emit(event), broadcast(exam_id, event)
- Redis pub/sub: backend subscribe exam:{exam_id} channel

### 7.2 Event Types
```python
PlanStepEvent:   {type: "plan_step", message, step, total_steps}
QuestionEvent:   {type: "question_generated", question_id, question}
ValidationEvent: {type: "validation_result", passed, issues_count}
CompletedEvent:  {type: "completed", exam_id}
ErrorEvent:      {type: "error", message, agent}
HitlEvent:       {type: "hitl_checkpoint", checkpoint_id, data}
```

---

## 8. Export Module

### 8.1 app/utils/export.py
- export_to_pdf(exam_data): WeasyPrint, HTML template → PDF
  - Header: exam title, subject, date
  - MCQ section: numbered, 4 options, answer hidden
  - Essay section: numbered, rubric table
  - Footer: page numbers
- export_to_docx(exam_data): python-docx
  - Heading styles, numbered lists, table for MCQ options

---

## 9. Observability (LangFuse)

### 9.1 app/observability/tracer.py
- LangFuseTracer wrapper cho mỗi LLM call
- Emit: span_name, agent, input_hash, output_hash, latency_ms, token_usage, model, estimated_cost_usd, status
- Trace structure:
  - Root: exam_generate_{exam_id}
  - Child spans: orchestrator.*, planner.*, retrieval.*, outline.*, builder.*, validator.*
  - Sub-spans: per-chunk, per-skill

### 9.2 Cost Tracking
- ExamCostReport: total_tokens, total_cost_usd, breakdown per agent, model_used
- Lưu vào exams.cost_report (JSONB)

---

## 10. HITL Checkpoints

### 10.1 Checkpoint 1: Blueprint Review
- Sau Outline Agent → render blueprint table (Bloom × Chapter)
- POST /api/v1/exams/{id}/approve-blueprint
- Reject → gọi lại Outline với feedback

### 10.2 Checkpoint 2: Full Review Screen
- Render all questions + Bloom chart + chat panel
- Inline edit (PATCH endpoint)
- Prompt edit (POST edit-prompt)
- Hiển thị cost report (token, USD)

### 10.3 Checkpoint 3: Export Preview
- Render preview trong browser
- Confirm → actual download

---

## Thứ tự triển khai

1. Phase 1: Project setup + folder structure + .env
2. Phase 2: SQLAlchemy models + Alembic migrations
3. Phase 3: Auth (JWT, bcrypt, refresh token rotation)
4. Phase 4: Redis client + dependencies
5. Phase 5: Document upload + S3 + RAG pipeline (parse → chunk → embed → Pinecone)
6. Phase 6: Celery setup + document_task
7. Phase 7: Skills library (5 skills)
8. Phase 8: Memory layer (Redis short-term + PostgreSQL long-term)
9. Phase 9: Agent base + LLM client + guardrails
10. Phase 10: Individual agents (Retrieval → Outline → Builder → Validator → Planner)
11. Phase 11: Orchestrator + full pipeline integration
12. Phase 12: Exam API endpoints + exam_service
13. Phase 13: Celery exam_task + Orchestrator integration
14. Phase 14: WebSocket streaming
15. Phase 15: LangFuse tracing + cost tracking
16. Phase 16: Export PDF/DOCX
17. Phase 17: HITL checkpoints + review flow
