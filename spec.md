# ExamAI - Hệ thống tạo đề thi tự động bằng AI

> **Trạng thái**: Đang phát triển (`feature/building_new_frontend`)
> **Ngày cập nhật**: 2026-04-27

---

## Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Kiến trúc hệ thống](#2-kiến-trúc-hệ-thống)
3. [Cấu trúc thư mục](#3-cấu-trúc-thư-mục)
4. [Frontend (Next.js)](#4-frontend-nextjs)
5. [Backend (FastAPI)](#5-backend-fastapi)
6. [Hệ thống Multi-Agent](#6-hệ-thống-multi-agent)
7. [LangGraph Pipeline](#7-langgraph-pipeline)
8. [RAG Pipeline](#8-rag-pipeline)
9. [Cơ sở dữ liệu & Lưu trữ](#9-cơ-sở-dữ-liệu--lưu-trữ)
10. [WebSocket & Thời gian thực](#10-websocket--thời-gian-thực)
11. [Background Tasks (Celery)](#11-background-tasks-celery)
12. [API Reference](#12-api-reference)
13. [Cấu hình môi trường](#13-cấu-hình-môi-trường)
14. [Lưu ý quan trọng](#14-lưu-ý-quan-trọng)

---

## 1. Tổng quan

### 1.1 Mô tả dự án

**ExamAI** là một hệ thống tạo đề thi tự động sử dụng AI đa tác tử (Multi-Agent). Người dùng tải lên tài liệu giảng dạy (PDF/DOCX/PPTX), hệ thống sẽ phân tích nội dung, tạo đề thi với các câu hỏi trắc nghiệm và tự luận theo yêu cầu, có sự can thiệp của con người (HITL - Human-in-the-Loop) tại các bước quan trọng.

### 1.2 Tính năng chính

| Tính năng | Mô tả |
|-----------|--------|
| **Tải lên tài liệu** | Hỗ trợ PDF, DOCX, PPTX (tối đa 100MB) |
| **Xử lý RAG** | Phân tích, chunk, embedding và lưu vào vector DB |
| **Tạo đề thi tự động** | Sinh câu hỏi từ blueprint theo phân bố Bloom |
| **HITL Checkpoints** | 3 điểm dừng để người dùng xác nhận/chỉnh sửa |
| **Xem trước thời gian thực** | WebSocket streaming tiến trình tạo đề |
| **Xuất đề thi** | PDF và DOCX với/không đáp án |
| **Điều chỉnh đề thi** | Chỉnh sửa câu hỏi, khóa/xóa câu, tái sinh một phần |
| **Bảng điều khiển** | Thống kê số lượng tài liệu, đề thi, chi phí |

### 1.3 Người dùng mục tiêu

- **Giáo viên/Giảng viên**: Tạo đề thi nhanh chóng từ tài liệu có sẵn
- **Quản lý giáo dục**: Quản lý ngân hàng câu hỏi và đề thi

---

## 2. Kiến trúc hệ thống

### 2.1 Sơ đồ kiến trúc tổng thể

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           BROWSER (Next.js)                              │
│                    localhost:3000 / examai.topdomain.com                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    HTTP/REST ◄─────► WebSocket (WSS)
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI)                                │
│                     localhost:8000 / api.examai.topdomain.com             │
│                                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │  Routers │  │  Agents  │  │   RAG    │  │  Tasks   │               │
│  │  (REST)  │  │(LangGraph)│  │ Pipeline │  │ (Celery) │               │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘               │
│       │             │             │             │                      │
│       └─────────────┴─────────────┴─────────────┘                      │
│                           │                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │  WebSocket│  │  Redis   │  │  Postgres │  │  MinIO/S3 │               │
│  │  Manager  │  │ (Cache)  │  │  (Data)   │  │  (Files)  │               │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘               │
│                                    │             │                      │
│                                    ▼             ▼                      │
│                           ┌──────────────┐  ┌────────────┐             │
│                           │   Pinecone   │  │  Groq/Gemini│             │
│                           │ (Vector DB)  │  │  (LLM API) │             │
│                           └──────────────┘  └────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Luồng dữ liệu chính

#### Luồng 1: Tải lên và xử lý tài liệu

```
FE Upload → POST /documents/upload → S3/MinIO → Background Task (Celery)
                                              ↓
                                    RAG Pipeline (Parser → Cleaner → Chunker → Embedder → Vector Store)
                                              ↓
                                    Pinecone (Upsert vectors) + Redis (Status cache)
```

#### Luồng 2: Tạo đề thi

```
FE Request → POST /generate/exam → Create Exam DB record
                                    ↓
                            LangGraph Pipeline (27 nodes)
                                    ↓
                            HITL Checkpoint 1 (Blueprint) → Teacher approves
                                    ↓
                            HITL Checkpoint 2 (Questions) → Teacher reviews
                                    ↓
                            HITL Checkpoint 3 (Preview) → Finalize
                                    ↓
                            WebSocket stream (progress) + DB (questions)
```

### 2.3 Công nghệ sử dụng

| Layer | Công nghệ | Vai trò |
|-------|-----------|---------|
| **Frontend** | Next.js 16, React 19, TypeScript | Giao diện người dùng |
| **UI** | Tailwind CSS 4, Radix UI, Lucide Icons, Recharts | Thiết kế & biểu đồ |
| **Backend** | FastAPI, Pydantic, SQLAlchemy (async) | REST API |
| **AI Agents** | LangGraph, Groq/Anthropic/OpenAI/Gemini | Multi-agent orchestration |
| **Vector DB** | Pinecone | Semantic search |
| **Embeddings** | Sentence Transformers (BAAI/bge-m3) | Text embedding |
| **Database** | PostgreSQL (asyncpg) | Dữ liệu quan hệ |
| **Cache/PubSub** | Redis | Cache, session, pub/sub |
| **File Storage** | MinIO / AWS S3 | Lưu file tài liệu |
| **Background** | Celery + Redis | Async task queue |
| **Auth** | JWT (access + refresh tokens) | Xác thực |

---

## 3. Cấu trúc thư mục

```
E:/Đồ án/Project/
│
├── SPEC.md                          # File spec này
├── README.md
│
├── Frontend/                        # Next.js Frontend
│   ├── app/                         # App Router
│   │   ├── layout.tsx               # Root layout (ThemeProvider, AuthProvider)
│   │   ├── page.tsx                # Login/Register page
│   │   ├── globals.css             # Global styles
│   │   ├── dashboard/              # Protected dashboard routes
│   │   │   ├── layout.tsx          # Dashboard layout (sidebar)
│   │   │   ├── page.tsx            # Dashboard home
│   │   │   ├── documents/
│   │   │   │   └── page.tsx        # Document management
│   │   │   ├── exams/
│   │   │   │   ├── page.tsx        # Exam list
│   │   │   │   └── [id]/page.tsx   # Exam detail
│   │   │   ├── generate/
│   │   │   │   └── page.tsx        # Exam generation wizard
│   │   │   └── feedback/
│   │   │       └── page.tsx        # Feedback page
│   │   └── api/                    # Next.js API routes (proxy)
│   │
│   ├── components/                  # React components
│   │   ├── generation-live-viewer.tsx  # Real-time generation viewer (1400+ lines)
│   │   ├── auth-provider.tsx       # Auth context provider
│   │   ├── upload-notification-provider.tsx # Upload progress notifications
│   │   └── ui/                     # Radix UI components
│   │       ├── button.tsx
│   │       ├── input.tsx
│   │       ├── card.tsx
│   │       ├── sidebar.tsx         # Main sidebar
│   │       ├── curriculum-tree.tsx # Document chapter tree
│   │       ├── exam-form.tsx       # Exam creation form
│   │       ├── question-card.tsx   # Question display/edit
│   │       ├── question-editor.tsx # Question editing modal
│   │       ├── tabs.tsx
│   │       ├── toast.tsx
│   │       ├── dialog.tsx
│   │       ├── dropdown-menu.tsx
│   │       ├── label.tsx
│   │       ├── select.tsx
│   │       ├── slider.tsx
│   │       ├── textarea.tsx
│   │       ├── table.tsx
│   │       ├── badge.tsx
│   │       ├── progress.tsx
│   │       ├── scroll-area.tsx
│   │       ├── separator.tsx
│   │       ├── tooltip.tsx
│   │       ├── sheet.tsx
│   │       ├── skeleton.tsx
│   │       └── index.ts            # Re-export all UI components
│   │
│   └── lib/                        # Utilities
│       └── api.ts                  # API client (800+ lines)
│
├── backend/                        # FastAPI Backend
│   ├── app/
│   │   ├── main.py                 # FastAPI app entry point
│   │   │
│   │   ├── core/                   # Core infrastructure
│   │   │   ├── config.py           # Pydantic Settings (50+ env vars)
│   │   │   ├── database.py         # SQLAlchemy async setup
│   │   │   └── redis_client.py     # Redis async client
│   │   │
│   │   ├── routers/               # API routers
│   │   │   ├── auth.py             # Authentication endpoints
│   │   │   ├── documents.py        # Document upload/management
│   │   │   ├── exams.py            # Exam CRUD & export
│   │   │   ├── generate.py         # Exam generation bridge
│   │   │   ├── courses.py          # Course management
│   │   │   └── playbook.py         # Teacher preferences
│   │   │
│   │   ├── models/                 # SQLAlchemy models
│   │   │   ├── user.py
│   │   │   ├── document.py
│   │   │   ├── exam.py
│   │   │   └── teacher_preference.py
│   │   │
│   │   ├── services/               # Business logic
│   │   │   ├── exam_service.py
│   │   │   ├── document_service.py
│   │   │   └── auth_service.py
│   │   │
│   │   ├── agents/                 # Multi-agent AI system
│   │   │   ├── orchestrator.py     # Master orchestrator (Agent 0)
│   │   │   ├── llm.py              # Unified LLM client
│   │   │   ├── retrieval.py         # RAG retrieval agent (Agent 1)
│   │   │   ├── outline.py          # Blueprint generator (Agent 2)
│   │   │   ├── builder.py          # Question builder (Agent 3)
│   │   │   ├── validator.py        # Question validator (Agent 4)
│   │   │   ├── planner.py          # Dynamic planner
│   │   │   ├── guardrails.py       # Input safety
│   │   │   ├── base.py             # Shared types & enums
│   │   │   │
│   │   │   ├── graph/              # LangGraph pipeline
│   │   │   │   ├── state.py        # Graph state schema
│   │   │   │   ├── builder.py      # Graph compilation
│   │   │   │   └── nodes/          # 27 graph nodes
│   │   │   │       ├── initialize.py
│   │   │   │       ├── clarification_check.py
│   │   │   │       ├── load_long_term_memory.py
│   │   │   │       ├── decide_plan.py
│   │   │   │       ├── plan_complex.py
│   │   │   │       ├── retrieve_knowledge.py
│   │   │   │       ├── create_outline.py
│   │   │   │       ├── emit_checkpoint_1.py
│   │   │   │       ├── wait_for_blueprint_approval.py
│   │   │   │       ├── build_questions.py
│   │   │   │       ├── validate_questions.py
│   │   │   │       ├── check_validation_result.py
│   │   │   │       ├── retry_builder.py
│   │   │   │       ├── emit_checkpoint_2.py
│   │   │   │       ├── wait_for_review.py
│   │   │   │       ├── save_teacher_preferences.py
│   │   │   │       ├── emit_checkpoint_3.py
│   │   │   │       ├── finalize_output.py
│   │   │   │       ├── handle_*.py   # Error handlers
│   │   │   │       └── __init__.py  # ALL_NODES constant
│   │   │   │
│   │   │   └── memory/             # Memory management
│   │   │       ├── short_term.py   # Redis session memory
│   │   │       └── long_term.py    # PostgreSQL teacher preferences
│   │   │
│   │   ├── rag/                    # RAG pipeline
│   │   │   ├── parser.py           # Multi-format document parsing
│   │   │   ├── cleaner.py          # Text cleaning
│   │   │   ├── structure.py        # Heading tree detection
│   │   │   ├── chunker.py          # Semantic chunking
│   │   │   ├── embedder.py         # Sentence embeddings
│   │   │   └── vector_store.py     # Pinecone operations
│   │   │
│   │   ├── tasks/                 # Celery background tasks
│   │   │   ├── celery_app.py       # Celery configuration
│   │   │   ├── exam_task.py        # Async exam generation
│   │   │   └── document_task.py    # Async document processing
│   │   │
│   │   ├── websocket/            # WebSocket management
│   │   │   └── manager.py          # Connection manager + SSE events
│   │   │
│   │   └── utils/                # Utilities
│   │       └── export.py          # PDF/DOCX export
│   │
│   ├── requirements.txt           # Python dependencies
│   ├── .env                       # Environment variables
│   ├── alembic.ini               # DB migration config
│   └── docker-compose.yml       # Local dev services
│
├── run_guide.md                  # Hướng dẫn chạy dự án
└── package.json                  # Workspace root (nếu có)
```

---

## 4. Frontend (Next.js)

### 4.1 Cấu hình

- **Framework**: Next.js 16 (App Router)
- **Language**: TypeScript 5
- **Styling**: Tailwind CSS 4
- **UI Library**: Radix UI primitives
- **State**: React Context (Auth, Theme, Upload)
- **HTTP Client**: Native fetch với wrapper trong `lib/api.ts`
- **Real-time**: Native WebSocket API

### 4.2 Routes

| Route | Component | Mô tả |
|-------|-----------|--------|
| `/` | `page.tsx` | Login/Register với Tabs |
| `/dashboard` | `page.tsx` | Trang chủ với thống kê |
| `/dashboard/documents` | `page.tsx` | Quản lý tài liệu |
| `/dashboard/exams` | `page.tsx` | Danh sách đề thi |
| `/dashboard/exams/[id]` | `page.tsx` | Chi tiết đề thi |
| `/dashboard/generate` | `page.tsx` | Trình tạo đề thi (wizard) |
| `/dashboard/feedback` | `page.tsx` | Trang phản hồi |

### 4.3 API Client (`lib/api.ts`)

File API client chính (800+ dòng) cung cấp các đối tượng API:

```typescript
// Auth
authApi.login(email, password) → JWT tokens
authApi.register(email, password, fullName) → User
authApi.logout()
authApi.refreshToken()

// Documents
documentsApi.upload(file, onProgress) → Document
documentsApi.list(params) → PaginatedResponse<Document>
documentsApi.getById(id) → Document
documentsApi.getStatus(id) → ProcessingStatus
documentsApi.getCurriculumTree(id) → CurriculumTree
documentsApi.delete(id)
documentsApi.rescanStructure(id)
documentsApi.reprocess(id)

// Exams
examsApi.list(params) → PaginatedResponse<Exam>
examsApi.getById(id) → Exam
examsApi.updateQuestion(examId, questionId, data)
examsApi.partialRegenerate(examId, changes)
examsApi.approveBlueprint(id)
examsApi.rejectBlueprint(id, feedback)
examsApi.submitReview(id, data)
examsApi.exportPdf(id, params) → Blob
examsApi.exportDocx(id, params) → Blob
examsApi.preview(id) → HTML

// Generation
generateApi.createExam(config) → Exam
generateApi.getReviewData(examId) → ReviewData

// WebSocket
createExamWebSocket(examId, callbacks) → WebSocket
```

### 4.4 WebSocket Events

Frontend lắng nghe các event từ backend:

| Event | Dữ liệu | Xử lý |
|-------|---------|--------|
| `generation_started` | `{exam_id, config}` | Reset viewer |
| `retrieval_progress` | `{retrieved_chunks}` | Hiển thị chunks đã truy xuất |
| `outline_created` | `{blueprint, stats}` | Hiển thị blueprint |
| `checkpoint_1` | `{blueprint, requires_approval}` | Mở modal duyệt blueprint |
| `questions_building` | `{total, done, questions}` | Cập nhật progress bar |
| `questions_built` | `{questions, stats}` | Hiển thị danh sách câu hỏi |
| `validation_progress` | `{issues_count}` | Hiển thị validation |
| `validation_done` | `{passed, issues}` | Hiển thị kết quả validation |
| `checkpoint_2` | `{questions, stats}` | Mở modal duyệt câu hỏi |
| `checkpoint_3` | `{final_exam, stats}` | Hiển thị preview cuối |
| `generation_complete` | `{exam_id, questions}` | Điều hướng đến trang chi tiết |
| `generation_error` | `{error}` | Hiển thị lỗi |
| `generation_cancelled` | `{}` | Reset UI |
| `heartbeat` | `{timestamp}` | Keep-alive |

### 4.5 Các Component quan trọng

#### `generation-live-viewer.tsx` (1400+ lines)

Component chính cho việc xem và tương tác với quá trình tạo đề thi:

- **Phần hiển thị**: Progress bar, step indicator, real-time log
- **Blueprint Review**: Danh sách câu hỏi theo chương và Bloom level
- **Questions Review**: Danh sách câu hỏi với chỉnh sửa inline
- **Modal duyệt**: Dialog để approve/reject tại các checkpoint
- **Preview Panel**: Xem trước đề thi dạng HTML

#### `curriculum-tree.tsx`

Cây chương từ heading tree của tài liệu, cho phép:
- Chọn/bỏ chọn chương để tạo đề thi
- Collapsible tree view
- Checkbox với trạng thái mixed

#### `exam-form.tsx`

Form tạo đề thi với:
- Chọn tài liệu nguồn
- Chọn phạm vi (chương)
- Cấu hình: số lượng câu, phân bố Bloom, loại câu hỏi
- Tùy chọn nâng cao

#### `question-card.tsx` / `question-editor.tsx`

Hiển thị và chỉnh sửa câu hỏi:
- Loại: Trắc nghiệm (4 lựa chọn), Tự luận
- Các trường: Nội dung, đáp án, giải thích, Bloom level
- Hành động: Khóa, xóa, tái sinh

---

## 5. Backend (FastAPI)

### 5.1 Entry Point (`app/main.py`)

```python
# Lifespan: Khởi tạo và dọn dẹp tài nguyên
# Routers: auth, courses, documents, exams, generate, playbook
# WebSocket: /ws/exam/{exam_id}, /ws/document/{document_id}
# Health: /health, /ready
```

### 5.2 Routers

#### `routers/auth.py`
- `POST /api/v1/auth/register` - Đăng ký
- `POST /api/v1/auth/login` - Đăng nhập
- `POST /api/v1/auth/logout` - Đăng xuất
- `POST /api/v1/auth/refresh` - Refresh token
- `GET /api/v1/auth/me` - Lấy thông tin user hiện tại

#### `routers/documents.py`
- `POST /api/v1/documents/upload` - Tải lên tài liệu
- `GET /api/v1/documents` - Danh sách tài liệu (phân trang)
- `GET /api/v1/documents/{id}` - Chi tiết tài liệu
- `GET /api/v1/documents/{id}/status` - Trạng thái xử lý (Redis cache)
- `GET /api/v1/documents/{id}/curriculum-tree` - Cây chương
- `DELETE /api/v1/documents/{id}` - Xóa tài liệu
- `POST /api/v1/documents/{id}/rescan-structure` - Quét lại cấu trúc
- `POST /api/v1/documents/{id}/reprocess` - Xử lý lại RAG

#### `routers/exams.py`
- `POST /api/v1/exams/generate` - Tạo đề thi (rate limit: 10/ngày/user)
- `GET /api/v1/exams` - Danh sách đề thi
- `GET /api/v1/exams/{id}` - Chi tiết đề thi
- `PATCH /api/v1/exams/{id}/questions/{qid}` - Chỉnh sửa câu hỏi
- `POST /api/v1/exams/{id}/regenerate` - Tái sinh toàn bộ
- `GET /api/v1/exams/{id}/export/pdf` - Xuất PDF
- `GET /api/v1/exams/{id}/export/docx` - Xuất DOCX
- `POST /api/v1/exams/{id}/approve-blueprint` - Duyệt blueprint (HITL CP1)
- `POST /api/v1/exams/{id}/reject-blueprint` - Từ chối blueprint (HITL CP1)
- `POST /api/v1/exams/{id}/submit-review` - Gửi review (HITL CP2)
- `GET /api/v1/exams/{id}/review-data` - Dữ liệu review
- `GET /api/v1/exams/{id}/preview` - Preview HTML

#### `routers/generate.py`
- `POST /api/v1/generate/exam` - Tạo đề (FE-compatible, sync)
- `POST /api/v1/generate/partial-regenerate` - Tái sinh một phần

### 5.3 Database Models

#### `models/user.py`
```python
User:
  - id: UUID (PK)
  - email: String (unique, indexed)
  - password_hash: String
  - full_name: String
  - role: Enum (STUDENT, TEACHER, ADMIN)
  - created_at, updated_at: DateTime
```

#### `models/document.py`
```python
Document:
  - id: UUID (PK)
  - user_id: UUID (FK → User)
  - filename: String
  - s3_key: String
  - file_type: Enum (PDF, DOCX, PPTX)
  - file_size: Integer (bytes)
  - processing_status: Enum (PENDING, PROCESSING, COMPLETED, FAILED)
  - heading_tree: JSONB  # {chapters: [{id, title, level, children}]}
  - total_pages: Integer
  - total_chapters: Integer
  - total_chunks: Integer
  - metadata: JSONB  # extracted metadata
  - error_message: Text (nullable)
  - created_at, updated_at: DateTime
```

#### `models/exam.py`
```python
Exam:
  - id: UUID (PK)
  - user_id: UUID (FK → User)
  - document_id: UUID (FK → Document, nullable)
  - title: String
  - scope: JSONB  # {chapters: [{id, title}], selection_method}
  - exam_config: JSONB  # {type, question_count, bloom_distribution, ...}
  - questions: JSONB  # [{id, type, content, options, answer, bloom_level, ...}]
  - blueprint: JSONB  # {slots: [{question_id, bloom_level, chapter, topic}]}
  - status: Enum (GENERATING, HITL_PENDING_1, HITL_PENDING_2, HITL_PENDING_3, COMPLETED, FAILED, CANCELLED)
  - checkpoint_state: JSONB  # current checkpoint metadata
  - generation_metadata: JSONB  # tokens, cost, model used
  - quality_metrics: JSONB  # {verifier_pass_rate, evidence_coverage}
  - created_at, updated_at: DateTime

ExamHistory:
  - id: UUID (PK)
  - exam_id: UUID (FK → Exam)
  - snapshot: JSONB  # full exam state at this point
  - change_type: Enum (CREATED, UPDATED, REGENERATED, PUBLISHED)
  - change_description: Text
  - created_at: DateTime
```

#### `models/teacher_preference.py`
```python
TeacherPreference:
  - id: UUID (PK)
  - user_id: UUID (FK → User, unique)
  - preferred_bloom_distribution: JSONB  # {Nhớ: 10, Hiểu: 20, ...}
  - preferred_exam_types: JSONB  # ["Trắc nghiệm", "Tự luận"]
  - subject_focus: String
  - additional_notes: Text
  - created_at, updated_at: DateTime
```

---

## 6. Hệ thống Multi-Agent

### 6.1 Tổng quan 5 Agent

```
┌─────────────────────────────────────────────────────────────────┐
│                    Orchestrator (Agent 0)                        │
│              Master coordinator via LangGraph                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
    ┌────────────────────┼────────────────────┐
    ▼                    ▼                    ▼
┌─────────┐       ┌──────────┐        ┌──────────┐
│Retrieval│       │  Outline │        │  Builder │
│Agent 1  │       │ Agent 2  │        │ Agent 3  │
│  (RAG)  │──────▶│(Blueprint)│───────▶│(Question)│
└─────────┘       └──────────┘        └─────┬────┘
                                           │
                                           ▼
                                    ┌──────────┐
                                    │ Validator│
                                    │ Agent 4  │
                                    │(Critic)  │
                                    └──────────┘
```

### 6.2 Agent 0: Orchestrator (`orchestrator.py`)

**Vai trò**: Điều phối toàn bộ pipeline

**Các phương thức chính**:
- `generate_exam()`: Entry point chính, chạy LangGraph với `thread_id=exam_id`
- `reject_blueprint()`: G8 - Xử lý từ chối blueprint, tiêm feedback vào prompt
- `approve_blueprint()`: G7 - Duyệt blueprint, cập nhật Redis
- `submit_review()`: G14 - Lưu teacher preferences, dispatch task
- `edit_via_prompt()`: Chỉnh sửa đề bằng prompt

### 6.3 Agent 1: Retrieval (`retrieval.py`)

**Vai trò**: Truy xuất knowledge chunks từ Pinecone

**Quy trình**:
1. G11: Query expansion - Tạo 3-5 biến thể query
2. G10: Truy xuất song song theo chapter
3. Reranking bằng CrossEncoder
4. Token budget enforcement (cắt chunks nếu vượt MAX_CONTEXT_TOKENS)

### 6.4 Agent 2: Outline (`outline.py`)

**Vai trò**: Tạo blueprint đề thi

**Output**: `OutlineOutput`:
- `blueprint`: Danh sách slots, mỗi slot có `question_id`, `bloom_level`, `chapter`, `topic`
- `distribution_summary`: Thống kê phân bố Bloom
- `estimated_tokens`, `estimated_cost`

**G8 Feedback Loop**: Nếu bị reject, `outline_feedback` được tiêm vào prompt tiếp theo

### 6.5 Agent 3: Builder (`builder.py`)

**Vai trò**: Sinh câu hỏi từ blueprint slots

**Skill pipeline cho mỗi câu hỏi**:
1. `bloom_classifier` - Xác định Bloom level
2. `difficulty_estimator` - Ước lượng độ khó
3. `dedup_checker` - Kiểm tra trùng lặp
4. `latex_renderer` - Render LaTeX

**Fallback**: Nếu LLM thất bại sau 3 lần thử, dùng demo question

### 6.6 Agent 4: Validator (`validator.py`)

**Vai trò**: Kiểm tra chất lượng câu hỏi

**Validations**:
- `bloom_compliance`: Câu hỏi có đúng Bloom level?
- `scope_violation`: Câu hỏi có nằm ngoài scope?
- `answer_solvability`: LLM giải được đáp án?

**G9 Retry Logic**: Issues được lưu vào Redis để survive Celery restarts

---

## 7. LangGraph Pipeline

### 7.1 State Schema (`graph/state.py`)

```python
ExamGraphState (TypedDict):
  # Identity
  - exam_id: str
  - user_id: str
  - document_id: Optional[str]
  
  # Configuration snapshot
  - user_prompt: str
  - exam_config: dict
  - scope: dict
  
  # Pipeline status
  - pipeline_status: PipelineStatus enum
  
  # Intermediate products
  - retrieval_result: Optional[RetrievalOutput]
  - outline_result: Optional[OutlineOutput]
  - builder_result: Optional[BuilderOutput]
  - validation_result: Optional[ValidatorOutput]
  
  # HITL checkpoints
  - checkpoint_1_state: HITLCheckpointStatus
  - checkpoint_2_state: HITLCheckpointStatus
  - checkpoint_3_state: HITLCheckpointStatus
  
  # Memory & errors
  - short_term_memory: dict
  - long_term_memory: Optional[TeacherPreference]
  - errors: List[str]
  - retry_count: int
```

### 7.2 27 Nodes và Data Flow

```
[START]
    │
    ▼
┌──────────────────────────────────────────────┐
│              initialize                       │
│  - Set default HITL timeouts                 │
│  - retry_count = 0                           │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│         clarification_check                   │
│  - Check if user needs clarification          │
└──────────┬───────────────────────────┬───────┘
           │ no clarification needed   │ needs clarification
           ▼                           ▼
┌──────────────────────────────────┐  ┌──────────────────────┐
│        decide_plan               │  │ emit_clarification   │
│  - complex? → plan_complex       │  │ → END                │
│  - simple? → retrieve_knowledge │  └──────────────────────┘
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│                  retrieve_knowledge                   │
│  - Agent 1: Query expansion + Pinecone retrieval     │
│  - Reranking + token budget enforcement              │
└──────────┬────────────────────────────┬──────────────┘
           │ success                    │ failure
           ▼                            ▼
┌──────────────────────┐  ┌─────────────────────────────┐
│    create_outline    │  │  handle_retrieval_failure   │
│  - Agent 2: Blueprint│  │  → create_outline (empty)   │
│  - G8: inject feedback│ └─────────────────────────────┘
└──────────┬───────────┴──────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│            emit_checkpoint_1                  │
│  - WebSocket: blueprint to FE                 │
│  - Auto-approve if timeout                    │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│       wait_for_blueprint_approval            │
│  🔴 HITL INTERRUPT #1                        │
│  - await user approval/rejection             │
│  - Command(resume=...) from /approve-        │
│    or /reject-blueprint endpoint             │
└──────────┬───────────────────────────┬──────┘
           │ approved                   │ rejected
           ▼                            ▼
┌──────────────────────┐  ┌─────────────────────────────┐
│  build_questions     │  │ create_outline (with feedback│
│  - Agent 3: Generate │  │   from rejection)           │
│    questions one by  │  │   → emit_checkpoint_1       │
│    one (chunk_size=1)│  └─────────────────────────────┘
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│           validate_questions                  │
│  - Agent 4: Quality checks                   │
│  - Bloom compliance, scope, solvability      │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│        check_validation_result                │
│  ┌─────────┬──────────────┬────────────────┐ │
│  │ passed  │ retry (<3)   │ max exceeded  │ │
│  ▼         ▼              ▼                │ │
│ emit_cp2  retry_builder  handle_max_        │ │
│                          retries_exceeded   │ │
└─────────────────────────────────────────────┘
           │
           ▼ (loop back)
┌──────────────────────────────────────────────┐
│            retry_builder                      │
│  - Self-loop to validate_questions           │
│  - G9: Load/save issues from Redis          │
└──────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│           emit_checkpoint_2                   │
│  - WebSocket: questions list to FE           │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│           wait_for_review                    │
│  🔴 HITL INTERRUPT #2                        │
│  - await user review submission              │
│  - Command(resume=...) from /submit-review   │
└──────────┬───────────────────────────┬──────┘
           │ approved                   │ rejected
           ▼                            ▼
┌──────────────────────┐  ┌─────────────────────────────┐
│save_teacher_pref     │  │ build_questions (with edits)│
└──────────┬───────────┘  │   → validate_questions      │
           ▼              └─────────────────────────────┘
┌──────────────────────────────────────────────┐
│           emit_checkpoint_3                  │
│  - WebSocket: final preview                  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│           finalize_output                     │
│  - Save final exam to DB                     │
│  - Update status = COMPLETED                 │
│  - WebSocket: generation_complete           │
└──────────────────────────────────────────────┘
                   │
                   ▼
                  [END]
```

### 7.3 HITL Checkpoints Chi tiết

#### Checkpoint 1: Blueprint Approval (G7/G8)
- **Trigger**: Sau khi outline được tạo
- **Frontend**: Modal hiển thị blueprint với:
  - Tổng số câu hỏi theo phân bố Bloom
  - Danh sách chương được chọn
  - Ước lượng chi phí/token
- **Actions**:
  - **Approve** → `Command(resume={"action": "approve"})` → build_questions
  - **Reject** → Lưu feedback + tạo outline mới
  - **Timeout** (5 phút) → Auto-approve

#### Checkpoint 2: Questions Review (G14)
- **Trigger**: Sau khi questions được build và validate
- **Frontend**: Danh sách câu hỏi với:
  - Nội dung câu hỏi
  - Đáp án đúng
  - Bloom level
  - Nút edit/lock/delete mỗi câu
- **Actions**:
  - **Submit** → Lưu preferences → finalize
  - **Edit + Submit** → Chỉnh sửa rồi gửi

#### Checkpoint 3: Preview
- **Trigger**: Trước khi finalize
- **Frontend**: Preview đề thi hoàn chỉnh dạng HTML

---

## 8. RAG Pipeline

### 8.1 Tổng quan luồng

```
Document Upload
      │
      ▼
┌─────────────┐
│  Parser     │  PDF: Gemini → Marker → PyMuPDF fallback
│             │  DOCX: python-docx
│             │  PPTX: python-pptx
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Cleaner    │  Remove noise, normalize formatting
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Structure  │  Detect heading tree from markdown
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Chunker    │  Semantic chunking (overlap)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Embedder   │  BAAI/bge-m3 → embeddings
└──────┬──────┘
       │
       ▼
┌─────────────┐
│Vector Store │  Upsert to Pinecone (namespaced)
└─────────────┘
```

### 8.2 Parser (`rag/parser.py`)

**PDF parsing (3-level fallback)**:

```
Level 1: Gemini (google.genai SDK)
  ├── Split PDF into 10-page chunks
  ├── Distribute to worker threads
  ├── Vietnamese prompt: structure + math + images
  └── Thread-safe ParserJobCoordinator

Level 2: Marker server (QWEN_VISION_BASE_URL/parse-pdf)
  └── Remote API call fallback

Level 3: PyMuPDF (local)
  ├── Font-size based heading detection
  └── Basic text extraction
```

### 8.3 Embedder (`rag/embedder.py`)

- **Model**: `BAAI/bge-m3` (sentence-transformers)
- **Cache**: Redis với 7-day TTL
- **Fallback**: Hash-based deterministic embedding nếu model unavailable
- **Reranker**: `BAAI/bge-reranker-v2-m3` (local CrossEncoder)

### 8.4 Vector Store (`rag/vector_store.py`)

- **Pinecone** với namespace pattern: `{doc_id}_{chapter_id}` (ASCII-safe)
- **Methods**:
  - `upsert_chunks()` - Batch upsert
  - `query_namespace()` - Semantic search
  - `count_chunks_in_scope()` - Kiểm tra số chunks
  - `delete_document_vectors()` - Cleanup

---

## 9. Cơ sở dữ liệu & Lưu trữ

### 9.1 PostgreSQL

**Tables**: `users`, `documents`, `exams`, `exam_history`, `teacher_preferences`

**Indexes**:
- `users.email` (unique)
- `documents.user_id`
- `exams.user_id`
- `exams.document_id`
- `exams.status`

### 9.2 Redis

**Use cases**:
| Key Pattern | Purpose | TTL |
|-------------|---------|-----|
| `session:{exam_id}:{user_id}` | Short-term memory | 2h |
| `retry_issues:{exam_id}` | G9 retry issues | 1h |
| `hitl:approved:{exam_id}:1` | HITL CP1 approval | 30min |
| `doc_status:{doc_id}` | Processing status cache | - |
| `embed_cache:{hash}` | Embedding cache | 7d |
| `rate_limit:gen:{user_id}` | Rate limiting | 24h |

### 9.3 MinIO/S3

**Bucket**: `documents` (configurable via `S3_BUCKET_NAME`)

**Key pattern**: `{user_id}/{document_id}/{filename}`

**Operations**:
- Upload (signed URL hoặc direct)
- Download (presigned URL, 1h expiry)
- Delete (cascade với DB records + Pinecone vectors)

### 9.4 Pinecone

**Index**: `curriculum` (configurable)

**Namespace**: `{doc_id}_{chapter_id}` (ASCII-safe)

**Metadata stored per vector**:
- `doc_id`, `chapter_id`, `chapter_title`
- `chunk_index`, `total_chunks`
- `source_file`, `page_number`

---

## 10. WebSocket & Thời gian thực

### 10.1 Connection Manager (`websocket/manager.py`)

```python
class ConnectionManager:
  # Exam WebSocket connections
  active_connections: Dict[str, Set[WebSocket]]
  
  # Redis pub/sub fan-out
  redis_pubsub: asyncio.Task
  
  # Event replay for reconnect
  ws_events:{exam_id}: List[SSEvent]
  
  # Methods
  connect(exam_id, websocket)
  disconnect(exam_id, websocket)
  emit(exam_id, event_type, data)  # store + send + publish
  listen_redis(channel)  # fan-out from Redis to local clients
```

### 10.2 Event Replay Mechanism (G19)

Khi client reconnect, server replay tất cả events từ Redis LIST:

```
1. Client connects → receives last_event_id
2. Server reads: LRANGE ws_events:{exam_id} {last_event_id} -1
3. Server sends all missed events
4. Client resumes from correct state
```

### 10.3 SSEvent Types

```python
SSEvent.generation_started()
SSEvent.retrieval_progress()
SSEvent.outline_created()
SSEvent.checkpoint_1()
SSEvent.questions_building()
SSEvent.questions_built()
SSEvent.validation_progress()
SSEvent.validation_done()
SSEvent.checkpoint_2()
SSEvent.checkpoint_3()
SSEvent.generation_complete()
SSEvent.generation_error()
SSEvent.generation_cancelled()
SSEvent.heartbeat()
```

---

## 11. Background Tasks (Celery)

### 11.1 Celery Configuration (`tasks/celery_app.py`)

```python
broker_url = REDIS_URL
result_backend = REDIS_URL
task_serializer = json
accept_content = [json]
timezone = Asia/Ho_Chi_Minh
task_time_limit = 7200  # 2h hard limit
task_soft_time_limit = 6600  # 1h50 soft limit
worker_prefetch_multiplier = 1
task_acks_late = True
```

### 11.2 Exam Generation Task (`tasks/exam_task.py`)

```python
@celery_app.task(bind=True, max_retries=3)
def generate_exam_task(self, exam_id: str, config: dict):
  # Idempotency guard (check exam status)
  # Run async via asyncio.new_event_loop()
  # Store progress in Redis for WebSocket
  # Fallback: in-memory storage if Redis unavailable
```

### 11.3 Document Processing Task (`tasks/document_task.py`)

Xử lý tài liệu trong background:
- Parse document
- Extract heading tree
- Chunk content
- Generate embeddings
- Upsert to Pinecone
- Update processing status

---

## 12. API Reference

### 12.1 Authentication

```
POST /api/v1/auth/register
Body: { email, password, full_name }
Response: { user, access_token, refresh_token }

POST /api/v1/auth/login
Body: { email, password }
Response: { user, access_token, refresh_token }

POST /api/v1/auth/refresh
Body: { refresh_token }
Response: { access_token, refresh_token }

POST /api/v1/auth/logout
Headers: Authorization: Bearer {token}
Response: { message }
```

### 12.2 Documents

```
POST /api/v1/documents/upload
Headers: Authorization, Content-Type: multipart/form-data
Body: file (PDF/DOCX/PPTX, max 100MB)
Response: { id, filename, file_type, processing_status }

GET /api/v1/documents?page=1&limit=10&status=COMPLETED
Headers: Authorization
Response: { items: [], total, page, limit }

GET /api/v1/documents/{id}
Headers: Authorization
Response: { document object with heading_tree }

GET /api/v1/documents/{id}/status
Headers: Authorization
Response: { status, progress, message }

GET /api/v1/documents/{id}/curriculum-tree
Headers: Authorization
Response: { tree: { id, title, level, children, page_range } }

DELETE /api/v1/documents/{id}
Headers: Authorization
Response: { message }

POST /api/v1/documents/{id}/reprocess
Headers: Authorization
Response: { message }
```

### 12.3 Exams

```
POST /api/v1/exams/generate
Headers: Authorization
Body: {
  document_id,
  scope: { chapters: [{id, title}], selection_method },
  config: {
    type: "trac_nghiem" | "tu_luan" | "mixed",
    question_count: 30,
    bloom_distribution: { "Nhớ": 5, "Hiểu": 10, ... },
    difficulty: "medium",
    time_limit: 90,
    include_answers: true
  }
}
Response: { exam_id, status }

GET /api/v1/exams?page=1&limit=10&status=COMPLETED
Headers: Authorization
Response: { items: [], total, page, limit }

GET /api/v1/exams/{id}
Headers: Authorization
Response: { exam object with questions }

PATCH /api/v1/exams/{id}/questions/{qid}
Headers: Authorization
Body: { content?, options?, answer?, bloom_level?, ... }
Response: { question }

POST /api/v1/exams/{id}/approve-blueprint
Headers: Authorization
Body: { notes? }
Response: { message, checkpoint_2_state }

POST /api/v1/exams/{id}/reject-blueprint
Headers: Authorization
Body: { feedback: "..." }
Response: { message }

POST /api/v1/exams/{id}/submit-review
Headers: Authorization
Body: {
  action: "approve" | "request_changes",
  edited_questions?: [...],
  preferences?: {...}
}
Response: { message, exam }

GET /api/v1/exams/{id}/export/pdf
Headers: Authorization
Query: ?include_answers=true&include_blueprint=true
Response: Binary PDF (max 10MB)

GET /api/v1/exams/{id}/export/docx
Headers: Authorization
Query: ?include_answers=true
Response: Binary DOCX (max 10MB)
```

### 12.4 Rate Limiting

| Endpoint | Limit |
|----------|-------|
| `POST /api/v1/exams/generate` | 10/user/24h |
| `POST /api/v1/auth/login` | 20/user/15min |

---

## 13. Cấu hình môi trường

### 13.1 Backend Environment Variables (`.env`)

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/examai
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=examai

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=your-secret-key-here
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# LLM Providers
ORCHESTRATOR_PROVIDER=groq
ORCHESTRATOR_MODEL=llama-3.3-70b-versatile
ORCHESTRATOR_API_KEY=...

BUILDER_PROVIDER=groq
BUILDER_MODEL=llama-3.3-70b-versatile
BUILDER_API_KEY=...

# Gemini (for PDF parsing)
GEMINI_API_KEY=...
GEMINI_KEYS_FILE=./.gemini_keys

# Pinecone
PINECONE_API_KEY=...
PINECONE_INDEX=curriculum
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1

# S3/MinIO
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET_NAME=documents
S3_REGION=us-east-1

# Qwen/Marker (optional)
QWEN_VISION_BASE_URL=http://localhost:8001

# LangFuse (optional)
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Demo Mode
DEMO_MODE=false

# App
API_V1_PREFIX=/api/v1
CORS_ORIGINS=["http://localhost:3000"]
LOG_LEVEL=INFO
```

### 13.2 Frontend Environment Variables

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000
NEXT_PUBLIC_APP_NAME=ExamAI
```

---

## 14. Lưu ý quan trọng

### 14.1 Về Gemini Keys

File `.gemini_keys` chứa danh sách API keys Gemini (mỗi dòng 1 key). Code sẽ đọc file này và sử dụng luân phiên. Nếu không có file, dùng `GEMINI_API_KEY` env var.

### 14.2 Về Demo Mode

Khi `DEMO_MODE=true` hoặc không có `document_id`:
- Không gọi LLM
- Sinh câu hỏi demo cố định
- Không truy xuất vector DB

### 14.3 Về HITL Timeouts

- Checkpoint 1: Mặc định 5 phút, auto-approve nếu timeout
- Timeout được cấu hình trong `app/core/config.py`

### 14.4 Về Celery Idempotency

Task `generate_exam_task` có idempotency guard:
- Kiểm tra `exam.status` trước khi chạy
- Nếu đã `COMPLETED` hoặc `GENERATING`, skip

### 14.5 Về G19 Event Replay

- Events được lưu vào Redis LIST `ws_events:{exam_id}`
- Max 1000 events per exam (trim oldest)
- Client nên gửi `Last-Event-ID` header khi reconnect

### 14.6 Về LLM Fallback Chains

Mỗi role có thể cấu hình nhiều provider fallback:
```
ORCHESTRATOR_PROVIDER=groq → openai → anthropic
```

### 14.7 Về File Parsing Fallback

```
PDF: Gemini → Marker → PyMuPDF
```

Nếu không có API keys, hệ thống vẫn hoạt động với PyMuPDF cơ bản (chất lượng thấp hơn).

### 14.8 Về Redis Graceful Degradation

- Nếu Redis unavailable: dùng in-memory fallback
- Ghi log warning
- Một số tính năng bị hạn chế (rate limiting, session memory, event replay)

### 14.9 Về Pinecone Graceful Degradation

- Nếu Pinecone unavailable: vẫn tạo đề nhưng không truy xuất knowledge
- Ghi log error
- Trả về warning trong response

### 14.10 Về CORS

Frontend chạy ở `localhost:3000`, backend ở `localhost:8000`. CORS được cấu hình trong `app/core/config.py` với `CORS_ORIGINS`.

---

## Phụ lục: Danh sách file loại trừ

Các thư mục sau **KHÔNG** thuộc spec vì là dữ liệu rác/thử nghiệm:

```
chunking/              # Code thử nghiệm chunking
chunking_demo/         # Demo chunking
data sách/             # Dữ liệu sách test
kaggle/                # Dataset kaggle
docs/                  # Tài liệu tham khảo
figures/               # Hình ảnh minh họa
node_modules/          # Dependencies
__pycache__/           # Python cache
.next/                 # Next.js build
.venv/                 # Virtual environment
```

---

*Document generated: 2026-04-27*
*Version: 1.0*
