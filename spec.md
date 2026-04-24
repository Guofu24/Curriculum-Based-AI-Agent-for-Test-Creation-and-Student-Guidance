# ExamAI — System Specification

> **Mục tiêu**: Hệ thống sinh đề thi trắc nghiệm/tự luận môn Vật lý tự động bằng multi-agent AI pipeline với Human-in-the-Loop (HITL), sử dụng kiến thức nội dung từ tài liệu PDF/DOCX/PPTX của giáo viên.

---

## 1. Tổng quan kiến trúc

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js 16)                    │
│  /dashboard/generate   /dashboard/exams/[id]   /dashboard    │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                     Backend (FastAPI)                        │
│  Routers: auth | documents | exams | generate | courses | playbook │
│  WebSocket: /ws/exam/{exam_id}                              │
└──┬──────────┬──────────┬──────────┬──────────┬─────────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
 PostgreSQL  Redis     MinIO/S3  Pinecone   LangFuse
 (DB)       (Cache/   (File      (Vector    (Tracing/
            PubSub)    Storage)   Store)     Sentry)
```

---

## 2. Frontend (Next.js 16 + TypeScript)

### 2.1. Cấu trúc thư mục

```
Frontend/
├── app/
│   ├── dashboard/
│   │   ├── layout.tsx          # Layout dashboard: sidebar + auth guard
│   │   ├── page.tsx            # Trang chủ dashboard
│   │   ├── generate/
│   │   │   └── page.tsx        # Trang sinh đề: 3 bước
│   │   ├── exams/
│   │   │   └── [id]/
│   │   │       └── page.tsx    # Chi tiết đề: 4 tabs
│   │   └── documents/
│   │       └── page.tsx        # Quản lý tài liệu
│   └── (auth pages)
├── components/
│   ├── generation-live-viewer.tsx  # Viewer real-time + HITL dialogs
│   └── ui/ (shadcn/ui components)
└── lib/
    └── api.ts  # API client + WebSocket factory
```

### 2.2. Trang Generate (`/dashboard/generate`)

Quy trình 3 bước:

1. **Chọn tài liệu** — Gọi `GET /api/v1/documents` để lấy danh sách tài liệu đã upload. Gọi `GET /api/v1/documents/{id}/curriculum-tree` để lấy cấu trúc cây chương.
2. **Cấu hình đề** — Chọn chapters trong scope, số lượng câu hỏi, phân bổ Bloom (slider), loại đề, prompt bổ sung, strict_scope flag.
3. **Sinh đề live** — Gọi `POST /api/v1/generate/exam`, nhận `exam_id`, sau đó kết nối WebSocket `ws://.../ws/exam/{exam_id}` để nhận stream events. Dùng `GenerationLiveViewer` component hiển thị tiến trình.

### 2.3. Trang Exam Detail (`/dashboard/exams/[id]`)

4 tabs:

- **Questions**: Danh sách câu hỏi với inline editing, nút "Sửa AI", "Tạo lại".
- **Blueprint**: Ma trận đề chi tiết (phân bổ câu hỏi theo chương và mức Bloom), nút Duyệt/Từ chối blueprint (HITL).
- **Quality**: Quality score, pass rate, evidence coverage, danh sách warnings.
- **History**: Phiên bản đề đã lưu với khả năng restore.

Actions: Export PDF/DOCX (`GET /api/v1/exams/{id}/export/pdf|docx`), Publish (`POST /api/v1/exams/{id}/publish`).

### 2.4. Generation Live Viewer (`generation-live-viewer.tsx`)

Kết nối WebSocket, xử lý các event types sau:

| Event type | Mô tả |
|---|---|
| `plan_step` | Một bước pipeline đã hoàn thành |
| `question_generated` | Một câu hỏi đã được sinh |
| `hitl_checkpoint` | Dừng lại chờ HITL approval |
| `validation_result` | Kết quả validation |
| `completed` | Hoàn thành |
| `error` | Có lỗi xảy ra |

HITL Checkpoints hiển thị dạng card tương tác:
- **Checkpoint 1** (Blueprint Review): Hiển thị blueprint + distribution, nút Duyệt/Từ chối.
- **Checkpoint 2** (Full Review): Hiển thị tất cả câu hỏi + validation issues, nút Duyệt/Từ chối.

Auto-reconnect: Tự động reconnect khi WebSocket drop, replay events từ Redis (G19).

### 2.5. API Client (`lib/api.ts`)

- **Token management**: Login/register/refresh/logout, lưu vào localStorage.
- **REST API**: `apiFetch` wrapper tự động gắn JWT header.
- **API namespaces**: `authApi`, `documentsApi`, `examsApi`, `generateApi`.
- **WebSocket factory**: `createExamWebSocket(examId, callbacks)` với auto-reconnect.

---

## 3. Backend (FastAPI + Python)

