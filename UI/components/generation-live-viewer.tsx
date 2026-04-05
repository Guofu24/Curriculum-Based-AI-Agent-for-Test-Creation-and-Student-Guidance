"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  BookOpen, Database, Sparkles, ShieldCheck, FileCheck,
  Check, Loader2, AlertCircle, ChevronRight, Wifi, WifiOff,
  Terminal, Eye, EyeOff, RefreshCw, X, ThumbsUp
} from "lucide-react"
import { cn } from "@/lib/utils"
import { generation as generationApi } from "@/lib/api"

// ─── Event types from backend SSEvent ─────────────────────────────────────────

interface PlanStepEvent {
  type: "plan_step"
  step: number
  total_steps: number
  message: string
}

interface QuestionGeneratedEvent {
  type: "question_generated"
  question_id: string
  question: Record<string, unknown>
}

interface ValidationResultEvent {
  type: "validation_result"
  passed: boolean
  issues_count: number
  issues: unknown[]
}

interface CompletedEvent {
  type: "completed"
  exam_id: string
  status: string
}

interface HitlCheckpointEvent {
  type: "hitl_checkpoint"
  checkpoint_id: number
  data: Record<string, unknown>
}

interface PipelinePausedEvent {
  type: "pipeline_paused"
  checkpoint_id: number
  message: string
}

interface ErrorEvent {
  type: "error"
  message: string
  agent?: string
}

type BackendEvent =
  | PlanStepEvent
  | QuestionGeneratedEvent
  | ValidationResultEvent
  | CompletedEvent
  | HitlCheckpointEvent
  | PipelinePausedEvent
  | ErrorEvent
  | { type: string; [key: string]: unknown }

// ─── Pipeline steps ────────────────────────────────────────────────────────────

const PIPELINE_STEPS = [
  { id: 1, label: "Truy xuất kiến thức", icon: BookOpen },
  { id: 2, label: "Tạo sườn đề (Blueprint)", icon: Database },
  { id: 3, label: "Sinh câu hỏi", icon: Sparkles },
  { id: 4, label: "Kiểm tra & sửa lỗi", icon: ShieldCheck },
  { id: 5, label: "Hoàn tất", icon: FileCheck },
]

function buildStepLabel(step: number): string {
  return PIPELINE_STEPS.find((s) => s.id === step)?.label ?? `Bước ${step}`
}

// ─── Live log entry ────────────────────────────────────────────────────────────

type LogVariant = "info" | "success" | "warning" | "error" | "debug"

interface LogEntry {
  id: number
  ts: Date
  type: string
  label: string
  detail: string
  variant: LogVariant
  raw?: string
}

// ─── Connection state ──────────────────────────────────────────────────────────

type ConnState = "idle" | "connecting" | "connected" | "error" | "closed"

// ─── Main component ────────────────────────────────────────────────────────────

