# Repository Specification

Tài liệu này mô tả repository dựa trên những gì hiện diện trong source code, config, scripts, migrations, tài liệu và cấu trúc thư mục tại thời điểm quét repository.

- Phạm vi quét: toàn bộ thư mục gốc, `backend/`, `UI/`, `docs/`, `Data sách/`, scripts/tests ở root, cấu hình Docker/Alembic/env.
- Ưu tiên nguồn sự thật: code runtime và config đang được import/thực thi. Tài liệu mô tả cũ chỉ được dùng như ngữ cảnh lịch sử.
- Quy ước:
  - `Xác nhận`: nhận định suy ra trực tiếp từ code/config/tài liệu hiện có.
  - `Suy luận`: suy ra từ nhiều file nhưng repo không có một chỗ khẳng định thẳng.
  - `Chưa xác minh`: repo có surface/interface/tài liệu nhưng implementation thực tế còn thiếu, stub, hoặc không thể xác nhận chỉ bằng đọc code.

## 1. Tổng quan hệ thống

### 1.1. Mục tiêu của repo

`Xác nhận`: repository đang xây một hệ thống sinh đề kiểm tra từ tài liệu giảng dạy, theo hướng document-first, với backend FastAPI + frontend Next.js + pipeline RAG + orchestration nhiều agent nội bộ. Dấu vết chính nằm ở `README.md`, `backend/app/main.py`, `backend/app/routers/generate.py`, `backend/app/routers/exams.py`, `backend/app/services/document_service.py`, `backend/app/agents/orchestrator.py`, `UI/lib/api.ts`, `UI/app/dashboard/generate/page.tsx`.

`Xác nhận`: scope runtime hiện tại bị giới hạn khá mạnh:

- Vật lý là môn mặc định được UI và README nhấn mạnh: `README.md`, `UI/app/dashboard/settings/page.tsx`, `UI/app/dashboard/generate/page.tsx`.
- Tiếng Việt là ngôn ngữ mặc định: `README.md`, `backend/app/schemas/exam.py`, `UI/app/dashboard/generate/page.tsx`.
- Strict grounding được bật mặc định: `README.md`, `backend/app/schemas/exam.py`, `UI/app/dashboard/generate/page.tsx`.
- UI thực tế chỉ mở upload PDF, dù backend parser hỗ trợ thêm DOCX/PPTX: `UI/app/dashboard/documents/page.tsx`, `backend/app/routers/documents.py`, `backend/app/rag/parser.py`.
- UI generation flow tập trung vào single-answer MCQ: `README.md`, `UI/app/dashboard/generate/page.tsx`, `UI/app/dashboard/exams/[id]/page.tsx`.

### 1.2. Bài toán repo đang giải quyết

`Xác nhận`: repo giải quyết ít nhất 4 bài toán chính:

1. Chuẩn hóa và ingest tài liệu giảng dạy vào một representation có thể chọn phạm vi theo chương/mục: `backend/app/rag/parser.py`, `backend/app/rag/structure.py`, `backend/app/routers/documents.py`.
2. Sinh đề kiểm tra có cấu hình Bloom distribution, số câu, scope và prompt giáo viên: `backend/app/schemas/exam.py`, `backend/app/routers/generate.py`, `backend/app/agents/orchestrator.py`.
3. Cho phép giáo viên review/chỉnh sửa/publish đề sau khi sinh: `backend/app/routers/exams.py`, `backend/app/services/exam_service.py`, `UI/app/dashboard/exams/[id]/page.tsx`.
4. Chuẩn bị nền tảng cho “ACE foundation” như feedback store, playbook, reflection candidate, warmup data, nhưng phần lớn mới dừng ở UI/spec/stub: `docs/ace_foundation.md`, `docs/feedback_store.md`, `docs/playbook_model.md`, `backend/app/routers/playbook.py`, `UI/app/dashboard/playbook/page.tsx`, `UI/app/dashboard/feedback/page.tsx`.

### 1.3. Các use case chính

`Xác nhận`:

1. Đăng ký/đăng nhập giáo viên và quản lý phiên đăng nhập bằng JWT + refresh token: `backend/app/routers/auth.py`, `backend/app/services/auth_service.py`, `UI/components/auth-provider.tsx`.
2. Upload tài liệu, chờ parse/heading detection/chunking/indexing, rồi chọn scope từ curriculum tree: `backend/app/routers/documents.py`, `backend/app/services/document_service.py`, `UI/app/dashboard/documents/page.tsx`, `UI/app/dashboard/generate/page.tsx`.
3. Sinh đề từ tài liệu và theo dõi tiến trình qua WebSocket: `backend/app/routers/generate.py`, `backend/app/main.py`, `backend/app/websocket/manager.py`, `UI/lib/api.ts`.
4. Chỉnh sửa từng câu, regenerate một phần hoặc toàn bộ, publish đề, export PDF/DOCX ở API: `backend/app/routers/exams.py`, `backend/app/services/exam_service.py`, `backend/app/utils/export.py`, `UI/app/dashboard/exams/[id]/page.tsx`.
5. Xem dashboard quality/history/feedback/playbook/settings: `UI/app/dashboard/page.tsx`, `UI/app/dashboard/history/page.tsx`, `UI/app/dashboard/feedback/page.tsx`, `UI/app/dashboard/playbook/page.tsx`, `UI/app/dashboard/settings/page.tsx`.

### 1.4. Luồng hoạt động end-to-end

`Xác nhận`: luồng end-to-end chính đang được code hóa như sau:

1. Giáo viên đăng nhập qua `POST /api/v1/auth/login`: `backend/app/routers/auth.py`, `backend/app/services/auth_service.py`.
2. Frontend lưu access token và refresh token vào `localStorage`, tự refresh khi gặp 401: `UI/lib/api.ts`, `UI/components/auth-provider.tsx`.
3. Giáo viên upload tài liệu qua `POST /api/v1/documents/upload`: `backend/app/routers/documents.py`.
4. Backend lưu file vào object storage (MinIO hoặc S3), tạo bản ghi `documents`, rồi chạy parse/chunk/index ở background: `backend/app/services/document_service.py`, `backend/app/utils/storage/*`, `backend/app/rag/*`.
5. Frontend lấy curriculum tree qua `GET /api/v1/documents/{id}/curriculum-tree`, cho phép chọn scope: `backend/app/routers/documents.py`, `UI/app/dashboard/generate/page.tsx`.
6. Frontend gọi `POST /api/v1/generate/exam` để sinh đề theo payload FE-compatible: `UI/lib/api.ts`, `backend/app/routers/generate.py`.
7. Backend tạo `exams` row, chạy orchestrator inline, đồng thời emit progress/question/HITL/completed events vào WebSocket channel `ws/exam/{exam_id}` và Redis: `backend/app/routers/generate.py`, `backend/app/agents/orchestrator.py`, `backend/app/websocket/manager.py`.
8. Review screen tải exam detail, hiển thị questions, source evidence, warning, version/history synthetic và cho phép edit/regenerate/publish: `backend/app/routers/exams.py`, `UI/app/dashboard/exams/[id]/page.tsx`.
9. Khi publish, backend đổi trạng thái exam và cập nhật long-term memory (`teacher_preferences`): `backend/app/services/exam_service.py`, `backend/app/agents/memory/long_term.py`.
10. API hỗ trợ preview/export PDF hoặc DOCX; UI hiện chủ yếu dừng ở review và publish: `backend/app/routers/exams.py`, `backend/app/utils/export.py`.

