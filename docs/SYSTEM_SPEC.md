# SYSTEM_SPEC.md

> **Căn cứ:** Quét toàn bộ source code repo. Không mô tả chung chung, chỉ kết luận những gì có căn cứ từ code.
> **Nguyên tắc:** Ưu tiên đúng theo repo hiện tại, không viết kiểu tài liệu marketing.

---

## A. Tổng quan hệ thống

### Hệ thống dùng để làm gì

**ExamAI** là hệ thống tạo đề thi tự động từ tài liệu giảng dạy, sử dụng multi-agent AI pipeline với kiến trúc hỏi-đáp human-in-the-loop (HITL).

Input cốt lõi:
- Tài liệu giảng dạy (PDF, DOCX, PPTX) đã được upload và xử lý RAG
- Cấu hình đề thi (số câu, phân bố Bloom, phạm vi chương)
- Hướng dẫn tự nhiên từ giáo viên (tùy chọn)

Output:
- Bộ câu hỏi MCQ + Essay hoàn chỉnh (đề thi) với đầy đủ metadata
- Export PDF/DOCX
- Báo cáo chất lượng + chi phí token

### Người dùng chính

**Giáo viên** (hiện tại chỉ có role `teacher`, chưa có phân quyền khác).
Có thể mở rộng sau cho admin/supervisor — nhưng từ code hiện tại, chỉ có teacher.

### Bài toán nghiệp vụ chính

1. **Tạo đề thi tự động** — giáo viên upload tài liệu → AI sinh đề hoàn chỉnh, không cần viết tay
2. **Human-in-the-loop quality control** — đề sinh ra phải qua 3 checkpoint giáo viên duyệt (sườn đề, câu hỏi, preview)
3. **Học từ phản hồi** — giáo viên phản hồi đề → hệ thống học sở thích giáo viên (long-term memory)
4. **Đa dạng định dạng** — xuất PDF/DOCX, đa dạng loại câu hỏi

### Giá trị cốt lõi

- **Tự động hóa hoàn toàn** việc tạo đề từ tài liệu
- **Kiểm soát chất lượng** qua HITL checkpoints
- **Cá nhân hóa** theo sở thích giáo viên qua long-term memory
- **Bloom taxonomy alignment** — câu hỏi được phân loại theo 4 mức nhận thức

---

## B. Kiến trúc tổng thể

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CLIENT (Browser)                                │
│   Next.js 16 (App Router)  │  React 19  │  Tailwind v4  │  Radix UI     │
└──────────────┬──────────────────────────────────────────────────────────┘
               │ HTTP REST + WebSocket ws://host:8000/ws/exam/{id}
               │ (Bearer JWT, auto-refresh token)
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FASTAPI BACKEND (uvicorn)                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ Auth Router   │  │ Docs Router  │  │ Exams Router  │  │ Gen Router │  │
│  │ POST /login   │  │ POST /upload │  │ POST /generate│  │ POST /exam │  │
│  │ POST /refresh  │  │ GET /{id}    │  │ GET /{id}     │  │            │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘  │
│                                                                   ↑    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ WebSocket    │  │ Courses      │  │ Playbook     │  │            │  │
│  │ WS /ws/exam  │  │ (placeholder)│  │ (placeholder)│  │            │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘  │
└──────┬─────┬─────┬─────┬──────────────┬──────────────────────────────────┘
       │     │     │     │              │
       ▼     ▼     ▼     ▼              ▼
   PostgreSQL  Redis  MinIO/S3      LLM (Groq/OpenAI/etc.)
   (data)    (cache,  (file        sentence-transformers
              pub/sub) storage)    Pinecone (vectors)
                                   LangFuse (observability)
                                   Qwen Vision (OCR via ngrok)

┌─────────────────────────────────────────────────────────────────────────┐
│                    CELERY WORKER (background)                           │
│  - generate_exam_task: chạy pipeline khi user ấn regenerate/reject        │
│  - process_document_task: full RAG pipeline                              │
│  Broker: Redis │ Backend: Redis                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                    MULTI-AGENT AI PIPELINE                              │
│  OrchestratorAgent (Agent 0)                                             │
│    ├── PlannerAgent (Agent 5) — complex requests only                   │
│    │   └── → DEFAULT_PLAN: retrieve → outline → build → validate         │
│    ├── RetrievalAgent (Agent 1) → Pinecone (vector search)              │
│    ├── OutlineAgent (Agent 2) → LLM (exam blueprint/sườn đề)           │
│    ├── BuilderAgent (Agent 3) → LLM + Skills                           │
│    │       ├── BloomClassifierSkill                                    │
│    │       ├── DedupCheckerSkill                                       │
│    │       ├── DifficultyEstimatorSkill                                │
│    │       ├── ScopeCheckerSkill                                       │
│    │       └── LatexRendererSkill                                      │
│    └── ValidatorAgent (Agent 4) → LLM + Skills (answer correctness)   │
│                                                                     │   │
│  Memory: ShortTermMemory (Redis TTL 2h) + LongTermMemory (PostgreSQL)  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Luồng dữ liệu chính

1. **Upload flow:** File → S3 → DB record (pending) → Background RAG task → Pinecone vectors
2. **Generation flow:** User request → Orchestrator → 4 sub-agents → Questions saved to DB → WebSocket events → FE live viewer
3. **HITL flow:** Checkpoint → Redis flag → FE polls → User approves/rejects → Pipeline continues
4. **Export flow:** Exam questions → WeasyPrint/python-docx → PDF/DOCX response

---

## C. Cấu trúc thư mục quan trọng

### Backend (`backend/`)