### 3.1. Cấu trúc thư mục

```
backend/
├── app/
│   ├── main.py                    # FastAPI entry, lifespan, routers
│   ├── core/
│   │   ├── config.py              # Pydantic Settings (.env)
│   │   ├── database.py            # SQLAlchemy async
│   │   └── redis_client.py        # Redis singleton
│   ├── models/                    # SQLAlchemy models
│   │   ├── user.py
│   │   ├── exam.py                # Exam + ExamHistory
│   │   ├── document.py
│   │   ├── teacher_preference.py  # G14: long-term memory
│   │   └── refresh_token.py      # JWT refresh token rotation
│   ├── schemas/                  # Pydantic request/response
│   ├── routers/
│   │   ├── auth.py               # Login, register, refresh, logout
│   │   ├── documents.py           # Upload, list, detail, status, delete, reprocess, rescan, refresh-url (G20)
│   │   ├── exams.py              # CRUD, history, export, publish, HITL endpoints
│   │   ├── generate.py           # Start generation (FE-compatible)
│   │   ├── courses.py            # Placeholder stubs (backlog)
│   │   └── playbook.py           # Placeholder stubs (backlog, Phase 4)
│   ├── services/
│   │   ├── auth_service.py       # JWT + bcrypt + refresh token rotation
│   │   ├── exam_service.py      # Exam CRUD, publish, history, snapshot (G14)
│   │   └── document_service.py   # Upload, process, delete, curriculum tree
│   ├── agents/
│   │   ├── orchestrator.py       # Agent 0: điều phối toàn pipeline
│   │   ├── retrieval.py          # Agent 1: truy xuất kiến thức (G10, G11)
│   │   ├── outline.py           # Agent 2: tạo blueprint (G8)
│   │   ├── builder.py           # Agent 3: sinh câu hỏi (G4, G9)
│   │   ├── validator.py         # Agent 4: kiểm tra chất lượng (G9)
│   │   ├── planner.py          # Dynamic execution planning (G6)
│   │   ├── llm.py              # Unified LLM client (7 providers)
│   │   ├── base.py             # Base classes, AgentStatus, Pydantic outputs
│   │   ├── guardrails.py       # TokenBudgetGuard, ScopeGuard, ContentFilter
│   │   ├── memory/
│   │   │   ├── short_term.py   # Redis: session data + G9 retry issues
│   │   │   └── long_term.py    # PostgreSQL: teacher preferences (G3, G14)
│   │   ├── skills/
│   │   │   ├── bloom_classifier.py
│   │   │   ├── scope_checker.py
│   │   │   ├── latex_renderer.py
│   │   │   ├── dedup_checker.py
│   │   │   └── difficulty_estimator.py
│   │   └── graph/              # LangGraph StateGraph
│   │       ├── state.py         # ExamGraphState TypedDict
│   │       ├── builder.py       # build_exam_graph() + conditional edges
│   │       └── nodes/          # 27 node functions
│   ├── websocket/
│   │   └── manager.py          # ConnectionManager: G19 replay, G7 pub/sub fan-out
│   ├── rag/
│   │   ├── parser.py           # 3-level fallback: Gemini → Marker → PyMuPDF
│   │   ├── chunker.py          # Semantic chunking (LlamaIndex → fallback)
│   │   ├── embedder.py         # Local sentence-transformers embeddings
│   │   ├── vector_store.py     # Pinecone operations
│   │   ├── structure.py         # Heading tree detection + normalize_chapter_id
│   │   └── cleaner.py          # Markdown cleaning
│   ├── tasks/
│   │   ├── exam_task.py        # Celery task + idempotency guard + G14, demo fallback
│   │   └── document_task.py    # Celery task for document processing
│   ├── dependencies.py         # get_current_user, JWT decode, password hashing
│   └── observability/
│       ├── tracer.py           # LangFuse tracing (CurriculumTracer, decorators)
│       └── cost.py             # Cost calculation + ExamCostReport
├── tests/
│   └── agents/graph/
│       ├── conftest.py
│       ├── test_state_schema.py
│       ├── nodes/
│       │   ├── test_initialize.py
│       │   └── test_validate_questions.py
│       ├── test_edge_cases/
│       │   └── test_edge_cases.py
│       └── test_integration/
│           └── test_full_graph.py
└── requirements.txt
```

### 3.2. Entry Point (`main.py`)

- **Lifespan events**: Khởi tạo DB, ping Redis, shutdown WebSocket manager.
- **Health checks**: `GET /health`, `GET /ready`.
- **Routers**: auth, documents, exams, generate, courses, playbook.
- **WebSocket**: `GET /ws/exam/{exam_id}` → `ConnectionManager`.
- **Middleware**: CORS, GZip.

### 3.3. Configuration (`config.py`)

Dùng Pydantic Settings, load từ `.env`. Key sections:

