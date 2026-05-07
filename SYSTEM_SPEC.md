# ExamAI System Spec

Last repo scan: 2026-05-07

This file is the handoff spec for another AI or engineer. It describes the actual codebase, not only the README intent. When this spec conflicts with code, inspect the referenced module and prefer the implementation.

## 1. Product Goal

ExamAI is a full-stack system for Vietnamese teachers to generate physics test papers from teaching materials or from admin-uploaded textbook knowledge. The system combines:

- Document ingestion: upload PDF/DOCX/PPTX, parse to Markdown, detect curriculum structure, chunk, embed, and index into Pinecone.
- Multi-agent exam generation: retrieve knowledge, create a blueprint, generate questions, validate quality, and pause for human review.
- Human-in-the-loop control: teachers approve or reject the blueprint, review generated questions, edit/regenerate questions, then export.
- Real-time progress: frontend follows generation and document processing through WebSocket events.
- Persistence and memory: PostgreSQL stores users, documents, exams, exam history, feedback events, teacher preferences, and textbook knowledge. Redis stores sessions, rate limits, WebSocket replay events, retry state, and HITL approval flags.

The target user is a teacher. The core quality goals are strict scope grounding, correct Bloom taxonomy distribution, good distractors, answer correctness, LaTeX support, and export-ready PDF/DOCX output.

## 2. Repo Layout

Root:

- `README.md`: high-level product overview.
- `CLAUDE.md`: coding behavior guidelines for AI agents.
- `SYSTEM_SPEC.md`: this handoff spec.
- `Frontend/`: Next.js app.
- `backend/`: FastAPI app, agents, RAG, services, routers, migrations, Celery.
- `.gitignore`: ignores local env, tests, generated docs, PDF drops, caches, and `spec.md`. Use `SYSTEM_SPEC.md` for specs that should remain visible.

Frontend important paths:

- `Frontend/app/page.tsx`: login/register screen.
- `Frontend/app/dashboard/layout.tsx`: authenticated dashboard shell.
- `Frontend/app/dashboard/page.tsx`: dashboard summary.
- `Frontend/app/dashboard/documents/page.tsx`: document list, upload, polling.
- `Frontend/app/dashboard/documents/[id]/page.tsx`: document details, curriculum tree edit, rescan, reprocess, delete, open file.
- `Frontend/app/dashboard/generate/page.tsx`: generation from uploaded document.
- `Frontend/app/dashboard/generate/textbook/page.tsx`: generation from admin textbook namespace.
- `Frontend/app/dashboard/exams/page.tsx`: exam list.
- `Frontend/app/dashboard/exams/[id]/page.tsx`: exam detail, blueprint tab, question edit, export.
- `Frontend/app/dashboard/exams/[id]/history/page.tsx`: exam history and restore.
- `Frontend/app/dashboard/feedback/page.tsx`: feedback store.
- `Frontend/app/dashboard/admin/users/page.tsx`: admin user list.
- `Frontend/app/dashboard/admin/knowledge/page.tsx`: admin textbook knowledge upload.
- `Frontend/lib/api.ts`: frontend API client and TypeScript contracts.
- `Frontend/components/generation-live-viewer.tsx`: WebSocket generation stream and HITL UI.
- `Frontend/components/upload-notification-provider.tsx`: document upload/progress notifications.

Backend important paths:

- `backend/app/main.py`: FastAPI app, lifespan, health checks, routers, WebSocket endpoints.
- `backend/app/core/config.py`: environment settings.
- `backend/app/core/database.py`: async SQLAlchemy engine/session and `Base`.
- `backend/app/core/redis_client.py`: Redis wrapper with in-memory fallback.
- `backend/app/dependencies.py`: auth, JWT, DB, Redis, pagination dependencies.
- `backend/app/routers/`: REST API routers.
- `backend/app/services/`: business logic for auth, documents, exams.
- `backend/app/models/`: SQLAlchemy models.
- `backend/app/schemas/`: Pydantic schemas.
- `backend/app/rag/`: parser, cleaner, structure detector, chunker, embedder, vector store.
- `backend/app/agents/`: LLM abstraction, planner/retrieval/outline/builder/validator, skills, memory, LangGraph.
- `backend/app/agents/graph/`: LangGraph state, builder, nodes.
- `backend/app/tasks/`: Celery app and tasks.
- `backend/app/websocket/manager.py`: exam and document WebSocket managers.
- `backend/app/utils/`: storage, export, search, security, Qwen vision.
- `backend/migrations/`: Alembic migrations.

## 3. Tech Stack

Frontend:

- Next.js `16.2.0`, React `19`, TypeScript `5.7.3`.
- Tailwind CSS v4, Radix UI, shadcn-style local components, lucide-react icons.
- React Hook Form, Zod, KaTeX/react-katex, Sonner toasts.
- API base: `NEXT_PUBLIC_API_URL || http://localhost:8000/api/v1`.

Backend:

