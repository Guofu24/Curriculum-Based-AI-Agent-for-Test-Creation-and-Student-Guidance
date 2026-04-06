# V0_UI_PROMPT.md

> Prompt để generate UI/frontend bằng v0.dev (hoặc AI tương đương), bám sát SYSTEM_SPEC.md đã viết.
> **Nguyên tắc:** Không invent feature ngoài code. Không tạo UI xa rời backend hiện tại.
> **Stack:** React + TypeScript + modern dashboard components (shadcn/ui style)

---

## A. Product Context

### Sản phẩm là gì

**ExamAI** — Hệ thống tạo đề thi tự động từ tài liệu giảng dạy bằng multi-agent AI pipeline với human-in-the-loop checkpoints.

Input: Tài liệu (PDF/DOCX/PPTX) + cấu hình đề (số câu, phân bố Bloom, phạm vi chương)
Output: Bộ câu hỏi MCQ + Essay hoàn chỉnh, export PDF/DOCX, báo cáo chất lượng

### Người dùng là ai

**Giáo viên** — chuyên gia nội dung, cần tạo đề thi nhanh mà không phải viết tay, có thể duyệt/chỉnh sửa đề từ AI.

### Mục tiêu của UI

Admin dashboard hiện đại, thực dụng, usable ngay:
- Quản lý tài liệu (upload, theo dõi processing, xem curriculum tree)
- Tạo đề thi (wizard 3-step với real-time progress)
- Xem/sửa/export đề đã sinh
- Duyệt HITL checkpoints (blueprint → questions → preview)
- Dashboard quality metrics

---

## B. Danh sách màn hình

Dựa trên backend routes + frontend pages hiện có, chỉ giữ những màn có backend thật:

| # | Màn hình | Route | Backend |
|---|---------|-------|---------|
| 1 | Login/Register | `/` | ✅ `/auth/*` |
| 2 | Dashboard Home | `/dashboard` | ✅ `/exams/` + `/exams/quality-summary` |
| 3 | Document List | `/dashboard/documents` | ✅ `/documents/*` |
| 4 | Document Detail (Curriculum Tree) | `/dashboard/documents/[id]` | ✅ `/documents/{id}` + `/curriculum-tree` |
| 5 | Exam Generation Wizard | `/dashboard/generate` | ✅ `/generate/exam` + `/documents/*` |
| 6 | Exam List | `/dashboard/exams` | ✅ `/exams/` |
| 7 | Exam Detail/Editor | `/dashboard/exams/[id]` | ✅ `/exams/{id}` + all edit/export/HITL endpoints |
| 8 | Exam Version History | `/dashboard/exams/[id]/history` | ✅ `/exams/{id}/history` + `/versions` |
| 9 | Settings | `/dashboard/settings` | ✅ placeholder |
| 10 | Feedback Store | `/dashboard/feedback` | ⚠️ Returns empty (mock data needed) |

**Không thêm:** Courses page, Playbook page (backend 501 stubs)

---

## C. Mô tả chi tiết từng màn hình

### 1. Login/Register (`/`)

**Mục tiêu:** Authenticate giáo viên, bootstrap session.

**Layout:**
- Centered card (max-width 400px), logo + app name ở trên
- Tab toggle: "Đăng nhập" | "Đăng ký"
- Form fields:
  - Login: email, password
  - Register: email, password (min 8 chars), full_name
- Button "Đăng nhập" / "Đăng ký"
- Error message area (red)
- Redirect to `/dashboard` on success

**Actions:**
- Submit → `POST /auth/login` hoặc `POST /auth/register`
- On success: store tokens in localStorage, redirect to `/dashboard`
- On 401: show error message
- On network error: "Cannot connect to server. Please check that the backend is running."

**States:**
- Default: empty form
- Loading: button disabled + spinner
- Error: red message below form
- Success: redirect

---

### 2. Dashboard Home (`/dashboard`)

**Mục tiêu:** Tổng quan hệ thống, quality metrics, recent activity.