| Category | Details |
|---|---|
| Database | PostgreSQL URL, SQLAlchemy async |
| Redis | Host, port, password, db |
| LLM Providers | 7 providers: OpenAI, Groq, OpenRouter, Anthropic, Ollama, g4f, Qwen Vision |
| **Per-Role Model Routing** | 11 roles: orchestrator, builder, validator, outline, planner, reranker, dedup, skills, classifier, guardrails, vision |
| **Fallback Chain** | `LLM_FALLBACK_CHAIN` list cho mỗi provider |
| Embeddings | `paraphrase-multilingual-mpnet-base-v2` (768 dim), local |
| Pinecone | API key, index, cloud, region |
| Storage | MinIO (local dev) / AWS S3 |
| RAG params | `RAG_TOP_K_PER_CHAPTER`, `RAG_TOP_K_AFTER_RERANK`, `MAX_CONTEXT_TOKENS` |
| Agent settings | Timeouts, max retries, token budget |
| JWT | Secret key, access/refresh expiry |
| LangFuse | Enabled, public/secret key, host |
| Demo mode | `DEMO_MODE=true` → dùng demo questions thay vì gọi LLM |
| Rate limit | `EXAM_GEN_RATE_LIMIT_PER_DAY` (default 10) |

### 3.4. API Routers chi tiết

#### 3.4.1. `routers/auth.py`

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/v1/auth/register` | POST | Đăng ký user (teacher role) |
| `/api/v1/auth/login` | POST | Login + JWT + refresh token rotation |
| `/api/v1/auth/refresh` | POST | Refresh access token |
| `/api/v1/auth/logout` | POST | Revoke refresh token |

Features: Rate limit login (5 attempts/IP/minute), bcrypt password, refresh token hash stored in DB.

#### 3.4.2. `routers/documents.py`

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/v1/documents/upload` | POST | Upload file → S3 → DB → background processing |
| `/api/v1/documents` | GET | List documents (pagination) |
| `/api/v1/documents/{id}` | GET | Detail + heading_tree |
| `/api/v1/documents/{id}/status` | GET | Processing status |
| `/api/v1/documents/{id}` | DELETE | Delete: DB + S3 + Pinecone |
| `/api/v1/documents/{id}/refresh-url` | GET | Presigned URL mới (G20) |
| `/api/v1/documents/{id}/curriculum-tree` | GET | Flat curriculum tree |
| `/api/v1/documents/{id}/curriculum-tree` | PATCH | Update curriculum tree |
| `/api/v1/documents/{id}/rescan-structure` | POST | Re-detect headings |
| `/api/v1/documents/{id}/reprocess` | POST | Re-chunk + re-embed + re-upsert |

Processing: 3-level PDF parse fallback → clean markdown → detect heading tree → semantic chunk → embed (sentence-transformers) → upsert to Pinecone (namespace = `{doc_id}_{chapter_id}`).

#### 3.4.3. `routers/exams.py`

| Endpoint | Method | Mô tả |
|---|---|---|
| `GET /api/v1/exams` | GET | List exams |
| `GET /api/v1/exams/{id}` | GET | Exam detail |
| `PATCH /api/v1/exams/{id}/questions/{qid}` | PATCH | Inline edit question |
| `POST /api/v1/exams/{id}/edit-prompt` | POST | AI-assisted edit |
| `POST /api/v1/exams/{id}/regenerate` | POST | Regenerate questions |
| `POST /api/v1/exams/{id}/publish` | POST | Publish + save teacher prefs (G14) |
| `GET /api/v1/exams/{id}/export/pdf` | GET | Export LaTeX → PDF |
| `GET /api/v1/exams/{id}/export/docx` | GET | Export DOCX |
| `POST /api/v1/exams/{id}/approve-blueprint` | POST | HITL checkpoint 1 approve |
| `POST /api/v1/exams/{id}/reject-blueprint` | POST | HITL checkpoint 1 reject (G8) |
| `GET /api/v1/exams/{id}/review-data` | GET | Review data for HITL |
| `POST /api/v1/exams/{id}/submit-review` | POST | HITL full review approve/reject |
| `GET /api/v1/exams/history` | GET | Exam history |
| `POST /api/v1/exams/{id}/restore/{version}` | POST | Restore version |

Features: Rate limit sinh đề (G13: 10 lần/ngày/user), G8 blueprint rejection feedback, G14 teacher preferences save on publish, version history + snapshot.

#### 3.4.4. `routers/generate.py`

| Endpoint | Method | Mô tả |
|---|---|---|
| `POST /api/v1/generate/exam` | POST | Start generation (FE-compatible) |
| `POST /api/v1/generate/partial-regenerate` | POST | Regenerate subset of questions |

FE-compatible: Map frontend request sang `ExamConfigRequest`, gọi `_run_generation_inline` (asyncio task, không dùng Celery) để WebSocket stream ngay lập tức.

