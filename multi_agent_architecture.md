# ExamAI — Multi-Agent System Architecture

> Quét toàn bộ codebase · Vẽ chính xác theo source code thực tế

---

## 🗺️ Tổng quan hệ thống

```mermaid
graph TB
    subgraph CLIENT["🌐 Client Layer"]
        FE["Next.js Frontend"]
        WS["WebSocket / SSE Stream"]
    end

    subgraph API["⚡ FastAPI Backend"]
        RT_GEN["POST /generate\n(generate.py)"]
        RT_EXAM["GET /exams/{id}\n(exams.py)"]
        RT_HITL["POST /approve-blueprint\nPOST /submit-review"]
        RT_DOC["POST /documents\n(documents.py)"]
    end

    subgraph QUEUE["🔁 Task Queue"]
        CELERY["Celery Worker\n(exam_task.py)"]
        BROKER["Redis Broker"]
    end

    subgraph ORCH["🎯 Orchestrator Agent (Agent-0)"]
        ORC["OrchestratorAgent\norchestrator.py"]
    end

    subgraph LANGGRAPH["🧠 LangGraph StateGraph — ExamGraphState"]
        direction TB
        GRAPH["build_exam_graph()\nStateGraph + checkpointer"]
    end

    subgraph STORAGE["🗄️ Persistence"]
        PG["PostgreSQL\n(exam, question, document, feedback_event)"]
        REDIS["Redis\n(session, HITL keys, pub/sub, retry_issues)"]
        PINE["Pinecone\n(vector namespace per doc)"]
        PG_CP["AsyncPostgresSaver\n(LangGraph Checkpoints)"]
    end

    subgraph OBS["📊 Observability"]
        TRACER["Tracer\n(tracer.py)"]
        LANGFUSE["Langfuse\n(LLM call tracing)"]
        WSMANAGER["WebSocket Manager\n(SSEvent stream)"]
    end

    FE -->|"HTTP POST"| RT_GEN
    FE <-->|"SSE stream"| WS
    RT_GEN -->|"generate_exam_task.delay()"| BROKER
    BROKER --> CELERY
    CELERY -->|"instantiate"| ORC
    ORC -->|"ainvoke()"| GRAPH
    GRAPH -->|"interrupt / resume"| PG_CP
    GRAPH -->|"emit events"| WSMANAGER
    WSMANAGER <--> WS
    ORC -->|"read/write session"| REDIS
    RT_HITL -->|"set hitl:approved:*"| REDIS
    RT_HITL -->|"graph.ainvoke(Command(resume=...))"| GRAPH
    GRAPH --- PINE
    GRAPH --- PG
    TRACER --> LANGFUSE
    ORC --> TRACER
```

---

## 🔄 LangGraph Pipeline — Toàn bộ luồng node-by-node