- FastAPI, Pydantic v2, SQLAlchemy async, asyncpg, Alembic.
- PostgreSQL 16, Redis 7, Celery.
- Pinecone vector DB.
- MinIO or AWS S3 compatible storage.
- LangGraph for the multi-agent pipeline and HITL interrupts.
- LLM providers through `app/agents/llm.py`: OpenAI, OpenRouter, Groq, Anthropic, Ollama, g4f, Qwen Vision.
- Embeddings: Gemini embedding if keys are available, otherwise local SentenceTransformers (`BAAI/bge-m3`), otherwise deterministic fallback vectors.
- Reranker: CrossEncoder model from `RERANKER_MODEL`, default `BAAI/bge-reranker-v2-m3`.
- Observability: Langfuse wrapper modules exist.

## 4. Runtime Topology

Local or Docker topology:

```text
Next.js frontend
  -> REST /api/v1/*
  -> WebSocket /ws/exam/{exam_id}, /ws/document/{document_id}

FastAPI backend
  -> PostgreSQL: users, docs, exams, history, feedback, preferences, textbook knowledge
  -> Redis: sessions, rate limits, HITL flags, retry issues, WebSocket replay/pubsub
  -> Pinecone: document chunks and textbook chunks
  -> MinIO/S3: uploaded source files
  -> LLM providers and Gemini/Qwen services
  -> optional Celery worker for legacy generation and background tasks
```

`backend/docker-compose.yml` defines `postgres`, `redis`, `minio`, `api`, and `celery_worker`.

Important runtime detail:

- Current frontend calls `POST /api/v1/generate/exam`.
- That route creates an exam and returns immediately with `websocket_url`, then starts generation via `asyncio.create_task()` inside the FastAPI event loop. It does not require Celery for the main FE path.
- Legacy `POST /api/v1/exams/generate` still dispatches `generate_exam_task.delay(...)` through Celery.
- Document upload uses FastAPI `BackgroundTasks` to process documents after upload. A Celery document task exists, but the current upload router does not use it.

## 5. Environment Variables

Backend settings live in `backend/app/core/config.py` and load from `.env`.

Core:

- `DATABASE_URL`: async SQLAlchemy URL, default `postgresql+asyncpg://postgres:postgres@localhost:5432/curriculum_ai`.
- `REDIS_URL`: default `redis://localhost:6379/0`.
- `CELERY_BROKER_URL`: default `redis://localhost:6379/1`.
- `MAX_GENERATES_PER_DAY`: default `9999` in code, despite comments mentioning 10/day.
- `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`.
- `APP_BASE_URL`: used to derive returned WebSocket URLs.
- `CORS_ORIGINS`: comma-separated or JSON array string.

LLM routing:

- Global defaults: `LLM_PROVIDER_DEFAULT`, `LLM_MODEL_STRONG_DEFAULT`, `LLM_MODEL_LIGHT_DEFAULT`.
- Per-role provider/key/model: `ORCHESTRATOR_*`, `BUILDER_*`, `VALIDATOR_*`, `PLANNER_*`, `OUTLINE_*`, `DEDUP_*`, `SKILLS_*`, `CLASSIFIER_*`, `GUARDRAILS_*`, `RERANKER_*`, `VISION_*`.
- Provider keys: `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`.
- Ollama: `OLLAMA_BASE_URL`, `OLLAMA_MODEL_STRONG`, `OLLAMA_MODEL_LIGHT`.
- Qwen Vision: `QWEN_VISION_BASE_URL`, `QWEN_VISION_TIMEOUT`.
- Gemini parse/embed keys: `GEMINI_API_KEY`, `GEMINI_API_KEYS`, plus optional local files `.gemini_keys` and `.gemini_embed_keys`.

RAG/vector:

- `ST_EMBEDDING_MODEL`, `ST_EMBEDDING_DIM`.
- `PINECONE_API_KEY`, `PINECONE_INDEX`, `PINECONE_CLOUD`, `PINECONE_REGION`.
- `RAG_TOP_K_PER_CHAPTER`, `RAG_TOP_K_AFTER_RERANK`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `MAX_CONTEXT_TOKENS`, `EMBEDDING_CACHE_TTL_SECONDS`.

Storage:

- `STORAGE_BACKEND`: `minio` or `s3`.
- MinIO: `MINIO_ENDPOINT_URL`, `MINIO_PUBLIC_URL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_NAME`.
- AWS: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME`, `S3_PRESIGNED_URL_TTL`.

Frontend:

- `NEXT_PUBLIC_API_URL`: should point to backend API prefix, for example `http://localhost:8000/api/v1`.
- `NEXT_PUBLIC_WS_URL`: optional override used by `createExamWebSocket`.

## 6. Authentication And Authorization

Auth is JWT bearer based:

- Register: `POST /api/v1/auth/register`.
- Login: `POST /api/v1/auth/login`.
- Refresh: `POST /api/v1/auth/refresh`.
- Logout: `POST /api/v1/auth/logout`.
- Me: `GET /api/v1/auth/me`.

