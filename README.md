# ExamAI Backend

Hệ thống Multi-Agent AI tự động sinh đề thi từ giáo trình, sử dụng **LangGraph**, **FastAPI**, **Pinecone**, và **PostgreSQL**.

---

## Tổng quan kiến trúc

```
┌────────────────────────────────────────────────────────────────────┐
│                          FastAPI Application                       │
│                      http://localhost:8000/api/v1                  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Routers                                                           │
│  ┌──────────┐  ┌──────────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  /auth   │  │ /textbooks   │  │  /exams  │  │  /generate    │  │
│  └────┬─────┘  └──────┬───────┘  └────┬─────┘  └──────┬────────┘  │
│       │               │               │               │            │
│  Services                                                          │
│  ┌────┴───────────────┴───────────────┴───────────────┴─────────┐  │
│  │  TextbookService      ExamService          RAGService         │  │
│  └───────────────────────────┬───────────────────────────────────┘  │
│                              │                                     │
│  LangGraph Multi-Agent Pipeline                                    │
│  ┌───────────────────────────┴───────────────────────────────────┐  │
│  │                                                               │  │
│  │  [Blueprint] → [Retrieval] → [QuestionGenerator]             │  │
│  │                                      │                       │  │
│  │                              [Validator] ──► pass?           │  │
│  │                                  │ No                        │  │
│  │                            [mark_retry] → [QuestionGenerator]│  │
│  │                                  │ Yes                       │  │
│  │                             [Finalize]                       │  │
│  │                                                               │  │
│  │  Partial Edit: [Reviewer] → [Validator] → [Finalize]         │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  Storage                                                           │
│  ┌───────────────┐   ┌─────────────────┐   ┌──────────────────┐   │
│  │  PostgreSQL   │   │    Pinecone      │   │  File Storage    │   │
│  │  (data+BM25)  │   │  (vector search) │   │  data/uploads/   │   │
│  └───────────────┘   └─────────────────┘   └──────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
```

---

## Agent Pipeline chi tiết

### 1. Luồng sinh đề đầy đủ (Full Generation)

```
POST /api/v1/generate/exam/stream
          │
          ▼
  ┌───────────────┐
  │  ExamService  │  ← khởi tạo LLM, agents, initial AgentState
  └───────┬───────┘
          │  invoke LangGraph graph
          ▼
  ┌───────────────────────────────────────────────────────────┐
  │                   LangGraph State Graph                   │
  │                                                           │
  │  Step 1: parse_textbook_node                              │
  │    - Xác nhận sách giáo trình đã được xử lý              │
  │    - Load textbook metadata từ PostgreSQL                  │
  │    - progress: 20%                                        │
  │                     │                                     │
  │  Step 2: create_blueprint_node  ← BlueprintAgent          │
  │    - Gọi LLM để lập kế hoạch đề thi                      │
  │    - Phân bổ câu hỏi theo chương, Bloom level, độ khó    │
  │    - Output: ExamBlueprint (danh sách QuestionSlot)       │
  │    - progress: 40%                                        │
  │                     │                                     │
  │  Step 3: retrieve_context_node  ← RetrievalAgent          │
  │    - Với mỗi QuestionSlot: tìm kiếm hybrid               │
  │      · Vector search (Pinecone, cosine similarity)        │
  │      · BM25 keyword search (PostgreSQL textbook_chunks)   │
  │      · Reciprocal Rank Fusion → top 5 chunks/slot        │
  │    - Output: list[RetrievedContext]                       │
  │    - progress: 60%                                        │
  │                     │                                     │
  │  Step 4: generate_questions_node  ← QuestionGeneratorAgent│
  │    - Với mỗi slot + context: gọi LLM               │
  │    - Hỗ trợ MCQ (4 lựa chọn) và Essay                    │
  │    - Có guidance cho applied questions, strict grounding  │
  │    - Output: list[GeneratedQuestion]                      │
  │    - progress: 80%                                        │
  │                     │                                     │
  │  Step 5: validate_questions_node  ← ValidatorAgent        │
  │    - LLM-as-judge: kiểm tra mỗi câu hỏi                  │
  │      · grounding_score: có bám sát nguồn không?           │
  │      · accuracy_score: đáp án đúng không?                 │
  │      · difficulty_alignment: độ khó có khớp không?       │
  │      · hallucination_flags: liệt kê claim bị bịa         │
  │    - Ngưỡng pass: overall_quality ≥ 0.7                   │
  │    - progress: 90%                                        │
  │                     │                                     │
  │  Routing: should_retry_or_finalize                        │
  │    - pass_rate < 60% AND _retry_attempted == False?       │
  │      → mark_retry_node → generate_questions_node (once)   │
  │    - pass_rate ≥ 60% OR đã retry rồi?                    │
  │      → finalize_node                                      │
  │                     │                                     │
  │  Step 6: finalize_node                                    │
  │    - Lưu Exam + ExamQuestion vào PostgreSQL               │
  │    - Tính quality_score tổng thể                          │
  │    - Trả về ExamResponse                                  │
  │    - progress: 100%                                       │
  └───────────────────────────────────────────────────────────┘
```

