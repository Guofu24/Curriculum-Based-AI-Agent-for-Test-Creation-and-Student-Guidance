# Curriculum AI Agent - System Specification (SPEC)

> **Ngày viết:** 02/05/2026  
> **Nguồn:** Phân tích code thực tế từ Backend (`e:\Đồ án\Project\backend`) và Frontend (`e:\Đồ án\Project\Frontend`)  
> **Lưu ý:** Chỉ mô tả những gì đang chạy được thực tế, không dựa vào docs hay file md có sẵn.

---

## 1. Tổng Quan Hệ Thống

### 1.1 Kiến trúc tổng thể

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (Next.js 16.2.0)                     │
│  http://localhost:3000                                                     │
│  ├── / (Auth: Login/Register)                                              │
│  └── /dashboard/* (Protected routes với sidebar)                           │
│       ├── /dashboard (Home: stats, charts, recent exams)                   │
│       ├── /dashboard/generate (3-step exam generation wizard)             │
│       ├── /dashboard/exams/* (List, Detail, History)                      │
│       ├── /dashboard/documents/* (Upload, List, Detail)                    │
│       ├── /dashboard/feedback (Feedback store viewer)                      │
│       └── /dashboard/settings (User settings)                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │ HTTP REST + WebSocket
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND (FastAPI)                              │
│  http://localhost:8000                                                     │
│  ├── /api/v1/auth/* (JWT Authentication)                                   │
│  ├── /api/v1/documents/* (Document CRUD + RAG pipeline)                   │
│  ├── /api/v1/exams/* (Exam CRUD + Generation + HITL)                     │
│  ├── /api/v1/generate/* (Generation triggers)                              │
│  ├── /ws/exam/{id} (Real-time generation streaming)                      │
│  └── /ws/document/{id} (Real-time upload progress)                        │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                    │                    │
         ▼                    ▼                    ▼                    ▼
┌─────────────┐    ┌─────────────────┐   ┌─────────────┐   ┌─────────────────┐
│ PostgreSQL  │    │     Redis       │   │   Pinecone   │   │   MinIO (S3)    │
│ (asyncpg)  │    │ (caching/pubsub)│   │ (vector DB)  │   │  (file storage) │
└─────────────┘    └─────────────────┘   └─────────────┘   └─────────────────┘
```

### 1.2 Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Next.js 16.2.0, React 19, TypeScript, Tailwind CSS 4.2 |
| **Backend** | FastAPI, Python 3.11+, SQLAlchemy 2.0 (async) |
| **Database** | PostgreSQL (async via asyncpg) |
| **Cache/PubSub** | Redis 5.x |
| **Vector Store** | Pinecone 5.x |
| **LLM Providers** | Groq (primary), OpenAI, Anthropic Claude, Ollama, g4f, Google Gemini |
| **Embeddings** | Sentence Transformers (BAAI/bge-m3) - local |
| **Task Queue** | Celery 5.x (optional, background tasks) |
| **Storage** | MinIO (local S3) or AWS S3 |
| **Agent Framework** | LangGraph 0.2+ |
| **Observability** | LangFuse, Sentry |

---

## 2. BACKEND API ENDPOINTS

### 2.1 Authentication `/api/v1/auth`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/register` | Register teacher account (email, password, full_name) |
| POST | `/login` | Login with email/password, returns JWT access + refresh tokens |
| POST | `/refresh` | Refresh access token using refresh token rotation |
| POST | `/logout` | Revoke refresh token |
| GET | `/me` | Get current user profile |

**JWT Config:**
- Access token TTL: 15 minutes
- Refresh token TTL: 7 days
- Algorithm: HS256
- Refresh token rotation: enabled

### 2.2 Documents `/api/v1/documents`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/upload` | Upload PDF/DOCX/PPTX file (max 100MB) |
| GET | `/` | List user's documents (paginated) |
| GET | `/{document_id}` | Get document details with heading_tree |
| GET | `/{document_id}/status` | Get processing status (cached 1s) |
| DELETE | `/{document_id}` | Delete document (DB + S3 + Pinecone) |
| GET | `/{document_id}/refresh-url` | Generate presigned download URL |
| GET | `/{document_id}/curriculum-tree` | Get flattened curriculum tree |
| PATCH | `/{document_id}/curriculum-tree` | Update curriculum tree |
| POST | `/{document_id}/rescan-structure` | Re-detect heading tree |
| POST | `/{document_id}/reprocess` | Re-chunk and re-index to Pinecone |

**Document Processing Pipeline (RAG):**
1. Upload to MinIO/S3
2. Parse document (PDF → markdown via PyMuPDF, DOCX → markdown, PPTX → markdown)
3. Detect heading tree (LLM-based with pattern fallback)
4. Semantic chunking (by headings, max 1200 tokens, 200 overlap)
5. Embed chunks (BAAI/bge-m3, 1024 dimensions)
6. Upsert to Pinecone (per-chapter namespace)

**Processing Status:** `pending` → `processing` → `completed` → `indexed`

### 2.3 Exams `/api/v1/exams`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/generate` | Start exam generation (rate-limited: 10/day) |
| GET | `/` | List user's exams (paginated, filterable by status) |
| GET | `/quality-summary` | Aggregated quality metrics |
| GET | `/feedback-summary` | Feedback store summary |
| GET | `/feedback-store` | Paginated feedback events |
| GET | `/{exam_id}` | Full exam details |
| GET | `/{exam_id}/versions` | Version history |
| GET | `/{exam_id}/feedback` | Exam's feedback events |
| POST | `/{exam_id}/publish` | Publish exam |
| DELETE | `/{exam_id}` | Delete exam |
| POST | `/{exam_id}/backfill-blueprint` | Synthesize blueprint from questions |
| POST | `/{exam_id}/backfill-quality` | Recompute quality metrics |
| PATCH | `/{exam_id}/questions/{qid}` | Edit question inline |
| POST | `/{exam_id}/edit-prompt` | Edit via natural language |
| POST | `/{exam_id}/regenerate` | Regenerate questions |
| GET | `/{exam_id}/export/pdf` | Export PDF (include_answers, include_blueprint) |
| GET | `/{exam_id}/export/docx` | Export DOCX |
| GET | `/{exam_id}/history` | Version snapshots |
| POST | `/{exam_id}/history/{hid}/restore` | Restore snapshot |
| POST | `/{exam_id}/approve-blueprint` | HITL CP1: Approve blueprint |
| POST | `/{exam_id}/reject-blueprint` | HITL CP1: Reject with feedback |
| GET | `/{exam_id}/review-data` | Full review data for HITL CP2 |
| GET | `/{exam_id}/preview` | HTML export preview |
| POST | `/{exam_id}/submit-review` | HITL CP2: Submit review |

### 2.4 Generation `/api/v1/generate`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/exam` | Start generation (FE-compatible, async) |
| POST | `/partial-regenerate` | Partial regeneration with edits |

### 2.5 WebSocket Endpoints

| Path | Description |
|------|-------------|
| `/ws/exam/{exam_id}` | Real-time exam generation streaming |
| `/ws/document/{document_id}` | Real-time upload/processing progress |

### 2.6 Health Checks

| Path | Description |
|------|-------------|
| GET | `/health` | Liveness probe |
| GET | `/ready` | Readiness check (postgres + redis + pinecone) |

---

## 3. FRONTEND ROUTES & FEATURES

### 3.1 Route Structure

```
/ (AuthPage)
├── /dashboard (DashboardPage)
│   ├── /dashboard/generate (GeneratePage)
│   ├── /dashboard/exams (ExamListPage)
│   ├── /dashboard/exams/[id] (ExamDetailPage)
│   ├── /dashboard/exams/[id]/history (ExamHistoryPage)
│   ├── /dashboard/documents (DocumentListPage)
│   ├── /dashboard/documents/[id] (DocumentDetailPage)
│   ├── /dashboard/feedback (FeedbackPage)
│   └── /dashboard/settings (SettingsPage)
```

### 3.2 Auth (`/`)
- Login form (email + password)
- Register form (email + password + full_name)
- JWT token storage in localStorage
- Auto-redirect to `/dashboard` if authenticated
- Token refresh on 401 response

### 3.3 Dashboard Layout
- Protected by auth guard (redirect to `/` if not authenticated)
- Collapsible sidebar with user profile
- Dark/light mode toggle (next-themes)
- Toast notifications (sonner)

### 3.4 Dashboard Home (`/dashboard`)
- Statistics cards (total exams, quality score, etc.)
- Quality metrics charts (Recharts)
- Recent exams list
- Quick actions

### 3.5 Generate Page (`/dashboard/generate`)

**3-step wizard:**

**Step 1 - Select Document:**
- Grid of completed documents (status: completed/indexed)
- Document cards showing filename, chapter count, chunk count
- Select to proceed

**Step 2 - Configure Exam:**
- Scope selection (checkboxes for chapters from curriculum tree)
- Title input (optional)
- Exam type: MCQ / Essay / Mixed
- MCQ count (1-50) and Essay count (0-10)
- Bloom Taxonomy distribution sliders:
  - Nhận biết (nhan_biet)
  - Thông hiểu (thong_hieu)
  - Vận dụng (van_dung)
  - Vận dụng cao (van_dung_cao)
  - Total must equal 100%
- Strict scope flag (checkbox)
- Additional instructions textarea (500 char max)

**Step 3 - Generation Live Viewer:**
- Real-time pipeline progress (6 steps)
- WebSocket connection status indicator
- Blueprint review panel (HITL CP1)
- Question streaming display
- Validation issues display
- HITL checkpoint approval/rejection dialogs
- Completion celebration

### 3.6 Exam List (`/dashboard/exams`)
- Paginated exam list
- Status filter
- Columns: title, type, difficulty, status, questions, quality score, created date
- Delete action

### 3.7 Exam Detail (`/dashboard/exams/[id]`)
- Exam metadata display
- Blueprint table (question slots with Bloom levels)
- Questions display with:
  - Type badge (MCQ/Essay)
  - Bloom level badge
  - Question content
  - MCQ options with correct answer highlight
  - Essay rubric
  - Quality metrics
  - Source citations
  - Validation warnings
- Inline question editing
- Export buttons (PDF/DOCX with answers toggle)
- Version history access
- HITL review actions

### 3.8 Document List (`/dashboard/documents`)
- Paginated document list
- Upload button (PDF/DOCX/PPTX, max 100MB)
- Document cards with:
  - Filename, type, size
  - Processing status
  - Chapter count, chunk count
- Delete action
- Real-time upload progress via WebSocket

### 3.9 Document Detail (`/dashboard/documents/[id]`)
- Document metadata
- Processing status with steps
- Curriculum tree visualization
- Actions: Refresh URL, Rescan Structure, Reprocess

### 3.10 Feedback Page (`/dashboard/feedback`)
- Aggregated feedback summary
- Paginated feedback events list
- Filter by severity, review_status, signal_type
- Signal types: bloom_mismatch, out_of_scope, duplicate, quality_low, answer_incorrect, validation_warning, generation_error, publish, edit_applied

### 3.11 Settings (`/dashboard/settings`)
- User profile form
- Theme toggle
- Preferences

---

## 4. DATABASE MODELS

### 4.1 User
```python
id: UUID (PK)
email: str (unique, indexed)
password_hash: str
full_name: str (nullable)
role: str (default: "teacher")  # student, teacher, admin
created_at: datetime
updated_at: datetime

Relations:
- documents: List[Document]
- exams: List[Exam]
- refresh_tokens: List[RefreshToken]
- preferences: TeacherPreference (one-to-one)
- feedback_events: List[FeedbackEvent]
```

### 4.2 Document
```python
id: UUID (PK)
user_id: UUID (FK -> users, indexed)
course_id: UUID (nullable, indexed)
file_size: int (nullable)
original_filename: str
file_type: str  # pdf, docx, pptx
s3_key: str
processing_status: str  # pending, processing, completed, failed
parse_error_message: str (nullable)
heading_tree: JSONB (nullable)  # nested structure
total_chapters: int (nullable)
total_pages_or_slides: int (nullable)
total_chunks: int (nullable)
uploaded_at: datetime

Relations:
- user: User
- exams: List[Exam]
```

**heading_tree structure:**
```json
{
  "chapters": [
    {
      "chapter_id": "ch1",
      "title": "Chapter 1 Title",
      "sections": [
        {
          "section_id": "ch1_s1",
          "title": "Section 1 Title",
          "subsections": [
            {"section_id": "ch1_s1_ss1", "title": "Subsection Title"}
          ]
        }
      ]
    }
  ]
}
```

### 4.3 Exam
```python
id: UUID (PK)
user_id: UUID (FK -> users, indexed)
document_id: UUID (FK -> documents, nullable)
title: str
scope: JSONB (nullable)  # list of chapter titles
exam_config: JSONB (nullable)
questions: JSONB (nullable)
status: str (indexed)  # draft, generating, hitl_pending_1/2/3, completed, failed, published, regenerating
cost_report: JSONB (nullable)
total_tokens: int (nullable)
total_cost_usd: Decimal (nullable)
blueprint: JSONB (nullable)  # list of BlueprintSlot dicts
checkpoint_state: JSONB (nullable)
generation_metadata: JSONB (nullable)
quality_metrics: JSONB (nullable)
created_at: datetime
updated_at: datetime

Relations:
- user: User
- document: Document (nullable)
- history: List[ExamHistory]
- feedback_events: List[FeedbackEvent]
```

**Exam Status Flow:**
```
draft → generating → hitl_pending_1 → [approved/rejected] → hitl_pending_2 → [approved/rejected] → hitl_pending_3 → completed → published
                         ↓
                      failed/cancelled
```

**BlueprintSlot structure:**
```json
{
  "question_id": "MCQ_001",
  "type": "mcq",
  "bloom_level": "thong_hieu",
  "chapter": "Chapter 1 Title",
  "topic_hint": "Brief description",
  "estimated_difficulty": 0.5
}
```

### 4.4 ExamHistory
```python
id: UUID (PK)
exam_id: UUID (FK -> exams, indexed)
snapshot: JSONB (nullable)
change_type: str  # generate, edit_direct, edit_prompt, regenerate, published
change_description: str (nullable)
created_at: datetime

Relations:
- exam: Exam
```

### 4.5 RefreshToken
```python
id: UUID (PK)
user_id: UUID (FK -> users)
token_hash: str
expires_at: datetime
created_at: datetime
ip_address: str (nullable)
revoked: bool (default: False)

Relations:
- user: User
```

### 4.6 FeedbackEvent
```python
id: UUID (PK)
user_id: UUID (FK -> users, indexed)
exam_id: UUID (FK -> exams, indexed)
signal_type: str  # bloom_mismatch, out_of_scope, duplicate, quality_low, answer_incorrect, validation_warning, generation_error, publish, edit_applied
severity: str  # info, warning, error, critical
workflow_stage: str (nullable)
event_source: str (nullable)
source_type: str (nullable)
source_ref: str (nullable)
review_status: str (nullable)  # pending, accepted, rejected, corrected
reviewed_by_human: bool
question_id: str (nullable)
error_categories: JSONB (nullable)
before_snapshot_ref: str (nullable)
after_snapshot_ref: str (nullable)
payload: JSONB (nullable)
created_at: datetime

Relations:
- user: User
- exam: Exam
```

---

## 5. WEBSOCKET EVENTS

### 5.1 Exam Generation Events (`/ws/exam/{exam_id}`)

| Event Type | Fields | Description |
|------------|--------|-------------|
| `plan_step` | `step`, `total_steps`, `message` | Pipeline progress (0-5) |
| `question_generated` | `question_id`, `question` | Single question generated |
| `validation_result` | `passed`, `issues_count`, `issues` | Validation completed |
| `hitl_checkpoint` | `checkpoint_id`, `data` | HITL pause (0/1/2/3) |
| `pipeline_paused` | `checkpoint_id`, `message`, `blueprint`, `distribution_summary` | Graph paused |
| `completed` | `exam_id`, `total_cost_usd` | Generation completed |
| `error` | `message`, `agent` | Error occurred |

**HITL Checkpoints:**
- **Checkpoint 0:** Requirements confirmation
- **Checkpoint 1:** Blueprint review (approve/reject with feedback)
- **Checkpoint 2:** Full exam review (approve/request changes)
- **Checkpoint 3:** Export preview

### 5.2 Document Upload Events (`/ws/document/{document_id}`)

| Event Type | Fields | Description |
|------------|--------|-------------|
| `upload_started` | `document_id`, `filename` | Upload began |
| `upload_progress` | `document_id`, `percent` | Upload progress |
| `processing_step` | `document_id`, `step`, `message`, `percent` | Processing step |
| `processing_completed` | `document_id`, `filename` | Processing done |
| `processing_failed` | `document_id`, `error` | Processing failed |

---

## 6. AGENT SYSTEM

### 6.1 Multi-Agent Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Orchestrator Agent (Agent 0)                   │
│  - Coordinates all sub-agents                                    │
│  - Manages LangGraph StateGraph                                  │
│  - Handles HITL checkpoints                                      │
│  - Emits WebSocket events                                        │
└────────────────────────┬─────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
┌───────────────┐ ┌─────────────┐ ┌─────────────┐
│ Retrieval     │ │ Outline     │ │ Builder      │
│ Agent (1)    │ │ Agent (2)   │ │ Agent (3)    │
│ - RAG        │ │ - Blueprint │ │ - Questions  │
│ - Reranking  │ │ - Bloom     │ │ - MCQ/Essay │
└───────────────┘ └─────────────┘ └──────┬──────┘
                                        │
                                        ▼
                               ┌─────────────────┐
                               │ Validator       │
                               │ Agent (4)      │
                               │ - Quality      │
                               │ - Scope check  │
                               │ - Bloom match  │
                               └─────────────────┘
```

### 6.2 LangGraph Pipeline Nodes

1. **initialize** - Setup initial state
2. **plan_complex** - Complex request planning
3. **decide_plan** - Route to appropriate path
4. **load_long_term_memory** - Load teacher preferences
5. **clarification_check** - Check for unclear requirements
6. **retrieve_knowledge** - RAG retrieval
7. **create_outline** - Generate blueprint
8. **wait_for_blueprint_approval** - HITL CP1 (interrupt)
9. **build_questions** - Generate questions
10. **validate_questions** - Quality validation
11. **check_validation_result** - Route based on validation
12. **retry_builder** - Retry on validation failure
13. **handle_*_failure** - Error handling
14. **save_teacher_preferences** - G14: Persist preferences
15. **finalize_output** - Complete generation
16. **emit_checkpoint_1/2/3** - HITL events
17. **wait_for_review** - HITL CP2 (interrupt)

### 6.3 HITL (Human-In-The-Loop) Flow

```
1. Teacher submits generation request
        ↓
2. Pipeline creates blueprint (HITL CP1)
        ↓
3. Teacher reviews blueprint:
   - Approve → continue
   - Reject → feedback → regenerate blueprint
        ↓
4. Pipeline generates questions
        ↓
5. Teacher reviews questions (HITL CP2):
   - Approve → ready for export
   - Reject → regenerate with feedback
        ↓
6. Export (HITL CP3 - optional preview)
```

### 6.4 Bloom Taxonomy Levels

| Level | Vietnamese | Description |
|-------|-----------|-------------|
| nhan_biet | Nhận biết | Recall/identify facts |
| thong_hieu | Thông hiểu | Explain/interpret |
| van_dung | Vận dụng | Apply in new situations |
| van_dung_cao | Vận dụng cao | Complex analysis/synthesis |

---

## 7. EXPORT FEATURES

### 7.1 PDF Export
- Uses ReportLab
- Two versions:
  - Student version (no answers)
  - Teacher version (with answers, explanations, rubric)
- Optional: Include blueprint table at top
- Limit: 10MB

### 7.2 DOCX Export
- Uses python-docx
- Two versions: Student / Teacher
- Teacher version includes answer key table

---

## 8. KEY CONFIGURATIONS

### 8.1 Environment Variables (`.env`)

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/curriculum_ai

# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1

# LLM Provider
LLM_PROVIDER=groq
LLM_FALLBACK_CHAIN=groq,ollama,g4f

# Per-Role LLM Models
ORCHESTRATOR_MODEL=llama-3.3-70b-versatile
BUILDER_MODEL=llama-3.3-70b-versatile
VALIDATOR_MODEL=llama-3.3-70b-versatile
OUTLINE_MODEL=llama-3.1-8b-instant

# Pinecone
PINECONE_API_KEY=your_key_here
PINECONE_INDEX=curriculum-ai

# Storage
STORAGE_BACKEND=minio  # or "s3"
MINIO_ENDPOINT_URL=http://127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=curriculum-ai

# JWT
JWT_SECRET_KEY=change-me-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Server
HOST=0.0.0.0
PORT=8000
APP_BASE_URL=http://localhost:8000

# CORS
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

### 8.2 Rate Limiting
- Max exam generations per user per day: 10 (configurable via `MAX_GENERATES_PER_DAY`)

### 8.3 RAG Settings
- Chunk size: 1200 tokens
- Chunk overlap: 200 tokens
- Top K per chapter: 20
- Top K after rerank: 30
- Max context tokens: 12000

---

## 9. FEATURES ĐANG CHẠY (IMPLEMENTED)

### 9.1 Authentication
- [x] JWT login/register with bcrypt password hashing
- [x] Refresh token rotation
- [x] Token auto-refresh on 401
- [x] Logout with token revocation

### 9.2 Document Management
- [x] Upload PDF/DOCX/PPTX (max 100MB)
- [x] Background processing pipeline
- [x] Heading tree detection (LLM + pattern fallback)
- [x] Semantic chunking
- [x] Embedding with BAAI/bge-m3
- [x] Pinecone indexing (per-chapter namespace)
- [x] Curriculum tree management
- [x] Rescan structure / Reprocess

### 9.3 Exam Generation
- [x] 3-step wizard UI (document → config → generate)
- [x] Real-time WebSocket streaming
- [x] Pipeline progress visualization
- [x] Blueprint review (HITL CP1)
- [x] Question streaming
- [x] Validation result display
- [x] HITL approval/rejection flow
- [x] Demo mode (no AI, local sample questions)
- [x] Rate limiting (10/day)

### 9.4 Exam Management
- [x] List exams with pagination/filtering
- [x] View exam details
- [x] Inline question editing
- [x] Edit via prompt (LLM-based)
- [x] Regenerate questions
- [x] Version history with snapshots
- [x] Restore from snapshot
- [x] Quality metrics display
- [x] Feedback events

### 9.5 Export
- [x] PDF export (student/teacher versions)
- [x] PDF with/without blueprint
- [x] DOCX export (student/teacher versions)
- [x] HTML preview before export

### 9.6 Feedback System
- [x] Feedback event logging
- [x] Feedback store aggregation
- [x] Signal types: bloom_mismatch, out_of_scope, duplicate, quality_low, etc.
- [x] Severity levels
- [x] Review status tracking

### 9.7 WebSocket Real-time
- [x] Exam generation streaming
- [x] Document upload progress
- [x] Event replay on reconnect
- [x] Redis pub/sub for multi-instance

### 9.8 Agent System
- [x] Orchestrator with LangGraph
- [x] Retrieval agent (RAG + reranking)
- [x] Outline agent (blueprint generation)
- [x] Builder agent (question generation)
- [x] Validator agent (quality checking)
- [x] HITL checkpoints integration
- [x] Teacher preference memory (G14)

---

## 10. FEATURES CHƯA/CHƯA ĐẦY ĐỦ (NOT FULLY IMPLEMENTED)

### 10.1 Placeholder APIs
- `POST /api/v1/courses/*` - Course router tồn tại nhưng chưa có logic đầy đủ

### 10.2 Incomplete Features
- Long-term memory (TeacherPreference model tồn tại nhưng chưa được gọi đầy đủ)
- Partial regeneration UI - endpoint tồn tại nhưng chưa được integrate vào FE

### 10.3 Optional Features (configured but may not be active)
- LangFuse tracing (requires API keys)
- Celery workers (optional, FastAPI background tasks used instead)
- Sentry (requires DSN)

---

## 11. FILE STRUCTURE

### 11.1 Backend (`backend/`)
```
backend/
├── app/
│   ├── main.py                    # FastAPI app entry
│   ├── config.py                  # Settings re-export
│   ├── dependencies.py            # Auth, DB, Redis dependencies
│   ├── agents/
│   │   ├── orchestrator.py        # Main coordinator
│   │   ├── retrieval.py           # RAG retrieval
│   │   ├── outline.py            # Blueprint creation
│   │   ├── builder.py            # Question generation
│   │   ├── validator.py          # Quality validation
│   │   ├── planner.py            # Complex request planning
│   │   ├── llm.py                # Multi-provider LLM client
│   │   ├── base.py               # Base agent class
│   │   ├── memory/
│   │   │   ├── short_term.py     # Redis session memory
│   │   │   └── long_term.py      # PostgreSQL preferences
│   │   ├── graph/
│   │   │   ├── builder.py         # LangGraph StateGraph builder
│   │   │   ├── state.py          # Graph state schema
│   │   │   └── nodes/            # Pipeline nodes
│   │   └── skills/
│   │       ├── bloom_classifier.py
│   │       └── scope_checker.py
│   ├── core/
│   │   ├── config.py             # Pydantic Settings
│   │   ├── database.py          # Async SQLAlchemy
│   │   └── redis_client.py      # Redis wrapper
│   ├── models/
│   │   ├── user.py
│   │   ├── document.py
│   │   ├── exam.py
│   │   └── feedback.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── document.py
│   │   ├── exam.py
│   │   └── common.py
│   ├── routers/
│   │   ├── auth.py
│   │   ├── courses.py
│   │   ├── documents.py
│   │   ├── exams.py
│   │   └── generate.py
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── exam_service.py
│   │   └── document_service.py
│   ├── rag/
│   │   ├── parser.py             # PDF/DOCX/PPTX parsing
│   │   ├── cleaner.py           # Markdown normalization
│   │   ├── chunker.py          # Semantic chunking
│   │   ├── structure.py        # Heading tree detection
│   │   ├── embedder.py         # Sentence transformer embeddings
│   │   └── vector_store.py     # Pinecone operations
│   ├── tasks/
│   │   ├── celery_app.py
│   │   ├── exam_task.py         # Celery background task
│   │   └── document_task.py
│   ├── websocket/
│   │   └── manager.py          # WebSocket connection manager
│   └── utils/
│       ├── storage.py           # MinIO/S3 abstraction
│       ├── export.py            # PDF/DOCX export
│       └── security.py          # JWT, bcrypt
└── requirements.txt
```

### 11.2 Frontend (`Frontend/`)
```
Frontend/
├── app/
│   ├── layout.tsx               # Root layout (providers)
│   ├── page.tsx                 # Auth page
│   ├── globals.css              # Global styles
│   └── dashboard/
│       ├── layout.tsx           # Dashboard layout (sidebar)
│       ├── page.tsx             # Dashboard home
│       ├── generate/page.tsx    # 3-step generation wizard
│       ├── exams/
│       │   ├── page.tsx        # Exam list
│       │   └── [id]/
│       │       ├── page.tsx     # Exam detail
│       │       └── history/page.tsx
│       ├── documents/
│       │   ├── page.tsx        # Document list
│       │   └── [id]/page.tsx   # Document detail
│       ├── feedback/page.tsx   # Feedback store
│       └── settings/page.tsx   # Settings
├── components/
│   ├── auth-provider.tsx        # Auth context
│   ├── upload-notification-provider.tsx
│   ├── theme-provider.tsx
│   ├── status-badge.tsx
│   ├── generation-live-viewer.tsx  # Real-time generation UI
│   ├── latex-renderer.tsx
│   ├── dashboard-header.tsx
│   ├── empty-state.tsx
│   ├── file-upload.tsx
│   ├── generation-progress.tsx
│   ├── question-editor.tsx
│   ├── curriculum-tree.tsx
│   └── ui/                      # Shadcn/ui components
│       ├── button.tsx
│       ├── card.tsx
│       ├── dialog.tsx
│       ├── sidebar.tsx
│       └── ... (60+ components)
├── lib/
│   ├── api.ts                   # Complete API client
│   ├── utils.ts                # cn() utility
│   └── format.ts               # Formatting utilities
├── package.json
└── tsconfig.json
```

---

## 12. QUICK START

### 12.1 Backend
```bash
cd backend
cp .env.example .env  # Edit with your API keys
pip install -r requirements.txt

# Start dependencies
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:15
docker run -d -p 6379:6379 redis:7
docker run -d -p 9000:9000 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin minio/minio server /data

# Run migrations
alembic upgrade head

# Start backend
uvicorn app.main:app --reload --port 8000
```

### 12.2 Frontend
```bash
cd Frontend
npm install
npm run dev
# Open http://localhost:3000
```

### 12.3 Dependencies Required
- PostgreSQL 15+
- Redis 7+
- MinIO (or AWS S3)
- Pinecone account (for vector search)
- LLM API keys (Groq recommended for development)

---

*Document generated on 2026-05-02 from actual codebase analysis.*
