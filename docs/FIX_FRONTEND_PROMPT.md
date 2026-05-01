# FIX_FRONTEND_PROMPT.md

> Prompt này hướng dẫn AI tiếp tục chỉnh sửa UI trong thư mục `Frontend` để fix các vấn đề còn thiếu.
>
> **Cách đọc:** Đọc từng phần, thực hiện từ trên xuống. Phần nào đã làm rồi thì đánh dấu ✅ và bỏ qua.
>
> **Quy tắc:** Không thêm feature mới ngoài spec. Không đổi API contract. Chỉ fix những gì được liệt kê.

---

## TỔNG QUAN

Cần fix **6 vấn đề nghiêm trọng** và **4 vấn đề nhẹ** trong `Frontend/`.

### File cần đọc trước khi sửa
- `Frontend/lib/api.ts` — API client + type definitions
- `Frontend/components/question-editor.tsx` — Question editor component
- `Frontend/components/curriculum-tree.tsx` — Curriculum tree component
- `Frontend/app/dashboard/documents/[id]/page.tsx` — Document detail page
- `Frontend/app/dashboard/exams/[id]/page.tsx` — Exam detail page
- `Frontend/app/dashboard/generate/page.tsx` — Generation wizard page

### File đã verified là OK (không cần sửa)
- `Frontend/app/page.tsx` — Login/Register ✅
- `Frontend/app/layout.tsx` — Root layout ✅
- `Frontend/app/dashboard/layout.tsx` — Dashboard layout ✅
- `Frontend/app/dashboard/page.tsx` — Dashboard home ✅
- `Frontend/app/dashboard/documents/page.tsx` — Document list ✅
- `Frontend/app/dashboard/exams/page.tsx` — Exam list ✅
- `Frontend/app/dashboard/exams/[id]/history/page.tsx` — History page ✅
- `Frontend/app/dashboard/feedback/page.tsx` — Feedback page (mock data OK) ✅
- `Frontend/app/dashboard/settings/page.tsx` — Settings page ✅
- `Frontend/components/app-sidebar.tsx` — Sidebar ✅
- `Frontend/components/dashboard-header.tsx` — Header ✅
- `Frontend/components/status-badge.tsx` — Badges ✅
- `Frontend/components/theme-provider.tsx` — Theme ✅
- `Frontend/components/empty-state.tsx` ✅
- `Frontend/components/file-upload.tsx` ✅
- `Frontend/components/generation-progress.tsx` ✅
- `Frontend/hooks/use-toast.ts` ✅
- `Frontend/hooks/use-mobile.ts` ✅
- `Frontend/lib/utils.ts` ✅
- `Frontend/lib/format.ts` ✅

---

## FIX 1: Bloom Level Colors (NGHIÊM TRỌNG — Fix trước)

**File:** `Frontend/components/question-editor.tsx`
**Tầm quan trọng:** 🔴 Cao nhất — Bloom badge sẽ không hiển thị màu nếu không fix

### Vấn đề
Component dùng key tiếng Anh (`remember`, `understand`, `apply`, ...) nhưng backend trả về tiếng Việt (`nhan_biet`, `thong_hieu`, `van_dung`, `van_dung_cao`).

### Cần làm

**Bước 1:** Đọc `Frontend/components/question-editor.tsx`

**Bước 2:** Tìm dòng chứa `bloomLevelColors` (khoảng dòng 34) — thay toàn bộ object thành:

```typescript
const bloomLevelColors: Record<BloomLevel, string> = {
  nhan_biet: "bg-slate-500/20 text-slate-300 border-slate-500/30",
  thong_hieu: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  van_dung: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  van_dung_cao: "bg-amber-500/20 text-amber-300 border-amber-500/30",
}
```

**Bước 3:** Tìm `bloomLevelLabels` (khoảng dòng 48) — thay thành:

```typescript
const bloomLevelLabels: Record<BloomLevel, string> = {
  nhan_biet: "Nhận biết",
  thong_hieu: "Thông hiểu",
  van_dung: "Vận dụng",
  van_dung_cao: "Vận dụng cao",
}
```

**Bước 4:** Kiểm tra xem còn key cũ nào (`remember`, `understand`, `apply`, `analyze`, `evaluate`, `create`) trong file — xóa bỏ hoặc đổi sang tiếng Việt.

### Căn cứ từ code
- Backend schema (`backend/app/schemas/exam.py`): `BloomDistribution` dùng 4 key tiếng Việt
- Backend `Question` JSONB dùng `bloom_level` string tiếng Việt
- FE `BloomLevel` type trong `lib/api.ts`: `'nhan_biet' | 'thong_hieu' | 'van_dung' | 'van_dung_cao'`

---

## FIX 2: Hard-coded WebSocket URL (NGHIÊM TRỌNG)

**File:** `Frontend/lib/api.ts`
**Tầm quan trọng:** 🔴 Cao — sẽ break khi backend chạy trên host khác

### Vấn đề
WebSocket URL cố định `ws://localhost:8000/ws/exam/` — không linh hoạt.

### Cần làm

**Bước 1:** Đọc `Frontend/lib/api.ts`

**Bước 2:** Tìm `createExamWebSocket` function (khoảng dòng 511)

**Bước 3:** Thay dòng hard-coded URL thành:

```typescript
// Tạo WebSocket URL linh hoạt
function getWebSocketUrl(examId: string): string {
  // Ưu tiên env var, fallback về same-origin (cho proxy) hoặc localhost dev
  if (typeof window === 'undefined') {
    // Server-side: fallback localhost
    return `ws://localhost:8000/ws/exam/${examId}`
  }
  
  // Client-side: ưu tiên env var
  const wsBaseUrl = process.env.NEXT_PUBLIC_WS_URL || ''
  if (wsBaseUrl) {
    return `${wsBaseUrl}/${examId}`
  }
  
  // Fallback: same origin (khi backend proxy qua Next.js)
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/exam/${examId}`
}

// Bên trong createExamWebSocket, thay dòng:
const wsUrl = `ws://localhost:8000/ws/exam/${examId}`
// Thành:
const wsUrl = getWebSocketUrl(examId)
```

**Bước 4:** Tạo file `Frontend/.env.local` với nội dung:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/exam
```

### Căn cứ từ code
- Backend `config.py`: `APP_BASE_URL` default `http://localhost:8000`, `ws_base_url` property tự derive từ đó
- FE `api.ts` đã dùng `NEXT_PUBLIC_API_URL` cho REST calls, WebSocket cần tương tự

---

## FIX 3: Curriculum Tree — Missing Save + Shape Transform (NGHIÊM TRỌNG)

**Files:** `Frontend/components/curriculum-tree.tsx` + `Frontend/app/dashboard/documents/[id]/page.tsx`
**Tầm quan trọng:** 🔴 Cao — user không thể lưu thay đổi curriculum tree

### Vấn đề 1 — Backend trả flat, component cần nested
Backend `GET /documents/{id}/curriculum-tree` trả flat array:
```typescript
// Backend trả về:
CurriculumNode[] = [
  { id: "ch1", title: "Chương 1", level: 1, parent_id: null },
  { id: "ch1-s1", title: "1.1 Hàm số", level: 2, parent_id: "ch1" },
  // ...
]
```

Component `CurriculumTree` nhận nested `{ id, title, type: "chapter"|"section"|"topic", children }`.

**Cần transform: flat → nested tree**

### Vấn đề 2 — Không có save callback
Component chỉ emit `onSelectionChange` khi checkbox toggle, nhưng không có `onSave` callback để parent gọi API.

### Cần làm

**Bước 1:** Đọc `Frontend/components/curriculum-tree.tsx`

**Bước 2:** Thêm helper function transform flat → nested ở đầu file (sau imports):

