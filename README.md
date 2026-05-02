# ExamAI — Hệ thống Tạo đề Kiểm tra Vật lý bằng Multi-Agent AI

Hệ thống tạo đề kiểm tra tự động từ tài liệu PDF, sử dụng pipeline **multi-agent AI** với **Human-in-the-Loop (HITL)** — giảng viên kiểm soát hoàn toàn chất lượng đầu ra.

---

## Tính năng chính

- **Sinh đề tự động** từ tài liệu PDF trong vài phút
- **Phân bổ Bloom chính xác** theo cấu hình giảng viên
- **HITL checkpoints** — giảng viên duyệt blueprint và đề trước khi hoàn thành
- **Real-time WebSocket** — theo dõi từng bước sinh đề
- **Xuất PDF / DOCX** sẵn sàng in
- **Ghi nhớ sở thích** giảng viên qua Long-term Memory

---

## Kiến trúc

```
Frontend (Next.js 16)
       │ REST + WebSocket
       ▼
Backend (FastAPI)
  ├── Routers: auth, documents, exams, generate
  ├── Orchestrator Agent (LangGraph StateGraph)
  │     ├── Retrieval Agent
  │     ├── Outline Agent
  │     ├── Builder Agent
  │     └── Validator Agent
  └── Tasks (Celery)
       │
       ├── PostgreSQL  (users, exams, documents, preferences)
       ├── Redis       (short-term memory, pub/sub, WebSocket relay)
       ├── Pinecone    (vector store: document chunks)
       └── MinIO/S3    (file storage)
```

---

## Cấu trúc thư mục

```
Project/
├── Frontend/                    # Next.js 16 + TypeScript
│   └── app/dashboard/          # Routes: generate, exams, documents, settings
│
├── backend/
│   ├── app/
│   │   ├── agents/            # AI agents
│   │   │   ├── orchestrator.py   # Agent 0: điều phối (LangGraph)
│   │   │   ├── retrieval.py       # Agent 1: truy xuất vector
│   │   │   ├── outline.py         # Agent 2: tạo blueprint
│   │   │   ├── builder.py         # Agent 3: sinh câu hỏi
│   │   │   ├── validator.py        # Agent 4: kiểm tra chất lượng
│   │   │   ├── planner.py          # Planner cho yêu cầu phức tạp
│   │   │   ├── graph/              # LangGraph nodes & state
│   │   │   ├── skills/             # Bloom classifier, dedup, difficulty, latex
│   │   │   └── memory/             # Short-term (Redis) + Long-term (PostgreSQL)
│   │   ├── routers/            # API endpoints
│   │   │   ├── auth.py        # Đăng nhập / đăng ký / JWT
│   │   │   ├── documents.py   # Upload, xử lý PDF, chunking
│   │   │   ├── exams.py        # CRUD đề, approve/reject, export
│   │   │   ├── generate.py     # Khởi tạo sinh đề
│   │   │   └── courses.py      # Placeholder (chưa implement)
│   │   ├── services/           # Business logic
│   │   │   ├── auth_service.py
│   │   │   ├── exam_service.py
│   │   │   └── document_service.py
│   │   ├── rag/               # RAG pipeline
│   │   │   ├── parser.py          # PDF parsing (Marker, PyMuPDF)
│   │   │   ├── cleaner.py          # Markdown cleaning
│   │   │   ├── chunker.py          # Chunking strategy
│   │   │   ├── structure.py        # Heading tree detection
│   │   │   ├── embedder.py         # BGE-m3 embeddings
│   │   │   └── vector_store.py     # Pinecone client
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── tasks/             # Celery tasks (exam, document)
│   │   ├── websocket/         # WebSocket manager
│   │   ├── core/              # Config, database, redis
│   │   ├── observability/     # Langfuse, tracer, cost tracking
│   │   └── utils/             # Storage (S3/MinIO), export PDF/DOCX
│   ├── migrations/            # Alembic migrations
│   ├── requirements.txt
│   ├── Dockerfile
│   └── docker-compose.yml
```

---

## API Routers