```
backend/
├── app/
│   ├── main.py                          # FastAPI entry, lifespan, routes, WS endpoint
│   ├── config.py                        # Re-export Settings from core.config
│   ├── dependencies.py                  # Auth helpers, password hashing, JWT, pagination
│   │
│   ├── agents/                          # [QUAN TRỌNG] Multi-agent AI system
│   │   ├── base.py                      # AgentBaseOutput, AgentStatus, TokenUsage, ContentFilterRules
│   │   ├── llm.py                       # Unified LLM client (Groq, OpenAI, Ollama, Anthropic, g4f, QwenVision)
│   │   ├── orchestrator.py              # Agent 0 - điều phối toàn pipeline
│   │   ├── retrieval.py                 # Agent 1 - query Pinecone vector DB
│   │   ├── outline.py                   # Agent 2 - tạo sườn đề
│   │   ├── builder.py                   # Agent 3 - sinh câu hỏi thực tế
│   │   ├── validator.py                  # Agent 4 - kiểm tra chất lượng
│   │   ├── planner.py                    # Agent 5 - lập kế hoạch cho request phức tạp
│   │   ├── guardrails.py                # Token budget + content filtering
│   │   ├── memory/
│   │   │   ├── short_term.py            # Redis-based session memory (TTL 2h)
│   │   │   └── long_term.py             # PostgreSQL teacher preferences
│   │   └── skills/
│   │       ├── bloom_classifier.py      # Phân loại Bloom level bằng LLM
│   │       ├── dedup_checker.py         # Phát hiện câu trùng lặp
│   │       ├── difficulty_estimator.py  # Ước lượng độ khó 0.0-1.0
│   │       ├── scope_checker.py         # Kiểm tra câu ngoài phạm vi
│   │       └── latex_renderer.py         # Render công thức LaTeX
│   │
│   ├── core/
│   │   ├── config.py                    # Pydantic Settings, 80+ env vars, get_settings()
│   │   ├── database.py                  # async SQLAlchemy engine, sessionmaker, init_db()
│   │   └── redis_client.py              # Redis wrapper (get/set/incr/pubsub)
│   │
│   ├── models/                          # SQLAlchemy ORM models
│   │   ├── user.py                      # users table
│   │   ├── document.py                  # documents table
│   │   ├── exam.py                      # exams + exam_history tables
│   │   ├── refresh_token.py             # refresh_tokens table (SHA256 hash)
│   │   └── teacher_preference.py        # teacher_preferences table (1-to-1 with User)
│   │
│   ├── schemas/                         # Pydantic request/response schemas
│   │   ├── auth.py                      # Register/Login/Refresh/UserResponse
│   │   ├── document.py                  # Upload response, heading tree, curriculum tree
│   │   ├── exam.py                      # ExamConfigRequest, QuestionResponse, all HITL schemas
│   │   └── agent.py                     # Re-exports agent output models
│   │
│   ├── routers/                         # FastAPI route handlers
│   │   ├── auth.py                      # /api/v1/auth/*
│   │   ├── documents.py                 # /api/v1/documents/*
│   │   ├── exams.py                     # /api/v1/exams/* (generate, edit, export, HITL)
│   │   ├── generate.py                  # /api/v1/generate/* (FE bridge)
│   │   ├── courses.py                   # /api/v1/courses/* (placeholder stubs)
│   │   └── playbook.py                  # /api/v1/playbook/* (placeholder stubs)
│   │
│   ├── services/                        # Business logic layer
│   │   ├── auth_service.py              # Register, login, refresh, logout
│   │   ├── document_service.py          # Upload, delete, process (RAG pipeline), curriculum
│   │   └── exam_service.py              # CRUD, versioning, partial edit
│   │
│   ├── rag/                             # [QUAN TRỌNG] RAG pipeline
│   │   ├── parser.py                    # parse_document(): PDF(Docker/Marker+PyMuPDF)/DOCX/PPTX → markdown
│   │   ├── structure.py                 # detect_heading_tree(), normalize_chapter_id()
│   │   ├── chunker.py                   # semantic_chunk(): markdown → chunks với chapter_id
│   │   ├── embedder.py                  # EmbeddingService (sentence-transformers local, 768-dim)
│   │   ├── vector_store.py              # VectorStore: Pinecone CRUD per chapter namespace
│   │   └── extractor.py                 # Trích xuất LaTeX từ content
│   │
│   ├── tasks/                           # Celery background jobs
│   │   ├── celery_app.py               # Celery instance (Redis broker)
│   │   ├── exam_task.py                # generate_exam_task (pipeline)
│   │   └── document_task.py            # process_document_task (RAG)
│   │
│   ├── websocket/
│   │   └── manager.py                   # ConnectionManager: WebSocket + Redis pub/sub
│   │
│   ├── utils/
│   │   ├── storage/                     # StorageBackend abstraction
│   │   │   ├── base.py                  # Abstract class
│   │   │   ├── minio_backend.py        # MinIO implementation
│   │   │   └── s3_backend.py           # AWS S3 implementation
│   │   ├── export.py                    # ExamExporter: PDF (WeasyPrint) + DOCX (python-docx)
│   │   ├── search.py                    # search_similar_problems() (SERPAPI, G4)
│   │   ├── security.py                  # Password hashing helpers
│   │   └── qwen_vision.py              # OCR + image description via self-hosted Qwen3.5-9B
│   │
│   └── observability/
│       ├── tracer.py                    # LangFuse decorator @tracer.agent_span()
│       ├── langfuse_client.py          # LangFuse client init
│       └── cost.py                      # Token cost calculation
│
├── migrations/                          # Alembic migrations
│   └── versions/
│       ├── 001_initial.py               # Initial schema
│       ├── bd3064db5e63_add_course_id.py
│       └── add_file_size_to_documents.py
│
├── requirements.txt                      # 35+ Python packages
├── alembic.ini
├── Dockerfile
└── docker-compose.yml
```

### Frontend (`UI/`)