### 2. Luồng chỉnh sửa một phần (Partial Edit)

```
POST /api/v1/generate/exam/{id}/regenerate
          │
          ▼
  ReviewerAgent
    - Nhận edit_requests: [{question_ids, range_start, range_end, edit_prompt}]
    - Xác định các câu cần tái sinh (theo ID hoặc range)
    - Giữ nguyên các câu không cần sửa
    - Gọi lại QuestionGeneratorAgent chỉ cho các slot cần thiết
          │
          ▼
  ValidatorAgent → finalize_node
```

---

## Agents

### BlueprintAgent (`agents/blueprint.py`)

**Nhiệm vụ**: Lập kế hoạch cấu trúc đề thi trước khi sinh câu hỏi.

- Input: `prompt`, `exam_type` (mcq/essay/mixed), `difficulty`, `chapters`, `question_distribution`, `gradually_increasing`, `constraints`, `textbook_metadata`
- Gọi LLM với `BLUEPRINT_SYSTEM_PROMPT` → trả về JSON blueprint
- Phân bổ câu hỏi theo Bloom's Taxonomy:

  | Bloom Level | Difficulty Score |
  |--|--|
  | remember | 0.1 |
  | understand | 0.25 |
  | apply | 0.5 |
  | analyze | 0.65 |
  | evaluate | 0.8 |
  | create | 0.95 |

- Nếu `gradually_increasing=True`: sắp xếp slot từ dễ đến khó
- Fallback khi LLM fail: tạo 5 MCQ slot mặc định
- Output: `ExamBlueprint` với list `QuestionSlot`

### RetrievalAgent (`agents/retrieval.py`)

**Nhiệm vụ**: Tìm kiếm context liên quan từ sách giáo trình cho từng slot câu hỏi.

- **Hybrid Search** cho mỗi `QuestionSlot`:
  1. **Vector Search** (Pinecone): `similarity_search_with_score(query, k=10)` — tìm theo semantic similarity
  2. **BM25 Keyword Search** (PostgreSQL `textbook_chunks`): xây `BM25Okapi` từ toàn bộ chunks của textbook, score từng chunk
  3. **Reciprocal Rank Fusion (RRF)**: kết hợp 2 kết quả bằng công thức `1/(rank+60)`, lấy top 5

- Query được build từ: `bloom_level + topics + chapter`
- Output: `RetrievedContext` với `combined_text` (nối các chunk bằng `---`)

### QuestionGeneratorAgent (`agents/question_generator.py`)

**Nhiệm vụ**: Sinh câu hỏi dựa trên blueprint slot và context đã lấy.

- Hỗ trợ 2 loại câu hỏi:
  - **MCQ**: 4 lựa chọn A/B/C/D, 1 đáp án đúng, có giải thích
  - **Essay**: câu hỏi tự luận, model answer, grading criteria
- Với `difficulty ≥ 0.6` và `allow_applied_questions=True`: thêm `APPLIED_QUESTION_PROMPT` — yêu cầu tạo tình huống thực tế
- Với `strict_grounding=True`: reminder bắt buộc bám sát context
- Robust JSON parsing: regex `\`\`\`json...\`\`\`` → regex `{...}` → `json.loads()`
- Output: `GeneratedQuestion` với `source_chunks[]` và `source_texts[]` để trích dẫn