```mermaid
flowchart TD
    START([▶ START]) --> INIT

    subgraph PHASE0["Phase 0 · Setup"]
        INIT["initialize\nInit ExamGraphState\n+ defaults"]
    end

    subgraph PHASE1["Phase 1 · Clarification"]
        CC["clarification_check\nLLM → yêu cầu rõ chưa?"]
        EC["emit_clarification\n→ WebSocket event\n→ END ⏹"]
    end

    subgraph PHASE2["Phase 2 · Planning"]
        LLM_MEM["load_long_term_memory\nPostgres → teacher prefs"]
        DP["decide_plan\ncount complexity signals\n→ 'simple' | 'complex'"]
        FC["fanout_complex\n[passthrough node]\n→ parallel fan-out"]
        PC["plan_complex\nPlannerAgent.create_plan()\nLLM execution plan"]
        RK["retrieve_knowledge\nRetrievalAgent.retrieve()\nQuery Pinecone namespace"]
        HRF["handle_retrieval_failure\n→ create_outline\n(fallback empty context)"]
        MP["merge_plan_retrieval\nMerge plan + retrieved context"]
        DT["dispatch_tasks\nProcess task_queue\n(focused_retrieval etc.)"]
    end

    subgraph PHASE3["Phase 3 · Blueprint (Outline)"]
        CO["create_outline\nOutlineAgent.create_outline()\nBloom blueprint gen"]
        HOF["handle_outline_failure\n→ END ⏹"]
        EP1["emit_checkpoint_1\nEmit hitl_checkpoint #1\n(blueprint preview)"]
    end

    subgraph HITL1["⏸ HITL Checkpoint 1 · Blueprint Review"]
        WBA["wait_for_blueprint_approval\ninterrupt() ⏸\nRedis pub/sub poll\n30-min timeout"]
        WBA_A{"approved?"}
        HTO["handle_timeout → END ⏹"]
    end

    subgraph PHASE4["Phase 4 · Question Generation"]
        BQ["build_questions\nBuilderAgent.build()\nLLM per blueprint slot"]
        HBF["handle_builder_failure\n→ emit_checkpoint_2"]
    end

    subgraph PHASE5["Phase 5 · Validation + Retry Loop (G9)"]
        VQ["validate_questions\nValidatorAgent.validate()\nBatch LLM (BATCH_SIZE=10)\n+ BloomClassifier + ScopeChecker"]
        CVR["check_validation_result\nRoute: passed / retry / max_exceeded"]
        RB["retry_builder\nIncrement retry_count\n(max 3)"]
        HMR["handle_max_retries_exceeded\n→ emit_checkpoint_2"]
    end

    subgraph HITL2["⏸ HITL Checkpoint 2 · Full Exam Review"]
        EP2["emit_checkpoint_2\nEmit hitl_checkpoint #2\n(questions preview)"]
        WFR["wait_for_review\ninterrupt() ⏸\nRedis poll\n30-min timeout"]
        WFR_A{"approved?"}
    end

    subgraph PHASE6["Phase 6 · Finalize"]
        STP["save_teacher_preferences\nLongTermMemory.save()\n→ Postgres"]
        EP3["emit_checkpoint_3\nEmit completion event"]
        FO["finalize_output\nBuild final output\n→ ExamService.update_questions()\n→ END ✅"]
        FWF["finalize_with_feedback\nSave feedback\n→ END ⏹"]
    end

    %% ── Phase 0 → 1 ───────────────────────────────────────
    INIT --> CC
    CC -->|"clarification_needed"| EC
    CC -->|"requirements_clear"| LLM_MEM

    %% ── Phase 2 ─────────────────────────────────────────
    LLM_MEM --> DP
    DP -->|"complex"| FC
    DP -->|"simple"| RK
    FC --> PC
    FC --> RK
    PC --> MP
    RK -->|"success / partial"| MP
    RK -->|"failed"| HRF
    HRF --> CO
    MP --> DT
    DT --> CO

    %% ── Phase 3 ─────────────────────────────────────────
    CO -->|"success / partial"| EP1
    CO -->|"failed"| HOF
    EP1 --> WBA

    %% ── HITL 1 ──────────────────────────────────────────
    WBA --> WBA_A
    WBA_A -->|"approved"| BQ
    WBA_A -->|"rejected → feedback"| CO
    WBA_A -->|"waiting (END, resume later)"| RESUME1(["⏸ Graph saved\nResume via HTTP"])
    WBA_A -->|"timeout"| HTO

    %% ── Phase 4 ─────────────────────────────────────────
    BQ -->|"success / partial"| VQ
    BQ -->|"failed"| HBF

    %% ── Phase 5 (retry loop G9) ─────────────────────────
    VQ --> CVR
    CVR -->|"passed"| EP2
    CVR -->|"retry (count < 3)"| RB
    CVR -->|"max_exceeded"| HMR
    RB --> BQ
    HMR --> EP2
    HBF --> EP2

    %% ── HITL 2 ──────────────────────────────────────────
    EP2 --> WFR
    WFR --> WFR_A
    WFR_A -->|"approved"| STP
    WFR_A -->|"rejected"| FWF
    WFR_A -->|"timeout"| HTO

    %% ── Phase 6 ─────────────────────────────────────────
    STP --> EP3
    EP3 --> FO

    %% ── Styling ─────────────────────────────────────────
    classDef hitl fill:#f59e0b,stroke:#d97706,color:#000
    classDef error fill:#ef4444,stroke:#b91c1c,color:#fff
    classDef success fill:#10b981,stroke:#059669,color:#fff
    classDef agent fill:#3b82f6,stroke:#2563eb,color:#fff
    classDef decision fill:#8b5cf6,stroke:#7c3aed,color:#fff

    class WBA,WFR,EP1,EP2 hitl
    class HRF,HOF,HBF,HMR,HTO,FWF error
    class FO success
    class CC,PC,RK,CO,BQ,VQ agent
    class WBA_A,WFR_A,CVR decision
```