```
UI/
├── app/                                 # Next.js App Router
│   ├── page.tsx                         # Login/Register page (/)
│   ├── layout.tsx                       # Root layout with AuthProvider
│   ├── dashboard/
│   │   ├── layout.tsx                   # Sidebar wrapper
│   │   ├── page.tsx                     # Dashboard home (quality metrics)
│   │   ├── exams/[id]/page.tsx          # Exam detail/editor (largest page, 741 lines)
│   │   ├── generate/page.tsx            # 3-step generation wizard
│   │   ├── documents/page.tsx            # Document upload + management
│   │   ├── history/page.tsx              # Exam version history
│   │   ├── playbook/page.tsx            # Playbook bullets (placeholder content)
│   │   ├── feedback/page.tsx             # Feedback store signals
│   │   └── settings/page.tsx             # Settings page
│
├── components/
│   ├── app-sidebar.tsx                   # Navigation sidebar (collapsible)
│   ├── dashboard-header.tsx              # Top header (theme, bell, breadcrumb)
│   ├── auth-provider.tsx                # AuthContext + useAuth() hook
│   ├── generation-live-viewer.tsx        # WebSocket-driven live generation log
│   ├── generation-loading-screen.tsx    # Loading states
│   ├── generation-stepper.tsx           # Step progress indicator
│   ├── theme-provider.tsx               # next-themes dark/light
│   └── ui/                              # ~53 shadcn/ui components
│       ├── button, input, card, badge, dialog, select
│       ├── textarea, checkbox, table, tabs, skeleton, spinner
│       ├── progress, slider, popover, chart (recharts)
│       ├── carousel, calendar, form, alert, accordion, command
│       ├── collapsible, separator, scroll-area, navigation-menu
│       ├── menubar, dropdown-menu, sheet, drawer, tooltip
│       ├── label, radio-group, kbd, toggle, switch, pagination
│       ├── resizable, alert-dialog, aspect-ratio, input-otp
│       ├── avatar, breadcrumb, hover-card, item, empty
│       ├── field, context-menu, use-mobile, input-group, sonner
│
├── lib/
│   ├── api.ts                           # [QUAN TRỌNG] Full API client, 1100+ lines
│   │                                     # Auth + documents + exams + generation + WebSocket
│   ├── quality.ts                        # Quality data formatting helpers
│   └── utils.ts                          # General utilities (cn)
│
├── next.config.mjs
└── package.json                          # Next.js 16, React 19, ~40 packages
```

---

## D. Luồng nghiệp vụ chính

### Flow 1: Authentication

**Điểm bắt đầu:** `POST /api/v1/auth/register` hoặc `POST /api/v1/auth/login`

**Endpoint sequence:**
1. `POST /auth/register` → `AuthService.register()` → bcrypt hash → DB insert → return `UserResponse`
2. `POST /auth/login` → `AuthService.login()` → verify bcrypt → generate JWT (15min) + refresh token (7 days) → store SHA256(refresh_token) in DB → return `{access_token, refresh_token}`
3. `POST /auth/refresh` → verify JWT + SHA256(refresh_token) in DB → rotate (revoke old, issue new) → return new access token
4. `GET /auth/me` → decode JWT → DB lookup → return `UserResponse`

**Dữ liệu:** `users.email`, `users.password_hash` (bcrypt), `users.full_name`, `refresh_tokens.token_hash` (SHA256)
**Lưu trữ:** PostgreSQL `users` + `refresh_tokens`
**Rate limit:** 5 login attempts/IP/minute via Redis `incr_rate_limit()`

---

### Flow 2: Document Upload & RAG Processing

**Điểm bắt đầu:** `POST /api/v1/documents/upload`

**Endpoint sequence:**
1. `POST /documents/upload` → `DocumentService.upload_document()` → upload file to MinIO/S3 → create DB record (`status=pending`)
2. `DocumentService.process_document()` được gọi ngay sau upload (trong cùng request context):
   - `parse_document()` — PDF (Marker→fallback PyMuPDF) / DOCX (python-docx) / PPTX (python-pptx) → markdown
   - `detect_heading_tree()` — parse `# ## ###` → nested chapter/section/subsection
   - `semantic_chunk()` — split markdown thành chunks với chapter_id gắn vào
   - `embed_chunks()` — sentence-transformers `paraphrase-multilingual-mpnet-base-v2` → 768-dim vectors
   - `upsert_chunks()` → Pinecone với namespace `{doc_id}_{chapter_id}`
3. Update DB record: `status=completed`, `heading_tree`, `total_chapters`, `total_chunks`

**GET polling:** `GET /documents/{id}/status` → trả về `processing_status` hiện tại

**Dữ liệu:** File binary → MinIO/S3 → markdown → chunks → Pinecone vectors
**Lưu trữ:** MinIO/S3 (file) + PostgreSQL `documents` (metadata) + Pinecone (vectors)
**Các endpoint liên quan:**
- `GET /documents/` — paginated list
- `GET /documents/{id}` — full detail với heading_tree
- `GET /documents/{id}/curriculum-tree` — flatten heading_tree → `CurriculumNode[]`
- `PATCH /documents/{id}/curriculum-tree` — persist FE-edited tree
- `DELETE /documents/{id}` — xóa khỏi S3 + Pinecone + DB

---

### Flow 3: Exam Generation (Multi-Agent Pipeline)

**Điểm bắt đầu:** `POST /api/v1/generate/exam` hoặc `POST /api/v1/exams/generate`

**Sequence từng bước:**