### ValidatorAgent (`agents/validator.py`)

**Nhiệm vụ**: Anti-hallucination check — LLM đánh giá chất lượng câu hỏi.

- Cho mỗi câu hỏi: gửi question + source_texts cho LLM để đánh giá
- Output JSON từ LLM:
  ```json
  {
    "is_valid": true,
    "grounding_score": 0.0–1.0,
    "accuracy_score": 0.0–1.0,
    "difficulty_alignment": 0.0–1.0,
    "hallucination_flags": ["list các claim bịa đặt"],
    "issues": ["danh sách vấn đề"],
    "suggestions": ["đề xuất cải thiện"],
    "overall_quality": 0.0–1.0
  }
  ```
- `QUALITY_THRESHOLD = 0.7` — câu nào dưới ngưỡng này bị flag `is_validated=False`
- Summary: `{total, passed, failed, pass_rate, hallucination_flags}`

### ReviewerAgent (`agents/reviewer.py`)

**Nhiệm vụ**: Tái sinh một phần đề thi theo yêu cầu chỉnh sửa.

- Nhận `edit_requests` dạng:
  ```json
  [{"question_ids": ["3","5"], "range_start": null, "range_end": null, "edit_prompt": "Make it harder"}]
  ```
- Chỉ regenerate đúng các slot được chỉ định (theo ID hoặc range)
- Giữ nguyên các câu không trong danh sách edit
- Gọi lại `QuestionGeneratorAgent` + `RetrievalAgent` cho các slot cần thiết

### DocumentProcessorAgent (`agents/document_processor.py`)

**Nhiệm vụ**: Xử lý tài liệu tải lên, tạo embeddings và lưu vào storage.

- Hỗ trợ: **PDF** (pypdf), **DOCX** (python-docx), **PPTX** (python-pptx)
- Chunking: `CHUNK_SIZE=1000` ký tự, `CHUNK_OVERLAP=200`
- Mỗi chunk được gắn metadata: `textbook_id`, `chapter`, `page`, `chunk_index`
- Lưu embeddings vào **Pinecone** (cloud vector DB)
- Lưu raw text vào **PostgreSQL** `textbook_chunks` (cho BM25)

---

## AgentState (Shared State)

Toàn bộ pipeline chia sẻ một `AgentState` (TypedDict) chạy qua LangGraph:

```python
class AgentState(TypedDict):
    # Input từ user
    user_id: str
    textbook_id: str
    chapters: list[int]
    prompt: str
    exam_type: str          # mcq | essay | mixed
    difficulty: str         # basic | advanced | application | high_application | custom
    question_distribution: dict  # {mcq: {easy: N, medium: N, hard: N}, essay: {...}}
    num_variants: int
    gradually_increasing: bool
    constraints: dict       # {strict_grounding, allow_applied_questions, bloom_levels, ...}

    # Outputs tích lũy qua từng step
    textbook_metadata: dict
    processing_status: str
    blueprint: ExamBlueprint
    retrieved_contexts: list[RetrievedContext]
    generated_questions: list[GeneratedQuestion]
    validated_questions: list[GeneratedQuestion]
    validation_summary: dict

    # Tracking
    current_step: str
    step_progress: float    # 0.0 → 1.0
    error: Optional[str]

    # Partial edit
    edit_requests: Optional[list[dict]]
    is_partial_edit: bool

    # Agent instances (inject tại entry, không lưu DB)
    _retrieval_agent: Optional[Any]
    _blueprint_agent: Optional[Any]
    _question_generator: Optional[Any]
    _validator: Optional[Any]
    _reviewer: Optional[Any]
    _retry_attempted: Optional[bool]
```

---

## Storage Layer

### PostgreSQL (SQLAlchemy async)

| Bảng | Mô tả |
|--|--|
| `users` | Tài khoản người dùng, hashed password (bcrypt) |
| `textbooks` | Metadata sách giáo trình (title, file_path, status, total_chunks) |
| `textbook_chapters` | Cấu trúc chương (chapter_number, start_page, end_page, key_concepts) |
| `textbook_chunks` | Raw text của từng chunk — dùng cho BM25 search |
| `exams` | Đề thi đã tạo (config, quality_score, status) |
| `exam_questions` | Từng câu hỏi (content, options, correct_answer, bloom_level, source_chunks) |

