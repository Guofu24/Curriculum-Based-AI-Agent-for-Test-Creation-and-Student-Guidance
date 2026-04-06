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
import type { Question, QuestionType, BloomLevel, QuestionDifficulty } from "@/lib/api"

interface QuestionEditorProps {
  question: Question
  index: number
  onUpdate: (question: Question) => void
  onDelete: () => void
  onDuplicate: () => void
}

const bloomLevelColors: Record<BloomLevel, string> = {
  nhan_biet: "bg-slate-500/20 text-slate-300 border-slate-500/30",
  thong_hieu: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  van_dung: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  van_dung_cao: "bg-amber-500/20 text-amber-300 border-amber-500/30",
}

const bloomLevelLabels: Record<BloomLevel, string> = {
  nhan_biet: "Nhận biết",
  thong_hieu: "Thông hiểu",
  van_dung: "Vận dụng",
  van_dung_cao: "Vận dụng cao",
}

const difficultyLabels: Record<QuestionDifficulty, string> = {
  easy: "Dễ",
  medium: "Trung bình",
  hard: "Khó",
}

const questionTypeLabels: Record<QuestionType, string> = {
  mcq: "Trắc nghiệm",
  essay: "Tự luận",
  // internal-only types for demo — backend không hỗ trợ
  multiple_choice: "Trắc nghiệm",
  true_false: "Đúng/Sai",
  fill_blank: "Điền khuyết",
}

export function QuestionEditor({
  question,
  index,
  onUpdate,
  onDelete,
  onDuplicate,
}: QuestionEditorProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editedQuestion, setEditedQuestion] = useState(question)

  const handleSave = () => {
    onUpdate(editedQuestion)
    setIsEditing(false)
  }

  const handleCancel = () => {
    setEditedQuestion(question)
    setIsEditing(false)
  }

  const updateOption = (optionIndex: number, value: string) => {
    if (!editedQuestion.options) return
    const newOptions = [...editedQuestion.options]
    newOptions[optionIndex] = value
    setEditedQuestion({ ...editedQuestion, options: newOptions })
  }

  const toggleCorrectAnswer = (optionIndex: number) => {
    if (!editedQuestion.options) return
    const option = editedQuestion.options[optionIndex]
    const currentCorrect = editedQuestion.correct_answer || []
    const correctArray = Array.isArray(currentCorrect) ? currentCorrect : [currentCorrect]
    
    if (correctArray.includes(option)) {
      setEditedQuestion({
        ...editedQuestion,
        correct_answer: correctArray.filter(a => a !== option),
      })
    } else {
      setEditedQuestion({
        ...editedQuestion,
        correct_answer: [...correctArray, option],
      })
    }
  }

  const addOption = () => {
    const newOptions = [...(editedQuestion.options || []), ""]
    setEditedQuestion({ ...editedQuestion, options: newOptions })
  }

  const removeOption = (optionIndex: number) => {
    if (!editedQuestion.options) return
    const newOptions = editedQuestion.options.filter((_, i) => i !== optionIndex)
    setEditedQuestion({ ...editedQuestion, options: newOptions })
  }

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
              <Badge variant="outline" className={bloomLevelColors[question.bloom_level]}>
                {bloomLevelLabels[question.bloom_level]}
              </Badge>
              <Badge variant="outline" className="bg-muted/50">
                {questionTypeLabels[question.type]}
              </Badge>
              <Badge variant="outline" className="bg-muted/50">
                {difficultyLabels[question.difficulty]}
              </Badge>
              <span className="text-sm text-muted-foreground ml-auto">
                {question.points} điểm
              </span>
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
        {(question.type === "multiple_choice" || question.type === "true_false") && (
          <div className="space-y-2 mb-4">
            {(isEditing ? editedQuestion.options : question.options)?.map((option, optionIndex) => {
              const correctArray = Array.isArray(question.correct_answer) 
                ? question.correct_answer 
                : [question.correct_answer]
              const isCorrect = correctArray.includes(option)
              
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
                          return arr.includes(option)
                        })()}
                        onCheckedChange={() => toggleCorrectAnswer(optionIndex)}
                      />
                      <Input
                        value={option}
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
                        {String.fromCharCode(65 + optionIndex)}
                      </span>
                      <span className="flex-1">{option}</span>
                      {isCorrect && (
                        <Check className="h-5 w-5 text-emerald-500" />
                      )}
                    </>
                  )}
                </div>
              )
            })}
            {isEditing && question.type === "multiple_choice" && (
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
                value={editedQuestion.bloom_level}
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
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Độ khó</label>
              <Select
                value={editedQuestion.difficulty}
                onValueChange={(value) => setEditedQuestion({ ...editedQuestion, difficulty: value as QuestionDifficulty })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(difficultyLabels).map(([value, label]) => (
                    <SelectItem key={value} value={value}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Điểm</label>
              <Input
                type="number"
                value={editedQuestion.points}
                onChange={(e) => setEditedQuestion({ ...editedQuestion, points: Number(e.target.value) })}
                min={0}
                step={0.5}
              />
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