```
User sends POST /generate/exam
    │
    ├─ [G13] Rate limit check (max 10/user/day, Redis)
    │
    ├─ Create Exam record (status="draft", no questions yet)
    │
    ├─ Return immediately: {exam_id, websocket_url, scope_warning}
    │   Client connects WebSocket ws://host:8000/ws/exam/{exam_id}
    │
    ├─ Run generation inline (FastAPI background task):
    │
    ├─ [G6] Orchestrator._is_complex_request()
    │       Complex if: prompt>200chars OR keywords OR extra_instructions OR bloom+prompt>100chars
    │       Complex → use PlannerAgent
    │       Simple → use DEFAULT_PLAN: retrieve→outline→build→validate
    │
    ├─ [HITL Checkpoint 0] Emit requirements_confirmation via WS
    │
    ├─ [Step 1] RetrievalAgent.retrieve()
    │       ├─ [G11] Query expansion (3-5 variants per chapter via LLM)
    │       ├─ [G10] Parallel query per chapter via Pinecone
    │       ├─ LLM reranking: top-20 → top-8 per chapter
    │       └─ Token budget enforcement: hard cap MAX_CONTEXT_TOKENS (3000 tokens)
    │       Output: retrieved_context + coverage_map
    │
    ├─ [Step 2] OutlineAgent.create_outline()
    │       ├─ LLM generates exam blueprint (sườn đề)
    │       ├─ Blueprint = list of blueprint slots (question_id, bloom_level, chapter, topic_hint...)
    │       ├─ Validate: no chapter > 50%
    │       ├─ [G8] Support outline_feedback from HITL rejection
    │       └─ [HITL Checkpoint 1] PAUSE — poll Redis for approval (30min timeout)
    │
    │       ┌─ HITL1: User approves (approve_blueprint endpoint)
    │       │      Redis key hitl:approved:{exam_id}:1 = "true"
    │       │      Pipeline unblocks and continues
    │       └─ HITL1: User rejects (reject_blueprint endpoint)
    │              Orchestrator saves feedback + re-runs OutlineAgent with feedback
    │
    ├─ [Step 3] BuilderAgent.build()
    │       ├─ LLM generates 8 questions per call
    │       ├─ Per question: content_filter → bloom_classifier → dedup_checker → difficulty_estimator → latex_renderer
    │       ├─ [G4] van_dung_cao slots: search_similar_problems() (SERPAPI) → adapt into scope
    │       ├─ Emit question_generated event via WS per question
    │       ├─ Topics tracked in Redis (topics_used)
    │       └─ [G9] Retry issues from Redis for failed slots
    │
    ├─ [Step 4] ValidatorAgent.validate()
    │       ├─ Per question: bloom_classifier + scope_checker (skill-based)
    │       ├─ LLM call: answer correctness + bloom compliance + scope compliance
    │       └─ Emit validation_result event
    │
    ├─ [Retry Loop, max 3 times]
    │       Filter bad slots → regenerate only those → re-validate
    │
    ├─ [HITL Checkpoint 2] Emit questions + quality_scores + cost_report
    │
    ├─ [HITL Checkpoint 3] Emit HTML preview (no PDF conversion)
    │
    ├─ [G14] Save teacher preferences to LongTermMemory (PostgreSQL)
    │
    ├─ [G12] ExamService.update_questions(): persist questions + cost_report + snapshot
    │
    └─ Emit completed event + exam_id + total_cost_usd via WS
```

**Output cuối cùng:** `Exam` record với `questions` JSONB, `cost_report` JSONB, `status=draft/published`

---

### Flow 4: Document Curation (Curriculum Tree)

**Điểm bắt đầu:** `GET /api/v1/documents/{id}/curriculum-tree`

**Sequence:**
1. `GET /documents/{id}/curriculum-tree` → `flatten_heading_tree()` → list of `CurriculumNode` (flattened, FE-friendly format)
2. FE cho phép giáo viên edit curriculum tree
3. `PATCH /documents/{id}/curriculum-tree` → FE gửi flat list → `DocumentService.update_curriculum_tree()` → rebuild nested tree → save to DB

**Mục đích:** Giáo viên có thể merge/split/reorder chapters để kiểm soát phạm vi đề thi.

---

### Flow 5: HITL Checkpoint Review (Blueprint → Questions → Preview)

**Gồm 3 checkpoint:**

**HITL1 — Blueprint Review (Sườn đề):**
- `GET /exams/{id}/review-data` → return blueprint slots + distribution_summary
- `POST /exams/{id}/approve-blueprint` → unblock pipeline (set Redis key)
- `POST /exams/{id}/reject-blueprint` → save feedback (G8) → re-run OutlineAgent

**HITL2 — Full Question Review:**
- `GET /exams/{id}/review-data` → return full questions + quality_scores + cost_report
- `POST /exams/{id}/submit-review` → `approved=true` → save preferences (G14) + mark ready; `approved=false` → dispatch Celery task to regenerate

**HITL3 — Export Preview:**
- `GET /exams/{id}/preview` → render HTML (student/teacher version, no PDF conversion)
- Teacher version: answers + explanations + rubric + blueprint table
- Student version: no answers

---

### Flow 6: Edit & Regenerate Questions

**Inline edit:**
- `PATCH /exams/{id}/questions/{question_id}` → `ExamService.update_question()` → save + snapshot
- `POST /exams/{id}/edit-prompt` → LLM parses natural language instruction → apply to questions

**Partial regenerate:**
- `POST /generate/partial-regenerate` → `ExamService.partial_regenerate()` → lightweight edit (delete/lock/edit_text/edit_answer/edit_bloom/edit_options per question)

**Full regenerate:**
- `POST /exams/{id}/regenerate` → dispatch Celery task `generate_exam_task()` → re-run full pipeline

---

### Flow 7: Export

**Điểm bắt đầu:** `GET /api/v1/exams/{id}/export/pdf` hoặc `/export/docx`

**Sequence:**
1. `ExamExporter._render_html()` → build HTML from questions
2. PDF: `weasyprint` HTML → binary response (max 10MB)
3. DOCX: `python-docx` Document → binary response

**Options:** `include_answers`, `include_blueprint`

---

### Flow 8: Version History

**Sequence:**
1. Mỗi thay đổi (generate/edit/regenerate/publish/restore) → tạo `ExamHistory` snapshot
2. `GET /exams/{id}/versions` → list all snapshots (newest first)
3. `POST /exams/{id}/history/{history_id}/restore` → restore Exam state from snapshot + create restore history entry

---

## E. API Spec thực tế từ code

### Auth Router (`/api/v1/auth`)

| Method | Path | Mục đích | Auth | Service |
|--------|------|---------|------|---------|
| `POST` | `/register` | Tạo tài khoản teacher | No | `AuthService.register(email, password, full_name)` → bcrypt → DB |
| `POST` | `/login` | Đăng nhập | No | `AuthService.login(email, password, ip)` → JWT + refresh token (SHA256 hash in DB) |
| `POST` | `/refresh` | Refresh access token | No | `AuthService.refresh(refresh_token)` → token rotation |
| `POST` | `/logout` | Đăng xuất | No | Revoke refresh token hash in DB |
| `GET` | `/me` | Lấy profile hiện tại | Bearer | Return `UserResponse` (id, email, full_name, role, created_at) |

