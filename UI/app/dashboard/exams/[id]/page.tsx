"use client"

import { useState, useEffect } from "react"
import { useParams } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard-header"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
import {
  RefreshCw,
  Download,
  Save,
  Send,
  Pencil,
  MoreVertical,
  Lock,
  Unlock,
  Sparkles,
  FileText,
  ChevronDown,
  ChevronUp,
  Check,
  Loader2,
  ShieldCheck,
  Activity,
  AlertTriangle,
  Eye,
  Clock,
  Zap,
} from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { Progress } from "@/components/ui/progress"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import {
  exams as examsApi,
  generation as generationApi,
  type Exam,
  type Question as ApiQuestion,
  type QualityScoreDetail,
  type GroundingReportDetail,
  type ProviderLog,
  type DuplicateGroup,
} from "@/lib/api"

export default function ExamReviewPage() {
  const params = useParams()
  const examId = params.id as string
  const [exam, setExam] = useState<Exam | null>(null)
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editContent, setEditContent] = useState("")
  const [regenerateModal, setRegenerateModal] = useState<{
    type: "single" | "from"
    questionId: string
    questionNumber: number
  } | null>(null)
  const [regeneratePrompt, setRegeneratePrompt] = useState("")
  const [regenerateFrom, setRegenerateFrom] = useState<string>("current")
  const [isRegenerating, setIsRegenerating] = useState(false)
  const [isSavingDraft, setIsSavingDraft] = useState(false)
  const [savingQuestionId, setSavingQuestionId] = useState<string | null>(null)

  useEffect(() => {
    if (!examId) return
    examsApi.get(examId)
      .then(setExam)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [examId])

  const questions = exam?.questions ?? []
  const mcqQuestions = questions.filter((q) => q.question_type === "mcq")
  const essayQuestions = questions.filter((q) => q.question_type === "essay")

  const startEdit = (question: ApiQuestion) => {
    setEditingId(question.id)
    setEditContent(question.content)
  }

  const saveEdit = async () => {
    if (editingId === null || !exam) return
    setSavingQuestionId(editingId)
    try {
      const result = await generationApi.partialRegenerate({
        exam_id: exam.id,
        edits: [
          {
            question_ids: [editingId],
            edit_type: "edit_text",
            new_content: editContent,
          },
        ],
      })
      setExam(result)
      setEditingId(null)
      setEditContent("")
    } catch {
      // silently fail
    } finally {
      setSavingQuestionId(null)
    }
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditContent("")
  }

  const handleRegenerate = async () => {
    if (!regenerateModal || !exam) return
    setIsRegenerating(true)
    try {
      const regenerateFromCurrent =
        regenerateModal.type === "from" && regenerateFrom === "current"

      const result = await generationApi.partialRegenerate({
        exam_id: exam.id,
        edits: [
          {
            question_ids: regenerateFromCurrent ? [] : [regenerateModal.questionId],
            range_start: regenerateFromCurrent ? regenerateModal.questionNumber : undefined,
            range_end: regenerateFromCurrent ? questions.length : undefined,
            edit_prompt: regeneratePrompt || undefined,
            edit_type: "regenerate",
          },
        ],
      })
      setExam(result)
    } catch {
      // silently fail
    } finally {
      setIsRegenerating(false)
      setRegenerateModal(null)
      setRegeneratePrompt("")
    }
  }

  const handleSave = () => {
    setIsSavingDraft(true)
    setTimeout(() => setIsSavingDraft(false), 1500)
  }

  if (loading) {
    return (
      <>
        <DashboardHeader title="Exam Review" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </>
    )
  }

  if (!exam) {
    return (
      <>
        <DashboardHeader title="Exam Review" />
        <div className="flex flex-1 items-center justify-center">
          <p className="text-muted-foreground">Exam not found</p>
        </div>
      </>
    )
  }

  return (
    <>
      <DashboardHeader title="Exam Review" />
      <div className="flex flex-1 flex-col gap-6 p-6 max-w-4xl">
        {/* Page Header */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              {exam.title}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {exam.total_questions} questions - {exam.chapters.length > 0 ? `Chapters ${exam.chapters.join(", ")}` : "All chapters"} - {new Date(exam.created_at).toLocaleDateString()}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  <Download className="mr-2 h-3.5 w-3.5" />
                  Export
                  <ChevronDown className="ml-1 h-3 w-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem>
                  <FileText className="mr-2 h-4 w-4" />
                  Export as PDF
                </DropdownMenuItem>
                <DropdownMenuItem>
                  <FileText className="mr-2 h-4 w-4" />
                  Export as DOCX
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button variant="outline" size="sm" onClick={handleSave} disabled={isSavingDraft}>
              {isSavingDraft ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="mr-2 h-3.5 w-3.5" />
              )}
              {isSavingDraft ? "Saving..." : "Save"}
            </Button>
            <Button size="sm">
              <Send className="mr-2 h-3.5 w-3.5" />
              Publish
            </Button>
          </div>
        </div>

        {/* Regenerate Entire Exam */}
        <Card className="rounded-2xl shadow-sm border-dashed">
          <CardContent className="flex items-center justify-between py-4 px-5">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
                <RefreshCw className="h-4 w-4 text-primary" />
              </div>
              <div>
                <p className="text-sm font-medium text-foreground">Not satisfied?</p>
                <p className="text-xs text-muted-foreground">Regenerate the entire exam with new questions</p>
              </div>
            </div>
            <Button variant="outline" size="sm">
              <RefreshCw className="mr-2 h-3.5 w-3.5" />
              Regenerate All
            </Button>
          </CardContent>
        </Card>

        {/* Quality & Analysis Summary */}
        <ExamQualitySummary exam={exam} />

        {/* Section A: Multiple Choice */}
        {mcqQuestions.length > 0 && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <Badge className="bg-primary text-primary-foreground">Section A</Badge>
              <span className="text-sm font-medium text-foreground">Multiple Choice</span>
              <span className="text-xs text-muted-foreground">({mcqQuestions.length} questions)</span>
            </div>
            {mcqQuestions.map((question, index) => (
              <QuestionCard
                key={question.id}
                question={question}
                index={index + 1}
                isEditing={editingId === question.id}
                editContent={editContent}
                onEditContent={setEditContent}
                onStartEdit={() => startEdit(question)}
                onSaveEdit={saveEdit}
                onCancelEdit={cancelEdit}
                isSaving={savingQuestionId === question.id}
                onRegenerate={(type) =>
                  setRegenerateModal({
                    type,
                    questionId: question.id,
                    questionNumber: question.question_number,
                  })
                }
              />
            ))}
          </div>
        )}

        {/* Section B: Essay */}
        {essayQuestions.length > 0 && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <Badge className="bg-primary text-primary-foreground">Section B</Badge>
              <span className="text-sm font-medium text-foreground">Essay</span>
              <span className="text-xs text-muted-foreground">({essayQuestions.length} questions)</span>
            </div>
            {essayQuestions.map((question, index) => (
              <QuestionCard
                key={question.id}
                question={question}
                index={mcqQuestions.length + index + 1}
                isEditing={editingId === question.id}
                editContent={editContent}
                onEditContent={setEditContent}
                onStartEdit={() => startEdit(question)}
                onSaveEdit={saveEdit}
                onCancelEdit={cancelEdit}
                isSaving={savingQuestionId === question.id}
                onRegenerate={(type) =>
                  setRegenerateModal({
                    type,
                    questionId: question.id,
                    questionNumber: question.question_number,
                  })
                }
              />
            ))}
          </div>
        )}

        {/* Regenerate Modal */}
        <Dialog
          open={!!regenerateModal}
          onOpenChange={() => {
            setRegenerateModal(null)
            setRegeneratePrompt("")
            setRegenerateFrom("current")
          }}
        >
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>
                {regenerateModal?.type === "single"
                  ? `Modify Question ${regenerateModal?.questionNumber}`
                  : `Regenerate from Question ${regenerateModal?.questionNumber}`}
              </DialogTitle>
              <DialogDescription>
                {regenerateModal?.type === "single"
                  ? "Enter instructions to modify this specific question. All other questions remain unchanged."
                  : "Regenerate this question and all subsequent questions. Previous questions remain locked."}
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-2">
              {regenerateModal?.type === "from" && (
                <div className="flex flex-col gap-2">
                  <Label className="text-sm font-medium">Regenerate scope</Label>
                  <Select value={regenerateFrom} onValueChange={setRegenerateFrom}>
                    <SelectTrigger className="h-10">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="current">From this question onward</SelectItem>
                      <SelectItem value="only">Only this question</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}
              <div className="flex flex-col gap-2">
                <Label className="text-sm font-medium">Correction prompt</Label>
                <Textarea
                  placeholder="e.g., Make this question more applied, increase difficulty, focus on practical scenarios..."
                  className="min-h-24 resize-none"
                  value={regeneratePrompt}
                  onChange={(e) => setRegeneratePrompt(e.target.value)}
                />
              </div>
              <div className="rounded-lg bg-muted/50 p-3 flex items-start gap-2">
                <Lock className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                <p className="text-xs text-muted-foreground">
                  {regenerateModal?.type === "single"
                    ? "Only this question will be modified. All other questions remain locked and unchanged."
                    : "Questions before this one will remain locked and unchanged."}
                </p>
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setRegenerateModal(null)
                  setRegeneratePrompt("")
                  setRegenerateFrom("current")
                }}
              >
                Cancel
              </Button>
              <Button onClick={handleRegenerate} disabled={isRegenerating}>
                {isRegenerating ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-4 w-4" />
                )}
                {isRegenerating ? "Regenerating..." : "Regenerate"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </>
  )
}

