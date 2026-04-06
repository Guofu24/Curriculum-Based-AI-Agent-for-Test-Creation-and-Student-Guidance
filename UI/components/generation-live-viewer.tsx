"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import {
  Brain,
  Check,
  ChevronRight,
  ChevronDown,
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
} from "lucide-react"
import { cn } from "@/lib/utils"
import { generation as generationApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"

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
    id?: string
    stem?: string
    content?: string
    options?: Array<{ id: string; text: string }>
    bloom_level?: BloomLevel
    difficulty_score?: number
    [key: string]: unknown
  }
}

interface HitlCheckpointEvent {
  type: "hitl_checkpoint"
  checkpoint_id: number
  data: {
    blueprint?: BlueprintData
    suggestions?: string[]
    status?: string
    title?: string
    [key: string]: unknown
  }
}

interface CompletedEvent {
  type: "completed"
  exam_id: string
  total_questions?: number
  distribution?: BloomDistribution
}

type WsMessage =
  | PlanStepEvent
  | QuestionGeneratedEvent
  | HitlCheckpointEvent
  | CompletedEvent
  | { type: string; [key: string]: unknown }

type BloomLevel =
  | "remember"
  | "understand"
  | "apply"
  | "analyze"
  | "evaluate"
  | "create"

interface BloomDistribution {
  remember?: number
  understand?: number
  apply?: number
  analyze?: number
  evaluate?: number
  create?: number
}

interface BlueprintData {
  title?: string
  subject?: string
  grade?: string
  chapter?: string
  question_count?: number
  distribution?: BloomDistribution
  [key: string]: unknown
}

interface PlanStep {
  step: number
  message: string
  completed: boolean
  active: boolean
}

// ─── Pipeline steps config ────────────────────────────────────────────────────

const PIPELINE_STEPS = [
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
  remember: {
    label: "Nhận biết",
    color: "text-sky-700",
    bg: "bg-sky-100 border-sky-200",
    short: "NB",
  },
  understand: {
    label: "Thông hiểu",
    color: "text-emerald-700",
    bg: "bg-emerald-100 border-emerald-200",
    short: "TH",
  },
  apply: {
    label: "Vận dụng",
    color: "text-amber-700",
    bg: "bg-amber-100 border-amber-200",
    short: "VD",
  },
  analyze: {
    label: "Phân tích",
    color: "text-orange-700",
    bg: "bg-orange-100 border-orange-200",
    short: "PT",
  },
  evaluate: {
    label: "Đánh giá",
    color: "text-pink-700",
    bg: "bg-pink-100 border-pink-200",
    short: "ĐG",
  },
  create: {
    label: "Sáng tạo",
    color: "text-violet-700",
    bg: "bg-violet-100 border-violet-200",
    short: "ST",
  },
}

const BLOOM_ORDER: BloomLevel[] = [
  "remember",
  "understand",
  "apply",
  "analyze",
  "evaluate",
  "create",
]

// ─── Props ─────────────────────────────────────────────────────────────────────

export interface GenerationLiveViewerProps {
  examId: string
  wsUrl: string
  onApprove: (examId: string, approved: boolean) => Promise<void>
  onComplete: (examId: string) => void
}

// ─── Main component ───────────────────────────────────────────────────────────