Implementation:

- Passwords use bcrypt through `passlib`.
- Access tokens include `type=access`, `sub=user_id`, expiry from settings.
- Refresh tokens include `type=refresh`, are hashed with SHA256 in `refresh_tokens`, and are rotated on refresh.
- Frontend stores `token` and `refresh_token` in `localStorage`.
- `apiFetch` attaches `Authorization: Bearer <token>`, refreshes access tokens on 401, and clears tokens if refresh fails.
- Admin routes requiring admin use `get_current_admin`, checking `User.role == "admin"`.

Roles:

- `student`, `teacher`, `admin` enum exists.
- Registration creates normal teacher accounts.
- Admin-only UI is hidden unless `user.role === "admin"`.

## 7. Data Model

Tables and main fields:

### `users`

- `id`: UUID primary key.
- `email`: unique indexed string.
- `password_hash`.
- `full_name`.
- `role`: `student`, `teacher`, or `admin`; default `teacher`.
- `created_at`, `updated_at`.
- Relationships: `documents`, `exams`, `refresh_tokens`, `preferences`, `feedback_events`.

### `refresh_tokens`

- `id`, `user_id`, `token_hash`, `expires_at`, `revoked`, `created_at`.

### `documents`

- `id`, `user_id`, optional `course_id`.
- `file_size`, `original_filename`, `file_type`, `s3_key`.
- `processing_status`.
- `parse_error_message`.
- `heading_tree`: JSONB.
- `total_chapters`, `total_pages_or_slides`, `total_chunks`.
- `uploaded_at`.

Document status caveat:

- Model enum lists `pending`, `processing`, `completed`, `failed`.
- Actual code also writes `indexed` after successful embedding and `processed` when parsing/chunking succeeded but embedding/Pinecone failed.
- Frontend treats `completed`, `indexed`, and sometimes `processed` as usable in different places. Generation page currently filters `completed` or `indexed`.

### `exams`

- `id`, `user_id`, optional `document_id`.
- `title`.
- `scope`: JSONB list of selected chapter/section labels.
- `exam_config`: JSONB generation config.
- `questions`: JSONB list.
- `status`: string.
- `cost_report`, `total_tokens`, `total_cost_usd`.
- `blueprint`: JSONB dedicated blueprint storage.
- `checkpoint_state`, `generation_metadata`, `quality_metrics`.
- `created_at`, `updated_at`.

Exam status enum includes:

- `draft`, `generating`, `hitl_pending_1`, `hitl_pending_2`, `hitl_pending_3`, `completed`, `failed`, `cancelled`, `published`, `regenerating`, `ready_for_review`.

Current practical flow:

- `create_exam()` starts as `draft`.
- `update_questions()` sets `ready_for_review` when questions exist.
- `publish_exam()` sets `published`.
- regenerate paths may use `regenerating`.

### `exam_history`

- `id`, `exam_id`, `snapshot`, `change_type`, `change_description`, `created_at`.
- Used for version snapshots, restore, and edit history.

### `feedback_events`

- `id`, `exam_id`, optional `exam_version_id`, `user_id`, optional `question_id`.
- `signal_type`: `bloom_mismatch`, `out_of_scope`, `duplicate`, `quality_low`, `answer_incorrect`, `validation_warning`, `generation_error`, `publish`, `edit_applied`.
- `severity`: `info`, `warning`, `error`, `critical`.
- `workflow_stage`, `event_source`, `source_type`, `source_ref`.
- `review_status`, `reviewed_by_human`.
- `error_categories`, snapshot refs, flexible `payload`, human `description`.
- `created_at`, `updated_at`.

### `teacher_preferences`

- Keyed by `user_id`.
- `preferred_bloom_distribution`, `preferred_exam_types`, `subject_focus`, `style_notes`.
- Episodic fields: `topic_history`, `reject_patterns`.
- Used as long-term memory after teacher approval.

### `textbook_knowledge`

- `id`, `namespace`, `chapter`, `title`, `url`, `content`, `created_at`.
- Admin-uploaded JSON textbook items. Also embedded to Pinecone under the raw namespace.

## 8. Document Ingestion And RAG Pipeline

Main entrypoint: `POST /api/v1/documents/upload`.

Accepted MIME types:

- PDF.
- DOCX.
- PPTX.

Max backend upload size: 100 MB.

Flow:

1. Router validates MIME and size.
2. `DocumentService.upload_document()` uploads bytes to MinIO/S3 through `get_storage()`.
3. A `documents` row is created with status `pending`.
4. FastAPI `BackgroundTasks` starts `DocumentService.process_document(document_id)`.
5. WebSocket `/ws/document/{document_id}` receives progress events.

Processing steps in `DocumentService.process_document()`:

1. Status -> `processing`.
2. Download source file from storage.
3. Parse document:
   - PDF priority: Gemini parallel chunk parsing (`parser.py`), fallback marker server through `QWEN_VISION_BASE_URL`, fallback PyMuPDF.
   - DOCX: python-docx parser.
   - PPTX: python-pptx parser.
