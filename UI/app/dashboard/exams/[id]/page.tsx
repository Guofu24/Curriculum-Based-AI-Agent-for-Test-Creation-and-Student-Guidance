"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { DashboardHeader } from "@/components/dashboard-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  AlertTriangle,
  Check,
  Eye,
  FileText,
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
} from "lucide-react";
import {
  exams as examsApi,
  generation as generationApi,
  type Exam,
  type MCQOption,
  type Question,
} from "@/lib/api";

type EditState = {
  questionId: string;
  content: string;
  options: MCQOption[];
  correctAnswer: string;
  bloomLevel: string;
};

type RegenerateState = {
  type: "single" | "from" | "all";
  questionId?: string;
  questionNumber?: number;
} | null;

const BLOOM_LEVELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"];
const DEFAULT_OPTION_LABELS = ["A", "B", "C", "D"];

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
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

function getEditableOptions(question: Question): MCQOption[] {
  const indexed = new Map<string, string>();
  for (const option of question.options || []) {
    if (!option?.label) continue;
    indexed.set(option.label.toUpperCase(), option.text || "");
  }

  return DEFAULT_OPTION_LABELS.map((label) => ({
    label,
    text: indexed.get(label) || "",
  }));
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
  const [filterBloom, setFilterBloom] = useState("all");

  useEffect(() => {
    if (!examId) return;
    examsApi
      .get(examId)
      .then((result) => {
        setExam(result);
        setSelectedVersionId(result.current_version?.id || result.versions?.[result.versions.length - 1]?.id || "");
      })
      .catch((loadError: unknown) => {
        setError(loadError instanceof Error ? loadError.message : "Không tải được đề thi");
      })
      .finally(() => setLoading(false));
  }, [examId]);

  const activeVersion = useActiveVersion(exam, selectedVersionId);
  const questions = activeVersion?.questions || exam?.questions || [];

  const filteredQuestions = questions.filter((question) => {
    if (filterBloom !== "all" && question.bloom_level !== filterBloom) return false;
    return true;
  });

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
      setError(actionError instanceof Error ? actionError.message : "Thao tác thất bại");
    } finally {
      if (questionId) setSavingQuestionId(null);
    }
  };

  const handleStartEdit = (question: Question) => {
    setEditState({
      questionId: question.id,
      content: question.content,
      options: getEditableOptions(question),
      correctAnswer: question.correct_answer || "A",
      bloomLevel: question.bloom_level,
    });
  };

  const handleSaveEdit = async () => {
    if (!exam || !editState) return;

    const normalizedOptions = editState.options.map((option, index) => ({
      label: DEFAULT_OPTION_LABELS[index],
      text: option.text.trim(),
    }));

    const missingOption = normalizedOptions.find((option) => !option.text);
    if (missingOption) {
      setError("Mỗi câu hỏi phải có đủ 4 phương án A-D.");
      return;
    }

    if (!DEFAULT_OPTION_LABELS.includes(editState.correctAnswer)) {
      setError("Đáp án đúng phải là một trong các lựa chọn A-D.");
      return;
    }

    await applyAndRefresh(
      () =>
        generationApi.partialRegenerate({
          exam_id: exam.id,
          edits: [
            {
              question_ids: [editState.questionId],
              edit_type: "edit_text",
              new_content: editState.content.trim(),
            },
            {
              question_ids: [editState.questionId],
              edit_type: "edit_options",
              new_options: normalizedOptions,
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

    const edit =
      regenerateState.type === "single"
        ? {
            question_ids: regenerateState.questionId ? [regenerateState.questionId] : [],
            edit_type: "regenerate" as const,
            edit_prompt: regeneratePrompt.trim() || undefined,
          }
        : regenerateState.type === "from"
          ? {
              question_ids: [],
              range_start: regenerateState.questionNumber,
              range_end: questions.length,
              edit_type: "regenerate" as const,
              edit_prompt: regeneratePrompt.trim() || undefined,
            }
          : {
              question_ids: [],
              edit_type: "regenerate" as const,
              edit_prompt: regeneratePrompt.trim() || undefined,
            };

    await applyAndRefresh(
      () =>
        generationApi.partialRegenerate({
          exam_id: exam.id,
          edits: [edit],
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
      setError(publishError instanceof Error ? publishError.message : "Publish thất bại");
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return (
      <>
        <DashboardHeader title="Review đề thi" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </>
    );
  }

  if (!exam) {
    return (
      <>
        <DashboardHeader title="Review đề thi" />
        <div className="flex flex-1 items-center justify-center">
          <p className="text-muted-foreground">Không tìm thấy đề thi</p>
        </div>
      </>
    );
  }

  return (
    <>
      <DashboardHeader title="Review đề thi" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        {error && (
          <div className="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">{exam.title}</h2>
              <Badge variant="secondary" className="capitalize">
                {exam.status}
              </Badge>
              {exam.published_at ? <Badge>Đã publish</Badge> : null}
            </div>
            <p className="text-sm text-muted-foreground">
              {exam.total_questions} câu trắc nghiệm một đáp án đúng · tạo lúc {formatDate(exam.created_at)}
              {exam.updated_at ? ` · cập nhật ${formatDate(exam.updated_at)}` : ""}
            </p>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">Vật lý</Badge>
              <Badge variant="outline">Tiếng Việt</Badge>
              <Badge variant="outline">PDF scoped generation</Badge>
              <Badge variant="outline">{exam.strict_scope_flag ? "Strict scope" : "Non-strict scope"}</Badge>
            </div>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            {(exam.versions?.length || 0) > 0 ? (
              <div className="min-w-56">
                <Select value={selectedVersionId} onValueChange={setSelectedVersionId}>
                  <SelectTrigger className="h-10">
                    <SelectValue placeholder="Chọn version" />
                  </SelectTrigger>
                  <SelectContent>
                    {(exam.versions || []).map((version) => (
                      <SelectItem key={version.id} value={version.id}>
                        Phiên bản {version.version_number} · {version.status}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}

            <Button variant="outline" onClick={() => setRegenerateState({ type: "all" })}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Regenerate toàn bộ
            </Button>

            <Button onClick={handlePublish} disabled={publishing || !!exam.published_at}>
              {publishing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              {exam.published_at ? "Đã publish" : "Publish review"}
            </Button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          <SummaryCard
            title="Version hiện tại"
            value={activeVersion ? `v${activeVersion.version_number}` : "N/A"}
            note={activeVersion?.change_summary || "Bản review đang mở"}
            icon={Layers}
          />
          <SummaryCard
            title="Blueprint cells"
            value={String(Array.isArray(exam.blueprint?.cells) ? exam.blueprint.cells.length : 0)}
            note="Phân bổ câu theo chapter/lesson/topic"
            icon={FileText}
          />
          <SummaryCard
            title="Đã verify"
            value={`${questions.filter((question) => question.is_validated).length}/${questions.length}`}
            note="Câu đã qua basic verifier"
            icon={ShieldCheck}
          />
          <SummaryCard
            title="Cảnh báo"
            value={String(questions.reduce((sum, question) => sum + (question.warnings?.length || 0), 0))}
            note="Cần xem lại trước khi publish"
            icon={AlertTriangle}
          />
        </div>

        {exam.selected_scope && exam.selected_scope.length > 0 ? (
          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="pb-4">
              <CardTitle className="text-base">Scope đã chọn</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {exam.selected_scope.map((scope, index) => (
                <Badge key={`${String(scope.scope_id || scope.section_id || index)}`} variant="outline">
                  {String(scope.title || scope.scope_id || scope.section_id || `Scope ${index + 1}`)}
                </Badge>
              ))}
            </CardContent>
          </Card>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Select value={filterBloom} onValueChange={setFilterBloom}>
            <SelectTrigger className="h-9 w-48 text-sm">
              <SelectValue placeholder="Lọc theo Bloom" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả Bloom level</SelectItem>
              {BLOOM_LEVELS.map((level) => (
                <SelectItem key={level} value={level} className="capitalize">
                  {level}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {filterBloom !== "all" ? (
            <Button variant="ghost" size="sm" onClick={() => setFilterBloom("all")}>
              Bỏ lọc
            </Button>
          ) : null}
          <Badge variant="outline" className="text-xs">
            {filteredQuestions.length}/{questions.length} câu
          </Badge>
        </div>

        <div className="space-y-4">
          {filteredQuestions.map((question) => (
            <QuestionCard
              key={question.id}
              question={question}
              isEditing={editState?.questionId === question.id}
              saving={savingQuestionId === question.id}
              editState={editState}
              onStartEdit={() => handleStartEdit(question)}
              onEditChange={(next) => setEditState((current) => (current ? { ...current, ...next } : current))}
              onOptionChange={(index, text) =>
                setEditState((current) => {
                  if (!current) return current;
                  const options = current.options.map((option, optionIndex) =>
                    optionIndex === index ? { ...option, text } : option,
                  );
                  return { ...current, options };
                })
              }
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

        <Dialog open={!!regenerateState} onOpenChange={(open) => {
          if (!open) {
            setRegenerateState(null);
            setRegeneratePrompt("");
          }
        }}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>
                {regenerateState?.type === "single"
                  ? `Regenerate câu ${regenerateState.questionNumber}`
                  : regenerateState?.type === "from"
                    ? `Regenerate từ câu ${regenerateState.questionNumber}`
                    : "Regenerate toàn bộ đề"}
              </DialogTitle>
              <DialogDescription>
                Hệ thống sẽ giữ scope hiện tại, truy hồi lại evidence trong scope và tạo version mới trước khi review tiếp.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <Label htmlFor="regenerate-prompt">Prompt hiệu chỉnh tùy chọn</Label>
              <Textarea
                id="regenerate-prompt"
                value={regeneratePrompt}
                onChange={(event) => setRegeneratePrompt(event.target.value)}
                placeholder="Ví dụ: giữ nguyên scope nhưng làm câu ngắn hơn và tăng nhẹ độ phân hóa."
                className="min-h-28"
              />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => {
                setRegenerateState(null);
                setRegeneratePrompt("");
              }}>
                Hủy
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
  onOptionChange,
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
  onOptionChange: (index: number, text: string) => void;
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
              <Badge variant="secondary">Câu {question.question_number}</Badge>
              <Badge variant="outline">MCQ 1 đáp án</Badge>
              <Badge variant="outline" className="capitalize">
                {question.bloom_level}
              </Badge>
              {question.verification_status ? (
                <Badge variant={question.verification_status === "passed" ? "secondary" : "outline"}>
                  {question.verification_status}
                </Badge>
              ) : null}
              {question.is_locked ? (
                <Badge>
                  <Lock className="mr-1 h-3 w-3" />
                  Locked
                </Badge>
              ) : null}
              {question.is_human_edited ? (
                <Badge variant="outline">
                  <Pencil className="mr-1 h-3 w-3" />
                  Đã sửa tay
                </Badge>
              ) : null}
            </div>
            {question.blueprint_cell_key ? (
              <p className="text-xs text-muted-foreground">Blueprint cell: {question.blueprint_cell_key}</p>
            ) : null}
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
                Sửa câu hỏi và đáp án
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onRegenerate("single")}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Regenerate câu này
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onRegenerate("from")}>
                <Sparkles className="mr-2 h-4 w-4" />
                Regenerate từ đây trở đi
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onLockToggle}>
                {question.is_locked ? (
                  <>
                    <Unlock className="mr-2 h-4 w-4" />
                    Unlock câu hỏi
                  </>
                ) : (
                  <>
                    <Lock className="mr-2 h-4 w-4" />
                    Lock câu hỏi
                  </>
                )}
              </DropdownMenuItem>
              <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={onDelete}>
                <Trash2 className="mr-2 h-4 w-4" />
                Xóa câu hỏi
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {isEditing && editState ? (
          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label>Nội dung câu hỏi</Label>
              <Textarea
                value={editState.content}
                onChange={(event) => onEditChange({ content: event.target.value })}
                className="min-h-28"
              />
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              {editState.options.map((option, index) => (
                <div key={`${question.id}-${option.label}`} className="space-y-2">
                  <Label>Phương án {option.label}</Label>
                  <Input value={option.text} onChange={(event) => onOptionChange(index, event.target.value)} />
                </div>
              ))}
            </div>

            <div className="grid gap-4 md:grid-cols-[220px_220px]">
              <div className="space-y-2">
                <Label>Đáp án đúng</Label>
                <Select value={editState.correctAnswer} onValueChange={(value) => onEditChange({ correctAnswer: value })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DEFAULT_OPTION_LABELS.map((label) => (
                      <SelectItem key={label} value={label}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Bloom level</Label>
                <Select value={editState.bloomLevel} onValueChange={(value) => onEditChange({ bloomLevel: value })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BLOOM_LEVELS.map((level) => (
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
                Hủy
              </Button>
              <Button onClick={onSaveEdit} disabled={saving}>
                {saving ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Check className="mr-2 h-4 w-4" />
                )}
                Lưu thành version mới
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-4 space-y-4">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{question.content}</p>

            <div className="space-y-2">
              {(question.options || []).map((option) => (
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
                  {option.label === question.correct_answer ? <Check className="h-4 w-4 shrink-0" /> : null}
                </div>
              ))}
            </div>

            {question.explanation ? (
              <div className="rounded-xl border bg-muted/20 p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Giải thích</p>
                <p className="mt-2 text-sm text-foreground">{question.explanation}</p>
              </div>
            ) : null}

            {question.warnings?.length > 0 ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-amber-800">
                  <AlertTriangle className="h-4 w-4" />
                  Cảnh báo từ verifier
                </div>
                <ul className="mt-2 space-y-1 text-sm text-amber-700">
                  {question.warnings.map((warning) => (
                    <li key={warning}>- {warning}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {question.source_evidence && question.source_evidence.length > 0 ? (
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
                        {evidence.document_id ? <Badge variant="outline">Doc {evidence.document_id}</Badge> : null}
                        {evidence.section_id ? <Badge variant="outline">Section {evidence.section_id}</Badge> : null}
                        {evidence.chapter_number ? <Badge variant="secondary">Chương {evidence.chapter_number}</Badge> : null}
                        {evidence.page ? <Badge variant="outline">Trang {evidence.page}</Badge> : null}
                        {evidence.parent_heading ? <Badge variant="outline">{evidence.parent_heading}</Badge> : null}
                      </div>
                      {evidence.text_preview ? (
                        <p className="mt-2 text-sm text-foreground">{evidence.text_preview}</p>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
                Câu hỏi này chưa có source evidence hợp lệ.
              </div>
            )}

            {question.scope_tags?.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {question.scope_tags.map((tag) => (
                  <Badge key={tag} variant="outline">
                    {tag}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