#### 3.4.5. `routers/courses.py` + `routers/playbook.py`

Placeholder stubs (501) cho course management và playbook/reflection (Phase 4 backlog).

---

## 4. Multi-Agent Pipeline

### 4.1. LangGraph StateGraph

Biên dịch bằng `build_exam_graph()` trả về `CompiledStateGraph`. Dùng `MemorySaver` (in-memory checkpointer) cho dev; có thể thay bằng `PostgresSaver` cho production.

#### 4.1.1. ExamGraphState (TypedDict)

```python
class ExamGraphState(TypedDict, total=False):
    # Identity
    exam_id: str; user_id: str; document_id: str | None
    # Config
    exam_config: dict; exam_config_original: dict; user_prompt: str | None
    extra_instructions: str | None; scope: list[str]
    # Pipeline
    pipeline_status: PipelineStatus; current_agent: AgentRole | None
    current_step: int; total_steps: int
    # Agent outputs
    teacher_prefs: dict | None; plan_type: str
    execution_plan: list[dict]; retrieval_result: dict | None
    outline_result: dict | None; blueprint: list[dict] | None
    distribution_summary: dict | None; builder_result: dict | None
    validation_result: dict | None; questions: list[dict]
    approved_questions: list[dict]; cost_report: dict
    # HITL Checkpoints
    checkpoint_0_status: HITLCheckpointStatus; checkpoint_0_requirements: dict | None
    checkpoint_1_status: HITLCheckpointStatus; checkpoint_1_approved: bool | None
    checkpoint_1_rejection_history: list[dict]; checkpoint_1_timeout_at: float | None
    checkpoint_2_status: HITLCheckpointStatus; checkpoint_2_approved: bool | None
    checkpoint_2_feedback: str | None; checkpoint_2_timeout_at: float | None
    checkpoint_3_status: HITLCheckpointStatus
    # Retry (G9)
    retry_count: int; retry_issues: list[dict]; topics_used: list[str]
    # Memory
    retrieved_context: list[dict]; allowed_concepts: list[str]
    allowed_chapters: list[str]; conversation_history: list[dict]
    review_approved: bool
    # Errors
    warnings: list[str]; error: str | None; critical_error: str | None
    # Timestamps
    created_at: float; updated_at: float
```

#### 4.1.2. Nodes (27 functions trong `graph/nodes/`)

| Node | Mô tả |
|---|---|
| `initialize` | Khởi tạo ExamGraphState |
| `clarification_check` | G1: Check xem yêu cầu có rõ ràng không |
| `emit_clarification` | Emit HITL checkpoint 0 (requirements) |
| `load_long_term_memory` | G3: Load teacher preferences từ PostgreSQL |
| `decide_plan` | G6: Đánh giá độ phức tạp |
| `plan_complex` | G6: Gọi Planner Agent tạo dynamic plan |
| `retrieve_knowledge` | G10, G11: Retrieval Agent truy xuất Pinecone |
| `handle_retrieval_failure` | Xử lý lỗi retrieval |
| `create_outline` | G8: Outline Agent tạo blueprint (inject G8 feedback) |
| `handle_outline_failure` | Xử lý lỗi outline |
| `emit_checkpoint_1` | HITL Checkpoint 1: emit blueprint |
| `wait_for_blueprint_approval` | HITL Checkpoint 1: chờ duyệt blueprint (Redis pub/sub) |
| `build_questions` | G4, G9: Builder Agent sinh câu hỏi |
| `handle_builder_failure` | Xử lý lỗi builder |
| `validate_questions` | G9: Validator Agent kiểm tra |
| `check_validation_result` | G9: Route: retry / max_exceeded / passed |
| `retry_builder` | G9: Re-call builder với retry_issues |
| `handle_max_retries_exceeded` | G9: Xử lý khi retry hết lần |
| `emit_checkpoint_2` | HITL Checkpoint 2: emit questions + validation |
| `wait_for_review` | HITL Checkpoint 2: chờ full review |
| `save_teacher_preferences` | G14: Save prefs on publish |
| `emit_checkpoint_3` | HITL Checkpoint 3: final emit |
| `finalize_with_feedback` | Finalize với feedback |
| `finalize_output` | Finalize output |
| `handle_timeout` | Xử lý HITL timeout |

#### 4.1.3. Conditional Edge Routing

