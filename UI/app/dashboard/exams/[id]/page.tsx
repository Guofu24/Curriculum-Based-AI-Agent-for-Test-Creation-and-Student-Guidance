"use client"

import { useEffect, useMemo, useState } from "react"
import { useParams } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  AlertTriangle,
  Check,
  Eye,
  FileText,
  History,
  Layers,
  Loader2,
  Lock,
  MoreVertical,
  Pencil,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Unlock,
} from "lucide-react"
import {
  ApiError,
  exams as examsApi,
  generation as generationApi,
  type ExamVersion,
  type Exam,
  type MCQOption,
  type Question,
} from "@/lib/api"
import {
  countEvidenceCoverage,
  countVerifierWarnings,
  formatPercent,
  getEvidenceCoverageRate,
  getLatestVersion,
  getPlaybookShadowEvents,
  getQuestionEditOperations,
  getQuestionFeedbackEvents,
  getVerifierPassRate,
  getVersionChurn,
  humanReadableCategory,
  humanReadableSignal,
} from "@/lib/quality"

type EditState = {
  questionId: string
  content: string
  options: MCQOption[]
  correctAnswer: string
  bloomLevel: string
}

type RegenerateState = {
  type: "single" | "from" | "all"
  questionId?: string
  questionNumber?: number
} | null

const BLOOM_LEVELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"]
const DEFAULT_OPTION_LABELS = ["A", "B", "C", "D"]

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function getEditableOptions(question: Question): MCQOption[] {
  const indexed = new Map<string, string>()
  const opts: MCQOption[] = Array.isArray(question.options)
    ? question.options
    : Object.entries(question.options || {}).map(([label, text]) => ({ label, text: String(text) }))
  for (const option of opts) {
    if (!option?.label) continue
    indexed.set(option.label.toUpperCase(), option.text || "")
  }
  return DEFAULT_OPTION_LABELS.map((label) => ({ label, text: indexed.get(label) || "" }))
}

function useActiveVersion(exam: Exam | null, selectedVersionId: string) {
  return useMemo(() => {
    if (!exam) return null
    if (selectedVersionId && exam.versions?.length) {
      return exam.versions.find((version) => version.id === selectedVersionId) || exam.current_version || null
    }
    return exam.current_version || exam.versions?.[exam.versions.length - 1] || null
  }, [exam, selectedVersionId])
}

async function loadExamWithRetry(examId: string, attempts = 5): Promise<Exam> {
  let lastError: unknown = null

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await examsApi.get(examId)
    } catch (error: unknown) {
      lastError = error
      const isTransientNotFound = error instanceof ApiError && error.status === 404 && attempt < attempts
      if (!isTransientNotFound) {
        throw error
      }
      await new Promise((resolve) => setTimeout(resolve, 350 * attempt))
    }
  }

  throw lastError instanceof Error ? lastError : new Error("Unable to load exam")
}

