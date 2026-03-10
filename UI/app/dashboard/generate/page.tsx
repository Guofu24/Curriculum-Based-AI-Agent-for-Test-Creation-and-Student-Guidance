"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Checkbox } from "@/components/ui/checkbox"
import { Switch } from "@/components/ui/switch"
import { Slider } from "@/components/ui/slider"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  BookOpen,
  Sparkles,
  Wand2,
  Info,
  Loader2,
  ChevronRight,
  GraduationCap,
  Brain,
  ShieldCheck,
  Sliders,
  FileText,
  Hash,
} from "lucide-react"
import { GenerationStepper } from "@/components/generation-stepper"
import {
  textbooks as textbooksApi,
  generation as generationApi,
  type TextbookListItem,
  type Exam,
  type ExamGenerationRequest,
  type GenerationStep,
} from "@/lib/api"

const bloomLevels = [
  "Remember",
  "Understand",
  "Apply",
  "Analyze",
  "Evaluate",
  "Create",
]

export default function GenerateExamPage() {
  const router = useRouter()
  const [books, setBooks] = useState<TextbookListItem[]>([])
  const [loadingBooks, setLoadingBooks] = useState(true)
  const [selectedTextbook, setSelectedTextbook] = useState("")
  const [selectedChapters, setSelectedChapters] = useState<number[]>([])
  const [prompt, setPrompt] = useState("")
  const [questionType, setQuestionType] = useState("mixed")
  const [mcqCounts, setMcqCounts] = useState({ easy: 5, medium: 3, hard: 2 })
  const [essayCounts, setEssayCounts] = useState({ easy: 1, medium: 2, hard: 1 })
  const [examCount, setExamCount] = useState(1)
  const [gradualDifficulty, setGradualDifficulty] = useState(false)
  const [noHallucination, setNoHallucination] = useState(true)
  const [appliedQuestions, setAppliedQuestions] = useState(true)
  const [gradeLevelScope, setGradeLevelScope] = useState(true)
  const [creativityLevel, setCreativityLevel] = useState([30])
  const [bloomLevel, setBloomLevel] = useState("Apply")
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationSteps, setGenerationSteps] = useState<GenerationStep[]>([])
  const [generationError, setGenerationError] = useState("")
  const [generatedExamId, setGeneratedExamId] = useState<string | null>(null)

  // Fetch textbooks
  useEffect(() => {
    textbooksApi.list().then((list) => {
      setBooks(list.filter((b) => b.status.toLowerCase() === "processed"))
    }).catch(() => {}).finally(() => setLoadingBooks(false))
  }, [])

  const currentTextbook = books.find((t) => t.id === selectedTextbook)
  const chapterCount = currentTextbook?.chapter_count || 0

  const toggleChapter = (ch: number) => {
    setSelectedChapters((prev) =>
      prev.includes(ch) ? prev.filter((c) => c !== ch) : [...prev, ch]
    )
  }

  const selectAllChapters = () => {
    if (selectedChapters.length === chapterCount) {
      setSelectedChapters([])
    } else {
      setSelectedChapters(Array.from({ length: chapterCount }, (_, i) => i + 1))
    }
  }

  const totalMcq = mcqCounts.easy + mcqCounts.medium + mcqCounts.hard
  const totalEssay = essayCounts.easy + essayCounts.medium + essayCounts.hard
  const totalQuestions = questionType === "mcq" ? totalMcq : questionType === "essay" ? totalEssay : totalMcq + totalEssay

  const updateCount = (
    setter: React.Dispatch<React.SetStateAction<{ easy: number; medium: number; hard: number }>>,
    level: "easy" | "medium" | "hard",
    delta: number
  ) => {
    setter((prev) => ({
      ...prev,
      [level]: Math.max(0, Math.min(50, prev[level] + delta)),
    }))
  }

  const handleGenerate = () => {
    if (!selectedTextbook || totalQuestions === 0) return
    if (chapterCount > 0 && selectedChapters.length === 0) return
    setIsGenerating(true)
    setGenerationError("")
    setGeneratedExamId(null)

    const reqData: ExamGenerationRequest = {
      textbook_id: selectedTextbook,
      chapters: chapterCount > 0 ? selectedChapters : [],
      prompt: prompt || (chapterCount > 0
        ? `Generate exam for chapters ${selectedChapters.join(", ")}`
        : `Generate exam covering the entire textbook`),
      exam_type: questionType,
      difficulty: "custom",
      question_distribution: {
        mcq: questionType === "essay" ? { easy: 0, medium: 0, hard: 0 } : mcqCounts,
        essay: questionType === "mcq" ? { easy: 0, medium: 0, hard: 0 } : essayCounts,
      },
      num_variants: examCount,
      gradually_increasing: gradualDifficulty,
      constraints: {
        strict_grounding: noHallucination,
        allow_applied_questions: appliedQuestions,
        grade_level_scope: gradeLevelScope ? "undergraduate" : undefined,
        creativity_level: creativityLevel[0] / 100,
        bloom_levels: [bloomLevel.toLowerCase()],
      },
    }

    generationApi.generateStream(
      reqData,
      (step) => setGenerationSteps((prev) => {
        const idx = prev.findIndex((s) => s.step === step.step)
        if (idx >= 0) {
          const copy = [...prev]
          copy[idx] = step
          return copy
        }
        return [...prev, step]
      }),
      (exam) => {
        setGeneratedExamId(exam.id)
      },
      (error) => {
        setGenerationError(error)
      },
    )
  }

  const handleGenerationComplete = useCallback(() => {
    if (generatedExamId) {
      router.push(`/dashboard/exams/${generatedExamId}`)
    } else {
      // fallback if stream sent exam_id in step message
      const finalStep = generationSteps.find(
        (s) => s.step === 5 && s.status === "completed" && s.message,
      )
      if (finalStep?.message) {
        router.push(`/dashboard/exams/${finalStep.message}`)
      } else {
        router.push("/dashboard/history")
      }
    }
  }, [generatedExamId, generationSteps, router])

  if (isGenerating) {
    return (
      <>
        <DashboardHeader title="Generate Exam" />
        {generationError ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="max-w-md text-center">
              <p className="text-destructive font-medium mb-2">Generation Failed</p>
              <p className="text-sm text-muted-foreground mb-4">{generationError}</p>
              <Button onClick={() => { setIsGenerating(false); setGenerationError(""); }}>
                Try Again
              </Button>
            </div>
          </div>
        ) : (
          <GenerationStepper
            steps={generationSteps}
            onComplete={handleGenerationComplete}
          />
        )}
      </>
    )
  }

  return (
    <>
      <DashboardHeader title="Generate Exam" />
      <div className="flex flex-1 flex-col gap-6 p-6 max-w-4xl">
        {/* Page Header */}
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Configure Your Exam
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Select a textbook, configure parameters, and let AI generate a professional exam.
          </p>
        </div>

        {/* Section 1: Textbook Selection */}
        <Card className="rounded-2xl shadow-sm">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <BookOpen className="h-4 w-4 text-primary" />
              Textbook Selection
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <Label className="text-sm font-medium">Select Textbook</Label>
              <Select value={selectedTextbook} onValueChange={(val) => {
                setSelectedTextbook(val)
                setSelectedChapters([])
              }}>
                <SelectTrigger className="h-11">
                  <SelectValue placeholder={loadingBooks ? "Loading textbooks..." : "Choose a textbook from your library"} />
                </SelectTrigger>
                <SelectContent>
                  {books.map((book) => (
                    <SelectItem key={book.id} value={book.id}>
                      <div className="flex items-center gap-2">
                        <BookOpen className="h-3.5 w-3.5 text-muted-foreground" />
                        {book.title}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {currentTextbook && chapterCount > 0 && (
              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium">Select Chapters</Label>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={selectAllChapters}
                  >
                    {selectedChapters.length === chapterCount
                      ? "Deselect all"
                      : "Select all chapters"}
                  </Button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {Array.from({ length: chapterCount }, (_, i) => i + 1).map(
                    (ch) => (
                      <button
                        key={ch}
                        onClick={() => toggleChapter(ch)}
                        className={`flex h-9 w-9 items-center justify-center rounded-lg border text-sm font-medium transition-colors ${
                          selectedChapters.includes(ch)
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-card text-foreground hover:border-primary/40 hover:bg-muted/50"
                        }`}
                      >
                        {ch}
                      </button>
                    )
                  )}
                </div>
                {selectedChapters.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {selectedChapters.length} of {chapterCount} chapters selected
                  </p>
                )}
              </div>
            )}

            {currentTextbook && chapterCount === 0 && (
              <div className="rounded-xl border border-dashed border-primary/30 bg-primary/5 p-4">
                <p className="text-sm font-medium text-foreground">
                  No chapters detected
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  The entire textbook content will be used for exam generation.
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Section 2: Exam Configuration */}
        <Card className="rounded-2xl shadow-sm">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Sliders className="h-4 w-4 text-primary" />
              Exam Configuration
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            {/* Prompt Input */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">
                  <div className="flex items-center gap-1.5">
                    <Wand2 className="h-3.5 w-3.5 text-primary" />
                    AI Prompt
                  </div>
                </Label>
                <Badge variant="outline" className="text-xs gap-1">
                  <Sparkles className="h-3 w-3" />
                  AI-assisted
                </Badge>
              </div>
              <Textarea
                placeholder="Generate an exam for Chapter 1 including theory and applied questions. Focus on core data structures like arrays, linked lists, and stacks..."
                className="min-h-28 resize-none"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Describe the type of exam you want. Be specific about topics and question style.
              </p>
            </div>

            {/* Question Type Selection */}
            <div className="flex flex-col gap-3">
              <Label className="text-sm font-medium">
                <div className="flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5 text-primary" />
                  Question Type
                </div>
              </Label>
              <div className="flex flex-wrap gap-2">
                {[
                  { id: "mcq", label: "Multiple Choice" },
                  { id: "essay", label: "Essay" },
                  { id: "mixed", label: "Mixed" },
                ].map((type) => (
                  <button
                    key={type.id}
                    onClick={() => setQuestionType(type.id)}
                    className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                      questionType === type.id
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-card text-foreground hover:border-primary/40"
                    }`}
                  >
                    {type.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Question Distribution by Difficulty */}
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">
                  <div className="flex items-center gap-1.5">
                    <GraduationCap className="h-3.5 w-3.5 text-primary" />
                    Question Distribution
                  </div>
                </Label>
                <div className="flex items-center gap-2">
                  <Label
                    htmlFor="gradual"
                    className="text-xs text-muted-foreground cursor-pointer"
                  >
                    Gradually increasing
                  </Label>
                  <Switch
                    id="gradual"
                    checked={gradualDifficulty}
                    onCheckedChange={setGradualDifficulty}
                  />
                </div>
              </div>

              {/* Distribution Table */}
              <div className="rounded-xl border overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/40">
                      <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Difficulty</th>
                      {(questionType === "mcq" || questionType === "mixed") && (
                        <th className="px-4 py-2.5 text-center font-medium text-muted-foreground">
                          MCQ
                        </th>
                      )}
                      {(questionType === "essay" || questionType === "mixed") && (
                        <th className="px-4 py-2.5 text-center font-medium text-muted-foreground">
                          Essay
                        </th>
                      )}
                      <th className="px-4 py-2.5 text-center font-medium text-muted-foreground">Subtotal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(["easy", "medium", "hard"] as const).map((level, idx) => {
                      const labelMap = { easy: "Easy", medium: "Medium", hard: "Hard" }
                      const colorMap = {
                        easy: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
                        medium: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
                        hard: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
                      }
                      const rowMcq = mcqCounts[level]
                      const rowEssay = essayCounts[level]
                      const subtotal =
                        questionType === "mcq"
                          ? rowMcq
                          : questionType === "essay"
                          ? rowEssay
                          : rowMcq + rowEssay

                      return (
                        <tr
                          key={level}
                          className={idx < 2 ? "border-b" : ""}
                        >
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${colorMap[level]}`}>
                              {labelMap[level]}
                            </span>
                          </td>
                          {(questionType === "mcq" || questionType === "mixed") && (
                            <td className="px-4 py-3">
                              <div className="flex items-center justify-center gap-1.5">
                                <button
                                  onClick={() => updateCount(setMcqCounts, level, -1)}
                                  disabled={mcqCounts[level] <= 0}
                                  className="flex h-7 w-7 items-center justify-center rounded-md border text-sm font-medium transition-colors hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                  -
                                </button>
                                <span className="w-8 text-center font-medium tabular-nums">
                                  {rowMcq}
                                </span>
                                <button
                                  onClick={() => updateCount(setMcqCounts, level, 1)}
                                  className="flex h-7 w-7 items-center justify-center rounded-md border text-sm font-medium transition-colors hover:bg-muted"
                                >
                                  +
                                </button>
                              </div>
                            </td>
                          )}
                          {(questionType === "essay" || questionType === "mixed") && (
                            <td className="px-4 py-3">
                              <div className="flex items-center justify-center gap-1.5">
                                <button
                                  onClick={() => updateCount(setEssayCounts, level, -1)}
                                  disabled={essayCounts[level] <= 0}
                                  className="flex h-7 w-7 items-center justify-center rounded-md border text-sm font-medium transition-colors hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                  -
                                </button>
                                <span className="w-8 text-center font-medium tabular-nums">
                                  {rowEssay}
                                </span>
                                <button
                                  onClick={() => updateCount(setEssayCounts, level, 1)}
                                  className="flex h-7 w-7 items-center justify-center rounded-md border text-sm font-medium transition-colors hover:bg-muted"
                                >
                                  +
                                </button>
                              </div>
                            </td>
                          )}
                          <td className="px-4 py-3 text-center font-semibold tabular-nums text-foreground">
                            {subtotal}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                  <tfoot>
                    <tr className="border-t bg-muted/30">
                      <td className="px-4 py-2.5 font-medium text-foreground">Total</td>
                      {(questionType === "mcq" || questionType === "mixed") && (
                        <td className="px-4 py-2.5 text-center font-semibold text-primary tabular-nums">
                          {totalMcq}
                        </td>
                      )}
                      {(questionType === "essay" || questionType === "mixed") && (
                        <td className="px-4 py-2.5 text-center font-semibold text-primary tabular-nums">
                          {totalEssay}
                        </td>
                      )}
                      <td className="px-4 py-2.5 text-center font-bold text-primary tabular-nums">
                        {totalQuestions}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>

              {totalQuestions === 0 && (
                <p className="text-xs text-destructive">
                  Please add at least one question.
                </p>
              )}
            </div>

            {/* Number of Exams */}
            <div className="flex flex-col gap-2">
              <Label className="text-sm font-medium">
                <div className="flex items-center gap-1.5">
                  <Hash className="h-3.5 w-3.5 text-primary" />
                  Number of Exam Variants
                </div>
              </Label>
              <div className="flex items-center gap-3">
                <Button
                  variant="outline"
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  onClick={() => setExamCount(Math.max(1, examCount - 1))}
                  disabled={examCount <= 1}
                >
                  -
                </Button>
                <Input
                  type="number"
                  min={1}
                  max={10}
                  value={examCount}
                  onChange={(e) =>
                    setExamCount(
                      Math.max(1, Math.min(10, parseInt(e.target.value) || 1))
                    )
                  }
                  className="h-9 w-20 text-center"
                />
                <Button
                  variant="outline"
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  onClick={() => setExamCount(Math.min(10, examCount + 1))}
                  disabled={examCount >= 10}
                >
                  +
                </Button>
                <span className="text-xs text-muted-foreground">
                  Max 10 variants
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Section 3: Advanced Constraints */}
        <Card className="rounded-2xl shadow-sm">
          <Accordion type="single" collapsible>
            <AccordionItem value="constraints" className="border-none">
              <CardHeader className="pb-0">
                <AccordionTrigger className="hover:no-underline py-0">
                  <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                    Advanced Constraints
                  </CardTitle>
                </AccordionTrigger>
              </CardHeader>
              <AccordionContent>
                <CardContent className="flex flex-col gap-6 pt-4">
                  {/* Toggle Constraints */}
                  <TooltipProvider>
                    <div className="flex flex-col gap-4">
                      <ConstraintToggle
                        label="Strictly use textbook knowledge only"
                        description="Prevents AI from generating questions beyond the textbook content"
                        checked={noHallucination}
                        onCheckedChange={setNoHallucination}
                        tooltip="Ensures zero hallucination - all questions and answers are strictly derived from the uploaded textbook material."
                      />
                      <ConstraintToggle
                        label="Allow applied questions based on textbook"
                        description="Questions can be applied but must reference textbook concepts"
                        checked={appliedQuestions}
                        onCheckedChange={setAppliedQuestions}
                        tooltip="Allows real-world application questions that are grounded in the textbook's theoretical frameworks."
                      />
                      <ConstraintToggle
                        label="Enforce grade-level scope"
                        description="Knowledge must not exceed the defined academic level"
                        checked={gradeLevelScope}
                        onCheckedChange={setGradeLevelScope}
                        tooltip="Ensures question complexity aligns with the target academic level, preventing overly advanced content."
                      />
                    </div>
                  </TooltipProvider>

                  {/* Creativity Level */}
                  <div className="flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <Label className="text-sm font-medium">
                        <div className="flex items-center gap-1.5">
                          <Brain className="h-3.5 w-3.5 text-primary" />
                          Creativity Level
                        </div>
                      </Label>
                      <span className="text-sm font-medium text-primary">
                        {creativityLevel[0]}%
                      </span>
                    </div>
                    <Slider
                      value={creativityLevel}
                      onValueChange={setCreativityLevel}
                      max={100}
                      step={5}
                      className="w-full"
                    />
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>Conservative</span>
                      <span>Creative</span>
                    </div>
                  </div>

                  {/* Bloom Taxonomy */}
                  <div className="flex flex-col gap-2">
                    <Label className="text-sm font-medium">
                      <div className="flex items-center gap-1.5">
                        <GraduationCap className="h-3.5 w-3.5 text-primary" />
                        {"Bloom's Taxonomy Level"}
                      </div>
                    </Label>
                    <Select value={bloomLevel} onValueChange={setBloomLevel}>
                      <SelectTrigger className="h-10">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {bloomLevels.map((level) => (
                          <SelectItem key={level} value={level}>
                            {level}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {"Sets the cognitive complexity target based on Bloom's revised taxonomy."}
                    </p>
                  </div>
                </CardContent>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </Card>

        {/* Generate Button */}
        <div className="flex items-center justify-end gap-3 pb-6">
          <Button variant="outline" size="lg" onClick={() => router.push("/dashboard")}>
            Cancel
          </Button>
          <Button
            size="lg"
            className="px-8"
            onClick={handleGenerate}
            disabled={!selectedTextbook || (chapterCount > 0 && selectedChapters.length === 0) || totalQuestions === 0}
          >
            <Sparkles className="mr-2 h-4 w-4" />
            Generate Exam
            <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        </div>
      </div>
    </>
  )
}

function ConstraintToggle({
  label,
  description,
  checked,
  onCheckedChange,
  tooltip,
}: {
  label: string
  description: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  tooltip: string
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-xl border p-4">
      <div className="flex items-start gap-3 min-w-0">
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-medium text-foreground">{label}</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help shrink-0" />
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs">
                <p className="text-xs">{tooltip}</p>
              </TooltipContent>
            </Tooltip>
          </div>
          <span className="text-xs text-muted-foreground">{description}</span>
        </div>
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} className="shrink-0" />
    </div>
  )
}