export function GenerationLiveViewer({
  examId,
  websocketUrl,
  onComplete,
  onError,
}: {
  examId: string
  websocketUrl: string | null
  onComplete?: (examId: string) => void
  onError?: (message: string) => void
}) {
  const [connState, setConnState] = useState<ConnState>("idle")
  const [connError, setConnError] = useState<string>("")
  const [steps, setSteps] = useState<Record<number, "pending" | "running" | "completed" | "failed">>(
    Object.fromEntries(PIPELINE_STEPS.map((s) => [s.id, "pending"]))
  )
  const [stepMessages, setStepMessages] = useState<Record<number, string>>({})
  const [questionCount, setQuestionCount] = useState(0)
  const [validationPassed, setValidationPassed] = useState<boolean | null>(null)
  const [validationIssues, setValidationIssues] = useState(0)
  const [hitlStage, setHitlStage] = useState<string | null>(null)
  const [pendingBlueprint, setPendingBlueprint] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [showRaw, setShowRaw] = useState(true) // default ON so user can see what's coming
  const logRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const eventIdRef = useRef(0)
  const unmountedRef = useRef(false)

  // ── Build WebSocket URL ────────────────────────────────────────────────────

  // Try in order: full URL from backend → relative path → fallback to local backend
  const resolvedWsUrl = (() => {
    // 1. Full URL (ws:// or wss://) from backend
    if (websocketUrl && (websocketUrl.startsWith("ws://") || websocketUrl.startsWith("wss://"))) {
      return websocketUrl
    }
    // 2. Relative path — prepend frontend origin
    if (websocketUrl && websocketUrl.startsWith("/")) {
      const proto = window.location.protocol === "https:" ? "wss" : "ws"
      return `${proto}://${window.location.host}${websocketUrl}`
    }
    // 3. Fallback: construct from local backend
    const proto = window.location.protocol === "https:" ? "wss" : "ws"
    const wsPort = window.location.port === "3000" ? "8000" : window.location.port
    return `${proto}://${window.location.hostname}:${wsPort}/ws/exam/${examId}`
  })()

  // ── Push a log entry ──────────────────────────────────────────────────────

  const pushLog = useCallback(
    (
      type: string,
      label: string,
      detail: string,
      variant: LogVariant = "info",
      raw?: string
    ) => {
      if (unmountedRef.current) return
      const id = ++eventIdRef.current
      setLogs((prev) => [...prev.slice(-199), { id, ts: new Date(), type, label, detail, variant, raw }])
    },
    []
  )

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  // ── WebSocket event handler ─────────────────────────────────────────────────

  const handleWsMessage = useCallback(
    (rawData: string) => {
      // Always show raw in debug log
      pushLog("raw", "RAW", rawData.slice(0, 200), "debug", rawData)

      let data: BackendEvent
      try {
        data = JSON.parse(rawData)
      } catch {
        pushLog("parse_err", "PARSE ERROR", rawData.slice(0, 120), "error")
        return
      }

      const eventType = data.type

      switch (eventType) {
        case "plan_step": {
          const e = data as PlanStepEvent
          const label = buildStepLabel(e.step)
          const detail = e.message || ""

          setSteps((prev) => {
            const next = { ...prev }
            // Mark all steps before this one as completed if they were running
            PIPELINE_STEPS.forEach((s) => {
              if (s.id < e.step && prev[s.id] === "running") {
                next[s.id] = "completed"
              }
            })
            next[e.step] = "running"
            return next
          })

          if (detail) {
            setStepMessages((prev) => ({ ...prev, [e.step]: detail }))
          }

          pushLog("plan_step", label, detail, "info")
          break
        }

        case "question_generated": {
          const e = data as QuestionGeneratedEvent
          setQuestionCount((c) => {
            const next = c + 1
            if (next === 1) pushLog("question", "Câu hỏi đầu tiên", e.question_id, "success")
            else if (next === 5) pushLog("question", "5 câu hỏi", "Đang sinh...", "info")
            else if (next % 10 === 0) pushLog("question", `${next} câu hỏi`, "Đang sinh...", "info")
            return next
          })
          break
        }

        case "hitl_checkpoint": {
          const e = data as HitlCheckpointEvent
          const labels: Record<number, string> = {
            0: "Xác nhận yêu cầu",
            1: "Xem xét sườn đề",
            2: "Xem trước đề thi",
            3: "Xuất & hoàn tất",
          }
          const label = labels[e.checkpoint_id] ?? `Checkpoint ${e.checkpoint_id}`
          setHitlStage(label)
          pushLog("hitl", `HITL ${e.checkpoint_id}`, label, "warning")
          if (e.checkpoint_id === 1) {
            setPendingBlueprint(true)
          }
          break
        }

        case "validation_result": {
          const e = data as ValidationResultEvent
          setValidationPassed(e.passed)
          setValidationIssues(e.issues_count)
          if (e.passed) {
            pushLog("validation", "Validation OK", `${e.issues_count} issues ghi nhận`, "success")
          } else {
            pushLog("validation", "Validation có vấn đề", `${e.issues_count} issues cần sửa`, "warning")
          }
          break
        }

        case "pipeline_paused": {
          const e = data as PipelinePausedEvent
          setHitlStage(e.message)
          pushLog("paused", "Tạm dừng", e.message, "warning")
          break
        }

        case "completed": {
          const e = data as CompletedEvent
          setSteps((prev) => {
            const next = { ...prev }
            PIPELINE_STEPS.forEach((s) => {
              if (prev[s.id] === "running") next[s.id] = "completed"
            })
            return next
          })
          pushLog("completed", "HOÀN TẤT", `Exam ${e.exam_id}`, "success")
          wsRef.current?.close()
          if (!unmountedRef.current) {
            setTimeout(() => onComplete?.(e.exam_id), 800)
          }
          break
        }

        case "error": {
          const e = data as ErrorEvent
          const msg = e.message || "Unknown error"
          setErrorMessage(msg)
          setSteps((prev) => {
            const running = PIPELINE_STEPS.find((s) => prev[s.id] === "running")
            if (running) return { ...prev, [running.id]: "failed" }
            return prev
          })
          pushLog("error", "LỖI", msg, "error")
          wsRef.current?.close()
          if (!unmountedRef.current) onError?.(msg)
          break
        }

        default:
          pushLog("unknown", eventType || "(no type)", JSON.stringify(data).slice(0, 120), "debug")
          break
      }
    },
    [pushLog, onComplete, onError]
  )

  // ── WebSocket connection ───────────────────────────────────────────────────

  useEffect(() => {
    unmountedRef.current = false

    let destroyed = false
    setConnState("connecting")
    pushLog("system", "WS", `Đang kết nối: ${resolvedWsUrl}`, "info")

    const ws = new WebSocket(resolvedWsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      if (destroyed) { ws.close(); return }
      setConnState("connected")
      pushLog("system", "WS", "Đã kết nối thành công", "success")
    }

    ws.onmessage = (evt: MessageEvent) => {
      if (destroyed) return
      const raw = typeof evt.data === "string" ? evt.data : JSON.stringify(evt.data)
      handleWsMessage(raw)
    }

    ws.onerror = (evt) => {
      if (destroyed) return
      setConnState("error")
      const msg = "WebSocket error"
      setConnError(msg)
      pushLog("error", "WS ERROR", msg, "error")
    }

    ws.onclose = (evt) => {
      if (destroyed) return
      const wasConnected = connState === "connected"
      setConnState("closed")
      if (wasConnected && evt.code === 1000) {
        pushLog("system", "WS", `Đóng kết nối (code ${evt.code})`, "info")
      } else {
        pushLog("error", "WS", `Mất kết nối bất thường (code ${evt.code})`, "warning")
      }
    }

    return () => {
      destroyed = true
      unmountedRef.current = true
      ws.close()
    }
  }, [resolvedWsUrl, handleWsMessage, pushLog])

  // ── Derived state ──────────────────────────────────────────────────────────

  const completedCount = Object.values(steps).filter((s) => s === "completed").length
  const runningStep = PIPELINE_STEPS.find((s) => steps[s.id] === "running")
  const progressPct = Math.round((completedCount / PIPELINE_STEPS.length) * 100)
  const isDone = completedCount === PIPELINE_STEPS.length && connState === "closed"

  // ── Render helpers ─────────────────────────────────────────────────────────

  const connIcon = {
    idle: <WifiOff className="h-3.5 w-3.5" />,
    connecting: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    connected: <Wifi className="h-3.5 w-3.5 text-emerald-500" />,
    error: <WifiOff className="h-3.5 w-3.5 text-destructive" />,
    closed: <Wifi className="h-3.5 w-3.5 text-muted-foreground" />,
  }[connState]

  const connLabel = {
    idle: "Chưa kết nối",
    connecting: "Đang kết nối…",
    connected: "Live",
    error: "Lỗi kết nối",
    closed: "Đã đóng",
  }[connState]

  const connColor = {
    idle: "border-muted bg-muted text-muted-foreground",
    connecting: "border-amber-200 bg-amber-50 text-amber-600",
    connected: "border-emerald-200 bg-emerald-50 text-emerald-600",
    error: "border-destructive/30 bg-destructive/5 text-destructive",
    closed: "border-muted bg-muted text-muted-foreground",
  }[connState]

  const logVariantClasses: Record<LogVariant, string> = {
    info: "text-blue-700 bg-blue-50 border-blue-200",
    success: "text-emerald-700 bg-emerald-50 border-emerald-200",
    warning: "text-amber-700 bg-amber-50 border-amber-200",
    error: "text-destructive bg-destructive/5 border-destructive/30",
    debug: "text-gray-600 bg-gray-50 border-gray-200",
  }

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-6 py-3 border-b bg-card">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Sparkles className="h-4.5 w-4.5" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-foreground">Đang sinh đề thi</h1>
            <p className="text-xs text-muted-foreground font-mono">exam: {examId.slice(0, 8)}…</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Question count */}
          {questionCount > 0 && (
            <div className="text-sm tabular-nums">
              <span className="text-muted-foreground">Câu: </span>
              <span className="font-semibold text-primary">{questionCount}</span>
            </div>
          )}

          {/* Connection badge */}
          <div className={cn("flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border", connColor)}>
            {connIcon}
            <span>{connLabel}</span>
          </div>

          {/* Raw log toggle */}
          <button
            onClick={() => setShowRaw((v) => !v)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-muted bg-muted text-muted-foreground hover:text-foreground transition-colors"
            title={showRaw ? "Ẩn raw log" : "Hiện raw log"}
          >
            {showRaw ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            <span>RAW</span>
          </button>

          {/* Retry */}
          {connState === "error" && (
            <button
              onClick={() => window.location.reload()}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-destructive/30 text-destructive hover:bg-destructive/5 transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Thử lại</span>
            </button>
          )}
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── Left panel: Stepper ── */}
        <div className="w-[380px] shrink-0 border-r overflow-y-auto p-6 space-y-4">

          {/* Question counter */}
          {questionCount > 0 && (
            <div className="flex items-center justify-between rounded-xl border bg-card px-4 py-3 shadow-sm">
              <span className="text-sm text-muted-foreground">Câu hỏi đã sinh</span>
              <span className="text-2xl font-bold tabular-nums text-primary">{questionCount}</span>
            </div>
          )}

          {/* Validation status */}
          {validationPassed !== null && (
            <div className={cn(
              "flex items-center gap-3 rounded-xl border px-4 py-3 shadow-sm",
              validationPassed ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"
            )}>
              {validationPassed
                ? <Check className="h-4 w-4 text-emerald-600 shrink-0" />
                : <AlertCircle className="h-4 w-4 text-amber-600 shrink-0" />
              }
              <div className="min-w-0">
                <p className={cn("text-sm font-medium", validationPassed ? "text-emerald-700" : "text-amber-700")}>
                  {validationPassed ? "Qua kiểm tra" : `${validationIssues} vấn đề cần xử lý`}
                </p>
                {hitlStage && <p className="text-xs text-muted-foreground truncate">{hitlStage}</p>}
              </div>
            </div>
          )}

          {/* Pipeline steps */}
          <div className="space-y-0">
            {PIPELINE_STEPS.map((step, index) => {
              const status = steps[step.id] ?? "pending"
              const msg = stepMessages[step.id]
              const isCompleted = status === "completed"
              const isActive = status === "running"
              const isFailed = status === "failed"
              const StepIcon = step.icon

              return (
                <div key={step.id} className="flex items-start gap-3">
                  <div className="flex flex-col items-center">
                    <div
                      className={cn(
                        "flex h-8 w-8 items-center justify-center rounded-lg border-2 transition-all duration-300",
                        isCompleted && "border-primary bg-primary text-primary-foreground",
                        isActive && "border-primary bg-primary/10 text-primary",
                        isFailed && "border-destructive bg-destructive/10 text-destructive",
                        !isCompleted && !isActive && !isFailed && "border-border bg-muted text-muted-foreground"
                      )}
                    >
                      {isCompleted ? <Check className="h-3.5 w-3.5" />
                        : isActive ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <StepIcon className="h-3.5 w-3.5" />
                      }
                    </div>
                    {index < PIPELINE_STEPS.length - 1 && (
                      <div
                        className={cn("w-0.5 flex-1 my-1 transition-colors", isCompleted ? "bg-primary" : "bg-border")}
                        style={{ minHeight: 12 }}
                      />
                    )}
                  </div>
                  <div className="flex flex-col pb-4 pt-1 min-w-0">
                    <span
                      className={cn(
                        "text-sm font-medium transition-colors",
                        (isCompleted || isActive) && "text-foreground",
                        isFailed && "text-destructive",
                        !isCompleted && !isActive && !isFailed && "text-muted-foreground"
                      )}
                    >
                      {step.label}
                      {isCompleted && <span className="ml-1.5 text-xs text-primary">✓</span>}
                      {isFailed && <span className="ml-1.5 text-xs text-destructive">✗</span>}
                    </span>
                    {msg && isActive && (
                      <span className="text-xs text-muted-foreground italic mt-0.5">{msg}</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Progress bar */}
          <div>
            <div className="flex justify-between text-xs text-muted-foreground mb-1.5">
              <span>{completedCount}/{PIPELINE_STEPS.length} bước</span>
              <span>{progressPct}%</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>

          {/* Error banner */}
          {errorMessage && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-destructive">Đã xảy ra lỗi</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{errorMessage}</p>
                </div>
              </div>
            </div>
          )}

          {/* Blueprint approval panel */}
          {pendingBlueprint && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-3">
              <div className="flex items-center gap-2 text-amber-800">
                <AlertCircle className="h-4 w-4" />
                <p className="text-sm font-semibold">Xác nhận sườn đề</p>
              </div>
              <p className="text-xs text-amber-700">
                Agent đã tạo sườn đề. Bạn có muốn tiếp tục sinh câu hỏi không?
              </p>
              <div className="flex gap-2">
                <button
                  onClick={async () => {
                    try {
                      await generationApi.approveBlueprint(examId, true)
                      pushLog("approval", "Xác nhận sườn đề", "Đã xác nhận — tiếp tục sinh câu hỏi", "success")
                    } catch (error) {
                      console.error("approveBlueprint failed:", error)
                      pushLog("approval", "Xác nhận sườn đề", "Gọi API thất bại", "error")
                    } finally {
                      setPendingBlueprint(false)
                    }
                  }}
                  className="flex-1 flex items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  <ThumbsUp className="h-3.5 w-3.5" />
                  Xác nhận sườn đề
                </button>
                <button
                  onClick={async () => {
                    const feedback = "Từ chối sườn đề"
                    try {
                      await generationApi.rejectBlueprint(examId, feedback)
                      pushLog("approval", "Từ chối sườn đề", "Đã từ chối — dừng generation", "warning")
                    } catch {
                      pushLog("approval", "Từ chối sườn đề", "Gọi API thất bại", "error")
                    } finally {
                      setPendingBlueprint(false)
                    }
                  }}
                  className="flex-1 flex items-center justify-center gap-1.5 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium text-foreground hover:bg-muted transition-colors"
                >
                  <X className="h-3.5 w-3.5" />
                  Từ chối
                </button>
              </div>
            </div>
          )}

          {/* Debug info */}
          <div className="rounded-lg border border-dashed border-muted p-3">
            <p className="text-xs text-muted-foreground font-mono break-all">
              WS: {resolvedWsUrl}
            </p>
            <p className="text-xs text-muted-foreground font-mono mt-1">
              State: {connState} | Logs: {logs.length} | Questions: {questionCount}
            </p>
          </div>
        </div>

        {/* ── Right panel: Live reasoning log ── */}
        {showRaw && (
          <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b bg-card">
        <div className="flex items-center gap-2">
          <div className={cn(
            "h-1.5 w-1.5 rounded-full",
            connState === "connected" ? "bg-emerald-500 animate-pulse" : "bg-muted-foreground"
          )} />
          <span className="text-sm font-medium text-foreground flex items-center gap-1.5">
            <Terminal className="h-3.5 w-3.5" />
            Live reasoning log
          </span>
        </div>
        <span className="text-xs text-muted-foreground tabular-nums">
          {logs.length} events
        </span>
      </div>

            <div
              ref={logRef}
              className="flex-1 overflow-y-auto p-4 space-y-1.5"
              style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace", fontSize: 12 }}
            >
              {logs.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
                  <Loader2 className="h-6 w-6 animate-spin" />
                  <p className="text-xs">Đang chờ sự kiện từ agent…</p>
                  {connState === "connecting" && (
                    <p className="text-xs text-amber-500">Đang kết nối WebSocket…</p>
                  )}
                  {connState === "error" && (
                    <p className="text-xs text-destructive">Không thể kết nối: {connError}</p>
                  )}
                </div>
              ) : (
                logs.map((entry) => (
                  <div
                    key={entry.id}
                    className={cn(
                      "flex items-start gap-2 rounded border px-2.5 py-1.5 animate-in fade-in slide-in-from-bottom-1 duration-200",
                      logVariantClasses[entry.variant]
                    )}
                  >
                    <span className="shrink-0 text-muted-foreground tabular-nums select-none">
                      {entry.ts.toLocaleTimeString("vi-VN", {
                        hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit"
                      })}
                    </span>
                    <span className="shrink-0 font-semibold min-w-[100px]">{entry.label}</span>
                    <span className="text-foreground break-all leading-relaxed">{entry.detail}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Footer — done ── */}
      {isDone && (
        <div className="border-t bg-card p-4 flex items-center justify-between animate-in slide-in-from-bottom-2 duration-300">
          <div className="flex items-center gap-2">
            <Check className="h-4 w-4 text-emerald-500" />
            <p className="text-sm text-foreground font-medium">Đề thi đã sẵn sàng!</p>
            {questionCount > 0 && (
              <span className="text-xs text-muted-foreground">({questionCount} câu hỏi)</span>
            )}
          </div>
          <button
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            onClick={() => onComplete?.(examId)}
          >
            Xem đề thi
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  )
}