| Node | Routing Function | Routes |
|---|---|---|
| `clarification_check` | `_is_clarification_needed` | `clarification_needed` → `emit_clarification`; `requirements_clear` → `load_long_term_memory` |
| `decide_plan` | `_is_complex_request` | `complex` → `plan_complex`; `simple` → `retrieve_knowledge` |
| `retrieve_knowledge` | `_check_retrieval_status` | `success` → `create_outline`; `failed` → `handle_retrieval_failure` |
| `create_outline` | `_check_outline_status` | `success` → `emit_checkpoint_1`; `failed` → `handle_outline_failure` |
| `wait_for_blueprint_approval` | `_check_blueprint_approval` | `approved` → `build_questions`; `rejected` → `create_outline` (G8); `timeout` → `handle_timeout`; `waiting` → END |
| `build_questions` | `_check_builder_status` | `success` → `validate_questions`; `failed` → `handle_builder_failure` |
| `check_validation_result` | `_evaluate_validation` | `passed` → `emit_checkpoint_2`; `retry` → `retry_builder` (G9 self-loop); `max_exceeded` → `handle_max_retries_exceeded` |
| `wait_for_review` | `_check_review_approval` | `approved` → `save_teacher_preferences`; `rejected` → `finalize_with_feedback`; `timeout` → `handle_timeout` |

### 4.2. Orchestrator Agent (`orchestrator.py`)

**Agent 0** — điều phối toàn bộ pipeline LangGraph.

- `generate_exam()`: Main method, gọi `_run_graph()`.
- `_run_graph()`: Thực thi graph, emit WebSocket events qua `_emit()`, xử lý HITL interrupts.
- `reject_blueprint()`: G8 — lưu rejection + feedback vào Redis, trigger outline regeneration.
- `approve_blueprint()`: Approve blueprint → tiếp tục `build_questions`.
- `submit_review()`: Submit HITL review (approve/reject checkpoint 2).
- `edit_via_prompt()`: AI-assisted single question editing.

### 4.3. Retrieval Agent (`retrieval.py`)

**Agent 1** — truy xuất kiến thức từ Pinecone.

**G11 — Query Expansion**: LLM sinh 3-5 query variants từ chapter names + bloom targets.

**G10 — Parallel Retrieval**: `asyncio.gather()` gọi song song tất cả chapters. Một chapter fail không làm fail toàn retrieval (graceful degradation).

**Token Budget Guard**: Nếu tổng tokens > `MAX_CONTEXT_TOKENS`, truncate top-scoring chunks.

**LLM Reranking** (Bug-017 fix): Sau retrieval, gọi `llm.rerank()` (GPT-4o-mini) để reorder top-20 → top-8. Bug-017: validate index bounds để tránh `IndexError`.

### 4.4. Outline Agent (`outline.py`)

**Agent 2** — tạo blueprint (sườn đề).

**G8 — Blueprint Rejection Feedback**: Nếu có `outline_feedback` trong `exam_config`, inject vào prompt để tái sinh.

**Bloom Distribution**: Phân bổ số câu hỏi theo 4 mức Bloom (`nhan_biet`, `thong_hieu`, `van_dung`, `van_dung_cao`) + theo chapter/section.

**Validation**: Kiểm tra tổng số câu hỏi khớp với yêu cầu.

### 4.5. Builder Agent (`builder.py`)

**Agent 3** — sinh câu hỏi thực tế.

**G4 — Van Dung Cao Web Search**: Câu hỏi `van_dung_cao` dùng web search (SerpAPI) để lấy số liệu thực tế.

**Skill Pipeline** (5 skills):
1. **BloomClassifierSkill**: Phân loại Bloom level của câu hỏi.
2. **ScopeCheckerSkill**: Kiểm tra câu hỏi có nằm trong scope không.
3. **DedupCheckerSkill**: Phát hiện câu hỏi trùng lặp.
4. **DifficultyEstimatorSkill**: Ước lượng độ khó.
5. **LatexRendererSkill**: Validate LaTeX syntax.

**G9 — Retry Issues**: Validator issues được lưu vào Redis. Builder chỉ regenerate các câu hỏi có vấn đề.

**Bug-020 Fix**: Fallback sang demo questions deterministic nếu LLM parsing fail.

### 4.6. Validator Agent (`validator.py`)

**Agent 4** — kiểm tra chất lượng câu hỏi.

**Validation types**:
- **Bloom compliance**: So khớp Bloom level.
- **Scope violation**: Kiểm tra câu hỏi không chứa kiến thức ngoài scope.
- **LLM answer checking**: LLM tự giải MCQ và so sánh đáp án.

**Bug-015 Fix**: Skill-found issues được save vào `retry_issues` (trước đó chỉ save LLM-found issues).

**Bug-008 Fix**: Deduplicate issues trước khi return.

**G9 Retry**: Issues được persist vào Redis (`ShortTermMemory`) sau mỗi lần validation fail.

### 4.7. Planner Agent (`planner.py`)

**Dynamic execution planning** — được gọi khi request "complex" (G6).

**Signals để xác định complex** (≥ 2 signals = complex):
1. `len(user_prompt) > 200`
2. Keywords: `["tập trung", "thực tế", "ưu tiên", "hạn chế", "tránh"]`
3. Có `extra_instructions`
4. Có `bloom_distribution` + `len(user_prompt) > 100`