4. Clean Markdown with `clean_markdown()`.
5. Detect heading tree:
   - `detect_heading_tree_gemini_pdf(file_bytes, markdown)` for PDFs.
   - Falls back to `detect_heading_tree_llm(markdown)`.
   - Falls back to heuristic `detect_heading_tree(markdown)`.
6. Chunk with `semantic_chunk(markdown, heading_tree)`.
   - Tries LlamaIndex `SemanticSplitterNodeParser` if an embed model is provided.
   - Usually falls back to paragraph/heading chunking.
   - Every chunk must carry `chapter_id`; fallback is `ch_unknown`.
7. Save heading tree and chunk counts to DB before embedding.
8. Embed chunks:
   - `embed_chunks()` uses `EmbeddingService`.
   - Gemini embedding is tried first if keys exist.
   - Local SentenceTransformer is fallback.
   - Deterministic hash vectors are final fallback.
   - Redis caches embeddings.
9. Upsert to Pinecone grouped by chapter but inside one namespace per document.
10. Status -> `indexed` on successful vector upsert.
11. If embedding/upsert fails after parse/chunk success, status -> `processed` with error message, and the document is still partly usable.
12. On fatal parse/processing failure, status -> `failed`.

Pinecone document namespace convention:

- New format: one namespace per document, `doc_{uuid_without_dashes}` after ASCII normalization.
- `chapter_id` is stored in metadata and can be used as a filter.
- Query currently often searches the whole document namespace then reranks/supplements for scope coverage.
- Legacy per-chapter namespaces are still queried/deleted as fallbacks.

Textbook knowledge pipeline:

- Admin uploads JSON list to `POST /api/v1/admin/knowledge/textbook`.
- Required item keys: `chapter`, `title`, `content`; optional `url`.
- Existing rows for the namespace are deleted first.
- Items are chunked by paragraph at around 1000 chars.
- Embeddings are generated and directly upserted to Pinecone namespace equal to the submitted namespace.
- Metadata uses `document_id=namespace`, `chapter_id=chapter`, `section_id=title`.

## 9. Exam Generation Pipeline

Primary frontend path:

1. User selects a completed/indexed document or a textbook namespace.
2. User selects scope.
3. User sets exam mode, question counts, Bloom distribution, prompt, title.
4. Frontend calls `POST /api/v1/generate/exam`.
5. Backend creates `exams` row and returns:
   - `exam_id`
   - `job_id`
   - `message`
   - `websocket_url`
   - optional `scope_warning`
6. Frontend connects to `/ws/exam/{exam_id}`.
7. Backend background task runs `_run_generation_inline()`.
8. WebSocket streams plan steps, blueprint checkpoint, questions, validation, review checkpoint, completion or errors.

Frontend request shape in `Frontend/lib/api.ts`:

```json
{
  "document_id": "uuid or null",
  "use_builtin_knowledge": false,
  "knowledge_namespace": null,
  "scope": ["Chapter", "Chapter > Section"],
  "exam_type": "mcq | essay | mixed",
  "exam_mode": "standard | thpt_2025",
  "mcq_count": 18,
  "essay_count": 0,
  "dung_sai_count": 4,
  "short_answer_count": 6,
  "bloom_distribution": {
    "nhan_biet": 40,
    "thong_hieu": 30,
    "van_dung": 20,
    "van_dung_cao": 10
  },
  "user_prompt": "optional",
  "extra_instructions": "optional",
  "strict_scope_flag": true,
  "title": "optional"
}
```

Backend mapping in `_map_fe_to_be_request()`:

- If `scope` is list of dicts, maps to list of titles.
- Default Bloom if missing: 25/25/25/25.
- Explicit `mcq_count`, `essay_count`, `dung_sai_count`, `short_answer_count` are preferred.
- If `exam_mode == "thpt_2025"`, backend overrides counts:
  - `mcq_count = 18`
  - `dung_sai_count = 4`
  - `short_answer_count = 6`
  - `essay_count = 0`
  - Bloom = 40/30/20/10.
- `knowledge_namespace` maps to `textbook_namespace` in `exam_config`.

Scope normalization:

- For document-based generation, frontend may send display titles.
- Backend attempts to map those titles to canonical `chapter_id` from document `heading_tree`.
- Matching strategies include exact diacritic-stripped title, substring, keyword overlap, `Chapter > Section` split, and `normalize_chapter_id()`.
- Section titles from `Chapter > Section` are saved as `scope_sections`.

Demo mode:

- If `DEMO_MODE=true`, or no `document_id` and no builtin knowledge, backend builds demo payload with `_build_demo_payload()`.

## 10. LangGraph Agent Flow

Main class: `OrchestratorAgent`.

Graph builder: `backend/app/agents/graph/builder.py`.

Graph state: `ExamGraphState` in `backend/app/agents/graph/state.py`.

