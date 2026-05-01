# Hướng dẫn chạy hệ thống ExamAI

> **Cập nhật lần cuối:** 2026-04-05
> Dựa trên SYSTEM_SPEC.md và kiểm tra thực tế

---

## Kiến trúc tổng quan

```
Browser (localhost:3000)  ←  Frontend (Next.js 16)
        ↓ HTTP/WSS
Backend (localhost:8000)  ←  FastAPI
        ↓                  ↓          ↓          ↓          ↓
   PostgreSQL          Redis       MinIO     Pinecone    Groq API
  (port 5432)        (port 6379) (port 9000)  (cloud)    (internet)
```

---

## 1. Cài đặt PostgreSQL

### Windows (pgAdmin / psql)

```bash
# Tạo database
CREATE DATABASE examai;
CREATE USER examai WITH PASSWORD 'examai';
GRANT ALL PRIVILEGES ON DATABASE examai TO examai;
```

### Docker (nhanh hơn)

```bash
docker run -d \
  --name examai-postgres \
  -e POSTGRES_DB=examai \
  -e POSTGRES_USER=examai \
  -e POSTGRES_PASSWORD=examai \
  -p 5432:5432 \
  postgres:16-alpine
```

**Cập nhật `backend/.env`:**
```env
DATABASE_URL=postgresql+asyncpg://examai:examai@localhost:5432/examai
```

---

## 2. Cài đặt Redis

### Windows

```bash
# Tải Redis for Windows: https://github.com/microsoftarchive/redis/releases
# Hoặc dùng Docker:
docker run -d --name examai-redis -p 6379:6379 redis:7-alpine
```

### Verify Redis

```bash
redis-cli ping
# PONG
```

**Cập nhật `backend/.env`:**
```env
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
```

---

## 3. Cài đặt MinIO (S3-compatible storage)

### Docker

```bash
docker run -d \
  --name examai-minio \
  -p 9000:9000 \
  -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  minio/minio \
  server /data --console-address ":9001"
```

minio.exe server E:\MiNIO --console-address :9001

### Tạo bucket

1. Mở trình duyệt: http://localhost:9001
2. Login: `minioadmin` / `minioadmin`
3. Tạo bucket: `curriculum-ai` (hoặc tên bất kỳ)

**Cập nhật `backend/.env`:**
```env
STORAGE_BACKEND=minio
MINIO_ENDPOINT_URL=http://127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=curriculum-ai
MINIO_PUBLIC_URL=http://127.0.0.1:9000
```

---

## 4. Cài đặt Pinecone (Vector DB)

### Bước 1: Tạo tài khoản

1. Truy cập https://www.pinecone.io
2. Đăng ký free tier
3. Tạo index mới:
   - **Index name:** `examai` (hoặc `curriculum-ai`)
   - **Dimension:** 768 (phù hợp với `paraphrase-multilingual-mpnet-base-v2`)
   - **Metric:** Cosine
   - **Cloud:** AWS
   - **Region:** us-east-1

### Bước 2: Lấy API Key

1. Pinecone Dashboard → API Keys → Create Key
2. Copy Key vào `.env`

**Cập nhật `backend/.env`:**
```env
PINECONE_API_KEY=pcsk_xxxxxxxxxxxxx
PINECONE_INDEX=curriculum-ai
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1
```

---

## 5. Cài đặt Groq API

### Bước 1: Lấy API Key

1. Truy cập https://console.groq.com
2. Đăng ký / Login
3. API Keys → Create Key
4. Copy Key

**Cập nhật `backend/.env`:**
```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_MODEL_STRONG=llama-3.3-70b-versatile
LLM_MODEL_LIGHT=llama-3.1-8b-instant
```

> **Miễn phí:** Groq free tier có limit nhưng đủ để dev/test.

---

## 6. Chạy Database Migrations

```bash
cd backend

# Chạy Alembic migrations
alembic upgrade head
```

Kết quả mong đợi:
```
Running migrations/versions/001_initial.py ... done
Running migrations/versions/bd3064db5e63_add_course_id_to_documents.py ... done
Running migrations/versions/add_file_size_to_documents.py ... done
```

---

## 7. Chạy Backend (FastAPI)