**Register body:** `{"email": "a@b.com", "password": "min8chars", "full_name": "Nguyen Van A"}`
**Login response:** `{"access_token": "eyJ...", "refresh_token": "eyJ...", "token_type": "bearer", "expires_in": 900}`
**Refresh body:** `{"refresh_token": "eyJ..."}`

---

### Document Router (`/api/v1/documents`)

| Method | Path | Mục đích | Auth |
|--------|------|---------|------|
| `POST` | `/upload` | Upload file, trigger RAG processing | Bearer |
| `GET` | `/` | Paginated document list | Bearer |
| `GET` | `/{document_id}` | Full document detail (heading_tree) | Bearer |
| `GET` | `/{document_id}/status` | Poll processing status | Bearer |
| `DELETE` | `/{document_id}` | Delete from S3 + Pinecone + DB | Bearer |
| `GET` | `/{document_id}/refresh-url` | Fresh presigned URL (G20, TTL 1h) | Bearer |
| `GET` | `/{document_id}/curriculum-tree` | Flatten heading tree → FE nodes | Bearer |
| `PATCH` | `/{document_id}/curriculum-tree` | Persist FE-edited tree | Bearer |
| `POST` | `/{document_id}/rescan-structure` | Re-detect headings (unprocessed docs) | Bearer |
| `POST` | `/{document_id}/reprocess` | Re-chunk + re-upsert to Pinecone | Bearer |

**Upload request:** `multipart/form-data`, field `file` (PDF/DOCX/PPTX, max 100MB)
**Upload response:** `{"document_id": "uuid", "s3_key": "...", "message": "...", "processing_status": "pending", "uploaded_at": "..."}`
**Status values:** `pending` → `processing` → `completed` / `failed`

---

### Generate Router (`/api/v1/generate`)

| Method | Path | Mục đích | Auth |
|--------|------|---------|------|
| `POST` | `/exam` | Trigger generation (FE-compatible) | Bearer |
| `POST` | `/partial-regenerate` | Partial edit (FE-compatible) | Bearer |

**POST /exam request (ExamGenerationRequest from FE → ExamConfigRequest):**
```json
{
  "document_id": "uuid",
  "scope": ["Chương 1: Dao động"],
  "exam_type": "mixed",
  "mcq_count": 10,
  "essay_count": 2,
  "bloom_distribution": {
    "nhan_biet": 20,
    "thong_hieu": 30,
    "van_dung": 30,
    "van_dung_cao": 20
  },
  "user_prompt": "Tạo đề kiểm tra...",
  "extra_instructions": "...",
  "strict_scope_flag": true
}
```

**Response:** `{"exam_id": "uuid", "job_id": "uuid", "websocket_url": "ws://...", "scope_warning": null}`
**Ghi chú:** Scope format FE `["A.QUANG HÌNH HỌC"]` → canonical chapter_id normalization in `_run_generation_inline`
**Ghi chú:** Scope guard — if chunks > 200 → reject request

---

### Exam Router (`/api/v1/exams`)

#### Core
| Method | Path | Mục đích |
|--------|------|---------|
| `POST` | `/generate` | Start generation (rate limited, max 10/day/user) |
| `GET` | `/` | Paginated exam list |
| `GET` | `/{exam_id}` | Full exam detail |
| `GET` | `/{exam_id}/versions` | Version history |
| `GET` | `/{exam_id}/feedback` | Paginated feedback events |
| `POST` | `/{exam_id}/publish` | Mark published + save teacher prefs |
| `DELETE` | `/{exam_id}` | Delete exam |

#### Edit
| Method | Path | Mục đích |
|--------|------|---------|
| `PATCH` | `/{exam_id}/questions/{question_id}` | Edit single question |
| `POST` | `/{exam_id}/edit-prompt` | Natural language edit via LLM |
| `POST` | `/{exam_id}/regenerate` | Regenerate questions (Celery) |
| `GET` | `/{exam_id}/history` | All version snapshots |
| `POST` | `/{exam_id}/history/{history_id}/restore` | Restore from snapshot |

#### Export
| Method | Path | Mục đích |
|--------|------|---------|
| `GET` | `/{exam_id}/export/pdf` | WeasyPrint PDF |
| `GET` | `/{exam_id}/export/docx` | python-docx DOCX |

#### HITL
| Method | Path | Mục đích |
|--------|------|---------|
| `POST` | `/{exam_id}/approve-blueprint` | Unblock HITL1 |
| `POST` | `/{exam_id}/reject-blueprint` | G8: save feedback, re-run outline |
| `GET` | `/{exam_id}/review-data` | Full review data |
| `GET` | `/{exam_id}/preview` | HTML preview |
| `POST` | `/{exam_id}/submit-review` | HITL2: approve/reject |

#### Analytics
| Method | Path | Mục đích |
|--------|------|---------|
| `GET` | `/quality-summary` | Aggregated quality across all user exams |
| `GET` | `/feedback-summary` | Feedback store summary |
| `GET` | `/feedback-store` | Paginated feedback events |

---

### Courses Router (`/api/v1/courses`) — **ALL STUBS**

All endpoints return 501 or empty list. Course management is not implemented.

---

### Playbook Router (`/api/v1/playbook`) — **ALL STUBS**

All endpoints return 501. Playbook feature is Phase 4 backlog.

---

## F. Data Model / Schema / Database

### Database: PostgreSQL (async via asyncpg)

### Tables

#### `users`
```sql
id          UUID PK (auto)
email       VARCHAR(255) UNIQUE INDEXED
password_hash VARCHAR(255)  -- bcrypt
full_name   VARCHAR(255) NULL
role        VARCHAR(50) DEFAULT 'teacher'
created_at  DATETIME default now()
```

