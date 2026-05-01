# ExamAI – Bug Report & Fix Summary

> Generated: 2026-04-27 (updated 2026-04-27)
> Scope: Backend (FastAPI) + Frontend (Next.js 16)

---

## Tong quan

- Tong so van de phat hien: 17
- Da fix: 16
- Con lai (can them context/API key/service): 1

---

## Cac file da duoc TAO MOI

| File | Ly do tao |
|------|-----------|
| `backend/app/models/feedback_event.py` | Model moi cho quality signals tu AI pipeline. Cho phep luu tru feedback events vao DB thay vi chi Redis. Bao gom SignalType, Severity, ReviewStatus enums |
| `READY_TO_RUN.md` | Huong dan startup nhanh, services can thiet, env vars bat buoc, known limitations |

---

## Cac file da duoc FIX

| File | Van de | Giai phap |
|------|--------|-----------|
| `backend/app/agents/orchestrator.py` | Python syntax error: duplicate initial_state = { | Xoa dong trung lap |
| `backend/app/models/exam.py` | Thieu ExamStatusEnum, thieu truong JSONB, property blueprint trung ten column | Them enum + truong, doi property → blueprint_data, them feedback_events relationship |
| `backend/app/models/user.py` | Thieu UserRole enum | Them enum STUDENT/TEACHER/ADMIN, them feedback_events relationship |
| `backend/app/models/document.py` | Thieu DocumentProcessingStatus enum | Them enum |
| `backend/app/core/redis_client.py` | Khong co graceful degradation khi Redis unavailable | Them in-memory fallback |
| `backend/app/core/config.py` | CORS_ORIGINS chi parse comma-separated | Them cors_origins_list ho tro JSON array + comma-separated |
| `backend/app/main.py` | Parse CORS_ORIGINS bang tay | Doi thanh settings.cors_origins_list |
| `backend/app/agents/graph/nodes/emit_checkpoint_2.py` | Dung sync _emit thay vi _emit_async | Doi thanh await _emit_async() |
| `backend/app/agents/graph/nodes/emit_checkpoint_3.py` | Dung sync _emit thay vi _emit_async | Doi thanh await _emit_async() |
| `backend/app/agents/graph/nodes/finalize_output.py` | Dung sync _emit, unused vars | Doi _emit_async(), loai bo unused |
| `backend/app/schemas/exam.py` | Trung ten QualitySummaryResponse (2 dinh nghia) | Doi class 2 → QualitySummaryV2Response |
| `backend/app/services/exam_service.py` | Import shadowed, stub khong co real data | Xoa unused import, implement real get_feedback_store() voi demo fallback |
| `backend/app/routers/exams.py` | Import khong ton tai sau shadowing fix | Xoa import, them description/resolved mapping, them signal_type filter |
| `backend/app/websocket/manager.py` | store_event khong gioi han so events → unbounded Redis growth | Them LTRIM + pipeline giu max 1000 events |
| `Frontend/lib/api.ts` | processing_status thieu 'indexed' | Them vao union type |
| `Frontend/app/dashboard/feedback/page.tsx` | Dung MOCK data | Thay hoan toan bang feedbackApi.list(), loading/error/refresh states |

---

## Cac van de CHUA FIX (can them context)

| Van de | Ly do chua fix | Huong xu ly goi y |
|--------|----------------|-------------------|
| **HITL auto-approve mode** | Hien tai ca 3 checkpoints deu auto-approve de demo nhanh. Khong co user click handler cho manual approval | Can implement manual HITL: bo auto-approve logic, dung interrupt() that su trong wait_for_blueprint_approval va wait_for_review |

---

## Chi tiet bugs da fix

### 1. orchestrator.py – Duplicate initial_state
**File:** `backend/app/agents/orchestrator.py`
**Van de:** Co 2 dong `initial_state = {` lien nhau, dong thu 2 la incomplete. Python syntax error.
**Fix:** Xoa dong `initial_state = {` thua.

### 2. models/exam.py – Thieu enums va truong
**File:** `backend/app/models/exam.py`
**Van de:** Thieu ExamStatusEnum (11 trang thai), thieu blueprint/checkpoint_state/generation_metadata/quality_metrics columns, property blueprint trung ten column.
**Fix:** Them ExamStatusEnum, thieu enum, doi property → blueprint_data, them feedback_events relationship.

### 3. models/user.py – Thieu role enum
**File:** `backend/app/models/user.py`
**Fix:** Them UserRole(str, Enum) voi STUDENT/TEACHER/ADMIN, them feedback_events relationship.

### 4. models/document.py – Thieu ProcessingStatus enum
**File:** `backend/app/models/document.py`
**Fix:** Them DocumentProcessingStatus(str, Enum).

### 5. redis_client.py – Thieu graceful degradation
**File:** `backend/app/core/redis_client.py`
**Van de:** Neu Redis unavailable, moi operation raise exception. Khong fallback.
**Fix:** Them _using_fallback flag, _fallback dict (thread-safe), _mark_fallback() method.

### 6. emit_checkpoint_2/3 – Sync _emit thay vi async
**Files:** emit_checkpoint_2.py, emit_checkpoint_3.py
**Van de:** _emit() khong await → event co the chua gui kip truoc interrupt.
**Fix:** await _emit_async().

### 7. finalize_output.py – Sync _emit va unused vars
**File:** emit_checkpoint_finalize_output.py
**Fix:** await _emit_async(), loai bo unused variables.

### 8. config.py – CORS_ORIGINS parsing
**File:** `backend/app/core/config.py`
**Fix:** Them cors_origins_list property ho tro JSON array + comma-separated.

### 9. schemas/exam.py – Duplicate QualitySummaryResponse
**File:** `backend/app/schemas/exam.py`
**Fix:** Doi class thu 2 → QualitySummaryV2Response.

### 10. Service/router – Shadowed import
**Files:** exam_service.py, routers/exams.py
**Fix:** Xoa unused import, implement real get_feedback_store().

### 11. WebSocket store_event unbounded growth
**File:** `backend/app/websocket/manager.py`
**Van de:** Redis LIST ws_events:{exam_id} khong co gioi han → memory leak.
**Fix:** Them LTRIM + pipeline giu max 1000 events.

### 12. Frontend TS – Missing indexed status
**File:** `Frontend/lib/api.ts`
**Fix:** Them 'indexed' vao processing_status union type.

### 13. Feedback page – MOCK data
**File:** `Frontend/app/dashboard/feedback/page.tsx`
**Van de:** Dung MOCK_FEEDBACK hardcoded thay vi goi API.
**Fix:** Thay hoan toan bang feedbackApi.list() voi loading/error/refresh states.

---

## Integration Checks Results

### API Contract (Backend ↔ Frontend)

| Endpoint | Status | Ghi chu |
|----------|--------|---------|
| POST /auth/register | OK | |
| POST /auth/login | OK | |
| POST /auth/refresh | OK | |
| POST /auth/logout | OK | |
| GET /auth/me | OK | |
| POST /documents/upload | OK | |
| GET /documents/ | OK | |
| GET /documents/{id}/status | OK | |
| GET /documents/{id}/curriculum-tree | OK | |
| DELETE /documents/{id} | OK | |
| POST /documents/{id}/reprocess | OK | |
| POST /documents/{id}/rescan-structure | OK | |
| PATCH /documents/{id}/curriculum-tree | OK | |
| POST /generate/exam | OK | |
| POST /generate/partial-regenerate | OK | |
| POST /exams/generate | OK | Rate limit 10/day |
| GET /exams/ | OK | |
| GET /exams/{id} | OK | |
| PATCH /exams/{id}/questions/{qid} | OK | |
| POST /exams/{id}/approve-blueprint | OK | |
| POST /exams/{id}/reject-blueprint | OK | |
| POST /exams/{id}/submit-review | OK | |
| GET /exams/{id}/review-data | OK | |
| GET /exams/{id}/export/pdf | OK | |
| GET /exams/{id}/export/docx | OK | |
| GET /exams/quality-summary | OK | |
| GET /exams/feedback-store | OK | NEW - real API |

### WebSocket Contract

| Event (BE → FE) | Handler | Status |
|----------------|---------|--------|
| plan_step | OK | Khop |
| question_generated | OK | Khop |
| hitl_checkpoint | OK | Khop (checkpoint_id 1/2/3) |
| validation_result | OK | Khop |
| completed | OK | Khop |
| pipeline_paused | OK | Khop |

### Environment Variables

| File | Status |
|------|--------|
| Frontend/.env.local | OK |
| backend/.env.example | OK |
| backend/.env | OK |

---

## Runtime Trap Analysis

### Phase 4A: Celery + Async
OK - Ca exam_task.py va document_task.py deu dung asyncio.run() / loop.run_until_complete().

### Phase 4B: LangGraph HITL Pattern
OK - emit_checkpoint_1/2/3 deu await _emit_async() truoc interrupt. autoHITL mode hien tai bo qua manual approval.

### Phase 4C: JSONB Mutation
OK - update_questions() va update_question() deu dung list() copy + full reassignment.

### Phase 4D: Missing Await
OK - Tat ca db/redis calls deu co await.

### Phase 4E: Pinecone Namespace
OK - _make_ascii_namespace() sanitize tieng Viet + special chars. Batch upserts 100/batch. Graceful degradation.

### Phase 4F: WebSocket Race
OK - emit() luu event vao Redis truoc khi gui. Disconnect catch. LTRIM da duoc them.

### Phase 4G: JWT Edge Cases
OK - Refresh token rotation dung, revoked flag trong DB.

---

## Huong dan chay du an

### Buoc 1: Setup services
Docker Compose: PostgreSQL :5432, Redis :6379, MinIO :9000 (optional)

### Buoc 2: Backend
```bash
cd backend
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Buoc 3: Frontend
```bash
cd Frontend
npm install
npm run dev
```

### Buoc 4: Celery (optional)
```bash
celery -A app.tasks.celery_app worker --loglevel=info
```

### Can thiet
- GROQ_API_KEY hoac OPENAI_API_KEY cho AI generation
- PINECONE_API_KEY cho vector search
- DATABASE_URL, REDIS_URL, JWT_SECRET_KEY

---

## Verify health

- GET http://localhost:8000/health → {"status": "ok"}
- GET http://localhost:8000/ready → {"status": "ready"}
- http://localhost:3000 → Login page

---

## Frontend Type Check

```bash
cd Frontend
npx tsc --noEmit
# Exit 0 - Khong co type errors
```