```typescript
// ── Transform backend flat API response → nested tree ──────────────────────

interface FlatCurriculumNode {
  id: string
  title: string
  level: number       // 1=chapter, 2=section, 3=subsection
  parent_id?: string | null
  chunk_count?: number
}

interface NestedCurriculumNode {
  id: string
  title: string
  type: "chapter" | "section" | "topic"
  chunk_count?: number
  children?: NestedCurriculumNode[]
  selected?: boolean
  indeterminate?: boolean
}

function flatToNested(flat: FlatCurriculumNode[]): NestedCurriculumNode[] {
  const nodeMap = new Map<string, NestedCurriculumNode>()
  const roots: NestedCurriculumNode[] = []

  // First pass: create all nodes
  for (const node of flat) {
    const typeMap: Record<number, "chapter" | "section" | "topic"> = {
      1: "chapter",
      2: "section",
      3: "topic",
    }
    nodeMap.set(node.id, {
      id: node.id,
      title: node.title,
      type: typeMap[node.level] ?? "topic",
      chunk_count: node.chunk_count,
      children: [],
    })
  }

  // Second pass: build tree
  for (const node of flat) {
    const nested = nodeMap.get(node.id)!
    if (node.parent_id && nodeMap.has(node.parent_id)) {
      nodeMap.get(node.parent_id)!.children!.push(nested)
    } else {
      roots.push(nested)
    }
  }

  return roots
}
```

**Bước 3:** Thêm `onSave` prop vào interface và thêm button:

```typescript
interface CurriculumTreeProps {
  nodes: CurriculumNode[]           // Flat from API — sẽ transform bên trong
  onSelectionChange: (selectedIds: string[]) => void
  onSave?: (nodes: CurriculumNode[]) => void  // ← THÊM
  selectedIds: string[]
}
```

**Bước 4:** Trong component, tìm phần render cuối (trước `return`) — thêm:

```typescript
  // ── Save button ──────────────────────────────────────────────────────────
  const handleSave = () => {
    // Build flat list from selected nodes (for PATCH API)
    const buildFlatSelected = (nodes: NestedCurriculumNode[], selected: Set<string>): FlatCurriculumNode[] => {
      const result: FlatCurriculumNode[] = []
      for (const node of nodes) {
        if (selected.has(node.id)) {
          result.push({
            id: node.id,
            title: node.title,
            level: node.type === "chapter" ? 1 : node.type === "section" ? 2 : 3,
            parent_id: undefined, // reconstructed by backend
          })
        }
        if (node.children) {
          result.push(...buildFlatSelected(node.children, selected))
        }
      }
      return result
    }
    
    const selectedSet = new Set(selectedIds)
    const flatNodes = buildFlatSelected(nodes as NestedCurriculumNode[], selectedSet)
    onSave?.(flatNodes as unknown as CurriculumNode[])
  }

  // ── Main render ──────────────────────────────────────────────────────────
  return (
    <div className="space-y-0.5">
      {/* Save button — only show if onSave is provided */}
      {onSave && (
        <div className="flex justify-end mb-3">
          <Button size="sm" onClick={handleSave}>
            Lưu thay đổi
          </Button>
        </div>
      )}
      {(nodes as NestedCurriculumNode[]).map(node => renderNode(node))}
    </div>
  )
```

**Bước 5:** Sửa component để nhận flat `CurriculumNode[]` từ API và tự transform bên trong. Thay đổi đầu component:

```typescript
export function CurriculumTree({ 
  nodes, 
  onSelectionChange, 
  onSave,
  selectedIds 
}: CurriculumTreeProps) {
  // Transform flat API response → nested tree
  const nestedNodes = useMemo(() => flatToNested(nodes as FlatCurriculumNode[]), [nodes])
  
  // ... rest of component, but use nestedNodes instead of nodes in render
  return (
    <div className="space-y-0.5">
      {onSave && (
        <div className="flex justify-end mb-3">
          <Button size="sm" onClick={handleSave}>
            Lưu thay đổi
          </Button>
        </div>
      )}
      {nestedNodes.map(node => renderNode(node))}
    </div>
  )
}
```

