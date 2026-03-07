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
  Check,
  Loader2,
} from "lucide-react"
import {
  exams as examsApi,
  generation as generationApi,
  type Exam,
  type Question as ApiQuestion,
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
  } | null>(null)
  const [regeneratePrompt, setRegeneratePrompt] = useState("")
  const [regenerateFrom, setRegenerateFrom] = useState<string>("current")
  const [isRegenerating, setIsRegenerating] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

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

  const saveEdit = () => {
    if (editingId !== null && exam) {
      setExam({
        ...exam,
        questions: exam.questions.map((q) =>
          q.id === editingId ? { ...q, content: editContent } : q
        ),
      })
      setEditingId(null)
      setEditContent("")
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
      const result = await generationApi.partialRegenerate({
        exam_id: exam.id,
        edits: [
          {
            question_ids: [regenerateModal.questionId],
            edit_prompt: regeneratePrompt || undefined,
            edit_type: regenerateModal.type === "single" ? "regenerate" : "regenerate",
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
    setIsSaving(true)
    setTimeout(() => setIsSaving(false), 1500)
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
              {exam.total_questions} questions - Chapters {exam.chapters.join(", ")} - {new Date(exam.created_at).toLocaleDateString()}
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
            <Button variant="outline" size="sm" onClick={handleSave} disabled={isSaving}>
              {isSaving ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="mr-2 h-3.5 w-3.5" />
              )}
              {isSaving ? "Saving..." : "Save"}
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
                onRegenerate={(type) =>
                  setRegenerateModal({ type, questionId: question.id })
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
                onRegenerate={(type) =>
                  setRegenerateModal({ type, questionId: question.id })
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
          }}
        >
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>
                {regenerateModal?.type === "single"
                  ? `Modify Question ${regenerateModal?.questionId}`
                  : `Regenerate from Question ${regenerateModal?.questionId}`}
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
  editContent: string
  onEditContent: (content: string) => void
  onStartEdit: () => void
  onSaveEdit: () => void
  onCancelEdit: () => void
  onRegenerate: (type: "single" | "from") => void
}) {
  const difficultyLabel = question.difficulty_score <= 0.33 ? "Easy" : question.difficulty_score <= 0.66 ? "Medium" : "Hard"
  const difficultyColor = {
    Easy: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-400 dark:border-emerald-800",
    Medium: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-400 dark:border-amber-800",
    Hard: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950 dark:text-rose-400 dark:border-rose-800",
  }

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
                <Button size="sm" onClick={onSaveEdit}>
                  <Check className="mr-1.5 h-3.5 w-3.5" />
                  Save changes
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
                        option.text === question.correct_answer
                          ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-400"
                          : "border-border text-foreground"
                      }`}
                    >
                      <span className="flex h-5 w-5 items-center justify-center rounded-full border text-xs font-medium shrink-0">
                        {option.label}
                      </span>
                      {option.text}
                      {option.text === question.correct_answer && (
                        <Check className="ml-auto h-3.5 w-3.5 shrink-0" />
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
