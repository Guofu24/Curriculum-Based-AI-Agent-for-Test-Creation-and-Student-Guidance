# ExamAI – Ready to Run

> Last verified: 2026-04-27

## Services cần chạy trước

- [ ] PostgreSQL :5432 (DATABASE_URL connection)
- [ ] Redis :6379 (REDIS_URL connection)
- [ ] MinIO :9000 (optional — fallback to local S3 if not available)

## Env vars bắt buộc

### Backend (`backend/.env`)

```bash
# Bắt buộc cho AI generation
GROQ_API_KEY=gsk_...           # hoặc OPENAI_API_KEY / ANTHROPIC_API_KEY

# Bắt buộc cho vector search
PINECONE_API_KEY=...

# Kết nối database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/curriculum_ai

# JWT (thay đổi secret trong production)
JWT_SECRET_KEY=your-super-secret-key-change-in-production

# Optional — nếu dùng MinIO thay vì AWS S3
# MINIO_ENDPOINT=localhost:9000
# MINIO_ACCESS_KEY=...
# MINIO_SECRET_KEY=...
```

### Frontend (`Frontend/.env.local`)

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/exam
```

## Startup sequence

### 1. Database migrations
```bash
cd backend
alembic upgrade head
```

### 2. Backend server
```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Celery worker (optional — nếu dùng async generation qua Celery)
```bash
cd backend
celery -A app.tasks.celery_app worker --loglevel=info
```

### 4. Frontend
```bash
cd Frontend
npm install
npm run dev
```

## Verify health

- `GET http://localhost:8000/health` → `{"status": "ok"}`
- `GET http://localhost:8000/ready` → `{"status": "ready"}`
- `GET http://localhost:8000/docs` → Swagger UI
- http://localhost:3000 → Login page loads

## Happy path nhanh

```
1. Register/Login → JWT stored in localStorage
2. Upload PDF/DOCX document → S3 upload → Celery RAG pipeline → document COMPLETED
3. Navigate to /dashboard/generate → chọn document → chọn chương → config exam
4. Start generation → WebSocket events stream → HITL checkpoints
5. Approve blueprint → questions generated → HITL review
6. Submit review → exam completed → export PDF/DOCX
```

## Known limitations

1. **Feedback Store page** — Backend endpoint `GET /exams/feedback-store` trả demo data khi table `feedback_events` trống. Để có real data, cần chạy migration mới để tạo bảng `feedback_events`.

2. **HITL auto-approve mode** — Hiện tại cả 3 checkpoints đều auto-approve để demo nhanh. Để bật manual approval, cần set `AUTO_HITL=false` trong env và đợi user click approve/reject.

3. **Demo mode** — Nếu không có `GROQ_API_KEY` hoặc `document_id` null, hệ thống tự chạy demo mode (local mock questions, không gọi LLM).

4. **LangGraph interrupt** — Hiện tại dùng autoHITL nên không cần interrupt pattern. Nếu muốn manual HITL, cần implement `interrupt()` trong `wait_for_blueprint_approval` và `wait_for_review`.

5. **Alembic migration cần chạy sau khi thêm FeedbackEvent model**:
```bash
cd backend
alembic revision --autogenerate -m "Add feedback_events table"
alembic upgrade head
```

## Dependencies đã verify

Backend (system Python đã test import):
- fastapi, uvicorn, pydantic-settings, sqlalchemy, asyncpg
- redis, celery, langgraph
- groq, openai, anthropic
- sentence-transformers, pinecone-client, boto3
- python-multipart, python-jose, passlib, bcrypt
- python-docx, weasyprint, pymupdf, fitz

Frontend:
- TypeScript strict check: **0 errors**
- All dependencies in `package.json` installed