**Layout:**
- Header: "Dashboard" title + user avatar/name + logout
- Sidebar: navigation links (Dashboard, Tài liệu, Tạo đề, Đề thi, Cài đặt)
- Main area: 3 sections:
  1. **Stats row:** 4 metric cards (Total Exams, Quality Score Avg, Warnings Count, Documents)
  2. **Quality Summary:** Recharts line/bar chart showing verifier_pass_rate, evidence_coverage_rate over time
  3. **Recent Exams:** Table with columns: Title, Type, Status, Quality Score, Created At, Actions (View)

**API calls:**
- `GET /exams/?limit=5` → recent exams for table
- `GET /exams/quality-summary` → aggregated metrics for cards + chart
- Mock for charts if endpoint returns empty

**Actions:**
- Click "View" → navigate to `/dashboard/exams/{id}`
- Click "Tạo đề mới" CTA → `/dashboard/generate`

---

### 3. Document List (`/dashboard/documents`)

**Mục tiêu:** Upload và quản lý tài liệu.

**Layout:**
- Page header: "Tài liệu" + "Upload tài liệu" button
- Upload zone: drag-drop area (dashed border, icon, text "Kéo thả file PDF/DOCX/PPTX vào đây")
- File input fallback: "hoặc chọn file"
- Document list: Table columns: File Name, Type, Status, Chapters, Chunks, Uploaded At, Actions

**Status badge:**
- `pending` → gray "Đang chờ"
- `processing` → blue "Đang xử lý" + spinner
- `completed` → green "Hoàn thành"
- `failed` → red "Lỗi"

**Upload flow:**
1. User drops file → show uploading state (progress bar or spinner)
2. `POST /documents/upload` (multipart/form-data, field `file`)
3. Response: `{document_id, s3_key, message, processing_status, uploaded_at}`
4. Show "Đang xử lý" badge
5. Poll `GET /documents/{id}/status` every 3s until `completed` or `failed`

**Actions:**
- Click row → navigate to `/dashboard/documents/{id}`
- Delete → `DELETE /documents/{id}` + confirm dialog
- Refresh URL → `GET /documents/{id}/refresh-url` → open in new tab

**States:**
- Empty: "Chưa có tài liệu nào. Upload tài liệu đầu tiên."
- Loading: skeleton table rows
- Error: red message

---

### 4. Document Detail / Curriculum Tree (`/dashboard/documents/[id]`)

**Mục tiêu:** Xem chi tiết tài liệu, edit curriculum tree (chương/phần).

**Layout:**
- Breadcrumb: Tài liệu > [filename]
- Document info card: filename, file_type, size, pages, status, upload date
- "Curriculum Tree" section: editable tree view
  - Chapter → Section → Subsection hierarchy
  - Checkbox để chọn/bỏ chọn chương cho exam scope
  - "Rescan Structure" button (for unprocessed docs)
  - "Save Changes" button (PATCH curriculum tree)
- "Reprocess" button → trigger re-chunk và re-upsert

**Tree display:**
- Collapsible nodes (chevron icon)
- Chapter name + chapter number
- Each node shows: title, chunk count (if processed)

**Actions:**
- Toggle chapter checkbox → mark for exam scope
- Edit chapter title inline → PATCH curriculum tree
- "Reprocess" → `POST /documents/{id}/reprocess` → show processing status

---

### 5. Exam Generation Wizard (`/dashboard/generate`)

**Mục tiêu:** 3-step wizard để tạo đề thi từ document.

**Layout:**
- Step indicator: Step 1 (Chọn tài liệu) → Step 2 (Cấu hình đề) → Step 3 (Tạo đề)
- **Step 1 — Select Document:**
  - List of processed documents (only completed)
  - Each card: filename, chapter count, total chunks
  - Radio button to select
  - "Next" button

- **Step 2 — Configure Exam:**
  - Selected document name + scope selector (checkboxes for chapters)
  - Exam title input
  - Exam type: radio (MCQ only / Essay only / Mixed)
  - MCQ count: number input (1-50)
  - Essay count: number input (0-10)
  - Bloom distribution: 4 sliders that must sum to 100%
    - nhan_bieth: default 20%
    - thong_hieu: default 30%
    - van_dung: default 30%
    - van_dung_cao: default 20%
  - Strict scope checkbox (default checked): "Chỉ dùng nội dung trong phạm vi đã chọn"
  - User prompt textarea: "Hướng dẫn thêm cho AI" (optional, max 500 chars)
  - "Generate" button