Nodes:

- `initialize`
- `clarification_check`
- `load_long_term_memory`
- `decide_plan`
- `fanout_complex`
- `plan_complex`
- `retrieve_knowledge`
- `merge_plan_retrieval`
- `dispatch_tasks`
- `create_outline`
- `emit_checkpoint_1`
- `wait_for_blueprint_approval`
- `build_questions`
- `validate_questions`
- `check_validation_result`
- `retry_builder`
- `emit_checkpoint_2`
- `wait_for_review`
- `save_teacher_preferences`
- `emit_checkpoint_3`
- `finalize_output`
- Failure/exit nodes: `handle_retrieval_failure`, `handle_outline_failure`, `handle_builder_failure`, `handle_max_retries_exceeded`, `handle_timeout`, `emit_clarification`, `finalize_with_feedback`.

Main edges:

```text
START
  -> initialize
  -> clarification_check
  -> load_long_term_memory
  -> decide_plan
     -> simple: retrieve_knowledge
     -> complex: fanout_complex -> plan_complex and retrieve_knowledge in parallel
  -> merge_plan_retrieval
  -> dispatch_tasks
  -> create_outline
  -> emit_checkpoint_1
  -> wait_for_blueprint_approval
     -> approved: build_questions
     -> rejected: create_outline
     -> waiting: END until HTTP resume
  -> validate_questions
  -> check_validation_result
     -> passed: emit_checkpoint_2
     -> retry: retry_builder -> build_questions
     -> max_exceeded: handle_max_retries_exceeded -> emit_checkpoint_2
  -> wait_for_review
     -> approved: save_teacher_preferences -> emit_checkpoint_3 -> finalize_output -> END
     -> rejected: finalize_with_feedback -> END
     -> timeout: handle_timeout -> END
```

Checkpointer:

- Startup calls `init_shared_checkpointer()`.
- Preferred: `AsyncPostgresSaver` from `langgraph-checkpoint-postgres`.
- Fallback: `MemorySaver`.
- If fallback is used, HITL resume state is lost on process restart.

Agent roles:

- Orchestrator: user-facing coordination, graph execution, HITL resume.
- Planner: used for complex prompts. Complex signal threshold is at least two signals.
- Retrieval: query expansion, embedding search, reranking, scope coverage.
- Outline: turns retrieved chunks/config into a blueprint.
- Builder: turns blueprint slots into actual questions.
- Validator: answer checking, Bloom compliance, scope violation, content quality, retry issues.

Skills:

- Bloom classifier.
- Dedup checker.
- Difficulty estimator.
- LaTeX renderer.
- Scope checker.

Question types:

- `mcq`: 4 options, one correct answer.
- `essay`: rubric expected.
- `dung_sai`: THPT 2025 true/false block with 4 propositions a/b/c/d.
- `short_answer`: numeric short answer plus unit/solution.

Canonical Bloom levels:

- `nhan_biet`
- `thong_hieu`
- `van_dung`
- `van_dung_cao`

## 11. HITL Checkpoints

Checkpoint 0:

- Requirements clarification/confirmation.
- There is code for `clarification_needed`, but frontend clarification submit currently has a route mismatch. See Known Issues.

Checkpoint 1:

- Blueprint review.
- WebSocket event: `hitl_checkpoint` with `checkpoint_id=1`.
- Data should include:
  - `blueprint`: list of slots.
  - `distribution_summary`.
- Frontend shows the blueprint and lets teacher approve or reject.
- Approve endpoint: `POST /api/v1/exams/{exam_id}/approve-blueprint` with `{ "approved": true }`.
- Reject endpoint: `POST /api/v1/exams/{exam_id}/reject-blueprint` with `{ "feedback": "..." }`.
- Backend stores Redis flags such as `hitl:approved:{exam_id}:1` and resumes the paused LangGraph through `Command(resume=...)`.

Checkpoint 2:

- Generated exam review.
- WebSocket event: `hitl_checkpoint` with `checkpoint_id=2`.
- Data should include exam ID, questions, validation pass/fail, issues/warnings.
- Frontend can edit/regenerate individual questions and approve/reject the full exam.
- Review data endpoint: `GET /api/v1/exams/{exam_id}/review-data`.
- Submit endpoint: `POST /api/v1/exams/{exam_id}/submit-review`.
- If approved, backend saves teacher preferences and persists final questions.
- If rejected, backend resumes graph with feedback or falls back to Celery regeneration.

Checkpoint 3:

- Export preview/finalization.
- WebSocket event: `hitl_checkpoint` with `checkpoint_id=3`.
- API preview: `GET /api/v1/exams/{exam_id}/preview`.
- Export endpoints produce actual PDF/DOCX.

## 12. WebSocket Contract

Exam stream endpoint:

- `GET ws://host/ws/exam/{exam_id}`.
- `ConnectionManager.connect()` accepts and replays stored Redis events from `ws_events:{exam_id}`.
- `listen_redis()` subscribes to Redis channel `exam:{exam_id}` for multi-instance fanout.
- Events are stored before sending, TTL 3600 seconds, max 1000 list entries.