`Suy luận`: kiến trúc đang ở trạng thái chuyển tiếp từ “Curriculum AI Agent” sang “ACE foundation”. Dấu hiệu:

- Tài liệu gốc ở root nói về multi-agent curriculum AI: `spec_curriculum_ai_agent.md`, `tutorial.md`.
- README và docs mới nhấn mạnh “Phase 4 foundation”, “strict-scope Physics-only”: `README.md`, `docs/ace_foundation.md`.
- UI phản chiếu mạnh các khái niệm feedback/playbook/warmup dù backend chưa có persistence tương ứng: `UI/app/dashboard/*`, `backend/app/routers/playbook.py`, `backend/app/services/exam_service.py`.

## 2. Cấu trúc repository

### 2.1. Cây thư mục quan trọng

```text
.
├─ README.md
├─ run_guide.md
├─ tutorial.md
├─ spec_curriculum_ai_agent.md
├─ test_generate.py
├─ test_generate2.py
├─ test_generate3.py
├─ backend/
│  ├─ Dockerfile
│  ├─ docker-compose.yml
│  ├─ requirements.txt
│  ├─ alembic.ini
│  ├─ .env.example
│  ├─ .env.docker
│  ├─ reset_db.py
│  ├─ patch_service.py
│  ├─ test_e2e.py
│  ├─ migrations/
│  ├─ data/uploads/
│  └─ app/
├─ UI/
│  ├─ package.json
│  ├─ next.config.mjs
│  ├─ tsconfig.json
│  ├─ app/
│  ├─ components/
│  ├─ lib/
│  ├─ .next/        (artifact)
│  └─ node_modules/ (artifact)
├─ docs/
├─ Data sách/
└─ .github/
```

### 2.2. Vai trò của từng thư mục/module/service

| Path | Vai trò | Ghi chú |
| --- | --- | --- |
| `backend/app/main.py` | Entrypoint FastAPI, lifespan, router mounting, health/ready, WebSocket | Runtime backend chính |
| `backend/app/core/` | Settings, DB, Redis | Lớp hạ tầng cơ sở |
| `backend/app/models/` | SQLAlchemy models | Source-of-truth của schema runtime hiện tại |
| `backend/app/schemas/` | Pydantic request/response contract | Có nhiều field “future-facing” hơn DB thực tế |
| `backend/app/routers/` | HTTP API surfaces | Một số router là stub/compatibility layer |
| `backend/app/services/` | Business service layer | Auth/document/exam domain logic |
| `backend/app/rag/` | Parsing, heading detection, chunking, embedding, vector store | Luồng ingest tài liệu |
| `backend/app/agents/` | Orchestrator + sub-agents + skills + memory | Luồng sinh đề chính |
| `backend/app/tasks/` | Celery app và tasks | Có nhưng không phải mọi route chính đều dùng |
| `backend/app/websocket/` | Event fanout + replay qua Redis | Dùng cho progress generation |
| `backend/app/utils/` | Export, storage backend, vision/search shims | Utility cấp hệ thống |
| `backend/app/observability/` | Cost tracking + Langfuse tracing | Optional observability |
| `backend/migrations/` | Alembic migrations | Song song với `Base.metadata.create_all()` |
| `UI/app/` | App Router pages | Domain UI chính |
| `UI/components/` | Shared React components | `components/ui/*` chủ yếu là presentational wrappers |
| `UI/lib/api.ts` | Integration contract frontend-backend | Điểm nối quan trọng nhất ở phía UI |
| `docs/` | Design docs, future-state docs, archived notes | Không phải source-of-truth runtime |
| `Data sách/` | Tài liệu mẫu/tham chiếu | Không có dấu vết được app tự động mount/import vào runtime |

### 2.3. File nào là entrypoint, core logic, config

`Xác nhận`:

- Backend entrypoint: `backend/app/main.py`
- Frontend entrypoints: `UI/app/layout.tsx`, `UI/app/page.tsx`, `UI/app/dashboard/layout.tsx`
- Backend core logic:
  - ingest tài liệu: `backend/app/services/document_service.py`, `backend/app/rag/*`
  - sinh đề: `backend/app/routers/generate.py`, `backend/app/agents/orchestrator.py`, `backend/app/agents/{retrieval,outline,builder,validator}.py`
  - review/publish/export: `backend/app/services/exam_service.py`, `backend/app/routers/exams.py`, `backend/app/utils/export.py`
- Config backend: `backend/app/core/config.py`, `backend/.env.example`, `backend/.env.docker`, `backend/docker-compose.yml`, `backend/alembic.ini`
- Config frontend: `UI/package.json`, `UI/next.config.mjs`, `UI/tsconfig.json`, `UI/postcss.config.mjs`, `UI/app/globals.css`

### 2.4. Source-of-truth vs generated/local artifacts

`Xác nhận`:

- `UI/.next/`, `UI/node_modules/`, `backend/__pycache__/`, `backend/app/**/__pycache__/` là artifact/generated content, không nên dùng làm source-of-truth.
- `backend/data/uploads/` là dữ liệu runtime cục bộ do upload sinh ra, không phải schema hay fixture chuẩn.
- `Data sách/` chứa tài liệu tham khảo và dữ liệu mẫu; repo không có code tự động ingest thư mục này khi khởi động.
- `.github/` không có `workflows/`; hiện không thấy pipeline CI/CD trong repo.

## 3. Kiến trúc kỹ thuật

### 3.1. Kiểu kiến trúc đang dùng

`Xác nhận`: đây là một monorepo gồm:

- Một backend FastAPI dạng modular monolith: `backend/app/main.py`, `backend/app/routers/*`, `backend/app/services/*`.
- Một frontend Next.js App Router: `UI/app/*`, `UI/lib/api.ts`.
- Nhiều thành phần hạ tầng ngoài tiến trình backend: PostgreSQL, Redis, MinIO, Pinecone, Celery worker, tùy chọn Langfuse và provider LLM: `backend/docker-compose.yml`, `backend/app/core/config.py`, `backend/requirements.txt`.
- Một “multi-agent system” không tách microservice; các agent chỉ là module Python trong cùng backend process hoặc Celery worker process: `backend/app/agents/*`.

`Suy luận`: kiến trúc thực tế gần với “document-centric AI-enabled application” hơn là “distributed agent platform”.

### 3.1.1. Tech stack xác nhận từ package manifests

Backend manifest `backend/requirements.txt` cho thấy các nhóm phụ thuộc chính:

- Web/API: FastAPI, Uvicorn, Pydantic, SQLAlchemy async, Alembic
- Data/infra: asyncpg, Redis, Celery, boto3, Pinecone
- AI/RAG: OpenAI, Groq, Anthropic, instructor, llama-index, sentence-transformers, transformers, torch
- Parsing/OCR: PyMuPDF, marker-pdf, python-docx, python-pptx, Mathpix hooks
- Export/observability: WeasyPrint, Langfuse, Sentry

Frontend manifest `UI/package.json` cho thấy:

- Next.js `16.1.6`
- React `19.2.4`
- TypeScript `5.7.3`
- Tailwind CSS `4.2.0`
- Radix UI primitives + shadcn-style local wrappers
- Recharts, Sonner, React Hook Form, next-themes

### 3.2. High-level dependency graph