```bash
cd backend

# Cài dependencies (nếu chưa)
pip install -r requirements.txt

# Chạy server
uvicorn app.main:app --reload --port 8000 --host 0.0.0.0
```

### Verify Backend

```bash
# Health check
curl http://localhost:8000/health

# Ready check (kiểm tra DB + Redis + Pinecone)
curl http://localhost:8000/ready

# API docs
# Mở trình duyệt: http://localhost:8000/docs
```

**Expected response `/health`:**
```json
{"status":"healthy"}
```

---

## 8. Chạy Frontend (Next.js)

### Option A: UI cũ (thư mục `UI`)

```bash
cd UI

# Cài dependencies
npm install

# Chạy dev server
npm run dev
```

### Option B: UI mới (thư mục `Frontend`)

```bash
cd Frontend

# Cài dependencies
npm install

# Chạy dev server
npm run dev
```

### Verify Frontend

1. Mở trình duyệt: http://localhost:3000
2. Trang login hiển thị
3. Đăng ký tài khoản → login thành công → redirect dashboard

---

## 9. Chạy Celery Worker (Optional — cho background jobs)

```bash
cd backend

# Chạy worker (terminal riêng)
celery -A app.tasks.celery_app worker --loglevel=info -Q default,celery
```

> **Lưu ý:** Nếu không chạy Celery, generation vẫn hoạt động (chạy inline trong FastAPI),
> nhưng reject blueprint và submit-review sẽ cần worker để dispatch lại.

---

## 10. Cấu hình `.env` hoàn chỉnh

Copy và điền đầy đủ các giá trị:

```env
# ── Application ──────────────────────────────────────────────────────────
APP_NAME=ExamAI
DEBUG=true
APP_BASE_URL=http://localhost:8000

# ── Database ─────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://examai:examai@localhost:5432/examai

# ── Redis ─────────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1

# ── JWT ───────────────────────────────────────────────────────────────────
JWT_SECRET_KEY=YOUR_SECURE_SECRET_KEY_HERE_32_CHARS_MIN
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# ── LLM Provider ──────────────────────────────────────────────────────────
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_MODEL_STRONG=llama-3.3-70b-versatile
LLM_MODEL_LIGHT=llama-3.1-8b-instant
LLM_MODEL_VISION=llama-3.2-11b-vision-preview
LLM_FALLBACK_CHAIN=ollama,g4f

# ── Embeddings (Local — không cần API key) ────────────────────────────────
ST_EMBEDDING_MODEL=paraphrase-multilingual-mpnet-base-v2
ST_EMBEDDING_DIM=768

# ── Pinecone ───────────────────────────────────────────────────────────────
PINECONE_API_KEY=pcsk_xxxxxxxxxxxxx
PINECONE_INDEX=curriculum-ai
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1

# ── Storage (MinIO) ────────────────────────────────────────────────────────
STORAGE_BACKEND=minio
MINIO_ENDPOINT_URL=http://127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=curriculum-ai
MINIO_PUBLIC_URL=http://127.0.0.1:9000

# ── OCR (Optional) ─────────────────────────────────────────────────────────
QWEN_VISION_BASE_URL=  # Để trống nếu không dùng OCR
QWEN_VISION_TIMEOUT=120

# ── LangFuse (Observability — Optional) ───────────────────────────────────
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# ── Agent Settings ─────────────────────────────────────────────────────────
AGENT_MAX_RETRIES=3
AGENT_MAX_VALIDATION_RETRIES=3
AGENT_TIMEOUT_RETRIEVAL=30
AGENT_TIMEOUT_BUILDER=120
MAX_GENERATES_PER_DAY=9999  # Dev mode — production nên đặt 10

# ── RAG Settings ───────────────────────────────────────────────────────────
RAG_TOP_K_PER_CHAPTER=20
RAG_TOP_K_AFTER_RERANK=8
RAG_CHUNK_SIZE=1200
RAG_CHUNK_OVERLAP=200
MAX_CONTEXT_TOKENS=3000
EMBEDDING_CACHE_TTL_SECONDS=604800
```

---

## 11. Kiểm tra end-to-end

### Luồng test hoàn chỉnh