Common exam event types:

- `plan_step`: `{ type, step, total_steps, message }`.
- `question_generated`: `{ type, question_id, question }`.
- `validation_result`: `{ type, passed, issues_count, issues }`.
- `hitl_checkpoint`: `{ type, checkpoint_id, data }`.
- `pipeline_paused`: used by frontend, may carry `checkpoint_id`, `blueprint`, `distribution_summary`.
- `clarification_needed`: `{ type, data: { clarification_questions } }`.
- `question_updated`: emitted after per-question regenerate.
- `completed`: `{ type, exam_id, total_cost_usd? }`.
- `error`: `{ type, message, agent? }`.
- `reasoning_chunk`: frontend supports it, but not every backend path emits it.

Document upload stream endpoint:

- `GET ws://host/ws/document/{document_id}`.
- Events:
  - `upload_progress`
  - `processing_step`
  - `processing_completed`
  - `processing_failed`
- Document upload manager does not currently implement Redis replay like exam manager.

## 13. REST API Summary

All protected endpoints require `Authorization: Bearer <access_token>` unless noted.

### Health

- `GET /`: service info.
- `GET /health`: liveness.
- `GET /ready`: checks DB, Redis, Pinecone.

### Auth

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

### Documents

- `POST /api/v1/documents/upload`: upload PDF/DOCX/PPTX.
- `GET /api/v1/documents`: paginated user documents.
- `GET /api/v1/documents/{document_id}`: detail.
- `GET /api/v1/documents/{document_id}/status`: status with 1 second Redis throttle.
- `DELETE /api/v1/documents/{document_id}`: delete DB row, storage file, Pinecone vectors, Redis caches.
- `GET /api/v1/documents/{document_id}/refresh-url`: presigned download URL.
- `GET /api/v1/documents/{document_id}/curriculum-tree`: flattened curriculum tree.
- `PATCH /api/v1/documents/{document_id}/curriculum-tree`: persist edited tree.
- `POST /api/v1/documents/{document_id}/rescan-structure`: rerun parse/structure detection.
- `POST /api/v1/documents/{document_id}/reprocess`: delete old vectors, reprocess/reindex.

### Courses

Courses are placeholders:

- `GET /api/v1/courses/`: returns empty list.
- `GET /api/v1/courses/{course_id}`: 404 not implemented.
- `POST /api/v1/courses/`: 501 not implemented.
- `GET /api/v1/courses/{course_id}/documents`: filters documents by metadata `course_id`.
- `POST /api/v1/courses/{course_id}/documents/upload`: 501 not implemented.

### Generation

Frontend path:

- `POST /api/v1/generate/exam`: creates exam, returns WebSocket URL, starts background in-process generation.
- `POST /api/v1/generate/partial-regenerate`: FE-compatible wrapper to `ExamService.partial_regenerate()`.

Legacy path:

- `POST /api/v1/exams/generate`: creates exam and dispatches Celery task.

### Exams

- `GET /api/v1/exams`: list exams.
- `GET /api/v1/exams/quality-summary`: dashboard quality summary.
- `GET /api/v1/exams/feedback-summary`: feedback summary.
- `GET /api/v1/exams/feedback-store`: paginated feedback events.
- `GET /api/v1/exams/{exam_id}`: exam detail.
- `GET /api/v1/exams/{exam_id}/versions`: version list.
- `GET /api/v1/exams/{exam_id}/feedback`: exam feedback.
- `POST /api/v1/exams/{exam_id}/publish`: publish and log preference/feedback.
- `DELETE /api/v1/exams/{exam_id}`.
- `POST /api/v1/exams/{exam_id}/backfill-blueprint`: synthesize/persist blueprint.
- `POST /api/v1/exams/{exam_id}/backfill-quality`: recompute quality metrics.
- `PATCH /api/v1/exams/{exam_id}/questions/{question_id}`: inline question edit.
- `POST /api/v1/exams/{exam_id}/edit-prompt`: natural-language exam edit.
- `POST /api/v1/exams/{exam_id}/regenerate`: full or selected question regeneration through Celery.
- `POST /api/v1/exams/{exam_id}/partial-regenerate`: one-question regeneration at CP2.
- `GET /api/v1/exams/{exam_id}/export/pdf`.
- `GET /api/v1/exams/{exam_id}/export/docx`.
- `GET /api/v1/exams/{exam_id}/history`.
- `POST /api/v1/exams/{exam_id}/history/{history_id}/restore`.
- `POST /api/v1/exams/{exam_id}/approve-blueprint`.
- `POST /api/v1/exams/{exam_id}/reject-blueprint`.
- `POST /api/v1/exams/{exam_id}/clarify`.
- `GET /api/v1/exams/{exam_id}/review-data`.
- `GET /api/v1/exams/{exam_id}/preview`.
- `POST /api/v1/exams/{exam_id}/submit-review`.