#### `documents`
```sql
id                   UUID PK
user_id              UUID FK → users.id INDEXED
course_id            UUID FK → courses NULLABLE INDEXED
file_size            INTEGER NULLABLE
original_filename    VARCHAR(500)
file_type            VARCHAR(10)  -- pdf/docx/pptx
s3_key               VARCHAR(1000)
processing_status    VARCHAR(50) DEFAULT 'pending' INDEXED
                     -- pending → processing → completed / failed
parse_error_message  VARCHAR(2000) NULLABLE
heading_tree         JSONB NULLABLE  -- nested chapter/section/subsection
total_chapters       INTEGER NULLABLE
total_pages_or_slides INTEGER NULLABLE
total_chunks         INTEGER NULLABLE
uploaded_at          DATETIME
```

#### `exams`
```sql
id               UUID PK
user_id          UUID FK → users.id INDEXED
document_id      UUID FK → documents.id SET NULL NULLABLE
title            VARCHAR(500)
scope            JSONB NULLABLE  -- list of chapter titles
exam_config      JSONB NULLABLE  -- full config dict (bloom, mcq_count, etc.)
questions        JSONB NULLABLE  -- list of question dicts
status           VARCHAR(50) DEFAULT 'draft'
                 -- draft / ready_for_review / regenerating / published
cost_report      JSONB NULLABLE  -- token usage + cost breakdown
total_tokens     INTEGER NULLABLE
total_cost_usd   DECIMAL(10,4) NULLABLE
created_at       DATETIME
updated_at       DATETIME
```

#### `exam_history` (version snapshots)
```sql
id               UUID PK
exam_id          UUID FK → exams.id INDEXED
snapshot         JSONB NULLABLE  -- full exam state
change_type      VARCHAR(50)     -- generate/edit_direct/edit_prompt/regenerate/published/restore
change_description TEXT NULLABLE
created_at       DATETIME
```

#### `refresh_tokens`
```sql
id         UUID PK
user_id    UUID FK → users.id INDEXED
token_hash VARCHAR(255)  -- SHA256 of actual JWT
expires_at DATETIME
revoked    BOOLEAN DEFAULT False
created_at DATETIME
```

#### `teacher_preferences` (PK = user_id, 1-to-1 with users)
```sql
user_id                         UUID PK FK → users.id
preferred_bloom_distribution    JSONB NULLABLE
preferred_exam_types             JSONB NULLABLE
subject_focus                    VARCHAR(100) NULLABLE
style_notes                      TEXT NULLABLE
updated_at                       DATETIME
```

### Question Schema (JSONB in `exams.questions`)

```json
{
  "question_id": "MCQ_001",
  "type": "mcq",               // "mcq" | "essay"
  "bloom_level": "thong_hieu",  // nhan_biet | thong_hieu | van_dung | van_dung_cao
  "chapter": "Chương 1",
  "section": "1.2 Định luật Newton",
  "stem": "Câu hỏi...",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},  // MCQ only
  "correct_answer": "B",        // MCQ only
  "rubric": [...],              // Essay only
  "explanation": "...",
  "latex_content": "F = ma",    // optional
  "topic_hint": "...",
  "source_evidence": [
    {
      "document_id": "uuid",
      "chunk_id": "...",
      "chapter_number": 1,
      "page": 5,
      "role": "primary",
      "score": 0.92,
      "text_preview": "..."
    }
  ],
  "quality_score": 0.85,
  "is_validated": true,
  "warnings": [],
  "estimated_difficulty": 0.6
}
```

---

## G. Thành phần hạ tầng và kỹ thuật

### Database
- **PostgreSQL** — primary relational DB, async via `asyncpg` + SQLAlchemy
- **Alembic** — migrations (3 migrations total: initial + course_id + file_size)
- Default connection: `postgresql+asyncpg://postgres:postgres@localhost:5432/curriculum_ai`

### Cache / Queue / PubSub
- **Redis** — cache, rate limiting, short-term session memory (TTL 2h), Redis pub/sub for WebSocket broadcast, HITL checkpoint flags, Celery broker/backend
- Default: `redis://localhost:6379/0` (cache) + `redis://localhost:6379/1` (Celery)

### Vector DB
- **Pinecone** — vector similarity search, per-chapter namespace (`{doc_id}_{chapter_id}`)
- Model: `paraphrase-multilingual-mpnet-base-v2` (768-dim, local sentence-transformers)
- Free tier cloud: AWS `us-east-1`

### File Storage
- **MinIO** (default, local S3-compatible) — file upload/download
- **AWS S3** — alternative (set `STORAGE_BACKEND=s3`)
- Presigned URL TTL: 3600s (G20)

### Worker / Background Jobs
- **Celery** — background task queue for exam generation and document reprocessing
- Broker: Redis `/1`
- Used for: `generate_exam_task` (rejections/reviews), `process_document_task`

### WebSocket
- **FastAPI WebSocket** `/ws/exam/{exam_id}` — real-time generation events
- **Redis pub/sub** — `exam:{exam_id}` channel to broadcast events to multiple clients
- Event types: `plan_step`, `question_generated`, `validation_result`, `hitl_checkpoint`, `completed`, `error`, `clarification_needed`, `pipeline_paused`

### LLM Providers (fallback chain)
- Primary: **Groq** (fast, free tier) — `llama-3.3-70b-versatile`
- Fallback chain: `groq,ollama,g4f`
- Role routing: STRONG_ROLES (orchestrator, builder, validator) → `LLM_MODEL_STRONG`; LIGHT_ROLES → `LLM_MODEL_LIGHT`
- Vision: `llama-3.2-11b-vision-preview` via Groq

### Embedding
- **Local sentence-transformers** — `paraphrase-multilingual-mpnet-base-v2`
- 768-dim vectors
- No cloud API needed (free, offline)

### OCR / Image Processing
- **Qwen Vision** (primary) — self-hosted via ngrok, `QWEN_VISION_BASE_URL` env var
- **Marker PDF** (primary PDF parser) — GPU-accelerated deep learning PDF parsing
- **PyMuPDF** (fallback) — PDF parsing with custom heading detection
- **python-docx** / **python-pptx** — DOCX/PPTX parsing

