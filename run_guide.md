# Curriculum AI Backend — Hướng dẫn chạy & Kiểm tra sẵn sàng

## Kiến trúc tổng quan

```
Frontend (Next.js :3000)
        │
        ▼
FastAPI Backend (:8000)
  ├── /auth          → JWT authentication
  ├── /courses       → quản lý môn học
  ├── /documents     → upload + parse tài liệu (PDF/DOCX/PPTX)
  ├── /exams         → CRUD + export đề thi
  ├── /generate      → trigger sinh đề (multi-agent)
  ├── /playbook      → preferences giáo viên
  └── WS /ws/exam/{id} → stream tiến trình sinh đề
        │
        ├── PostgreSQL  (SQLAlchemy async) — users, courses, documents, exams
        ├── Redis       — pub/sub WebSocket + embedding cache + rate limit
        ├── MinIO       — file storage (PDF, DOCX, export)
        ├── Pinecone    — vector store (RAG chunks)
        ├── OpenAI      — text-embedding-3-large (bắt buộc cho RAG)
        ├── Groq/OpenAI/... — LLM cho agents
        └── Qwen3.5-9B (ngrok) — OCR ảnh / mô tả ảnh (primary vision)
```

---

## Các thành phần phụ thuộc

| Thành phần | Bắt buộc? | Ghi chú |
|---|---|---|
| **PostgreSQL** | ✅ Bắt buộc | Lưu users, courses, documents, exams |
| **Redis** | ✅ Bắt buộc | WebSocket pub/sub, embedding cache |
| **MinIO** | ✅ Bắt buộc | File storage (hoặc dùng bản chạy ngoài Docker) |
| **Pinecone** | ✅ Bắt buộc | Vector store cho RAG |
| **OpenAI API key** | ✅ Bắt buộc | Chỉ cho embedding (`text-embedding-3-large`) |
| **Groq API key** | ✅ Bắt buộc (as primary LLM) | LLM cho agents (có thể đổi sang OpenRouter) |
| **Qwen Vision (ngrok)** | ⚠️ Khuyến nghị | OCR ảnh / công thức — cần cập nhật URL khi restart |
| **MathPix** | ❌ Optional | Fallback OCR — để trống key là tự disable |
| **LangFuse** | ❌ Optional | Observability — đã có key trong .env |
| **Celery Worker** | ⚠️ Khuyến nghị | Chạy background tasks — cần Redis |

---

## Bước 1 — Cài đặt môi trường

```powershell
# Tạo virtual environment
python -m venv venv
venv\Scripts\activate

# Cài dependencies
pip install -r requirements.txt
```