```text
Browser UI -> UI/lib/api.ts -> FastAPI routers
Routers -> services -> models/schemas/dependencies
Document flow -> storage -> parser -> structure -> chunker -> embedder -> Pinecone
Exam flow -> ExamService -> Orchestrator -> Retrieval/Outline/Builder/Validator -> skills/memory/LLM
Cross-cutting -> PostgreSQL + Redis + WebSocket manager + Exporter + Langfuse
```

### 3.3. Quan hệ giữa các service/module

`Xác nhận`:

- `main.py` mount tất cả router và gọi `init_db()`, `close_db()`, `close_redis()`: `backend/app/main.py`.
- Routers chủ yếu mỏng, đẩy business logic vào service (`auth_service.py`, `document_service.py`, `exam_service.py`) hoặc agent orchestrator: `backend/app/routers/*.py`.
- `generate.py` là adapter FE-compatible, còn `exams.py` là API surface rộng hơn cho generation/review/export/history: `backend/app/routers/generate.py`, `backend/app/routers/exams.py`.
- `exam_service.py` là cầu nối giữa orchestrator output và persistence JSONB trong bảng `exams`: `backend/app/services/exam_service.py`.
- `orchestrator.py` điều phối retrieval/outline/builder/validator, lưu short-term memory vào Redis và emit WebSocket events: `backend/app/agents/orchestrator.py`.
- `websocket/manager.py` tách riêng logic connection, replay và Redis pub/sub khỏi router: `backend/app/websocket/manager.py`.

### 3.4. Luồng dữ liệu khi hệ thống khởi động và xử lý request/job/event

`Xác nhận`:

1. FastAPI lifespan chạy `init_db()` và `Base.metadata.create_all()`, rồi ping Redis: `backend/app/main.py`, `backend/app/core/database.py`.
2. Frontend boot bằng `AuthProvider`, đọc token từ `localStorage`, gọi `/auth/me` để hydrate user: `UI/components/auth-provider.tsx`, `UI/lib/api.ts`.
3. Document upload đi qua `BackgroundTasks` của FastAPI ở route chính, dù Celery document task vẫn tồn tại: `backend/app/routers/documents.py`, `backend/app/tasks/document_task.py`.
4. Generation có hai đường: synchronous FE route `/generate/exam` và async Celery route `/exams/generate`: `backend/app/routers/generate.py`, `backend/app/routers/exams.py`, `backend/app/tasks/exam_task.py`.
5. WebSocket `/ws/exam/{exam_id}` replay events cũ từ Redis rồi subscribe pub/sub cho event mới: `backend/app/main.py`, `backend/app/websocket/manager.py`.

## 4. Phân tích backend theo module/service

### 4.1. Core platform

#### `backend/app/core/config.py`

- Trách nhiệm:
  - gom env/config runtime vào một `Settings`.
  - khai báo provider/model routing cho LLM, Pinecone, storage, JWT, Langfuse, Mathpix, vision.
- Public interface: `Settings`, `get_settings()`, property `ws_base_url`.
- Input: biến môi trường, `.env`.
- Output: settings object dùng ở toàn hệ thống.
- Assumption ngầm:
  - có thể đổi provider LLM mà không đổi code.
  - dimension embedding mặc định là 768, khớp local sentence-transformers config.

#### `backend/app/core/database.py`

- Trách nhiệm: tạo async engine/session, `get_db()`, `init_db()`, `close_db()`.
- Side effect quan trọng: `init_db()` gọi `Base.metadata.create_all()`.
- Rủi ro: coexist với Alembic có thể gây drift migration/state.

#### `backend/app/core/redis_client.py`

- Trách nhiệm: wrapper cho Redis JSON, hash, pub/sub, rate-limit increments.
- Dùng ở: auth, rate limiting, short-term memory, websocket replay/pubsub, embedding cache.

#### `backend/app/dependencies.py`

- Trách nhiệm: JWT, password hashing, auth dependencies, pagination helper.
- Auth model:
  - HTTP Bearer token
  - lookup `users.id` từ token `sub`
  - ownership-based access thay vì RBAC thực thụ

### 4.2. Auth

#### Files chính

- `backend/app/routers/auth.py`
- `backend/app/services/auth_service.py`
- `backend/app/models/user.py`
- `backend/app/models/refresh_token.py`
- `backend/app/schemas/auth.py`

#### Trách nhiệm chính

- đăng ký teacher user.
- đăng nhập và cấp access/refresh token.
- refresh token rotation.
- logout bằng revoke hashed refresh token.

#### Business rules đáng chú ý

- login rate limit: tối đa 5 attempts/phút/IP (`MAX_LOGIN_ATTEMPTS = 5`): `backend/app/services/auth_service.py`.
- refresh token được băm trước khi lưu DB: `backend/app/models/refresh_token.py`, `backend/app/services/auth_service.py`.
- auth hiện không kiểm tra xác minh email hay department/university dù frontend có field tương ứng: `UI/lib/api.ts`, `UI/app/page.tsx`, `backend/app/schemas/auth.py`.

### 4.3. Documents + RAG

#### Router surface

- upload/list/get/status/delete/refresh-url/curriculum-tree/rescan-structure: `backend/app/routers/documents.py`.

#### `backend/app/services/document_service.py`

- Trách nhiệm:
  - upload file và tạo metadata DB
  - tải file từ object storage
  - chạy parse/structure/chunk/embed/index
  - xóa file và vector data
  - chuyển heading tree sang format FE-compatible
- Input: `UploadFile`, `document_id`, file bytes, flat curriculum tree.
- Output: `DocumentUploadResponse`, `DocumentStatus`, `DocumentDetail`, v.v.
- Side effects:
  - ghi object storage
  - ghi PostgreSQL
  - ghi Redis cache embedding
  - ghi Pinecone index
- Assumption ngầm:
  - object storage key lưu trong `documents.s3_key` luôn tồn tại.
  - Pinecone namespace theo `document_id` + `chapter_id`.

#### `backend/app/rag/parser.py`

- PDF:
  - thử `marker-pdf` trước
  - fallback PyMuPDF nếu parser chính lỗi
- DOCX:
  - trích Heading 1..4 và table text
- PPTX:
  - trích title/text theo slide

#### `backend/app/rag/structure.py`

- xây `heading_tree` từ markdown headings.
- có heuristic fallback nếu tài liệu không có heading markdown rõ ràng.
- IDs tạo theo kiểu `ch1`, `ch1_sec1`, `ch1_sec1_sub1`.

#### `backend/app/rag/chunker.py`

- ưu tiên `SemanticSplitterNodeParser` nếu có embedding model.
- fallback sang paragraph/heading chunker.
- chunk metadata gồm `chunk_id`, `chapter_id`, `section_id`, `content_type`, `page_number`, `latex_repr`.

#### `backend/app/rag/embedder.py`

- dùng sentence-transformers local, lazy-loaded.
- cache embedding trong Redis.
- nếu model không load được thì fallback hash-based embedding để pipeline vẫn chạy.

#### `backend/app/rag/vector_store.py`

- dùng Pinecone.
- auto create index nếu chưa có.
- namespace: `"{document_id}_{chapter_id}"`.
- query/delete theo namespace.
- một số exception bị nuốt để pipeline degrade gracefully.

#### Storage

- abstraction layer ở `backend/app/utils/storage/`.
- backend active chọn bởi `STORAGE_BACKEND`.
- `minio_backend.py` là default trong config; `s3_backend.py` cho AWS thực.

