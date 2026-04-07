# ExamAI — Hệ thống Tạo đề Kiểm tra Vật lý Tự động bằng Multi-Agent AI

<p align="center">
  <img src="figures/logo.svg" width="120" alt="ExamAI Logo" />
</p>

<p align="center">
  <img src="figures/architecture.svg" alt="System Architecture" />
</p>

> **ExamAI** là hệ thống tạo đề kiểm tra Vật lý tự động, sử dụng pipeline **5 agent AI phối hợp** với **Human-in-the-Loop (HITL)** — giảng viên kiểm soát hoàn toàn chất lượng đầu ra.

---

## Mục lục

1. [Tổng quan](#tổng-quan)
2. [Kiến trúc hệ thống](#kiến-trúc-hệ-thống)
3. [Các thành phần chính](#các-thành-phần-chính)
4. [Pipeline Agent — Luồng sinh đề 5 bước](#pipeline-agent--luồng-sinh-đề-5-bước)
5. [Human-in-the-Loop (HITL)](#human-in-the-loop-hitl)
6. [Tính năng nổi bật](#tính-năng-nổi-bật)
7. [Bắt đầu](#bắt-đầu)
8. [Cấu trúc thư mục](#cấu-trúc-thư-mục)
9. [Công nghệ sử dụng](#công-nghệ-sử-dụng)

---

## Tổng quan

**ExamAI** giải quyết bài toán: *"Giảng viên muốn tạo đề kiểm tra Vật lý nhanh, đúng chuẩn Bloom, có đáp án và rubric, từ tài liệu giáo trình PDF của mình — mà không cần viết tay từng câu."*

### Vấn đề cũ (thủ công)
- Tạo 1 đề 40 câu MCQ + 5 câu tự luận mất **2–4 giờ**
- Khó đảm bảo phân bổ Bloom đều
- Câu trả lời sai logic, đáp án mồi nhử không tốt
- Không tái sử dụng được tài liệu

### Giải pháp ExamAI
- Sinh đề trong **vài phút** với chất lượng kiểm soát bởi giảng viên
- Phân bổ Bloom chính xác theo cấu hình
- Đáp án mồi nhử có logic, rubric chấm điểm rõ ràng
- Ghi nhớ sở thích giảng viên (long-term memory)
- **Xuất PDF / DOCX** sẵn sàng in

---

## Kiến trúc hệ thống

<p align="center">
  <img src="figures/agent_pipeline.svg" alt="Agent Pipeline" />
</p>

### Tổng quan kiến trúc

```
┌──────────────────────────────────────────────────────────────────────┐
│                        EXAMAI SYSTEM                                 │
│                                                                      │
│  ┌──────────────┐         ┌──────────────────────┐                   │
│  │   Frontend   │◄───────►│   FastAPI Backend     │                   │
│  │  (Next.js)   │  REST   │   ┌──────────────┐   │                   │
│  │              │   +     │   │  Orchestrator │   │                   │
│  │ Dashboard    │  WS     │   │    Agent      │   │                   │
│  │ Generate     │         │   │  (Agent 0)    │   │                   │
│  │ Review       │         │   └──────┬───────┘   │                   │
│  │ History      │         │          │           │                   │
│  └──────────────┘         │   ┌──────▼───────┐   │                   │
│         │                 │   │ 5 Sub-Agents │   │                   │
│         │                 │   └──────┬───────┘   │                   │
│         │                 └──────────┼────────────┘                   │
│         │                            │                                │
│         ▼                            ▼                                │
│  ┌─────────────┐          ┌───────────────────┐                       │
│  │  PostgreSQL │          │      Redis        │                       │
│  │ (Hồ sơ, đề,│          │ (Short-term mem,  │                       │
│  │  người dùng)│          │  pub/sub events)  │                       │
│  └─────────────┘          └───────────────────┘                       │
│         │                            │                                │
│         │                 ┌──────────▼──────────┐                     │
│         │                 │     Pinecone        │                     │
│         │                 │ (Vector store cho   │                     │
│         │                 │  tài liệu PDF)     │                     │
│         │                 └─────────────────────┘                     │
│         │                                                          │
│         │                 ┌─────────────────────┐                    │
│         └────────────────►│  Celery Worker       │                    │
│                           │  (Async task queue)  │                    │
│                           └─────────────────────┘                    │
└──────────────────────────────────────────────────────────────────────┘
```

### Frontend — Next.js 16 (TypeScript)

| Route | Mô tả |
|---|---|
| `/` | Trang chủ / Landing |
| `/dashboard` | Dashboard chính |
| `/dashboard/generate` | Giao diện sinh đề — chọn tài liệu, cấu hình, theo dõi realtime |
| `/dashboard/exams/[id]` | Chi tiết đề — xem/sửa câu hỏi, HITL review |
| `/dashboard/documents` | Quản lý tài liệu PDF |
| `/dashboard/history` | Lịch sử đã tạo |
| `/dashboard/settings` | Cài đặt giảng viên |

### Backend — FastAPI (Python)

| Module | Vai trò |
|---|---|
| `app/routers/auth.py` | Đăng nhập / đăng ký / JWT tokens |
| `app/routers/documents.py` | Upload, xử lý, chunking PDF → Pinecone |
| `app/routers/exams.py` | CRUD đề, approve/reject, export PDF/DOCX |
| `app/routers/generate.py` | Khởi tạo sinh đề, WebSocket endpoint |
| `app/agents/orchestrator.py` | Agent 0 — điều phối toàn bộ pipeline |
| `app/agents/retrieval.py` | Agent 1 — truy xuất chunks từ Pinecone |
| `app/agents/outline.py` | Agent 2 — tạo blueprint (sườn đề) |
| `app/agents/builder.py` | Agent 3 — sinh câu hỏi từ blueprint |
| `app/agents/validator.py` | Agent 4 — kiểm tra chất lượng |
| `app/agents/planner.py` | Agent phụ — xử lý yêu cầu phức tạp |
| `app/agents/memory/` | Long-term & short-term memory |

---

## Pipeline Agent — Luồng sinh đề 5 bước

<p align="center">
  <img src="figures/dataflow.svg" alt="Data Flow" />
</p>

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Retrieval  │───►│   Outline   │───►│   HITL 1    │───►│   Builder   │───►│  Validator  │
│   Agent     │    │   Agent     │    │   (Pause)   │    │   Agent     │    │   Agent     │
│  (Agent 1)  │    │  (Agent 2)  │    │  ⏸  Pause   │    │  (Agent 3)  │    │  (Agent 4)  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
      │                  │                  │                  │                  │
      ▼                  ▼                  ▼                  ▼                  ▼
 Chunking tài liệu   Tạo blueprint     Giảng viên phê     Sinh MCQ + Essay   Kiểm tra:
   PDF → Vector     (sườn đề theo      duyệt sườn đề     với source evidence   - Scope
   store (Pinecone)  Bloom levels)       trước khi AI      cho mỗi câu       - Bloom
                        │              sinh câu hỏi          │               - Logic
                   HITL 0: Xác                             ▼              - Duplicate
                   nhận yêu cầu                          HITL 2: Full     - LaTeX
                                              ◄────────  Review
                                              │
                                              ▼
                                         HITL 3: Export Preview
```

### Chi tiết từng Agent

#### Agent 1 — Retrieval Agent
- Truy xuất chunks kiến thức từ **Pinecone vector store** dựa trên scope (chương)
- Mỗi chunk có metadata: `chapter`, `page_number`, `section_id`, `relevance_score`
- Hỗ trợ lọc theo target Bloom level
- Output: danh sách `retrieved_chunks` → truyền sang Agent 2

#### Agent 2 — Outline Agent
- Nhận `retrieved_chunks` + `exam_config`
- Xây dựng **blueprint** (sườn đề): mảng các slot, mỗi slot có:
  - `question_id`, `bloom_level`, `chapter`, `topic_hint`, `content_type`
- Phân bổ số lượng câu hỏi theo `bloom_distribution` cấu hình
- **Output**: Blueprint → chờ giảng viên phê duyệt (HITL Checkpoint 1)

#### Agent 3 — Builder Agent
- Sinh câu hỏi thực tế từ từng slot trong blueprint
- **MCQ**: 4 lựa chọn, 1 đúng, 3 mồi nhử có logic
- **Essay**: có rubric chấm điểm (4 mức điểm)
- Mỗi câu đi qua pipeline skills:
  - `BloomClassifierSkill` — xác nhận mức Bloom
  - `DedupCheckerSkill` — tránh trùng lặp chủ đề
  - `DifficultyEstimatorSkill` — ước lượng độ khó
  - `LatexRendererSkill` — render công thức LaTeX
- **van_dung_cao**: tự động web search bài toán tương tự → adapt vào scope
- **Guardrails**: kiểm soát token budget, scope restriction
- **Output**: mảng `questions` có `source_evidence` cho từng câu

#### Agent 4 — Validator Agent
- Kiểm tra từng câu hỏi theo nhiều chiều:
  - **Scope Guard**: câu hỏi chỉ dùng kiến thức trong phạm vi cho phép
  - **Bloom alignment**: mức Bloom thực tế vs mức khai báo
  - **Logic**: đáp án đúng có thực sự đúng?
  - **Duplicate**: trùng lặp nội dung với câu khác
  - **LaTeX**: cú pháp công thức
- Nếu có lỗi → tự động retry (max 3 lần), chỉ sinh lại câu bị lỗi
- **Output**: danh sách `issues` + `status`

#### Planner Agent (Agent phụ)
- Xử lý yêu cầu **phức tạp**: prompt > 200 ký tự, có từ khóa đặc biệt
- Phân tích → tạo execution plan → gợi ý cấu hình Bloom

---

## Human-in-the-Loop (HITL)

```
HITL Checkpoint 0 ── Xác nhận yêu cầu (rewritten requirements)
         │
         ▼
HITL Checkpoint 1 ── ⏸ PHÊ DUYỆT BLUEPRINT ── Giảng viên duyệt sườn đề
         │                                         │
         │  [Reject] ── Gửi phản hồi ──► Outline tái sinh ──► Checkpoint 1
         │  [Approve] ──► Tiếp tục sinh câu hỏi
         ▼
HITL Checkpoint 2 ── ⏸ FULL REVIEW ── Xem toàn bộ đề, gửi phản hồi/sửa trực tiếp
         │
         │  [Reject] ── Gửi feedback ──► Builder tái sinh câu bị lỗi
         │  [Approve] ──► Publish đề
         ▼
HITL Checkpoint 3 ── Export Preview ── Xem trước, chọn định dạng (PDF/DOCX)
```

### 3 Điểm dừng HITL

| Checkpoint | Giai đoạn | Hành động giảng viên |
|---|---|---|
| **HITL 0** | Sau khi làm rõ yêu cầu | Xác nhận requirements đã được diễn giải đúng |
| **HITL 1** ⏸ | Sau Outline Agent | **Duyệt/Từ chối blueprint** — đây là checkpoint quan trọng nhất |
| **HITL 2** ⏸ | Sau Validator Agent | Duyệt toàn bộ đề, chỉnh sửa trực tiếp từng câu hoặc gửi phản hồi |

> ⏸ = Pipeline **dừng lại** tại đây, chờ giảng viên hành động qua WebSocket/REST API

---

## Tính năng nổi bật

### Multi-Agent Pipeline
- **5 agent chuyên biệt**, mỗi agent có system prompt riêng
- Memory分层: **Short-term** (Redis) + **Long-term** (PostgreSQL)
- Planner Agent tự động nhận diện yêu cầu phức tạp
- Retry tự động max 3 lần — chỉ tái sinh câu bị lỗi

### Real-time WebSocket
- Giảng viên thấy **từng câu hỏi được sinh** theo thời gian thực
- Trạng thái pipeline: Retrieval → Outline → Waiting → Building → Validating → Done
- Tự động reconnect nếu mất kết nối (max 5 lần, exponential backoff)

### Kiểm soát chất lượng
- **Bloom Taxonomy** 4 mức: nhận biết, thông hiểu, vận dụng, vận dụng cao
- **Source Evidence**: mỗi câu hỏi gắn nguồn trích dẫn từ tài liệu gốc
- **Quality Score** tổng hợp: pass rate, evidence coverage, warning count
- Guardrails: kiểm soát token budget, scope restriction

### Quản lý tài liệu thông minh
- Upload PDF → tự động chunking, embedding → Pinecone
- Hiển thị **curriculum tree** (cây chương trình) từ heading
- Giảng viên có thể chỉnh sửa cây chương trình
- Re-process nếu cần

### Xuất đề đa dạng
- **PDF**: đề + đáp án, có thể tách riêng
- **DOCX**: import trực tiếp vào Word
- Mỗi đề có thể tạo **nhiều biến thể** (variant)
- Full edit history với khả năng **restore** về phiên bản trước

---

## Bắt đầu

### Yêu cầu

- Python 3.11+
- Node.js 20+
- PostgreSQL 15+
- Redis 7+
- Pinecone account (vector store)

### Backend

```bash
cd backend

# Tạo virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Cài đặt dependencies
pip install -r requirements.txt

# Cấu hình biến môi trường
cp .env.example .env
# Chỉnh sửa .env với API keys (OpenAI, Pinecone, PostgreSQL)

# Chạy migration
alembic upgrade head

# Khởi động server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd Frontend

# Cài đặt dependencies
npm install

# Cấu hình biến môi trường
cp .env.example .env.local

# Khởi động dev server
npm run dev
```

### Celery Worker (cho async tasks)

```bash
cd backend
celery -A app.tasks.celery_app worker --loglevel=info
```

### Biến môi trường quan trọng

| Variable | Mô tả |
|---|---|
| `OPENAI_API_KEY` | API key cho LLM (GPT-4o) |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `PINECONE_API_KEY` | Pinecone API key |
| `JWT_SECRET_KEY` | Secret cho JWT tokens |
| `NEXT_PUBLIC_API_URL` | Backend URL (frontend) |

---

## Cấu trúc thư mục

```
ExamAI/
├── Frontend/                      # Next.js 16 frontend
│   ├── app/
│   │   ├── dashboard/             # Dashboard routes
│   │   │   ├── generate/          # Sinh đề mới
│   │   │   ├── exams/[id]/        # Chi tiết đề
│   │   │   ├── documents/         # Quản lý tài liệu
│   │   │   ├── history/           # Lịch sử
│   │   │   └── settings/          # Cài đặt
│   │   ├── auth/                  # Trang đăng nhập
│   │   └── page.tsx              # Landing page
│   ├── components/               # React components
│   │   ├── generation-live-viewer.tsx  # Realtime streaming UI
│   │   ├── generation-stepper.tsx      # Pipeline stepper
│   │   └── ui/                   # shadcn/ui components
│   └── lib/
│       └── api.ts               # API client + WebSocket
│
├── backend/                       # FastAPI backend
│   ├── app/
│   │   ├── agents/               # 5 AI agents
│   │   │   ├── orchestrator.py   # Agent 0: điều phối
│   │   │   ├── retrieval.py       # Agent 1: truy xuất
│   │   │   ├── outline.py         # Agent 2: tạo blueprint
│   │   │   ├── builder.py        # Agent 3: sinh câu hỏi
│   │   │   ├── validator.py      # Agent 4: kiểm tra
│   │   │   ├── planner.py        # Planner agent
│   │   │   ├── base.py           # Base class
│   │   │   ├── llm.py            # LLM client wrapper
│   │   │   ├── memory/           # Memory management
│   │   │   ├── guardrails.py     # Guardrails pipeline
│   │   │   └── skills/           # Agent skills
│   │   ├── routers/             # API routes
│   │   │   ├── auth.py
│   │   │   ├── documents.py
│   │   │   ├── exams.py
│   │   │   └── generate.py
│   │   ├── core/                # Core utilities
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   └── redis_client.py
│   │   ├── models/              # Pydantic + SQLAlchemy models
│   │   ├── services/            # Business logic
│   │   └── tasks/               # Celery tasks
│   ├── alembic/                 # DB migrations
│   ├── requirements.txt
│   └── .env.example
│
├── figures/                       # Diagram files
│   ├── logo.svg
│   ├── architecture.svg
│   ├── agent_pipeline.svg
│   └── dataflow.svg
│
└── README.md
```

---

## Công nghệ sử dụng

### Frontend
| Công nghệ | Mục đích |
|---|---|
| Next.js 16 | React framework |
| TypeScript | Type safety |
| Tailwind CSS | Styling |
| shadcn/ui | Component library |
| Zustand | State management |
| WebSocket | Real-time updates |

### Backend
| Công nghệ | Mục đích |
|---|---|
| FastAPI | REST API framework |
| Pydantic v2 | Data validation |
| SQLAlchemy | ORM |
| Alembic | Database migrations |
| Celery | Async task queue |
| Redis | Pub/sub, short-term memory |
| PostgreSQL | Primary database |
| Pinecone | Vector database |

### AI / LLM
| Công nghệ | Mục đích |
|---|---|
| OpenAI GPT-4o | LLM cho tất cả agents |
| Bloom Taxonomy | Cognitive level classification |
| OpenAI Embeddings | Document chunk embedding |

---

## License

MIT License — dự án phục vụ mục đích nghiên cứu và giáo dục.