---

## 🤖 Agent Breakdown — Chi tiết từng Agent

```mermaid
graph LR
    subgraph AGENTS["Agent Catalogue"]
        direction TB

        subgraph A0["Agent-0: Orchestrator"]
            ORC_ROLE["orchestrator.py\n• Entry point duy nhất\n• Wrap LangGraph\n• HITL approve/reject\n• WebSocket stream\n• edit_via_prompt()"]
        end

        subgraph A1["Agent-1: Retrieval"]
            RET_ROLE["retrieval.py\n• Query expansion (G11)\n→ 3–5 LLM query variants\n• Parallel Pinecone query\n(asyncio.gather)\n• BGE-M3 embedding\n• CrossEncoder reranking\n• Token budget guard\n• Chapter supplement fallback"]
        end

        subgraph A2["Agent-2: Planner"]
            PLN_ROLE["planner.py\n• LLM execution plan\n• Parameter overrides\n• Token cost estimate\n• Only for 'complex' requests\n(G6: ≥2 signals)"]
        end

        subgraph A3["Agent-3: Outline"]
            OUT_ROLE["outline.py\n• Blueprint gen (Bloom dist)\n• Slot-by-slot structure\n• Feedback regeneration (G8)\n• Distribution validation"]
        end

        subgraph A4["Agent-4: Builder"]
            BLD_ROLE["builder.py\n• Per-slot question gen\n• MCQ / Essay / T-F / Short Ans\n• GuardrailsPipeline\n• ScopeGuard + ContentFilter\n• Token budget control"]
        end

        subgraph A5["Agent-5: Validator"]
            VAL_ROLE["validator.py\n• Batch LLM validation\n(10 questions / call)\n• Answer checking\n• Bloom compliance\n• Scope violation check\n• Content quality check\n• Persist issues → Redis"]
        end
    end

    subgraph SKILLS["🔧 Skills (shared)"]
        SK1["bloom_classifier.py\nBloom level classification"]
        SK2["scope_checker.py\nKeyword-overlap scope check"]
        SK3["dedup_checker.py\nDuplicate detection"]
        SK4["difficulty_estimator.py\nDifficulty scoring"]
        SK5["latex_renderer.py\nLaTeX math formatting"]
    end

    subgraph GUARDRAILS["🛡️ Guardrails Pipeline"]
        GR1["OutputParser\n(structured LLM output)"]
        GR2["ScopeGuard\n(concept keyword overlap)"]
        GR3["ContentFilter\n(stem length, option unique)"]
        GR4["TokenBudgetGuard\n(90% budget threshold)"]
    end

    A4 --> SKILLS
    A5 --> SK1
    A5 --> SK2
    A4 --> GUARDRAILS
```

---

## 🧠 Memory Architecture