**Exam status lifecycle**: `generating` → `generated` → `reviewed` → `published`

### Pinecone (Vector DB)

- Index: `examai-minilm`, dimension **384**, metric **cosine**, serverless (AWS us-east-1)
- Mỗi vector = 1 text chunk, metadata: `{textbook_id, chapter, page, chunk_index}`
- Namespace: theo `textbook_id` để isolate dữ liệu

### Embedding Model

**`sentence-transformers/all-MiniLM-L6-v2`** (HuggingFace, local):
- Dimension: 384
- Normalized embeddings (`normalize_embeddings=True`)
- Không cần API key, chạy hoàn toàn offline

---

## LLM Support

Cấu hình qua `LLM_PROVIDER` trong `.env`:

| Provider | Biến | Model mặc định | Ghi chú |
|--|--|--|--|
| `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` | Free tier, 6000 req/ngày |
| `google` | `GOOGLE_API_KEY` | `gemini-2.0-flash` | Free tier |
| `openai` | `OPENAI_API_KEY` | `gpt-4o` | Trả phí |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-20250514` | Trả phí |
| `together` | `TOGETHER_API_KEY` | `deepcogito/cogito-v1-preview-qwen-32B` | Free tier |
| `g4f` | *(không cần)* | `gpt-4o` | Free, không ổn định |

---

## API Endpoints

### Auth — `/api/v1/auth`
| Method | Path | Mô tả |
|--|--|--|
| `POST` | `/register` | Đăng ký tài khoản mới |
| `POST` | `/login` | Đăng nhập, trả về JWT |
| `GET` | `/me` | Thông tin user hiện tại |

### Textbooks — `/api/v1/textbooks`
| Method | Path | Mô tả |
|--|--|--|
| `GET` | `/` | Danh sách textbooks của user |
| `POST` | `/` | Upload textbook (PDF/DOCX/PPTX) |
| `GET` | `/{id}` | Chi tiết textbook + chapters |
| `DELETE` | `/{id}` | Xóa textbook và vectors |

### Generation — `/api/v1/generate`
| Method | Path | Mô tả |
|--|--|--|
| `POST` | `/exam` | Sinh đề thi (synchronous) |
| `POST` | `/exam/stream` | Sinh đề thi với SSE progress stream |
| `POST` | `/exam/{id}/regenerate` | Tái sinh một phần đề đã tạo |

### Exams — `/api/v1/exams`
| Method | Path | Mô tả |
|--|--|--|
| `GET` | `/` | Danh sách đề thi của user |
| `GET` | `/{id}` | Chi tiết đề thi + câu hỏi |
| `DELETE` | `/{id}` | Xóa đề thi |

---

## Cài đặt & Chạy

### Yêu cầu
- Python 3.11+
- PostgreSQL 15+ (hoặc Docker)
- Pinecone account (free tier: https://pinecone.io)
- Groq API key (free: https://console.groq.com)

### Cài đặt

```bash
cd backend
pip install -r requirements.txt
```

### Cấu hình `.env`

```ini
# App
APP_ENV=development
SECRET_KEY=your-secret-key

# Database
DATABASE_URL=postgresql+asyncpg://examai:examai@localhost:5432/examai

# LLM (chọn 1 provider)
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
GROQ_MODEL=llama-3.3-70b-versatile

