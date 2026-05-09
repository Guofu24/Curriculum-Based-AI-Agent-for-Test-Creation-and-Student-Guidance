"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { LatexRenderer } from "@/components/latex-renderer"
import {
  Brain,
  Check,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Loader2,
  AlertCircle,
  ThumbsUp,
  X,
  Sparkles,
  BookOpen,
  Database,
  ShieldCheck,
  FileCheck,
  Wifi,
  WifiOff,
  PartyPopper,
  ListChecks,
  Pencil,
  RefreshCw,
  MessageCircle,
  Send,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { examsApi } from "@/lib/api"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"

// ─── Event types ────────────────────────────────────────────────────────────────

interface PlanStepEvent {
  type: "plan_step"
  step: number
  total_steps: number
  message: string
}

interface QuestionGeneratedEvent {
  type: "question_generated"
  question_id: string
  question: {
    question_id?: string
    stem?: string
    content?: string
    type?: string
    options?: Record<string, string>
    optionsArray?: Array<{ label: string; text: string }>
    bloom_level?: BloomLevel
    difficulty_score?: number
    correct_answer?: string
    rubric?: Record<string, unknown>
    explanation?: string
    chapter?: string
    propositions?: Array<{ label: string; text: string; is_correct: boolean }>
    unit?: string
    solution?: string
    [key: string]: unknown
  }
}

interface HitlCheckpointEvent {
  type: "hitl_checkpoint"
  checkpoint_id: number
  data: {
    requirements?: RequirementsData
    blueprint?: BlueprintSlot[]
    distribution_summary?: BloomDistribution
    questions?: QuestionGeneratedEvent["question"][]
    validation_passed?: boolean
    issues?: ValidationIssue[]
    cost_report?: CostReport
    exam_id?: string
    [key: string]: unknown
  }
}

interface ValidationResultEvent {
  type: "validation_result"
  passed: boolean
  issues_count: number
  issues: ValidationIssue[]
}

interface CompletedEvent {
  type: "completed"
  exam_id: string
}

interface PipelinePausedEvent {
  type: "pipeline_paused"
  checkpoint_id: number
  message?: string
  blueprint?: BlueprintSlot[]
  distribution_summary?: BloomDistribution
}

interface ReasoningChunkEvent {
  type: "reasoning_chunk"
  /** ID links the chunk to its reasoning step (e.g. "step-2") */
  step_id: string
  chunk: string
}

type WsMessage =
  | PlanStepEvent
  | QuestionGeneratedEvent
  | HitlCheckpointEvent
  | ValidationResultEvent
  | CompletedEvent
  | PipelinePausedEvent
  | ReasoningChunkEvent
  | { type: "clarification_needed"; data: { clarification_questions: ClarificationQuestion[] } }
  | { type: string; [key: string]: unknown }

// ─── Supporting types ──────────────────────────────────────────────────────────

export type BloomLevel = "nhan_biet" | "thong_hieu" | "van_dung" | "van_dung_cao"

interface BloomDistribution {
  nhan_biet?: number
  thong_hieu?: number
  van_dung?: number
  van_dung_cao?: number
}

interface BlueprintSlot {
  question_id?: string
  type?: string
  bloom_level?: string
  chapter?: string
  section?: string
  topic_hint?: string
  content_type?: string
  estimated_difficulty?: number
  // Section-aware fields
  primary_section_id?: string
  primary_section_title?: string
  primary_scope_unit_key?: string
  secondary_section_ids?: string[]
  secondary_section_titles?: string[]
  secondary_scope_unit_keys?: string[]
  [key: string]: unknown
}

interface RequirementsData {
  scope?: string[]
  total_questions?: number
  mcq_count?: number
  essay_count?: number
  bloom_distribution_summary?: string
  user_prompt?: string
  extra_instructions?: string
  suggested_exam_type?: string
  [key: string]: unknown
}

interface ValidationIssue {
  question_id: string
  issue_type?: string
  type?: string
  detail?: string
  message?: string
  suggestion?: string
}

interface ClarificationQuestion {
  question_id: string
  question: string
}

interface CostReport {
  total_cost_usd?: number
  total_tokens?: number
  retrieval?: Record<string, unknown>
  outline?: Record<string, unknown>
  builder?: Record<string, unknown>
  validator?: Record<string, unknown>
}

// ─── Stream feed item types ───────────────────────────────────────────────────
type FeedItem =
  | { id: string; kind: 'reasoning'; stepLabel: string; message: string; chunks: string[] }
  | { id: string; kind: 'blueprint'; slots: BlueprintSlot[]; bloomDist: BloomDistribution }
  | { id: string; kind: 'question'; question: QuestionGeneratedEvent['question']; index: number }
  | { id: string; kind: 'validation'; issues: ValidationIssue[] }
  | { id: string; kind: 'hitl_waiting'; checkpointId: number }

interface PlanStep {
  step: number
  message: string
  completed: boolean
  active: boolean
  retryCount?: number
}

// ─── Pipeline steps config ────────────────────────────────────────────────────

const PIPELINE_STEPS = [
  { id: 0, label: "Khởi tạo", icon: Brain },
  { id: 1, label: "Truy xuất kiến thức", icon: BookOpen },
  { id: 2, label: "Tạo sườn đề", icon: Database },
  { id: 3, label: "Sinh câu hỏi", icon: Sparkles },
  { id: 4, label: "Kiểm tra & sửa lỗi", icon: ShieldCheck },
  { id: 5, label: "Hoàn tất", icon: FileCheck },
]

// ─── Bloom level config ───────────────────────────────────────────────────────

const BLOOM_CONFIG: Record<
  BloomLevel,
  { label: string; color: string; bg: string; short: string }
> = {
  nhan_biet: { label: "Nhận biết", color: "text-sky-700", bg: "bg-sky-100 border-sky-200", short: "NB" },
  thong_hieu: { label: "Thông hiểu", color: "text-emerald-700", bg: "bg-emerald-100 border-emerald-200", short: "TH" },
  van_dung: { label: "Vận dụng", color: "text-amber-700", bg: "bg-amber-100 border-amber-200", short: "VD" },
  van_dung_cao: { label: "Vận dụng cao", color: "text-orange-700", bg: "bg-orange-100 border-orange-200", short: "VDC" },
}

const BLOOM_ORDER: BloomLevel[] = ["nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"]

// ─── Props ─────────────────────────────────────────────────────────────────────

export interface GenerationLiveViewerProps {
  examId: string
  wsUrl: string
  examType?: "mcq" | "essay" | "mixed"
  onApprove: (examId: string, approved: boolean, feedback?: string, checkpointId?: number) => Promise<void>
  onComplete: (examId: string) => void
}

// ─── Main component ───────────────────────────────────────────────────────────

export function GenerationLiveViewer({
  examId,
  wsUrl,
  examType,
  onApprove,
  onComplete,
}: GenerationLiveViewerProps) {
  const router = useRouter()
  const [connState, setConnState] = useState<"idle" | "connecting" | "connected" | "error">("idle")

  // Pipeline state
  const [steps, setSteps] = useState<PlanStep[]>(
    PIPELINE_STEPS.map((s) => ({ step: s.id, message: "", completed: false, active: false }))
  )
  const [reasoningOpen, setReasoningOpen] = useState(true)

  // HITL state — checkpoint 0 = requirements, 1 = blueprint, 2 = full review, 3 = export preview
  const [activeCheckpoint, setActiveCheckpoint] = useState<number | null>(null)
  const [hitlApproved, setHitlApproved] = useState(false)
  const [hitlApproving, setHitlApproving] = useState(false)
  const [hitlRejecting, setHitlRejecting] = useState(false)
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false)
  const [rejectFeedback, setRejectFeedback] = useState("")
  const [lastSeenCheckpoint, setLastSeenCheckpoint] = useState<number | null>(null)

  // Blueprint
  const [blueprintSlots, setBlueprintSlots] = useState<BlueprintSlot[]>([])
  const [blueprintExpanded, setBlueprintExpanded] = useState(false)
  const [requirementsData, setRequirementsData] = useState<RequirementsData | null>(null)

  // Question stream
  const [questions, setQuestions] = useState<QuestionGeneratedEvent["question"][]>([])
  const [isGenerating, setIsGenerating] = useState(false)

  // Validation
  const [validationIssues, setValidationIssues] = useState<ValidationIssue[]>([])

  // Completion
  const [completed, setCompleted] = useState(false)
  const [showCelebration, setShowCelebration] = useState(false)
const [bloomDist, setBloomDist] = useState<BloomDistribution | null>(null)
  const [costReport, setCostReport] = useState<CostReport | null>(null)

  // Per-question edit state (CP2)
  const [selectedQuestionId, setSelectedQuestionId] = useState<string | null>(null)
  const [questionEditPrompt, setQuestionEditPrompt] = useState<string>("")
  const [questionRegenerating, setQuestionRegenerating] = useState<string | null>(null)

  // Clarification state — shown when outline needs more info from user
  const [clarificationQuestions, setClarificationQuestions] = useState<ClarificationQuestion[]>([])
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, string>>({})
  const [clarificationSubmitting, setClarificationSubmitting] = useState(false)

  // Unified stream feed — accumulates all events in order
  const [feedItems, setFeedItems] = useState<FeedItem[]>([])
  const feedEndRef = useRef<HTMLDivElement | null>(null)

  // Auto-scroll feed to bottom on new items
  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [feedItems])

  useEffect(() => {
    if (activeCheckpoint === 1) {
      setBlueprintExpanded(true)
    } else if (activeCheckpoint === 2) {
      setBlueprintExpanded(false)
    }
  }, [activeCheckpoint])

  // Connection
  const wsRef = useRef<WebSocket | null>(null)
  const unmountedRef = useRef(false)

  // ─── Derived ────────────────────────────────────────────────────────────────


  // ─── WebSocket URL resolver ──────────────────────────────────────────────────

  const resolvedWsUrl = (() => {
    if (wsUrl.startsWith("ws://") || wsUrl.startsWith("wss://")) return wsUrl
    const proto = window.location.protocol === "https:" ? "wss" : "ws"
    const backendHost = window.location.port === "3000"
      ? `${window.location.hostname}:8000`
      : window.location.host
    if (wsUrl.startsWith("/")) {
      return `${proto}://${backendHost}${wsUrl}`
    }
    return `${proto}://${backendHost}/${wsUrl}`
  })()

  // ─── Event handler ───────────────────────────────────────────────────────────

  // Refs to avoid stale closure in handleMessage.
  const activeCheckpointRef = useRef<number | null>(null)
  activeCheckpointRef.current = activeCheckpoint
  const lastSeenCheckpointRef = useRef<number | null>(null)
  lastSeenCheckpointRef.current = lastSeenCheckpoint

  const hitlApprovedRef = useRef(false)
  const blueprintSlotsRef = useRef<BlueprintSlot[]>([])
  blueprintSlotsRef.current = blueprintSlots
  const bloomDistRef = useRef<BloomDistribution | null>(null)
  bloomDistRef.current = bloomDist

  const handleMessage = useCallback(
    (raw: string) => {
      let msg: WsMessage
      try {
        msg = JSON.parse(raw)
      } catch {
        return
      }
      console.log("[WS] Received:", msg.type, msg)
      console.log("[WS DEBUG] activeCheckpoint=", activeCheckpointRef.current, "blueprintSlots=", blueprintSlotsRef.current.length)

      switch (msg.type) {
        case "plan_step": {
          const e = msg as PlanStepEvent
          setIsGenerating(true)
          if (e.step >= 3) {
            setActiveCheckpoint(null)
            activeCheckpointRef.current = null
          }
          setSteps((prev) =>
            prev.map((s) => {
              if (s.step < e.step) return { ...s, completed: true, active: false }
              if (s.step === e.step) return { ...s, message: e.message ?? "", active: true, completed: false }
              return { ...s, active: false }
            })
          )
          if (!reasoningOpen) setReasoningOpen(true)
          // Add reasoning item to feed
          const stepConfig = PIPELINE_STEPS.find((x) => x.id === e.step)
          setFeedItems((prev) => {
            const itemId = `step-${e.step}`
            const exists = prev.findIndex((f) => f.id === itemId)
            const item: FeedItem = {
              id: itemId,
              kind: 'reasoning',
              stepLabel: stepConfig?.label ?? `Bước ${e.step}`,
              message: e.message ?? '',
              chunks: [],   // chunks will be appended via reasoning_chunk events
            }
            if (exists >= 0) {
              const next = [...prev]
              // preserve existing chunks when step message updates
              next[exists] = { ...item, chunks: (prev[exists] as Extract<FeedItem, {kind:'reasoning'}>).chunks }
              return next
            }
            return [...prev, item]
          })
          break
        }

        case "question_generated": {
          const e = msg as QuestionGeneratedEvent
          const q = e.question
          if (examType && examType !== "mixed") {
            const qType = q.type || "mcq"
            if (qType !== examType) return
          }
          setQuestions((prev) => {
            const qId = q.question_id
            // If this question already exists (e.g. validator retry rebuild), replace it in-place
            const existingIdx = qId ? prev.findIndex((ex) => ex.question_id === qId) : -1
            if (existingIdx !== -1) {
              const next = [...prev]
              next[existingIdx] = q
              // Also update feedItems in-place
              setFeedItems((f) =>
                f.map((fi) =>
                  fi.kind === 'question' &&
                  (fi as Extract<FeedItem, { kind: 'question' }>).question.question_id === qId
                    ? { ...fi, question: q }
                    : fi
                )
              )
              return next
            }
            // New question — append
            const next = [...prev, q]
            setFeedItems((f) => {
              if (qId && f.some((fi) => fi.kind === 'question' && (fi as {id:string;kind:'question';question:QuestionGeneratedEvent['question'];index:number}).question.question_id === qId)) return f
              return [...f, { id: `q-${qId || next.length}`, kind: 'question' as const, question: q, index: next.length - 1 }]
            })
            return next
          })
          break
        }

        case "hitl_checkpoint": {
          const e = msg as HitlCheckpointEvent
          console.log("[WS DEBUG hitl_checkpoint] checkpoint_id=", e.checkpoint_id, "data=", e.data)
          setActiveCheckpoint(e.checkpoint_id)
          activeCheckpointRef.current = e.checkpoint_id
          setLastSeenCheckpoint(e.checkpoint_id)
          lastSeenCheckpointRef.current = e.checkpoint_id
          // Reset approval state for every new checkpoint — otherwise cp2 would
          // inherit hitlApproved=true from the user having approved cp1.
          setHitlApproved(false)
          hitlApprovedRef.current = false

          if (e.checkpoint_id === 0) {
            setRequirementsData(e.data as RequirementsData)
          }
          if (e.checkpoint_id === 1) {
            const slots = (e.data as { blueprint?: BlueprintSlot[] }).blueprint || []
            console.log("[WS DEBUG hitl_checkpoint] setting blueprintSlots:", slots.length, slots)
            setBlueprintSlots(slots)
            const dist: BloomDistribution = {}
            for (const slot of slots) {
              const lvl = slot.bloom_level as BloomLevel | undefined
              if (lvl && lvl in dist) dist[lvl] = (dist[lvl] || 0) + 1
              else if (lvl) dist[lvl] = 1
            }
            setBloomDist(dist)
            // Add/update blueprint in feed (update on re-generation after reject)
            if (slots.length > 0) {
              setFeedItems((prev) => {
                const existingIdx = prev.findIndex((f) => f.kind === 'blueprint')
                const newItem = { id: 'blueprint', kind: 'blueprint' as const, slots, bloomDist: dist }
                if (existingIdx >= 0) {
                  // Update existing blueprint feed item with new slots (after reject+regenerate)
                  const next = [...prev]
                  next[existingIdx] = newItem
                  return next
                }
                return [...prev, newItem]
              })
            }
          }
          if (e.checkpoint_id === 2) {
            const d = e.data as HitlCheckpointEvent["data"]
            setValidationIssues(d.issues || [])
          }
          if (e.checkpoint_id === 3) {
            const d = e.data as HitlCheckpointEvent["data"]
            setCostReport(d.cost_report || null)
            setBloomDist(d.distribution_summary || bloomDistRef.current)
          }
          break
        }

        case "validation_result": {
          const e = msg as ValidationResultEvent
          setValidationIssues(e.issues || [])
          if (e.issues && e.issues.length > 0) {
            setFeedItems((prev) => {
              const exists = prev.findIndex((f) => f.kind === 'validation')
              const item: FeedItem = { id: 'validation', kind: 'validation', issues: e.issues }
              if (exists >= 0) { const next = [...prev]; next[exists] = item; return next }
              return [...prev, item]
            })
          }
          break
        }

        case "completed": {
          const e = msg as CompletedEvent
          setSteps((prev) =>
            prev.map((s) => ({ ...s, completed: true, active: false }))
          )
          setIsGenerating(false)
          setCompleted(true)
          setShowCelebration(true)
          setTimeout(() => setShowCelebration(false), 3500)
          wsRef.current?.close()
          if (!unmountedRef.current) {
            setTimeout(() => onComplete(e.exam_id), 600)
          }
          break
        }

        case "pipeline_paused": {
          const e = msg as PipelinePausedEvent
          setActiveCheckpoint(e.checkpoint_id)
          activeCheckpointRef.current = e.checkpoint_id
          setLastSeenCheckpoint(e.checkpoint_id)
          lastSeenCheckpointRef.current = e.checkpoint_id
          setHitlApproved(false)
          hitlApprovedRef.current = false
          if (e.checkpoint_id === 1) {
            if (e.blueprint && e.blueprint.length > 0) {
              setBlueprintSlots(e.blueprint)
              blueprintSlotsRef.current = e.blueprint
              const dist: BloomDistribution = {}
              for (const slot of e.blueprint) {
                const lvl = slot.bloom_level as BloomLevel | undefined
                if (lvl && lvl in dist) dist[lvl] = (dist[lvl] || 0) + 1
                else if (lvl) dist[lvl] = 1
              }
              setBloomDist(dist)
              bloomDistRef.current = dist
              // Add/update blueprint in feed (update on re-generation after reject)
              setFeedItems((prev) => {
                const existingIdx = prev.findIndex((f) => f.kind === 'blueprint')
                const newItem = { id: 'blueprint', kind: 'blueprint' as const, slots: e.blueprint!, bloomDist: dist }
                if (existingIdx >= 0) {
                  const next = [...prev]
                  next[existingIdx] = newItem
                  return next
                }
                return [...prev, newItem]
              })
            }
          }
          if (e.checkpoint_id === 2) {
            // checkpoint 2 has no blueprint in pipeline_paused — questions come via question_generated
            // and validation_issues via validation_result/validation_retry events
          }
          setSteps((prev) =>
            prev.map((s) => ({ ...s, active: false }))
          )
          break
        }

        case "reasoning_chunk": {
          // Append streamed token to the last (or matching) reasoning feed item
          const e = msg as ReasoningChunkEvent
          if (!e.chunk) break
          setFeedItems((prev) => {
            // find the target reasoning item
            const idx = e.step_id
              ? prev.findIndex((f) => f.id === e.step_id)
              : prev.map((f, i) => f.kind === 'reasoning' ? i : -1).filter(i => i >= 0).slice(-1)[0] ?? -1
            if (idx < 0) return prev
            const target = prev[idx] as Extract<FeedItem, { kind: 'reasoning' }>
            const next = [...prev]
            next[idx] = { ...target, chunks: [...target.chunks, e.chunk] }
            return next
          })
          break
        }

        case "question_updated": {
          // CP2 per-question regenerate: swap out the updated question in-place
          const updatedQ = (msg as { type: string; question_id: string; question: QuestionGeneratedEvent["question"] }).question
          const updatedId = (msg as { type: string; question_id: string }).question_id
          if (!updatedQ || !updatedId) break
          setQuestions((prev) =>
            prev.map((q) => (q.question_id === updatedId ? updatedQ : q))
          )
          setFeedItems((prev) =>
            prev.map((fi) =>
              fi.kind === "question" &&
              (fi as Extract<FeedItem, { kind: "question" }>).question.question_id === updatedId
                ? { ...fi, question: updatedQ }
                : fi
            )
          )
          setQuestionRegenerating(null)
          break
        }

        case "clarification_needed": {
          const e = msg as { type: "clarification_needed"; data: { clarification_questions: ClarificationQuestion[] } }
          const qs = e.data?.clarification_questions ?? []
          if (qs.length > 0) {
            setClarificationQuestions(qs)
            setClarificationAnswers(Object.fromEntries(qs.map((q) => [q.question_id, ""])))
          }
          setIsGenerating(false)
          break
        }

        default:
          break
      }
    },
    [reasoningOpen, onComplete, examType]
  )

  // ─── WebSocket connection ────────────────────────────────────────────────────

  useEffect(() => {
    unmountedRef.current = false
    setConnState("connecting")

    const ws = new WebSocket(resolvedWsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      if (unmountedRef.current) { ws.close(); return }
      setConnState("connected")
    }

    ws.onmessage = (evt) => {
      if (unmountedRef.current) return
      const raw = typeof evt.data === "string" ? evt.data : JSON.stringify(evt.data)
      handleMessage(raw)
    }

    ws.onerror = () => {
      if (unmountedRef.current) return
      setConnState("error")
    }

    ws.onclose = () => {
      if (unmountedRef.current) return
      if (connState !== "connected") setConnState("error")
    }

    return () => {
      unmountedRef.current = true
      ws.close()
    }
  }, [resolvedWsUrl, handleMessage])

  // ─── HITL approval ──────────────────────────────────────────────────────────

  const handleApprove = async () => {
    const cp = lastSeenCheckpointRef.current ?? activeCheckpointRef.current ?? 1
    setHitlApproving(true)
    try {
      await onApprove(examId, true, undefined, cp)
      if (activeCheckpointRef.current === cp) {
        setHitlApproved(true)
        hitlApprovedRef.current = true
      }
    } finally {
      setHitlApproving(false)
    }
  }

  const handleReject = async (feedback?: string) => {
    const cp = lastSeenCheckpointRef.current ?? activeCheckpointRef.current ?? 1
    setHitlRejecting(true)
    try {
      await onApprove(examId, false, feedback, cp)
    } finally {
      setHitlRejecting(false)
    }
  }

  const openRejectDialog = () => {
    setRejectFeedback("")
    setRejectDialogOpen(true)
  }

  const submitReject = async () => {
    setRejectDialogOpen(false)
    setHitlRejecting(true)
    try {
      await handleReject(rejectFeedback || "Yêu cầu điều chỉnh.")
    } finally {
      setHitlRejecting(false)
    }
  }

  // ─── Navigate to exam ────────────────────────────────────────────────────────

  const handleViewExam = () => {
    router.push(`/dashboard/exams/${examId}`)
  }

  // ─── Clarification submit ────────────────────────────────────────────────────

  const handleClarificationSubmit = async () => {
    if (clarificationSubmitting) return
    const unanswered = clarificationQuestions.filter(
      (q) => !(clarificationAnswers[q.question_id] ?? "").trim()
    )
    if (unanswered.length > 0) return

    setClarificationSubmitting(true)
    try {
      const answersText = clarificationQuestions
        .map((q) => `${q.question}: ${clarificationAnswers[q.question_id]}`)
        .join("\n")
      const backendBase = `${window.location.protocol}//${window.location.hostname}:8000`
      const res = await fetch(`${backendBase}/api/exams/${examId}/clarify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ answers: clarificationAnswers, answers_text: answersText }),
      })
      if (!res.ok) {
        console.error("[Clarification] submit failed", res.status)
        return
      }
      setClarificationQuestions([])
      setClarificationAnswers({})
      setIsGenerating(true)
    } catch (err) {
      console.error("[Clarification] submit error", err)
    } finally {
      setClarificationSubmitting(false)
    }
  }

  // ─── Count questions by type ─────────────────────────────────────────────────

  const mcqCount = questions.filter(q => (q.type || "mcq") === "mcq").length
  const essayCount = questions.filter(q => q.type === "essay").length

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col bg-background">

      {/* ── Header ── */}
      <header className="sticky top-0 z-10 flex items-center justify-between px-6 py-3 border-b bg-background/95 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Brain className="h-4 w-4" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-foreground">
              {completed ? "Đề thi đã sẵn sàng" : isGenerating ? "Đang sinh đề thi" : "Sẵn sàng tạo đề"}
            </h1>
            <p className="text-[11px] text-muted-foreground font-mono">
              {examId.slice(0, 8)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {questions.length > 0 && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {questions.length} câu hỏi
            </span>
          )}
          <div className={cn(
            "flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border",
            connState === "connected" && "border-emerald-200 bg-emerald-50 text-emerald-700",
            connState === "connecting" && "border-amber-200 bg-amber-50 text-amber-700",
            connState === "error" && "border-red-200 bg-red-50 text-red-700",
            connState === "idle" && "border-muted bg-muted text-muted-foreground",
          )}>
            {connState === "connected" ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
            {connState === "connected" && (
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
              </span>
            )}
            <span>
              {connState === "connected" ? "Live"
                : connState === "connecting" ? "Kết nối..."
                : connState === "error" ? "Lỗi" : "Chờ"}
            </span>
          </div>
        </div>
      </header>

      {/* ── Pipeline progress strip ── */}
      <div className="border-b bg-muted/30 px-6 py-3">
        <div className="max-w-2xl mx-auto flex items-center">
          {PIPELINE_STEPS.map((step, i) => {
            const s = steps.find(x => x.step === step.id)
            const isCompleted = s?.completed
            const isActive = s?.active
            const StepIcon = step.icon
            return (
              <div key={step.id} className="flex items-center flex-1 last:flex-none">
                <div className="flex flex-col items-center gap-0.5">
                  <div className={cn(
                    "h-6 w-6 rounded-full flex items-center justify-center border transition-all",
                    isCompleted && "bg-primary border-primary text-primary-foreground",
                    isActive && !isCompleted && "border-primary text-primary bg-primary/10",
                    !isCompleted && !isActive && "border-border text-muted-foreground bg-background"
                  )}>
                    {isCompleted ? <Check className="h-3 w-3" /> : isActive ? <Loader2 className="h-3 w-3 animate-spin" /> : <StepIcon className="h-3 w-3" />}
                  </div>
                  <span className={cn(
                    "text-[9px] font-medium text-center leading-tight max-w-[56px]",
                    isActive && "text-primary",
                    isCompleted && "text-muted-foreground",
                    !isActive && !isCompleted && "text-muted-foreground/40",
                  )}>{step.label}</span>
                </div>
                {i < PIPELINE_STEPS.length - 1 && (
                  <div className={cn("flex-1 h-px mx-1 mb-4 transition-colors", isCompleted ? "bg-primary" : "bg-border")} />
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Main feed (single centered column) ── */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-4 py-6">

          {/* Empty state */}
          {feedItems.length === 0 && !completed && activeCheckpoint === null && (
            <div className="flex flex-col items-center justify-center py-24 gap-3 text-muted-foreground">
              <div className="relative flex h-10 w-10 items-center justify-center">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary/20" />
                <Brain className="h-5 w-5 text-primary relative z-10" />
              </div>
              <p className="text-sm">Đang kết nối pipeline AI...</p>
            </div>
          )}

          {/* CP0 Requirements — shown before any feed items */}
          {activeCheckpoint === 0 && requirementsData && (
            <div className="mb-5 rounded-xl border border-blue-200 bg-blue-50/50 p-4 space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <div className="flex items-center gap-2">
                <ListChecks className="h-4 w-4 text-blue-600 shrink-0" />
                <span className="text-sm font-semibold text-blue-900">Xác nhận yêu cầu tạo đề</span>
              </div>
              <div className="space-y-1.5 text-xs">
                {requirementsData.scope && (
                  <p><span className="font-medium text-foreground">Phạm vi: </span><span className="text-muted-foreground">{requirementsData.scope.join(", ")}</span></p>
                )}
                {(requirementsData.mcq_count || requirementsData.total_questions) && (
                  <p>
                    <span className="font-medium text-foreground">Số câu: </span>
                    <span className="text-muted-foreground">
                      {requirementsData.mcq_count ? `${requirementsData.mcq_count} MCQ` : ""}
                      {requirementsData.essay_count ? ` + ${requirementsData.essay_count} Essay` : ""}
                      {!requirementsData.mcq_count && requirementsData.total_questions ? `${requirementsData.total_questions} câu` : ""}
                    </span>
                  </p>
                )}
                {requirementsData.bloom_distribution_summary && (
                  <pre className="mt-2 p-2 rounded bg-white/60 border border-blue-100 text-muted-foreground whitespace-pre-wrap font-sans text-[11px]">
                    {requirementsData.bloom_distribution_summary}
                  </pre>
                )}
              </div>
              {!hitlApproved ? (
                <div className="flex gap-2 pt-1">
                  <Button size="sm" className="flex-1 bg-emerald-600 hover:bg-emerald-700 h-8"
                    onClick={handleApprove} disabled={hitlApproving || hitlRejecting}>
                    {hitlApproving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <ThumbsUp className="h-3.5 w-3.5 mr-1.5" />}
                    Xác nhận
                  </Button>
                  <Button size="sm" variant="outline" className="flex-1 h-8 text-destructive border-destructive/30 hover:bg-destructive/5"
                    onClick={openRejectDialog} disabled={hitlApproving || hitlRejecting}>
                    <X className="h-3.5 w-3.5 mr-1.5" />Từ chối
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-2">
                  <Check className="h-4 w-4 text-emerald-600" />
                  <span className="text-sm font-medium text-emerald-800">Đã xác nhận — đang bắt đầu...</span>
                </div>
              )}
            </div>
          )}

          {/* Feed items */}
          {feedItems.map((item, idx) => {

            // ─── Reasoning / thinking block ───────────────────────────────
            if (item.kind === 'reasoning') {
              const isLast = idx === feedItems.length - 1
              const isStreaming = isLast && isGenerating
              const chunksText = item.chunks.join('')
              const hasChunks = chunksText.length > 0
              return (
                <ThinkingBlock
                  key={item.id}
                  label={item.stepLabel}
                  message={item.message}
                  chunksText={chunksText}
                  hasChunks={hasChunks}
                  isStreaming={isStreaming}
                />
              )
            }

            // ─── Blueprint ─────────────────────────────────────────────────
            if (item.kind === 'blueprint') {
              return (
                <div key={item.id} className="mb-5 animate-in fade-in slide-in-from-bottom-2 duration-400">
                  <div className="rounded-xl border bg-card shadow-sm overflow-hidden">
                    <div className="px-4 py-3 border-b bg-muted/20 space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2 min-w-0">
                          <Database className="h-4 w-4 text-primary shrink-0" />
                          <span className="text-sm font-semibold truncate">Sườn đề · {item.slots.length} câu hỏi</span>
                        </div>
                        <button
                          type="button"
                          aria-expanded={blueprintExpanded}
                          onClick={() => setBlueprintExpanded(open => !open)}
                          className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md border bg-background px-2 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        >
                          {blueprintExpanded ? (
                            <>
                              <ChevronUp className="h-3.5 w-3.5" />
                              Thu gọn
                            </>
                          ) : (
                            <>
                              <ChevronDown className="h-3.5 w-3.5" />
                              Xem sườn
                            </>
                          )}
                        </button>
                      </div>
                      <div className="flex gap-1.5 flex-wrap">
                        {BLOOM_ORDER.filter(b => item.bloomDist[b]).map(b => (
                          <span key={b} className={cn("text-[10px] px-1.5 py-0.5 rounded border font-medium", BLOOM_CONFIG[b]?.bg, BLOOM_CONFIG[b]?.color)}>
                            {BLOOM_CONFIG[b]?.short} {item.bloomDist[b]}
                          </span>
                        ))}
                      </div>
                    </div>
                    {blueprintExpanded && (
                      <div className="divide-y">
                        {item.slots.map((slot, i) => {
                          const bl = slot.bloom_level as BloomLevel | undefined
                          const bc = bl && BLOOM_CONFIG[bl] ? BLOOM_CONFIG[bl] : null
                          return (
                            <div key={slot.question_id || i} className="flex items-start gap-3 px-4 py-2.5 hover:bg-muted/10 transition-colors">
                              <span className="w-5 text-xs text-muted-foreground/50 text-right shrink-0 pt-0.5">{i + 1}</span>
                              <div className="flex items-center gap-1.5 shrink-0 pt-0.5">
                                <Badge variant={(slot.type || 'mcq') === 'mcq' ? 'secondary' : 'outline'} className="text-[10px] px-1.5">
                                  {(slot.type || 'mcq').toUpperCase()}
                                </Badge>
                                {bc && <span className={cn("text-[10px] px-1.5 py-0.5 rounded border font-medium", bc.bg, bc.color)}>{bc.short}</span>}
                              </div>
                              <div className="flex-1 min-w-0">
                                {slot.chapter && <p className="text-xs text-muted-foreground/70 mb-0.5">{slot.chapter as string}</p>}
                                {(slot.primary_section_title || slot.section) && (
                                  <p className="text-xs text-muted-foreground/80 mb-0.5 flex flex-wrap items-center gap-1">
                                    <span className="font-medium text-primary/70">
                                      {(slot.primary_section_title || slot.section) as string}
                                    </span>
                                    {slot.secondary_section_titles && (slot.secondary_section_titles as string[]).length > 0 && (
                                      <>
                                        {(slot.secondary_section_titles as string[]).map((t, si) => (
                                          <span key={si} className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted border border-border/50 text-muted-foreground">
                                            +{t}
                                          </span>
                                        ))}
                                      </>
                                    )}
                                  </p>
                                )}
                                {slot.topic_hint && <p className="text-sm text-foreground">{slot.topic_hint as string}</p>}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>

                  {/* Inline HITL CP1 actions */}
                  {activeCheckpoint === 1 && !hitlApproved && (
                    <div className="mt-3 flex gap-2">
                      <Button className="flex-1 bg-emerald-600 hover:bg-emerald-700 h-9 text-sm"
                        onClick={handleApprove} disabled={hitlApproving || hitlRejecting}>
                        {hitlApproving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" /> : <ThumbsUp className="h-3.5 w-3.5 mr-2" />}
                        Xác nhận sườn đề
                      </Button>
                      <Button variant="outline" className="flex-1 h-9 text-sm border-destructive/30 text-destructive hover:bg-destructive/5"
                        onClick={openRejectDialog} disabled={hitlApproving || hitlRejecting}>
                        {hitlRejecting ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" /> : <X className="h-3.5 w-3.5 mr-2" />}
                        Yêu cầu chỉnh sửa
                      </Button>
                    </div>
                  )}
                  {activeCheckpoint === 1 && hitlApproved && (
                    <div className="mt-3 flex items-center gap-2 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-2">
                      <Check className="h-4 w-4 text-emerald-600" />
                      <span className="text-sm font-medium text-emerald-800">Đã xác nhận sườn đề — đang sinh câu hỏi...</span>
                    </div>
                  )}
                </div>
              )
            }

            // ─── Question ─────────────────────────────────────────────────
            if (item.kind === 'question') {
              const qId = item.question.question_id
              const isSelected = selectedQuestionId === qId
              const isRegenerating = questionRegenerating === qId
              return (
                <div key={item.id} className="mb-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
                  <QuestionCard question={item.question} index={item.index} />
                  {activeCheckpoint === 2 && (
                    <div className="mt-1.5 pl-1">
                      {!isSelected ? (
                        <button
                          className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-violet-700 transition-colors"
                          onClick={() => { setSelectedQuestionId(qId ?? null); setQuestionEditPrompt("") }}
                        >
                          <Pencil className="h-3 w-3" />
                          Chỉnh sửa câu này
                        </button>
                      ) : (
                        <div className="rounded-lg border border-violet-200 bg-violet-50/50 p-2.5 space-y-2">
                          <textarea
                            className="w-full text-xs rounded border border-violet-200 bg-white/80 px-2 py-1.5 resize-none focus:outline-none focus:ring-1 focus:ring-violet-300"
                            rows={2}
                            placeholder="Nhập yêu cầu chỉnh sửa... (để trống để tạo lại ngẫu nhiên)"
                            value={questionEditPrompt}
                            onChange={(e) => setQuestionEditPrompt(e.target.value)}
                            disabled={isRegenerating}
                            autoFocus
                          />
                          <div className="flex gap-1.5">
                            <button
                              className="flex items-center gap-1 text-[11px] px-3 py-1.5 rounded bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
                              disabled={!!isRegenerating}
                              onClick={async () => {
                                setQuestionRegenerating(qId ?? null)
                                try {
                                  await examsApi.partialRegenerate(examId, { question_id: qId!, prompt: questionEditPrompt || undefined })
                                  setSelectedQuestionId(null)
                                  setQuestionEditPrompt("")
                                } catch (err) {
                                  console.error(err)
                                  setQuestionRegenerating(null)
                                }
                              }}
                            >
                              {isRegenerating
                                ? <><Loader2 className="h-3 w-3 animate-spin" /> Đang tạo...</>
                                : <><RefreshCw className="h-3 w-3" /> Tạo lại</>}
                            </button>
                            <button
                              className="text-[11px] px-2.5 py-1.5 rounded border border-violet-200 text-violet-700 hover:bg-violet-100 transition-colors"
                              onClick={() => { setSelectedQuestionId(null); setQuestionEditPrompt("") }}
                            >
                              Hủy
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            }

            // ─── Validation ───────────────────────────────────────────────
            if (item.kind === 'validation') {
              return (
                <div key={item.id} className="mb-4 animate-in fade-in duration-300">
                  <div className="rounded-xl border border-orange-200 bg-orange-50/50 p-3 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <AlertCircle className="h-3.5 w-3.5 text-orange-600 shrink-0" />
                      <p className="text-xs font-semibold text-orange-800">{item.issues.length} vấn đề phát hiện — đang tự động sửa...</p>
                    </div>
                    {item.issues.slice(0, 3).map((issue, i) => (
                      <p key={i} className="text-[10px] text-orange-700 pl-5">• {issue.question_id}: {issue.issue_type || issue.detail}</p>
                    ))}
                  </div>
                </div>
              )
            }

            return null
          })}

          {/* Typing indicator while generating */}
          {isGenerating && feedItems.length > 0 && feedItems[feedItems.length - 1]?.kind === 'reasoning' && (
            <div className="flex items-center gap-1.5 pl-7 pb-3">
              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          )}

          {/* CP2 full exam review actions */}
          {activeCheckpoint === 2 && questions.length > 0 && (
            <div className="mt-2 mb-5 rounded-xl border border-violet-200 bg-violet-50/50 p-4 space-y-3 animate-in fade-in duration-300">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-violet-600 shrink-0" />
                <span className="text-sm font-semibold text-violet-900">Duyệt đề hoàn chỉnh</span>
                <span className="ml-auto text-xs text-muted-foreground">{questions.length} câu hỏi</span>
              </div>
              {validationIssues.length > 0 ? (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-destructive">{validationIssues.length} vấn đề phát hiện:</p>
                  {validationIssues.slice(0, 3).map((issue, i) => (
                    <div key={i} className="flex items-start gap-1.5 p-1.5 rounded bg-red-50 border border-red-100 text-[10px]">
                      <AlertCircle className="h-3 w-3 text-red-500 shrink-0 mt-0.5" />
                      <span className="text-red-700">{issue.question_id}: {issue.issue_type || issue.detail}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex items-center gap-2 p-2 rounded bg-emerald-50 border border-emerald-100">
                  <Check className="h-3.5 w-3.5 text-emerald-600" />
                  <span className="text-xs text-emerald-700 font-medium">Đề đạt yêu cầu kiểm tra</span>
                </div>
              )}
              {!hitlApproved ? (
                <div className="flex gap-2">
                  <Button className="flex-1 bg-emerald-600 hover:bg-emerald-700 h-9 text-sm"
                    onClick={handleApprove} disabled={hitlApproving || hitlRejecting}>
                    {hitlApproving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" /> : <ThumbsUp className="h-3.5 w-3.5 mr-2" />}
                    Xác nhận đề thi
                  </Button>
                  <Button variant="outline" className="flex-1 h-9 text-sm border-destructive/30 text-destructive hover:bg-destructive/5"
                    onClick={openRejectDialog} disabled={hitlApproving || hitlRejecting}>
                    {hitlRejecting ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" /> : <X className="h-3.5 w-3.5 mr-2" />}
                    Yêu cầu sửa tất cả
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-2">
                  <Check className="h-4 w-4 text-emerald-600" />
                  <span className="text-sm font-medium text-emerald-800">Đã xác nhận — đang hoàn tất...</span>
                </div>
              )}
            </div>
          )}

          {/* Clarification chat */}
          {clarificationQuestions.length > 0 && (
            <div className="mb-5 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <div className="flex gap-3">
                <div className="flex h-7 w-7 items-center justify-center rounded-full border bg-amber-100 border-amber-300 text-amber-700 shrink-0">
                  <MessageCircle className="h-3.5 w-3.5" />
                </div>
                <div className="flex-1 rounded-xl rounded-tl-none bg-amber-50 border border-amber-200 px-4 py-3 space-y-3">
                  <p className="text-xs font-semibold text-amber-700">AI cần thêm thông tin</p>
                  {clarificationQuestions.map((q, cidx) => (
                    <div key={q.question_id} className="space-y-1.5">
                      <p className="text-sm text-foreground leading-snug">
                        <span className="text-muted-foreground mr-1.5">{cidx + 1}.</span>{q.question}
                      </p>
                      <textarea
                        rows={2}
                        className="w-full rounded-lg border border-amber-200 bg-white/80 px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-amber-300 resize-none"
                        placeholder="Nhập câu trả lời..."
                        value={clarificationAnswers[q.question_id] ?? ""}
                        onChange={(e) => setClarificationAnswers(prev => ({ ...prev, [q.question_id]: e.target.value }))}
                      />
                    </div>
                  ))}
                  <button
                    onClick={handleClarificationSubmit}
                    disabled={clarificationSubmitting || clarificationQuestions.some(q => !(clarificationAnswers[q.question_id] ?? "").trim())}
                    className="flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {clarificationSubmitting
                      ? <><Loader2 className="h-4 w-4 animate-spin" />Đang gửi...</>
                      : <><Send className="h-4 w-4" />Gửi</>}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Completion banner */}
          {completed && (
            <div className="mb-4 animate-in fade-in zoom-in-95 duration-500">
              <div className="rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-teal-50 p-6 text-center space-y-4">
                <div className="flex justify-center">
                  <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                    <PartyPopper className="h-7 w-7" />
                  </div>
                </div>
                <div>
                  <p className="font-semibold text-emerald-900 text-base">Đề thi đã hoàn tất!</p>
                  <p className="text-sm text-emerald-700 mt-1">
                    {questions.length} câu hỏi · {mcqCount} MCQ · {essayCount} Essay
                  </p>
                  {costReport?.total_cost_usd != null && (
                    <p className="text-xs text-muted-foreground mt-1">Chi phí: ${costReport.total_cost_usd.toFixed(4)}</p>
                  )}
                </div>
                <Button className="bg-emerald-600 hover:bg-emerald-700 w-full sm:w-auto" onClick={handleViewExam}>
                  Xem đề đầy đủ <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
            </div>
          )}

          {/* Connection error */}
          {connState === "error" && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 mb-4">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-red-900">Lỗi kết nối WebSocket</p>
                  <p className="text-xs text-muted-foreground mt-1 font-mono break-all">{resolvedWsUrl}</p>
                </div>
              </div>
            </div>
          )}

          <div ref={feedEndRef} />
        </div>
      </div>

      {/* ── Reject Feedback Dialog ── */}
      <Dialog open={rejectDialogOpen} onOpenChange={setRejectDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Từ chối &amp; Yêu cầu điều chỉnh</DialogTitle>
            <DialogDescription>
              Mô tả vấn đề bạn muốn AI điều chỉnh. Phản hồi càng chi tiết, kết quả càng chính xác.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Textarea
              placeholder="Ví dụ: Phạm vi thiếu Chương 3, phân bố Bloom không chính xác, cần thêm câu Vận dụng cao..."
              value={rejectFeedback}
              onChange={(e) => setRejectFeedback(e.target.value)}
              rows={4}
              className="resize-none"
              maxLength={500}
            />
            <p className="text-xs text-muted-foreground text-right">
              {rejectFeedback.length}/500 ký tự
            </p>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setRejectDialogOpen(false)} disabled={hitlRejecting}>
              Hủy
            </Button>
            <Button variant="destructive" onClick={submitReject} disabled={hitlRejecting}>
              {hitlRejecting ? (
                <><Loader2 className="h-3.5 w-3.5 animate-spin" />Đang gửi...</>
              ) : (
                <><X className="h-3.5 w-3.5" />Gửi phản hồi</>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Celebration overlay ── */}
      {showCelebration && (
        <div className="fixed inset-0 pointer-events-none z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-primary/5 animate-in fade-in duration-300" />
          <div className="relative flex flex-col items-center gap-3 animate-in zoom-in-95 duration-500">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 text-white shadow-lg animate-bounce">
              <PartyPopper className="h-8 w-8" />
            </div>
            <p className="text-xl font-bold text-foreground">Hoàn tất!</p>
            <p className="text-sm text-muted-foreground">
              {questions.length} câu hỏi đã được sinh thành công
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── ThinkingBlock sub-component ─────────────────────────────────────────────

function ThinkingBlock({
  label,
  message,
  chunksText,
  hasChunks,
  isStreaming,
}: {
  label: string
  message: string
  chunksText: string
  hasChunks: boolean
  isStreaming: boolean
}) {
  const [expanded, setExpanded] = useState(true)

  useEffect(() => {
    if (isStreaming) setExpanded(true)
  }, [isStreaming])

  const hasContent = hasChunks || !!message

  return (
    <div className="mb-4 animate-in fade-in slide-in-from-bottom-1 duration-300">
      {/* Step label row */}
      <div className="flex items-center gap-2 mb-1">
        <div className={cn(
          "h-5 w-5 rounded-full flex items-center justify-center border shrink-0 transition-colors",
          isStreaming ? "border-primary/40 bg-primary/5 text-primary" : "border-border bg-muted text-muted-foreground"
        )}>
          {isStreaming
            ? <Loader2 className="h-3 w-3 animate-spin" />
            : <Check className="h-3 w-3" />}
        </div>
        <span className={cn(
          "text-sm font-medium transition-colors",
          isStreaming ? "text-foreground" : "text-muted-foreground"
        )}>
          {label}
        </span>
        {!isStreaming && hasContent && (
          <button
            className="ml-auto flex items-center gap-0.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => setExpanded(v => !v)}
          >
            {expanded
              ? <><ChevronUp className="h-3 w-3" />Thu gọn</>
              : <><ChevronDown className="h-3 w-3" />Chi tiết</>}
          </button>
        )}
      </div>

      {/* Thinking content — Claude-style streaming text with left border */}
      {(isStreaming || expanded) && hasContent && (
        <div className="ml-7">
          {message && !hasChunks && (
            <p className="text-sm text-muted-foreground mb-1.5 leading-relaxed">{message}</p>
          )}
          {(hasChunks || isStreaming) && (
            <div className={cn(
              "border-l-2 pl-3 py-0.5 transition-colors",
              isStreaming ? "border-primary/50" : "border-border"
            )}>
              <p className={cn(
                "text-sm leading-relaxed whitespace-pre-wrap",
                isStreaming ? "text-foreground/90" : "text-muted-foreground/80"
              )}>
                {chunksText}
                {isStreaming && (
                  <span className="inline-block w-[2px] h-[1.1em] bg-primary ml-0.5 animate-pulse align-text-bottom rounded-sm" />
                )}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── QuestionCard sub-component ───────────────────────────────────────────────

/** Returns true only if text likely contains LaTeX math delimiters */
function hasMath(text: string): boolean {
  return text.includes('$') || text.includes('\\(') || text.includes('\\[')
}

/** Render text: use LatexRenderer only when math is detected, else plain span */
function MathText({ children, className }: { children: string; className?: string }) {
  if (!children) return null
  if (hasMath(children)) {
    return <LatexRenderer className={className}>{children}</LatexRenderer>
  }
  return <span className={className}>{children}</span>
}

function QuestionCard({
  question,
  index,
}: {
  question: QuestionGeneratedEvent["question"]
  index: number
}) {
  const bloom = question.bloom_level as BloomLevel | undefined
  const bloomInfo = bloom && BLOOM_CONFIG[bloom] ? BLOOM_CONFIG[bloom] : null
  const qType = question.type || "mcq"
  const stem = question.stem || question.content || ""
  const rawOptions = question.options as Record<string, string> | undefined
  const optionsArray = question.optionsArray || []

  const options: Array<{ label: string; text: string }> =
    optionsArray.length > 0
      ? optionsArray
      : rawOptions
        ? Object.entries(rawOptions).map(([label, text]) => ({ label, text }))
        : []

  return (
    <div
      className="rounded-xl border bg-card shadow-sm p-4 animate-in slide-in-from-top-2 duration-300"
      style={{ animationDelay: `${Math.min(index * 30, 300)}ms` }}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-muted-foreground">
            {index + 1}
          </span>
          <Badge
            variant={qType === "mcq" ? "secondary" : "outline"}
            className={cn(
              "text-[10px]",
              qType === "mcq" && "bg-blue-100 text-blue-700 border-blue-200",
              qType === "essay" && "bg-violet-100 text-violet-700 border-violet-200",
              qType === "dung_sai" && "bg-amber-100 text-amber-700 border-amber-200",
              qType === "short_answer" && "bg-teal-100 text-teal-700 border-teal-200",
            )}
          >
            {qType === "mcq" ? "MCQ" : qType === "essay" ? "Essay" : qType === "dung_sai" ? "Đúng-Sai" : qType === "short_answer" ? "Trả lời ngắn" : qType.toUpperCase()}
          </Badge>
          {bloomInfo && (
            <span className={cn("text-xs px-2 py-0.5 rounded-full border font-medium", bloomInfo.bg, bloomInfo.color)}>
              {bloomInfo.label}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {question.difficulty_score != null && (
            <span className="text-xs text-muted-foreground">
              {Math.round(question.difficulty_score * 100)}% độ khó
            </span>
          )}
          {question.chapter && (
            <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
              {question.chapter}
            </span>
          )}
        </div>
      </div>

      {stem && (
        <div className="text-sm text-foreground leading-relaxed mb-3">
          <MathText>{stem}</MathText>
        </div>
      )}

      {qType === "mcq" && options.length > 0 && (
        <div className="space-y-1.5">
          {options.map((opt, oi) => (
            <div key={opt.label || oi} className="flex items-start gap-2 rounded-lg border bg-muted/30 px-3 py-2">
              <span className="text-xs font-semibold text-muted-foreground w-5 shrink-0 mt-0.5">
                {String.fromCharCode(65 + oi)}.
              </span>
              <span className="text-sm text-foreground">
                <MathText>{opt.text}</MathText>
              </span>
            </div>
          ))}
        </div>
      )}

      {qType === "dung_sai" && question.propositions && question.propositions.length > 0 && (
        <div className="space-y-1.5">
          {question.propositions.map((prop) => (
            <div
              key={prop.label}
              className={`flex items-start gap-2 rounded-lg border p-2.5 text-sm ${
                prop.is_correct
                  ? "border-emerald-500/40 bg-emerald-500/10"
                  : "border-red-500/30 bg-red-500/10"
              }`}
            >
              <span className="font-semibold text-xs w-4 shrink-0 mt-0.5">{prop.label})</span>
              <span className="flex-1">{prop.text}</span>
              <span className={`text-xs font-medium shrink-0 ${prop.is_correct ? "text-emerald-400" : "text-red-400"}`}>
                {prop.is_correct ? "Đúng" : "Sai"}
              </span>
            </div>
          ))}
        </div>
      )}

      {qType === "short_answer" && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 space-y-1">
          <p className="text-sm">
            <span className="font-medium text-amber-300 text-xs">Đáp án: </span>
            <span className="font-mono text-sm">{question.correct_answer ?? "—"}</span>
            {question.unit && <span className="ml-1 text-xs text-muted-foreground">{question.unit}</span>}
          </p>
          {question.solution && (
            <p className="text-xs text-muted-foreground whitespace-pre-line">{question.solution}</p>
          )}
        </div>
      )}

      {qType === "essay" && question.rubric && (
        <div className="rounded-lg border bg-muted/30 p-3 space-y-1">
          <p className="text-xs font-semibold text-muted-foreground mb-1">Đáp án & thang điểm</p>
          {Object.entries(question.rubric).map(([score, desc]) => (
            <div key={score} className="flex items-start gap-2 text-xs">
              <span className="font-bold text-primary shrink-0 w-6">{score}đ</span>
              <span className="text-muted-foreground">{String(desc)}</span>
            </div>
          ))}
        </div>
      )}

      {!stem && options.length === 0 && (
        <Skeleton className="h-4 w-3/4" />
      )}
    </div>
  )
}