> [!WARNING]
> `marker-pdf` rất nặng (tải nhiều ML model). Nếu chỉ test nhanh, có thể comment nó trong [requirements.txt](file:///e:/%C4%90%E1%BB%93%20%C3%A1n/Project/backend/requirements.txt) — parser sẽ tự fallback sang PyMuPDF.

---

## Bước 2 — Khởi động infrastructure

### Option A: Docker Compose (khuyến nghị)

```powershell
# Trong thư mục backend/
docker compose up postgres redis minio -d
```

> [!NOTE]
> Nếu đã chạy MinIO ngoài Docker (`minio.exe server E:\MiNIO`) thì bỏ `minio` khỏi lệnh trên.
minio.exe server E:\MiNIO --console-address :9001

### Option B: Thủ công

- **PostgreSQL**: Cài PostgreSQL 16, tạo database `curriculum_ai`, user `postgres/postgres`
- **Redis**: Cài Redis hoặc dùng `redis-server.exe` trên Windows
- **MinIO**: Đã chạy ngoài Docker tại `http://127.0.0.1:9000` ✅

---

## Bước 3 — Kiểm tra [.env](file:///e:/%C4%90%E1%BB%93%20%C3%A1n/Project/backend/.env)

File [.env](file:///e:/%C4%90%E1%BB%93%20%C3%A1n/Project/backend/.env) đã có đủ cấu hình. Những mục cần kiểm tra trước khi chạy:

```dotenv
# ✅ Đã set — LLM chính
GROQ_API_KEY=xxx

# ⚠️ CẦN SET — dùng cho embedding (bắt buộc cho RAG)
OPENAI_API_KEY=sk-...          # thay bằng key thật

# ✅ Đã set — Pinecone
PINECONE_API_KEY=pcsk_3M7p...

# ✅ Đã set — Qwen Vision (OCR ảnh)
QWEN_VISION_BASE_URL=https://ce4d-136-116-250-62.ngrok-free.app

# ⚠️ Cần đổi khi ngrok restart
# QWEN_VISION_BASE_URL=https://<new-url>.ngrok-free.app

# ✅ Đã set — PostgreSQL (khớp với docker-compose)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/curriculum_ai
```

> [!CAUTION]
> [docker-compose.yml](file:///e:/%C4%90%E1%BB%93%20%C3%A1n/Project/backend/docker-compose.yml) tạo PostgreSQL với user `examai/examai/examai`, nhưng [.env](file:///e:/%C4%90%E1%BB%93%20%C3%A1n/Project/backend/.env) trỏ đến `postgres/postgres/curriculum_ai`. Cần sửa 1 trong 2:
> - Đổi [.env](file:///e:/%C4%90%E1%BB%93%20%C3%A1n/Project/backend/.env): `DATABASE_URL=postgresql+asyncpg://examai:examai@localhost:5432/examai`
> - **Hoặc** tạo thủ công DB `curriculum_ai` với user `postgres` ngoài Docker

---

## Bước 4 — Chạy server

```powershell
# Trong thư mục backend/ (venv activated)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Khi khởi động thành công, sẽ thấy:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Truy cập:
- 📄 **Swagger UI**: http://localhost:8000/docs
- 💚 **Liveness**: http://localhost:8000/health
- 🔍 **Readiness** (DB + Redis + Pinecone): http://localhost:8000/ready

---

## Bước 5 — Chạy Celery Worker (tùy chọn)

```powershell
# Tab terminal mới
venv\Scripts\activate
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
```

---

## Checklist trạng thái hiện tại

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| FastAPI app structure | ✅ Sẵn sàng | Routers, middleware, lifespan đầy đủ |
| Database models | ✅ Sẵn sàng | User, Document, Exam, Course... |
| LLM multi-provider | ✅ Sẵn sàng | Groq primary → g4f fallback |
| RAG pipeline | ✅ Sẵn sàng | Parser, chunker, embedder, vector store |
| Qwen Vision OCR | ✅ Tích hợp | URL set trong .env — cần update khi ngrok restart |
| MathPix | ✅ Optional | Key trống → tự skip |
| WebSocket streaming | ✅ Sẵn sàng | Redis pub/sub |
| JWT Auth | ✅ Sẵn sàng | |
| MinIO storage | ✅ Sẵn sàng | Chạy ngoài Docker |
| **OpenAI embedding key** | ❌ Cần cài | `OPENAI_API_KEY=sk-...` chưa có key thật |
| **DB user mismatch** | ⚠️ Cần sửa | docker-compose dùng `examai`, .env dùng `postgres` |
| Celery tasks | ⚠️ Optional | Cần chạy thêm 1 process |
| marker-pdf | ⚠️ Nặng | Tự fallback sang PyMuPDF nếu load fail |

---

## Các vấn đề cần xử lý trước khi chạy ổn định

### 🔴 Bắt buộc:
1. **OpenAI API key cho embedding** — `OPENAI_API_KEY` hiện là `sk-...` placeholder. Embedding sẽ crash nếu upload tài liệu mà không có key thật.

2. **DB mismatch** — Chỉnh 1 trong 2:
   ```dotenv
   # Cách 1: Đổi .env về đúng với docker-compose
   DATABASE_URL=postgresql+asyncpg://examai:examai@localhost:5432/examai
   ```
   ```powershell
   # Cách 2: Tạo DB thủ công
   psql -U postgres -c "CREATE DATABASE curriculum_ai;"
   ```

### 🟡 Khuyến nghị:
3. **Cập nhật ngrok URL Qwen** mỗi lần restart Kaggle notebook:
   ```dotenv
   QWEN_VISION_BASE_URL=https://<new-url>.ngrok-free.app
   ```

4. **Test health check Qwen** sau khi set URL:
   ```powershell
   curl https://ce4d-136-116-250-62.ngrok-free.app/health
   ```

### 🟢 Đã ổn:
- Groq API key có sẵn và hợp lệ
- Pinecone API key có sẵn
- MinIO đang chạy local
- LangFuse observability đã cấu hình
- Qwen Vision client code hoàn chỉnh