| Router | Endpoint | Mô tả |
|--------|----------|--------|
| `auth.py` | `/api/v1/auth/*` | Đăng nhập, đăng ký, refresh token |
| `documents.py` | `/api/v1/documents/*` | Upload PDF, xử lý, chunking, curriculum tree |
| `exams.py` | `/api/v1/exams/*` | CRUD đề, approve/reject, export PDF/DOCX, history |
| `generate.py` | `/api/v1/generate/*` | Khởi tạo sinh đề, HITL approval |
| `courses.py` | `/api/v1/courses/*` | Placeholder (backlog) |

## WebSocket Endpoints

| Endpoint | Mô tả |
|----------|--------|
| `/ws/exam/{exam_id}` | Real-time exam generation streaming |
| `/ws/document/{document_id}` | Document upload/processing progress |

---

## Agent Pipeline (LangGraph)

```
User Request → Orchestrator → Retrieval → Outline → HITL 1 (Blueprint)
                                                      ↓ (approve)
                                                   Builder → Validator → HITL 2 (Review)
                                                                        ↓ (approve)
                                                                     Finalize → Export
```

### Agent Roles

1. **Orchestrator** — Điều phối toàn bộ pipeline qua LangGraph, xử lý HITL interrupts
2. **Retrieval** — Truy xuất chunks từ Pinecone theo scope (chapter)
3. **Outline** — Tạo blueprint với phân bổ Bloom: nhận biết, thông hiểu, vận dụng, vận dụng cao
4. **Builder** — Sinh MCQ (4 lựa chọn) và Essay (có rubric) từ blueprint
5. **Validator** — Kiểm tra scope, Bloom alignment, logic, duplicate, LaTeX

### Agent Skills

- `BloomClassifierSkill` — Xác nhận mức Bloom câu hỏi
- `DedupCheckerSkill` — Tránh trùng lặp nội dung
- `DifficultyEstimatorSkill` — Ước lượng độ khó
- `LatexRendererSkill` — Render công thức LaTeX
- `ScopeCheckerSkill` — Kiểm tra câu hỏi trong phạm vi cho phép

---

## Bắt đầu

### Yêu cầu

- Python 3.11+
- Node.js 20+
- PostgreSQL 16
- Redis 7
- Pinecone account
- MinIO (hoặc S3) cho file storage

### Backend

```bash
cd backend

# Virtual environment
python -m venv venv
source venv/Scripts/activate  # Linux: venv/bin/activate

# Dependencies
pip install -r requirements.txt

# Environment
cp .env.example .env
# Chỉnh sửa .env với API keys

# Migration
alembic upgrade head

# Chạy server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd Frontend
npm install
cp .env.example .env.local
npm run dev
```

### Celery Worker

```bash
cd backend
celery -A app.tasks.celery_app worker --loglevel=info
```

### Docker

```bash
cd backend
docker-compose up -d
```

---

## Biến môi trường quan trọng

| Variable | Mô tả |
|----------|--------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `PINECONE_API_KEY` | Pinecone API key |
| `OPENAI_API_KEY` | OpenAI API key (GPT-4o) |
| `JWT_SECRET_KEY` | Secret cho JWT tokens |
| `STORAGE_BACKEND` | `minio` hoặc `s3` |
| `MINIO_ENDPOINT` | MinIO endpoint |
| `MINIO_ACCESS_KEY` | MinIO access key |
| `MINIO_SECRET_KEY` | MinIO secret key |
| `NEXT_PUBLIC_API_URL` | Backend URL (frontend) |

---

## Công nghệ

| Layer | Công nghệ |
|-------|-----------|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS, Radix UI, Zod, React Hook Form, KaTeX |
| Backend | FastAPI, Pydantic v2, SQLAlchemy, Alembic, Celery, LangGraph |
| Database | PostgreSQL, Redis |
| Vector Store | Pinecone (BGE-m3 embeddings, CrossEncoder reranker) |
| Storage | MinIO / AWS S3 |
| LLM | OpenAI GPT-4o ( qua openai, openrouter, groq, anthropic, ollama) |
| Observability | Langfuse |

---

## Health Check

- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe (kiểm tra PostgreSQL, Redis, Pinecone)
