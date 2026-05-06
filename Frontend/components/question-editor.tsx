"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import {
  GripVertical,
  Trash2,
  Plus,
  Check,
  X
} from "lucide-react"
import type { Question, QuestionType, BloomLevel } from "@/lib/api"

interface QuestionEditorProps {
  question: Question
  index: number
  onUpdate: (question: Question) => void
  onDelete: () => void
  onDuplicate: () => void
}

const bloomLevelColors: Record<string, string> = {
  nhan_biet: "bg-slate-500/20 text-slate-300 border-slate-500/30",
  thong_hieu: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  van_dung: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  van_dung_cao: "bg-amber-500/20 text-amber-300 border-amber-500/30",
}

const bloomLevelLabels: Record<string, string> = {
  nhan_biet: "Nhận biết",
  thong_hieu: "Thông hiểu",
  van_dung: "Vận dụng",
  van_dung_cao: "Vận dụng cao",
}

const questionTypeLabels: Record<string, string> = {
  mcq: "Trắc nghiệm",
  essay: "Tự luận",
  multiple_choice: "Trắc nghiệm",
  true_false: "Đúng/Sai",
  fill_blank: "Điền khuyết",
  dung_sai: "Đúng-Sai (THPT)",
  short_answer: "Trả lời ngắn",
}