function QuestionCard({
  question,
  index,
  isEditing,
  isSaving,
  editContent,
  onEditContent,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  onRegenerate,
}: {
  question: ApiQuestion
  index: number
  isEditing: boolean
  isSaving: boolean
  editContent: string
  onEditContent: (content: string) => void
  onStartEdit: () => void
  onSaveEdit: () => Promise<void>
  onCancelEdit: () => void
  onRegenerate: (type: "single" | "from") => void
}) {
  const difficultyLabel = question.difficulty_score <= 0.33 ? "Easy" : question.difficulty_score <= 0.66 ? "Medium" : "Hard"
  const difficultyColor = {
    Easy: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-400 dark:border-emerald-800",
    Medium: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-400 dark:border-amber-800",
    Hard: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950 dark:text-rose-400 dark:border-rose-800",
  }

  const qs = question.quality_score_detail
  const gr = question.grounding_report_detail
  const [detailOpen, setDetailOpen] = useState(false)

  return (
    <Card className={`rounded-2xl shadow-sm transition-all ${isEditing ? "ring-2 ring-primary/20 border-primary/40" : ""}`}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-muted text-xs font-semibold text-muted-foreground">
              {index}
            </span>
            <Badge variant="outline" className="text-xs">
              {question.question_type === "mcq" ? "MCQ" : "Essay"}
            </Badge>
            <Badge
              variant="outline"
              className={`text-xs ${difficultyColor[difficultyLabel]}`}
            >
              {difficultyLabel}
            </Badge>
            {qs && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge
                      variant="outline"
                      className={`text-xs ${qs.passed
                        ? "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-400 dark:border-emerald-800"
                        : "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950 dark:text-rose-400 dark:border-rose-800"
                      }`}
                    >
                      <ShieldCheck className="mr-1 h-3 w-3" />
                      {Math.round(qs.overall * 100)}%
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Quality: {qs.recommendation}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
            {gr && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge
                      variant="outline"
                      className={`text-xs ${gr.grounding_pass
                        ? "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-400 dark:border-blue-800"
                        : "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950 dark:text-orange-400 dark:border-orange-800"
                      }`}
                    >
                      <Activity className="mr-1 h-3 w-3" />
                      {gr.grounding_pass ? "Grounded" : "Weak"}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Grounding score: {Math.round(gr.overall_score * 100)}%</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>

          <div className="flex items-center gap-1">
            {!isEditing && (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={onStartEdit}
                >
                  <Pencil className="h-3.5 w-3.5" />
                  <span className="sr-only">Edit question</span>
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-7 w-7">
                      <MoreVertical className="h-3.5 w-3.5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-56">
                    <DropdownMenuItem onClick={() => onRegenerate("single")}>
                      <RefreshCw className="mr-2 h-4 w-4" />
                      Regenerate this question
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => onRegenerate("from")}>
                      <Sparkles className="mr-2 h-4 w-4" />
                      Regenerate from here onward
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={onStartEdit}>
                      <Pencil className="mr-2 h-4 w-4" />
                      Edit question text
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            )}
          </div>
        </div>

        <div className="mt-4">
          {isEditing ? (
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-1.5 text-xs text-primary font-medium">
                <Unlock className="h-3 w-3" />
                Editing mode - Only this question is unlocked
              </div>
              <Textarea
                value={editContent}
                onChange={(e) => onEditContent(e.target.value)}
                className="min-h-24 resize-none"
                autoFocus
              />
              <div className="flex items-center gap-2 justify-end">
                <Button variant="outline" size="sm" onClick={onCancelEdit}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => {
                    void onSaveEdit()
                  }}
                  disabled={isSaving}
                >
                  {isSaving ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Check className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {isSaving ? "Saving..." : "Save changes"}
                </Button>
              </div>
            </div>
          ) : (
            <>
              <p className="text-sm text-foreground leading-relaxed">
                {question.content}
              </p>
              {question.options && (
                <div className="mt-3 flex flex-col gap-2">
                  {question.options.map((option, i) => (
                    <div
                      key={i}
                      className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-sm ${
                        option.label === question.correct_answer
                          ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-400"
                          : "border-border text-foreground"
                      }`}
                    >
                      <span className="flex h-5 w-5 items-center justify-center rounded-full border text-xs font-medium shrink-0">
                        {option.label}
                      </span>
                      {option.text}
                      {option.label === question.correct_answer && (
                        <Check className="ml-auto h-3.5 w-3.5 shrink-0" />
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Quality & Grounding Detail (collapsible) */}
              {(qs || gr) && (
                <Collapsible open={detailOpen} onOpenChange={setDetailOpen}>
                  <CollapsibleTrigger asChild>
                    <Button variant="ghost" size="sm" className="mt-3 text-xs text-muted-foreground gap-1.5 px-2 h-7">
                      <Eye className="h-3 w-3" />
                      {detailOpen ? "Hide" : "Show"} analysis
                      {detailOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div className="mt-2 rounded-lg bg-muted/40 p-4 flex flex-col gap-3">
                      {qs && (
                        <div className="flex flex-col gap-2">
                          <p className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                            <ShieldCheck className="h-3.5 w-3.5" />
                            Quality Rubric
                            <Badge variant="outline" className="ml-auto text-[10px]">
                              {qs.recommendation}
                            </Badge>
                          </p>
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                            <QualityBar label="Answerability" value={qs.answerability} />
                            <QualityBar label="Grounding" value={qs.grounding} />
                            <QualityBar label="Clarity" value={qs.clarity} />
                            <QualityBar label="Ambiguity Risk" value={qs.ambiguity_risk} invert />
                            <QualityBar label="Distractor Quality" value={qs.distractor_quality} />
                            <QualityBar label="Bloom Alignment" value={qs.bloom_alignment} />
                            <QualityBar label="Difficulty Realism" value={qs.difficulty_realism} />
                            <QualityBar label="Overall" value={qs.overall} bold />
                          </div>
                          {qs.notes.length > 0 && (
                            <div className="flex flex-col gap-0.5 mt-1">
                              {qs.notes.map((note, i) => (
                                <p key={i} className="text-[11px] text-muted-foreground flex items-start gap-1">
                                  <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5 text-amber-500" />
                                  {note}
                                </p>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                      {gr && (
                        <div className="flex flex-col gap-2">
                          <p className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                            <Activity className="h-3.5 w-3.5" />
                            Grounding Analysis
                            <Badge variant="outline" className={`ml-auto text-[10px] ${gr.grounding_pass ? "text-emerald-600" : "text-rose-600"}`}>
                              {gr.grounding_pass ? "Pass" : "Fail"}
                            </Badge>
                          </p>
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                            <QualityBar label="Lexical Overlap" value={gr.lexical_overlap} />
                            <QualityBar label="N-gram Overlap" value={gr.ngram_overlap} />
                            <QualityBar label="Phrase Overlap" value={gr.phrase_overlap} />
                            <QualityBar label="Answer Support" value={gr.answer_support_score} />
                            <QualityBar label="Verbatim Ratio" value={gr.verbatim_ratio} invert />
                            <QualityBar label="Overall" value={gr.overall_score} bold />
                          </div>
                        </div>
                      )}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              )}
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

/* ── Helper: single quality metric bar ──────────────────────────── */
function QualityBar({
  label,
  value,
  bold,
  invert,
}: {
  label: string
  value: number
  bold?: boolean
  invert?: boolean
}) {
  const pct = Math.round(value * 100)
  const color = invert
    ? pct > 60 ? "bg-rose-500" : pct > 30 ? "bg-amber-500" : "bg-emerald-500"
    : pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-rose-500"

  return (
    <div className="flex items-center gap-2">
      <span className={`text-[11px] w-28 shrink-0 ${bold ? "font-semibold text-foreground" : "text-muted-foreground"}`}>
        {label}
      </span>
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-[11px] w-8 text-right ${bold ? "font-semibold" : "text-muted-foreground"}`}>{pct}%</span>
    </div>
  )
}

/* ── Exam-level quality summary ─────────────────────────────────── */
function ExamQualitySummary({ exam }: { exam: Exam }) {
  const qs = exam.quality_scores
  const gr = exam.grounding_reports
  const dupes = exam.duplicate_groups
  const logs = exam.provider_logs

  // Skip if no data at all
  if (!qs?.length && !gr?.length && !dupes?.length && !logs?.length) return null

  const passCount = qs?.filter((s) => s.passed).length ?? 0
  const totalQ = qs?.length ?? exam.total_questions
  const avgOverall = qs?.length ? qs.reduce((a, s) => a + s.overall, 0) / qs.length : 0
  const groundedCount = gr?.filter((r) => r.grounding_pass).length ?? 0
  const totalLatency = logs?.reduce((a, l) => a + l.latency_ms, 0) ?? 0
  const avgLatency = logs?.length ? totalLatency / logs.length : 0

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {qs && qs.length > 0 && (
        <Card className="rounded-2xl shadow-sm">
          <CardContent className="p-4 flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <ShieldCheck className="h-3.5 w-3.5" />
              Quality
            </div>
            <p className="text-lg font-semibold">{Math.round(avgOverall * 100)}%</p>
            <p className="text-[11px] text-muted-foreground">
              {passCount}/{totalQ} passed
            </p>
          </CardContent>
        </Card>
      )}
      {gr && gr.length > 0 && (
        <Card className="rounded-2xl shadow-sm">
          <CardContent className="p-4 flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Activity className="h-3.5 w-3.5" />
              Grounding
            </div>
            <p className="text-lg font-semibold">{groundedCount}/{gr.length}</p>
            <p className="text-[11px] text-muted-foreground">
              questions grounded
            </p>
          </CardContent>
        </Card>
      )}
      {dupes && dupes.length > 0 && (
        <Card className="rounded-2xl shadow-sm">
          <CardContent className="p-4 flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <AlertTriangle className="h-3.5 w-3.5" />
              Duplicates
            </div>
            <p className="text-lg font-semibold">{dupes.length}</p>
            <p className="text-[11px] text-muted-foreground">
              groups detected
            </p>
          </CardContent>
        </Card>
      )}
      {logs && logs.length > 0 && (
        <Card className="rounded-2xl shadow-sm">
          <CardContent className="p-4 flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Zap className="h-3.5 w-3.5" />
              LLM Calls
            </div>
            <p className="text-lg font-semibold">{logs.length}</p>
            <p className="text-[11px] text-muted-foreground">
              avg {Math.round(avgLatency)}ms
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