**Default Plan** (simple request): `retrieve → outline → build → validate`.

### 4.8. LLM Client (`llm.py`)

Unified abstraction cho 7 LLM providers:

| Provider | Model examples |
|---|---|
| OpenAI | gpt-4o, gpt-4o-mini, gpt-4-turbo |
| Groq | llama-3.3-70b-versatile, llama-3.1-8b-instant |
| OpenRouter | Various models |
| Anthropic | claude-3-5-sonnet |
| Ollama | Local models |
| g4f | Free models (dev only) |
| Qwen Vision | Self-hosted OCR/image description |

**Features**:
- Per-role model routing: Mỗi role (orchestrator, builder, validator, ...) dùng model riêng được cấu hình.
- Fallback chain: Tự động fallback qua list providers nếu primary fail.
- `chat()`: Free-form chat.
- `chat_structured()`: Structured output (Pydantic) dùng `instructor`.
- `rerank()`: LLM-based reranking.
- `chat_vision()`: Vision model support.
- LangFuse tracing integration.

### 4.9. Agent Skills (`agents/skills/`)

5 skill classes, mỗi cái có:
- `@tracer.skill_span()` decorator cho LangFuse tracing
- LLM call với fallback
- Keyword-based fallback classification

| Skill | Input | Output |
|---|---|---|
| `BloomClassifierSkill` | question_stem, type, subject | `bloom_level`, `confidence`, `reasoning` |
| `ScopeCheckerSkill` | question, allowed_concepts | `passed`, `violations` |
| `DedupCheckerSkill` | questions[] | duplicate groups |
| `DifficultyEstimatorSkill` | question_stem | `difficulty_score`, `factors` |
| `LatexRendererSkill` | latex_string | `valid`, `rendered_html`, `error` |

### 4.10. Memory System

#### Short-term (`memory/short_term.py`) — Redis

| Key | TTL | Content |
|---|---|---|
| `session:{exam_id}:{user_id}` | 2h | exam_config, topics_used, conversation_history, retry_count, HITL flags |
| `retry_issues:{exam_id}` | 1h | G9: Validator issues per exam |

#### Long-term (`memory/long_term.py`) — PostgreSQL

| Method | Mô tả |
|---|---|
| `get_preferences(user_id)` | Load teacher preferences (G3) |
| `save_preferences(user_id, ...)` | Upsert preferences (G14) |
| `update_from_exam(user_id, exam_config)` | G14: Extract + save prefs on exam publish |

---

## 5. Human-in-the-Loop (HITL)

### 5.1. Checkpoints

| Checkpoint | Trigger | UI | Decision |
|---|---|---|---|
| 0 | Yêu cầu không rõ ràng (G1) | Clarification questions | User trả lời → pipeline tiếp tục |
| 1 | Sau khi blueprint được tạo | Blueprint matrix + distribution | Approve → sinh câu hỏi; Reject → G8 feedback → tái sinh |
| 2 | Sau khi questions được sinh + validate | Full exam + validation issues | Approve → finalize; Reject → finalize with feedback |
| 3 | Sau khi review được submit | Final confirmation | Auto tiếp sau save_teacher_preferences |

### 5.2. Redis Pub/Sub Flow

```
wait_for_blueprint_approval node
    │
    ├─ emit "pipeline_paused" event (WebSocket → FE)
    │
    ├─ SET exam:{exam_id}:approval "pending" (with timeout)
    │
    ├─ SUBSCRIBE exam:{exam_id}:approval
    │
    ├─ [Teacher clicks Approve/Reject in FE]
    │     POST /api/v1/exams/{id}/approve-blueprint
    │         → SET exam:{exam_id}:approval "approved" or "rejected"
    │         → PUBLISH exam:{exam_id}:approval
    │
    └─ LOOP: polling GET exam:{exam_id}:approval mỗi 2s
           cho đến khi nhận được giá trị hoặc timeout
```

---

## 6. RAG Pipeline

### 6.1. Document Parser (`rag/parser.py`)

3-level fallback cho PDF:

1. **Gemini 2.5 Flash** (priority 1): Upload từng chunk 10 trang lên Gemini Files API → Multimonial xử lý ảnh trong PDF → mô tả chi tiết nội dung hình vẽ. Retry 3 lần.
2. **Marker Remote Server** (priority 2): Gọi `/parse-pdf` endpoint của Marker server (GPU, Kaggle). Health check trước, timeout 120s.
3. **PyMuPDF** (priority 3): CPU-only fallback. Extract text + detect headings bằng font size heuristics.

DOCX: `python-docx` library, parse paragraphs + tables → Markdown.
PPTX: `python-pptx` library, parse slides + shapes → Markdown.

### 6.2. Structure Detection (`rag/structure.py`)