export function QuestionEditor({
  question,
  index,
  onUpdate,
  onDelete,
  onDuplicate,
}: QuestionEditorProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editedQuestion, setEditedQuestion] = useState<Question>(question)

  const handleSave = () => {
    onUpdate(editedQuestion)
    setIsEditing(false)
  }

  const handleCancel = () => {
    setEditedQuestion(question)
    setIsEditing(false)
  }

  const getOptions = (q: Question): Array<{ label: string; text: string }> => {
    return q.options ?? []
  }

  const updateOption = (optionIndex: number, value: string) => {
    const opts = getOptions(editedQuestion)
    const newOptions = [...opts]
    newOptions[optionIndex] = { label: opts[optionIndex]?.label ?? String(optionIndex), text: value }
    setEditedQuestion({ ...editedQuestion, options: newOptions })
  }

  const toggleCorrectAnswer = (optionIndex: number) => {
    const opts = getOptions(editedQuestion)
    const option = opts[optionIndex]
    if (!option) return
    const currentCorrect = editedQuestion.correct_answer || ''
    const currentStr = Array.isArray(currentCorrect) ? currentCorrect[0] ?? '' : currentCorrect
    const optionLabel = option.label

    if (currentStr === optionLabel) {
      setEditedQuestion({
        ...editedQuestion,
        correct_answer: '',
      })
    } else {
      setEditedQuestion({
        ...editedQuestion,
        correct_answer: optionLabel,
      })
    }
  }

  const addOption = () => {
    const opts = getOptions(editedQuestion)
    const newLabel = String.fromCharCode(65 + opts.length)
    setEditedQuestion({
      ...editedQuestion,
      options: [...opts, { label: newLabel, text: "" }],
    })
  }

  const removeOption = (optionIndex: number) => {
    const opts = getOptions(editedQuestion)
    const newOptions = opts.filter((_, i) => i !== optionIndex)
    setEditedQuestion({ ...editedQuestion, options: newOptions })
  }

  const safeBloomLevel = typeof question.bloom_level === 'string' ? question.bloom_level : 'thong_hieu'
  const safeQuestionType = typeof question.type === 'string' ? question.type : 'mcq'

  return (
    <Card className="border-border/50 bg-card/50 backdrop-blur-sm">
      <CardHeader className="pb-3">
        <div className="flex items-start gap-3">
          <div className="flex items-center gap-2 pt-1">
            <GripVertical className="h-5 w-5 text-muted-foreground cursor-grab" />
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-sm font-medium text-primary">
              {index + 1}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-2">
              <Badge variant="outline" className={bloomLevelColors[safeBloomLevel] ?? ''}>
                {bloomLevelLabels[safeBloomLevel] ?? safeBloomLevel}
              </Badge>
              <Badge variant="outline" className="bg-muted/50">
                {questionTypeLabels[safeQuestionType] ?? safeQuestionType}
              </Badge>
            </div>
            {isEditing ? (
              <Textarea
                value={editedQuestion.content}
                onChange={(e) => setEditedQuestion({ ...editedQuestion, content: e.target.value })}
                className="min-h-[80px] bg-background"
              />
            ) : (
              <CardTitle className="text-base font-normal leading-relaxed">
                {question.content}
              </CardTitle>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {/* Options for multiple choice */}
        {(safeQuestionType === 'mcq' || safeQuestionType === 'multiple_choice') && (
          <div className="space-y-2 mb-4">
            {(isEditing ? getOptions(editedQuestion) : getOptions(question)).map((option, optionIndex) => {
              const correctArray = Array.isArray(question.correct_answer)
                ? question.correct_answer
                : question.correct_answer ? [question.correct_answer] : []
              const isCorrect = correctArray.includes(option.label)

              return (
                <div
                  key={optionIndex}
                  className={`flex items-center gap-3 rounded-lg border p-3 transition-colors ${
                    isCorrect
                      ? "border-emerald-500/50 bg-emerald-500/10"
                      : "border-border/50 bg-muted/30"
                  }`}
                >
                  {isEditing ? (
                    <>
                      <Checkbox
                        checked={(() => {
                          const ca = editedQuestion.correct_answer || []
                          const arr = Array.isArray(ca) ? ca : [ca]
                          return arr.includes(option.label)
                        })()}
                        onCheckedChange={() => toggleCorrectAnswer(optionIndex)}
                      />
                      <Input
                        value={option.text}
                        onChange={(e) => updateOption(optionIndex, e.target.value)}
                        className="flex-1 bg-background"
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-destructive hover:text-destructive"
                        onClick={() => removeOption(optionIndex)}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </>
                  ) : (
                    <>
                      <span className="flex h-6 w-6 items-center justify-center rounded-full border text-xs font-medium">
                        {option.label}
                      </span>
                      <span className="flex-1">{option.text}</span>
                      {isCorrect && (
                        <Check className="h-5 w-5 text-emerald-500" />
                      )}
                    </>
                  )}
                </div>
              )
            })}
            {isEditing && (
              <Button
                variant="outline"
                size="sm"
                onClick={addOption}
                className="w-full border-dashed"
              >
                <Plus className="h-4 w-4 mr-2" />
                Thêm đáp án
              </Button>
            )}
          </div>
        )}

        {/* Đúng-Sai propositions */}
        {safeQuestionType === 'dung_sai' && question.propositions && (
          <div className="space-y-2 mb-4">
            {question.propositions.map((prop) => (
              <div
                key={prop.label}
                className={`flex items-start gap-3 rounded-lg border p-3 ${
                  prop.is_correct
                    ? "border-emerald-500/50 bg-emerald-500/10"
                    : "border-red-500/40 bg-red-500/10"
                }`}
              >
                <span className="font-semibold text-sm w-4 shrink-0">{prop.label})</span>
                <span className="flex-1 text-sm">{prop.text}</span>
                <span className={`text-xs font-medium shrink-0 ${prop.is_correct ? "text-emerald-400" : "text-red-400"}`}>
                  {prop.is_correct ? "Đúng" : "Sai"}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Short Answer */}
        {safeQuestionType === 'short_answer' && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 mb-4">
            <p className="text-sm">
              <span className="font-medium text-amber-300">Đáp án: </span>
              <span className="font-mono">{question.correct_answer ?? "—"}</span>
              {question.unit && <span className="ml-1 text-muted-foreground">{question.unit}</span>}
            </p>
            {question.solution && (
              <p className="text-sm text-muted-foreground mt-1 whitespace-pre-line">{question.solution}</p>
            )}
          </div>
        )}

        {/* Explanation */}
        {question.explanation && (
          <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3 mb-4">
            <p className="text-sm text-blue-200">
              <span className="font-medium">Giải thích:</span> {question.explanation}
            </p>
          </div>
        )}

        {/* Metadata editing */}
        {isEditing && (
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Mức Bloom</label>
              <Select
                value={editedQuestion.bloom_level ?? 'thong_hieu'}
                onValueChange={(value) => setEditedQuestion({ ...editedQuestion, bloom_level: value as BloomLevel })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(bloomLevelLabels).map(([value, label]) => (
                    <SelectItem key={value} value={value}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2 pt-2 border-t border-border/50">
          {isEditing ? (
            <>
              <Button size="sm" onClick={handleSave}>
                <Check className="h-4 w-4 mr-1" />
                Lưu
              </Button>
              <Button size="sm" variant="outline" onClick={handleCancel}>
                Hủy
              </Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="outline" onClick={() => setIsEditing(true)}>
                Chỉnh sửa
              </Button>
              <Button size="sm" variant="outline" onClick={onDuplicate}>
                Nhân bản
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="text-destructive hover:text-destructive ml-auto"
                onClick={onDelete}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