```mermaid
graph TB
    subgraph STM["Short-Term Memory (Redis, TTL 2h)"]
        S1["session:{exam_id}:{user_id}\n• exam_config_original\n• topics_used\n• conversation_history\n• retry_count\n• retrieved_context"]
        S2["hitl:approved:{exam_id}:1\nhitl:approved:{exam_id}:2\n(HITL approval keys)"]
        S3["retry_issues:{exam_id}\n(validator issues, TTL 1h)"]
        S4["task:started:{exam_id}\n(idempotency guard)"]
        S5["exam:{exam_id} channel\n(Redis pub/sub for HITL events)"]
    end

    subgraph LTM["Long-Term Memory (PostgreSQL)"]
        L1["teacher_preferences table\n• preferred_bloom_distribution\n• preferred_exam_types\n• subject_focus\n• user_id (FK)"]
        L2["exam table\n• id, status, blueprint, cost_report"]
        L3["question table\n• content, bloom_level, quality_score"]
        L4["feedback_event table\n• issue_type, workflow_stage\n• event_source, detail"]
    end

    subgraph GRAPH_CP["Graph Checkpoints (AsyncPostgresSaver)"]
        GP1["langgraph_checkpoints table\n• thread_id = exam_id\n• Snapshot ExamGraphState\n• Resume on restart"]
    end

    subgraph VECTOR["Vector Memory (Pinecone)"]
        V1["Namespace: doc_{document_id}\n• chunk_id, content\n• chapter_id, section\n• content_type, latex_repr\n• BGE-M3 embeddings (1024-dim)"]
        V2["Textbook namespace\n• Admin-uploaded content\n• Chapter-filtered queries"]
    end

    STM --- LTM
    LTM --- GRAPH_CP
    GRAPH_CP --- VECTOR
```

---

## 📡 HITL Interaction Flow — Luồng Human-in-the-Loop

```mermaid
sequenceDiagram
    actor Teacher as 👨‍🏫 Teacher
    participant FE as Next.js Frontend
    participant API as FastAPI
    participant REDIS as Redis
    participant GRAPH as LangGraph Graph
    participant DB as PostgreSQL

    Teacher->>FE: Submit exam config + scope
    FE->>API: POST /generate
    API->>REDIS: dispatch generate_exam_task
    REDIS-->>GRAPH: Celery worker starts graph

    Note over GRAPH: Phase 1-3: Init → Retrieve → Outline

    GRAPH->>REDIS: Publish hitl_checkpoint #1 (blueprint)
    REDIS-->>FE: SSE: hitl_checkpoint event
    FE-->>Teacher: Show Blueprint UI

    alt Teacher APPROVES blueprint
        Teacher->>FE: Click Approve
        FE->>API: POST /approve-blueprint
        API->>REDIS: SET hitl:approved:{id}:1 = "true"
        API->>GRAPH: graph.ainvoke(Command(resume))
        Note over GRAPH: Phase 4-5: Build → Validate → Retry loop
    else Teacher REJECTS blueprint
        Teacher->>FE: Feedback text + Click Reject
        FE->>API: POST /reject-blueprint {feedback}
        API->>REDIS: Publish rejection event
        Note over GRAPH: G8: Regenerate outline with feedback
        GRAPH->>REDIS: Publish hitl_checkpoint #1 (new blueprint)
        REDIS-->>FE: SSE: Updated blueprint
    end

    GRAPH->>REDIS: Publish hitl_checkpoint #2 (questions)
    REDIS-->>FE: SSE: hitl_checkpoint #2 event
    FE-->>Teacher: Show Full Exam Review UI

    alt Teacher APPROVES exam
        Teacher->>FE: Click Approve
        FE->>API: POST /submit-review {approved: true}
        API->>GRAPH: graph.ainvoke(Command(resume={approved:true}))
        GRAPH->>DB: ExamService.update_questions()
        GRAPH->>DB: save teacher_preferences (Long-term memory)
        GRAPH->>REDIS: SSE: completed event
        REDIS-->>FE: Exam ready!
    else Teacher REJECTS exam
        Teacher->>FE: Feedback + Reject
        FE->>API: POST /submit-review {approved: false, feedback}
        API->>GRAPH: graph.ainvoke(Command(resume={approved:false}))
        GRAPH->>REDIS: finalize_with_feedback → END
        Note over GRAPH: Pipeline ends, feedback saved
    end
```