export default function ExamReviewPage() {
  const params = useParams()
  const examId = params.id as string
  const [exam, setExam] = useState<Exam | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedVersionId, setSelectedVersionId] = useState("")
  const [editState, setEditState] = useState<EditState | null>(null)
  const [regenerateState, setRegenerateState] = useState<RegenerateState>(null)
  const [regeneratePrompt, setRegeneratePrompt] = useState("")
  const [savingQuestionId, setSavingQuestionId] = useState<string | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState("")
  const [filterBloom, setFilterBloom] = useState("all")

  useEffect(() => {
    if (!examId) return
    let cancelled = false
    setLoading(true)
    setError("")

    void loadExamWithRetry(examId)
      .then((result) => {
        if (cancelled) return
        setExam(result)
        setSelectedVersionId(result.current_version?.id || result.versions?.[result.versions.length - 1]?.id || "")
      })
      .catch((loadError: unknown) => {
        if (cancelled) return
        setError(loadError instanceof Error ? loadError.message : "Unable to load exam")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [examId])

  const activeVersion = useActiveVersion(exam, selectedVersionId)
  const questions = (activeVersion?.questions?.length ? activeVersion.questions : null) ?? exam?.questions ?? []
  const feedbackEvents = activeVersion?.feedback_events || exam?.feedback_events || []
  const playbookShadowEvents = getPlaybookShadowEvents(feedbackEvents)
  const filteredQuestions = questions.filter((question) => filterBloom === "all" || question.bloom_level === filterBloom)
  const versionOperations = activeVersion?.edit_operations || []
  const latestVersion = getLatestVersion(exam)
  const playbookMode = String(playbookShadowEvents[0]?.payload?.retrieval_mode || "off")

  const applyAndRefresh = async (action: () => Promise<Exam>, questionId?: string) => {
    setError("")
    if (questionId) setSavingQuestionId(questionId)
    try {
      const updated = await action()
      setExam(updated)
      setSelectedVersionId(updated.current_version?.id || updated.versions?.[updated.versions.length - 1]?.id || "")
      setEditState(null)
      setRegenerateState(null)
      setRegeneratePrompt("")
    } catch (actionError: unknown) {
      setError(actionError instanceof Error ? actionError.message : "Action failed")
    } finally {
      if (questionId) setSavingQuestionId(null)
    }
  }

  const handleSaveEdit = async () => {
    if (!exam || !editState) return
    const normalizedOptions = editState.options.map((option, index) => ({
      label: DEFAULT_OPTION_LABELS[index],
      text: option.text.trim(),
    }))
    if (normalizedOptions.some((option) => !option.text)) {
      setError("Each question must keep four non-empty options.")
      return
    }
    if (!DEFAULT_OPTION_LABELS.includes(editState.correctAnswer)) {
      setError("Correct answer must be A, B, C, or D.")
      return
    }
    await applyAndRefresh(
      () =>
        generationApi.partialRegenerate({
          exam_id: exam.id,
          edits: [
            { question_ids: [editState.questionId], edit_type: "edit_text", new_content: editState.content.trim() },
            { question_ids: [editState.questionId], edit_type: "edit_options", new_options: normalizedOptions },
            { question_ids: [editState.questionId], edit_type: "edit_answer", new_correct_answer: editState.correctAnswer },
            { question_ids: [editState.questionId], edit_type: "edit_bloom", new_bloom_level: editState.bloomLevel },
          ],
        }),
      editState.questionId,
    )
  }

  const handleQuestionAction = async (question: Question, action: "lock" | "unlock" | "delete") => {
    if (!exam) return
    await applyAndRefresh(
      () =>
        generationApi.partialRegenerate({
          exam_id: exam.id,
          edits: [{ question_ids: [question.id], edit_type: action }],
        }),
      question.id,
    )
  }

  const handleRegenerate = async () => {
    if (!exam || !regenerateState) return
    const edit =
      regenerateState.type === "single"
        ? { question_ids: regenerateState.questionId ? [regenerateState.questionId] : [], edit_type: "regenerate" as const, edit_prompt: regeneratePrompt.trim() || undefined }
        : regenerateState.type === "from"
          ? { question_ids: [], range_start: regenerateState.questionNumber, range_end: questions.length, edit_type: "regenerate" as const, edit_prompt: regeneratePrompt.trim() || undefined }
          : { question_ids: [], edit_type: "regenerate" as const, edit_prompt: regeneratePrompt.trim() || undefined }
    await applyAndRefresh(
      () => generationApi.partialRegenerate({ exam_id: exam.id, edits: [edit] }),
      regenerateState.questionId,
    )
  }

  const handlePublish = async () => {
    if (!exam) return
    setPublishing(true)
    setError("")
    try {
      const updated = await examsApi.publish(exam.id)
      setExam(updated)
      setSelectedVersionId(updated.current_version?.id || updated.versions?.[updated.versions.length - 1]?.id || "")
    } catch (publishError: unknown) {
      setError(publishError instanceof Error ? publishError.message : "Publish failed")
    } finally {
      setPublishing(false)
    }
  }

  if (loading) {
    return (
      <>
        <DashboardHeader title="Review" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </>
    )
  }

  if (!exam) {
    return (
      <>
        <DashboardHeader title="Review" />
        <div className="flex flex-1 items-center justify-center">
          <p className="text-muted-foreground">Exam not found</p>
        </div>
      </>
    )
  }

  return (
    <>
      <DashboardHeader title="Review" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        {error && <div className="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</div>}

        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">{exam.title}</h2>
              <Badge variant="secondary" className="capitalize">{exam.status}</Badge>
              {exam.published_at ? <Badge>Published</Badge> : null}
            </div>
            <p className="text-sm text-muted-foreground">
              {exam.total_questions} MCQ questions | created {formatDate(exam.created_at)}
              {exam.updated_at ? ` | updated ${formatDate(exam.updated_at)}` : ""}
            </p>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">Physics</Badge>
              <Badge variant="outline">Vietnamese</Badge>
              <Badge variant="outline">PDF scoped generation</Badge>
              <Badge variant="outline">{exam.strict_scope_flag ? "Strict scope enforced" : "Legacy non-MVP exam"}</Badge>
              {playbookShadowEvents.length > 0 ? <Badge variant="outline" className="capitalize">Playbook {playbookMode}</Badge> : null}
            </div>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            {(exam.versions?.length || 0) > 0 ? (
              <div className="min-w-56">
                <Select value={selectedVersionId} onValueChange={setSelectedVersionId}>
                  <SelectTrigger className="h-10"><SelectValue placeholder="Select version" /></SelectTrigger>
                  <SelectContent>
                    {(exam.versions || []).map((version) => (
                      <SelectItem key={version.id} value={version.id}>Version {version.version_number} - {version.status}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
            <Button variant="outline" onClick={() => setRegenerateState({ type: "all" })}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Regenerate all
            </Button>
            <Button onClick={handlePublish} disabled={publishing || !!exam.published_at}>
              {publishing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
              {exam.published_at ? "Published" : "Publish review"}
            </Button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-6">
          <Metric title="Active version" value={activeVersion ? `v${activeVersion.version_number}` : "N/A"} note={activeVersion?.change_summary || "Current review version"} icon={Layers} />
          <Metric title="Verifier pass" value={formatPercent(getVerifierPassRate(questions))} note="Current version pass rate" icon={ShieldCheck} />
          <Metric title="Evidence coverage" value={formatPercent(getEvidenceCoverageRate(questions))} note={`${countEvidenceCoverage(questions)}/${questions.length || 0} questions grounded`} icon={Eye} />
          <Metric title="Warnings" value={String(countVerifierWarnings(questions))} note="Current warning load" icon={AlertTriangle} />
          <Metric title="Version churn" value={String(getVersionChurn(exam))} note={latestVersion ? `Latest version is v${latestVersion.version_number}` : "No saved churn"} icon={History} />
          <Metric title="Playbook shadows" value={String(playbookShadowEvents.length)} note={playbookShadowEvents.length > 0 ? `${playbookMode} retrieval logged` : "No playbook context logged"} icon={Sparkles} />
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="pb-4"><CardTitle className="text-base">Selected scope</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {(exam.selected_scope || []).length === 0 ? (
                <span className="text-sm text-muted-foreground">No selected scope stored on this exam.</span>
              ) : (
                (exam.selected_scope || []).map((scope, index) => (
                  <Badge key={`${String(scope.scope_id || scope.section_id || index)}`} variant="outline">
                    {String(scope.title || scope.scope_id || scope.section_id || `Scope ${index + 1}`)}
                  </Badge>
                ))
              )}
            </CardContent>
          </Card>

          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="pb-4"><CardTitle className="text-base">Version activity</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <ActivityRow label="Feedback signals" value={String(feedbackEvents.length)} />
              <ActivityRow label="Edit operations" value={String(versionOperations.length)} />
              <ActivityRow label="Human-edited questions" value={String(questions.filter((question) => question.is_human_edited).length)} />
              <ActivityRow label="Locked questions" value={String(questions.filter((question) => question.is_locked).length)} />
            </CardContent>
          </Card>
        </div>

        {feedbackEvents.length > 0 ? (
          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="pb-4"><CardTitle className="text-base">Recent feedback signals</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {feedbackEvents.slice().reverse().slice(0, 5).map((event) => (
                <div key={event.id} className="rounded-xl border bg-muted/20 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{humanReadableSignal(event.signal_type)}</Badge>
                    {event.review_status ? <Badge variant="outline">{humanReadableCategory(event.review_status)}</Badge> : null}
                    {event.workflow_stage ? <Badge variant="outline">{event.workflow_stage}</Badge> : null}
                    <span className="text-xs text-muted-foreground">{formatDate(event.created_at)}</span>
                  </div>
                  {event.payload ? (
                    <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">{JSON.stringify(event.payload, null, 2)}</pre>
                  ) : null}
                </div>
              ))}
            </CardContent>
          </Card>
        ) : null}

        {playbookShadowEvents.length > 0 ? (
          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="pb-4"><CardTitle className="text-base">Playbook shadow hints</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {playbookShadowEvents.slice().reverse().slice(0, 4).map((event) => {
                const matchedBullets = Array.isArray(event.payload?.matched_bullets) ? event.payload?.matched_bullets : []
                const wouldAttachBullets = Array.isArray(event.payload?.would_attach_bullets)
                  ? event.payload?.would_attach_bullets
                  : matchedBullets
                return (
                  <div key={event.id} className="rounded-xl border bg-muted/20 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary">Playbook shadow</Badge>
                      <Badge variant="outline" className="capitalize">{String(event.payload?.retrieval_mode || playbookMode)}</Badge>
                      {event.event_stage || event.workflow_stage ? <Badge variant="outline">{event.event_stage || event.workflow_stage}</Badge> : null}
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {wouldAttachBullets.length > 0
                        ? `${wouldAttachBullets.length} bullet(s) would attach for this stage in limited mode.`
                        : "Shadow mode was active but no bullet matched this stage."}
                    </p>
                    {wouldAttachBullets.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {wouldAttachBullets.map((bullet) => (
                          <Badge key={`${event.id}-${String((bullet as { bullet_id?: string }).bullet_id || "")}`} variant="outline">
                            {String((bullet as { title?: string }).title || "Untitled")}
                          </Badge>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </CardContent>
          </Card>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Select value={filterBloom} onValueChange={setFilterBloom}>
            <SelectTrigger className="h-9 w-48 text-sm"><SelectValue placeholder="Filter by Bloom level" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Bloom levels</SelectItem>
              {BLOOM_LEVELS.map((level) => (
                <SelectItem key={level} value={level} className="capitalize">{level}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {filterBloom !== "all" ? <Button variant="ghost" size="sm" onClick={() => setFilterBloom("all")}>Clear filter</Button> : null}
          <Badge variant="outline" className="text-xs">{filteredQuestions.length}/{questions.length} questions</Badge>
        </div>

        <div className="space-y-4">
          {filteredQuestions.map((question) => (
            <QuestionCard
              key={question.id}
              question={question}
              version={activeVersion}
              isEditing={editState?.questionId === question.id}
              saving={savingQuestionId === question.id}
              editState={editState}
              onStartEdit={() =>
                setEditState({
                  questionId: question.id,
                  content: question.content,
                  options: getEditableOptions(question),
                  correctAnswer: question.correct_answer || "A",
                  bloomLevel: question.bloom_level,
                })
              }
              onEditChange={(next) => setEditState((current) => (current ? { ...current, ...next } : current))}
              onOptionChange={(index, text) =>
                setEditState((current) => {
                  if (!current) return current
                  const options = current.options.map((option, optionIndex) => optionIndex === index ? { ...option, text } : option)
                  return { ...current, options }
                })
              }
              onCancelEdit={() => setEditState(null)}
              onSaveEdit={() => void handleSaveEdit()}
              onRegenerate={(type) => setRegenerateState({ type, questionId: question.id, questionNumber: question.question_number })}
              onLockToggle={() => void handleQuestionAction(question, question.is_locked ? "unlock" : "lock")}
              onDelete={() => void handleQuestionAction(question, "delete")}
            />
          ))}
        </div>

        <Dialog open={!!regenerateState} onOpenChange={(open) => {
          if (!open) {
            setRegenerateState(null)
            setRegeneratePrompt("")
          }
        }}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>
                {regenerateState?.type === "single"
                  ? `Regenerate question ${regenerateState.questionNumber}`
                  : regenerateState?.type === "from"
                    ? `Regenerate from question ${regenerateState.questionNumber}`
                    : "Regenerate the full exam"}
              </DialogTitle>
              <DialogDescription>
                The system keeps the current scope, retrieves evidence inside the selected sections, and saves a new review version.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <Label htmlFor="regenerate-prompt">Optional regenerate note</Label>
              <Textarea
                id="regenerate-prompt"
                value={regeneratePrompt}
                onChange={(event) => setRegeneratePrompt(event.target.value)}
                placeholder="Example: keep the same scope but make the wording shorter and slightly harder."
                className="min-h-28"
              />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => { setRegenerateState(null); setRegeneratePrompt("") }}>
                Cancel
              </Button>
              <Button onClick={() => void handleRegenerate()} disabled={savingQuestionId === regenerateState?.questionId}>
                {savingQuestionId === regenerateState?.questionId ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
                Regenerate
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </>
  )
}

function Metric({
  title,
  value,
  note,
  icon: Icon,
}: {
  title: string
  value: string
  note: string
  icon: typeof FileText
}) {
  return (
    <Card className="rounded-2xl shadow-sm">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Icon className="h-3.5 w-3.5" />
          {title}
        </div>
        <p className="mt-2 text-2xl font-semibold text-foreground">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  )
}

function ActivityRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-xl border bg-muted/20 px-4 py-3">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-semibold text-foreground">{value}</span>
    </div>
  )
}

function QuestionCard({
  question,
  version,
  isEditing,
  saving,
  editState,
  onStartEdit,
  onEditChange,
  onOptionChange,
  onCancelEdit,
  onSaveEdit,
  onRegenerate,
  onLockToggle,
  onDelete,
}: {
  question: Question
  version: ExamVersion | null
  isEditing: boolean
  saving: boolean
  editState: EditState | null
  onStartEdit: () => void
  onEditChange: (next: Partial<EditState>) => void
  onOptionChange: (index: number, text: string) => void
  onCancelEdit: () => void
  onSaveEdit: () => void
  onRegenerate: (type: "single" | "from") => void
  onLockToggle: () => void
  onDelete: () => void
}) {
  const relatedFeedback = getQuestionFeedbackEvents(version, question.id)
  const relatedOperations = getQuestionEditOperations(version, question)
  const hasRegenerateEvent = relatedFeedback.some((event) => event.signal_type === "regenerate_requested")
  const playbookHints = relatedFeedback.filter((event) => event.signal_type === "playbook_shadow")

  return (
    <Card className={`rounded-2xl shadow-sm ${isEditing ? "border-primary/50 ring-2 ring-primary/15" : ""}`}>
      <CardContent className="p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">Question {question.question_number}</Badge>
              <Badge variant="outline">MCQ single-answer</Badge>
              <Badge variant="outline" className="capitalize">{question.bloom_level}</Badge>
              {question.verification_status ? <Badge variant={question.verification_status === "passed" ? "secondary" : "outline"}>{question.verification_status}</Badge> : null}
              {question.is_locked ? <Badge><Lock className="mr-1 h-3 w-3" />Locked</Badge> : null}
              {question.is_human_edited ? <Badge variant="outline"><Pencil className="mr-1 h-3 w-3" />Human edited</Badge> : null}
              {hasRegenerateEvent ? <Badge variant="outline"><RefreshCw className="mr-1 h-3 w-3" />Regenerated</Badge> : null}
            </div>
            {question.blueprint_cell_key ? <p className="text-xs text-muted-foreground">Blueprint cell: {question.blueprint_cell_key}</p> : null}
            {(question.error_categories || []).length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {(question.error_categories || []).map((category, i) => (
                  <Badge key={`${question.id}-${category}-${i}`} variant="outline" className="capitalize">
                    {humanReadableCategory(category)}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="h-8 w-8"><MoreVertical className="h-4 w-4" /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem onClick={onStartEdit}><Pencil className="mr-2 h-4 w-4" />Edit question and answer</DropdownMenuItem>
              <DropdownMenuItem onClick={() => onRegenerate("single")}><RefreshCw className="mr-2 h-4 w-4" />Regenerate this question</DropdownMenuItem>
              <DropdownMenuItem onClick={() => onRegenerate("from")}><Sparkles className="mr-2 h-4 w-4" />Regenerate from this point</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onLockToggle}>
                {question.is_locked ? <><Unlock className="mr-2 h-4 w-4" />Unlock question</> : <><Lock className="mr-2 h-4 w-4" />Lock question</>}
              </DropdownMenuItem>
              <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={onDelete}><Trash2 className="mr-2 h-4 w-4" />Delete question</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {isEditing && editState ? (
          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label>Question text</Label>
              <Textarea value={editState.content} onChange={(event) => onEditChange({ content: event.target.value })} className="min-h-28" />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {editState.options.map((option, index) => (
                <div key={`${question.id}-${option.label}`} className="space-y-2">
                  <Label>Option {option.label}</Label>
                  <Input value={option.text} onChange={(event) => onOptionChange(index, event.target.value)} />
                </div>
              ))}
            </div>
            <div className="grid gap-4 md:grid-cols-[220px_220px]">
              <div className="space-y-2">
                <Label>Correct answer</Label>
                <Select value={editState.correctAnswer} onValueChange={(value) => onEditChange({ correctAnswer: value })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{DEFAULT_OPTION_LABELS.map((label) => <SelectItem key={label} value={label}>{label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Bloom level</Label>
                <Select value={editState.bloomLevel} onValueChange={(value) => onEditChange({ bloomLevel: value })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{BLOOM_LEVELS.map((level) => <SelectItem key={level} value={level}>{level}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onCancelEdit}>Cancel</Button>
              <Button onClick={onSaveEdit} disabled={saving}>{saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}Save as a new version</Button>
            </div>
          </div>
        ) : (
          <div className="mt-4 space-y-4">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{question.content}</p>
            <div className="space-y-2">
              {(() => {
                const opts: MCQOption[] = Array.isArray(question.options)
                  ? question.options
                  : Object.entries(question.options || {}).map(([label, text]) => ({ label, text: String(text) }))
                return opts.map((option) => (
                  <div key={`${question.id}-${option.label}`} className={`flex items-start gap-3 rounded-lg border px-3 py-2 text-sm ${option.label === question.correct_answer ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-border bg-background text-foreground"}`}>
                    <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs font-medium">{option.label}</span>
                    <span className="flex-1">{option.text}</span>
                    {option.label === question.correct_answer ? <Check className="h-4 w-4 shrink-0" /> : null}
                  </div>
                ))
              })()}
            </div>
            {question.explanation ? (
              <div className="rounded-xl border bg-muted/20 p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Explanation</p>
                <p className="mt-2 text-sm text-foreground">{question.explanation}</p>
              </div>
            ) : null}
            {question.warnings?.length ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-amber-800"><AlertTriangle className="h-4 w-4" />Verifier warnings</div>
                <ul className="mt-2 space-y-1 text-sm text-amber-700">{question.warnings.map((warning) => <li key={warning}>- {warning}</li>)}</ul>
              </div>
            ) : null}
            {question.source_evidence?.length ? (
              <div className="rounded-xl border bg-muted/20 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground"><Eye className="h-4 w-4" />Source evidence</div>
                <div className="mt-3 space-y-2">
                  {question.source_evidence.map((evidence) => (
                    <div key={`${question.id}-${evidence.chunk_id}`} className="rounded-lg border bg-background p-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <Badge variant="outline">{evidence.chunk_id}</Badge>
                        {evidence.document_id ? <Badge variant="outline">Doc {evidence.document_id}</Badge> : null}
                        {evidence.section_id ? <Badge variant="outline">Section {evidence.section_id}</Badge> : null}
                        {evidence.chapter_number ? <Badge variant="secondary">Chapter {evidence.chapter_number}</Badge> : null}
                        {evidence.page ? <Badge variant="outline">Page {evidence.page}</Badge> : null}
                        {evidence.parent_heading ? <Badge variant="outline">{evidence.parent_heading}</Badge> : null}
                      </div>
                      {evidence.text_preview ? <p className="mt-2 text-sm text-foreground">{evidence.text_preview}</p> : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">This question does not have valid source evidence yet.</div>
            )}
            {(relatedFeedback.length > 0 || relatedOperations.length > 0) ? (
              <div className="rounded-xl border bg-muted/20 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground"><History className="h-4 w-4" />Question activity</div>
                <div className="mt-3 space-y-2">
                  {relatedFeedback.map((event) => (
                    <div key={event.id} className="rounded-lg border bg-background p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">{humanReadableSignal(event.signal_type)}</Badge>
                        {event.review_status ? <Badge variant="outline">{humanReadableCategory(event.review_status)}</Badge> : null}
                        <span className="text-xs text-muted-foreground">{formatDate(event.created_at)}</span>
                      </div>
                      {(() => {
                        const matchedBullets = Array.isArray(event.payload?.matched_bullets)
                          ? event.payload.matched_bullets as Array<Record<string, unknown>>
                          : []
                        const wouldAttachBullets = Array.isArray(event.payload?.would_attach_bullets)
                          ? event.payload.would_attach_bullets as Array<Record<string, unknown>>
                          : matchedBullets
                        if (event.signal_type !== "playbook_shadow" || wouldAttachBullets.length === 0) {
                          return null
                        }
                        return (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {wouldAttachBullets.map((bullet) => (
                              <Badge key={`${event.id}-${String(bullet.bullet_id || "")}`} variant="outline">
                                {String(bullet.title || "Untitled")}
                              </Badge>
                            ))}
                          </div>
                        )
                      })()}
                    </div>
                  ))}
                  {relatedOperations.map((operation) => (
                    <div key={operation.id} className="rounded-lg border bg-background p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{humanReadableCategory(operation.edit_type)}</Badge>
                        {operation.target_slots.length > 0 ? <Badge variant="outline">Slots {operation.target_slots.join(", ")}</Badge> : null}
                        <span className="text-xs text-muted-foreground">{formatDate(operation.created_at)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {playbookHints.length > 0 ? (
              <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground"><Sparkles className="h-4 w-4" />Playbook hint trail</div>
                <p className="mt-2 text-sm text-muted-foreground">
                  This question has playbook shadow activity attached to the same review version, so you can inspect which approved bullets would have been used in limited mode.
                </p>
              </div>
            ) : null}
            {question.scope_tags?.length ? <div className="flex flex-wrap gap-2">{question.scope_tags.map((tag) => <Badge key={tag} variant="outline">{tag}</Badge>)}</div> : null}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