### Admin

- `GET /api/v1/admin/users`: admin only.
- `GET /api/v1/admin/knowledge/namespaces`: public.
- `GET /api/v1/admin/knowledge/chapters?namespace=...`: public.
- `GET /api/v1/admin/knowledge/outline?namespace=...`: public.
- `POST /api/v1/admin/knowledge/textbook`: admin only, upload JSON and embed to Pinecone.

## 14. Frontend Workflows

### Login/Register

- `Frontend/app/page.tsx`.
- Uses `authApi.login()` and `authApi.register()`.
- On success stores tokens and navigates to dashboard.

### Document Management

- `DocumentsPage` lists up to 50 docs, polls `pending` and `processing` docs every 3 seconds.
- Upload uses `useUploadNotification().startUpload(file)`, not the generic `FileUpload` simulation component.
- Allowed UI types match backend: PDF/DOCX/PPTX.
- Detail page loads document and curriculum tree, supports selecting/editing tree nodes, saving tree, reprocess, rescan, delete, and opening file via presigned URL.

### Generate From Document

- Page loads completed/indexed documents.
- Selecting a document loads its curriculum tree.
- User selects sections. If all sections in a chapter are selected, frontend sends only the chapter title. Otherwise sends `Chapter > Section`.
- User configures standard/THPT 2025 mode, counts, Bloom distribution, prompt, title.
- Calls `generateApi.startGeneration()`.
- Opens `GenerationLiveViewer` with `examId` and `wsUrl`.

### Generate From Textbook Knowledge

- Page loads public namespaces and outlines from admin endpoints.
- User selects namespace and textbook sections.
- Scope sent to backend is unique chapter names, not section names.
- Request uses `document_id: null`, `use_builtin_knowledge: true`, and `knowledge_namespace`.

### Live Generation UI

- `GenerationLiveViewer` handles WebSocket events.
- It renders a pipeline strip, reasoning/feed blocks, blueprint review, streamed questions, validation issues, CP2 edit/regenerate controls, clarification UI, and completion navigation.
- CP1 approve/reject calls `onApprove(examId, approved, feedback, checkpointId)`, implemented by generation pages.
- CP2 approve/reject calls `examsApi.submitReview()`.
- One-question regeneration calls `examsApi.partialRegenerate(examId, { question_id, prompt })`.

### Exam Detail

- Loads exam and versions.
- Loads blueprint from `exam.blueprint`, falls back to `getReviewData()`, then synthesizes from questions.
- Opens its own WebSocket to catch CP1 blueprint events if pipeline is still running.
- Supports PDF and DOCX export. Frontend downloads both student and teacher versions by calling export endpoints twice.
- Supports publish, prompt edit, regenerate, inline question edit, blueprint approve/reject.

## 15. Export

Exporter: `backend/app/utils/export.py`.

PDF:

- Endpoint: `GET /api/v1/exams/{exam_id}/export/pdf`.
- Uses `ExamExporter.export_pdf()`.
- Query params:
  - `include_answers=false`: student version.
  - `include_answers=true`: teacher version with answer key/explanations/rubrics.
  - `include_blueprint=true`: include Bloom distribution table.
- Backend has a 10 MB guard.

DOCX:

- Endpoint: `GET /api/v1/exams/{exam_id}/export/docx`.
- Query param:
  - `include_answers`.
- Backend has a 10 MB guard.

Preview:

- Endpoint: `GET /api/v1/exams/{exam_id}/preview`.
- Returns HTML strings, does not create files.

## 16. Testing And Verification

Backend tests:

- `backend/tests/agents/graph/test_state_schema.py`: state and conditional edge routing.
- `backend/tests/agents/graph/test_integration/test_full_graph.py`: graph compilation and routing.
- `backend/tests/agents/graph/nodes/test_initialize.py`: initialize defaults and checkpoint timeouts.
- `backend/tests/agents/graph/nodes/test_validate_questions.py`: validation issue dedupe and event emission.
- `backend/tests/agents/graph/test_edge_cases/test_edge_cases.py`: specific bug regression tests.
- `backend/test_e2e.py`: script-style E2E covering auth, upload, generation, HITL, export, rate limit, WebSocket replay, health.
- `.gitignore` currently ignores backend tests, so treat them as local/hidden unless policy changes.

Expected commands:

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
celery -A app.tasks.celery_app worker --loglevel=info

# Frontend
cd Frontend
npm install
npm run dev
npm run build
npm run lint