`detect_heading_tree()`:
- Parse `# ## ###` markdown headings → nested chapters/sections/subsections.
- Fallback heuristic: Nếu không có `#` headings, dùng regex patterns cho "Chương N", "Bài N", "1.1", ALL CAPS lines, Title Case detection.

`normalize_chapter_id()`:
- Chuyển đổi raw chapter IDs về canonical form `ch{n}`.
- Hỗ trợ: "Chương 1", "Chapter 1", "Bài 1", "chuong-1", "A.QUANG HÌNH HỌC", "1"...
- Strip Vietnamese diacritics.

### 6.3. Semantic Chunker (`rag/chunker.py`)

`semantic_chunk()`:
- Thử dùng `LlamaIndex SemanticSplitterNodeParser`.
- **Fallback**: `_simple_chunk()` — paragraph-based với overlap.
- Mỗi chunk có: `chunk_id`, `document_id`, `chapter`, `chapter_id`, `section`, `section_id`, `content_type`, `page_number`, `latex_repr`, `content`.
- Canonical `chapter_id` từ `heading_tree` (luôn đảm bảo non-empty).

### 6.4. Embedder (`rag/embedder.py`)

Dùng `sentence-transformers` (`paraphrase-multilingual-mpnet-base-v2`, 768 dimensions) để embed locally. Cache embeddings in Redis để tránh re-embed.

### 6.5. Vector Store (`rag/vector_store.py`)

Pinecone operations:
- **Namespace**: `{doc_id}_{chapter_id}` (ASCII-safe via `_make_ascii_namespace()`).
- `upsert_chunks()`: Batch upsert (100 records/batch), retry 3 lần, NaN→0 handling.
- `query_namespace()`: Query theo embedding, sort by score desc.
- `count_chunks_in_scope()`: Dùng `describe_index_stats()` count vectors theo namespace prefix.
- `delete_document_vectors()`: Delete theo namespace per chapter + `ch_unknown`.
- `delete_all_document_vectors()`: List all namespaces matching doc_id prefix.

---

## 7. WebSocket & Event Streaming

### 7.1. ConnectionManager (`websocket/manager.py`)

**G19 — Event Replay**: Mỗi event được lưu vào Redis LIST `events:{exam_id}`. Khi client reconnect, gọi `replay_events()` để gửi lại các event đã miss.

**G7 — Pub/Sub Fan-out**: Multi-instance deployment. Khi emit event, publish lên Redis channel `ws:exam:{exam_id}`. Mỗi instance subscribe các channels của nó và broadcast tới local WebSocket clients.

**Methods**:
| Method | Mô tả |
|---|---|
| `connect(websocket, exam_id)` | Thêm connection |
| `disconnect(websocket, exam_id)` | Xóa connection |
| `emit(exam_id, event)` | Lưu Redis + broadcast local + pub/sub |
| `store_event(exam_id, event)` | Append vào Redis LIST |
| `replay_events(exam_id)` | Lấy events từ Redis LIST → gửi cho client mới |
| `listen_redis(channel)` | Subscribe Redis pub/sub |

### 7.2. SSEvent Factory

| Event type | Fields |
|---|---|
| `plan_step` | `step`, `step_name`, `status` |
| `question_generated` | `question`, `slot_index`, `bloom_level` |
| `hitl_checkpoint` | `checkpoint_id`, `data`, `timeout_seconds` |
| `validation_result` | `passed`, `issues[]`, `bloom_compliance` |
| `completed` | `exam_id`, `summary` |
| `error` | `message`, `node` |

---

## 8. Celery Tasks (`tasks/`)

### 8.1. Exam Generation Task (`exam_task.py`)

`generate_exam_task()`:
- Idempotency guard: Check Redis `idempotency:{idempotency_key}` trước khi chạy.
- Gọi `OrchestratorAgent().generate_exam()`.
- LangFuse root trace.
- Demo mode: `_build_demo_payload()` tạo deterministic demo questions.

**G14 Fallback**: Nếu Redis unavailable khi `save_teacher_preferences` được gọi, dùng in-memory dict `_hitl_fallback_approvals` để lưu tạm.

### 8.2. Document Processing Task (`document_task.py`)

Gọi `DocumentService(db).process_document()`.

---

## 9. Authentication & Security (`services/auth_service.py`)

- **JWT access token**: Short-lived (configurable), chứa `sub: user_id`.
- **Refresh token rotation**: Mỗi login tạo refresh token mới, revoke token cũ.
- **Refresh token storage**: Hash stored in PostgreSQL `refresh_tokens` table.
- **Rate limiting**: 5 login attempts/IP/minute qua Redis.
- **Password hashing**: bcrypt.

---

## 10. Observability

### 10.1. LangFuse Tracing (`observability/tracer.py`)