**Bước 6:** Đọc `Frontend/app/dashboard/documents/[id]/page.tsx`

**Bước 7:** Tìm chỗ render `CurriculumTree` — thêm `onSave` handler:

```typescript
// Tìm component CurriculumTree trong JSX, thêm:
<CurriculumTree
  nodes={curriculumNodes}
  selectedIds={selectedChapterIds}
  onSelectionChange={setSelectedChapterIds}
  onSave={handleSaveCurriculum}    // ← THÊM
/>
```

**Bước 8:** Thêm handler function:

```typescript
const handleSaveCurriculum = async (nodes: CurriculumNode[]) => {
  try {
    await documentsApi.updateCurriculumTree(id, nodes)
    toast.success('Đã lưu cấu trúc chương trình')
  } catch (error) {
    toast.error('Không thể lưu. Vui lòng thử lại.')
  }
}
```

### Căn cứ từ code
- Backend `DocumentService.update_curriculum_tree()` nhận flat `CurriculumNode[]` (từ `CurriculumNodeSchema`)
- Backend schema: `{ id, title, level, parent_id }` (flat, not nested)
- FE component: nested `{ id, title, type, children }` — cần transform

---

## FIX 4: Question Type Labels — Missing `mcq` Key (NGHIÊM TRỌNG)

**File:** `Frontend/components/question-editor.tsx`
**Tầm quan trọng:** 🔴 Cao — type badge sẽ hiển thị undefined

### Vấn đề
`questionTypeLabels` dùng key `multiple_choice`, `true_false`, `fill_blank` nhưng FE `Question` interface chỉ hỗ trợ `type: "mcq" | "essay"`.

### Cần làm

**Bước 1:** Đọc `Frontend/components/question-editor.tsx`

**Bước 2:** Tìm `questionTypeLabels` (khoảng dòng 58) — thay thành:

```typescript
const questionTypeLabels: Record<QuestionType, string> = {
  mcq: "Trắc nghiệm",
  essay: "Tự luận",
  // internal-only types for demo — backend không hỗ trợ
  multiple_choice: "Trắc nghiệm",
  true_false: "Đúng/Sai",
  fill_blank: "Điền khuyết",
}
```

**Bước 3:** Kiểm tra tương tự cho `difficultyLabels` (khoảng dòng 55) — đảm bảo key khớp với `QuestionDifficulty` trong `lib/api.ts`.

### Căn cứ từ code
- Backend chỉ trả `type: "mcq"` hoặc `type: "essay"` trong `Question` JSONB
- FE `lib/api.ts`: `QuestionType = 'mcq' | 'essay'`

---

## FIX 5: Blueprint HITL Actions — Approve/Reject Buttons (NGHIÊM TRỌNG)

**File:** `Frontend/app/dashboard/exams/[id]/page.tsx`
**Tầm quan trọng:** 🔴 Cao — user không thể approve/reject blueprint

### Vấn đề
Backend có `POST /exams/{id}/approve-blueprint` và `POST /exams/{id}/reject-blueprint` nhưng FE tab Blueprint không có button.

### Cần làm

**Bước 1:** Đọc `Frontend/app/dashboard/exams/[id]/page.tsx`

**Bước 2:** Thêm state và handlers vào đầu component (sau các state hiện tại):

```typescript
const [showBlueprintActionDialog, setShowBlueprintActionDialog] = useState(false)
const [blueprintAction, setBlueprintAction] = useState<'approve' | 'reject' | null>(null)
const [blueprintFeedback, setBlueprintFeedback] = useState('')
const [isBlueprintActing, setIsBlueprintActing] = useState(false)
```

**Bước 3:** Thêm handlers:

```typescript
const handleApproveBlueprint = () => {
  setBlueprintAction('approve')
  setBlueprintFeedback('')
  setShowBlueprintActionDialog(true)
}

const handleRejectBlueprint = () => {
  setBlueprintAction('reject')
  setBlueprintFeedback('')
  setShowBlueprintActionDialog(true)
}

const handleBlueprintAction = async () => {
  if (!blueprintAction) return
  setIsBlueprintActing(true)
  try {
    if (blueprintAction === 'approve') {
      await examsApi.approveBlueprint(id)
      toast.success('Đã duyệt sườn đề. Pipeline đang tiếp tục...')
    } else {
      if (!blueprintFeedback.trim()) {
        toast.error('Vui lòng nhập phản hồi khi từ chối')
        return
      }
      await examsApi.rejectBlueprint(id, blueprintFeedback)
      toast.success('Đã gửi phản hồi. Sườn đề mới đang được tạo...')
    }
    setShowBlueprintActionDialog(false)
    // Refresh review data
    const reviewData = await examsApi.getReviewData(id)
    setBlueprint(reviewData.blueprint || [])
  } catch (error) {
    toast.error(blueprintAction === 'approve' ? 'Không thể duyệt sườn đề' : 'Không thể gửi phản hồi')
  } finally {
    setIsBlueprintActing(false)
  }
}
```

**Bước 4:** Trong Blueprint tab (tìm `TabsContent value="blueprint"`, khoảng dòng 437), thêm button sau `</CardContent>` của table card:

```tsx
                </CardContent>
                
                {/* Action buttons */}
                <CardFooter className="flex gap-3 border-t pt-4">
                  <Button onClick={handleApproveBlueprint} disabled={isBlueprintActing}>
                    <CheckCircle2 className="mr-2 h-4 w-4" />
                    Duyệt sườn đề
                  </Button>
                  <Button variant="outline" onClick={handleRejectBlueprint} disabled={isBlueprintActing}>
                    <XCircle className="mr-2 h-4 w-4" />
                    Từ chối
                  </Button>
                </CardFooter>
```

**Bước 5:** Thêm AlertDialog cho Reject feedback (sau AlertDialog của Publish, khoảng dòng 627):

```tsx
      {/* Blueprint Action Dialog */}
      <AlertDialog open={showBlueprintActionDialog} onOpenChange={setShowBlueprintActionDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {blueprintAction === 'approve' ? 'Duyệt sườn đề?' : 'Từ chối sườn đề'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {blueprintAction === 'approve'
                ? 'Sau khi duyệt, hệ thống sẽ tiếp tục sinh câu hỏi.'
                : 'Nhập phản hồi để hệ thống tạo sườn đề mới phù hợp hơn.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          
          {blueprintAction === 'reject' && (
            <Textarea
              placeholder="Ví dụ: Tăng tỷ lệ câu khó lên 30%, tập trung vào bài tập tính toán..."
              value={blueprintFeedback}
              onChange={(e) => setBlueprintFeedback(e.target.value)}
              rows={3}
              className="mt-3"
            />
          )}
          
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <Button
              onClick={handleBlueprintAction}
              disabled={isBlueprintActing || (blueprintAction === 'reject' && !blueprintFeedback.trim())}
            >
              {isBlueprintActing ? <Spinner className="mr-2" /> : null}
              {blueprintAction === 'approve' ? 'Duyệt' : 'Gửi phản hồi'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
```

**Bước 6:** Import thêm `CheckCircle2`, `XCircle` từ `lucide-react`.

### Căn cứ từ code
- Backend `exams.py` có `@router.post("/{exam_id}/approve-blueprint")` và `@router.post("/{exam_id}/reject-blueprint")`
- FE `lib/api.ts` có `examsApi.approveBlueprint` và `examsApi.rejectBlueprint`

---

## FIX 6: Rescan Structure Button (NGHIÊM TRỌNG)

**File:** `Frontend/app/dashboard/documents/[id]/page.tsx`
**Tầm quan trọng:** 🔴 Cao — user không thể rescane headings

### Vấn đề
Backend có `POST /documents/{id}/rescan-structure` nhưng FE không có button.