---

## 🔁 Retry Loop Detail — G9 Validation

```mermaid
stateDiagram-v2
    [*] --> build_questions

    build_questions --> validate_questions : success / partial
    build_questions --> handle_builder_failure : failed

    validate_questions --> check_validation_result

    state check_validation_result {
        [*] --> routing
        routing --> passed : no issues
        routing --> retry : has_issues AND retry_count < 3
        routing --> max_exceeded : retry_count >= 3
    }

    passed --> emit_checkpoint_2
    handle_builder_failure --> emit_checkpoint_2
    max_exceeded --> handle_max_retries_exceeded
    handle_max_retries_exceeded --> emit_checkpoint_2

    retry --> retry_builder
    retry_builder --> build_questions : increment retry_count\npass issues list back

    emit_checkpoint_2 --> [*]

    note right of retry_builder
        Redis: retry_issues:{exam_id}
        persisted across worker restarts
        (ShortTermMemory.save_retry_issues)
    end note
```

---

## 🔍 RAG Pipeline — Retrieval Detail

```mermaid
flowchart LR
    subgraph INPUT["Input"]
        SC["scope_chapters\n['Chương 1', 'Chương 3']"]
        BT["bloom_targets\n['van_dung', 'van_dung_cao']"]
        HINTS["query_hints\n(from planner)"]
    end

    subgraph EXPAND["G11: Query Expansion"]
        QE["LLM: generate 3–5\nquery variants\n(GPT-4o-mini, temp=0.3)"]
    end

    subgraph EMBED["Embedding"]
        BGE["BGE-M3 (1024-dim)\nEmbeddingService\n(Redis cache)"]
    end

    subgraph QUERY["G10: Parallel Query"]
        PQ["asyncio.gather()\nquery Pinecone\n(doc namespace)\n30s timeout/chapter"]
        SUPP["Chapter supplement\n(targeted filter for\nunder-represented chapters\n< MIN_CHUNKS_PER_CHAPTER=5)"]
    end

    subgraph RERANK["Reranking"]
        SEP["Separate scope vs\nnon-scope chunks"]
        PER_CH["Per-chapter rerank\n(BGE reranker-v2-m3)"]
        BUDGET["Token budget cut\n(tiktoken, MAX_CONTEXT_TOKENS)"]
    end

    subgraph OUTPUT["Output: RetrievalOutput"]
        RC["retrieved_chunks\n(chunk_id, content,\nchapter, section,\nrelevance_score, latex_repr)"]
        CM["coverage_map\n{chapter → [chunk_ids]}"]
    end

    SC & BT & HINTS --> QE
    QE --> BGE
    BGE --> PQ
    PQ -->|"< MIN per chapter"| SUPP
    PQ & SUPP --> SEP
    SEP --> PER_CH
    PER_CH --> BUDGET
    BUDGET --> RC
    BUDGET --> CM
```

---

## 🏗️ Infrastructure Overview