```bash
# 1. Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password123","full_name":"Test Teacher"}'

# 2. Login → lấy token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password123"}'
# Response: {"access_token":"...", "refresh_token":"...", ...}

# 3. Upload document
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@path/to/your/document.pdf"

# 4. Poll document status (đợi completed)
curl http://localhost:8000/api/v1/documents/<DOC_ID>/status \
  -H "Authorization: Bearer <TOKEN>"

# 5. Get curriculum tree
curl http://localhost:8000/api/v1/documents/<DOC_ID>/curriculum-tree \
  -H "Authorization: Bearer <TOKEN>"

# 6. Start generation
curl -X POST http://localhost:8000/api/v1/generate/exam \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "<DOC_ID>",
    "scope": ["Chương 1"],
    "mcq_count": 5,
    "essay_count": 1,
    "bloom_distribution": {
      "nhan_biet": 20,
      "thong_hieu": 30,
      "van_dung": 30,
      "van_dung_cao": 20
    }
  }'

# 7. Get exam
curl http://localhost:8000/api/v1/exams/<EXAM_ID> \
  -H "Authorization: Bearer <TOKEN>"

# 8. Export PDF
curl -O -J http://localhost:8000/api/v1/exams/<EXAM_ID>/export/pdf \
  -H "Authorization: Bearer <TOKEN>"
```

---

## 12. Troubleshooting

### Lỗi thường gặp

**`ModuleNotFoundError: No module named 'psycopg2'`**
```bash
pip install psycopg2-binary
# Hoặc dùng async:
pip install asyncpg
```

**`Connection refused: Redis`**
```bash
# Kiểm tra Redis đang chạy
redis-cli ping
# Nếu PONG → kiểm tra REDIS_URL trong .env
```

**`Connection refused: PostgreSQL`**
```bash
# Kiểm tra PostgreSQL
psql -U examai -d examai -c "SELECT 1"
```

**`Pinecone connection failed`**
```bash
# Kiểm tra API key đúng
# Kiểm tra index tồn tại trên Pinecone dashboard
```

**`Groq rate limit`**
```bash
# Đợi 1 phút hoặc dùng fallback provider
# Thêm vào .env:
LLM_FALLBACK_CHAIN=ollama,g4f
```

**`MinIO: bucket not found`**
```bash
# Tạo bucket trên http://localhost:9001
# Hoặc dùng mc CLI:
mc alias set local http://127.0.0.1:9000 minioadmin minioadmin
mc mb local/curriculum-ai
```

**`CORS error`**
```bash
# Kiểm tra CORS_ORIGINS trong .env
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

---

## 13. Quản lý services

### Quick check script

```bash
# Chạy tất cả services kiểm tra
echo "=== PostgreSQL ===" && PGPASSWORD=examai psql -U examai -d examai -c "SELECT 1" -h localhost 2>&1 | head -3
echo "=== Redis ===" && redis-cli ping 2>&1
echo "=== Backend ===" && curl -s http://localhost:8000/health
echo "=== Frontend ===" && curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
```

### Một lệnh chạy tất cả (tmux/screen)

```bash
# Tạo và chạy tất cả trong tmux
tmux new-session -d -s examai "docker start examai-postgres examai-redis examai-minio"

# Backend
tmux new-window -t examai:1 "cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000"

# Celery (optional)
tmux new-window -t examai:2 "cd backend && source .venv/bin/activate && celery -A app.tasks.celery_app worker --loglevel=info"

# Frontend
tmux new-window -t examai:3 "cd Frontend && npm run dev"
```

---

## Docker Compose (Tất cả trong 1 lệnh)

`backend/docker-compose.yml` đã có sẵn. Chạy:

```bash
cd backend
docker-compose up -d
```

Kiểm tra:
```bash
docker-compose ps
docker-compose logs -f
```

---

## Contacts & Resources

- **API Docs:** http://localhost:8000/docs (Swagger UI)
- **ReDoc:** http://localhost:8000/redoc
- **Frontend:** http://localhost:3000
- **MinIO Console:** http://localhost:9001
- **System Spec:** `SYSTEM_SPEC.md`
- **V0 UI Prompt:** `V0_UI_PROMPT.md`