### Cần làm

**Bước 1:** Đọc `Frontend/app/dashboard/documents/[id]/page.tsx`

**Bước 2:** Thêm state:

```typescript
const [isRescanning, setIsRescanning] = useState(false)
```

**Bước 3:** Thêm handler:

```typescript
const handleRescanStructure = async () => {
  setIsRescanning(true)
  try {
    // Backend sẽ cập nhật heading_tree
    // Refresh document để thấy tree mới
    const doc = await documentsApi.get(id)
    setDocument(doc)
    
    // Reload curriculum tree
    const tree = await documentsApi.getCurriculumTree(id)
    setCurriculumNodes(tree)
    setSelectedChapterIds([])
    
    toast.success('Đã quét lại cấu trúc tài liệu')
  } catch (error) {
    toast.error('Không thể quét lại cấu trúc')
  } finally {
    setIsRescanning(false)
  }
}
```

**Bước 4:** Tìm chỗ hiển thị document info card hoặc toolbar — thêm button:

```tsx
<div className="flex gap-2">
  <Button variant="outline" onClick={handleRescanStructure} disabled={isRescanning}>
    <RefreshCw className={`mr-2 h-4 w-4 ${isRescanning ? 'animate-spin' : ''}`} />
    {isRescanning ? 'Đang quét...' : 'Quét lại cấu trúc'}
  </Button>
  
  <Button variant="outline" onClick={handleReprocess} disabled={isReprocessing}>
    <RefreshCw className={`mr-2 h-4 w-4 ${isReprocessing ? 'animate-spin' : ''}`} />
    Xử lý lại
  </Button>
</div>
```

### Căn cứ từ code
- Backend `documents.py` có `@router.post("/{document_id}/rescan-structure")`
- FE `lib/api.ts` gọi đúng endpoint

---

## FIX 7: Scope Warning UX Enhancement (NHẸ)

**File:** `Frontend/app/dashboard/generate/page.tsx`
**Tầm quan trọng:** 🟡 Trung bình — UX improvement

### Vấn đề
Backend trả `scope_warning` khi scope có >200 chunks. FE chỉ hiển thị toast, không ngăn submit.

### Cần làm

**Bước 1:** Đọc `Frontend/app/dashboard/generate/page.tsx`

**Bước 2:** Tìm chỗ handle `handleGenerate` (khoảng dòng 170) — thêm kiểm tra scope_warning:

```typescript
// Sau dòng:
const response = await generateApi.startGeneration(configToRequest())

if (response.scope_warning) {
  // Nếu backend trả warning → vẫn cho phép nhưng cảnh báo
  setProgress(100)
  setExamId(response.exam_id)
  setGenerationComplete(true)
  toast.warning(`Cảnh báo: ${response.scope_warning}`, {
    description: 'Đề đã được tạo nhưng một số nội dung có thể bị cắt ngắn.',
    duration: 8000,
  })
} else {
  setProgress(100)
  setExamId(response.exam_id)
  setGenerationComplete(true)
  toast.success('Tạo đề thành công!')
}
```

**Bước 3:** Thêm alert/warning banner ở đầu generation result section (sau khi `setGenerationComplete(true)`):

```tsx
{response.scope_warning && generationComplete && (
  <Alert variant="warning" className="mb-4">
    <AlertTriangle className="h-4 w-4" />
    <AlertTitle>Cảnh báo phạm vi</AlertTitle>
    <AlertDescription>
      {response.scope_warning}. Một số nội dung có thể bị giới hạn token.
    </AlertDescription>
  </Alert>
)}
```

Import `Alert`, `AlertTitle`, `AlertDescription` từ `@/components/ui/alert`.

### Căn cứ từ code
- Backend `generate.py` trả `scope_warning` khi chunk count > threshold
- FE `GenerationResponse` interface đã có `scope_warning?: string`

---

## FIX 8: WebSocket Reconnect Logic (NHẸ)

