# Plan: Backend Curriculum AI Agent - Exam Generator

**Nguồn tham khảo:** `spec_curriculum_ai_agent_new.md` (Technical Blueprint v2.0)  
**Phạm vi:** Viết lại toàn bộ folder `backend/` từ đầu. Frontend đã có.  
**Changelog:** Bổ sung `⚠️ GAP FIX TASKS` (20 điểm thiếu/yếu so với spec v2.0).

---

## Progress Tracker

### ✅ COMPLETED (Phase 7-11: Core Agent System)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Agent output model wiring | DONE | All 4 agents now return typed output models |
| 2 | Planner Agent duplicate class definition | ✅ DONE | Removed duplicate class in `planner.py` |
| 3 | Missing `ExamConfigRequest` schema | ✅ DONE | Added `ExamConfigRequest` + `BloomDistribution` to `schemas/exam.py` |
| 4 | `ExamConfigRequest` bloom_distribution fix | ✅ DONE | Now uses `BloomDistribution` pydantic model for type safety |
| 5 | `BlueprintApprovalRequest` schema | ✅ DONE | Already existed in `schemas/exam.py` |
| 6 | `generation.py` `job_id` parameter fix | ✅ DONE | Removed nonexistent `job_id` from Celery task call |
| 7 | `exam_task.py` parameter mismatch | ✅ DONE | All parameters now optional; `job_id` removed (unused) |
| 8 | `SSEvent` usage in document_task | ✅ DONE | `SSEvent.progress()` and `SSEvent.error()` are static methods, usage is correct |
| 9 | WebSocket streaming endpoint | ✅ DONE | Added `/ws/exam/{exam_id}` to `main.py` |
| 10 | HITL checkpoint endpoints | ✅ DONE | Added `approve-blueprint` + `submit-review` to `exams.py` |
| 11 | `submit_review` method in orchestrator | ✅ DONE | Added to `orchestrator.py` |
| 12 | `auth_service` password_hash field | ✅ DONE | `User` model uses `password_hash`, `auth_service` uses `user.password_hash` — consistent |
| 13 | `ValidatorAgent` duplicate class + `ValidatorOutput` | ✅ DONE | Consolidated class, returns `ValidatorOutput` with all fields |
| 14 | `OutlineAgent` return type | ✅ DONE | Returns `OutlineOutput` with `blueprint` + `distribution_summary` |
| 15 | `BuilderAgent` return type | ✅ DONE | Returns `BuilderOutput` with `questions`, `topics_used`, `chunks_referenced` |

### ✅ COMPLETED (Issue Fixes Round 2)