- **Step 3 — Generation Progress:**
  - Real-time progress via WebSocket
  - `generation-live-viewer` component: scrollable log of agent events
  - Events shown: plan_step, question_generated, validation_result, hitl_checkpoint
  - If HITL checkpoint: show "Review" button + data
  - On completed: show exam_id + "Xem đề" button + "Tạo đề mới" button

**WebSocket integration:**
```javascript
// Connect to ws://host:8000/ws/exam/{exam_id}
Event types to display:
- plan_step: "Bước 1/4: Đang truy xuất tài liệu..."
- question_generated: "Đã sinh câu hỏi MCQ_001"
- hitl_checkpoint: "Duyệt sườn đề" / "Duyệt câu hỏi" / "Xem trước đề"
- validation_result: "Đã kiểm tra 10/10 câu hỏi"
- completed: "Hoàn thành! Chi phí: $0.0042"
- error: "Lỗi: ..." (red)
```

**Form validation:**
- Document required
- At least 1 MCQ or 1 Essay
- Bloom sliders sum = 100%

---

### 6. Exam List (`/dashboard/exams`)

**Mục tiêu:** List all exams for current user.

**Layout:**
- Header: "Đề thi" + "Tạo đề mới" button → `/dashboard/generate`
- Filter bar: status filter (All / Draft / Published)
- Table columns: Title, Type, Chapters, Questions, Status, Quality Score, Warnings, Created, Actions
- Pagination: prev/next + page numbers

**Status badge:**
- `draft` → gray "Nháp"
- `ready_for_review` → yellow "Chờ duyệt"
- `regenerating` → blue "Đang tạo lại"
- `published` → green "Đã xuất bản"

**Actions:**
- View → `/dashboard/exams/{id}`
- Delete → `DELETE /exams/{id}` + confirm

**API:** `GET /exams/?page=1&limit=20&status=`

---

### 7. Exam Detail/Editor (`/dashboard/exams/[id]`) — MÀN LỚN NHẤT

**Mục tiêu:** Xem toàn bộ đề, chỉnh sửa câu hỏi, duyệt HITL, export.

**Layout (tab-based):**

**Tab: "Câu hỏi"** (default)
- Header: exam title + status badge + action buttons
- Action bar: "Edit Prompt" (AI edit) | "Regenerate" | "Publish" | "Export PDF" | "Export DOCX"
- Filter: All / MCQ / Essay
- Question list: numbered cards
  - Each card: number, bloom badge, type badge, question stem, options (MCQ), rubric (Essay), source evidence, quality score, validation warnings
  - MCQ: show A/B/C/D options, correct answer highlighted in green
  - Essay: show rubric table
  - Edit button per question → inline edit mode
- Inline edit: click "Sửa" → fields become editable (stem, options, correct_answer, bloom_level) → "Lưu" → `PATCH /exams/{id}/questions/{question_id}`

**Tab: "Sườn đề" (Blueprint)**
- Blueprint table: question_id, bloom_level, chapter, topic_hint, content_type, difficulty
- "Approve Blueprint" button → `POST /exams/{id}/approve-blueprint`
- "Reject with Feedback" button → text area + `POST /exams/{id}/reject-blueprint`

**Tab: "Chất lượng"**
- Quality metrics: quality_score, verifier_pass_rate, evidence_coverage_rate
- Warning list: items with bloom mismatch / out of scope
- Duplicate groups: questions flagged as similar

**Tab: "Lịch sử"**
- Version list: version number, change_type, change_description, created_at
- "Restore" button per version → `POST /exams/{id}/history/{history_id}/restore`

**Actions across all tabs:**
- `GET /exams/{id}` → load exam data
- `GET /exams/{id}/versions` → version history
- `GET /exams/{id}/review-data` → HITL review data
- `POST /exams/{id}/submit-review` → submit review
- `GET /exams/{id}/export/pdf` → trigger PDF download
- `GET /exams/{id}/export/docx` → trigger DOCX download

---

### 8. Exam Version History (`/dashboard/exams/[id]/history`)

**Mục tiêu:** Xem tất cả snapshots của đề thi.