### 4.4. Exam service + review/export

#### Files chính

- `backend/app/services/exam_service.py`
- `backend/app/models/exam.py`
- `backend/app/routers/exams.py`
- `backend/app/utils/export.py`

#### Trách nhiệm

- tạo exam row và lưu `scope`, `exam_config`, `questions` dưới dạng JSONB.
- append `ExamHistory` snapshots.
- update question list sau generation.
- chỉnh sửa từng câu / partial regenerate.
- publish exam và sync long-term preferences.
- export PDF/DOCX.

#### Public interface quan trọng

- `create_exam()`
- `update_questions()`
- `update_question()`
- `partial_regenerate()`
- `publish_exam()`
- `delete_exam()`
- `get_quality_summary()`
- `get_feedback_events()` và feedback store methods

#### Chưa xác minh / compatibility surface

- `get_feedback_events()`, `get_feedback_store_summary()`, `get_feedback_store()` là stub compatibility, chưa có feedback table riêng: `backend/app/services/exam_service.py`.
- field `current_version_number`, `feedback_event_count`, `feedback_events` ở nhiều adapter vẫn là synthetic/TODO: `backend/app/routers/exams.py`.

#### Export

- PDF dùng WeasyPrint.
- DOCX dùng `python-docx`.
- hỗ trợ include answers / include blueprint cho bản giáo viên.
- có guard file size tối đa 10MB sau render: `backend/app/utils/export.py`.

### 4.5. Multi-agent generation pipeline

#### `backend/app/agents/llm.py`

- abstract provider layer cho OpenAI, OpenRouter, Groq, Anthropic, Ollama, g4f.
- model routing theo role:
  - strong: orchestrator/builder/validator
  - light: planner/reranker/outline/skills/classifier
  - vision: model riêng
- fallback chain lấy từ config.

#### `backend/app/agents/planner.py`

- dùng khi request phức tạp.
- nếu request đơn giản thì orchestrator có thể đi theo default plan.

#### `backend/app/agents/retrieval.py`

- expand query bằng LLM.
- query vector store theo chapter.
- có thể rerank bằng LLM.
- `Suy luận`: mapping chapter title sang `chapter_id` có thể lệch do retrieval normalize bằng `chapter.lower().replace(" ", "_").replace("chương_", "ch")`, trong khi heading tree tạo id theo heuristics khác: `backend/app/agents/retrieval.py`, `backend/app/rag/structure.py`, `backend/app/rag/vector_store.py`.

#### `backend/app/agents/outline.py`

- tạo blueprint slot distribution bằng LLM.
- có fallback blueprint nếu LLM lỗi.
- Rủi ro cụ thể: fallback `distribution_summary["by_chapter"]` dùng `blueprint.count(ch)` trên list dict nên khó cho ra số đúng: `backend/app/agents/outline.py`.

#### `backend/app/agents/builder.py`

- build questions theo chunk blueprint.
- có thể gọi SerpAPI wrapper cho `van_dung_cao`.
- áp dụng `bloom_classifier`, `difficulty_estimator`, `dedup_checker`, `latex_renderer`.
- question format nội bộ dùng keys như `stem`, `options`, `correct_answer`, chưa phải shape FE final: `backend/app/agents/builder.py`.

#### `backend/app/agents/validator.py`

- kiểm tra bloom, scope, rồi gọi LLM validator.
- lưu retry issues vào Redis để builder vòng sau dùng lại.
- Rủi ro cụ thể:
  - gọi `scope_skill.run(question_stem=..., allowed_scope=...)` nhưng skill đòi `allowed_content, scope_chapters`; exception bị nuốt nên scope check nội bộ gần như bị vô hiệu: `backend/app/agents/validator.py`, `backend/app/agents/skills/scope_checker.py`.
  - issues do skill tạo có thể bị ghi đè bởi `issues` trả về từ LLM response trong đoạn sau của method validate: `backend/app/agents/validator.py`.

#### `backend/app/agents/orchestrator.py`

- orchestration chính của generation.
- emit HITL checkpoints.
- save/load short-term memory.
- dùng long-term memory khi publish/review.
- retry loop tối đa qua Redis-stored issues.
- có flow `clarification_needed` nếu prompt mơ hồ.
- `edit_via_prompt()` mới lập edit plan, chưa thực sự mutate exam/questions: `backend/app/agents/orchestrator.py`.

#### Skills

- `bloom_classifier.py`: classify Bloom bằng LLM, fallback keyword-based.
- `difficulty_estimator.py`: ước lượng difficulty/time theo Bloom.
- `dedup_checker.py`: phát hiện trùng lặp.
- `scope_checker.py`: so question với allowed chunks.
- `latex_renderer.py`: render formula bằng rule-based cleanup.

#### Memory

- short-term Redis session: `backend/app/agents/memory/short_term.py`
  - key `session:{exam_id}:{user_id}`
  - TTL 2 giờ
  - lưu exam_config, scope, retrieved_context, conversation_history, retry_count, review_feedback
- retry issues: `retry_issues:{exam_id}`, TTL 1 giờ
- long-term PostgreSQL: `teacher_preferences`
  - bloom distribution ưa thích
  - exam type ưa thích
  - subject focus
  - style notes
  (`backend/app/agents/memory/long_term.py`, `backend/app/models/teacher_preference.py`)

### 4.6. Tasks, WebSocket và observability

#### `backend/app/tasks/celery_app.py`

- cấu hình Celery broker/backend đều qua Redis.
- time limit cứng 600s, soft limit 540s.
- include `exam_task` và `document_task`.

#### `backend/app/tasks/exam_task.py`

- wrapper Celery cho generation async.
- tự tạo event loop để chạy async pipeline trong worker.
- có `DEMO_MODE` path và payload giả lập.

#### `backend/app/tasks/document_task.py`

- wrapper Celery cho document processing.
- tồn tại nhưng upload route chính đang đi qua `BackgroundTasks`, không phải dispatch task này.

#### `backend/app/websocket/manager.py`

- phát sự kiện qua socket hiện có.
- replay event cũ từ Redis list.
- subscribe Redis pub/sub cho multi-instance.

#### `backend/app/observability/*`

- `cost.py`: cost model và `ExamCostReport`
- `langfuse_client.py`: lazy singleton cho Langfuse
- `tracer.py`: decorators/context manager cho agent/skill/llm spans

`Chưa xác minh`: tracing Langfuse có được dùng đầy đủ trong production hay không phụ thuộc env keys, không thể khẳng định chỉ từ repo.

## 5. Phân tích frontend theo module

### 5.1. Khung ứng dụng

- `UI/app/layout.tsx`: bọc `ThemeProvider`, `AuthProvider`, Vercel Analytics.
- `UI/app/page.tsx`: landing page kiêm login/register.
- `UI/app/dashboard/layout.tsx`: shell sau đăng nhập.
- `UI/components/app-sidebar.tsx`, `UI/components/dashboard-header.tsx`: navigation/layout.

### 5.2. Integration contract

`UI/lib/api.ts` là file quan trọng nhất phía frontend:

- default base URL: `NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"`.
- lưu token trong `localStorage`.
- auto refresh khi gặp 401.
- định nghĩa các TypeScript interfaces cho `User`, `Course`, `Document`, `Exam`, `ExamVersion`, `FeedbackEvent`, `PlaybookBullet`, v.v.
- export các API groups: `documents`, `exams`, `generation`, `playbook`.