`CurriculumTracer` class:
- **Root trace**: `@contextmanager tracer.trace(exam_id=...)` cho toàn bộ exam session.
- **Agent spans**: `@tracer.agent_span("agent_name")` decorator cho mỗi agent method.
- **Skill spans**: `@tracer.skill_span("skill_name")` decorator cho skill methods.
- Non-critical: Tất cả methods safely no-op khi LangFuse unavailable.
- Always `span.end()` trong `finally` block.

### 10.2. Cost Tracking (`observability/cost.py`)

`MODEL_PRICING` dict cho GPT-4o family, GPT-4-Turbo, legacy GPT-4, embeddings. `calculate_cost(model, prompt_tokens, completion_tokens)` trả về USD estimate. `ExamCostReport` Pydantic model được save vào `exams.cost_report` sau khi sinh xong.

---

## 11. Key Features & Mechanisms

### 11.1. G-Codes

| Code | Feature | Implementation |
|---|---|---|
| G1 | Clarification Check | `clarification_check` node + `emit_clarification` node |
| G3 | Teacher Preferences Load | `load_long_term_memory` node |
| G4 | Van Dung Cao Web Search | `BuilderAgent` dùng SerpAPI |
| G6 | Complex Plan Detection | `decide_plan` node + 5 signal heuristics |
| G7 | Distributed Fan-out | Redis pub/sub trong `ConnectionManager` |
| G8 | Blueprint Rejection Feedback | `reject_blueprint()` → inject `outline_feedback` vào `create_outline` |
| G9 | Validator Retry Persistence | `ShortTermMemory` Redis + `retry_builder` self-loop node |
| G10 | Parallel Retrieval | `asyncio.gather()` trong `RetrievalAgent` |
| G11 | Query Expansion | `_expand_queries()` trong `RetrievalAgent` |
| G13 | Rate Limit | `check_generate_rate_limit()` trong `exams.py` |
| G14 | Teacher Preferences Save | `save_teacher_preferences` node + `publish_exam()` |
| G19 | Event Replay | Redis LIST trong `ConnectionManager` |
| G20 | Presigned URL Refresh | `GET /documents/{id}/refresh-url` endpoint |

### 11.2. Bugs Fixed

| Bug | File | Fix |
|---|---|---|
| Bug-008 | `validator.py` | Deduplicate issues trước return |
| Bug-015 | `validator.py` | Save skill-found issues vào `retry_issues` |
| Bug-017 | `retrieval.py` | Validate index bounds trong `_rerank_chunks()` |
| Bug-020 | `builder.py` | Fallback demo questions khi LLM parsing fail |

---

## 12. Frontend-Backend Compatibility Layer

FE và BE có một số minor naming differences được handle bằng aliases trong `documents.py`:

| Backend Field | Frontend Field |
|---|---|
| `original_filename` | `file_name` |
| `processing_status` | `status` |
| `version` | (default 1) |
| `uploaded_at` | `created_at`, `updated_at` |
| `heading_tree` | `curriculum_tree` |

---

## 13. Trạng thái hoàn thành

| Module | Completion | Notes |
|---|---|---|
| Backend core (FastAPI, routers) | ~95% | |
| Multi-agent pipeline (LangGraph) | ~95% | |
| HITL checkpoints | ~90% | |
| RAG pipeline (parse, chunk, embed, retrieve) | ~90% | |
| WebSocket real-time streaming | ~95% | |
| LLM client (7 providers, routing, fallback) | ~95% | |
| Skills (5 skills) | ~90% | |
| Memory (short-term + long-term) | ~90% | |
| Document service (upload, process, delete) | ~90% | |
| Exam service (CRUD, publish, history) | ~85% | Feedback persistence stubbed |
| Auth service | ~90% | |
| Celery tasks | ~85% | |
| LangFuse tracing | ~85% | |
| Frontend pages | ~85% | |
| Unit tests | ~40% | graph tests only |
| Course management | 0% | Placeholder stubs |
| Playbook/reflection | 0% | Placeholder stubs (Phase 4) |

---

## 14. Technologies

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, TypeScript, Tailwind CSS, shadcn/ui, Zustand |
| Backend | FastAPI (Python 3.11+), Pydantic v2, SQLAlchemy async |
| Database | PostgreSQL 15+ |
| Cache/PubSub | Redis 7+ |
| Vector Store | Pinecone |
| File Storage | MinIO (local dev) / AWS S3 |
| Task Queue | Celery + Redis broker |
| LLM Providers | Groq, OpenAI, OpenRouter, Anthropic, Ollama, g4f, Qwen Vision |
| Embeddings | `sentence-transformers` (`paraphrase-multilingual-mpnet-base-v2`, 768d) |
| Graph | LangGraph |
| Tracing | LangFuse |
| PDF Parsing | Gemini 2.5 Flash, Marker, PyMuPDF |
| Auth | JWT (PyJWT), bcrypt, Refresh Token Rotation |
| Rate Limiting | Redis |
| Export | LaTeX → PDF (pdflatex), python-docx |