**Layout:**
- Breadcrumb: Đề thi > [title] > Lịch sử
- Version list: timeline-style list
  - Each entry: version number (v1, v2, ...), change_type badge, description, timestamp
  - "Xem" button → load snapshot data
  - "Restore" button → confirm dialog → `POST /exams/{id}/history/{history_id}/restore`

**change_type badges:**
- `generate` → blue "Tạo mới"
- `edit_direct` → yellow "Sửa tay"
- `edit_prompt` → purple "Sửa AI"
- `regenerate` → orange "Tạo lại"
- `published` → green "Xuất bản"
- `restore` → gray "Khôi phục"

---

### 9. Settings (`/dashboard/settings`)

**Mục tiêu:** User settings + system config display.

**Layout:**
- User profile section: email, full_name, role (read-only)
- Preferences display (if stored in LongTermMemory): preferred_bloom_distribution, style_notes
- Runtime info: app version, environment
- Logout button

**Note:** Backend settings router not implemented — show placeholder content.

---

### 10. Feedback Store (`/dashboard/feedback`)

**Mục đích:** Xem feedback signals từ AI pipeline.

**Layout:**
- Header: "Kho phản hồi"
- Summary cards: total feedback, by category
- Feedback list: table (timestamp, exam_id, signal_type, description)
- Filter by exam

**Note:** Backend returns empty — use mock data structure:
```typescript
interface FeedbackEvent {
  id: string;
  exam_id: string;
  timestamp: string;
  signal_type: "bloom_mismatch" | "out_of_scope" | "duplicate" | "quality_low" | "answer_incorrect";
  description: string;
  resolved: boolean;
}
```

---

## D. API Integration Contract

### Auth Integration

| Màn hình | Endpoint | Method | Payload | Response |
|---------|---------|--------|---------|----------|
| Login | `/auth/login` | POST | `{email, password}` | `{access_token, refresh_token, token_type, expires_in}` |
| Register | `/auth/register` | POST | `{email, password, full_name?}` | `UserResponse` |
| Refresh | `/auth/refresh` | POST | `{refresh_token}` | `{access_token, expires_in}` |
| Logout | `/auth/logout` | POST | `{refresh_token}` | `{message}` |
| Me | `/auth/me` | GET | — | `UserResponse` |

**Token storage:** `localStorage.setItem("token", ...)` + `localStorage.setItem("refresh_token", ...)`
**Header:** `Authorization: Bearer {token}` for all protected endpoints

---

### Document Integration

| Màn hình | Endpoint | Method | Notes |
|---------|---------|--------|-------|
| List | `/documents/` | GET | `?page=1&limit=20` |
| Upload | `/documents/upload` | POST | `multipart/form-data`, field `file` |
| Detail | `/documents/{id}` | GET | Full detail + heading_tree |
| Status | `/documents/{id}/status` | GET | Poll every 3s |
| Delete | `/documents/{id}` | DELETE | Confirm dialog |
| Curriculum | `/documents/{id}/curriculum-tree` | GET | Flat list of CurriculumNode |
| Update curriculum | `/documents/{id}/curriculum-tree` | PATCH | `{nodes: [...]}` |
| Refresh URL | `/documents/{id}/refresh-url` | GET | Opens presigned URL |
| Reprocess | `/documents/{id}/reprocess` | POST | Trigger background |

**Upload response mapping:**
```typescript
// FE field → Backend field
file_name → original_filename
status → processing_status
uploaded_at → uploaded_at (aliased from created_at in list view)
```

---

### Generation Integration

| Màn hình | Endpoint | Method | Payload |
|---------|---------|--------|---------|
| Start | `/generate/exam` | POST | `ExamGenerationRequest` (see below) |
| WebSocket | `/ws/exam/{exam_id}` | WS | Connect immediately after POST |

**ExamGenerationRequest payload:**
```typescript
{
  document_id: string;        // required
  scope: string[];            // chapter titles selected by user
  exam_type: "mcq" | "essay" | "mixed";  // default "mixed"
  mcq_count: number;          // default 10
  essay_count: number;        // default 2
  bloom_distribution: {
    nhan_biet: number;        // default 20, must sum 100%
    thong_hieu: number;       // default 30
    van_dung: number;         // default 30
    van_dung_cao: number;    // default 20
  };
  user_prompt: string;        // optional, natural language guidance
  extra_instructions: string; // optional
  strict_scope_flag: boolean; // default true
  title: string;              // optional, auto-generated if null
}
```