`Xác nhận`: frontend đang giả định nhiều field hơn backend thật sự persist, ví dụ:

- `User.department`, `User.university`, `User.is_email_verified`: `UI/lib/api.ts`
- `Exam.current_version`, `Exam.versions`, `feedback_events`, `provider_logs`, `quality_scores`: `UI/lib/api.ts`
- `Playbook*`, `FeedbackStore*`: `UI/lib/api.ts`

### 5.3. Các page domain

- `UI/app/dashboard/page.tsx`: dashboard quality + playbook overview + recent exams.
- `UI/app/dashboard/documents/page.tsx`: upload/list documents, chỉ accept PDF ở UI.
- `UI/app/dashboard/generate/page.tsx`: chọn tài liệu/scope và gọi generation.
- `UI/app/dashboard/exams/[id]/page.tsx`: review/edit/regenerate/publish.
- `UI/app/dashboard/history/page.tsx`: xem exam list và feedback summary.
- `UI/app/dashboard/feedback/page.tsx`: filter event stream.
- `UI/app/dashboard/playbook/page.tsx`: quản lý bullets/candidates/warmup shell.
- `UI/app/dashboard/settings/page.tsx`: hiển thị runtime boundary/phạm vi Phase 4.

`Chưa xác minh`: vì backend playbook endpoints đang 501, các page tương ứng hiện là UI shell/fallback nhiều hơn là fully working feature.

### 5.4. UI components khác

- `UI/components/ui/*`: local copies/wrappers của nhiều primitive Radix/shadcn. Đây là infrastructure UI, không phải business logic sản phẩm.
- `UI/lib/quality.ts`: helper phía UI để tính pass rate/evidence coverage/filter feedback.

## 6. API / interface / contract

### 6.1. Root, health và WebSocket

| Method | Path | Auth | Mô tả |
| --- | --- | --- | --- |
| `GET` | `/health` | No | heartbeat đơn giản từ `main.py` |
| `GET` | `/ready` | No | readiness gồm database, redis, pinecone |
| `GET` | `/` | No | root message |
| `WS` | `/ws/exam/{exam_id}` | No | stream tiến trình generation, replay từ Redis |

`Xác nhận`: WebSocket route không dùng auth dependency, chỉ cần `exam_id`: `backend/app/main.py`.

### 6.2. Auth API