### Observability
- **LangFuse** — LLM tracing, cost tracking, agent span instrumentation
- `@tracer.agent_span()` decorator on agent methods
- Config: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`

### Cách chạy local/dev

```bash
# Backend
cd backend
cp .env.example .env  # fill in API keys
uvicorn app.main:app --reload --port 8000

# Dependencies
# PostgreSQL on localhost:5432
# Redis on localhost:6379
# MinIO on localhost:9000 (credentials: minioadmin/minioadmin)
# Pinecone cloud (free tier)
# Groq API key (free tier)

# Frontend
cd UI
npm install
npm run dev  # runs on port 3000
```

---

## H. AI/LLM/Document Pipeline

### Document → Embeddings Pipeline

```
PDF/DOCX/PPTX (upload)
    │
    ▼
parse_document()
    ├── PDF: Marker (GPU DL) → fallback PyMuPDF
    │         Page markers: <!-- Page N -->
    │         Heading detection: font size + bold heuristics
    ├── DOCX: python-docx → markdown (headings, tables)
    └── PPTX: python-pptx → markdown (## Slide N: title)
    │
    ▼
detect_heading_tree() — parse # ## ### → nested structure
    │
    ▼
semantic_chunk() — split markdown
    chunks: {text, chapter_id, chunk_index, start_line, end_line}
    chunk_size: 1200 chars, overlap: 200 chars
    │
    ▼
embed_chunks() — sentence-transformers
    model: paraphrase-multilingual-mpnet-base-v2
    dim: 768
    Cache: Redis TTL 7 days
    │
    ▼
upsert_chunks() → Pinecone
    namespace: {doc_id}_{chapter_id} (ASCII-safe)
    upsert with document_id metadata
```

### Multi-Agent Pipeline (Exam Generation)

```
OrchestratorAgent (Agent 0)
  │
  ├─ [G6] is_complex?
  │     Complex → PlannerAgent → DEFAULT_PLAN
  │     Simple → DEFAULT_PLAN: retrieve → outline → build → validate
  │
  ├─ [G7] LongTermMemory.load_preferences(user_id)
  │
  ├─ [HITL Checkpoint 0] Emit requirements_confirmation
  │
  ├─ [Step 1] RetrievalAgent
  │     ├─ [G11] _expand_queries() — LLM generates 3-5 query variants
  │     ├─ [G10] _parallel_query_chapters() — asyncio.gather per chapter
  │     ├─ Pinecone query per chapter (top_k=20)
  │     ├─ Token budget enforcement: MAX_CONTEXT_TOKENS (3000 tokens)
  │     ├─ [RERANK] LLM rerank: top-20 → top-8
  │     └─ Output: {chunks, coverage_map, query_log}
  │
  ├─ [Step 2] OutlineAgent
  │     ├─ LLM generates exam blueprint (sườn đề)
  │     ├─ Blueprint slots: question_id, bloom_level, chapter, topic_hint, content_type, difficulty
  │     ├─ Validate distribution (no chapter > 50%)
  │     ├─ [G8] outline_feedback support
  │     └─ [HITL Checkpoint 1] PAUSE (30min timeout via Redis polling)
  │
  ├─ [Step 3] BuilderAgent
  │     ├─ Batch: 8 questions per LLM call
  │     ├─ Per question pipeline:
  │     │     1. LLM generate
  │     │     2. ContentFilterRules.validate_batch()
  │     │     3. BloomClassifierSkill.run() → classify bloom
  │     │     4. DedupCheckerSkill.run() → detect duplicates
  │     │     5. DifficultyEstimatorSkill.run() → 0.0-1.0
  │     │     6. LatexRendererSkill.run() → render formulas
  │     │     7. Map evidence_chunks → source_evidence
  │     ├─ [G4] van_dung_cao: search_similar_problems() via SERPAPI → adapt
  │     ├─ [G9] load_retry_issues from Redis
  │     └─ Emit question_generated via WS
  │
  ├─ [Step 4] ValidatorAgent
  │     ├─ Skill-based: BloomClassifier + ScopeChecker per question
  │     ├─ LLM validation: answer correctness, bloom compliance, scope compliance
  │     ├─ Merge issues: skill-found + LLM-found (no deduplication — audit trail)
  │     └─ Bloom distribution compliance check
  │
  ├─ [Retry Loop, max 3]
  │     filter bad slots → regenerate only those → re-validate
  │
  ├─ [HITL Checkpoint 2] questions + quality_scores + cost_report
  │
  ├─ [HITL Checkpoint 3] HTML preview (no PDF conversion)
  │
  ├─ [G14] LongTermMemory.save_preferences(user_id, exam_config)
  │
  └─ save questions + cost_report to Exam record
```

### LLM Role Routing

| Role | Model | Used By |
|------|-------|---------|
| STRONG (orchestrator, builder, validator) | `llama-3.3-70b-versatile` (Groq) | OrchestratorAgent, BuilderAgent, ValidatorAgent, OutlineAgent (reranking) |
| LIGHT (planner, outline, reranker, skills) | `llama-3.1-8b-instant` (Groq) | PlannerAgent, OutlineAgent, BloomClassifierSkill, DedupCheckerSkill, DifficultyEstimatorSkill, ScopeCheckerSkill |
| VISION | `llama-3.2-11b-vision-preview` | Qwen Vision provider |

### Token Budget
- `AGENT_TOKEN_BUDGET: 50000` tokens total per generation session
- Flush mode when budget exceeded: reduced context → stop adding new chunks
- `MAX_CONTEXT_TOKENS: 3000` tokens hard cap per chapter slot

---

## I. Tích hợp Frontend

### Frontend hiện tại cần dữ liệu gì từ backend

**Login/Register:**
- `POST /auth/login` → tokens
- `POST /auth/register` → user
- `GET /auth/me` → profile

**Document list & upload:**
- `GET /documents/` → paginated list
- `POST /documents/upload` → upload trigger
- `GET /documents/{id}/status` → poll processing
- `GET /documents/{id}` → full detail với heading_tree
- `GET /documents/{id}/curriculum-tree` → flattened nodes cho FE tree

**Generation wizard:**
- `POST /generate/exam` → exam_id + websocket_url (IMMEDIATE return)
- WebSocket → real-time progress (plan_step, question_generated, hitl_checkpoint, completed, error)
- `GET /documents/{id}/curriculum-tree` → populate scope selection
- `GET /exams/` → exam list (after generation completes)

**Exam detail/editor (lớn nhất, 741 lines):**
- `GET /exams/{id}` → full exam with questions
- `GET /exams/{id}/versions` → version history
- `GET /exams/{id}/review-data` → HITL review data
- `POST /exams/{id}/approve-blueprint` → HITL1 approve
- `POST /exams/{id}/reject-blueprint` → HITL1 reject (with feedback)
- `POST /exams/{id}/submit-review` → HITL2 submit
- `GET /exams/{id}/preview` → HTML preview
- `PATCH /exams/{id}/questions/{id}` → inline edit
- `POST /exams/{id}/regenerate` → full regenerate
- `GET /exams/{id}/export/pdf` → download PDF

**Dashboard home:**
- `GET /exams/` → recent exams
- `GET /exams/quality-summary` → aggregated quality metrics

**History:**
- `GET /exams/{id}/history` → all snapshots
- `POST /exams/{id}/history/{history_id}/restore` → restore

**Feedback:**
- `GET /exams/feedback-store` → all feedback events

**Playbook:**
- `GET /playbook/overview` → placeholder (501)

### Contract đã rõ

- Auth endpoints: đầy đủ, stable
- Document endpoints: đầy đủ, stable
- Exam generation: đầy đủ, stable (generation flow)
- HITL checkpoints: đầy đủ
- Export: đầy đủ

### Contract còn thiếu / chưa ổn định

- `GET /exams/feedback` — backend returns empty list (no dedicated table), FE may need mock
- `GET /exams/feedback-summary` — backend returns empty metrics
- `/playbook/*` — all 501 stubs, no real backend
- `/courses/*` — all stubs
- `GET /exams/{id}/versions` — `current_version_number` TODO (not joined from ExamVersion table)
- `feedback_event_count` — TODO (not counting from feedback_events)

---

## J. Điểm chưa hoàn thiện / Tech Debt / Risk

### TODO / Chưa xong

1. **`exam_history` table** — migration exists but `current_version_number` trong `_exam_to_list_item` là `None` (TODO: join với ExamVersion)
2. **Feedback events** — `get_feedback_events()` returns empty list, no dedicated table
3. **`feedback_event_count`** trong exam list → hardcoded `0`
4. **`GET /exams/feedback-store`** và `GET /exams/feedback-summary`** — returns empty, no backing table
5. **`/playbook/*` routes** — all 8 endpoints return 501
6. **`/courses/*` routes** — all 6 endpoints return 501 or empty list
7. **Demo mode** — `DEMO_MODE: bool = False` in config; generation có fake question path khi không có document_id

### Code smell / Hard-code

1. **JWT secret in .env:** `JWT_SECRET_KEY: str = "change-me-in-production"` — có default, dễ quên thay
2. **Groq API key hard-coded** trong `.env` (real key exposed)
3. **Pinecone API key hard-coded** trong `.env` (real key exposed)
4. **`chapters_num`** workaround — backend trả `chapters_str` (string titles) nhưng FE expects number indices; `_exam_to_list_item` trả cả hai để maintain compatibility
5. **PyMuPDF fallback heading detection** — heuristic-based font size + bold detection, không deterministic
6. **`DEMO_MODE`** — tạo fake questions khi không có document_id, có thể confuse người dùng
7. **`MAX_GENERATES_PER_DAY: int = 9999`** — effectively no rate limit in dev

### Frontend/Backend Contract Mismatches

1. **`chapter_id` vs chapter title** — FE gửi `"A.QUANG HÌNH HỌC"`, backend phải normalize → canonical chapter_id. Đã handle trong `generate.py` nhưng fragile.
2. **Scope > 200 chunks** → reject nhưng chưa có clear error message về chunk count cho user
3. **Token budget exceeded** → flush mode không có clear signal về partial results

### Cần mock để dựng UI

1. **Courses page** — backend 501, dựng UI placeholder với mock data
2. **Playbook page** — backend 501, UI có content placeholder
3. **Feedback store** — returns empty, cần mock data structure
4. **HITL Checkpoint 1** — blueprint review UI, cần mock blueprint data nếu backend chưa ready

---

## K. Kết luận ngắn gọn

### Repo hiện đang ở mức nào

**MVP có thể demo được** — core pipeline hoạt động end-to-end:
- Upload document → RAG processing → Pinecone
- Generate exam → multi-agent → questions in DB
- HITL review checkpoints → WebSocket events
- Export PDF/DOCX

### Có thể demo được gì

1. Đăng ký/đăng nhập
2. Upload PDF → xem heading tree → tạo đề thi
3. Xem đề đã sinh → inline edit → export PDF
4. HITL checkpoints (duyệt sườn đề, duyệt câu hỏi)
5. Quality metrics dashboard

### Cần bổ sung gì để production hơn

1. **Security:** Thay JWT_SECRET_KEY, API keys từ env thật (không hard-code trong .env)
2. **Courses/Playbook modules** — phát triển từ stubs
3. **Feedback events table** — current trả empty list
4. **Version history** — `current_version_number` field chưa joined
5. **Error handling** — production-grade error messages
6. **Rate limit** — `MAX_GENERATES_PER_DAY=9999` (dev mode)
7. **Observability** — LangFuse đã integrate nhưng cần configure
8. **Demo mode** — nên disable trong production

---

*Căn cứ từ code: Tất cả kết luận trong tài liệu này dựa trên việc đọc trực tiếp source code tại các đường dẫn đã quét. Không có giả định nào được đưa vào mà không có căn cứ từ code.*