```mermaid
graph TB
    subgraph BACKEND["Backend (FastAPI + Uvicorn)"]
        APP["main.py\nFastAPI app\nlifespan startup:\n• init_shared_checkpointer()\n• preload BGE-M3 model\n• connect Pinecone / Redis / PG"]
        subgraph ROUTERS["Routers"]
            R1["generate.py\n/generate, /status"]
            R2["exams.py\n/exams/{id}\n/approve-blueprint\n/submit-review"]
            R3["documents.py\n/documents"]
            R4["admin.py\n/admin/textbooks"]
        end
        WM["WebSocket Manager\n(manager.py)\nSSE broadcast per exam_id"]
    end

    subgraph WORKERS["Celery Workers"]
        W1["exam_task.py\ngenerate_exam_task\n• max_retries=3\n• retry_backoff=True\n• idempotency guard"]
        W2["document_task.py\nparse + chunk + embed"]
    end

    subgraph INFRA["Infrastructure"]
        REDIS2["Redis\n• Celery broker\n• Session cache\n• HITL keys\n• pub/sub channels"]
        PG2["PostgreSQL\n• Core tables\n• LangGraph checkpoints\n• Teacher preferences"]
        PINE2["Pinecone\n• Vector index\n• Per-doc namespaces\n• BGE-M3 1024-dim"]
        LANGFUSE2["Langfuse\n• LLM call tracing\n• Token cost tracking\n• Span hierarchy"]
    end

    APP --> ROUTERS
    APP --> WM
    ROUTERS --> REDIS2
    ROUTERS --> WORKERS
    WORKERS --> PG2
    WORKERS --> REDIS2
    WORKERS --> PINE2
    WORKERS --> LANGFUSE2
```

---

## 📋 Node Registry — Tất cả 29 nodes trong graph

| # | Node | Phase | Mô tả |
|---|------|-------|--------|
| 1 | `initialize` | Setup | Init ExamGraphState, set defaults |
| 2 | `clarification_check` | Clarification | LLM check: yêu cầu rõ chưa? |
| 3 | `emit_clarification` | Clarification | Emit WS event, → END |
| 4 | `load_long_term_memory` | Planning | Load teacher prefs từ Postgres |
| 5 | `decide_plan` | Planning | Count signals → simple / complex |
| 6 | `fanout_complex` | Planning | Passthrough → parallel fan-out |
| 7 | `plan_complex` | Planning | PlannerAgent.create_plan() |
| 8 | `retrieve_knowledge` | Planning | RetrievalAgent.retrieve() |
| 9 | `handle_retrieval_failure` | Error | Fallback → create_outline (empty ctx) |
| 10 | `merge_plan_retrieval` | Planning | Merge plan + retrieved context |
| 11 | `dispatch_tasks` | Planning | Process dynamic task_queue |
| 12 | `create_outline` | Blueprint | OutlineAgent.create_outline() |
| 13 | `handle_outline_failure` | Error | → END |
| 14 | `emit_checkpoint_1` | HITL-1 | Emit blueprint preview event |
| 15 | `wait_for_blueprint_approval` | HITL-1 | `interrupt()` ⏸ Redis pub/sub poll |
| 16 | `build_questions` | Generation | BuilderAgent.build() |
| 17 | `handle_builder_failure` | Error | → emit_checkpoint_2 |
| 18 | `validate_questions` | Validation | ValidatorAgent.validate() batched |
| 19 | `check_validation_result` | Validation | Route: passed / retry / max_exceeded |
| 20 | `retry_builder` | Retry (G9) | Increment counter, pass issues |
| 21 | `handle_max_retries_exceeded` | Error | → emit_checkpoint_2 |
| 22 | `emit_checkpoint_2` | HITL-2 | Emit questions preview event |
| 23 | `wait_for_review` | HITL-2 | `interrupt()` ⏸ Redis poll |
| 24 | `save_teacher_preferences` | Finalize | LongTermMemory.save() → Postgres |
| 25 | `emit_checkpoint_3` | Finalize | Emit completion event |
| 26 | `finalize_output` | Finalize | update_questions() → DB, → END ✅ |
| 27 | `finalize_with_feedback` | Finalize | Save feedback, → END |
| 28 | `handle_timeout` | Error | → END |
| 29 | `dispatch_tasks` | Planning | Dynamic task queue execution |

---

> **Nguồn**: Quét trực tiếp từ `graph/builder.py`, `graph/nodes/__init__.py`, `orchestrator.py`, `retrieval.py`, `outline.py`, `validator.py`, `planner.py`, `memory/short_term.py`, `memory/long_term.py`, `guardrails.py`, `tasks/exam_task.py`, `websocket/manager.py`