**File:** `Frontend/lib/api.ts`
**Tầm quan trọng:** 🟡 Trung bình — resilience improvement

### Vấn đề
Không có reconnect logic khi WebSocket drop. Backend restart → FE mất kết nối không recover.

### Cần làm

**Bước 1:** Đọc `Frontend/lib/api.ts` — tìm `createExamWebSocket` (dòng 511)

**Bước 2:** Thêm reconnect logic bằng cách sửa `createExamWebSocket`:

```typescript
export function createExamWebSocket(
  examId: string,
  onEvent: (event: WSEvent) => void,
  onError?: (error: Event) => void,
  onClose?: () => void
): WebSocket {
  let ws: WebSocket
  let reconnectAttempts = 0
  const MAX_RECONNECT_ATTEMPTS = 5
  const BASE_RECONNECT_DELAY = 1000 // ms

  const connect = () => {
    const wsUrl = getWebSocketUrl(examId)  // Dùng function từ FIX 2
    ws = new WebSocket(wsUrl)

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onEvent(data as WSEvent)
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
      onError?.(error)
    }

    ws.onclose = (event) => {
      console.log('WebSocket closed:', event.code, event.reason)
      onClose?.()
      
      // Auto-reconnect if not intentional close and under limit
      if (event.code !== 1000 && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++
        const delay = BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttempts - 1)
        console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`)
        setTimeout(connect, delay)
      } else if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        console.error('Max reconnect attempts reached')
      }
    }
  }

  connect()
  return ws
}
```

---

## FIX 9: Extra Instructions Field (NHẸ)

**File:** `Frontend/app/dashboard/generate/page.tsx`
**Tầm quan trọng:** 🟡 Thấp — backend có nhưng FE không gửi

### Vấn đề
Backend `ExamConfigRequest` có `extra_instructions` nhưng form chỉ gửi `user_prompt`.

### Cần làm

**Bước 1:** Đọc `Frontend/app/dashboard/generate/page.tsx`

**Bước 2:** Thêm field vào `GenerationConfig` interface (khoảng dòng 47):

```typescript
export interface GenerationConfig {
  documentId: string
  selectedChapters: string[]
  mcqCount: number
  essayCount: number
  bloomDistribution: Record<BloomLevel, number>
  userPrompt: string
  extraInstructions: string  // ← THÊM
  strictScope: boolean
  title: string
}
```

**Bước 3:** Thêm vào default state (khoảng dòng 68):

```typescript
export const DEFAULT_CONFIG: GenerationConfig = {
  // ... existing fields
  userPrompt: '',
  extraInstructions: '',  // ← THÊM
  strictScope: true,
  title: '',
}
```

**Bước 4:** Thêm UI field trong Step 2 form (sau `userPrompt` Textarea):

```tsx
<Field>
  <FieldLabel>Ràng buộc bắt buộc cho AI (tùy chọn)</FieldLabel>
  <Textarea
    placeholder="Ví dụ: Chỉ dùng công thức đã học trong chương 1, không tham khảo tài liệu bên ngoài..."
    value={config.extraInstructions}
    onChange={(e) => setConfig(prev => ({ ...prev, extraInstructions: e.target.value }))}
    maxLength={500}
    rows={2}
  />
  <FieldDescription>
    Những yêu cầu này AI phải tuân thủ tuyệt đối.
  </FieldDescription>