| # | Task | Status | Notes |
|---|------|--------|-------|
| A | `exam_task.py` asyncio.run() in Celery worker | ✅ DONE | Rewrote with ThreadPoolExecutor pattern. Added `autoretry_for`, `retry_backoff`, `Task.ignore_result=False`. Same fix applied to `document_task.py` |
| B | `generation_router` creates exam after generation | ✅ DONE | Moved `service.create_exam()` BEFORE `orchestrator.generate_exam()` in `_generation_stream_generator()` |
| C | `edit_via_prompt` uses AgentStatus enum instead of string | ✅ DONE | Changed all `AgentStatus.FAILED` → `"failed"` and `AgentStatus.PARTIAL` → `"partial"` in `edit_via_prompt()` and `submit_review()` |
| D | `OrchestratorAgent.__init__` ShortTermMemory initialization | ✅ DONE | Verified `ShortTermMemory` is correctly instantiated in `__init__` with redis client |
| E | `partial_regenerate` exam ID extraction from question_ids | ✅ DONE | Added explicit `exam_id` field to `PartialRegenerateRequest` schema. Changed endpoint to accept `PartialRegenerateRequest` (object with exam_id + edits) instead of `list[PartialEditRequest]` |
| F | `RedisClient` constructor mismatch | ✅ DONE | Updated `RedisClient.__init__()` to accept both `Redis` client instance and URL string |
| G | `exam_task` status check against AgentStatus enum | ✅ DONE | Changed status check to use `result.get('status') == 'success'` string comparison with fallback for enum value |
| H | Alembic migrations setup | ✅ DONE | Created `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, and `001_initial.py` with all 8 tables |

### ✅ COMPLETED (Phase 2: Database Models + Migrations)

| # | Task | Status | Notes |
|---|------|--------|-------|
| P2-1 | Delete `course.py`, no `course_id` FK anywhere | ✅ DONE | `course.py` deleted; `document.py` and `exam.py` rewritten without course FK |
| P2-2 | 6 SQLAlchemy models (SQLAlchemy 2.0 `mapped_column` + `Mapped`) | ✅ DONE | `user.py`, `refresh_token.py`, `document.py`, `exam.py` (with `ExamHistory`), `teacher_preference.py` |
| P2-3 | `001_initial.py` migration (6 tables, JSONB, UUID, no courses) | ✅ DONE | Gộp cả `scope` + `exam_config` vào 001; xóa `002_add_scope_exam_config.py` |
| P2-4 | `migrations/env.py` updated | DONE | Imports only 6 models |

### ✅ COMPLETED (Phase 5: Document Module + RAG Pipeline)

| # | Task | Status | Notes |
|---|------|---------|-------|
| P5-1 | `app/utils/s3.py` | DONE | Added spec-named functions (`upload_file`, `download_file`, `delete_file`) + `generate_fresh_url` alias (G20) |
| P5-2 | `app/rag/parser.py` | DONE | Marker (PDF), python-docx, python-pptx → markdown; `parse_document(file_bytes, file_type) -> {content, page_count}` |
| P5-3 | `app/rag/structure.py` | DONE | `detect_heading_tree` → `{chapters: [{chapter_id: "ch1", title, sections: [{section_id, title, subsections: []}]}]}` |
| P5-4 | `app/rag/extractor.py` | DONE | `extract_formulas` → `[{text_repr, latex_repr, location}]`; `extract_image_description` (GPT-4o Vision, Vietnamese physics) |
| P5-5 | `app/rag/chunker.py` | DONE | `semantic_chunk` → `[{chunk_id, chapter, chapter_id, section, section_id, content_type, page_number, latex_repr, content}]` |
| P5-6 | `app/rag/embedder.py` | DONE | `embed_chunks` with cache key `embed:{doc_id}:{chunk_id}`, TTL 7 days; only embed uncached chunks (G16) |
| P5-7 | `app/rag/vector_store.py` | DONE | `upsert_chunks(doc_id, chapter_id, chunks)`, `query_namespace`, `delete_document_vectors(doc_id, chapters)`; namespace = `{doc_id}_{chapter_id}` |
| P5-8 | `app/routers/documents.py` | DONE | 6 endpoints: upload, list, detail, status, delete, refresh-url (G20) |
| P5-9 | `app/services/document_service.py` | DONE | Full RAG pipeline: parse → structure → chunk → embed (G16 cache) → upsert per chapter → update DB |
| P5-10 | `app/schemas/document.py` | DONE | `DocumentUploadResponse`, `DocumentDetail`, `DocumentStatus`, `RefreshUrlResponse`, heading tree schema |
| P5-11 | `app/models/document.py` | DONE | Aligned with spec: `s3_key`, `processing_status`, `heading_tree`, `total_chapters`; added `parse_error_message`, `total_pages_or_slides`, `total_chunks`; removed `course_id` |
| P5-12 | `migrations/001_initial.py` | DONE | Added `parse_error_message`, `total_pages_or_slides`, `total_chunks` columns to documents table |
| P5-13 | UUID import fixes | DONE | Fixed missing `UUID` import in `exam.py`, `teacher_preference.py` |

### ✅ COMPLETED (Phase 6: Skills Library + Memory Layer + SerpAPI)

| # | Task | Status | Notes |
|---|------|---------|-------|
| P6-1 | `tracer.py` `@tracer.skill_span` decorator | ✅ DONE | Added `skill_span()` and `agent_span()` decorators to `LangFuseTracer`; emit span with input_hash, output_hash, latency_ms, status |
| P6-2 | `skills/bloom_classifier.py` G5 tracer | ✅ DONE | `@get_tracer().skill_span("bloom_classifier")` on `classify()`; added `run()` alias |
| P6-3 | `skills/scope_checker.py` G5 tracer | ✅ DONE | `@get_tracer().skill_span("scope_checker")` on `check()`; added `run()` alias |
| P6-4 | `skills/latex_renderer.py` G5 tracer | ✅ DONE | `@get_tracer().skill_span("latex_renderer")` on `render()` (sync); added `run()` alias |
| P6-5 | `skills/dedup_checker.py` G5 tracer | ✅ DONE | `@get_tracer().skill_span("dedup_checker")` on `check()`; added `run()` alias |
| P6-6 | `skills/difficulty_estimator.py` G5 tracer + G15 fix | ✅ DONE | `@get_tracer().skill_span("difficulty_estimator")` + `BLOOM_SOLUTION_STEPS` default; `solution_steps=None` → auto-map from bloom_level |
| P6-7 | `memory/short_term.py` G2 7 methods + G9 retry_issues | ✅ DONE | Split into separate file; `save_session`, `load_session`, `append_history`, `update_topics`, `increment_retry` + G9: `save_retry_issues(key=retry_issues:{exam_id}, TTL=3600s)`, `load_retry_issues` |
| P6-8 | `memory/long_term.py` G3 2 methods | ✅ DONE | Split into separate file; `get_preferences(user_id)` + `save_preferences(user_id, prefs)` — upsert after approve (G14) |
| P6-9 | `utils/search.py` SerpAPI wrapper G4 | ✅ DONE | `search_similar_problems(query, subject, num_results)` → `[{title, snippet, url}]`; sync call wrapped in `run_in_executor()`; graceful fallback when key not set |
| P6-10 | `utils/__init__.py` export search | ✅ DONE | Added `search_similar_problems` to `__all__` |
| P6-11 | `memory/__init__.py` re-export | ✅ DONE | Re-exported `ShortTermMemory`, `LongTermMemory`, TTL constants |

### ⚠️ REMAINING TASKS

| # | Task | Priority | Notes |
|---|------|---------|-------|
| 1 | Install `alembic` package and run `alembic upgrade head` | HIGH | Ensure alembic is in requirements.txt, then apply migrations. **Phải fix G1 trước** |
| 2 | End-to-end pipeline test | HIGH | Test full flow: auth → upload document → generate exam → stream events → save. **Phải fix G1-G5 trước** |
| 3 | Verify WebSocket streaming in SSE endpoint | MEDIUM | `exam_service.update_questions()` properly saves questions + cost_report |
| 4 | RAG pipeline integration test | MEDIUM | Test `rag/parser.py`, `rag/chunker.py`, `rag/embedder.py`, `rag/vector_store.py` |
| 5 | LangFuse observability integration | LOW | Wire up `observability/tracer.py` to all LLM calls. **Liên quan G5** |
| 6 | Docker Compose setup for local dev | LOW | postgres + redis + celery worker + uvicorn. **Liên quan G18** |

---

## ⚠️ GAP FIX TASKS (Bổ sung từ spec v2.0 review)

> Các task này được phát hiện sau khi đối chiếu kỹ plan với spec v2.0.  
> **🔴 Critical phải hoàn thành TRƯỚC KHI chạy end-to-end test.**

### 🔴 CRITICAL — Pipeline sẽ broken nếu không fix

| # | Task | File cần sửa | Notes |
|---|------|-------------|-------|
| G1 | Xóa `app/models/course.py`, bỏ `course_id` FK khỏi Document + Exam | `models/course.py`, `models/document.py`, `models/exam.py`, migrations | Spec không có Course entity. Deviation này gây migration thừa. Xóa trước khi chạy alembic upgrade |
| G2 | Implement `short_term.py` — 7 methods | `agents/memory/short_term.py` | ✅ DONE | Split into separate file; 7 methods + G9 retry_issues. Key `retry_issues:{exam_id}` TTL 3600s |
| G3 | Implement `long_term.py` — 2 methods | `agents/memory/long_term.py` | ✅ DONE | Split into separate file; `get_preferences()` + `save_preferences()` (upsert, called after approve per G14) |
| G4 | Thêm SerpAPI wrapper | `utils/search.py`, `requirements.txt`, `.env.example` | ✅ DONE | `search_similar_problems()` async wrapper; graceful fallback; `google-search-results` + `SERPAPI_KEY` already present |
| G5 | Wire LangFuse tracer vào Skills Library | `agents/skills/*.py`, `observability/tracer.py` | ✅ DONE | Added `skill_span()` + `agent_span()` decorators to `tracer.py`; all 5 skills decorated with `@get_tracer().skill_span(skill_name)` |

**Schema G2 — short_term.py:**
```python
class ShortTermMemory:
    # Key: session:{exam_id}:{user_id}, TTL 7200s
    async def save_session(self, exam_id, user_id, exam_config, topics_used=None) -> None
    async def load_session(self, exam_id, user_id) -> dict | None
    async def append_history(self, exam_id, user_id, role, content) -> None
    async def update_topics(self, exam_id, user_id, new_topics: list[str]) -> None
    async def increment_retry(self, exam_id, user_id) -> int
    # Key riêng cho retry issues: retry_issues:{exam_id}, TTL 3600s
    async def save_retry_issues(self, exam_id, issues: list[dict]) -> None
    async def load_retry_issues(self, exam_id) -> list[dict]
```

**Schema G4 — utils/search.py:**
```python
async def search_similar_problems(
    query: str, subject: str = "physics", num_results: int = 5
) -> list[dict]:
    # Dùng SerpAPI, wrap synchronous call trong asyncio.get_event_loop().run_in_executor()
    # Return: [{title, snippet, url}]
```

---

### 🟡 IMPORTANT — Tính năng không hoạt động đúng spec

| # | Task | File cần sửa | Notes |
|---|------|-------------|-------|
| G6 | Định nghĩa `_is_complex_request()` trong Orchestrator | `agents/orchestrator.py` | Không có logic → Planner không bao giờ được gọi hoặc luôn được gọi |
| G7 | Hoàn thiện `HitlEvent` payload cho Checkpoint 1 | `websocket/manager.py`, `schemas/agent.py` | `data` phải chứa `blueprint` + `distribution_summary` để frontend render bảng Bloom × Chapter |
| G8 | Implement HITL reject flow | `routers/exams.py`, `services/exam_service.py`, `agents/orchestrator.py` | Chỉ có approve. Reject cần: nhận feedback → gọi lại OutlineAgent → emit blueprint mới |
| G9 | Validator retry — persist issues qua Redis, không in-memory | `agents/validator.py`, `agents/memory/short_term.py` | ✅ DONE | Key `retry_issues:{exam_id}` TTL 3600s; `save_retry_issues()` + `load_retry_issues()` added to `short_term.py` |
| G10 | Parallel retrieval với `asyncio.gather()` + partial failure handling | `agents/retrieval.py` | — | 1 chapter fail không được fail toàn bộ — log warning và tiếp tục với chapters còn lại |
| G11 | Query expansion trong Retrieval Agent | `agents/retrieval.py` | Sinh 3-5 query variants từ bloom_target + chapter bằng GPT-4o-mini. Chưa có implementation |
| G12 | Thêm `include_answers: bool` vào export | `utils/export.py`, `routers/exams.py`, `schemas/exam.py` | Cần 2 bản: học sinh (ẩn đáp án) và giáo viên (hiện đáp án + rubric) |
| G13 | Rate limit trên `POST /exams/generate` | `services/exam_service.py` | Max 10 generate/user/ngày. Redis key: `ratelimit:generate:{user_id}:{date}`, TTL 86400s |
| G14 | Trigger `long_term.save_preferences()` sau approve | `services/exam_service.py`, `agents/orchestrator.py` | Spec cuối luồng 2.8 yêu cầu update long-term memory. Không có trigger nào hiện tại |
| G15 | Fix `solution_steps` input cho `difficulty_estimator_skill` | `agents/skills/difficulty_estimator.py` | ✅ DONE | Added `BLOOM_SOLUTION_STEPS = {"nhan_biet":1, "thong_hieu":2, "van_dung":3, "van_dung_cao":5}`; `solution_steps=None` → auto-map from bloom_level |
| G16 | Verify embedding cache trong `document_task.py` | `tasks/document_task.py`, `rag/embedder.py` | Re-upload cùng doc sẽ re-embed toàn bộ nếu không check cache trước |

**Code G6:**
```python
def _is_complex_request(self, user_prompt: str, exam_config: dict) -> bool:
    signals = [
        len(user_prompt) > 200,
        any(kw in user_prompt for kw in ["tập trung", "thực tế", "ưu tiên", "hạn chế", "tránh"]),
        exam_config.get("extra_instructions") not in (None, ""),
        exam_config.get("bloom_distribution") is not None and len(user_prompt) > 100,
    ]
    return sum(signals) >= 2
```

**Code G7:**
```python
class HitlCheckpoint1Data(BaseModel):
    blueprint: list[BlueprintSlot]
    distribution_summary: dict  # {by_bloom: {...}, by_chapter: {...}}

class HitlEvent(BaseModel):
    type: str = "hitl_checkpoint"
    checkpoint_id: int  # 1 | 2 | 3
    data: HitlCheckpoint1Data | dict
```

**Code G10:**
```python
async def _parallel_query_chapters(self, chapters, query_embedding):
    tasks = [self._query_chapter(ch, query_embedding) for ch in chapters]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    chunks, warnings = [], []
    for ch, result in zip(chapters, results):
        if isinstance(result, Exception):
            warnings.append(f"Chapter {ch} failed: {str(result)}")
            continue
        chunks.extend(result)
    return chunks, warnings
```

**Code G15:**
```python
BLOOM_SOLUTION_STEPS = {
    "nhan_biet": 1, "thong_hieu": 2, "van_dung": 3, "van_dung_cao": 5
}
# Trong DifficultyEstimatorSkill.run():
steps = input.solution_steps or BLOOM_SOLUTION_STEPS.get(input.bloom_level, 2)
```

---

### 🟢 MINOR — Không ảnh hưởng core nhưng thiếu so với spec

| # | Task | File cần sửa | Notes |
|---|------|-------------|-------|
| G17 | Review + gộp migration 002 vào 001 nếu thừa | `migrations/versions/` | `002_add_scope_exam_config.py` có thể thừa nếu `scope` + `exam_config` đã có trong 001 |
| G18 | Docker Compose + quyết định LangFuse self-hosted vs cloud | `docker-compose.yml`, `.env.example` | Spec khuyến nghị self-hosted cho bảo mật dữ liệu giảng viên. Hiện .env dùng cloud URL |
| G19 | WebSocket event replay khi reconnect | `websocket/manager.py` | Lưu events vào Redis list `ws_events:{exam_id}` TTL 3600s; client reconnect replay từ `last_event_id` |
| G20 | Presigned URL refresh endpoint | `utils/s3.py`, `routers/documents.py` | TTL 1h. Thêm `GET /documents/{id}/refresh-url` để tạo presigned URL mới khi hết hạn |

**Code G19:**
```python
async def store_event(self, exam_id: str, event: dict) -> None:
    key = f"ws_events:{exam_id}"
    await self.redis.rpush(key, json.dumps(event))
    await self.redis.expire(key, 3600)

async def replay_events(self, exam_id: str, websocket: WebSocket, from_index: int = 0) -> None:
    events = await self.redis.lrange(f"ws_events:{exam_id}", from_index, -1)
    for event_str in events:
        await websocket.send_text(event_str)
```

---

## 🧹 CLEANUP REPORT (Phase 1–8)

> **Ngày cleanup:** 2026-03-28  
> **Phương pháp:** Theo `spec_curriculum_ai_agent_new.md` + `plan.todo.md` làm source of truth duy nhất  
> **Nguyên tắc:** Không comment code cũ, xóa hoàn toàn code không có trong spec

### Tổng quan

| Metric | Số lượng |
|--------|----------|
| File đã xóa | ~40+ files/dirs |
| File đã viết lại | ~8 files |
| File được giữ nguyên | ~50 files |

### Phase 1 — Xóa root-level directories thừa

```
backend/
├── agents/          ❌ Đã xóa (trùng, code cũ)
├── models/          ❌ Đã xóa (trùng, code cũ)
├── routers/         ❌ Đã xóa (trùng, code cũ)
├── schemas/         ❌ Đã xóa (trùng, code cũ)
├── services/        ❌ Đã xóa (trùng, code cũ)
├── core/            ❌ Đã xóa (trùng, code cũ)
├── utils/           ❌ Đã xóa (trùng, code cũ)
├── legacy/          ❌ Đã xóa (không có trong spec)
├── tests/           ❌ Đã xóa (không có trong spec)
├── docs/            ❌ Đã xóa (không có trong spec)
├── evals/           ❌ Đã xóa (không có trong spec)
├── data/            ❌ Đã xóa (không có trong spec)
└── repositories/    ❌ Đã xóa (không có trong spec)
```

### Phase 2 — Xóa app/ subdirectories không có trong spec

```
app/
├── api/             ❌ Đã xóa (endpoint wrappers, không cần thiết)
├── repositories/    ❌ Đã xóa (DAO layer, SQLAlchemy đủ)
├── services/        ❌ Đã xóa (trùng, chỉ giữ services/ tại app level)
└── (tất cả service sub-folders bên trong đã xóa)
    ├── auth_service/        ❌
    ├── document_service/    ❌
    ├── exam_service/        ❌
    └── generation_service/  ❌
```

### Phase 3 — Xóa app/core/ và app/models/ files thừa

- `app/core/mvp.py` ❌ Xóa
- `app/core/runtime_models.py` ❌ Xóa
- `app/models/curriculum.py` ❌ Xóa
- `app/models/course.py` ✅ Recreated — **⚠️ Cần xóa lại theo G1**

### Phase 4 — Viết lại routers thừa

- `app/routers/courses.py` ❌ Xóa
- `app/routers/generation.py` ❌ Xóa (logic vào exam_task + exam_service)
- `app/routers/playbook.py` ❌ Xóa
- `app/routers/__init__.py` ✅ Viết lại (3 routers: auth, documents, exams)

### Phase 5 — Sửa main.py

- Bỏ import `courses`, `generation`, `playbook` routers
- Bỏ unused `StaticFiles` import
- Chỉ giữ `auth`, `documents`, `exams`

### Phase 6 — Sửa app/utils/security.py

- Xóa Vietnamese encoding corruption
- Sửa import model không tồn tại: `app.models.token_blacklist.TokenBlacklist`
- Sửa config keys sai: `SECRET_KEY` → `JWT_SECRET_KEY`, `ALGORITHM` → `JWT_ALGORITHM`
- Viết lại hoàn toàn, chỉ re-export helpers từ `app/dependencies.py`

### Phase 7 — Cross-reference check cuối

- ✅ Không còn references đến `courses.router`, `generation.router`, `playbook.router`
- ✅ Không còn references đến `TokenBlacklist`
- ✅ Không còn import curriculum model
- ✅ Tất cả `__init__.py` files đều clean

### Cấu trúc hiện tại (target sau Gap Fix)

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── database.py
│   │   └── redis_client.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── refresh_token.py
│   │   ├── document.py          ← ⚠️ Bỏ course_id FK (G1)
│   │   ├── exam.py              ← ⚠️ Bỏ course_id FK (G1)
│   │   ├── exam_history.py
│   │   └── teacher_preference.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── document.py
│   │   ├── exam.py
│   │   └── agent.py             ← ⚠️ Thêm HitlCheckpoint1Data (G7)
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── documents.py         ← ⚠️ Thêm /refresh-url endpoint (G20)
│   │   └── exams.py             ← ⚠️ Thêm reject-blueprint, include_answers (G8, G12)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── document_service.py
│   │   └── exam_service.py      ← ⚠️ Rate limit (G13), save_preferences trigger (G14)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── llm.py
│   │   ├── orchestrator.py      ← ⚠️ _is_complex_request() (G6), reject flow (G8), save_prefs (G14)
│   │   ├── retrieval.py         ← ⚠️ asyncio.gather + query expansion (G10, G11)
│   │   ├── outline.py
│   │   ├── builder.py           ← ⚠️ Wire SerpAPI (G4)
│   │   ├── validator.py         ← ⚠️ Persist issues qua Redis (G9)
│   │   ├── planner.py
│   │   ├── guardrails.py
│   │   ├── skills/
│   │   │   ├── __init__.py
│   │   │   ├── bloom_classifier.py    ← ⚠️ Thêm tracer span (G5)
│   │   │   ├── scope_checker.py       ← ⚠️ Thêm tracer span (G5)
│   │   │   ├── latex_renderer.py      ← ⚠️ Thêm tracer span (G5)
│   │   │   ├── dedup_checker.py       ← ⚠️ Thêm tracer span (G5)
│   │   │   └── difficulty_estimator.py ← ⚠️ Fix solution_steps default (G15)
│   │   └── memory/
│   │       ├── __init__.py
│   │       ├── short_term.py          ← ⚠️ Implement đầy đủ 7 methods (G2)
│   │       └── long_term.py           ← ⚠️ Implement đầy đủ 2 methods (G3)
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── parser.py
│   │   ├── structure.py
│   │   ├── extractor.py
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   └── vector_store.py
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── celery_app.py
│   │   ├── document_task.py     ← ⚠️ Verify embedding cache path (G16)
│   │   └── exam_task.py
│   ├── websocket/
│   │   ├── __init__.py
│   │   └── manager.py           ← ⚠️ Thêm store_event + replay_events (G19)
│   ├── observability/
│   │   ├── __init__.py
│   │   └── tracer.py
│   └── utils/
│       ├── __init__.py
│       ├── s3.py                ← ⚠️ Thêm generate_fresh_url() (G20)
│       ├── export.py            ← ⚠️ Thêm include_answers param (G12)
│       ├── search.py            ← ⚠️ NEW — SerpAPI wrapper (G4)
│       └── security.py
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial.py      ← ⚠️ Gộp 002 vào đây nếu thừa (G17)
├── alembic.ini
├── requirements.txt             ← ⚠️ Thêm google-search-results (G4)
├── .env.example                 ← ⚠️ Thêm SERPAPI_KEY (G4)
├── docker-compose.yml           ← ⚠️ NEW (G18)
└── Dockerfile
```

---

## Các điểm chưa implement theo spec (updated)

| # | Điểm | Ghi chú | Gap Task |
|---|-------|---------|---------|
| 1 | `app/agents/memory/short_term.py` | File rỗng — cần implement đầy đủ | G2 |
| 2 | `app/agents/memory/long_term.py` | File rỗng — cần implement đầy đủ | G3 |
| 3 | SerpAPI web search tool | Hoàn toàn không có | G4 |
| 4 | LangFuse spans cho Skills | Skills không emit trace | G5 |
| 5 | `_is_complex_request()` | Planner không được trigger đúng | G6 |
| 6 | HitlEvent payload | Data chưa rõ, frontend không render được | G7 |
| 7 | HITL reject flow | Chỉ có approve, thiếu reject + rerun Outline | G8 |
| 8 | Validator retry qua Redis | Issues trong RAM, mất khi worker restart | G9 |
| 9 | Parallel retrieval | `asyncio.gather()` + partial failure | G10 |
| 10 | Query expansion | Chưa có implementation | G11 |
| 11 | Export answer key version | Thiếu `include_answers` param | G12 |
| 12 | Rate limit trên generate | Cost runaway risk | G13 |
| 13 | Long-term memory update trigger | `save_preferences()` không bao giờ được gọi | G14 |
| 14 | `difficulty_estimator` solution_steps | Không có input source hợp lý | G15 |
| 15 | Embedding cache verify | Re-upload sẽ re-embed toàn bộ | G16 |

---

## Ghi chú quan trọng

1. **`app/models/course.py`** — ⚠️ **PHẢI XÓA** trước khi chạy alembic upgrade. Xem G1.
2. **Memory Layer** — ⚠️ **PHẢI IMPLEMENT** trước khi test edit-via-prompt. Xem G2, G3.
3. **SerpAPI** — ⚠️ **PHẢI CÓ** trước khi test Builder Agent với van_dung_cao. Xem G4.
4. **`app/routers/generation.py`** — Đã xóa đúng. Logic generation nằm trong `exam_task.py` + `exam_service.py` + `exams.py`. Confirm endpoint `POST /api/v1/exams/generate` có trong `exams.py`.
5. **`app/schemas/course.py`** — Không tồn tại và không cần tạo.
6. **Partial regenerate** — `PartialRegenerateRequest` là tính năng ngoài spec. Nếu giữ cần document rõ hoặc xóa để tránh scope creep.

---

## 1. Project Setup & Core Infrastructure

### 1.1 Folder Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan events, middleware, WebSocket
│   ├── config.py            # Pydantic Settings từ .env
│   ├── database.py          # Async SQLAlchemy engine + session
│   ├── redis_client.py      # Redis connection pool
│   ├── dependencies.py      # FastAPI Depends() reusable
│   ├── models/              # SQLAlchemy ORM
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── document.py
│   │   ├── exam.py
│   │   ├── exam_history.py
│   │   ├── refresh_token.py
│   │   └── teacher_preference.py
│   ├── schemas/             # Pydantic request/response
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── document.py
│   │   ├── exam.py
│   │   └── agent.py
│   ├── routers/             # FastAPI APIRouter
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── documents.py
│   │   └── exams.py
│   ├── services/            # Business logic
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── document_service.py
│   │   └── exam_service.py
│   ├── agents/              # Multi-agent system (CORE)
│   │   ├── __init__.py
│   │   ├── base.py          # AgentStatus, TokenUsage, AgentBaseOutput (Pydantic)
│   │   ├── llm.py           # Shared async OpenAI client + instructor
│   │   ├── orchestrator.py  # Agent 0: điều phối toàn pipeline
│   │   ├── retrieval.py     # Agent 1: truy vấn vector DB
│   │   ├── outline.py       # Agent 2: lập sườn đề
│   │   ├── builder.py       # Agent 3: sinh câu hỏi
│   │   ├── validator.py     # Agent 4: kiểm tra đề
│   │   ├── planner.py       # Planner Agent: dynamic execution plan
│   │   ├── skills/          # Skills Library
│   │   │   ├── __init__.py
│   │   │   ├── bloom_classifier.py
│   │   │   ├── scope_checker.py
│   │   │   ├── latex_renderer.py
│   │   │   ├── dedup_checker.py
│   │   │   └── difficulty_estimator.py
│   │   ├── memory/          # Memory Layer
│   │   │   ├── __init__.py
│   │   │   ├── short_term.py  # Redis session (2h TTL)
│   │   │   └── long_term.py   # PostgreSQL teacher_preferences
│   │   └── guardrails.py    # Output parser, token budget, content filter, scope guard
│   ├── rag/                 # RAG Pipeline
│   │   ├── __init__.py
│   │   ├── parser.py        # Marker (PDF), python-docx, python-pptx
│   │   ├── structure.py     # Heading tree detection
│   │   ├── extractor.py     # Formula (Nougat/MathPix) + Image (GPT-4o Vision)
│   │   ├── chunker.py       # LlamaIndex SemanticSplitter
│   │   ├── embedder.py      # OpenAI embedding + Redis cache
│   │   └── vector_store.py  # Pinecone upsert/query
│   ├── tasks/               # Celery tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py
│   │   ├── document_task.py
│   │   └── exam_task.py
│   ├── websocket/           # WebSocket streaming
│   │   ├── __init__.py
│   │   └── manager.py       # ConnectionManager + Redis pub/sub
│   ├── observability/       # LangFuse tracing
│   │   ├── __init__.py
│   │   └── tracer.py
│   └── utils/
│       ├── __init__.py
│       ├── s3.py            # AWS S3 upload + presigned URL
│       ├── export.py        # PDF (WeasyPrint) + DOCX export
│       ├── search.py        # ⚠️ NEW — SerpAPI wrapper (G4)
│       └── security.py      # JWT + bcrypt helpers
├── migrations/              # Alembic
├── tests/
├── requirements.txt
├── .env.example
└── Dockerfile
```

### 1.2 requirements.txt

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.6.0
pydantic-settings>=2.2.0
sqlalchemy[asyncio]>=2.0.27
asyncpg>=0.29.0
alembic>=1.13.0
redis>=5.0.0
celery>=5.3.6
pinecone-client>=3.0.0
llama-index>=0.10.0
openai>=1.12.0
instructor>=1.0.0
tiktoken>=0.6.0
marker-pdf>=1.0.0
python-docx>=1.1.0
python-pptx>=1.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.9
boto3>=1.34.0
langfuse>=2.0.0
weasyprint>=60.0
httpx>=0.27.0
tenacity>=8.2.0
google-search-results>=2.4.2
```

### 1.3 .env.example

```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/curriculum_ai
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=...
PINECONE_INDEX=curriculum_ai
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-southeast-1
S3_BUCKET_NAME=curriculum-ai-uploads
MATHPIX_APP_ID=...
MATHPIX_APP_KEY=...
SERPAPI_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
JWT_SECRET_KEY=<openssl rand -hex 32>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
```

---

## 2. Database Models & Migrations

### 2.1 SQLAlchemy Models (app/models/)

**user.py** — id (UUID, PK), email (unique), password_hash, full_name, role (default 'teacher'), created_at

**refresh_token.py** — id (UUID, PK), user_id (FK → users), token_hash, expires_at, revoked (bool), created_at

**document.py** — id (UUID, PK), user_id (FK → users), original_filename, file_type (pdf/docx/pptx), s3_key, processing_status (pending/processing/completed/failed), heading_tree (JSONB), total_chapters (int), uploaded_at ⚠️ Không có course_id (G1)

**exam.py** — id (UUID, PK), user_id (FK → users), document_id (FK → documents), title, scope (JSONB), exam_config (JSONB), questions (JSONB), status (draft/published), cost_report (JSONB), total_tokens (int), total_cost_usd (Numeric 10,4), created_at, updated_at ⚠️ Không có course_id (G1)

**exam_history.py** — id (UUID, PK), exam_id (FK → exams), snapshot (JSONB), change_type, change_description, created_at

**teacher_preference.py** — user_id (UUID, PK → users), preferred_bloom_distribution (JSONB), preferred_exam_types (JSONB), subject_focus (varchar), style_notes (text), updated_at

### 2.2 Alembic
- Migration duy nhất: `001_initial.py` — tạo 6 tables, không có courses table
- ⚠️ Gộp 002 vào 001 nếu thừa (G17)
- Handle JSONB columns: `from sqlalchemy.dialects.postgresql import JSONB`

---

## 3. Auth Module

### 3.1 app/services/auth_service.py
- `register(email, password, full_name)` → hash bcrypt, tạo user
- `login(email, password)` → verify, rate limit 5/min/IP qua Redis `ratelimit:login:{ip}`, trả JWT access + refresh tokens
- `refresh(refresh_token)` → rotation: revoke cũ, tạo mới
- `logout(refresh_token)` → revoke trong DB

### 3.2 app/routers/auth.py
- POST `/api/v1/auth/register`
- POST `/api/v1/auth/login`
- POST `/api/v1/auth/refresh`
- POST `/api/v1/auth/logout`

### 3.3 JWT Strategy
- Access token: JWT HS256, TTL 15 phút
- Refresh token: opaque hash trong DB, TTL 7 ngày, rotation enabled

### 3.4 app/dependencies.py
- `get_current_user()`: decode JWT → user object
- `get_db()`: async SQLAlchemy session
- `get_redis()`: Redis connection

---

## 4. Document Module (RAG Pipeline)

### 4.1 app/routers/documents.py
- POST `/api/v1/documents/upload` → upload S3 → tạo DB record → trigger Celery task
- GET `/api/v1/documents` → list user's documents
- GET `/api/v1/documents/{id}` → chi tiết + heading_tree
- GET `/api/v1/documents/{id}/status` → processing status
- DELETE `/api/v1/documents/{id}` → xóa DB + S3 + Pinecone vectors
- ⚠️ GET `/api/v1/documents/{id}/refresh-url` → tạo presigned URL mới (G20)

### 4.2 app/utils/s3.py
- `upload_file(file, user_id)` → S3 private bucket, return s3_key
- `generate_presigned_url(s3_key, TTL=3600)`
- `delete_file(s3_key)`
- ⚠️ `generate_fresh_url(s3_key)` → alias cho refresh endpoint (G20)

### 4.3 app/rag/parser.py
- `parse_document(file_bytes, file_type)`:
  - PDF (text/scan): Marker — giữ heading, table, formula, OCR
  - DOCX: python-docx — heading levels, tables
  - PPTX: python-pptx — slide title = heading
- Return: markdown string với heading tags

### 4.4 app/rag/structure.py
- `detect_heading_tree(markdown_content)`: regex + heading tags → nested tree
- Gán chapter_id, section_id, subsection_id
- Return: heading_tree JSON

### 4.5 app/rag/extractor.py
- `extract_formulas(text)`: detect LaTeX → parse. Image formula: Nougat → MathPix fallback
- `extract_images(images)`: GPT-4o Vision → text description (Vietnamese physics prompt)

### 4.6 app/rag/chunker.py
- `semantic_chunk(markdown_content, heading_tree, embed_model)`
- LlamaIndex SemanticSplitterNodeParser: buffer_size=1, breakpoint_percentile_threshold=95
- Metadata: chunk_id, document_id, chapter, chapter_id, section, section_id, content_type, page_number, latex_repr

### 4.7 app/rag/embedder.py
- `embed_chunks(chunks)`: text-embedding-3-large
- ⚠️ Cache: Redis key `embed:{doc_id}:{chunk_id}`, TTL 7 days — check cache TRƯỚC khi embed (G16)

### 4.8 app/rag/vector_store.py
- `upsert_namespace(doc_id, chapter_id, chunks)`: Pinecone namespace = `{doc_id}_{chapter_id}`
- `query_namespace(doc_id, chapters, query_embedding, top_k)`: query per-chapter namespace
- `delete_namespace(doc_id)`

### 4.9 app/tasks/document_task.py (Celery)
- `process_document_task(document_id)`:
  1. Download từ S3
  2. Parse (rag/parser.py)
  3. Structure detection (rag/structure.py)
  4. Formula + image extraction (rag/extractor.py)
  5. Chunking (rag/chunker.py)
  6. Embed + upsert Pinecone — ⚠️ dùng embedding cache (G16)
  7. Update DB: processing_status = 'completed'
- ⚠️ Dùng ThreadPoolExecutor, không `asyncio.run()`
- Emit WebSocket status event qua Redis pub/sub

---

## 5. Multi-Agent System (CORE)

### 5.1 app/agents/base.py

```python
class AgentStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    RETRY_NEEDED = "retry"

class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float

class AgentBaseOutput(BaseModel):
    status: AgentStatus
    agent_name: str
    execution_time_ms: int
    token_usage: TokenUsage
    warnings: List[str] = []
    trace_id: str
```

### 5.2 app/agents/llm.py
- Shared async OpenAI client (instructor-powered)
- Model routing: GPT-4o (Orchestrator, Builder), GPT-4o-mini (Planner, Reranker, Outline), GPT-4o/Opus (Validator)
- Auto LangFuse span emission mỗi LLM call

### 5.3 app/agents/skills/ — Skills Library

#### bloom_classifier.py
- Input: `{question_stem, question_type, subject}`
- Output: `{bloom_level, confidence, reasoning}`
- Bloom rubric: nhận biết / thông hiểu / vận dụng / vận dụng cao
- ⚠️ `@tracer.skill_span("bloom_classifier")` (G5)

#### scope_checker.py
- Input: `{question_stem, retrieved_context_ids, scope_chapters}`
- Output: `{in_scope, violation_type, evidence_chunk_ids, confidence}`
- ⚠️ `@tracer.skill_span("scope_checker")` (G5)

#### latex_renderer.py
- Input: `{raw_formula, context}`
- Output: `{latex, display_latex, unicode_fallback}`
- Dùng regex rules, không cần LLM
- ⚠️ `@tracer.skill_span("latex_renderer")` (G5)

#### dedup_checker.py
- Input: `{new_question_topic, existing_topics}`
- Output: `{is_duplicate, duplicate_with, similarity_score, suggestion}`
- ⚠️ `@tracer.skill_span("dedup_checker")` (G5)

#### difficulty_estimator.py
- Input: `{question_stem, bloom_level, solution_steps}`
- Output: `{difficulty_score: 0.0-1.0, estimated_solve_time_minutes, complexity_factors}`
- ⚠️ `solution_steps` default từ bloom_level nếu None: `{nhan_biet:1, thong_hieu:2, van_dung:3, van_dung_cao:5}` (G15)
- ⚠️ `@tracer.skill_span("difficulty_estimator")` (G5)

### 5.4 app/agents/memory/

#### short_term.py (Redis) — ⚠️ Implement đầy đủ (G2)
- Key: `session:{exam_id}:{user_id}`, TTL 7200s
- Methods: `save_session()`, `load_session()`, `append_history()`, `update_topics()`, `increment_retry()`
- ⚠️ Thêm: `save_retry_issues(exam_id, issues)`, `load_retry_issues(exam_id)` — key: `retry_issues:{exam_id}` TTL 3600s (G9)

#### long_term.py (PostgreSQL) — ⚠️ Implement đầy đủ (G3)
- `get_preferences(user_id)`: load TeacherPreference từ DB
- `save_preferences(user_id, prefs)`: upsert sau exam approve

### 5.5 app/agents/guardrails.py
- **Output Parser**: instructor client + Pydantic model, max_retries=3
- **TokenBudgetGuard**: check trước mỗi LLM call, flush khi <10% budget
- **ContentFilter**: stem > 20 chars, MCQ options unique, correct_answer in options, no answer in stem
- **ScopeGuard**: inline, câu hỏi chỉ dùng allowed_concepts

### 5.6 app/agents/retrieval.py (Agent 1)
- Input: `{document_id, scope_chapters, bloom_targets, query_hints}`
- Flow:
  1. ⚠️ Query expansion: GPT-4o-mini sinh 3-5 query variants (G11)
  2. ⚠️ Parallel sub-queries với `asyncio.gather()` per chapter (G10)
  3. ⚠️ Partial failure: 1 chapter fail → warning, tiếp tục (G10)
  4. LLM reranking: GPT-4o-mini top-20 → top-8
  5. Merge & dedupe
- Output: `{retrieved_chunks, coverage_map}`
- Timeout: 30s, fallback: empty context + warning

### 5.7 app/agents/outline.py (Agent 2)
- Input: `{retrieved_context, exam_config}`
- Logic: bloom % → số câu; phân bổ đều across chapters (không chapter nào > 50%); van_dung_cao ưu tiên chapters nhiều công thức
- Output: `{blueprint, distribution_summary}`
- Timeout: 20s, fallback: default distribution template

### 5.8 app/agents/builder.py (Agent 3)
- Input: `{blueprint, retrieved_context, topics_used, allowed_concepts}`
- Flow: sinh theo chunk 5-10 câu → bloom_classifier → dedup_checker → content_filter
- ⚠️ van_dung_cao: gọi `utils/search.search_similar_problems()` (G4)
- Formula: text + LaTeX song song
- Append topics_used vào Redis short_term memory
- Timeout: 120s per chunk; MCQ: 4 options, 1 correct, 3 distractors

### 5.9 app/agents/validator.py (Agent 4)
- Input: `{questions, exam_config}`
- 3 nhiệm vụ: Answer Checking, Bloom Compliance Check, Scope Violation Check
- ⚠️ Persist issues: `short_term.save_retry_issues(exam_id, issues)` — không in-memory (G9)
- Retry logic: max 3 vòng; Orchestrator gọi lại Builder với issues từ Redis
- Timeout: 60s, fallback: partial validation + manual review flag

### 5.10 app/agents/planner.py (Planner Agent)
- Input: `{user_request_parsed, exam_config, available_tools, constraints}`
- ⚠️ Chỉ gọi khi `_is_complex_request()` return True (G6)
- Output: `{plan, estimated_token_cost, hitl_checkpoint_after_step}`
- GPT-4o-mini; timeout 15s → fallback hardcoded DEFAULT_PLAN

### 5.11 app/agents/orchestrator.py (Agent 0)
- Entry point duy nhất từ API
- ⚠️ `_is_complex_request(user_prompt, exam_config) -> bool` (G6)
- Luồng: Parse & Clarify (≤3 câu hỏi làm rõ) → Load long-term memory → Dispatch (Planner/default) → Execute pipeline → HITL checkpoints → Output
- ⚠️ HITL reject flow: reject + feedback → rerun OutlineAgent (G8)
- ⚠️ `submit_review` approved=True → gọi `long_term.save_preferences()` (G14)
- Streaming: emit plan steps qua WebSocket

---

## 6. Exam Module & API

### 6.1 app/routers/exams.py
- POST `/api/v1/exams/generate` — ⚠️ check rate limit trước (G13) → tạo exam record → trigger Celery
- GET `/api/v1/exams/{id}`
- PATCH `/api/v1/exams/{id}/questions/{qid}` → sửa trực tiếp → snapshot history
- POST `/api/v1/exams/{id}/edit-prompt` → load Redis → Orchestrator
- POST `/api/v1/exams/{id}/approve-blueprint`
- ⚠️ POST `/api/v1/exams/{id}/reject-blueprint` → reject + feedback (G8)
- POST `/api/v1/exams/{id}/regenerate`
- POST `/api/v1/exams/{id}/export` — ⚠️ với `include_answers: bool` (G12)
- GET `/api/v1/exams`
- GET `/api/v1/exams/history/{id}`
- POST `/api/v1/exams/history/{id}/restore/{history_id}`
- WS `/api/v1/exams/stream/{job_id}`

### 6.2 app/services/exam_service.py
- `create_exam`, `get_exam`, `update_question`, `prompt_edit`, `regenerate_exam`
- `export_exam(exam_id, format, include_answers)` — ⚠️ (G12)
- `list_exams`, `get_history`, `restore_snapshot`
- ⚠️ `check_generate_rate_limit(redis, user_id)` — max 10/user/ngày, key: `ratelimit:generate:{user_id}:{date}` (G13)

### 6.3 app/tasks/exam_task.py (Celery)
- `generate_exam_task(exam_config)`:
  1. Load exam record từ DB
  2. Orchestrator: execute full pipeline
  3. Emit WebSocket events qua Redis pub/sub
  4. Save result + cost_report vào DB
  5. Update exam status
- ⚠️ Dùng ThreadPoolExecutor, không `asyncio.run()`
- Auto-retry: max 3 lần

---

## 7. WebSocket Streaming

### 7.1 app/websocket/manager.py
- ConnectionManager: connect, disconnect, emit, broadcast
- Redis pub/sub: subscribe `exam:{exam_id}` channel
- ⚠️ `store_event(exam_id, event)` — lưu vào `ws_events:{exam_id}` TTL 3600s (G19)
- ⚠️ `replay_events(exam_id, websocket, from_index)` — gọi khi client reconnect (G19)

### 7.2 Event Types

```python
PlanStepEvent:   {type: "plan_step", message, step, total_steps}
QuestionEvent:   {type: "question_generated", question_id, question}
ValidationEvent: {type: "validation_result", passed, issues_count}
CompletedEvent:  {type: "completed", exam_id, total_cost_usd}
ErrorEvent:      {type: "error", message, agent}
# ⚠️ HitlEvent Checkpoint 1 phải có blueprint + distribution_summary (G7)
HitlEvent:       {type: "hitl_checkpoint", checkpoint_id: int, data: {blueprint, distribution_summary} | dict}
```

---

## 8. Export Module

### 8.1 app/utils/export.py
- ⚠️ `export_to_pdf(exam_data, include_answers: bool = False)` (G12):
  - WeasyPrint HTML → PDF
  - `include_answers=False` → ẩn correct_answer, explanation (bản học sinh)
  - `include_answers=True` → hiện đáp án + rubric (bản giáo viên)
- ⚠️ `export_to_docx(exam_data, include_answers: bool = False)` (G12):
  - python-docx; heading styles, numbered lists
  - Tương tự include_answers logic

---

## 9. Observability (LangFuse)

### 9.1 app/observability/tracer.py
- LangFuseTracer wrapper
- `agent_span(agent_name)` decorator — emit span cho mỗi agent call
- ⚠️ `skill_span(skill_name)` decorator — emit sub-span cho mỗi skill call (G5)
- Emit: span_name, agent, input_hash, output_hash, latency_ms, token_usage, model, estimated_cost_usd, status
- Trace root: `exam_generate_{exam_id}` → agent spans → skill sub-spans

### 9.2 Cost Tracking
- ExamCostReport: total_tokens, total_cost_usd, breakdown per agent, model_used
- Lưu vào `exams.cost_report` (JSONB)

---

## 10. HITL Checkpoints

### 10.1 Checkpoint 1: Blueprint Review
- Sau Outline Agent → emit HitlEvent với `{blueprint, distribution_summary}` (G7)
- POST `/api/v1/exams/{id}/approve-blueprint` → `{approved: true}`
- ⚠️ Reject flow: `{approved: false, feedback: "..."}` → rerun OutlineAgent với feedback (G8)

### 10.2 Checkpoint 2: Full Review Screen
- Render all questions + Bloom chart + chat panel
- Inline edit (PATCH endpoint)
- Prompt edit (POST edit-prompt)
- Hiển thị cost report (token, USD)

### 10.3 Checkpoint 3: Export Preview
- Render preview trong browser
- Confirm → export với `include_answers` param (G12)

---

## Thứ tự triển khai (Updated — bao gồm Gap Fixes)

> Items có `[G#]` là gap fix tasks bắt buộc. Thực hiện đúng thứ tự để tránh dependency conflict.

| Phase | Task | Gap Fix |
|---|---|---|
| **0 — Pre-flight** | Xóa `course.py`, clean FK, gộp migration 001+002 | G1, G17 |
| 1 | Project setup | G4 |
| 2 | SQLAlchemy models | G1 |
| 3 | Auth module | DONE |
| 4 | Redis client + core dependencies | DONE |
| 5 | Document module: S3, RAG pipeline | DONE |
| **5.1** | Verify embedding cache path trong document_task | DONE |
| 6 | Celery setup + document_task (ThreadPoolExecutor) | — |
| 7 | Skills Library (5 skills + tracer spans + difficulty_estimator fix) | G5, G15 |
| 8 | Memory Layer: short_term (7 methods) + long_term (2 methods) | G2, G3 |
| 9 | Agent base + LLM client (model routing) + guardrails | — |
| **9.1** | utils/search.py SerpAPI wrapper | G4 |
| 10 | Individual agents: Retrieval, Outline, Builder, Validator, Planner | — |
| **10.1** | Retrieval: asyncio.gather() parallel + query expansion | G10, G11 |
| **10.2** | Builder: wire SerpAPI search cho van_dung_cao | G4 |
| **10.3** | Validator: persist retry issues qua Redis | G9 |
| 11 | Orchestrator: full pipeline integration | — |
| **11.1** | Orchestrator: `_is_complex_request()` heuristic | G6 |
| **11.2** | Orchestrator: HITL reject flow + rerun Outline với feedback | G8 |
| **11.3** | Orchestrator: trigger `save_preferences()` sau approve | G14 |
| 12 | Exam API: routers/exams + exam_service | — |
| **12.1** | Rate limit POST /exams/generate | G13 |
| **12.2** | Export: include_answers param cho PDF + DOCX | G12 |
| **12.3** | Documents: GET /documents/{id}/refresh-url endpoint | G20 |
| 13 | Celery exam_task + Orchestrator integration (ThreadPoolExecutor) | — |
| 14 | WebSocket streaming: manager.py | — |
| **14.1** | WebSocket: store_event + replay_events từ Redis | G19 |
| **14.2** | WebSocket: HitlEvent payload đầy đủ với blueprint data | G7 |
| 15 | LangFuse tracing + cost tracking toàn bộ pipeline | — |
| **16** | Export PDF/DOCX: export.py với WeasyPrint + python-docx | **✅ DONE** |
| 17 | HITL checkpoints + review flow hoàn chỉnh | — |
| **17.1** | Docker Compose: postgres + redis + celery + uvicorn | G18 |
| 18 | End-to-end integration test
---
## Phase 6 — Skills Library + Memory Layer + SerpAPI
**Status: ✅ DONE**
Phase 5 sẵn sàng

**Đã hoàn thành:**
- ✅ tracer.py: `@tracer.skill_span` + `@tracer.agent_span` decorators cho mọi skill/agent call
- ✅ skills/bloom_classifier.py: `@get_tracer().skill_span("bloom_classifier")`
- ✅ skills/scope_checker.py: `@get_tracer().skill_span("scope_checker")`
- ✅ skills/latex_renderer.py: `@get_tracer().skill_span("latex_renderer")`
- ✅ skills/dedup_checker.py: `@get_tracer().skill_span("dedup_checker")`
- ✅ skills/difficulty_estimator.py: `@get_tracer().skill_span("difficulty_estimator")` + G15 `BLOOM_SOLUTION_STEPS` default
- ✅ memory/short_term.py: 7 G2 methods + G9 `retry_issues:{exam_id}` TTL 3600s
- ✅ memory/long_term.py: G3 `get_preferences()` + `save_preferences()` (upsert sau approve)
- ✅ utils/search.py: G4 SerpAPI async wrapper `search_similar_problems()`
- ✅ requirements.txt: `google-search-results` đã có
- ✅ .env.example: `SERPAPI_KEY` đã có

**Điểm dễ sai đã tránh:**
- ✅ `@tracer.skill_span` emit đúng span cho mỗi skill call (input_hash, output_hash, latency_ms, status)
- ✅ `retry_issues` key: `retry_issues:{exam_id}` TTL 3600s
- ✅ `save_preferences()` chỉ được gọi SAU khi user approve blueprint (G14 — trigger trong orchestrator/approve endpoint)
- ✅ `difficulty_estimator` dùng `BLOOM_SOLUTION_STEPS` làm default cho `solution_steps`

---

## Phase 7 — Individual Agents + Orchestrator Wiring

**Phase 6 sẵn sàng:** Skills, Memory, SerpAPI đã xong

**Nhiệm vụ:**

**app/agents/base.py** — kiểm tra + bổ sung nếu thiếu
- `AgentStatus`, `TokenUsage`, `AgentBaseOutput` (Pydantic) — đã có
- Thêm `AgentSkillInput/Output` base models nếu cần

**app/agents/orchestrator.py** — G6, G8, G14
- `_is_complex_request(user_prompt, exam_config) -> bool` (G6)
- HITL reject flow: `reject_blueprint(exam_id, feedback)` → gọi lại `OutlineAgent` với feedback (G8)
- `submit_review(approved=True)` → gọi `long_term.save_preferences()` (G14)
- Wire `builder.py` → `utils/search.search_similar_problems()` cho van_dung_cao (G4)

**app/agents/retrieval.py** — G10, G11
- `_parallel_query_chapters(chapters, query_embedding)` với `asyncio.gather()` + partial failure (G10)
- Query expansion: GPT-4o-mini sinh 3-5 query variants từ bloom_target + chapter (G11)
- `asyncio.gather(*tasks, return_exceptions=True)` → log warning cho failed chapters, continue

**app/agents/builder.py** — G4, G5
- Wire `utils/search.search_similar_problems()` cho van_dung_cao questions
- Các skill calls: `bloom_classifier.run()`, `dedup_checker.run()`, `difficulty_estimator.run()`, `latex_renderer.run()`
- Thêm `@tracer.agent_span("builder_agent")` decorator

**app/agents/validator.py** — G9
- Thay in-memory issues → `short_term.save_retry_issues(exam_id, issues)`
- Load issues: `short_term.load_retry_issues(exam_id)`
- Max 3 retry loops với retry_issues persistence

**app/agents/outline.py** — G5
- `@tracer.agent_span("outline_agent")` decorator
- Returns `OutlineOutput` với `blueprint` + `distribution_summary`

**app/agents/planner.py** — G6
- Chỉ gọi khi `_is_complex_request()` return True
- GPT-4o-mini; timeout 15s → fallback `DEFAULT_PLAN`

**app/agents/guardrails.py** — kiểm tra implementation
- `OutputParser`: instructor client + Pydantic model, max_retries=3
- `TokenBudgetGuard`: check trước mỗi LLM call
- `ContentFilter`: stem > 20 chars, MCQ options unique, correct_answer in options
- `ScopeGuard`: inline, câu hỏi chỉ dùng allowed_concepts

**app/agents/llm.py** — kiểm tra model routing
- GPT-4o (Orchestrator, Builder), GPT-4o-mini (Planner, Reranker, Outline), GPT-4o (Validator)
- Auto LangFuse span emission mỗi LLM call

**Điểm dễ sai:**
- `_is_complex_request()` phải return True khi `sum(signals) >= 2` (G6)
- HITL reject: gọi `outline_agent.run()` với `user_feedback` context (G8)
- `save_preferences()`: extract từ `exam_config` sau khi user approve blueprint (G14)
- Retrieval parallel: `asyncio.gather()` với `return_exceptions=True`, log warning cho Exception (G10)
- Validator retry: dùng `short_term.load_retry_issues()` trước khi gọi Builder (G9)

**Khi xong xuất prompt Phase 8**

---

## Phase 16 — Export PDF/DOCX

**Status: ✅ DONE**
Phase 15 sẵn sàng: LangFuse tracing + cost tracking hoạt động

**Đã hoàn thành:**

**app/utils/export.py — ExamExporter class:**
- `ExamExporter.__init__(exam_service)` — nhận ExamService instance
- `export_pdf(exam_id, include_answers=False, include_blueprint=False)` — async, trả bytes
  - G12: `include_answers=False` → bản học sinh; `True` → bản giáo viên (answer key ở cuối)
  - `include_blueprint=True` → bảng phân bổ Bloom ở đầu file
  - Size guard: reject nếu PDF > 10MB
- `export_docx(exam_id, include_answers=False)` — async, trả bytes
  - G12: tương tự, answer key ở cuối DOCX (page break trước)
- `_render_html(exam, questions, blueprint, include_answers, include_blueprint)`
  - Vietnamese font: Noto Sans via Google Fonts CDN + DejaVu Sans fallback
  - MCQ + Essay sections riêng biệt
  - Options hỗ trợ cả dict {A, B, C, D} và list-of-dict [{label, text}, ...]
  - `_render_blueprint_table(blueprint)` — bảng 6 cột: Chương, Nhận biết, Thông hiểu, Vận dụng, Vận dụng cao, Tổng
  - `_render_answer_key(questions)` — answer key table cho cả MCQ và Essay, page-break trước
  - LaTeX handling: `$...$` → `<em>...</em>` (PDF), strip delimiters (DOCX)
- `_build_docx(exam, questions, include_answers)` + helper methods
  - python-docx Document với heading, paragraph, table cho answer key
  - MCQ: bullet list với List Bullet style; đáp án đúng in green bold
  - Essay: rubric table; answer key ở cuối với page break
- Legacy standalone functions `export_exam_to_pdf()` và `export_exam_to_docx()` giữ nguyên

**app/routers/exams.py — Export Endpoints:**
- `GET /{exam_id}/export/pdf?include_answers=false&include_blueprint=false`
  - StreamingResponse với `Content-Length` header
  - Filename: `{title}_{exam_id}.pdf`
  - 404 check + ExamServiceError → HTTP 400
- `GET /{exam_id}/export/docx?include_answers=false`
  - Tương tự, filename `.docx`
- Đã xóa `POST /export` cũ (dùng `ExportFormat` body)
- Đã xóa unused `ExportFormat` import

**requirements.txt:**
- `weasyprint>=60.0` ✅ (đã có)
- `python-docx>=1.1.0` ✅ (đã có)

**Điểm dễ sai đã tránh:**
- ✅ G12: `include_answers` param có trong cả PDF và DOCX export
- ✅ HTML template dùng Noto Sans (Google Fonts CDN) + DejaVu Sans fallback cho tiếng Việt
- ✅ WeasyPrint font: `@import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;700&display=swap')` trong CSS
- ✅ DOCX export giữ đúng formatting: MCQ bullet list, đáp án green bold, Essay rubric table
- ✅ Size limit: 10MB check trước khi trả bytes cho cả PDF và DOCX
- ✅ Options format: hỗ trợ cả dict và list-of-dict

---

## Phase 17 — HITL Checkpoints + Review Flow Hoàn Chỉnh

Phase 16 sẵn sàng: PDF/DOCX export với ExamExporter hoạt động

**Mục tiêu:** Hoàn thiện HITL review flow — 3 checkpoint, inline edit, export preview

### 17.1 Checkpoint 1: Blueprint Review (`/approve-blueprint`, `/reject-blueprint`)
- Đã có: `approve_blueprint()` → set Redis key `hitl:approved:{exam_id}:1`
- Cần thêm: `reject_blueprint()` → gọi OutlineAgent lại với feedback
  - Lưu feedback vào Redis: `hitl:feedback:{exam_id}:1`
  - Trigger re-run outline với `user_feedback` context

### 17.2 Checkpoint 2: Full Review Screen
- `GET /{exam_id}/review-data` → trả về:
  ```json
  {
    "exam": {...},
    "questions": [...],
    "blueprint": {...},
    "quality_scores": [...],
    "cost_report": {...},
    "feedback_events": [...]
  }
  ```
- Inline edit: `PATCH /{exam_id}/questions/{question_id}` (đã có trong routers/exams.py)
- Prompt edit: `POST /{exam_id}/edit-prompt` (đã có)
- Cost report display: đọc từ `exam.cost_report`

### 17.3 Checkpoint 3: Export Preview + Confirm
- Preview: `GET /{exam_id}/preview` → trả về HTML render của đề (không phải PDF)
  - Dùng `_render_html()` từ ExamExporter nhưng không gọi `write_pdf()`
  - Trả về `<html string>` với `Content-Type: text/html`
- Confirm → export: gọi `GET /{exam_id}/export/pdf?include_answers=true/false`

### 17.4 app/routers/exams.py — Review Endpoints
```python
@router.get("/{exam_id}/review-data")
async def get_review_data(exam_id: UUID, ...):
    """Return full data needed for HITL review screen."""
    service = ExamService(db, redis)
    exam = await service.get_exam(exam_id, current_user.id)
    return {
        "exam": _exam_to_detail(exam),
        "blueprint": exam.blueprint,
        "quality_scores": exam.quality_scores,
        "cost_report": exam.cost_report,
        "feedback_events": [...],
    }

@router.get("/{exam_id}/preview")
async def export_preview(exam_id: UUID, include_answers: bool = False, ...):
    """Return HTML preview of exam (no PDF conversion)."""
    service = ExamService(db, redis)
    exporter = ExamExporter(service)
    # Reuse HTML rendering without PDF conversion
    exam = await service.get_exam(exam_id, current_user.id)
    questions = exam.questions or []
    blueprint = exam.blueprint or {}
    html = exporter._render_html(exam, questions, blueprint, include_answers, False)
    return HTMLResponse(content=html, media_type="text/html")

@router.post("/{exam_id}/reject-blueprint")
async def reject_blueprint(exam_id: UUID, request: BlueprintRejectionRequest, ...):
    """
    G8: Re-generate outline with HITL feedback.
    Pass feedback → Orchestrator → OutlineAgent với user_feedback context.
    """
    from app.agents.orchestrator import OrchestratorAgent
    orchestrator = OrchestratorAgent(redis=redis, db_session=db)
    # Save feedback to Redis for re-run
    await redis.set(f"hitl:feedback:{exam_id}:1", request.feedback, ex=86400)
    result = await orchestrator.reject_blueprint(exam_id, feedback)
    return result
```

### 17.5 Điểm dễ sai
- Preview HTML: KHÔNG gọi `write_pdf()`, chỉ trả raw HTML string
- `reject_blueprint()`: phải save feedback vào Redis TRƯỚC khi gọi Orchestrator
- Review screen phải hiển thị cost_report (token, USD) từ `exam.cost_report`
- Inline edit PATCH endpoint phải broadcast qua WebSocket sau khi save

**Khi xong xuất prompt Phase 17.1 (Docker Compose)**
 |