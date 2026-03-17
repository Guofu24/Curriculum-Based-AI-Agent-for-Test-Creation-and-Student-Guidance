"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { DashboardHeader } from "@/components/dashboard-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertTriangle,
  Check,
  Download,
  Eye,
  FileCheck,
  FileJson,
  FileText,
  Filter,
  Layers,
  Loader2,
  Lock,
  MessageSquare,
  MoreVertical,
  Pencil,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Unlock,
} from "lucide-react";
import {
  exams as examsApi,
  generation as generationApi,
  type Exam,
  type Question,
} from "@/lib/api";

type EditState = {
  questionId: string;
  content: string;
  correctAnswer: string;
  bloomLevel: string;
};

type RegenerateState = {
  type: "single" | "from";
  questionId: string;
  questionNumber: number;
} | null;

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function useActiveVersion(exam: Exam | null, selectedVersionId: string) {
  return useMemo(() => {
    if (!exam) return null;
    if (selectedVersionId && exam.versions?.length) {
      return exam.versions.find((version) => version.id === selectedVersionId) || exam.current_version || null;
    }
    return exam.current_version || exam.versions?.[exam.versions.length - 1] || null;
  }, [exam, selectedVersionId]);
}

export default function ExamReviewPage() {
  const params = useParams();
  const examId = params.id as string;
  const [exam, setExam] = useState<Exam | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [editState, setEditState] = useState<EditState | null>(null);
  const [regenerateState, setRegenerateState] = useState<RegenerateState>(null);
  const [regeneratePrompt, setRegeneratePrompt] = useState("");
  const [savingQuestionId, setSavingQuestionId] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState("");
  const [exportLoading, setExportLoading] = useState(false);
  const [promptEdit, setPromptEdit] = useState("");
  const [promptEditLoading, setPromptEditLoading] = useState(false);
  const [filterBloom, setFilterBloom] = useState("all");
  const [filterType, setFilterType] = useState("all");

  useEffect(() => {
    if (!examId) return;
    examsApi
      .get(examId)
      .then((result) => {
        setExam(result);
        setSelectedVersionId(result.current_version?.id || result.versions?.[result.versions.length - 1]?.id || "");
      })
      .catch((loadError: unknown) => {
        setError(loadError instanceof Error ? loadError.message : "Failed to load exam");
      })
      .finally(() => setLoading(false));
  }, [examId]);

  const activeVersion = useActiveVersion(exam, selectedVersionId);
  const questions = activeVersion?.questions || exam?.questions || [];

  const applyAndRefresh = async (action: () => Promise<Exam>, questionId?: string) => {
    setError("");
    if (questionId) setSavingQuestionId(questionId);
    try {
      const updated = await action();
      setExam(updated);
      setSelectedVersionId(updated.current_version?.id || updated.versions?.[updated.versions.length - 1]?.id || "");
      setEditState(null);
      setRegenerateState(null);
      setRegeneratePrompt("");
    } catch (actionError: unknown) {
      setError(actionError instanceof Error ? actionError.message : "Action failed");
    } finally {
      if (questionId) setSavingQuestionId(null);
    }
  };

  const handleSaveEdit = async () => {
    if (!exam || !editState) return;
    await applyAndRefresh(
      () =>
        generationApi.partialRegenerate({
          exam_id: exam.id,
          edits: [
            {
              question_ids: [editState.questionId],
              edit_type: "edit_text",
              new_content: editState.content,
            },
            {
              question_ids: [editState.questionId],
              edit_type: "edit_answer",
              new_correct_answer: editState.correctAnswer,
            },
            {
              question_ids: [editState.questionId],
              edit_type: "edit_bloom",
              new_bloom_level: editState.bloomLevel,
            },
          ],
        }),
      editState.questionId,
    );
  };

  const handleQuestionAction = async (question: Question, action: "lock" | "unlock" | "delete") => {
    if (!exam) return;
    await applyAndRefresh(
      () =>
        generationApi.partialRegenerate({
          exam_id: exam.id,
          edits: [
            {
              question_ids: [question.id],
              edit_type: action,
            },
          ],
        }),
      question.id,
    );
  };

  const handleRegenerate = async () => {
    if (!exam || !regenerateState) return;
    await applyAndRefresh(
      () =>
        generationApi.partialRegenerate({
          exam_id: exam.id,
          edits: [
            regenerateState.type === "single"
              ? {
                  question_ids: [regenerateState.questionId],
                  edit_type: "regenerate",
                  edit_prompt: regeneratePrompt || undefined,
                }
              : {
                  question_ids: [],
                  range_start: regenerateState.questionNumber,
                  range_end: questions.length,
                  edit_type: "regenerate",
                  edit_prompt: regeneratePrompt || undefined,
                },
          ],
        }),
      regenerateState.questionId,
    );
  };

  const handlePublish = async () => {
    if (!exam) return;
    setPublishing(true);
    setError("");
    try {
      const updated = await examsApi.publish(exam.id);
      setExam(updated);
      setSelectedVersionId(updated.current_version?.id || updated.versions?.[updated.versions.length - 1]?.id || "");
    } catch (publishError: unknown) {
      setError(publishError instanceof Error ? publishError.message : "Publish failed");
    } finally {
      setPublishing(false);
    }
  };

  const handleExport = async (format: "docx" | "docx-answers" | "docx-key" | "json") => {
    if (!exam) return;
    setExportLoading(true);
    setError("");
    try {
      const slug = exam.title.replace(/[^\w]/g, "_").toLowerCase().slice(0, 50);
      switch (format) {
        case "docx":
          await examsApi.exportDocx(exam.id, `${slug}.docx`);
          break;
        case "docx-answers":
          await examsApi.exportDocx(exam.id, `${slug}_dap_an.docx`, {
            includeAnswers: true,
            includeRubric: true,
            includeExplanation: true,
          });
          break;
        case "docx-key":
          await examsApi.exportAnswerKey(exam.id, `${slug}_bang_dap_an.docx`);
          break;
        case "json":
          await examsApi.exportJson(exam.id, `${slug}.json`);
          break;
      }
    } catch (exportError: unknown) {
      setError(exportError instanceof Error ? exportError.message : "Export failed");
    } finally {
      setExportLoading(false);
    }
  };

  const handlePromptEdit = async () => {
    if (!exam || !promptEdit.trim()) return;
    setPromptEditLoading(true);
    setError("");
    try {
      const updated = await generationApi.partialRegenerate({
        exam_id: exam.id,
        edits: [{
          question_ids: [],
          edit_type: "regenerate",
          edit_prompt: promptEdit,
        }],
      });
      setExam(updated);
      setSelectedVersionId(updated.current_version?.id || updated.versions?.[updated.versions.length - 1]?.id || "");
      setPromptEdit("");
    } catch (editError: unknown) {
      setError(editError instanceof Error ? editError.message : "Edit failed");
    } finally {
      setPromptEditLoading(false);
    }
  };

  const filteredQuestions = questions.filter((q) => {
    if (filterBloom !== "all" && q.bloom_level !== filterBloom) return false;
    if (filterType !== "all" && q.question_type !== filterType) return false;
    return true;
  });

  if (loading) {
    return (
      <>
        <DashboardHeader title="Exam Review" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </>
    );
  }

  if (!exam) {
    return (
      <>
        <DashboardHeader title="Exam Review" />
        <div className="flex flex-1 items-center justify-center">
          <p className="text-muted-foreground">Exam not found</p>
        </div>
      </>
    );
  }

  return (
    <>
      <DashboardHeader title="Exam Review" />
      <div className="flex flex-1 flex-col gap-6 p-6 max-w-6xl">
        {error && (
          <div className="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">{exam.title}</h2>
              <Badge variant="secondary" className="capitalize">
                {exam.status}
              </Badge>
              {exam.published_at && <Badge>Published</Badge>}
            </div>
            <p className="text-sm text-muted-foreground">
              {exam.total_questions} questions · created {formatDate(exam.created_at)}
              {exam.updated_at ? ` · updated ${formatDate(exam.updated_at)}` : ""}
            </p>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="capitalize">
                {exam.exam_type}
              </Badge>
              <Badge variant="outline" className="capitalize">
                {exam.difficulty.replaceAll("_", " ")}
              </Badge>
              <Badge variant="outline">
                {exam.strict_scope_flag ? "Strict scope" : "Flexible scope"}
              </Badge>
              <Badge variant="outline">
                {exam.output_language.toUpperCase()}
              </Badge>
            </div>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            {(exam.versions?.length || 0) > 0 && (
              <div className="min-w-52">
                <Select value={selectedVersionId} onValueChange={setSelectedVersionId}>
                  <SelectTrigger className="h-10">
                    <SelectValue placeholder="Choose version" />
                  </SelectTrigger>
                  <SelectContent>
                    {(exam.versions || []).map((version) => (
                      <SelectItem key={version.id} value={version.id}>
                        Version {version.version_number} · {version.status}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" disabled={exportLoading}>
                  {exportLoading ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="mr-2 h-4 w-4" />
                  )}
                  Export
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuItem onClick={() => void handleExport("docx")}>
                  <FileText className="mr-2 h-4 w-4" />
                  DOCX (đề thi)
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => void handleExport("docx-answers")}>
                  <FileCheck className="mr-2 h-4 w-4" />
                  DOCX (kèm đáp án)
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => void handleExport("docx-key")}>
                  <FileText className="mr-2 h-4 w-4" />
                  DOCX (bảng đáp án)
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => void handleExport("json")}>
                  <FileJson className="mr-2 h-4 w-4" />
                  JSON (file data)
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            <Button onClick={handlePublish} disabled={publishing || !!exam.published_at}>
              {publishing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              {exam.published_at ? "Published" : "Publish exam"}
            </Button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          <SummaryCard
            title="Active version"
            value={activeVersion ? `v${activeVersion.version_number}` : "N/A"}
            note={activeVersion?.change_summary || "Current working version"}
            icon={Layers}
          />
          <SummaryCard
            title="Blueprint cells"
            value={String(Array.isArray(exam.blueprint?.cells) ? exam.blueprint.cells.length : 0)}
            note="Planned scope/question allocations"
            icon={FileText}
          />
          <SummaryCard
            title="Warnings"
            value={String(questions.reduce((sum, question) => sum + (question.warnings?.length || 0), 0))}
            note="Question-level verification warnings"
            icon={AlertTriangle}
          />
          <SummaryCard
            title="Validated"
            value={`${questions.filter((question) => question.is_validated).length}/${questions.length}`}
            note="Questions that passed validation"
            icon={ShieldCheck}
          />
        </div>

        {exam.selected_scope && exam.selected_scope.length > 0 && (
          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="pb-4">
              <CardTitle className="text-base">Selected Scope</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {exam.selected_scope.map((scope, index) => (
                <Badge key={`${scope.scope_id || scope.title || index}`} variant="outline">
                  {String(scope.title || scope.scope_id || `Scope ${index + 1}`)}
                </Badge>
              ))}
            </CardContent>
          </Card>
        )}

        {/* Global Prompt Edit */}
        <Card className="rounded-2xl shadow-sm">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <MessageSquare className="mt-1 h-4 w-4 text-muted-foreground shrink-0" />
              <div className="flex-1 space-y-2">
                <Textarea
                  value={promptEdit}
                  onChange={(e) => setPromptEdit(e.target.value)}
                  placeholder="Nhập prompt để chỉnh sửa toàn bộ đề... Ví dụ: Tăng độ khó các câu trắc nghiệm, thêm câu hỏi phân tích cho chương 3"
                  className="min-h-16 resize-none"
                />
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    onClick={() => void handlePromptEdit()}
                    disabled={promptEditLoading || !promptEdit.trim()}
                  >
                    {promptEditLoading ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Sparkles className="mr-2 h-4 w-4" />
                    )}
                    Áp dụng chỉnh sửa
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Question Filters */}
        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <Select value={filterBloom} onValueChange={setFilterBloom}>
              <SelectTrigger className="h-8 w-40 text-xs">
                <SelectValue placeholder="Bloom level" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Bloom levels</SelectItem>
                {["remember", "understand", "apply", "analyze", "evaluate", "create"].map((level) => (
                  <SelectItem key={level} value={level} className="capitalize">
                    {level}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={filterType} onValueChange={setFilterType}>
              <SelectTrigger className="h-8 w-36 text-xs">
                <SelectValue placeholder="Question type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All types</SelectItem>
                <SelectItem value="mcq">MCQ</SelectItem>
                <SelectItem value="essay">Essay</SelectItem>
              </SelectContent>
            </Select>
            {(filterBloom !== "all" || filterType !== "all") && (
              <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => { setFilterBloom("all"); setFilterType("all"); }}>
                Clear filters
              </Button>
            )}
            <Badge variant="outline" className="text-xs">
              {filteredQuestions.length}/{questions.length} questions
            </Badge>
          </div>
        </div>

        <div className="space-y-4">
          {filteredQuestions.map((question) => (
            <QuestionCard
              key={question.id}
              question={question}
              isEditing={editState?.questionId === question.id}
              saving={savingQuestionId === question.id}
              editState={editState}
              onStartEdit={() =>
                setEditState({
                  questionId: question.id,
                  content: question.content,
                  correctAnswer: question.correct_answer,
                  bloomLevel: question.bloom_level,
                })
              }
              onEditChange={(next) => setEditState((current) => (current ? { ...current, ...next } : current))}
              onCancelEdit={() => setEditState(null)}
              onSaveEdit={() => void handleSaveEdit()}
              onRegenerate={(type) =>
                setRegenerateState({
                  type,
                  questionId: question.id,
                  questionNumber: question.question_number,
                })
              }
              onLockToggle={() => void handleQuestionAction(question, question.is_locked ? "unlock" : "lock")}
              onDelete={() => void handleQuestionAction(question, "delete")}
            />
          ))}
        </div>

        <Dialog open={!!regenerateState} onOpenChange={() => setRegenerateState(null)}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>
                {regenerateState?.type === "single"
                  ? `Regenerate question ${regenerateState.questionNumber}`
                  : `Regenerate from question ${regenerateState?.questionNumber}`}
              </DialogTitle>
              <DialogDescription>
                The backend will keep existing constraints, preserve scope, and create a new exam version after regeneration.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <Label>Optional correction prompt</Label>
              <Textarea
                value={regeneratePrompt}
                onChange={(event) => setRegeneratePrompt(event.target.value)}
                placeholder="Example: Make this question more applied, shorten the wording, and keep it in the same scope."
                className="min-h-28"
              />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setRegenerateState(null)}>
                Cancel
              </Button>
              <Button onClick={() => void handleRegenerate()} disabled={savingQuestionId === regenerateState?.questionId}>
                {savingQuestionId === regenerateState?.questionId ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-4 w-4" />
                )}
                Regenerate
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </>
  );
}

function SummaryCard({
  title,
  value,
  note,
  icon: Icon,
}: {
  title: string;
  value: string;
  note: string;
  icon: typeof FileText;
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
  );
}

function QuestionCard({
  question,
  isEditing,
  saving,
  editState,
  onStartEdit,
  onEditChange,
  onCancelEdit,
  onSaveEdit,
  onRegenerate,
  onLockToggle,
  onDelete,
}: {
  question: Question;
  isEditing: boolean;
  saving: boolean;
  editState: EditState | null;
  onStartEdit: () => void;
  onEditChange: (next: Partial<EditState>) => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onRegenerate: (type: "single" | "from") => void;
  onLockToggle: () => void;
  onDelete: () => void;
}) {
  return (
    <Card className={`rounded-2xl shadow-sm ${isEditing ? "border-primary/50 ring-2 ring-primary/15" : ""}`}>
      <CardContent className="p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">Q{question.question_number}</Badge>
              <Badge variant="outline" className="capitalize">
                {question.question_type}
              </Badge>
              <Badge variant="outline" className="capitalize">
                {question.bloom_level}
              </Badge>
              {question.verification_status && (
                <Badge variant={question.verification_status === "passed" ? "secondary" : "outline"}>
                  {question.verification_status}
                </Badge>
              )}
              {question.is_locked && (
                <Badge>
                  <Lock className="mr-1 h-3 w-3" />
                  Locked
                </Badge>
              )}
              {question.is_human_edited && (
                <Badge variant="outline">
                  <Pencil className="mr-1 h-3 w-3" />
                  Human edited
                </Badge>
              )}
            </div>
            {question.blueprint_cell_key && (
              <p className="text-xs text-muted-foreground">Blueprint cell: {question.blueprint_cell_key}</p>
            )}
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8">
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem onClick={onStartEdit}>
                <Pencil className="mr-2 h-4 w-4" />
                Edit content, answer, Bloom
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onRegenerate("single")}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Regenerate this question
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onRegenerate("from")}>
                <Sparkles className="mr-2 h-4 w-4" />
                Regenerate from here onward
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onLockToggle}>
                {question.is_locked ? (
                  <>
                    <Unlock className="mr-2 h-4 w-4" />
                    Unlock question
                  </>
                ) : (
                  <>
                    <Lock className="mr-2 h-4 w-4" />
                    Lock question
                  </>
                )}
              </DropdownMenuItem>
              <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={onDelete}>
                <Trash2 className="mr-2 h-4 w-4" />
                Delete question
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {isEditing && editState ? (
          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label>Question content</Label>
              <Textarea
                value={editState.content}
                onChange={(event) => onEditChange({ content: event.target.value })}
                className="min-h-28"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-[1fr_220px]">
              <div className="space-y-2">
                <Label>Correct answer</Label>
                <Input
                  value={editState.correctAnswer}
                  onChange={(event) => onEditChange({ correctAnswer: event.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label>Bloom level</Label>
                <Select value={editState.bloomLevel} onValueChange={(value) => onEditChange({ bloomLevel: value })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["remember", "understand", "apply", "analyze", "evaluate", "create"].map((level) => (
                      <SelectItem key={level} value={level}>
                        {level}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onCancelEdit}>
                Cancel
              </Button>
              <Button onClick={onSaveEdit} disabled={saving}>
                {saving ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Check className="mr-2 h-4 w-4" />
                )}
                Save as new version
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-4 space-y-4">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{question.content}</p>

            {question.options && question.options.length > 0 && (
              <div className="space-y-2">
                {question.options.map((option) => (
                  <div
                    key={`${question.id}-${option.label}`}
                    className={`flex items-start gap-3 rounded-lg border px-3 py-2 text-sm ${
                      option.label === question.correct_answer
                        ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                        : "border-border bg-background text-foreground"
                    }`}
                  >
                    <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs font-medium">
                      {option.label}
                    </span>
                    <span className="flex-1">{option.text}</span>
                    {option.label === question.correct_answer && <Check className="h-4 w-4 shrink-0" />}
                  </div>
                ))}
              </div>
            )}

            {!question.options?.length && (
              <div className="rounded-lg bg-muted/30 p-3 text-sm">
                <span className="font-medium text-foreground">Answer: </span>
                <span className="text-muted-foreground">{question.correct_answer}</span>
              </div>
            )}

            {question.explanation && (
              <div className="rounded-xl border bg-muted/20 p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Explanation</p>
                <p className="mt-2 text-sm text-foreground">{question.explanation}</p>
              </div>
            )}

            {question.rubric && (
              <div className="rounded-xl border bg-muted/20 p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Rubric</p>
                <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-sm text-foreground">
                  {JSON.stringify(question.rubric, null, 2)}
                </pre>
              </div>
            )}

            {question.warnings?.length > 0 && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-amber-800">
                  <AlertTriangle className="h-4 w-4" />
                  Verification warnings
                </div>
                <ul className="mt-2 space-y-1 text-sm text-amber-700">
                  {question.warnings.map((warning) => (
                    <li key={warning}>• {warning}</li>
                  ))}
                </ul>
              </div>
            )}

            {question.source_evidence && question.source_evidence.length > 0 && (
              <div className="rounded-xl border bg-muted/20 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Eye className="h-4 w-4" />
                  Source evidence
                </div>
                <div className="mt-3 space-y-2">
                  {question.source_evidence.map((evidence) => (
                    <div key={`${question.id}-${evidence.chunk_id}`} className="rounded-lg border bg-background p-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <Badge variant="outline">{evidence.chunk_id}</Badge>
                        {evidence.chapter_number ? <Badge variant="secondary">Chapter {evidence.chapter_number}</Badge> : null}
                        {evidence.page ? <Badge variant="outline">Page {evidence.page}</Badge> : null}
                        {evidence.parent_heading ? <Badge variant="outline">{evidence.parent_heading}</Badge> : null}
                      </div>
                      {evidence.text_preview && (
                        <p className="mt-2 text-sm text-foreground">{evidence.text_preview}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {question.scope_tags?.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {question.scope_tags.map((tag) => (
                  <Badge key={tag} variant="outline">
                    {tag}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