**WebSocket event handling:**
```typescript
type WSEvent =
  | { type: "plan_step"; step: number; total_steps: number; message: string }
  | { type: "question_generated"; question_id: string; question: QuestionResponse }
  | { type: "validation_result"; passed: boolean; issues_count: number; issues: Issue[] }
  | { type: "hitl_checkpoint"; checkpoint_id: number; data: any }
  | { type: "completed"; exam_id: string; total_cost_usd: number }
  | { type: "error"; message: string; agent?: string }
  | { type: "clarification_needed"; questions: string[] }
  | { type: "pipeline_paused"; reason: string };
```

---

### Exam Integration

| Màn hình | Endpoint | Method | Payload |
|---------|---------|--------|---------|
| List | `/exams/` | GET | `?page=1&limit=20&status=` |
| Detail | `/exams/{id}` | GET | Full exam |
| Versions | `/exams/{id}/versions` | GET | Version history |
| Edit question | `/exams/{id}/questions/{qid}` | PATCH | `{content, options, correct_answer, bloom_level, ...}` |
| Edit prompt | `/exams/{id}/edit-prompt` | POST | `{instruction}` |
| Regenerate | `/exams/{id}/regenerate` | POST | `{question_ids?}` |
| Publish | `/exams/{id}/publish` | POST | — |
| Approve blueprint | `/exams/{id}/approve-blueprint` | POST | — |
| Reject blueprint | `/exams/{id}/reject-blueprint` | POST | `{feedback: string}` |
| Submit review | `/exams/{id}/submit-review` | POST | `{approved, feedback?, direct_edits?}` |
| Review data | `/exams/{id}/review-data` | GET | Full review data |
| Preview | `/exams/{id}/preview` | GET | HTML preview |
| History | `/exams/{id}/history` | GET | All snapshots |
| Restore | `/exams/{id}/history/{hid}/restore` | POST | — |
| Export PDF | `/exams/{id}/export/pdf` | GET | `?include_answers=true&include_blueprint=false` |
| Export DOCX | `/exams/{id}/export/docx` | GET | `?include_answers=true` |
| Quality summary | `/exams/quality-summary` | GET | Aggregated metrics |

**Partial regenerate:**
```typescript
POST /generate/partial-regenerate
{
  exam_id: string;
  edits: Array<
    | { action: "delete"; question_id: string }
    | { action: "lock"; question_id: string }
    | { action: "edit_text"; question_id: string; content: string }
    | { action: "edit_answer"; question_id: string; correct_answer: string }
    | { action: "edit_bloom"; question_id: string; bloom_level: string }
    | { action: "edit_options"; question_id: string; options: Record<string, string> }
  >;
}
```

---

## E. Design Direction

### Phong cách