</Field>
```

**Bước 5:** Thêm vào request payload (khoảng dòng 184):

```typescript
{
  document_id: config.documentId,
  scope: config.selectedChapters,
  exam_type: config.examType,
  mcq_count: config.mcqCount,
  essay_count: config.essayCount,
  bloom_distribution: config.bloomDistribution,
  user_prompt: config.userPrompt || undefined,
  extra_instructions: config.extraInstructions || undefined,  // ← THÊM
  strict_scope_flag: config.strictScope,
  title: config.title || undefined,
}
```

### Căn cứ từ code
- Backend `ExamConfigRequest` có `extra_instructions: str | None`
- FE `ExamGenerationRequest` interface trong `lib/api.ts` có `extra_instructions?: string`

---

## FIX 10: Partial Regenerate UI (NHẸ)

**File:** `Frontend/lib/api.ts` + `Frontend/app/dashboard/exams/[id]/page.tsx`
**Tầm quan trọng:** 🟡 Thấp — backend có nhưng FE chưa gọi

### Vấn đề
Backend có `POST /generate/partial-regenerate` cho phép edit từng câu một (delete/lock/edit_text/edit_answer/edit_bloom/edit_options) nhưng FE chưa có UI.

### Cần làm

**Bước 1:** Trong `Frontend/lib/api.ts` — thêm interface và API method:

```typescript
// Partial edit types
export type PartialEditAction =
  | { action: 'delete'; question_id: string }
  | { action: 'lock'; question_id: string }
  | { action: 'edit_text'; question_id: string; content: string }
  | { action: 'edit_answer'; question_id: string; correct_answer: string }
  | { action: 'edit_bloom'; question_id: string; bloom_level: BloomLevel }
  | { action: 'edit_options'; question_id: string; options: Record<string, string> }

export interface PartialRegenerateRequest {
  exam_id: string
  edits: PartialEditAction[]
}
```

**Bước 2:** Thêm method vào `generateApi`:

```typescript
partialRegenerate: async (request: PartialRegenerateRequest): Promise<void> => {
  await apiFetch('/generate/partial-regenerate', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}
```

**Bước 3:** (Tuỳ chọn) Thêm button trong exam detail — có thể implement sau khi basic flow hoạt động. Ghi chú trong code: `// TODO: Add partial regenerate UI using generateApi.partialRegenerate()`

---

## THỨ TỰ THỰC HIỆN

Thực hiện theo thứ tự sau để có thể test sớm:

```
1. FIX 1  → Bloom colors       [5 dòng]  → Test được ngay
2. FIX 2  → WebSocket URL      [3 dòng]  → Test được ngay  
3. FIX 3  → Curriculum tree     [30 dòng] → Test được ngay
4. FIX 4  → Question type      [1 dòng]  → Test được ngay
5. FIX 5  → Blueprint actions  [40 dòng] → Cần backend chạy
6. FIX 6  → Rescan button      [15 dòng] → Cần backend chạy
7. FIX 7  → Scope warning UX   [10 dòng] → Cần backend chạy
8. FIX 8  → WS reconnect       [20 dòng] → Cần backend chạy
9. FIX 9  → Extra instructions [10 dòng] → Cần backend chạy
10. FIX 10 → Partial regenerate [Optional] → Backend chưa stable
```

Sau khi hoàn thành **Fix 1-4**, frontend đã có thể merge và test với backend.

---

## CHECKLIST TRƯỚC KHI MERGE

Sau khi thực hiện tất cả các fix, verify:

- [ ] `bloomLevelColors` dùng key tiếng Việt (`nhan_biet`, `thong_hieu`, `van_dung`, `van_dung_cao`)
- [ ] `bloomLevelLabels` dùng label tiếng Việt
- [ ] `questionTypeLabels` có key `mcq`
- [ ] `getWebSocketUrl()` được dùng trong `createExamWebSocket`
- [ ] `.env.local` có `NEXT_PUBLIC_WS_URL`
- [ ] `CurriculumTree` có `onSave` prop và gọi được API
- [ ] Document detail page gọi `updateCurriculumTree()`
- [ ] Blueprint tab có Approve/Reject buttons
- [ ] Document detail page có Rescan Structure button
- [ ] Generation page hiển thị `scope_warning` banner
- [ ] WebSocket có reconnect logic
- [ ] Generation form gửi `extra_instructions`

---

*Căn cứ: Tất cả fix đều dựa trên SYSTEM_SPEC.md đã viết từ code thực tế. Không có giả định nào được thêm vào.*