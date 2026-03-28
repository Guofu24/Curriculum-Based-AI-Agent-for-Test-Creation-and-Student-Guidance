# Đặc Tả Kỹ Thuật: Curriculum-Based AI Agent for Test Creation

**Phiên bản:** 2.0  
**Ngày:** 2025  
**Loại tài liệu:** Technical Blueprint + Implementation Spec  
**Changelog v2.0:** Bổ sung Agent Skills Library, Memory Layer, Agent Communication Contract, Guardrails, Planner Agent, HITL Checkpoint bổ sung, Observability & Cost Tracking.

---

## Mục Lục

1. [Tổng Quan Hệ Thống](#1-tổng-quan-hệ-thống)
2. [Kiến Trúc Multi-Agent](#2-kiến-trúc-multi-agent)
3. [RAG Pipeline & Chunking Strategy](#3-rag-pipeline--chunking-strategy)
4. [API & System Design](#4-api--system-design)
5. [UI/UX Flow & Human-in-the-Loop](#5-uiux-flow--human-in-the-loop)
6. [Observability & Cost Tracking](#6-observability--cost-tracking)
7. [Tính Năng Phụ](#7-tính-năng-phụ)
8. [Tech Stack Đề Xuất](#8-tech-stack-đề-xuất)
9. [Rủi Ro & Giảm Thiểu](#9-rủi-ro--giảm-thiểu)

---

## 1. Tổng Quan Hệ Thống

### 1.1 Mục Tiêu

Xây dựng hệ thống **multi-agent AI** cho phép giảng viên:
- Upload tài liệu giảng dạy (PDF, DOCX, PPTX) và lưu trữ dài hạn có bảo mật
- Tự động sinh đề kiểm tra từ tài liệu theo scope, loại câu hỏi, và Bloom's Taxonomy
- Xem trước, chỉnh sửa trực tiếp hoặc qua prompt trước khi xuất bản
- Quản lý lịch sử sinh đề

### 1.2 Đối Tượng Người Dùng

| Vai trò | Hành động chính |
|---|---|
| Giảng viên | Upload tài liệu, cấu hình đề, review/edit, xuất đề |
| Admin | Quản lý tài khoản, tài liệu, quota |

### 1.3 Luồng Tổng Quát

```
[Giảng viên Upload] → [RAG Pipeline xử lý] → [Lưu Vector DB]
        ↓
[Chọn tài liệu + Scope + Cấu hình đề]
        ↓
[Orchestrator Agent nhận yêu cầu]
        ↓
[Planner Agent lên dynamic plan]
        ↓
[Sub-agents: Retrieve → Outline → (HITL Checkpoint 1) → Build → Validate]
        ↓
[Human-in-the-loop: Preview → Edit/Approve]
        ↓
[Xuất đề (PDF/DOCX)]
```

---

## 2. Kiến Trúc Multi-Agent

### 2.1 Sơ Đồ Tổng Thể

```
┌─────────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR AGENT                          │
│  - Nhận yêu cầu từ giảng viên                                   │
│  - Rewrite & clarify requirements                               │
│  - Điều phối toàn bộ pipeline                                   │
│  - Human-in-the-loop checkpoints (x3)                           │
└──────────┬──────────────────────────────────────────────────────┘
           │  calls as tools
    ┌──────▼──────────────────────────────────────────────────────┐
    │                   PLANNER AGENT                             │
    │  - Phân tích yêu cầu phức tạp → lên dynamic execution plan │
    │  - Quyết định bước nào skip / loop / tăng web_search calls  │
    └──────┬──────────────────────────────────────────────────────┘
           │  dispatches
    ┌──────▼──────────────────────────────────────────┐
    │                                                 │
    ▼              ▼               ▼           ▼      │
[RETRIEVAL    [OUTLINE        [BUILDER    [VALIDATOR   │
 AGENT]        AGENT]          AGENT]      AGENT]      │
    │              │               │           │       │
    └──────────────┴───────────────┴───────────┘       │
                   │  shared skills via Skills Library  │
        ┌──────────▼──────────────────────────┐        │
        │          SKILLS LIBRARY             │        │
        │  bloom_classifier  | scope_checker  │        │
        │  latex_renderer    | dedup_checker  │        │
        │  difficulty_estimator               │        │
        └─────────────────────────────────────┘        │
                                                        │
        ┌───────────────────────────────────────────────┘
        │  MEMORY LAYER
        │  In-context (passed per call)
        │  Short-term  → Redis TTL 2h (chat history)
        │  Long-term   → PostgreSQL (teacher preferences)
        └──────────────────────────────────────────────
```

---

### 2.2 Chi Tiết Từng Agent

---

#### 🟦 Agent 0: Orchestrator Agent

**Vai trò:** Quản lý toàn bộ pipeline sinh đề. Đây là agent duy nhất tương tác trực tiếp với người dùng. Các sub-agent được expose như **tools** của Orchestrator.

**Trigger:** Giảng viên submit yêu cầu tạo đề

**Input:**
```json
{
  "user_id": "string",
  "document_id": "string",
  "scope": ["Chương 1", "Chương 2", "Chương 3"],
  "exam_type": "mixed",             // "mcq" | "essay" | "mixed"
  "mcq_count": 40,
  "essay_count": 5,
  "bloom_distribution": {
    "nhan_biet": 20,
    "thong_hieu": 30,
    "van_dung": 30,
    "van_dung_cao": 20
  },
  "user_prompt": "Tạo đề kiểm tra 1 tiết môn Vật lý 11...",
  "extra_instructions": "..."
}
```

**Output:** Đề hoàn chỉnh đã qua validate + plan reasoning stream

**Hành vi đặc biệt:**
- Nếu yêu cầu người dùng **chưa rõ**: Tự động sinh ≤3 câu hỏi làm rõ trước khi gọi bất kỳ tool nào
- **Rewrite requirement**: Sau khi hiểu đủ, diễn giải lại yêu cầu bằng structured format và confirm với giảng viên
- **Streaming plan**: Hiển thị real-time kế hoạch ("Đang phân tích scope... → Đang lập sườn đề... → Đang sinh câu hỏi...")
- Không tự gọi LLM trực tiếp để sinh câu hỏi — toàn bộ thực hiện qua tool calls

**Tools (sub-agents) được expose:**
| Tool name | Maps to | Ghi chú |
|---|---|---|
| `tool_plan_execution` | Planner Agent | Gọi đầu tiên với yêu cầu phức tạp |
| `tool_retrieve_context` | Retrieval Agent | |
| `tool_outline_exam` | Outline Agent | |
| `tool_build_questions` | Builder Agent | |
| `tool_validate_exam` | Validator Agent | |

---

#### 🟩 Agent 1: Retrieval Agent

**Vai trò:** Truy vấn vector database để lấy đúng nội dung kiến thức theo scope được chọn. Output là raw knowledge context cho Outline Agent.

**Input:**
```json
{
  "document_id": "string",
  "scope_chapters": ["Chương 1", "Chương 2"],
  "bloom_targets": ["van_dung", "van_dung_cao"],
  "query_hints": ["động lực học", "định luật Newton"]
}
```

**Output:**
```json
{
  "retrieved_chunks": [
    {
      "chunk_id": "string",
      "chapter": "Chương 1",
      "section": "1.2 Định luật Newton",
      "content": "...",
      "content_type": "text|formula|image_description",
      "relevance_score": 0.92
    }
  ],
  "coverage_map": {
    "Chương 1": ["1.1", "1.2", "1.3"],
    "Chương 2": ["2.1", "2.2"]
  }
}
```

**Cơ chế retrieval:**
1. Với mỗi chapter trong scope → query riêng trong namespace tương ứng (1 chapter = 1 Pinecone namespace)
2. **Semantic search** bằng embedding (text-embedding-3-large)
3. **LLM Reranking**: Sau semantic search, dùng LLM nhỏ (GPT-4o-mini) rerank top-20 kết quả → giữ top-8
4. **Query expansion**: Từ bloom target và chapter, tự sinh thêm 3-5 query variants để tăng recall
5. Spawn **parallel sub-queries** (1 per chapter) → thu thập song song → gộp kết quả

**Ràng buộc quan trọng:**
- Chỉ retrieve trong namespace của scope đã chọn — tuyệt đối không lấy ngoài scope
- Đánh dấu `content_type` rõ ràng để Builder Agent xử lý đúng (formula cần render LaTeX, image cần mô tả VLM)

---

#### 🟨 Agent 2: Outline Agent

**Vai trò:** Từ knowledge context, lập **sườn đề** (blueprint) — phân bổ câu hỏi theo Bloom, theo chapter, theo phần (MCQ/Essay), đảm bảo không tập trung quá vào một chủ đề.

**Input:**
```json
{
  "retrieved_context": "<output từ Retrieval Agent>",
  "exam_config": {
    "mcq_count": 40,
    "essay_count": 5,
    "bloom_distribution": { "nhan_biet": 20, "thong_hieu": 30, "van_dung": 30, "van_dung_cao": 20 },
    "scope": ["Chương 1", "Chương 2", "Chương 3"]
  }
}
```

**Output — Exam Blueprint:**
```json
{
  "blueprint": [
    {
      "question_id": "MCQ_001",
      "type": "mcq",
      "bloom_level": "thong_hieu",
      "chapter": "Chương 1",
      "section": "1.2",
      "topic_hint": "Định luật 2 Newton - áp dụng F=ma",
      "content_type": "calculation",
      "estimated_difficulty": 0.4
    },
    {
      "question_id": "ESSAY_001",
      "type": "essay",
      "bloom_level": "van_dung_cao",
      "chapter": "Chương 2",
      "section": "2.3",
      "topic_hint": "Bài toán hệ vật kết hợp lực ma sát và gia tốc",
      "content_type": "applied_problem",
      "estimated_difficulty": 0.85
    }
  ],
  "distribution_summary": {
    "by_bloom": { "nhan_biet": 8, "thong_hieu": 12, "van_dung": 12, "van_dung_cao": 8 },
    "by_chapter": { "Chương 1": 15, "Chương 2": 15, "Chương 3": 10 }
  }
}
```

**Logic phân bổ:**
- Bloom distribution theo % người dùng chọn → convert sang số câu → làm tròn hợp lệ
- Câu hỏi phân bổ đều các chapter (không để 1 chapter chiếm >50%)
- Với `van_dung_cao`: ưu tiên chapters có nhiều công thức và bài toán phức hợp

---

#### 🟥 Agent 3: Builder Agent

**Vai trò:** Nhận blueprint từ Outline Agent → sinh câu hỏi thực tế từng slot, có thể gọi web search tool cho bài toán vận dụng cao.

**Input:** Blueprint + retrieved_context (passed through từ Orchestrator)

**Output:**
```json
{
  "questions": [
    {
      "question_id": "MCQ_001",
      "stem": "Một vật có khối lượng 5kg chịu lực 20N. Gia tốc của vật là?",
      "options": {
        "A": "2 m/s²",
        "B": "4 m/s²",
        "C": "10 m/s²",
        "D": "100 m/s²"
      },
      "correct_answer": "B",
      "explanation": "Theo F = ma → a = F/m = 20/5 = 4 m/s²",
      "bloom_level": "thong_hieu",
      "chapter": "Chương 1",
      "latex_content": "F = ma \\Rightarrow a = \\frac{F}{m} = \\frac{20}{5} = 4 \\text{ m/s}^2"
    }
  ]
}
```

**Cơ chế sinh câu hỏi:**
- Sinh theo **chunk**: Mỗi lần gọi LLM sinh 5-10 câu (tránh overflow context window)
- Mỗi chunk nhận: blueprint slot + relevant context chunks + yêu cầu Bloom cụ thể
- Câu hỏi **không được lặp chủ đề** với câu trước đó (Orchestrator truyền danh sách topic đã dùng)
- Với `van_dung_cao`: gọi thêm `web_search_tool` tìm bài toán tương tự → LLM adapt vào kiến thức scope
- Formula render: luôn output song song dạng text + LaTeX

**Ràng buộc:**
- Đáp án MCQ phải có 4 lựa chọn, chỉ 1 đáp án đúng, 3 mồi nhử có logic (không quá lộ liễu)
- Câu tự luận phải có rubric chấm điểm rõ ràng

---

#### 🟪 Agent 4: Validator Agent

**Vai trò:** Đây là agent **"phản biện"** — đọc toàn bộ đề đã sinh ra và thực hiện 3 nhiệm vụ kiểm tra.

**Input:** Toàn bộ câu hỏi từ Builder Agent + exam_config gốc

**Output:**
```json
{
  "validation_passed": false,
  "issues": [
    {
      "question_id": "MCQ_015",
      "issue_type": "wrong_answer",
      "detail": "Đáp án B tính ra 3.5 m/s² nhưng mark là A",
      "suggestion": "Sửa đáp án thành B"
    },
    {
      "question_id": "ESSAY_003",
      "issue_type": "bloom_mismatch",
      "detail": "Câu này chỉ ở mức nhận biết, cần nâng lên vận dụng cao",
      "suggestion": "Thêm điều kiện phức hợp vào bài toán"
    }
  ],
  "score_attempt": {
    "MCQ_001": { "model_answer": "B", "correct": true },
    "MCQ_015": { "model_answer": "B", "expected": "A", "correct": false }
  },
  "bloom_compliance": {
    "nhan_biet": { "expected": 20, "actual": 18, "ok": false },
    "van_dung_cao": { "expected": 20, "actual": 22, "ok": true }
  },
  "scope_violation": [],
  "approved_for_publish": false
}
```

**3 Nhiệm vụ kiểm tra:**

**① Giải đề (Answer Checking)**
- Dùng LLM mạnh (GPT-4o hoặc Claude Opus) **thực sự giải từng câu**
- So sánh đáp án model với đáp án Builder Agent đề xuất
- Câu sai → flag để Builder Agent sinh lại

**② Bloom Compliance Check**
- Kiểm tra từng câu có thực sự ở Bloom level đã khai báo không
- Rubric đánh giá Bloom level được pre-define trong system prompt của Validator
- Nếu lệch >2 câu so với phân bổ yêu cầu → trigger regenerate

**③ Scope Violation Check**
- Kiểm tra câu hỏi có dùng kiến thức ngoài scope không
- Đánh giá hallucination: kiến thức trong câu có xuất hiện trong retrieved_context không

**Retry Logic:**
- Nếu validation fail → Orchestrator gọi lại Builder Agent với danh sách issues cụ thể
- Tối đa **3 vòng retry** trước khi trả về partial result với warning

---

### 2.3 Planner Agent (Dynamic Planning)

**Vai trò:** Layer trung gian giữa Orchestrator và các sub-agents. Thay vì Orchestrator gọi sub-agent theo thứ tự cố định, Planner Agent phân tích yêu cầu và lên **dynamic execution plan** — quyết định bước nào cần thiết, bước nào có thể skip, bước nào cần lặp lại.

**Khi nào Orchestrator gọi Planner:**
- Yêu cầu có prompt phức tạp (ví dụ: "Tập trung nhiều bài toán thực tế, ít lý thuyết, câu vận dụng cao phải có số liệu thực")
- Yêu cầu chỉnh sửa hàng loạt qua prompt (ví dụ: "Làm lại toàn bộ phần tự luận theo hướng khác")
- Yêu cầu đơn giản → Orchestrator tự dispatch trực tiếp, không cần Planner

**Input:**
```json
{
  "user_request_parsed": "...",
  "exam_config": { "..." },
  "available_tools": ["tool_retrieve_context", "tool_outline_exam", "tool_build_questions", "tool_validate_exam"],
  "constraints": {
    "max_web_search_calls": 10,
    "token_budget": 50000
  }
}
```

**Output — Execution Plan:**
```json
{
  "plan": [
    {
      "step": 1,
      "tool": "tool_retrieve_context",
      "params_override": { "bloom_targets": ["van_dung", "van_dung_cao"] },
      "note": "Tăng focus vào van_dung theo yêu cầu"
    },
    {
      "step": 2,
      "tool": "tool_outline_exam",
      "params_override": {},
      "note": "Standard outline"
    },
    {
      "step": 3,
      "tool": "tool_build_questions",
      "params_override": {
        "web_search_quota": 8,
        "prefer_applied_problems": true
      },
      "note": "Tăng web_search calls vì user muốn bài toán thực tế nhiều"
    },
    {
      "step": 4,
      "tool": "tool_validate_exam",
      "params_override": {},
      "note": "Standard validate"
    }
  ],
  "estimated_token_cost": 38000,
  "hitl_checkpoint_after_step": 2
}
```

**Lợi ích so với hardcoded pipeline:**
- Linh hoạt với prompt phức tạp mà không cần sửa code
- Planner có thể quyết định tăng/giảm `web_search_quota` động
- Có thể thêm bước loop (ví dụ: retrieve thêm 1 lần nếu coverage_map không đủ)

---

### 2.4 Agent Skills Library

Skills là các **capability module độc lập**, tái sử dụng được bởi nhiều agent khác nhau. Mỗi skill là 1 function/class có interface chuẩn, nhận input → trả output có schema định nghĩa rõ.

**Tại sao cần Skills Library:**
- Tránh duplicate logic giữa Builder và Validator (cả 2 cần đánh giá Bloom)
- Đảm bảo consistency — cùng 1 logic bloom classification cho cả pipeline
- Dễ unit test độc lập từng skill

---

#### Skill 1: `bloom_classifier_skill`

**Dùng bởi:** Builder Agent (tự check trước khi output), Validator Agent (verify)

**Input:**
```python
{
  "question_stem": "Một vật chịu lực F=20N, khối lượng m=5kg. Tính gia tốc.",
  "question_type": "mcq",
  "subject": "physics"
}
```

**Output:**
```python
{
  "bloom_level": "thong_hieu",
  "confidence": 0.87,
  "reasoning": "Câu hỏi yêu cầu áp dụng công thức đã học vào tình huống cho sẵn — đây là mức Thông hiểu/Vận dụng thấp"
}
```

**Bloom Rubric (pre-defined trong skill system prompt):**

| Mức | Từ khóa nhận diện | Đặc điểm câu hỏi Vật lý |
|---|---|---|
| Nhận biết | Định nghĩa, liệt kê, nêu tên | Hỏi thẳng khái niệm/công thức |
| Thông hiểu | Giải thích, so sánh, phân biệt | Áp dụng công thức 1 bước trực tiếp |
| Vận dụng | Tính toán, giải, xác định | Bài toán 2-3 bước, có điều kiện |
| Vận dụng cao | Phân tích, đánh giá, thiết kế | Bài toán phức hợp, nhiều công thức, số liệu thực tế |

---

#### Skill 2: `scope_checker_skill`

**Dùng bởi:** Validator Agent

**Input:**
```python
{
  "question_stem": "...",
  "retrieved_context_ids": ["chunk_001", "chunk_002"],
  "scope_chapters": ["Chương 1", "Chương 2"]
}
```

**Output:**
```python
{
  "in_scope": true,
  "violation_type": null,
  "evidence_chunk_ids": ["chunk_001"],
  "confidence": 0.91
}
```

**Logic:** So sánh kiến thức trong câu hỏi với metadata của retrieved chunks. Nếu câu hỏi reference khái niệm không có trong bất kỳ chunk nào của scope → flag violation.

---

#### Skill 3: `latex_renderer_skill`

**Dùng bởi:** Builder Agent, Retrieval Agent

**Input:**
```python
{ "raw_formula": "F = m*a", "context": "Định luật 2 Newton" }
```

**Output:**
```python
{
  "latex": "F = ma",
  "display_latex": "\\[F = ma\\]",
  "unicode_fallback": "F = m·a"
}
```

---

#### Skill 4: `dedup_checker_skill`

**Dùng bởi:** Builder Agent (check trước khi output mỗi câu)

**Input:**
```python
{
  "new_question_topic": "Định luật 2 Newton - tính gia tốc",
  "existing_topics": ["Định luật 1 Newton", "Định luật 2 Newton - tính lực", "Ma sát trượt"]
}
```

**Output:**
```python
{
  "is_duplicate": true,
  "duplicate_with": "Định luật 2 Newton - tính lực",
  "similarity_score": 0.78,
  "suggestion": "Chuyển sang Định luật 3 Newton hoặc ứng dụng khác"
}
```

---

#### Skill 5: `difficulty_estimator_skill`

**Dùng bởi:** Outline Agent (ước lượng khi lập blueprint), Validator Agent (verify)

**Input:**
```python
{
  "question_stem": "...",
  "bloom_level": "van_dung_cao",
  "solution_steps": 4
}
```

**Output:**
```python
{
  "difficulty_score": 0.82,   // 0.0 = rất dễ, 1.0 = rất khó
  "estimated_solve_time_minutes": 8,
  "complexity_factors": ["multi-formula", "conditional", "requires_calculus"]
}
```

---

### 2.5 Memory Layer

Hệ thống cần 3 loại memory riêng biệt. Thiếu bất kỳ loại nào sẽ gây lỗi nghiêm trọng (agent quên yêu cầu ban đầu khi chỉnh sửa, không nhớ topic đã dùng, ...).

| Loại | Mục đích | Lưu ở đâu | TTL |
|---|---|---|---|
| **In-context memory** | Topics đã dùng trong phiên generate hiện tại, danh sách issues từ Validator | Passed trực tiếp qua Orchestrator mỗi lần gọi tool | Hết khi session kết thúc |
| **Short-term memory** | Conversation history khi giảng viên chat chỉnh sửa, exam_config gốc | Redis | 2 giờ |
| **Long-term memory** | Preference của giảng viên (style câu hỏi, bloom distribution hay dùng, môn học) | PostgreSQL `teacher_preferences` | Vĩnh viễn |

**Schema Short-term (Redis):**
```
Key: session:{exam_id}:{user_id}
Value (JSON):
{
  "exam_config_original": { ... },
  "topics_used": ["Định luật Newton", "Ma sát", ...],
  "conversation_history": [
    { "role": "user", "content": "Sửa câu 15 tăng độ khó" },
    { "role": "assistant", "content": "Đã cập nhật câu 15..." }
  ],
  "retry_count": 1
}
TTL: 7200 (2 giờ)
```

**Schema Long-term (PostgreSQL):**
```sql
CREATE TABLE teacher_preferences (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    preferred_bloom_distribution JSONB,  -- bloom dist hay dùng nhất
    preferred_exam_types JSONB,          -- mcq/essay/mixed tỉ lệ nào
    subject_focus VARCHAR(100),          -- "physics", "math", ...
    style_notes TEXT,                    -- agent tự ghi chú style preference
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id)
);
```

**Cách Orchestrator sử dụng memory khi chỉnh sửa qua prompt:**
```
Nhận prompt chỉnh sửa từ giảng viên
    │
    ▼
Load từ Redis: exam_config_original + conversation_history + topics_used
    │
    ▼
Build context cho LLM:
  [System]: Đây là exam_config gốc: {...}. Topics đã dùng: [...]
  [History]: <conversation_history>
  [User]: <prompt chỉnh sửa mới>
    │
    ▼
Agent xử lý với đầy đủ context → không bị quên yêu cầu ban đầu
```

---

### 2.6 Agent Communication Contract

Mỗi tool call giữa Orchestrator và sub-agent phải tuân theo contract nghiêm ngặt. Dùng **Pydantic models** để validate input/output tại runtime.

**Base classes:**
```python
from pydantic import BaseModel
from typing import Optional, List
from enum import Enum

class AgentStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"       # hoàn thành nhưng có warnings
    FAILED = "failed"         # không thể hoàn thành
    RETRY_NEEDED = "retry"    # cần thử lại với thông tin khác

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
    trace_id: str             # dùng cho observability

# Mỗi agent extend class này
class BuilderAgentOutput(AgentBaseOutput):
    questions: List[Question]
    topics_used: List[str]
    chunks_referenced: List[str]

class ValidatorAgentOutput(AgentBaseOutput):
    validation_passed: bool
    issues: List[ValidationIssue]
    score_attempt: dict
    bloom_compliance: dict
    scope_violations: List[str]
    approved_for_publish: bool
```

**Timeout & Fallback Policy:**

| Agent | Timeout | Fallback khi fail |
|---|---|---|
| Retrieval Agent | 30s | Trả về empty context + warning, Orchestrator hỏi user |
| Outline Agent | 20s | Dùng default distribution template |
| Builder Agent | 120s per chunk | Skip chunk đó, đánh dấu warning |
| Validator Agent | 60s | Trả về partial validation, flag manual review |
| Planner Agent | 15s | Dùng hardcoded default plan |

**Error Propagation:**
```python
# Orchestrator xử lý failed sub-agent
if output.status == AgentStatus.FAILED:
    if agent_name == "retrieval":
        # Critical — không thể tiếp tục
        raise OrchestratorError("Không thể lấy dữ liệu từ tài liệu. Vui lòng thử lại.")
    elif agent_name == "validator":
        # Non-critical — vẫn trả về đề nhưng có warning
        emit_warning("Validation không hoàn chỉnh. Hãy review kỹ trước khi xuất bản.")
```

---

### 2.7 Guardrails

Guardrails chạy **inline** trong Builder Agent — không đợi đến Validator Agent mới phát hiện lỗi. Mục đích là fail fast, tiết kiệm token.

**① Output Parser với Auto-retry:**
```python
import instructor
from openai import OpenAI

client = instructor.from_openai(OpenAI())

# Instructor tự động retry nếu LLM output sai format
question = client.chat.completions.create(
    model="gpt-4o",
    response_model=MCQQuestion,   # Pydantic model
    max_retries=3,
    messages=[...]
)
# Nếu sau 3 lần vẫn sai → raise ParseError → Orchestrator xử lý
```

**② Token Budget Guard:**
```python
class TokenBudgetGuard:
    def __init__(self, total_budget: int):
        self.budget = total_budget
        self.used = 0

    def check_before_call(self, estimated_tokens: int):
        if self.used + estimated_tokens > self.budget * 0.9:
            # Còn <10% budget → flush chunk hiện tại, bắt đầu chunk mới
            return "flush_needed"
        return "ok"

    def record_usage(self, actual_tokens: int):
        self.used += actual_tokens
```

**③ Content Filter:**

Sau khi Builder Agent sinh câu hỏi, chạy qua filter trước khi trả về Orchestrator:

```python
CONTENT_FILTER_RULES = [
    # Câu hỏi phải liên quan đến môn học
    lambda q: len(q.stem) > 20,
    # Không được có đáp án trùng nhau trong MCQ
    lambda q: len(set(q.options.values())) == 4 if q.type == "mcq" else True,
    # Đáp án đúng phải nằm trong danh sách options
    lambda q: q.correct_answer in q.options if q.type == "mcq" else True,
    # Câu hỏi không được chứa thông tin đáp án lộ liễu trong stem
    lambda q: q.correct_answer.lower() not in q.stem.lower()
]
```

**④ Scope Guard (inline):**

Trước khi Builder Agent sinh câu, Orchestrator truyền vào danh sách `allowed_concepts` extract từ retrieved_context. Builder Agent được instruct trong system prompt: "Chỉ sinh câu hỏi dựa trên các khái niệm sau: {allowed_concepts}. Không được đưa thêm kiến thức ngoài danh sách này."

---

### 2.8 Luồng Gọi Chi Tiết

```
User Request
    │
    ▼
Orchestrator: Parse & Clarify
    │
    ├─► [Nếu chưa rõ] → Hỏi giảng viên (≤3 câu) → Nhận câu trả lời → tiếp tục
    │
    ▼
Orchestrator: Rewrite Requirements → Confirm với giảng viên
    │
    ▼
Load Long-term Memory (teacher_preferences từ DB)
    │
    ▼
[Nếu prompt phức tạp] → tool_plan_execution (Planner Agent)
[Nếu đơn giản]        → dùng default plan, skip Planner
    │
    ▼
tool_retrieve_context (Retrieval Agent)
    │ parallel queries per chapter
    │ Skills dùng: latex_renderer_skill (cho formula chunks)
    │
    ▼
tool_outline_exam (Outline Agent)
    │ → Exam Blueprint
    │ Skills dùng: bloom_classifier_skill, difficulty_estimator_skill
    │
    ▼
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ✅ HITL CHECKPOINT 1: Giảng viên review Blueprint
    - Xem phân bổ câu theo Bloom + chapter
    - Approve → tiếp tục  |  Reject → quay lại Outline
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    │
    ▼
tool_build_questions (Builder Agent)
    │ Sinh theo chunk (5-10 câu/lần)
    │ Skills dùng: bloom_classifier_skill, dedup_checker_skill,
    │              latex_renderer_skill, scope_checker_skill (inline guard)
    │ Guardrails: output_parser, token_budget_guard, content_filter
    │ web_search khi cần (van_dung_cao, theo quota từ Planner)
    │ Lưu topics_used vào Redis (short-term memory)
    │
    ▼
tool_validate_exam (Validator Agent)
    │ Skills dùng: bloom_classifier_skill, scope_checker_skill,
    │              difficulty_estimator_skill
    │
    ├─► [FAIL] → Orchestrator retry Builder với issues list (max 3 lần)
    │            Load issues từ Redis, append vào context
    │
    └─► [PASS] → Orchestrator trả về đề hoàn chỉnh
                    │
                    ▼
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ✅ HITL CHECKPOINT 2: Full Review Screen
    - Xem toàn bộ đề + Bloom distribution chart
    - Chỉnh sửa trực tiếp hoặc qua prompt
    - Prompt edit: load Redis session → build full context
    - Approve → bước tiếp
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    │
                    ▼
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ✅ HITL CHECKPOINT 3: Export Preview
    - Xem đề đúng format PDF/DOCX
    - Confirm → Export
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    │
                    ▼
             Update Long-term Memory
             (ghi lại preference của giảng viên)
```

---

## 3. RAG Pipeline & Chunking Strategy

### 3.1 Tổng Quan Pipeline Xử Lý Tài Liệu

Khi tài liệu được upload, hệ thống chạy qua pipeline sau:

```
[Upload File]
     │
     ▼
[Step 1: Document Parsing]     ← Marker (PDF) / python-docx / python-pptx
     │
     ▼
[Step 2: Structure Detection]  ← Heading tree + Section mapping
     │
     ▼
[Step 3: Content Extraction]
     ├── Text       → trực tiếp
     ├── Formula    → MathPix API hoặc Nougat → LaTeX
     └── Image      → GPT-4o Vision → text description
     │
     ▼
[Step 4: Semantic Chunking]    ← LlamaIndex SemanticSplitter
     │
     ▼
[Step 5: Embedding]            ← text-embedding-3-large (OpenAI)
     │
     ▼
[Step 6: Store to Pinecone]    ← Namespace = chapter_id
```

---

### 3.2 Document Parsing

**Công cụ theo loại file:**

| File type | Tool | Ghi chú |
|---|---|---|
| PDF (text) | **Marker** (open-source) | Giữ heading, table, formula tốt hơn PyMuPDF |
| PDF (scan) | Marker + OCR fallback | Marker tích hợp sẵn OCR qua Surya |
| DOCX | python-docx | Parse heading levels, tables |
| PPTX | python-pptx | Slide title = heading, body = content |

**Tại sao Marker thay vì PyMuPDF/pdfplumber?**
- Marker tự động nhận diện heading hierarchy
- Xử lý được multi-column layout
- Output là Markdown với heading tags giữ nguyên cấu trúc

---

### 3.3 Structure Detection — Heading Tree

Sau parsing, hệ thống xây dựng **heading tree** để biết mỗi chunk thuộc phần nào:

```
Document
├── Chương 1: Động lực học
│   ├── 1.1 Lực và phân loại lực
│   │   └── [chunks: text, formula, image]
│   ├── 1.2 Định luật Newton
│   │   └── [chunks: text, formula, image]
│   └── 1.3 Bài tập vận dụng
│       └── [chunks: text]
└── Chương 2: Năng lượng
    ├── 2.1 Công và công suất
    └── ...
```

**Cách xây heading tree:**
- Regex + font-size heuristics từ Marker output
- Dùng `outlinelevel` / heading tags trong Markdown Marker tạo ra
- Gán `chapter_id`, `section_id`, `subsection_id` cho từng đoạn

**Hiển thị cho người dùng:** Sau upload, UI render cây heading này để giảng viên chọn scope bài kiểm tra.

---

### 3.4 Content Extraction — Formula & Image

#### Formula (Công thức)

**Vấn đề:** Công thức có thể ở dạng:
- Text thường (ASCII): `F = m*a` → đơn giản, giữ nguyên
- Embedded LaTeX trong DOCX/PPTX → extract trực tiếp
- **Ảnh công thức** trong PDF → cần OCR đặc biệt

**Pipeline xử lý công thức ảnh:**
```
Detect formula region (heuristics: bounding box aspect ratio, pixel density)
    │
    ▼
[Nougat - Meta] → LaTeX string        ← Ưu tiên (offline, miễn phí)
    │
    ▼ (fallback nếu Nougat fail)
[MathPix API] → LaTeX string          ← Chính xác hơn, có cost
    │
    ▼
Lưu vào chunk với field: latex_representation
```

**Kết quả:** Mỗi formula chunk có:
```json
{
  "content_type": "formula",
  "text_repr": "F = ma",
  "latex_repr": "F = ma",
  "source_location": "Chương 1, trang 12"
}
```

#### Image (Hình ảnh)

Dùng **GPT-4o Vision** (hoặc Claude 3.5 Sonnet Vision) để generate mô tả:

**Prompt system cho Vision model:**
```
Bạn là assistant mô tả hình ảnh trong sách giáo khoa vật lý.
Mô tả hình ảnh một cách chính xác, bao gồm:
- Loại hình (đồ thị, sơ đồ, hình minh họa thực nghiệm, ...)
- Các đại lượng vật lý có trong hình
- Mô tả ngắn gọn nội dung cần truyền đạt
Trả về dưới dạng text thuần, không dùng markdown.
```

**Kết quả:** Image chunk có text description → embeddable như text thường.

---

### 3.5 Semantic Chunking

**Công cụ:** LlamaIndex `SemanticSplitterNodeParser`

**Tại sao Semantic Chunking thay vì Fixed-size?**
- Fixed-size chunking cắt giữa câu, giữa công thức → mất context
- Semantic chunking giữ nguyên ý nghĩa của đoạn văn

**Config:**
```python
from llama_index.core.node_parser import SemanticSplitterNodeParser

splitter = SemanticSplitterNodeParser(
    buffer_size=1,
    breakpoint_percentile_threshold=95,
    embed_model=embedding_model,
)
```

**Metadata gắn vào mỗi chunk:**
```python
{
    "chunk_id": "doc_{doc_id}_ch1_sec1.2_001",
    "document_id": "string",
    "chapter": "Chương 1",
    "chapter_id": "ch1",
    "section": "1.2 Định luật Newton",
    "section_id": "ch1_sec1.2",
    "content_type": "text|formula|image_description",
    "page_number": 12,
    "latex_repr": "...",      # chỉ khi content_type = formula
}
```

---

### 3.6 Vector Database — Pinecone

**Lý do chọn Pinecone:**
- Managed service — không cần tự host
- Hỗ trợ **namespaces** → mỗi chapter = 1 namespace → retrieval đúng scope
- Serverless plan phù hợp MVP, scale dễ

**Schema lưu trữ:**

```
Index: curriculum_ai
├── Namespace: {doc_id}_ch1          ← Chương 1
├── Namespace: {doc_id}_ch2          ← Chương 2
├── Namespace: {doc_id}_ch3          ← Chương 3
└── ...
```

**Mỗi vector entry:**
```json
{
  "id": "doc_abc123_ch1_sec1.2_001",
  "values": [0.021, -0.043, ...],
  "metadata": {
    "document_id": "abc123",
    "chapter": "Chương 1",
    "section": "1.2 Định luật Newton",
    "content_type": "formula",
    "text": "Định luật 2 Newton: F = ma...",
    "latex_repr": "F = ma"
  }
}
```

**Retrieval strategy:**
```
Input scope: [Chương 1, Chương 2]
    │
    ├── Query namespace: {doc_id}_ch1 → top-20 kết quả
    └── Query namespace: {doc_id}_ch2 → top-20 kết quả
            │
            ▼
    LLM Reranking (GPT-4o-mini) → top-8 per chapter
            │
            ▼
    Merge & deduplicate → trả về Retrieval Agent
```

---

### 3.7 Lưu Trữ File Gốc

**Vấn đề:** Lưu file gốc ở local là thiếu bảo mật và không scale.

**Giải pháp đề xuất: AWS S3 + presigned URLs**

```
Upload flow:
User → Backend API → AWS S3 (private bucket)
                       │
                       └── Presigned URL (TTL: 1 giờ) → trả về client để download

Metadata lưu ở PostgreSQL:
{
  "file_id": "uuid",
  "user_id": "uuid",
  "original_filename": "vatly11_chuong1.pdf",
  "s3_key": "uploads/user_abc/file_xyz.pdf",
  "file_type": "pdf",
  "processing_status": "completed|processing|failed",
  "heading_tree": {...},
  "uploaded_at": "timestamp"
}
```

**Bảo mật:**
- S3 bucket policy: **không public** — chỉ backend có quyền đọc
- Presigned URL hết hạn sau 1 giờ
- Mỗi user chỉ access được file của mình (check `user_id` trong backend)

---

## 4. API & System Design

### 4.1 Kiến Trúc Backend

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                │
└──────────────────┬──────────────────────────────────┘
                   │ REST + WebSocket (streaming)
┌──────────────────▼──────────────────────────────────┐
│                FastAPI Backend                       │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Auth     │  │ Document     │  │ Exam          │  │
│  │ Module   │  │ Module       │  │ Module        │  │
│  └──────────┘  └──────────────┘  └───────────────┘  │
└──────┬────────────────────────────────────┬──────────┘
       │                                    │
┌──────▼──────┐                    ┌────────▼────────┐
│ PostgreSQL  │                    │  Celery Worker  │
│ (metadata,  │                    │  (RAG pipeline, │
│  users,     │                    │   agent calls)  │
│  exam hist) │                    └────────┬────────┘
└─────────────┘                             │
                                   ┌────────▼────────┐
                             ┌─────┤   Redis Queue   │
                             │     └─────────────────┘
                             │
                    ┌────────▼────────────────────────┐
                    │         External Services        │
                    │  Pinecone │ OpenAI │ AWS S3      │
                    └─────────────────────────────────┘
```

---

### 4.2 API Endpoints

#### Auth

| Method | Endpoint | Mô tả |
|---|---|---|
| POST | `/api/v1/auth/register` | Đăng ký tài khoản |
| POST | `/api/v1/auth/login` | Đăng nhập → trả JWT |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| POST | `/api/v1/auth/logout` | Invalidate refresh token |

**JWT Strategy:**
- Access token: TTL 15 phút
- Refresh token: TTL 7 ngày, lưu trong HttpOnly cookie
- Refresh token rotation: mỗi lần refresh → cấp token mới, thu hồi token cũ
- Lưu refresh token hash trong PostgreSQL để revoke

#### Document

| Method | Endpoint | Mô tả |
|---|---|---|
| POST | `/api/v1/documents/upload` | Upload file → trigger RAG pipeline |
| GET | `/api/v1/documents` | Danh sách tài liệu của user |
| GET | `/api/v1/documents/{id}` | Chi tiết + heading tree |
| DELETE | `/api/v1/documents/{id}` | Xóa tài liệu + vectors |
| GET | `/api/v1/documents/{id}/status` | Trạng thái xử lý pipeline |

#### Exam

| Method | Endpoint | Mô tả |
|---|---|---|
| POST | `/api/v1/exams/generate` | Tạo đề mới (async job) |
| GET | `/api/v1/exams/{id}` | Lấy đề đã generate |
| PATCH | `/api/v1/exams/{id}/questions/{qid}` | Sửa trực tiếp 1 câu hỏi |
| POST | `/api/v1/exams/{id}/edit-prompt` | Chỉnh sửa qua prompt |
| POST | `/api/v1/exams/{id}/regenerate` | Generate lại toàn bộ đề |
| POST | `/api/v1/exams/{id}/export` | Xuất đề (PDF/DOCX) |
| GET | `/api/v1/exams` | Lịch sử đề |

#### Streaming (WebSocket)

```
WS /api/v1/exams/stream/{job_id}

Server → Client events:
{
  "type": "plan_step",
  "message": "Đang lấy kiến thức từ Chương 1...",
  "step": 1,
  "total_steps": 5
}

{
  "type": "question_generated",
  "question_id": "MCQ_001",
  "question": { ... }
}

{
  "type": "validation_result",
  "passed": true,
  "issues_count": 0
}

{
  "type": "completed",
  "exam_id": "exam_xyz"
}
```

---

### 4.3 Database Schema

```sql
-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'teacher',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Refresh tokens
CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    revoked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Documents
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    original_filename VARCHAR(500) NOT NULL,
    file_type VARCHAR(10) NOT NULL,       -- pdf, docx, pptx
    s3_key VARCHAR(1000) NOT NULL,
    processing_status VARCHAR(50) DEFAULT 'pending',  -- pending|processing|completed|failed
    heading_tree JSONB,                   -- cây heading đã parse
    total_chapters INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Exams
CREATE TABLE exams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id),
    title VARCHAR(500),
    scope JSONB,                          -- ["Chương 1", "Chương 2"]
    exam_config JSONB,                    -- bloom dist, counts, ...
    questions JSONB,                      -- toàn bộ câu hỏi
    status VARCHAR(50) DEFAULT 'draft',   -- draft|published
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Exam history (edit log)
CREATE TABLE exam_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_id UUID REFERENCES exams(id) ON DELETE CASCADE,
    snapshot JSONB,                       -- full exam state tại thời điểm này
    change_type VARCHAR(50),              -- generate|edit_direct|edit_prompt|regenerate
    change_description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### 4.4 Async Processing với Celery

RAG pipeline và agent generation là tác vụ nặng — xử lý bất đồng bộ qua Celery:

```python
# Tasks
@celery.task(bind=True, max_retries=3)
def process_document_task(self, document_id: str):
    """Chạy toàn bộ RAG pipeline cho 1 document"""
    # 1. Download từ S3
    # 2. Parse + structure detection
    # 3. Formula + image extraction
    # 4. Chunking
    # 5. Embedding + upsert Pinecone
    # 6. Update DB status

@celery.task(bind=True)
def generate_exam_task(self, exam_config: dict):
    """Chạy multi-agent pipeline"""
    # 1. Orchestrator → Retrieval → Outline → Builder → Validator
    # 2. Emit WebSocket events qua Redis pub/sub
    # 3. Lưu kết quả vào DB
```

---

## 5. UI/UX Flow & Human-in-the-Loop

### 5.1 Luồng Người Dùng Đầy Đủ

```
[1] Upload tài liệu
        │
        ▼
[2] Chờ processing (progress bar)
        │
        ▼
[3] Xem heading tree → Chọn scope
        │
        ▼
[4] Cấu hình đề:
    - Loại đề (MCQ / Tự luận / Kết hợp)
    - Số câu mỗi phần
    - Phân bổ Bloom (slider %)
    - Prompt tùy chỉnh (optional)
        │
        ▼
[5] Submit → Streaming panel xuất hiện
    - Hiển thị plan steps real-time (Planner Agent output)
    - Progress: Retrieve → Outline → Build → Validate
        │
        ▼
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[6] ✅ HITL CHECKPOINT 1: Blueprint Review
    - Hiển thị sườn đề: bảng phân bổ câu theo Bloom × chapter
    - Giảng viên approve hoặc yêu cầu điều chỉnh sườn
    - → Tránh tốn token sinh câu nếu sườn đề sai hướng
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        │
        ▼
[7] Builder Agent sinh câu (streaming từng câu ra UI)
        │
        ▼
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[8] ✅ HITL CHECKPOINT 2: Full Review Screen
    - Xem toàn bộ đề + Bloom distribution chart
    - Chỉnh sửa trực tiếp (inline edit)
    - Chỉnh sửa qua prompt (chat panel, có memory)
    - Xem cost report (token dùng, USD estimate)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        │
        ▼
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[9] ✅ HITL CHECKPOINT 3: Export Preview
    - Render đúng format PDF/DOCX trong browser
    - Confirm → Download / Publish
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### 5.2 Review Screen — Human-in-the-Loop

**Layout:**

```
┌──────────────────────────────────────────────────────────────────┐
│  Đề kiểm tra: Vật lý 11 - Chương 1-3          [Export] [Approve]│
├─────────────────────────────────┬────────────────────────────────┤
│  DANH SÁCH CÂU HỎI             │  BLOOM DISTRIBUTION            │
│                                 │  ██████ Nhận biết: 20%         │
│  ▼ Phần I: Trắc nghiệm         │  ████████ Thông hiểu: 30%      │
│  ┌─────────────────────────┐   │  ████████ Vận dụng: 30%        │
│  │ Câu 1 [Thông hiểu][Ch1] │   │  ██████ Vận dụng cao: 20%      │
│  │ Một vật có khối lượng...│   ├────────────────────────────────┤
│  │ A. 2 m/s²  ✓ B. 4 m/s² │   │  CHAT CHỈNH SỬA                │
│  │ C. 10 m/s² D. 100 m/s² │   │                                 │
│  │ [✏️ Sửa] [🔄 Regenerate] │   │  > Sửa câu 15, tăng độ khó    │
│  └─────────────────────────┘   │                                 │
│  ┌─────────────────────────┐   │  [Agent đang xử lý...]          │
│  │ Câu 2 [Nhận biết][Ch1]  │   │                                 │
│  │ ...                     │   │  > Câu 15 đã được cập nhật      │
│  └─────────────────────────┘   │  với mức vận dụng cao hơn      │
│                                 │                                 │
│  ▼ Phần II: Tự luận            │  [Gõ yêu cầu chỉnh sửa...]     │
│  ...                           │                        [Gửi]   │
└─────────────────────────────────┴────────────────────────────────┘
```

---

### 5.3 Chỉnh Sửa Trực Tiếp

- Click vào câu hỏi → Inline editor mở ra (textarea)
- Chỉnh sửa stem, options, đáp án, explanation
- Lưu → Tự động snapshot vào `exam_history`

---

### 5.4 Chỉnh Sửa Qua Prompt

**Hành vi của Agent khi nhận prompt chỉnh sửa:**

- Agent nhớ toàn bộ `exam_config` gốc + Bloom distribution + scope
- Parse prompt để xác định: câu nào cần sửa, sửa theo hướng nào
- **Không sửa câu ngoài phạm vi yêu cầu** (nếu giảng viên chỉ nói "sửa câu 15" thì chỉ sửa câu 15)
- Nếu yêu cầu "sửa từ câu 30 trở đi" → kiểm tra Bloom level + scope của từng câu trong range → regenerate giữ nguyên distribution
- Câu mới không được lặp kiến thức câu đã có

**Ví dụ prompt xử lý:**
```
User: "Câu 15 quá dễ, nâng lên vận dụng cao"

Agent:
1. Locate câu 15 trong exam state
2. Xác định chapter, section, bloom hiện tại (thông hiểu)
3. Gọi Builder Agent với yêu cầu: bloom_level=van_dung_cao, chapter=Ch1, topic=topic_của_câu_15
4. Validate câu mới
5. Replace câu 15 trong exam state
6. Snapshot vào history
```

---

## 6. Observability & Cost Tracking

Hệ thống multi-agent rất khó debug nếu không có trace đầy đủ. Mỗi agent call cần emit structured log để có thể replay, debug, và tối ưu cost.

### 6.1 Distributed Tracing với LangFuse

**Tại sao LangFuse thay vì LangSmith:**
- Self-hostable (quan trọng nếu data tài liệu giảng viên cần bảo mật)
- Open-source, free tier đủ dùng cho MVP
- Support trace nesting — phù hợp với multi-agent hierarchy

**Trace structure:**
```
Trace: exam_generate_{exam_id}
├── Span: orchestrator.clarify          (latency, token)
├── Span: planner.plan_execution        (latency, token)
├── Span: retrieval.retrieve_context    (latency, token)
│   ├── Sub-span: query_chapter_1
│   ├── Sub-span: query_chapter_2
│   └── Sub-span: reranking
├── Span: outline.outline_exam          (latency, token)
│   └── Sub-span: bloom_classifier_skill (x N)
├── Span: builder.build_questions       (latency, token)
│   ├── Sub-span: chunk_1 (câu 1-10)
│   │   ├── Sub-span: dedup_checker_skill
│   │   ├── Sub-span: scope_guard
│   │   └── Sub-span: web_search (nếu có)
│   └── Sub-span: chunk_2 (câu 11-20)
└── Span: validator.validate_exam       (latency, token)
    ├── Sub-span: answer_checking
    ├── Sub-span: bloom_compliance
    └── Sub-span: scope_violation_check
```

**Mỗi span emit:**
```python
{
  "trace_id": "exam_generate_abc123",
  "span_name": "builder.build_questions.chunk_1",
  "agent": "builder",
  "input_hash": "sha256:...",        # hash input để detect duplicate calls
  "output_hash": "sha256:...",
  "latency_ms": 4230,
  "token_usage": {
    "prompt": 3200,
    "completion": 800,
    "total": 4000
  },
  "model": "gpt-4o",
  "estimated_cost_usd": 0.056,
  "warnings": [],
  "status": "success"
}
```

---

### 6.2 Cost Tracking Per Exam

Mỗi đề sinh ra cần có cost report hiển thị cho giảng viên (và admin):

```python
class ExamCostReport(BaseModel):
    exam_id: str
    total_tokens: int
    total_cost_usd: float
    breakdown: dict  # cost per agent
    # Ví dụ:
    # {
    #   "retrieval": { "tokens": 2000, "cost": 0.002 },
    #   "outline":   { "tokens": 1500, "cost": 0.015 },
    #   "builder":   { "tokens": 35000, "cost": 0.49 },
    #   "validator": { "tokens": 8000, "cost": 0.11 }
    # }
    model_used: dict  # model nào dùng ở bước nào
```

**Lưu vào PostgreSQL:**
```sql
ALTER TABLE exams ADD COLUMN cost_report JSONB;
ALTER TABLE exams ADD COLUMN total_tokens INTEGER;
ALTER TABLE exams ADD COLUMN total_cost_usd DECIMAL(10,4);
```

**Cost optimization rules** (apply tự động):
- Embedding: cache kết quả theo `(document_id, chunk_id)` trong Redis — tránh re-embed chunk đã có
- Reranking: dùng GPT-4o-mini thay vì GPT-4o
- Validator answer checking: dùng GPT-4o chỉ cho câu van_dung và van_dung_cao, dùng GPT-4o-mini cho nhan_biet và thong_hieu
- Planner Agent: dùng GPT-4o-mini (plan không cần model mạnh nhất)

---

### 6.3 Alerting

Tích hợp alert cơ bản (gửi về Slack/email):

| Condition | Alert |
|---|---|
| Validation fail rate > 50% trong 1 exam | "Builder Agent quality drop — check prompt" |
| Cost per exam > $2 | "High cost exam — review token usage" |
| Celery task timeout | "Agent pipeline timeout — check logs" |
| Pinecone query latency > 5s | "Vector DB slow — check index health" |

---

## 7. Tính Năng Phụ

### 7.1 Exam History

- Mỗi hành động (generate, edit, regenerate) → tạo 1 snapshot trong `exam_history`
- UI cho phép xem timeline lịch sử
- Có thể rollback về phiên bản cũ (restore snapshot)

### 7.2 Auth — JWT Chuẩn

- Access token: JWT HS256 (hoặc RS256), TTL 15 phút
- Refresh token: opaque token lưu HttpOnly cookie, TTL 7 ngày
- Refresh token rotation + blacklist trong DB
- Rate limiting trên `/auth/login` (5 lần/phút/IP)

### 7.3 Streaming + Agent Plan Display

- WebSocket connection mở ngay khi submit generate
- Sidebar hiện real-time: "Bước 1/5: Đang truy xuất kiến thức Chương 1..."
- Câu hỏi stream ra từng cái khi Builder Agent hoàn thành

---

## 8. Tech Stack Đề Xuất

| Layer | Công nghệ | Lý do |
|---|---|---|
| Frontend | Next.js 14 (App Router) | SSR, streaming support tốt |
| Backend | FastAPI (Python) | Async native, phù hợp AI workloads |
| Task Queue | Celery + Redis | Heavy async tasks |
| Database | PostgreSQL | Relational + JSONB cho flexible schema |
| Cache / Short-term Memory | Redis | Session memory, embedding cache, pub/sub |
| Vector DB | Pinecone (serverless) | Managed, namespace support per chapter |
| File Storage | AWS S3 | Bảo mật, durable, presigned URLs |
| Embedding | OpenAI text-embedding-3-large | SOTA embedding quality |
| LLM — Orchestrator & Builder | GPT-4o hoặc Claude Sonnet | Reasoning mạnh, context window lớn |
| LLM — Validator (giải đề) | GPT-4o / Claude Opus | Cần model mạnh nhất để giải đề chính xác |
| LLM — Planner, Reranker, Dedup | GPT-4o-mini | Nhanh, rẻ — đủ cho tác vụ nhẹ |
| Output Parser + Guardrails | Instructor (Python) | Pydantic-native, auto-retry khi output sai format |
| Formula OCR | Nougat (Meta) + MathPix fallback | Nougat offline/free; MathPix chính xác hơn |
| Image Vision | GPT-4o Vision | Mô tả hình ảnh, biểu đồ vật lý |
| Document Parse | Marker (Hugging Face) | Tốt nhất cho PDF phức tạp, giữ heading tree |
| Observability / Tracing | LangFuse (self-hosted) | Multi-agent trace, span nesting, cost tracking |
| Auth | JWT + bcrypt | Chuẩn industry |
| Realtime | WebSocket (FastAPI) | Streaming events từ agent pipeline |
| Deploy | Docker + AWS ECS hoặc Railway | Scale dễ, managed infra |

---

## 9. Rủi Ro & Giảm Thiểu

| Rủi ro | Khả năng | Giảm thiểu |
|---|---|---|
| LLM sinh câu hỏi ngoài scope | Cao | Scope Guard inline (allowed_concepts) + scope_checker_skill trong Validator |
| Formula OCR sai | Trung bình | Nougat → MathPix fallback + HITL Checkpoint 2 cho giảng viên review |
| Context window overflow | Trung bình | Token Budget Guard + sinh theo chunk 5-10 câu |
| Validator không detect Bloom sai | Trung bình | bloom_classifier_skill với Bloom rubric pre-define chi tiết; test nhiều case |
| Token cost cao | Cao | Model nhỏ (mini) cho Planner/Reranker/Dedup; embedding cache Redis; cost alert |
| Latency cao (>60s) | Cao | Parallel retrieval per chapter; Planner skip bước không cần; streaming UX |
| Upload file lớn (>100MB) | Trung bình | Chunked upload to S3; async Celery processing |
| Hallucination trong van_dung_cao | Cao | web_search tool + scope_checker_skill + Validator retry max 3 lần |
| Agent quên yêu cầu khi chỉnh sửa | Cao | Short-term Memory (Redis) load đầy đủ context khi nhận prompt edit |
| Sub-agent output sai format | Trung bình | Instructor auto-retry + Pydantic validation + content_filter guardrail |
| Planner sinh plan sai | Thấp | Fallback về hardcoded default plan nếu Planner timeout/fail |
| Duplicate câu hỏi | Trung bình | dedup_checker_skill inline; topics_used lưu vào Redis và pass qua mỗi chunk |
| Dữ liệu giảng viên bị lộ | Thấp | S3 private bucket + presigned URL TTL 1h; user_id check mọi endpoint |
| Agent pipeline crash giữa chừng | Trung bình | Celery task retry max 3; LangFuse trace để debug; partial result với warning |

---

*Tài liệu phiên bản 2.0 — phục vụ cả mục đích blueprint kỹ thuật, tài liệu cho team dev, và trình bày stakeholder. Các quyết định công nghệ có thể điều chỉnh theo nguồn lực thực tế.*