**Admin/Dashboard sạch, hiện đại, thực dụng:**
- Font: Inter (sans-serif fallback)
- Color: Neutral background (#f8fafc light / #0f172a dark), primary accent blue (#2563eb)
- Spacing: Generous padding, clear visual hierarchy
- Radius: Rounded corners (default Tailwind `rounded-lg`)
- Shadows: Subtle, only on cards and dialogs

### Ưu tiên usability

- Clear CTAs với labels tiếng Việt
- Loading states hiển thị spinner + message
- Error states: specific error message, not generic
- Empty states: illustrated or clear text + CTA
- Confirmation dialogs cho destructive actions (delete, restore)

### Hỗ trợ dữ liệu nhiều trạng thái

- Status badges với màu sắc rõ ràng:
  - pending/processing: blue
  - draft: gray
  - completed/published: green
  - failed/error: red
  - regenerating: orange
- Progress indicators cho long operations (upload, generation)

### Hiển thị progress/status rõ ràng

- Generation wizard: step indicator (1/2/3)
- Document processing: status badge + polling indicator
- Question generation: real-time WebSocket log (generation-live-viewer)

### Dễ mở rộng

- Tab-based layouts (Exam Detail)
- Component library: button, card, dialog, table, badge, input, select, textarea, checkbox, tabs, progress, skeleton, alert

---

## F. Technical Requirements for v0

### Stack

- **React 19** + TypeScript
- **Next.js App Router** or Vite
- **Tailwind CSS v4** (CSS variables for theming)
- **Radix UI primitives** (or shadcn/ui components)
- **React Hook Form + Zod** for form validation
- **Lucide React** for icons
- **Recharts** for dashboard charts

### Component structure

```
src/
├── components/
│   ├── ui/                    # Reusable: Button, Input, Card, Badge, Dialog, Table, etc.
│   ├── layout/
│   │   ├── app-sidebar.tsx
│   │   ├── dashboard-header.tsx
│   │   └── dashboard-layout.tsx
│   ├── auth/
│   │   ├── login-form.tsx
│   │   └── register-form.tsx
│   ├── documents/
│   │   ├── document-list.tsx
│   │   ├── document-upload.tsx
│   │   └── curriculum-tree.tsx
│   ├── generation/
│   │   ├── generation-wizard.tsx
│   │   ├── step-1-select-document.tsx
│   │   ├── step-2-configure.tsx
│   │   ├── step-3-progress.tsx
│   │   └── generation-live-viewer.tsx
│   ├── exams/
│   │   ├── exam-list.tsx
│   │   ├── exam-detail.tsx
│   │   ├── exam-question-card.tsx
│   │   ├── exam-blueprint-view.tsx
│   │   └── export-dialog.tsx
│   └── shared/
│       ├── status-badge.tsx
│       ├── empty-state.tsx
│       └── loading-skeleton.tsx
├── hooks/
│   ├── use-auth.tsx
│   ├── use-documents.ts
│   ├── use-exams.ts
│   └── use-websocket.ts
├── lib/
│   └── api.ts               # Align with existing UI/lib/api.ts pattern
└── pages/
    ├── index.tsx            # Login/Register
    └── dashboard/
        ├── page.tsx          # Dashboard home
        ├── documents/
        │   ├── page.tsx      # Document list
        │   └── [id]/page.tsx # Document detail
        ├── generate/
        │   └── page.tsx      # Generation wizard
        ├── exams/
        │   ├── page.tsx      # Exam list
        │   └── [id]/
        │       ├── page.tsx  # Exam detail
        │       └── history/page.tsx
        └── settings/
            └── page.tsx
```

### Mock data cho nơi backend chưa đủ

**Feedback Store mock:**
```typescript
const MOCK_FEEDBACK: FeedbackEvent[] = [
  {
    id: "1",
    exam_id: "uuid-1",
    timestamp: "2026-04-01T10:00:00Z",
    signal_type: "bloom_mismatch",
    description: "Câu hỏi MCQ_003 có bloom_level 'thong_hieu' nhưng nội dung phù hợp 'nhan_biet'",
    resolved: false
  },
  {
    id: "2",
    exam_id: "uuid-1",
    timestamp: "2026-04-01T10:05:00Z",
    signal_type: "out_of_scope",
    description: "Câu hỏi ESSAY_001 vượt phạm vi: tham khảo nội dung từ Chương 3 không nằm trong scope",
    resolved: false
  }
];
```

**Quality summary mock:**
```typescript
const MOCK_QUALITY_SUMMARY = {
  total_exams: 12,
  avg_quality_score: 0.82,
  avg_verifier_pass_rate: 0.78,
  avg_evidence_coverage_rate: 0.91,
  warning_count: 5,
  timeline: [
    { date: "2026-03-28", quality_score: 0.75, pass_rate: 0.70 },
    { date: "2026-03-30", quality_score: 0.80, pass_rate: 0.75 },
    { date: "2026-04-02", quality_score: 0.85, pass_rate: 0.80 },
    { date: "2026-04-04", quality_score: 0.88, pass_rate: 0.85 }
  ]
};
```

**Playbook mock (for settings page):**
```typescript
const MOCK_PLAYBOOK = {
  total_bullets: 24,
  active_candidates: 5,
  warmup_preview: "Đề thi Vật lý lớp 11, Chương 1-2"
};
```

**HITL blueprint mock:**
```typescript
const MOCK_BLUEPRINT = [
  { question_id: "MCQ_001", type: "mcq", bloom_level: "nhan_biet", chapter: "Chương 1", topic_hint: "Dao động điều hòa", content_type: "text", estimated_difficulty: 0.3 },
  { question_id: "MCQ_002", type: "mcq", bloom_level: "thong_hieu", chapter: "Chương 1", topic_hint: "Công thức chu kỳ", content_type: "calculation", estimated_difficulty: 0.5 },
  // ... more slots
];
```

---

## G. Deliverable Expectations

Yêu cầu v0 sinh ra:

### Pages cần thiết

1. **Login/Register** — auth form với tab toggle, validation, error handling
2. **Dashboard Home** — stats cards + quality chart + recent exams table
3. **Document List** — upload zone + table với status badges + polling
4. **Document Detail** — curriculum tree view/edit
5. **Generation Wizard** — 3-step form + WebSocket live viewer
6. **Exam List** — paginated table với filter + status badges
7. **Exam Detail** — tabbed interface (Câu hỏi / Sườn đề / Chất lượng / Lịch sử) với inline edit
8. **Settings** — user profile display + logout

### Routing hợp lý

```
/                       → Login/Register
/dashboard              → Dashboard home
/dashboard/documents    → Document list
/dashboard/documents/[id] → Document detail
/dashboard/generate      → Generation wizard
/dashboard/exams        → Exam list
/dashboard/exams/[id]   → Exam detail
/dashboard/exams/[id]/history → Version history
/dashboard/settings     → Settings
```

### Reusable components

- `Button` (variant: primary, secondary, danger, ghost)
- `Input`, `Textarea`, `Select`, `Checkbox`
- `Card`, `Badge`
- `Dialog`, `AlertDialog`
- `Table`, `Pagination`
- `StatusBadge` (pending/processing/completed/failed/draft/published)
- `BloomBadge` (nhan_biet/thong_hieu/van_dung/van_dung_cao)
- `EmptyState` (icon + message + CTA)
- `LoadingSkeleton` (table rows, cards)
- `ProgressBar`
- `Tabs`
- `Stepper`

### States cần cover

- **Loading:** Skeleton placeholders for tables, spinners for buttons
- **Empty:** Custom messages with CTA ("Chưa có tài liệu nào", "Chưa có đề thi nào")
- **Error:** Red alert with message, retry button where applicable
- **Success:** Toast notification (sonner), redirect after action

### Mock data

- All mock data must be clearly marked with `// MOCK:` comment
- Match exact field names from backend schemas
- Use realistic Vietnamese content (exam titles, teacher names, chapter names)

---

## H. Lưu ý cực quan trọng

### Không invent feature ngoài repo

- **Không có:** Courses management, Playbook module, Admin role
- **Không có:** Real-time collaborative editing
- **Không có:** Email notifications, user invitation system
- **Chỉ làm:** Giáo viên tạo đề thi từ tài liệu đã upload

### Không tạo UI xa rời backend

- Nếu endpoint chưa có (501), dựng UI hợp lý + mock data rõ ràng
- Không design form cho `/courses/*` vì backend chưa có
- Không design full Playbook page vì backend 501

### Scope guard note

- FE gửi scope dạng chapter title string `"A.QUANG HÌNH HỌC"`, backend tự normalize
- Nếu scope chunks > 200 → backend reject với error message về chunk count

### WebSocket note

- ws://host:8000/ws/exam/{exam_id} — connect ngay sau khi POST /generate/exam thành công
- reconnect logic khi connection drop
- fallback: poll `GET /exams/{id}` nếu WS không khả dụng

### Language

- Tất cả UI labels tiếng Việt
- Error messages tiếng Việt
- Date formatting: dd/MM/yyyy HH:mm (Vietnamese standard)
- Numbers: dùng dấu phẩy cho decimal (VD: 0,85 thay vì 0.85) — hoặc dùng locale-aware formatting

---

*Căn cứ: Tất cả mô tả dựa trên SYSTEM_SPEC.md đã viết từ code thực tế. Không có giả định nào được thêm vào.*