# Docker services
cd backend
docker-compose up -d
```

Notes:

- FastAPI startup calls `init_db()` which runs SQLAlchemy `create_all`. Alembic still exists and should be the production migration path.
- On Windows, repo ownership may make `git status` fail with `dubious ownership` in sandbox users. That is environmental, not an app issue.
- PowerShell output may show mojibake for Vietnamese text. Source files are intended as UTF-8.

## 17. Known Gaps And Risks

These are important for any future AI working in the repo:

- Frontend `GenerationLiveViewer.handleClarificationSubmit()` posts to `/api/exams/{examId}/clarify` with cookie credentials. Backend route is `/api/v1/exams/{exam_id}/clarify` and auth uses bearer token. This likely breaks clarification submit.
- Frontend `examsApi.updateQuestion()` sends a partial question object directly to `PATCH /exams/{examId}/questions/{questionId}`. Backend expects `EditQuestionRequest` shape `{ question_id, updates }`. This likely causes 422 unless backend is changed.
- Frontend `examsApi.regenerate()` sends JSON body `{ question_ids }`, but backend route signature declares `question_ids` as a function parameter, not a Pydantic body model. Verify behavior before relying on it.
- `DocumentProcessingStatus` enum omits `indexed` and `processed`, but code uses both. Future changes should normalize statuses or update schemas/enums consistently.
- `POST /api/v1/generate/exam` docs say "runs synchronously", but implementation returns immediately and uses `asyncio.create_task()`.
- Rate limit comments mention 10 generations/day, but code uses `MAX_GENERATES_PER_DAY` from settings, default `9999`.
- Courses are placeholders. There is no course model.
- `FileUpload` component simulates upload progress and is not the actual backend upload path.
- `README.md` and comments contain some stale descriptions. Prefer current code paths.
- Some debug `print()` and `console.log()` calls remain in generation and WebSocket code.
- If LangGraph uses `MemorySaver`, HITL resume is not durable across backend restarts.
- Redis has an in-memory fallback, but event replay, pubsub, rate limit, and HITL coordination degrade significantly.
- Pinecone startup failure does not block server startup. Upload can parse/chunk and then end at `processed` if vector indexing fails.
- `.env.example` contains older variable names such as `LLM_MODEL_STRONG`; current config prefers per-role fields and `LLM_MODEL_STRONG_DEFAULT`.

## 18. Invariants Future AI Must Preserve

- Do not bypass auth ownership checks. Every user-owned document/exam access should filter by `current_user.id`.
- Keep question IDs stable when editing or regenerating individual questions.
- Keep `question_id`, `type`/`question_type`, `content`/`stem`, `options`, `correct_answer`, `bloom_level`, `chapter`, `source_evidence`, and `warnings` compatible with frontend normalization.
- Bloom distribution must sum to 100 before generation.
- THPT 2025 preset must produce 18 MCQ, 4 `dung_sai`, 6 `short_answer`, 0 essay unless product requirements change.
- CP1 must emit a list blueprint. Frontend expects array slots.
- CP2 must provide enough question/review data for inline edit and final approval.
- When emitting WebSocket events, store/replay compatibility matters. Do not rename event types without updating `Frontend/lib/api.ts` and `GenerationLiveViewer`.
- Document chunks must have non-empty `chapter_id`; use `ch_unknown` as last resort.
- Pinecone document namespace must remain one namespace per document unless all retrieval/delete/reprocess code is migrated.
- Admin textbook namespaces are raw namespaces, not `doc_{uuid}` namespaces.
- Do not delete vectors or files before verifying ownership.
- Keep export endpoints producing binary `StreamingResponse` with correct content type and filename.
- Prefer small fixes that align frontend and backend contracts over adding parallel duplicate endpoints.

## 19. Suggested Next Cleanup Priorities

1. Fix frontend/backend API mismatches for question edit, regenerate, and clarification submit.
2. Normalize document statuses across model enum, schemas, frontend filters, and services.
3. Remove or gate debug logs in generation routes and live viewer.
4. Decide whether `/api/v1/generate/exam` or `/api/v1/exams/generate` is the official generation endpoint and mark the other as legacy.
5. Make HITL resume durability mandatory in non-dev environments by failing startup if Postgres checkpointer is unavailable.
6. Add tests for frontend API request shapes against backend schemas.
7. Move ignored tests into tracked test paths or update `.gitignore` if tests are meant to be part of the repo.
8. Update README and `.env.example` to match the current per-role config and in-process generation path.

## 20. Quick Mental Model For Another AI

If asked to implement a feature:

1. Identify whether it touches document ingestion, generation/HITL, exam editing/export, auth/admin, or frontend-only UI.
2. Check `Frontend/lib/api.ts` and the matching backend router together. Many bugs are contract mismatches.
3. For generation changes, inspect the LangGraph node, not only `OrchestratorAgent`. The actual path is in `app/agents/graph/nodes`.
4. For document retrieval issues, inspect `heading_tree`, `semantic_chunk()`, `normalize_chapter_id()`, Pinecone namespace, and `RetrievalAgent` scope filtering/reranking.
5. For WebSocket issues, inspect both the event emitter in backend nodes/tasks and the handler switch in `GenerationLiveViewer`.
6. For persistence issues, inspect `ExamService.update_questions()`, `update_blueprint()`, history snapshots, and Redis session writes.
7. For export issues, inspect `ExamExporter`, not only the route.