| Method | Path | Auth | Ghi chú |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/register` | No | tạo teacher user |
| `POST` | `/api/v1/auth/login` | No | rate limit theo IP, trả access + refresh |
| `POST` | `/api/v1/auth/refresh` | No | refresh token rotation |
| `POST` | `/api/v1/auth/logout` | No | revoke refresh token |
| `GET` | `/api/v1/auth/me` | Yes | trả current user |

### 6.3. Documents API

| Method | Path | Auth | Ghi chú |
| --- | --- | --- | --- |
| `POST` | `/api/v1/documents/upload` | Yes | upload file, start background processing |
| `GET` | `/api/v1/documents` | Yes | list documents của user |
| `GET` | `/api/v1/documents/{id}` | Yes | document detail |
| `GET` | `/api/v1/documents/{id}/status` | Yes | polling status |
| `DELETE` | `/api/v1/documents/{id}` | Yes | xoá DB + storage + vector namespaces |
| `GET` | `/api/v1/documents/{id}/refresh-url` | Yes | fresh presigned URL |
| `GET` | `/api/v1/documents/{id}/curriculum-tree` | Yes | tree cho scope selection |
| `PATCH` | `/api/v1/documents/{id}/curriculum-tree` | Yes | update tree |
| `POST` | `/api/v1/documents/{id}/rescan-structure` | Yes | rescan heading tree |

### 6.4. Courses, generation, exams và playbook API

| Surface | Trạng thái thực tế | File chính |
| --- | --- | --- |
| `courses` | đa số placeholder/stub | `backend/app/routers/courses.py` |
| `generate/exam` | FE route chính, sync inline | `backend/app/routers/generate.py` |
| `exams/generate` | async/Celery route | `backend/app/routers/exams.py`, `backend/app/tasks/exam_task.py` |
| `exams/*` review/export/history | working core flow | `backend/app/routers/exams.py` |
| `playbook/*` | 501 planned | `backend/app/routers/playbook.py` |

### 6.5. Request/response schema quan trọng

| API | Request schema thực tế | Response schema thực tế | Ghi chú |
| --- | --- | --- | --- |
| `POST /api/v1/documents/upload` | multipart form (`file`, `title`, `language`) | `DocumentUploadResponse` | FE gửi `FormData`; backend không dùng JSON schema ở route này |
| `POST /api/v1/generate/exam` | FE gửi shape gần `ExamGenerationRequest`, backend map sang `ExamConfigRequest` bằng `_map_fe_to_be_request()` | `ExamGenerateResponse` | Route synchronous, FE-compatible |
| `POST /api/v1/exams/generate` | `ExamConfigRequest` | `ExamGenerateResponse` | Route async/Celery |
| `POST /api/v1/generate/partial-regenerate` | payload gần `ExamPartialRegenerateRequest` | exam detail dict tương thích FE | Edit/regenerate partial |
| `PATCH /api/v1/exams/{exam_id}/questions/{question_id}` | `EditQuestionRequest` | exam detail dict | Inline edit |
| `POST /api/v1/exams/{exam_id}/edit-prompt` | `PromptEditRequest` | dict kế hoạch chỉnh sửa | Chưa apply sửa đổi thật |
| `POST /api/v1/exams/{exam_id}/submit-review` | `ExamReviewRequest` | `ExamReviewResponse` | Approve hoặc yêu cầu regenerate |
| `GET /api/v1/exams/{exam_id}/preview` | query params export flags | `ExportPreviewResponse` | HTML preview, không phải file |
| `POST /api/v1/auth/login` | login request schema ở `backend/app/schemas/auth.py` | `TokenResponse` tương thích FE | FE lưu token vào `localStorage` |

Lưu ý contract:

- `UI/lib/api.ts` kỳ vọng nhiều field hơn schema/persistence thật của backend, đặc biệt quanh `User`, `Exam`, `ExamVersion`, `FeedbackEvent`, `Playbook*`.
- `DocumentStatus` trong schema backend nhấn mạnh `pending/processing/completed/failed`, nhưng frontend còn xử lý thêm `processed`, `structured`, `indexed` như các trạng thái “usable”: `backend/app/schemas/document.py`, `UI/app/dashboard/generate/page.tsx`.

### 6.6. Auth/Authz, error handling, retry, timeout, rate limit

`Xác nhận`:

- Auth: HTTP Bearer access token; refresh token bằng body API, không phải cookie: `backend/app/dependencies.py`, `backend/app/routers/auth.py`, `UI/lib/api.ts`.
- Authz: tài nguyên được giới hạn theo `user_id`; chưa có RBAC chi tiết ngoài field `role` trên user: `backend/app/services/*`, `backend/app/dependencies.py`.
- Error handling:
  - routers raise `HTTPException` cho lỗi validation/business.
  - global exception handler trả JSON 500 generic: `backend/app/main.py`.
  - nhiều utility nuốt exception để degrade gracefully, nhất là vector/search/tracing/storage.
- Retry/timeout:
  - Celery task time limit 600s, soft 540s: `backend/app/tasks/celery_app.py`.
  - `process_document_task` autoretry 3 lần với backoff: `backend/app/tasks/document_task.py`.
  - synchronous `/generate/exam` map `TimeoutError` thành 504: `backend/app/routers/generate.py`.
- Rate limit:
  - login: 5 attempts/phút/IP: `backend/app/services/auth_service.py`.
  - generation: 10 lần/ngày/user cho cả `/generate/exam` và `/exams/generate`: `backend/app/routers/exams.py`, `backend/app/routers/generate.py`.

## 7. Dữ liệu và persistence

### 7.1. PostgreSQL schema runtime

`Xác nhận` từ `backend/app/models/*` và `backend/migrations/versions/*`:

| Table | Vai trò | Ghi chú |
| --- | --- | --- |
| `users` | tài khoản người dùng | role hiện chủ yếu là `teacher` |
| `refresh_tokens` | refresh token rotation/revoke | token hash thay vì plaintext |
| `documents` | metadata tài liệu upload | `course_id` nullable, không có FK tới `courses` |
| `exams` | exam aggregate chính | nhiều trường JSONB |
| `exam_history` | snapshot versioning | gần với history log hơn là normalized version table |
| `teacher_preferences` | long-term memory | 1 row/user |

### 7.2. Cấu trúc dữ liệu đáng chú ý

- `documents.heading_tree`: JSONB cấu trúc chapter/section/subsection.
- `exams.scope`: JSONB selected scope.
- `exams.exam_config`: JSONB cấu hình generation.
- `exams.questions`: JSONB toàn bộ question list.
- `exams.cost_report`: JSONB cost/tokens.
- `exam_history.snapshot`: JSONB snapshot exam state.

`Suy luận`: schema ưu tiên tốc độ iterate product hơn là chuẩn hóa relational. Nhiều state/phản hồi/phiên bản được nhét vào JSONB thay vì bảng con riêng.

### 7.3. Các field quan trọng và ý nghĩa nghiệp vụ

| Entity.field | Ý nghĩa nghiệp vụ | Nguồn |
| --- | --- | --- |
| `documents.processing_status` | trạng thái ingest/index của tài liệu; UI dùng để quyết định có cho generate hay không | `backend/app/models/document.py`, `backend/app/routers/documents.py`, `UI/app/dashboard/generate/page.tsx` |
| `documents.heading_tree` | curriculum tree dùng để giáo viên chọn phạm vi sinh đề | `backend/app/models/document.py`, `backend/app/rag/structure.py` |
| `documents.s3_key` | object key nội bộ tới file gốc | `backend/app/models/document.py`, `backend/app/utils/storage/*` |
| `documents.total_chunks` | số chunk đã sinh/index, phản ánh mức sẵn sàng retrieval | `backend/app/models/document.py`, `backend/app/services/document_service.py` |
| `documents.parse_error_message` | lỗi parse/index gần nhất | `backend/app/models/document.py`, `backend/app/services/document_service.py` |
| `exams.status` | vòng đời exam: draft/regenerating/ready_for_review/published/... | `backend/app/models/exam.py`, `backend/app/services/exam_service.py` |
| `exams.scope` | phạm vi chương/mục được chọn | `backend/app/models/exam.py`, `backend/app/services/exam_service.py` |
| `exams.exam_config` | cấu hình generation và metadata phụ trợ | `backend/app/models/exam.py`, `backend/app/schemas/exam.py` |
| `exams.questions` | toàn bộ output generation và state review ở dạng JSONB | `backend/app/models/exam.py`, `backend/app/services/exam_service.py` |
| `exams.cost_report` | token/cost breakdown của quá trình sinh đề | `backend/app/models/exam.py`, `backend/app/observability/cost.py` |
| `refresh_tokens.revoked` | cờ vô hiệu hóa refresh token đã logout/rotate | `backend/app/models/refresh_token.py`, `backend/app/services/auth_service.py` |
| `teacher_preferences.*` | long-term memory rút ra từ exam đã publish | `backend/app/models/teacher_preference.py`, `backend/app/agents/memory/long_term.py` |

### 7.4. Quan hệ bảng / entity

`Xác nhận`:

- `users` 1-n `documents`
- `users` 1-n `exams`
- `users` 1-n `refresh_tokens`
- `users` 1-1 mềm với `teacher_preferences`
- `documents` có thể được tham chiếu từ `exams.document_id`
- `exams` 1-n `exam_history`

`Chưa xác minh`:

- không có bảng `courses`, `feedback_events`, `exam_versions`, `playbook_bullets`, `reflection_candidates` trong DB runtime hiện tại dù UI/schema/docs nói nhiều về chúng.

### 7.5. Migrations

- Alembic env: `backend/migrations/env.py`
- migrations hiện có:
  - `001_initial.py`
  - `bd3064db5e63_add_course_id_to_documents.py`
  - `add_file_size_to_documents.py`

Rủi ro:

- app startup dùng `create_all()` thay vì bắt buộc migrate.
- `reset_db.py` drop toàn bộ schema `public` rồi recreate.

### 7.6. Redis

`Xác nhận`:

- rate-limit keys:
  - `ratelimit:login:{ip}`
  - `ratelimit:generate:{user_id}:{date}`
- short-term memory:
  - `session:{exam_id}:{user_id}`
  - `retry_issues:{exam_id}`
- WebSocket/event:
  - `ws_events:{exam_id}`
  - pub/sub channel `exam:{exam_id}`
- embedding cache: do `embedder.py` tạo, keyed theo document/chunk hash.

### 7.7. Vector store, cache và object storage

- Vector DB: Pinecone index, dimension theo `ST_EMBEDDING_DIM`: `backend/app/rag/vector_store.py`, `backend/app/core/config.py`.
- Object storage:
  - MinIO mặc định
  - AWS S3 tùy chọn
  (`backend/app/utils/storage/*`, `backend/docker-compose.yml`)
- Cache:
  - Redis cho embedding
  - Redis cho websocket replay
  - Redis cho short-term memory

### 7.8. Dữ liệu mẫu và dữ liệu ngoài runtime

`Data sách/` chứa:

- PDF/DOCX/XLSX vật lý và đáp án.
- `teacher_reference_cases_from_docx.json` mô tả bộ reference cases/warmup data đã extract từ tài liệu giáo viên.

`Suy luận`: đây là nguồn dữ liệu thủ công/phục vụ nghiên cứu hoặc curation offline, không phải fixture được app tự nạp lúc boot.

## 8. Business logic quan trọng

### 8.1. Rule encode trong code

`Xác nhận`:

- Bloom distribution phải sum = 100: `backend/app/routers/generate.py`, `backend/app/routers/exams.py`.
- Upload size tối đa 100MB và MIME whitelist tại route documents: `backend/app/routers/documents.py`.
- Document ownership enforced khi đọc/xóa/chỉnh sửa tree: `backend/app/services/document_service.py`, `backend/app/routers/documents.py`.
- Exam ownership enforced cho get/edit/publish/delete/review/export: `backend/app/services/exam_service.py`, `backend/app/routers/exams.py`.
- Publish exam sẽ ghi long-term preference: `backend/app/services/exam_service.py`, `backend/app/agents/memory/long_term.py`.
- Builder cố tránh duplicate topics và gắn difficulty/bloom metadata sau generation: `backend/app/agents/builder.py`.
- Validator dùng Redis retry issues để loop chỉnh lại generation: `backend/app/agents/validator.py`, `backend/app/agents/orchestrator.py`.

### 8.2. Validation và branching

- Nếu prompt mơ hồ, orchestrator có thể dừng sớm bằng `clarification_needed`: `backend/app/agents/orchestrator.py`.
- Nếu blueprint chưa approve, orchestrator chờ Redis key `hitl:approved:{exam_id}:1`: `backend/app/agents/orchestrator.py`.
- Nếu review reject, orchestrator dispatch rerun: `backend/app/agents/orchestrator.py`, `backend/app/routers/exams.py`.
- Nếu embed/index thất bại, document parsing vẫn có thể coi là usable ở mức nào đó: `backend/app/services/document_service.py`.

### 8.3. Edge cases có xử lý hoặc chưa xử lý

Đã xử lý:

- parser fallback từ marker-pdf sang PyMuPDF.
- embedder fallback sang hash-based vectors.
- OpenAI/Groq/OpenRouter/... fallback chain trong `LLMClient`.
- WebSocket replay khi reconnect.

Chưa xử lý tốt hoặc chỉ xử lý một phần:

- scope checker mismatch làm mất kiểm tra scope ở validator.
- feedback/playbook store chưa có persistence thật.
- UI/BE contract drift ở nhiều field.
- status document có thể mơ hồ giữa `completed`, `processed`, `indexed`.
- WebSocket không auth.

## 9. Cấu hình và môi trường chạy

### 9.1. Biến môi trường backend

Nhóm chính trong `backend/app/core/config.py`, `backend/.env.example`, `backend/.env.docker`:

- Database: `DATABASE_URL`
- Redis/Celery: `REDIS_URL`, `CELERY_BROKER_URL`
- LLM: `LLM_PROVIDER`, `LLM_FALLBACK_CHAIN`, `LLM_MODEL_STRONG`, `LLM_MODEL_LIGHT`, `LLM_MODEL_VISION`, các API keys OpenAI/OpenRouter/Groq/Anthropic/Ollama
- Embedding/vector: `ST_EMBEDDING_MODEL`, `ST_EMBEDDING_DIM`, `PINECONE_*`
- Storage: `STORAGE_BACKEND`, `MINIO_*`, `AWS_*`
- Auth: `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`
- Observability: `LANGFUSE_*`, `SENTRY_DSN`
- Vision/OCR: `MATHPIX_*`, `QWEN_VISION_*`
- Runtime: `HOST`, `PORT`, `DEBUG`, `DEMO_MODE`, `APP_BASE_URL`, `CORS_ORIGINS`

### 9.2. Config frontend

- `NEXT_PUBLIC_API_URL` là env runtime đáng chú ý nhất: `UI/lib/api.ts`.
- build config:
  - `ignoreBuildErrors: true`
  - `images.unoptimized: true`
  (`UI/next.config.mjs`)

### 9.3. Dev / staging / production differences

`Xác nhận`:

- `backend/.env.docker` dùng hostname Docker (`postgres`, `redis`), còn config default trong code và `.env.example` dùng local defaults.
- `backend/docker-compose.yml` mount source code và expose backend/worker/minio/postgres/redis.
- UI không có Dockerfile trong repo; chạy độc lập bằng `next dev`/`next build`/`next start`.

`Rủi ro`: `backend/.env.example` default `DATABASE_URL` trỏ `postgres:postgres@localhost/curriculum_ai`, trong khi `docker-compose.yml` khởi tạo DB `examai/examai/examai`; nếu copy nhầm env example mà không sửa, app sẽ trỏ sai database.

### 9.4. Build / run / deploy

Backend:

1. `docker-compose up -d` trong `backend/` để chạy Postgres/Redis/MinIO/Celery/API.
2. Hoặc chạy API riêng bằng `uvicorn app.main:app`.
3. Alembic tồn tại nhưng app cũng tự `create_all()`.

Frontend:

1. `npm run dev` trong `UI/`
2. `npm run build`
3. `npm run start`

Scripts hỗ trợ:

- `backend/test_e2e.py`
- `test_generate.py`, `test_generate2.py`, `test_generate3.py`
- `backend/reset_db.py`

## 10. Hạ tầng và vận hành

### 10.1. Docker / Compose

`backend/docker-compose.yml` định nghĩa:

- `minio`
- `postgres`
- `redis`
- `celery_worker`
- `api`

Có healthcheck cho:

- MinIO
- PostgreSQL
- Redis
- API `/health`

### 10.2. Background jobs và scheduler

- Background jobs có 2 cơ chế:
  - FastAPI `BackgroundTasks` cho document processing route chính
  - Celery worker cho exam/document tasks khi đi qua async path
- Không thấy cron/scheduler định kỳ trong repo.

### 10.3. Logging / monitoring / tracing

- logging chủ yếu qua Python logging.
- Langfuse tracing optional.
- cost report được lưu vào exam JSON.
- không thấy metrics system kiểu Prometheus/Grafana/OpenTelemetry collector trong repo.

### 10.4. Healthcheck

- `/health`: liveness đơn giản.
- `/ready`: kiểm tra DB, Redis, Pinecone.

`Chưa xác minh`: nếu Pinecone key không cấu hình, readiness có thể fail dù phần lớn app local vẫn chạy được.

### 10.5. CI/CD, infra files khác

`Xác nhận`:

- không có `.github/workflows/*`
- không có Kubernetes manifests
- không có nginx/reverse proxy config
- không có Terraform/Helm/Ansible

Kết luận: repo hiện có local/dev dockerization tốt hơn là deployment automation hoàn chỉnh.

## 11. Bảo mật

### 11.1. Secret handling

- Repo có `.env.example` và `.env.docker`.
- Quan sát thấy tồn tại cả `backend/.env` trong working tree, nhưng tài liệu này không lặp lại nội dung file đó.
- JWT secret có default placeholder nguy hiểm nếu dùng nguyên trạng: `backend/app/core/config.py`, `backend/.env.docker`.

### 11.2. Auth flow

- Access token Bearer cho API.
- Refresh token gửi qua JSON body.
- Refresh token hash lưu DB và có revoke flag.
- FE giữ token trong `localStorage`, không phải httpOnly cookie: `UI/lib/api.ts`.

### 11.3. Permission model

- Model quyền thực tế là owner-only.
- `role` tồn tại trên `users`, nhưng repo chưa có policy admin/teacher/student đầy đủ.
- Courses/playbook/feedback permission model chi tiết chưa có vì feature chưa hoàn thiện.

### 11.4. Rủi ro quan sát được từ code/config

1. WebSocket generation stream không auth; ai biết `exam_id` có thể thử subscribe: `backend/app/main.py`.
2. Token nằm trong `localStorage`; tăng bề mặt tấn công XSS: `UI/lib/api.ts`.
3. `ignoreBuildErrors: true` làm frontend có thể build dù TS contract sai: `UI/next.config.mjs`.
4. Provider `g4f` và fallback “free aggregator” xuất hiện trong code; phù hợp dev/test hơn là production: `backend/app/agents/llm.py`.
5. Nhiều exception bị nuốt, có thể che khuất lỗi thật ở vector/search/tracing/storage: `backend/app/rag/vector_store.py`, `backend/app/agents/*`, `backend/app/websocket/manager.py`.

## 12. Điểm chưa rõ / nợ kỹ thuật / rủi ro

### 12.1. Code/docs mâu thuẫn hoặc drift

1. `README.md` và `UI/settings` nói runtime chỉ PDF/MCQ/Physics/Vietnamese, nhưng backend parser/route vẫn hỗ trợ DOCX/PPTX: `README.md`, `UI/app/dashboard/settings/page.tsx`, `backend/app/routers/documents.py`, `backend/app/rag/parser.py`.
2. `backend/README.md`, `run_guide.md`, `tutorial.md`, `spec_curriculum_ai_agent.md` chứa nhiều mô tả lịch sử/aspirational, không còn khớp hoàn toàn runtime.
3. `docs/feedback_store.md`, `docs/playbook_model.md`, `docs/ace_foundation.md` mô tả nền tảng feedback/playbook phong phú hơn nhiều so với DB/runtime hiện tại.
4. `UI/app/globals.css` là CSS source-of-truth đang được import, trong khi `UI/styles/globals.css` hiện diện nhưng không thấy file nào tham chiếu: `UI/app/layout.tsx`, `UI/components.json`, `UI/styles/globals.css`.

### 12.2. Phần có vẻ dang dở hoặc stub

1. `courses` router chủ yếu là placeholder: `backend/app/routers/courses.py`.
2. `playbook` router toàn bộ trả 501 planned: `backend/app/routers/playbook.py`.
3. Feedback store methods là compatibility stubs: `backend/app/services/exam_service.py`.
4. Versioning ở UI/API phong phú hơn persistence thực; hiện chủ yếu dựa vào `exam_history` snapshots: `backend/app/models/exam.py`, `backend/app/routers/exams.py`, `UI/lib/api.ts`.

### 12.3. Rủi ro kỹ thuật cụ thể

1. `create_all()` khi startup song song với Alembic có thể gây drift schema/state: `backend/app/core/database.py`, `backend/migrations/env.py`.
2. Upload route nói về Celery trong description nhưng implementation lại dùng FastAPI background task: `backend/app/routers/documents.py`, `backend/app/tasks/document_task.py`.
3. Scope check validator bị lệch chữ ký hàm: `backend/app/agents/validator.py`, `backend/app/agents/skills/scope_checker.py`.
4. Fallback outline tính sai `by_chapter`: `backend/app/agents/outline.py`.
5. Retrieval namespace normalization có thể không khớp với chapter ids từ heading tree: `backend/app/agents/retrieval.py`, `backend/app/rag/structure.py`, `backend/app/rag/vector_store.py`.
6. `edit_via_prompt()` mới lập edit plan, chưa apply sửa đổi thật: `backend/app/agents/orchestrator.py`.
7. UI hiển thị feedback/playbook/version metrics đậm hơn dữ liệu backend thực sự có.
8. Một số file/scripts có hiện tượng mojibake/encoding lệch trong comment/docstring, làm giảm độ rõ ràng khi bảo trì: nhiều file dưới `backend/`, `test_e2e.py`, `spec_curriculum_ai_agent.md`.

### 12.4. Các giả định cần xác minh thêm

- `Chưa xác minh`: production hiện có dùng path synchronous `/generate/exam` hay Celery `/exams/generate` là chính.
- `Chưa xác minh`: Pinecone/index lifecycle ngoài local dev có được provision sẵn hay trông chờ app auto-create index.
- `Chưa xác minh`: playbook/feedback store đang được phát triển ở branch khác hay chỉ mới là UI/docs placeholder.
- `Chưa xác minh`: các file dữ liệu trong `Data sách/` có đang được dùng trong pipeline warmup/eval ngoài repo hay không.

## 13. Hướng dẫn tái dựng mental model

### 13.1. Nếu là kỹ sư mới vào dự án, nên đọc gì trước

Thứ tự khuyến nghị:

1. `README.md`
2. `backend/app/main.py`
3. `backend/app/core/config.py`
4. `backend/app/routers/generate.py`
5. `backend/app/routers/exams.py`
6. `backend/app/services/document_service.py`
7. `backend/app/agents/orchestrator.py`
8. `backend/app/agents/{retrieval,outline,builder,validator}.py`
9. `backend/app/rag/{parser,structure,chunker,embedder,vector_store}.py`
10. `UI/lib/api.ts`
11. `UI/app/dashboard/generate/page.tsx`
12. `UI/app/dashboard/exams/[id]/page.tsx`

Lý do:

- Đây là chuỗi file tái hiện trọn luồng upload -> scope -> generate -> review -> publish.
- Đọc docs trước code chỉ nên dùng để biết ý định sản phẩm; source-of-truth nằm ở các file trên.

### 13.2. Cần chạy thành phần nào theo thứ tự nào

1. Chuẩn bị backend infra trong `backend/docker-compose.yml`: Postgres, Redis, MinIO, Celery.
2. Khởi động backend API.
3. Khởi động frontend Next.js ở `UI/`.
4. Đăng nhập trên UI.
5. Upload document.
6. Chờ document parse/index xong.
7. Generate exam.
8. Review/publish/export.

### 13.3. Nên bắt đầu debug từ đâu

Nếu lỗi upload/tài liệu:

- `backend/app/routers/documents.py`
- `backend/app/services/document_service.py`
- `backend/app/rag/parser.py`
- `backend/app/rag/structure.py`
- `backend/app/rag/embedder.py`
- `backend/app/rag/vector_store.py`

Nếu lỗi generation:

- `UI/lib/api.ts`
- `backend/app/routers/generate.py`
- `backend/app/services/exam_service.py`
- `backend/app/agents/orchestrator.py`
- `backend/app/agents/{retrieval,outline,builder,validator}.py`
- `backend/app/websocket/manager.py`

Nếu lỗi review/history/feedback:

- `backend/app/routers/exams.py`
- `backend/app/services/exam_service.py`
- `UI/app/dashboard/exams/[id]/page.tsx`
- `UI/app/dashboard/history/page.tsx`
- `UI/app/dashboard/feedback/page.tsx`

Nếu lỗi auth:

- `backend/app/routers/auth.py`
- `backend/app/services/auth_service.py`
- `backend/app/dependencies.py`
- `UI/components/auth-provider.tsx`
- `UI/lib/api.ts`

### 13.4. Cách giữ mental model đúng

- Luôn phân biệt 3 lớp:
  - runtime thật: backend services/routers/models/tasks đang chạy
  - compatibility surface: schema/UI fields để giữ FE không vỡ
  - future-state docs: feedback/playbook/ACE foundation
- Với mọi tính năng mới, kiểm tra lần lượt:
  - UI có gọi endpoint nào trong `UI/lib/api.ts`
  - router nào thực sự xử lý endpoint đó
  - service/model nào persist dữ liệu
  - dữ liệu đó có bảng riêng hay chỉ nằm trong JSONB/Redis

## 14. Kết luận ngắn

`Xác nhận`: repo đã có một lõi chạy được cho bài toán upload tài liệu -> chọn scope -> sinh đề -> review -> publish, với backend monolith tương đối dày logic và frontend dashboard tương đối hoàn chỉnh.

`Xác nhận`: phần “ACE foundation” như feedback store, playbook bullet, reflection candidate, warmup export hiện xuất hiện mạnh ở docs, schema và UI, nhưng backend runtime mới chỉ có stub hoặc compatibility layer.

`Suy luận`: nếu tiếp tục phát triển repo này, điểm quan trọng nhất là đóng khoảng cách giữa UI/schema/docs và persistence/runtime thật, đặc biệt quanh versioning, feedback events, playbook store, auth cho WebSocket, và chiến lược migration/schema ownership.
