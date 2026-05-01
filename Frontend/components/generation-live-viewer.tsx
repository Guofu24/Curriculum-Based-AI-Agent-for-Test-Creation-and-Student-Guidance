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
  Loader,
  Wifi,
  WifiOff,
  PartyPopper,
  Eye,
  FileText,
  ListChecks,
  Info,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
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

  // Blueprint
  const [blueprintSlots, setBlueprintSlots] = useState<BlueprintSlot[]>([])
  const [requirementsData, setRequirementsData] = useState<RequirementsData | null>(null)

  // Question stream
  const [questions, setQuestions] = useState<QuestionGeneratedEvent["question"][]>([])
  const [isGenerating, setIsGenerating] = useState(false)

  // Validation
  const [validationIssues, setValidationIssues] = useState<ValidationIssue[]>([])

  // Completion
  const [completed, setCompleted] = useState(false)
  const [showCelebration, setShowCelebration] = useState(false)
  const [completionBlueprint, setCompletionBlueprint] = useState<BlueprintSlot[]>([])
  const [bloomDist, setBloomDist] = useState<BloomDistribution | null>(null)
  const [costReport, setCostReport] = useState<CostReport | null>(null)

  // Unified stream feed — accumulates all events in order
  const [feedItems, setFeedItems] = useState<FeedItem[]>([])
  const feedEndRef = useRef<HTMLDivElement | null>(null)

  // Auto-scroll feed to bottom on new items
  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [feedItems])

  // Connection
  const wsRef = useRef<WebSocket | null>(null)
  const unmountedRef = useRef(false)

  // ─── Derived ────────────────────────────────────────────────────────────────

  const completedCount = steps.filter((s) => s.completed).length
  const progressPct = Math.round((completedCount / PIPELINE_STEPS.length) * 100)
  const currentStep = steps.find((s) => s.active)

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
            if (qId && prev.some((existing) => existing.question_id === qId)) return prev
            const next = [...prev, q]
            // Also add to feed
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
            // Add blueprint to feed
            if (slots.length > 0) {
              setFeedItems((prev) => {
                if (prev.some((f) => f.kind === 'blueprint')) return prev
                return [...prev, { id: 'blueprint', kind: 'blueprint' as const, slots, bloomDist: dist }]
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
            if ((d as { blueprint?: BlueprintSlot[] }).blueprint) {
              setCompletionBlueprint((d as { blueprint: BlueprintSlot[] }).blueprint)
            }
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
              // Add blueprint to feed
              setFeedItems((prev) => {
                if (prev.some((f) => f.kind === 'blueprint')) return prev
                return [...prev, { id: 'blueprint', kind: 'blueprint' as const, slots: e.blueprint!, bloomDist: dist }]
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

  // Track which checkpoint the user last saw (so we can still show it in the panel)
  const [lastSeenCheckpoint, setLastSeenCheckpoint] = useState<number | null>(null)

  const handleApprove = async () => {
    const cp = lastSeenCheckpointRef.current ?? activeCheckpointRef.current ?? 1
    setHitlApproving(true)
    try {
      await onApprove(examId, true, undefined, cp)
      // Only mark as approved if we're still on the same checkpoint.
      // approveBlueprint is a blocking call that returns AFTER the graph has run
      // to the next interrupt — by then the WebSocket may have already delivered
      // hitl_checkpoint N+1 and reset hitlApproved=false. Setting it back to true
      // here would override that reset and hide the approval button for the next CP.
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

  // ─── Count questions by type ─────────────────────────────────────────────────

  const mcqCount = questions.filter(q => (q.type || "mcq") === "mcq").length
  const essayCount = questions.filter(q => q.type === "essay").length

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col min-h-screen bg-background">
      {/* ── Header ── */}
      <header className="flex items-center justify-between px-6 py-4 border-b bg-card/80 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <Brain className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-foreground">
              {completed ? "Đề thi đã sẵn sàng" : isGenerating ? "Đang sinh đề thi" : "Sẵn sàng tạo đề"}
            </h1>
            <p className="text-xs text-muted-foreground font-mono">
              exam · {examId.slice(0, 8)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {questions.length > 0 && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-secondary/60 text-sm">
              <span className="text-muted-foreground">Câu:</span>
              <span className="font-semibold tabular-nums">{questions.length}</span>
            </div>
          )}
          <div
            className={cn(
              "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border",
              connState === "connected" && "border-emerald-200 bg-emerald-50 text-emerald-700",
              connState === "connecting" && "border-amber-200 bg-amber-50 text-amber-700",
              connState === "error" && "border-red-200 bg-red-50 text-red-700",
              connState === "idle" && "border-muted bg-muted text-muted-foreground"
            )}
          >
            {connState === "connected" ? (
              <Wifi className="h-3 w-3" />
            ) : (
              <WifiOff className="h-3 w-3" />
            )}
            {connState === "connected" && (
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
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

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left sidebar ── */}
        <div className="w-[340px] shrink-0 border-r overflow-y-auto p-5 space-y-4">

          {/* Progress summary */}
          <div className="rounded-xl border bg-card p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-foreground">Tiến độ</span>
              <span className="text-xs text-muted-foreground tabular-nums">
                {completedCount}/{PIPELINE_STEPS.length} bước
              </span>
            </div>
            <Progress value={progressPct} className="h-1.5" />
            <p className="text-xs text-muted-foreground text-right tabular-nums">{progressPct}%</p>
          </div>

          {/* ── Pipeline steps ── */}
          <div className="rounded-xl border bg-card p-4 space-y-0">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
              Pipeline
            </p>
            {PIPELINE_STEPS.map((step, index) => {
              const s = steps.find((x) => x.step === step.id)
              const isCompleted = s?.completed
              const isActive = s?.active
              const StepIcon = step.icon

              return (
                <div key={step.id} className="flex items-start gap-3">
                  <div className="flex flex-col items-center">
                    <div
                      className={cn(
                        "flex h-7 w-7 items-center justify-center rounded-lg border-2 transition-all duration-300",
                        isCompleted && "border-primary bg-primary text-primary-foreground",
                        isActive && !isCompleted && "border-primary bg-primary/10 text-primary animate-pulse",
                        !isCompleted && !isActive && "border-border bg-muted text-muted-foreground"
                      )}
                    >
                      {isCompleted ? (
                        <Check className="h-3.5 w-3.5" />
                      ) : isActive ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <StepIcon className="h-3.5 w-3.5" />
                      )}
                    </div>
                    {index < PIPELINE_STEPS.length - 1 && (
                      <div
                        className={cn(
                          "w-0.5 flex-1 my-1 transition-colors duration-300",
                          isCompleted ? "bg-primary" : "bg-border"
                        )}
                        style={{ minHeight: 12 }}
                      />
                    )}
                  </div>

                  <div className="flex flex-col pb-4 pt-0.5 min-w-0">
                    <span
                      className={cn(
                        "text-sm font-medium transition-colors",
                        isCompleted && "text-foreground",
                        isActive && !isCompleted && "text-primary",
                        !isCompleted && !isActive && "text-muted-foreground"
                      )}
                    >
                      {step.label}
                    </span>
                    {s?.message && (
                      <span
                        className={cn(
                          "text-xs mt-0.5 italic",
                          isActive ? "text-muted-foreground" : "text-muted-foreground/70"
                        )}
                      >
                        {s.message}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* ── HITL Checkpoint 0: Requirements Confirmation ── */}
          {activeCheckpoint === 0 && requirementsData && (
            <HITLCard
              title="Xác nhận yêu cầu"
              subtitle="Checkpoint 0 — Kiểm tra yêu cầu trước khi bắt đầu"
              icon={<ListChecks className="h-4 w-4" />}
              colorClass="border-blue-200 bg-gradient-to-br from-blue-50 to-indigo-50"
              iconBg="bg-blue-200 text-blue-800"
              infoTooltip={
                <div className="space-y-1.5">
                  <p className="font-semibold text-foreground">Checkpoint 0 là gì?</p>
                  <p className="text-muted-foreground">
                    Đây là bước <strong>xác nhận yêu cầu</strong> trước khi AI bắt đầu tạo đề. Hệ thống sẽ kiểm tra:
                  </p>
                  <ul className="text-muted-foreground list-disc list-inside space-y-0.5">
                    <li>Phạm vi đề thi (các chương đã chọn)</li>
                    <li>Số lượng câu hỏi (MCQ / Essay)</li>
                    <li>Phân bố Bloom Taxonomy</li>
                    <li>Yêu cầu bổ sung của bạn</li>
                  </ul>
                  <p className="text-muted-foreground pt-1">
                    Nếu thông tin chính xác, nhấn <strong>Xác nhận</strong> để tiếp tục.
                    Nếu có sai sót, nhấn <strong>Từ chối</strong> và mô tả vấn đề.
                  </p>
                </div>
              }
            >
              <div className="space-y-2 text-xs">
                {requirementsData.scope && (
                  <div>
                    <span className="font-medium text-foreground">Phạm vi: </span>
                    <span className="text-muted-foreground">{requirementsData.scope.join(", ")}</span>
                  </div>
                )}
                {(requirementsData.mcq_count || requirementsData.total_questions) && (
                  <div>
                    <span className="font-medium text-foreground">Số câu: </span>
                    <span className="text-muted-foreground">
                      {requirementsData.mcq_count ? `${requirementsData.mcq_count} MCQ` : ""}
                      {requirementsData.essay_count ? ` + ${requirementsData.essay_count} Essay` : ""}
                      {!requirementsData.mcq_count && requirementsData.total_questions
                        ? `${requirementsData.total_questions} câu`
                        : null}
                    </span>
                  </div>
                )}
                {requirementsData.bloom_distribution_summary && (
                  <div className="mt-2 p-2 rounded bg-white/60 border border-blue-100">
                    <span className="font-medium text-foreground">Phân bố Bloom:</span>
                    <pre className="mt-1 text-muted-foreground whitespace-pre-wrap font-sans">
                      {requirementsData.bloom_distribution_summary}
                    </pre>
                  </div>
                )}
                {requirementsData.user_prompt && (
                  <div>
                    <span className="font-medium text-foreground">Yêu cầu thêm: </span>
                    <span className="text-muted-foreground italic">{requirementsData.user_prompt}</span>
                  </div>
                )}
              </div>

              {hitlApproved ? (
                <div className="flex items-center gap-2 rounded-lg bg-emerald-100 border border-emerald-200 px-3 py-2 mt-3">
                  <Check className="h-4 w-4 text-emerald-600" />
                  <span className="text-sm font-medium text-emerald-800">Đã xác nhận</span>
                </div>
              ) : (
                <div className="flex gap-2 mt-3">
                  <Button size="sm" className="flex-1 h-9 bg-emerald-600 hover:bg-emerald-700"
                    onClick={handleApprove} disabled={hitlApproving || hitlRejecting}>
                    {hitlApproving ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <ThumbsUp className="h-3.5 w-3.5" />}
                    Xác nhận
                  </Button>
                  <Button size="sm" variant="outline"
                    className="flex-1 h-9 border-blue-300 text-blue-800 hover:bg-blue-100"
                    onClick={openRejectDialog} disabled={hitlApproving || hitlRejecting}>
                    {hitlRejecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <X className="h-3.5 w-3.5" />}
                    Từ chối
                  </Button>
                </div>
              )}
            </HITLCard>
          )}

          {/* ── HITL Checkpoint 1: Blueprint Review ── */}
          {activeCheckpoint === 1 && (
            <HITLCard
              title="Xem xét sườn đề"
              subtitle="Checkpoint 1 — Xem ma trận trước khi sinh câu hỏi"
              icon={<Eye className="h-4 w-4" />}
              colorClass="border-amber-200 bg-gradient-to-br from-amber-50 to-orange-50"
              iconBg="bg-amber-200 text-amber-800"
              infoTooltip={
                <div className="space-y-1.5">
                  <p className="font-semibold text-foreground">Checkpoint 1 là gì?</p>
                  <p className="text-muted-foreground">
                    Đây là bước <strong>xem xét sườn đề (blueprint)</strong>. AI đã lên kế hoạch tổng thể:
                  </p>
                  <ul className="text-muted-foreground list-disc list-inside space-y-0.5">
                    <li>Bao nhiêu câu hỏi cho mỗi loại (MCQ / Essay)</li>
                    <li>Phân bố Bloom cho mỗi câu hỏi</li>
                    <li>Câu hỏi thuộc chương nào</li>
                    <li>Độ khó ước tính của từng câu</li>
                  </ul>
                  <p className="text-muted-foreground pt-1">
                    Nếu blueprint phù hợp, nhấn <strong>Xác nhận sườn đề</strong>.
                    Nếu cần thay đổi (thiếu chương, sai phân bố Bloom...), nhấn <strong>Từ chối</strong> và mô tả.
                  </p>
                </div>
              }
            >
              {blueprintSlots.length === 0 ? (
                <div className="text-center py-4">
                  <p className="text-xs text-muted-foreground">
                    Đang tải sườn đề...
                  </p>
                </div>
              ) : (
                <>
                  {/* Blueprint summary */}
                  <div className="flex items-center gap-2 mb-2">
                    <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">
                      {blueprintSlots.length} câu hỏi trong sườn đề
                    </span>
                  </div>

                  {/* Blueprint table */}
                  <div className="rounded-lg border border-amber-200/60 bg-white/70 overflow-hidden">
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-amber-200/40 bg-amber-50/50">
                            <th className="px-2 py-1.5 text-left font-semibold text-amber-900">#</th>
                            <th className="px-2 py-1.5 text-left font-semibold text-amber-900">Loại</th>
                            <th className="px-2 py-1.5 text-left font-semibold text-amber-900">Bloom</th>
                            <th className="px-2 py-1.5 text-left font-semibold text-amber-900">Chương</th>
                            <th className="px-2 py-1.5 text-left font-semibold text-amber-900">Độ khó</th>
                          </tr>
                        </thead>
                        <tbody>
                          {blueprintSlots.map((slot, i) => {
                            const bloomLvl = slot.bloom_level as BloomLevel | undefined
                            const bloomInfo = bloomLvl && BLOOM_CONFIG[bloomLvl] ? BLOOM_CONFIG[bloomLvl] : null
                            return (
                              <tr key={slot.question_id || i} className="border-b border-amber-100/40 last:border-0">
                                <td className="px-2 py-1.5 font-mono text-muted-foreground">{i + 1}</td>
                                <td className="px-2 py-1.5">
                                  <Badge
                                    variant={(slot.type || "mcq") === "mcq" ? "secondary" : "outline"}
                                    className="text-[10px] px-1.5"
                                  >
                                    {(slot.type || "mcq").toUpperCase()}
                                  </Badge>
                                </td>
                                <td className="px-2 py-1.5">
                                  {bloomInfo ? (
                                    <span className={cn("font-medium", bloomInfo.color)}>
                                      {bloomInfo.short}
                                    </span>
                                  ) : (
                                    <span className="text-muted-foreground">—</span>
                                  )}
                                </td>
                                <td className="px-2 py-1.5 text-muted-foreground truncate max-w-[80px]">
                                  {slot.chapter || "—"}
                                </td>
                                <td className="px-2 py-1.5 text-muted-foreground">
                                  {slot.estimated_difficulty != null
                                    ? `${Math.round(slot.estimated_difficulty * 100)}%`
                                    : "—"}
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>

                    {/* Bloom distribution */}
                    {bloomDist && Object.keys(bloomDist).length > 0 && (
                      <div className="border-t border-amber-200/40 px-2 py-2 space-y-1">
                        <p className="text-[10px] font-semibold text-amber-800 uppercase tracking-wide">
                          Phân bố Bloom
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {BLOOM_ORDER.filter((b) => bloomDist[b]).map((b) => (
                            <span
                              key={b}
                              className={cn(
                                "text-[10px] px-1.5 py-0.5 rounded border font-medium",
                                BLOOM_CONFIG[b].bg,
                                BLOOM_CONFIG[b].color
                              )}
                            >
                              {BLOOM_CONFIG[b].short}: {bloomDist[b]}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              )}

              {hitlApproved ? (
                <div className="flex items-center gap-2 rounded-lg bg-emerald-100 border border-emerald-200 px-3 py-2 mt-3">
                  <Check className="h-4 w-4 text-emerald-600" />
                  <span className="text-sm font-medium text-emerald-800">Đã xác nhận sườn đề</span>
                </div>
              ) : (
                <div className="flex gap-2 mt-3">
                  <Button size="sm" className="flex-1 h-9 bg-emerald-600 hover:bg-emerald-700"
                    onClick={handleApprove} disabled={hitlApproving || hitlRejecting}>
                    {hitlApproving ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <ThumbsUp className="h-3.5 w-3.5" />}
                    Xác nhận sườn đề
                  </Button>
                  <Button size="sm" variant="outline"
                    className="flex-1 h-9 border-amber-300 text-amber-800 hover:bg-amber-100"
                    onClick={openRejectDialog} disabled={hitlApproving || hitlRejecting}>
                    {hitlRejecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <X className="h-3.5 w-3.5" />}
                    Từ chối
                  </Button>
                </div>
              )}
            </HITLCard>
          )}

          {/* ── HITL Checkpoint 2: Full Review ── */}
          {activeCheckpoint === 2 && (
            <HITLCard
              title="Xem xét đề hoàn chỉnh"
              subtitle="Checkpoint 2 — Kiểm tra đề trước khi hoàn tất"
              icon={<ShieldCheck className="h-4 w-4" />}
              colorClass="border-violet-200 bg-gradient-to-br from-violet-50 to-purple-50"
              iconBg="bg-violet-200 text-violet-800"
            >
              <div className="space-y-2">
                {validationIssues.length > 0 ? (
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-destructive">
                      {validationIssues.length} vấn đề được phát hiện:
                    </p>
                    {validationIssues.slice(0, 5).map((issue, i) => (
                      <div key={i} className="flex items-start gap-1.5 p-1.5 rounded bg-red-50 border border-red-100">
                        <AlertCircle className="h-3 w-3 text-red-500 shrink-0 mt-0.5" />
                        <div>
                          <p className="text-[10px] font-semibold text-red-700">
                            {issue.question_id}
                            {issue.issue_type && <span className="ml-1">— {issue.issue_type}</span>}
                          </p>
                          {issue.detail && <p className="text-[10px] text-red-600">{issue.detail}</p>}
                          {issue.suggestion && <p className="text-[10px] text-emerald-600">→ {issue.suggestion}</p>}
                        </div>
                      </div>
                    ))}
                    {validationIssues.length > 5 && (
                      <p className="text-[10px] text-muted-foreground text-center">
                        +{validationIssues.length - 5} vấn đề khác
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 p-2 rounded bg-emerald-50 border border-emerald-100">
                    <Check className="h-3.5 w-3.5 text-emerald-600" />
                    <span className="text-xs text-emerald-700 font-medium">Đề đạt yêu cầu kiểm tra</span>
                  </div>
                )}
                <p className="text-xs text-muted-foreground mt-2">
                  {questions.length} câu hỏi đã được tạo
                </p>
              </div>

              {hitlApproved ? (
                <div className="flex items-center gap-2 rounded-lg bg-emerald-100 border border-emerald-200 px-3 py-2 mt-3">
                  <Check className="h-4 w-4 text-emerald-600" />
                  <span className="text-sm font-medium text-emerald-800">Đã xác nhận</span>
                </div>
              ) : (
                <div className="flex gap-2 mt-3">
                  <Button size="sm" className="flex-1 h-9 bg-emerald-600 hover:bg-emerald-700"
                    onClick={handleApprove} disabled={hitlApproving || hitlRejecting}>
                    {hitlApproving ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <ThumbsUp className="h-3.5 w-3.5" />}
                    Xác nhận
                  </Button>
                  <Button size="sm" variant="outline"
                    className="flex-1 h-9 border-violet-300 text-violet-800 hover:bg-violet-100"
                    onClick={openRejectDialog} disabled={hitlApproving || hitlRejecting}>
                    {hitlRejecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <X className="h-3.5 w-3.5" />}
                    Yêu cầu sửa
                  </Button>
                </div>
              )}
            </HITLCard>
          )}

          {/* ── Completion card ── */}
          {completed && (
            <div className="rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-teal-50 p-4 space-y-4">
              <div className="flex items-center gap-2">
                <Check className="h-5 w-5 text-emerald-600" />
                <p className="text-sm font-semibold text-emerald-900">Hoàn tất!</p>
              </div>

              {/* Question counts */}
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Tổng câu hỏi</span>
                  <span className="font-semibold tabular-nums">{questions.length}</span>
                </div>
                {(examType === "mixed" || !examType) && (mcqCount > 0 || essayCount > 0) && (
                  <div className="flex gap-2 text-xs text-muted-foreground">
                    {mcqCount > 0 && <span>MCQ: {mcqCount}</span>}
                    {essayCount > 0 && <span>Essay: {essayCount}</span>}
                  </div>
                )}

                {/* Blueprint summary */}
                {completionBlueprint.length > 0 && (
                  <div className="mt-2">
                    <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
                      Sườn đề (Blueprint)
                    </p>
                    <div className="space-y-0.5 max-h-36 overflow-y-auto">
                      {completionBlueprint.map((slot, i) => {
                        const bloomLvl = slot.bloom_level as BloomLevel | undefined
                        const bloomInfo = bloomLvl && BLOOM_CONFIG[bloomLvl] ? BLOOM_CONFIG[bloomLvl] : null
                        return (
                          <div key={slot.question_id || i} className="flex items-center gap-1.5 text-[10px]">
                            <span className="w-4 text-right text-muted-foreground/60">{i + 1}.</span>
                            <Badge
                              variant={(slot.type || "mcq") === "mcq" ? "secondary" : "outline"}
                              className="text-[9px] px-1 py-0"
                            >
                              {(slot.type || "mcq").toUpperCase()}
                            </Badge>
                            {bloomInfo && (
                              <span className={cn("font-medium", bloomInfo.color)}>{bloomInfo.short}</span>
                            )}
                            <span className="text-muted-foreground truncate">{slot.chapter || slot.topic_hint || ""}</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Bloom distribution */}
                {bloomDist && Object.keys(bloomDist).length > 0 && (
                  <>
                    <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide pt-1">
                      Phân phối Bloom
                    </p>
                    {BLOOM_ORDER.filter((b) => bloomDist[b]).map((b) => (
                      <div key={b} className="flex items-center gap-2">
                        <span
                          className={cn(
                            "text-[10px] px-1.5 py-0.5 rounded border w-12 text-center shrink-0",
                            BLOOM_CONFIG[b].bg,
                            BLOOM_CONFIG[b].color
                          )}
                        >
                          {BLOOM_CONFIG[b].short}
                        </span>
                        <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full rounded-full bg-primary transition-all duration-500"
                            style={{ width: `${Math.round(((bloomDist[b] || 0) / questions.length) * 100)}%` }}
                          />
                        </div>
                        <span className="text-[10px] tabular-nums text-muted-foreground w-4 text-right">
                          {bloomDist[b]}
                        </span>
                      </div>
                    ))}
                  </>
                )}

                {/* Cost */}
                {costReport && costReport.total_cost_usd != null && (
                  <div className="flex justify-between text-xs pt-1">
                    <span className="text-muted-foreground">Chi phí</span>
                    <span className="font-medium">${costReport.total_cost_usd.toFixed(4)}</span>
                  </div>
                )}
              </div>

              <Button className="w-full h-10 bg-primary hover:bg-primary/90" onClick={handleViewExam}>
                Xem đề đầy đủ <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          )}

          {/* Connection error */}
          {connState === "error" && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-red-900">Lỗi kết nối</p>
                  <p className="text-xs text-red-700 mt-0.5">
                    Không thể kết nối WebSocket. Kiểm tra backend đang chạy.
                  </p>
                  <p className="text-xs text-muted-foreground mt-1 font-mono break-all">{resolvedWsUrl}</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Main content: unified stream feed ── */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto p-6 space-y-0">

            {/* Empty state while waiting for first event */}
            {feedItems.length === 0 && !completed && (
              <div className="flex flex-col items-center justify-center h-64 gap-3 text-muted-foreground">
                <div className="relative flex h-12 w-12 items-center justify-center">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary/20" />
                  <Brain className="h-6 w-6 text-primary relative z-10" />
                </div>
                <p className="text-sm">Đang kết nối đến pipeline AI...</p>
              </div>
            )}

            {/* Feed items */}
            {feedItems.map((item, idx) => {
              if (item.kind === 'reasoning') {
                const isLast = idx === feedItems.length - 1
                const hasChunks = item.chunks && item.chunks.length > 0
                const chunksText = hasChunks ? item.chunks.join('') : ''
                const isStreaming = isLast && isGenerating
                return (
                  <div key={item.id} className="flex gap-3 py-3 group animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <div className="flex flex-col items-center">
                      <div className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-bold shrink-0 transition-colors ${isStreaming ? 'bg-primary/10 border-primary/40 text-primary' : 'bg-muted border-border text-muted-foreground'}`}>
                        {isStreaming
                          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          : <Brain className="h-3.5 w-3.5" />}
                      </div>
                      {idx < feedItems.length - 1 && (
                        <div className="w-px flex-1 bg-border mt-1" style={{ minHeight: 16 }} />
                      )}
                    </div>
                    <div className="flex-1 pb-1 pt-0.5 min-w-0">
                      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">{item.stepLabel}</p>
                      {/* Step message */}
                      <p className={`text-sm leading-relaxed mb-1 ${isStreaming ? 'text-foreground' : 'text-muted-foreground'}`}>
                        {isStreaming ? <TypingText text={item.message} /> : item.message}
                      </p>
                      {/* Streaming chunks (detailed LLM reasoning) */}
                      {(hasChunks || isStreaming) && (
                        <div className="mt-2 rounded-lg bg-muted/40 border border-border/60 px-3 py-2 font-mono text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto">
                          {chunksText}
                          {isStreaming && (
                            <span className="inline-block w-0.5 h-3.5 bg-primary ml-0.5 animate-pulse align-text-bottom" />
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )
              }

              if (item.kind === 'blueprint') {
                return (
                  <div key={item.id} className="py-3 animate-in fade-in slide-in-from-bottom-3 duration-500">
                    <div className="flex items-center gap-2 mb-2 pl-1">
                      <div className="h-px flex-1 bg-border" />
                      <span className="text-xs text-muted-foreground font-medium px-2">Sườn đề (Blueprint)</span>
                      <div className="h-px flex-1 bg-border" />
                    </div>
                    <div className="rounded-xl border bg-card shadow-sm overflow-hidden">
                      <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Database className="h-4 w-4 text-primary" />
                          <span className="text-sm font-semibold">{item.slots.length} câu hỏi đã lên kế hoạch</span>
                        </div>
                        <div className="flex gap-1.5 flex-wrap">
                          {(BLOOM_ORDER.filter(b => item.bloomDist[b])).map((b) => (
                            <span key={b} className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${BLOOM_CONFIG[b]?.bg} ${BLOOM_CONFIG[b]?.color}`}>
                              {BLOOM_CONFIG[b]?.short} {item.bloomDist[b]}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="divide-y max-h-80 overflow-y-auto">
                        {item.slots.map((slot, i) => {
                          const bl = slot.bloom_level as BloomLevel | undefined
                          const bc = bl && BLOOM_CONFIG[bl] ? BLOOM_CONFIG[bl] : null
                          const topicHint = (slot.topic_hint as string) || ''
                          const chapter = (slot.chapter as string) || ''
                          return (
                            <div key={slot.question_id || i} className="flex items-start gap-3 px-4 py-2.5 hover:bg-muted/20 transition-colors">
                              <span className="w-5 text-xs text-muted-foreground/50 text-right shrink-0 pt-0.5">{i + 1}</span>
                              <div className="flex items-center gap-1.5 shrink-0 pt-0.5">
                                <Badge variant={(slot.type || 'mcq') === 'mcq' ? 'secondary' : 'outline'} className="text-[10px] px-1.5">
                                  {(slot.type || 'mcq').toUpperCase()}
                                </Badge>
                                {bc && <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${bc.bg} ${bc.color}`}>{bc.short}</span>}
                              </div>
                              <div className="flex-1 min-w-0">
                                {chapter && (
                                  <p className="text-xs text-muted-foreground/70 mb-0.5">
                                    <LatexRenderer className="text-xs">{chapter}</LatexRenderer>
                                  </p>
                                )}
                                {topicHint && (
                                  <LatexRenderer className="text-sm text-foreground">{topicHint}</LatexRenderer>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                )
              }

              if (item.kind === 'question') {
                return (
                  <div key={item.id} className="py-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <QuestionCard question={item.question} index={item.index} />
                  </div>
                )
              }

              if (item.kind === 'validation') {
                return (
                  <div key={item.id} className="py-3 animate-in fade-in duration-300">
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


            {/* Blinking cursor at the end while generating */}
            {isGenerating && feedItems.length > 0 && feedItems[feedItems.length - 1]?.kind !== 'question' && (
              <div className="flex gap-3 py-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 border border-primary/30 shrink-0">
                  <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />
                </div>
                <div className="flex items-center gap-1.5 pt-1.5">
                  <span className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            )}

            {/* Completion banner */}
            {completed && (
              <div className="py-4 animate-in fade-in zoom-in-95 duration-500">
                <div className="rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-teal-50 p-5 text-center space-y-3">
                  <div className="flex justify-center">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                      <PartyPopper className="h-6 w-6" />
                    </div>
                  </div>
                  <div>
                    <p className="font-semibold text-emerald-900">Đề thi đã hoàn tất!</p>
                    <p className="text-sm text-emerald-700 mt-0.5">{questions.length} câu hỏi · {questions.filter(q => (q.type || 'mcq') === 'mcq').length} MCQ · {questions.filter(q => q.type === 'essay').length} Essay</p>
                  </div>
                  <Button className="bg-emerald-600 hover:bg-emerald-700" onClick={handleViewExam}>
                    Xem đề đầy đủ <ChevronRight className="h-4 w-4 ml-1" />
                  </Button>
                </div>
              </div>
            )}

            <div ref={feedEndRef} />
          </div>
        </div>

      </div>{/* ── end flex flex-1 overflow-hidden ── */}

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
            <Button
              variant="outline"
              onClick={() => setRejectDialogOpen(false)}
              disabled={hitlRejecting}
            >
              Hủy
            </Button>
            <Button
              variant="destructive"
              onClick={submitReject}
              disabled={hitlRejecting}
            >
              {hitlRejecting ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Đang gửi...
                </>
              ) : (
                <>
                  <X className="h-3.5 w-3.5" />
                  Gửi phản hồi
                </>
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

// ─── HITLCard sub-component ───────────────────────────────────────────────────

function HITLCard({
  title,
  subtitle,
  icon,
  colorClass,
  iconBg,
  children,
  infoTooltip,
}: {
  title: string
  subtitle: string
  icon: React.ReactNode
  colorClass: string
  iconBg: string
  children: React.ReactNode
  infoTooltip?: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(true)

  return (
    <div className={cn("rounded-xl border p-4 space-y-3", colorClass)}>
      <div className="flex items-start gap-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <div className={cn("flex h-7 w-7 items-center justify-center rounded-lg shrink-0", iconBg)}>
            {icon}
          </div>
          <div className="text-left min-w-0">
            <div className="flex items-center gap-1.5">
              <p className="text-sm font-semibold text-foreground">{title}</p>
              {infoTooltip && (
                <div className="relative group shrink-0">
                  <button
                    className="flex items-center justify-center h-4 w-4 rounded-full bg-blue-200 text-blue-700 hover:bg-blue-300 transition-colors cursor-help"
                    title="Xem giải thích"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Info className="h-2.5 w-2.5" />
                  </button>
                  <div className="absolute left-full top-0 ml-2 z-50 hidden group-hover:block">
                    <div className="bg-background border rounded-lg shadow-lg p-3 w-64 text-xs space-y-1.5">
                      {infoTooltip}
                    </div>
                  </div>
                </div>
              )}
            </div>
            <p className="text-[10px] text-muted-foreground">{subtitle}</p>
          </div>
        </div>
        <button
          className="shrink-0 p-0.5 hover:bg-black/5 rounded transition-colors"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
        </button>
      </div>
      {expanded && children}
    </div>
  )
}

// ─── BlueprintPreviewCard sub-component ───────────────────────────────────────

function BlueprintPreviewCard({
  slots,
  bloomDist,
}: {
  slots: BlueprintSlot[]
  bloomDist: BloomDistribution | null
}) {
  return (
    <div className="rounded-2xl border border-dashed border-amber-200 bg-amber-50/30 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Database className="h-4 w-4 text-amber-600" />
        <h3 className="text-sm font-semibold text-amber-900">Ma trận sườn đề</h3>
        <Badge variant="secondary" className="text-xs ml-auto">{slots.length} câu</Badge>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-amber-200/40">
              <th className="px-2 py-1.5 text-left font-semibold text-amber-800">#</th>
              <th className="px-2 py-1.5 text-left font-semibold text-amber-800">Loại</th>
              <th className="px-2 py-1.5 text-left font-semibold text-amber-800">Bloom</th>
              <th className="px-2 py-1.5 text-left font-semibold text-amber-800">Chương</th>
              <th className="px-2 py-1.5 text-left font-semibold text-amber-800">Chủ đề</th>
            </tr>
          </thead>
          <tbody>
            {slots.map((slot, i) => {
              const bloomLvl = slot.bloom_level as BloomLevel | undefined
              const bloomInfo = bloomLvl && BLOOM_CONFIG[bloomLvl] ? BLOOM_CONFIG[bloomLvl] : null
              return (
                <tr key={slot.question_id || i} className="border-b border-amber-100/30 last:border-0">
                  <td className="px-2 py-1.5 text-muted-foreground">{i + 1}</td>
                  <td className="px-2 py-1.5">
                    <Badge variant={(slot.type || "mcq") === "mcq" ? "secondary" : "outline"} className="text-[10px] px-1.5">
                      {(slot.type || "mcq").toUpperCase()}
                    </Badge>
                  </td>
                  <td className="px-2 py-1.5">
                    {bloomInfo ? (
                      <span className={cn("font-medium text-[10px]", bloomInfo.color)}>{bloomInfo.label}</span>
                    ) : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-muted-foreground truncate max-w-[80px]">{slot.chapter || "—"}</td>
                  <td className="px-2 py-1.5 text-muted-foreground truncate max-w-[100px]">
                    {slot.topic_hint || slot.content_type || "—"}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {bloomDist && Object.keys(bloomDist).length > 0 && (
        <div className="flex flex-wrap gap-1">
          {BLOOM_ORDER.filter((b) => bloomDist[b]).map((b) => (
            <span
              key={b}
              className={cn(
                "text-[10px] px-1.5 py-0.5 rounded border font-medium",
                BLOOM_CONFIG[b].bg,
                BLOOM_CONFIG[b].color
              )}
            >
              {BLOOM_CONFIG[b].short}: {bloomDist[b]}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── TypingText sub-component ──────────────────────────────────────────────────

function TypingText({ text }: { text: string }) {
  const [displayed, setDisplayed] = useState("")
  const ref = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setDisplayed("")
    if (!text) return
    let i = 0
    const type = () => {
      if (i < text.length) {
        setDisplayed((prev) => prev + text[i])
        i++
        ref.current = setTimeout(type, 20 + Math.random() * 15)
      }
    }
    ref.current = setTimeout(type, 200)
    return () => { if (ref.current) clearTimeout(ref.current) }
  }, [text])

  return (
    <>
      {displayed}
      <span className="inline-block h-3 w-0.5 bg-primary animate-pulse ml-0.5 align-middle" />
    </>
  )
}

// ─── QuestionCard sub-component ───────────────────────────────────────────────

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
          {/* Type badge */}
          <Badge
            variant={qType === "mcq" ? "secondary" : "outline"}
            className={cn(
              "text-[10px]",
              qType === "mcq" && "bg-blue-100 text-blue-700 border-blue-200",
              qType === "essay" && "bg-violet-100 text-violet-700 border-violet-200"
            )}
          >
            {qType === "mcq" ? "MCQ" : qType === "essay" ? "Essay" : qType.toUpperCase()}
          </Badge>
          {/* Bloom badge */}
          {bloomInfo && (
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full border font-medium",
                bloomInfo.bg,
                bloomInfo.color
              )}
            >
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

      {/* Stem */}
      {stem && (
        <p className="text-sm text-foreground leading-relaxed mb-3">{stem}</p>
      )}

      {/* Options for MCQ */}
      {qType === "mcq" && options.length > 0 && (
        <div className="space-y-1.5">
          {options.map((opt, oi) => (
            <div
              key={opt.label || oi}
              className="flex items-start gap-2 rounded-lg border bg-muted/30 px-3 py-2"
            >
              <span className="text-xs font-semibold text-muted-foreground w-5 shrink-0 mt-0.5">
                {String.fromCharCode(65 + oi)}.
              </span>
              <span className="text-sm text-foreground">{opt.text}</span>
            </div>
          ))}
        </div>
      )}

      {/* Rubric for Essay */}
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

// ─── QuestionCardSkeleton sub-component ──────────────────────────────────────

function QuestionCardSkeleton({ isLoading }: { isLoading: boolean }) {
  return (
    <div className="rounded-xl border border-dashed border-primary/30 bg-primary/[0.02] p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Skeleton className="h-6 w-6 rounded-full" />
        <Skeleton className="h-4 w-20 rounded-full" />
      </div>
      {isLoading ? (
        <>
          <Skeleton className="h-4 w-full rounded" />
          <Skeleton className="h-4 w-5/6 rounded" />
          <Skeleton className="h-4 w-4/6 rounded" />
        </>
      ) : (
        <div className="space-y-1.5">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-8 w-full rounded-lg" />
          ))}
        </div>
      )}
      <div className="flex items-center gap-1.5 pt-1">
        <Loader2 className="h-3 w-3 animate-spin text-primary" />
        <span className="text-xs text-muted-foreground">Đang sinh câu tiếp theo...</span>
      </div>
    </div>
  )
}