export function GenerationLiveViewer({
  examId,
  wsUrl,
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

  // HITL state
  const [hitlCheckpoint, setHitlCheckpoint] = useState<HitlCheckpointEvent | null>(null)
  const [hitlApproved, setHitlApproved] = useState(false)
  const [hitlApproving, setHitlApproving] = useState(false)
  const [hitlRejecting, setHitlRejecting] = useState(false)
  const [blueprint, setBlueprint] = useState<BlueprintData | null>(null)

  // Question stream
  const [questions, setQuestions] = useState<QuestionGeneratedEvent["question"][]>([])
  const [nextQuestionLoading, setNextQuestionLoading] = useState(false)
  const questionsCountRef = useRef(0)

  // Completion
  const [completed, setCompleted] = useState(false)
  const [showCelebration, setShowCelebration] = useState(false)
  const [bloomDist, setBloomDist] = useState<BloomDistribution | null>(null)

  // Connection
  const wsRef = useRef<WebSocket | null>(null)
  const unmountedRef = useRef(false)

  // ─── Derived ────────────────────────────────────────────────────────────────

  const completedCount = steps.filter((s) => s.completed).length
  const progressPct = Math.round((completedCount / PIPELINE_STEPS.length) * 100)
  const currentStep = steps.find((s) => s.active)
  const isGenerating = connState === "connected" && !completed

  // Count questions per bloom level
  const bloomCounts = questions.reduce<Record<string, number>>((acc, q) => {
    const level = q.bloom_level || "understand"
    acc[level] = (acc[level] || 0) + 1
    return acc
  }, {})

  // ─── WebSocket URL resolver ──────────────────────────────────────────────────

  const resolvedWsUrl = (() => {
    if (wsUrl.startsWith("ws://") || wsUrl.startsWith("wss://")) return wsUrl
    if (wsUrl.startsWith("/")) {
      const proto = window.location.protocol === "https:" ? "wss" : "ws"
      return `${proto}://${window.location.host}${wsUrl}`
    }
    const proto = window.location.protocol === "https:" ? "wss" : "ws"
    const port = window.location.port === "3000" ? "8000" : window.location.port
    return `${proto}://${window.location.hostname}:${port}${wsUrl}`
  })()

  // ─── Event handler ───────────────────────────────────────────────────────────

  const handleMessage = useCallback(
    (raw: string) => {
      let msg: WsMessage
      try {
        msg = JSON.parse(raw)
      } catch {
        return
      }

      switch (msg.type) {
        case "plan_step": {
          const e = msg as PlanStepEvent
          setSteps((prev) =>
            prev.map((s) => {
              if (s.step < e.step) return { ...s, completed: true, active: false }
              if (s.step === e.step) return { ...s, message: e.message, active: true, completed: false }
              return { ...s, active: false }
            })
          )
          // Auto-expand reasoning panel while generating
          if (!reasoningOpen) setReasoningOpen(true)
          break
        }

        case "question_generated": {
          const e = msg as QuestionGeneratedEvent
          setQuestions((prev) => [...prev, e.question])
          questionsCountRef.current += 1
          // Show skeleton only after first question appears
          setNextQuestionLoading(false)
          break
        }

        case "hitl_checkpoint": {
          const e = msg as HitlCheckpointEvent
          if (e.checkpoint_id === 1) {
            setHitlCheckpoint(e)
            setHitlApproved(false)
            setBlueprint((e.data as { blueprint?: BlueprintData }).blueprint || null)
          }
          break
        }

        case "completed": {
          const e = msg as CompletedEvent
          setSteps((prev) =>
            prev.map((s) => ({ ...s, completed: true, active: false }))
          )
          setBloomDist(e.distribution || null)
          setCompleted(true)
          setShowCelebration(true)
          // Collapse reasoning panel on completion
          setReasoningOpen(false)
          // Auto-collapse HITL panel if still showing
          if (hitlCheckpoint && !hitlApproved) setHitlCheckpoint(null)
          setTimeout(() => setShowCelebration(false), 3000)
          wsRef.current?.close()
          if (!unmountedRef.current) {
            setTimeout(() => onComplete(e.exam_id), 500)
          }
          break
        }

        default:
          break
      }
    },
    [reasoningOpen, onComplete, hitlCheckpoint, hitlApproved]
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
  }, [resolvedWsUrl, handleMessage]) // eslint-disable-line react-hooks/exhaustive-deps

  // ─── HITL approval ──────────────────────────────────────────────────────────

  const handleApprove = async () => {
    setHitlApproving(true)
    try {
      await onApprove(examId, true)
      setHitlApproved(true)
    } finally {
      setHitlApproving(false)
    }
  }

  const handleReject = async () => {
    setHitlRejecting(true)
    try {
      await onApprove(examId, false)
      setHitlCheckpoint(null)
    } finally {
      setHitlRejecting(false)
    }
  }

  // ─── Navigate to exam ────────────────────────────────────────────────────────

  const handleViewExam = () => {
    router.push(`/dashboard/exams/${examId}`)
  }

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
              {completed ? "Đề thi đã sẵn sàng" : "Đang sinh đề thi"}
            </h1>
            <p className="text-xs text-muted-foreground font-mono">
              exam · {examId.slice(0, 8)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Question count */}
          {questions.length > 0 && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-secondary/60 text-sm">
              <span className="text-muted-foreground">Câu:</span>
              <span className="font-semibold tabular-nums">{questions.length}</span>
            </div>
          )}

          {/* Connection indicator */}
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
              {connState === "connected"
                ? "Live"
                : connState === "connecting"
                  ? "Kết nối..."
                  : connState === "error"
                    ? "Lỗi"
                    : "Chờ"}
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

          {/* ── HITL Checkpoint Panel ── */}
          {hitlCheckpoint && (
            <div className="rounded-xl border border-amber-200 bg-gradient-to-br from-amber-50 to-orange-50 p-4 space-y-3">
              <div className="flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-200 text-amber-800">
                  <Eye className="h-3.5 w-3.5" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-amber-900">Xem xét sườn đề</p>
                  <p className="text-xs text-amber-700">Checkpoint 1</p>
                </div>
              </div>

              {blueprint && (
                <div className="rounded-lg border border-amber-200/60 bg-white/70 p-3 space-y-2">
                  {blueprint.title && (
                    <p className="text-sm font-medium text-foreground">{blueprint.title}</p>
                  )}
                  {blueprint.question_count && (
                    <p className="text-xs text-muted-foreground">
                      {blueprint.question_count} câu hỏi
                    </p>
                  )}
                  {blueprint.distribution && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {BLOOM_ORDER.filter((b) => blueprint.distribution?.[b]).map((b) => (
                        <span
                          key={b}
                          className={cn(
                            "text-xs px-1.5 py-0.5 rounded border",
                            BLOOM_CONFIG[b].bg,
                            BLOOM_CONFIG[b].color
                          )}
                        >
                          {BLOOM_CONFIG[b].short}: {blueprint.distribution[b]}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {hitlApproved ? (
                <div className="flex items-center gap-2 rounded-lg bg-emerald-100 border border-emerald-200 px-3 py-2">
                  <Check className="h-4 w-4 text-emerald-600" />
                  <span className="text-sm font-medium text-emerald-800">Đã xác nhận</span>
                </div>
              ) : (
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    className="flex-1 h-9 bg-emerald-600 hover:bg-emerald-700"
                    onClick={handleApprove}
                    disabled={hitlApproving || hitlRejecting}
                  >
                    {hitlApproving ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <ThumbsUp className="h-3.5 w-3.5" />
                    )}
                    Xác nhận
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1 h-9 border-amber-300 text-amber-800 hover:bg-amber-100"
                    onClick={handleReject}
                    disabled={hitlApproving || hitlRejecting}
                  >
                    {hitlRejecting ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <X className="h-3.5 w-3.5" />
                    )}
                    Từ chối
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* ── Completion card ── */}
          {completed && (
            <div className="rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-teal-50 p-4 space-y-4">
              <div className="flex items-center gap-2">
                <Check className="h-5 w-5 text-emerald-600" />
                <p className="text-sm font-semibold text-emerald-900">Hoàn tất!</p>
              </div>

              {/* Summary */}
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Tổng câu hỏi</span>
                  <span className="font-semibold tabular-nums">{questions.length}</span>
                </div>
                {bloomDist && (
                  <>
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide pt-1">
                      Phân phối Bloom
                    </p>
                    {BLOOM_ORDER.filter((b) => bloomDist[b]).map((b) => (
                      <div key={b} className="flex items-center gap-2">
                        <span
                          className={cn(
                            "text-xs px-1.5 py-0.5 rounded border w-16 text-center shrink-0",
                            BLOOM_CONFIG[b].bg,
                            BLOOM_CONFIG[b].color
                          )}
                        >
                          {BLOOM_CONFIG[b].short}
                        </span>
                        <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full rounded-full bg-primary transition-all duration-500"
                            style={{
                              width: `${Math.round(
                                ((bloomDist[b] || 0) / questions.length) * 100
                              )}%`,
                            }}
                          />
                        </div>
                        <span className="text-xs tabular-nums text-muted-foreground w-5 text-right">
                          {bloomDist[b]}
                        </span>
                      </div>
                    ))}
                  </>
                )}
              </div>

              <Button
                className="w-full h-10 bg-primary hover:bg-primary/90"
                onClick={handleViewExam}
              >
                Xem đề đầy đủ
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          )}

          {/* Connection debug */}
          {connState === "error" && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-red-900">Lỗi kết nối</p>
                  <p className="text-xs text-red-700 mt-0.5">
                    Không thể kết nối WebSocket. Kiểm tra backend đang chạy.
                  </p>
                  <p className="text-xs text-muted-foreground mt-1 font-mono break-all">
                    {resolvedWsUrl}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Main content ── */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto p-6 space-y-4">

            {/* ── Reasoning stream panel ── */}
            <div className="rounded-2xl border bg-card shadow-sm overflow-hidden">
              {/* Panel header */}
              <button
                onClick={() => setReasoningOpen((v) => !v)}
                className="w-full flex items-center justify-between px-5 py-4 hover:bg-muted/30 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "flex h-8 w-8 items-center justify-center rounded-lg transition-all",
                      isGenerating
                        ? "bg-primary text-primary-foreground animate-pulse"
                        : completed
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-muted text-muted-foreground"
                    )}
                  >
                    {isGenerating ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : completed ? (
                      <Check className="h-4 w-4" />
                    ) : (
                      <Brain className="h-4 w-4" />
                    )}
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-semibold text-foreground">
                      {isGenerating
                        ? "Đang suy nghĩ..."
                        : completed
                          ? "Đã hoàn thành"
                          : "Suy nghĩ của Agent"}
                    </p>
                    {currentStep && (
                      <p className="text-xs text-muted-foreground">
                        {currentStep.message || "Đang xử lý..."}
                      </p>
                    )}
                  </div>
                </div>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform duration-200",
                    reasoningOpen && "rotate-180"
                  )}
                />
              </button>

              {/* Reasoning content */}
              {reasoningOpen && (
                <div className="border-t">
                  {/* Step timeline */}
                  <div className="px-5 py-4 space-y-3">
                    {steps.map((s) => {
                      const stepConfig = PIPELINE_STEPS.find((x) => x.id === s.step)
                      const isCompleted = s.completed
                      const isActive = s.active
                      const StepIcon = stepConfig?.icon || Loader

                      return (
                        <div key={s.step} className="flex items-start gap-3">
                          <div
                            className={cn(
                              "flex h-6 w-6 items-center justify-center rounded-full border-2 text-xs font-bold shrink-0 mt-0.5 transition-all duration-300",
                              isCompleted && "border-primary bg-primary text-primary-foreground",
                              isActive && "border-primary bg-primary/10 text-primary",
                              !isCompleted && !isActive && "border-muted-foreground/30 bg-muted text-muted-foreground"
                            )}
                          >
                            {isCompleted ? (
                              <Check className="h-3 w-3" />
                            ) : isActive ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              s.step
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <StepIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                              <span
                                className={cn(
                                  "text-sm font-medium",
                                  isCompleted && "text-foreground",
                                  isActive && "text-primary",
                                  !isCompleted && !isActive && "text-muted-foreground"
                                )}
                              >
                                {stepConfig?.label || `Bước ${s.step}`}
                              </span>
                              {isActive && (
                                <span className="inline-flex h-1.5 w-1.5 rounded-full bg-primary animate-ping" />
                              )}
                            </div>

                            {/* Typing animation for active step */}
                            {isActive && s.message && (
                              <div className="mt-1">
                                <span className="text-xs text-muted-foreground">
                                  <TypingText text={s.message} />
                                </span>
                              </div>
                            )}

                            {/* Completed message */}
                            {isCompleted && s.message && (
                              <p className="text-xs text-muted-foreground/70 mt-0.5">{s.message}</p>
                            )}
                          </div>
                        </div>
                      )
                    })}

                    {/* Progress bar */}
                    <div className="pt-2">
                      <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
                        <div
                          className={cn(
                            "h-full rounded-full bg-primary transition-all duration-500 ease-out",
                            isGenerating && "animate-pulse"
                          )}
                          style={{ width: `${progressPct}%` }}
                        />
                      </div>
                      <p className="text-xs text-muted-foreground mt-1 text-right tabular-nums">
                        {completedCount}/{PIPELINE_STEPS.length} bước hoàn tất
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* ── Question stream ── */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold text-foreground">
                  Câu hỏi đang sinh
                </h2>
                {questions.length > 0 && (
                  <Badge variant="secondary" className="text-xs tabular-nums">
                    {questions.length} câu
                  </Badge>
                )}
              </div>

              {/* Question cards */}
              <div className="space-y-3">
                {questions.map((q, idx) => (
                  <QuestionCard key={q.id || idx} question={q} index={idx} />
                ))}

                {/* Skeleton for next question */}
                {isGenerating && (
                  <QuestionCardSkeleton isLoading={questions.length === 0} />
                )}
              </div>

              {/* Empty state */}
              {!isGenerating && questions.length === 0 && !completed && (
                <div className="rounded-xl border border-dashed border-muted p-8 text-center">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">
                    Đang chờ câu hỏi đầu tiên...
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

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

// ─── TypingText sub-component ──────────────────────────────────────────────────

function TypingText({ text }: { text: string }) {
  const [displayed, setDisplayed] = useState("")
  const ref = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setDisplayed("")
    let i = 0
    const type = () => {
      if (i < text.length) {
        setDisplayed((prev) => prev + text[i])
        i++
        ref.current = setTimeout(type, 20 + Math.random() * 15)
      }
    }
    ref.current = setTimeout(type, 200)
    return () => {
      if (ref.current) clearTimeout(ref.current)
    }
  }, [text])

  return <>{displayed}<span className="inline-block h-3 w-0.5 bg-primary animate-pulse ml-0.5 align-middle" /></>
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
  const stem = question.stem || question.content || ""
  const options = question.options || []

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
          {question.difficulty_score != null && (
            <span className="text-xs text-muted-foreground">
              {Math.round(question.difficulty_score * 100)}% độ khó
            </span>
          )}
        </div>
      </div>

      {/* Stem */}
      {stem && (
        <p className="text-sm text-foreground leading-relaxed mb-3">{stem}</p>
      )}

      {/* Options */}
      {options.length > 0 && (
        <div className="space-y-1.5">
          {options.map((opt, oi) => (
            <div
              key={opt.id || oi}
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

      {/* No content yet */}
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