# Embedding (local, không cần API key)
EMBEDDING_PROVIDER=huggingface
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# Pinecone
PINECONE_API_KEY=pcsk_xxxxxxxxxxxxxxxxxxxx
PINECONE_INDEX_NAME=examai-minilm
```

### Khởi động PostgreSQL (Docker)

```bash
docker-compose up -d
```

### Chạy server

```bash
uvicorn main:app --reload --port 8000
```

### API Docs

Truy cập http://localhost:8000/docs để xem Swagger UI tương tác.

---

## Cấu trúc dự án

```
backend/
├── main.py                      # FastAPI app, startup/shutdown
├── config.py                    # Settings từ .env (pydantic-settings)
├── database.py                  # SQLAlchemy async engine + session
│
├── models/                      # ORM models (SQLAlchemy)
│   ├── user.py                  # User
│   ├── textbook.py              # Textbook, TextbookChapter, TextbookChunk
│   └── exam.py                  # Exam, ExamQuestion (+ Enums)
│
├── schemas/                     # Pydantic request/response schemas
│   ├── auth.py
│   ├── textbook.py
│   └── exam.py                  # ExamGenerationRequest, ExamResponse, ...
│
├── agents/                      # LangGraph multi-agent system
│   ├── state.py                 # AgentState TypedDict, dataclasses
│   ├── orchestrator.py          # LangGraph StateGraph + routing logic
│   ├── document_processor.py    # Parse PDF/DOCX/PPTX, chunk, embed, store
│   ├── retrieval.py             # Hybrid search: Pinecone + BM25 + RRF
│   ├── blueprint.py             # Exam structure planner (LLM)
│   ├── question_generator.py    # MCQ/Essay generator (LLM)
│   ├── validator.py             # Anti-hallucination validator (LLM-as-judge)
│   ├── reviewer.py              # Partial regeneration handler
│   └── llm_g4f.py               # LangChain wrapper cho g4f (GPT4Free)
│
├── services/                    # Business logic
│   ├── rag_service.py           # Pinecone index + embedding manager (singleton)
│   ├── textbook_service.py      # Textbook CRUD + trigger document processing
│   └── exam_service.py          # Exam generation + CRUD + LLM factory
│
├── routers/                     # FastAPI route handlers
│   ├── auth.py                  # JWT auth
│   ├── textbooks.py             # Textbook upload/management
│   ├── exams.py                 # Exam CRUD
│   └── generation.py            # Generation endpoints (SSE stream)
│
├── utils/                       # Shared utilities
├── alembic/                     # Database migrations
├── data/uploads/                # Uploaded textbook files
├── docker-compose.yml           # PostgreSQL container
├── requirements.txt
└── .env                         # Environment variables (không commit)
```

---

## Chiến lược Anti-Hallucination

1. **Strict Grounding**: Câu hỏi chỉ được dùng thông tin có trong context đã retrieve — bắt buộc qua system prompt
2. **Citation Tracking**: Mỗi `GeneratedQuestion` lưu `source_chunks[]` (IDs) và `source_texts[]` (raw text)
3. **Validator Agent (LLM-as-judge)**: Agent thứ 4 độc lập kiểm tra từng câu theo 4 tiêu chí
4. **Chapter Filtering**: Retrieval chỉ lấy chunks từ các chương được chọn
5. **Retry Loop**: Nếu pass rate < 60%, tự động regenerate một lần (tránh vòng lặp vô hạn bằng `_retry_attempted`)
6. **Robust JSON Parsing**: Tất cả agents parse LLM output qua regex fallback, không crash khi LLM trả định dạng sai


## API Endpoints

### Auth
- `POST /api/v1/auth/login` — Login
- `POST /api/v1/auth/register` — Register
- `GET  /api/v1/auth/me` — Current user

### Textbooks
- `POST /api/v1/textbooks/upload` — Upload textbook (multipart)
- `GET  /api/v1/textbooks/` — List textbooks
- `GET  /api/v1/textbooks/{id}` — Get textbook details
- `DELETE /api/v1/textbooks/{id}` — Delete textbook

### Exams
- `GET  /api/v1/exams/` — List exams
- `GET  /api/v1/exams/{id}` — Get exam with questions
- `DELETE /api/v1/exams/{id}` — Delete exam

### Generation
- `POST /api/v1/generate/exam` — Generate exam (synchronous)
- `POST /api/v1/generate/exam/stream` — Generate with SSE progress
- `POST /api/v1/generate/partial-regenerate` — Edit specific questions

## Bloom's Taxonomy Mapping

| Level | Difficulty | Question Style |
|-------|-----------|---------------|
| Remember | 0.1 | Recall facts, definitions |
| Understand | 0.25 | Explain, summarize |
| Apply | 0.5 | Use in new situations |
| Analyze | 0.65 | Compare, pattern recognition |
| Evaluate | 0.8 | Judge, critique |
| Create | 0.95 | Design, construct |
