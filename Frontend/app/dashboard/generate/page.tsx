"use client"

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Slider } from '@/components/ui/slider'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Label } from '@/components/ui/label'
import { FieldGroup, Field, FieldLabel, FieldDescription } from '@/components/ui/field'
import {
  FileText,
  ChevronRight,
  ChevronLeft,
  Sparkles,
  Check,
  AlertCircle,
  BookOpen,
  Layers,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  documentsApi,
  generateApi,
  examsApi,
  Document,
  CurriculumNode,
  ExamGenerationRequest,
  BloomLevel,
} from '@/lib/api'
import { GenerationLiveViewer } from '@/components/generation-live-viewer'
import { cn } from '@/lib/utils'

type ExamType = 'mcq' | 'essay' | 'mixed'

interface GenerationConfig {
  documentId: string
  scope: string[]
  examType: ExamType
  mcqCount: number
  essayCount: number
  bloomDistribution: Record<BloomLevel, number>
  userPrompt: string
  strictScope: boolean
  title: string
}

const defaultConfig: GenerationConfig = {
  documentId: '',
  scope: [],
  examType: 'mixed',
  mcqCount: 10,
  essayCount: 2,
  bloomDistribution: {
    nhan_biet: 20,
    thong_hieu: 30,
    van_dung: 30,
    van_dung_cao: 20,
  },
  userPrompt: '',
  strictScope: true,
  title: '',
}

const BLOOM_LABELS: Record<BloomLevel, string> = {
  nhan_biet: 'Nhận biết',
  thong_hieu: 'Thông hiểu',
  van_dung: 'Vận dụng',
  van_dung_cao: 'Vận dụng cao',
}

export default function GeneratePage() {
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [config, setConfig] = useState<GenerationConfig>(defaultConfig)
  const [documents, setDocuments] = useState<Document[]>([])
  const [curriculum, setCurriculum] = useState<CurriculumNode[]>([])
  const [isLoadingDocs, setIsLoadingDocs] = useState(true)
  const [isLoadingCurriculum, setIsLoadingCurriculum] = useState(false)
  const [examId, setExamId] = useState<string | null>(null)
  const [wsUrl, setWsUrl] = useState<string | null>(null)

  // Fetch completed documents
  useEffect(() => {
    async function fetchDocuments() {
      try {
        const response = await documentsApi.list(1, 100)
        // Accept both 'completed' (parsing done) and 'indexed' (fully processed with embeddings)
        const completed = response.items.filter(
          doc => doc.processing_status === 'completed' || doc.processing_status === 'indexed'
        )
        setDocuments(completed)
      } catch (error) {
        console.error('Failed to fetch documents:', error)
      } finally {
        setIsLoadingDocs(false)
      }
    }
    fetchDocuments()
  }, [])

  // Fetch curriculum when document is selected
  useEffect(() => {
    if (!config.documentId) return

    async function fetchCurriculum() {
      setIsLoadingCurriculum(true)
      try {
        const nodes = await documentsApi.getCurriculumTree(config.documentId)
        setCurriculum(nodes)
        // Select all chapters by default
        const chapters = nodes.filter(n => n.level === 1).map(n => n.title)
        setConfig(prev => ({ ...prev, scope: chapters }))
      } catch (error) {
        console.error('Failed to fetch curriculum:', error)
      } finally {
        setIsLoadingCurriculum(false)
      }
    }
    fetchCurriculum()
  }, [config.documentId])

  const handleSelectDocument = (docId: string) => {
    setConfig(prev => ({ ...prev, documentId: docId, scope: [] }))
  }

  const toggleChapter = (chapter: string) => {
    setConfig(prev => {
      const newScope = prev.scope.includes(chapter)
        ? prev.scope.filter(c => c !== chapter)
        : [...prev.scope, chapter]
      return { ...prev, scope: newScope }
    })
  }

  const handleBloomChange = (level: BloomLevel, value: number) => {
    setConfig(prev => ({
      ...prev,
      bloomDistribution: { ...prev.bloomDistribution, [level]: value }
    }))
  }

  const bloomSum = Object.values(config.bloomDistribution).reduce((a, b) => a + b, 0)
  const isBloomValid = bloomSum === 100

  const canProceedStep1 = config.documentId !== ''
  const canProceedStep2 = 
    config.scope.length > 0 &&
    (config.mcqCount > 0 || config.essayCount > 0) &&
    isBloomValid

  const handleStartGeneration = async () => {
    if (!canProceedStep2) return

    try {
      const request: ExamGenerationRequest = {
        document_id: config.documentId,
        scope: config.scope,
        exam_type: config.examType,
        mcq_count: config.mcqCount,
        essay_count: config.essayCount,
        bloom_distribution: config.bloomDistribution,
        user_prompt: config.userPrompt || undefined,
        strict_scope_flag: config.strictScope,
        title: config.title || undefined,
      }

      const response = await generateApi.startGeneration(request)
      setExamId(response.exam_id)

      if (response.scope_warning) {
        toast.warning(response.scope_warning)
      }

      // Use websocket_url from API response — backend resolves the correct host/port
      // so WebSocket connects properly even when backend is on a different port.
      setWsUrl(response.websocket_url || `/ws/exam/${response.exam_id}`)
      setStep(3)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Không thể bắt đầu tạo đề')
    }
  }

  const handleApprove = useCallback(async (
    id: string,
    approved: boolean,
    feedback?: string,
    checkpointId?: number,
  ) => {
    const cp = checkpointId ?? 1
    try {
      if (cp === 2) {
        await examsApi.submitReview(id, { approved, feedback })
      } else {
        if (approved) {
          await examsApi.approveBlueprint(id)
        } else {
          await examsApi.rejectBlueprint(id, feedback || 'Yêu cầu điều chỉnh.')
        }
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Có lỗi xảy ra khi xác nhận')
    }
  }, [])

  const handleExamTypeChange = (v: ExamType) => {
    setConfig(prev => ({
      ...prev,
      examType: v,
      ...(v === 'mcq' ? { essayCount: 0 } : {}),
      ...(v === 'essay' ? { mcqCount: 0 } : {}),
    }))
  }

  const handleExamComplete = useCallback((id: string) => {
    router.push(`/dashboard/exams/${id}`)
  }, [router])

  const selectedDoc = documents.find(d => d.id === config.documentId)
  const chapters = curriculum.filter(n => n.level === 1)

  return (
    <>
      <DashboardHeader breadcrumbs={[{ label: 'Tạo đề' }]} />
      
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Header */}
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Tạo đề thi mới</h1>
            <p className="text-muted-foreground">
              Sinh đề thi tự động từ tài liệu giảng dạy
            </p>
          </div>

          {/* Step Indicator */}
          <div className="flex items-center gap-2">
            {[1, 2, 3].map((s) => (
              <div key={s} className="flex items-center gap-2">
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium transition-colors",
                    step >= s
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground"
                  )}
                >
                  {step > s ? <Check className="h-4 w-4" /> : s}
                </div>
                <span className={cn(
                  "text-sm hidden sm:inline",
                  step >= s ? "text-foreground" : "text-muted-foreground"
                )}>
                  {s === 1 && "Chọn tài liệu"}
                  {s === 2 && "Cấu hình đề"}
                  {s === 3 && "Tạo đề"}
                </span>
                {s < 3 && <ChevronRight className="h-4 w-4 text-muted-foreground" />}
              </div>
            ))}
          </div>

          {/* Step 1: Select Document */}
          {step === 1 && (
            <Card>
              <CardHeader>
                <CardTitle>Chọn tài liệu</CardTitle>
                <CardDescription>
                  Chọn tài liệu đã xử lý để sinh đề thi
                </CardDescription>
              </CardHeader>
              <CardContent>
                {isLoadingDocs ? (
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {[...Array(6)].map((_, i) => (
                      <Skeleton key={i} className="h-32" />
                    ))}
                  </div>
                ) : documents.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center">
                    <FileText className="h-12 w-12 text-muted-foreground/50 mb-4" />
                    <p className="text-lg font-medium">Chưa có tài liệu nào</p>
                    <p className="text-muted-foreground mb-4">
                      Upload và xử lý tài liệu trước khi tạo đề
                    </p>
                    <Button onClick={() => router.push('/dashboard/documents')}>
                      Đến trang tài liệu
                    </Button>
                  </div>
                ) : (
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {documents.map((doc) => (
                      <Card
                        key={doc.id}
                        className={cn(
                          "cursor-pointer transition-all hover:border-primary/50",
                          config.documentId === doc.id && "border-primary ring-1 ring-primary"
                        )}
                        onClick={() => handleSelectDocument(doc.id)}
                      >
                        <CardContent className="pt-6">
                          <div className="flex items-start gap-3">
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                              <FileText className="h-5 w-5 text-primary" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className="font-medium truncate">
                                {doc.original_filename}
                              </p>
                              <div className="flex items-center gap-2 mt-1 text-sm text-muted-foreground">
                                <BookOpen className="h-3 w-3" />
                                <span>{doc.total_chapters || 0} chương</span>
                                <Layers className="h-3 w-3 ml-2" />
                                <span>{doc.total_chunks || 0} chunks</span>
                              </div>
                            </div>
                            {config.documentId === doc.id && (
                              <Check className="h-5 w-5 text-primary shrink-0" />
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}

                <div className="flex justify-end mt-6">
                  <Button
                    onClick={() => setStep(2)}
                    disabled={!canProceedStep1}
                  >
                    Tiếp theo
                    <ChevronRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Step 2: Configure Exam */}
          {step === 2 && (
            <div className="grid gap-6 lg:grid-cols-2">
              {/* Left: Scope Selection */}
              <Card>
                <CardHeader>
                  <CardTitle>Phạm vi đề thi</CardTitle>
                  <CardDescription>
                    Chọn các chương sẽ được sử dụng
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {selectedDoc && (
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50 mb-4">
                      <FileText className="h-5 w-5 text-primary" />
                      <span className="font-medium truncate">
                        {selectedDoc.original_filename}
                      </span>
                    </div>
                  )}

                  {isLoadingCurriculum ? (
                    <div className="space-y-2">
                      {[...Array(5)].map((_, i) => (
                        <Skeleton key={i} className="h-10" />
                      ))}
                    </div>
                  ) : chapters.length === 0 ? (
                    <div className="text-center py-8 text-muted-foreground">
                      Không có chương nào
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {chapters.map((chapter) => {
                        const sections = curriculum.filter(
                          n => n.level === 2 && n.parent_id === chapter.id
                        )
                        const isChapterSelected = config.scope.includes(chapter.title)
                        const selectedSections = sections.filter(s =>
                          config.scope.includes(s.title)
                        )
                        const isExpanded = isChapterSelected || selectedSections.length > 0

                        return (
                          <div key={chapter.id} className="rounded-lg border overflow-hidden">
                            {/* Chapter header */}
                            <label
                              className={cn(
                                "flex items-center gap-3 p-3 cursor-pointer transition-colors",
                                isChapterSelected
                                  ? "border-primary bg-primary/5"
                                  : "hover:bg-muted/50"
                              )}
                            >
                              <Checkbox
                                checked={isChapterSelected}
                                onCheckedChange={() => {
                                  if (isChapterSelected) {
                                    // Deselect chapter + all its sections
                                    const sectionTitles = sections.map(s => s.title)
                                    setConfig(prev => ({
                                      ...prev,
                                      scope: prev.scope.filter(
                                        t => t !== chapter.title && !sectionTitles.includes(t)
                                      ),
                                    }))
                                  } else {
                                    toggleChapter(chapter.title)
                                  }
                                }}
                              />
                              <BookOpen className="h-4 w-4 text-primary shrink-0" />
                              <span className="flex-1 font-medium truncate">
                                {chapter.title}
                              </span>
                              {sections.length > 0 && (
                                <Badge variant="outline" className="text-xs">
                                  {sections.length} mục
                                </Badge>
                              )}
                              {chapter.chunk_count !== undefined && (
                                <Badge variant="secondary">
                                  {chapter.chunk_count} chunks
                                </Badge>
                              )}
                            </label>

                            {/* Sections dropdown — visible when chapter selected */}
                            {isExpanded && sections.length > 0 && (
                              <div className="border-t bg-muted/20 px-3 py-2 space-y-1">
                                <p className="text-xs text-muted-foreground mb-1 pl-7">
                                  Chọn mục cụ thể (không chọn = dùng cả chương):
                                </p>
                                {sections.map((sec) => {
                                  const isSecSelected = config.scope.includes(sec.title)
                                  return (
                                    <label
                                      key={sec.id}
                                      className={cn(
                                        "flex items-center gap-2 p-2 pl-7 rounded cursor-pointer transition-colors text-sm",
                                        isSecSelected
                                          ? "bg-primary/10 text-foreground"
                                          : "hover:bg-muted/50 text-muted-foreground"
                                      )}
                                    >
                                      <Checkbox
                                        checked={isSecSelected}
                                        onCheckedChange={() => {
                                          setConfig(prev => {
                                            const newScope = prev.scope.includes(sec.title)
                                              ? prev.scope.filter(t => t !== sec.title)
                                              : [...prev.scope, sec.title]
                                            return { ...prev, scope: newScope }
                                          })
                                        }}
                                      />
                                      <FileText className="h-3 w-3 shrink-0" />
                                      <span className="flex-1 truncate">{sec.title}</span>
                                    </label>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Right: Exam Config */}
              <Card>
                <CardHeader>
                  <CardTitle>Cấu hình đề thi</CardTitle>
                  <CardDescription>
                    Thiết lập số câu hỏi và phân bố Bloom
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  {/* Title */}
                  <FieldGroup>
                    <Field>
                      <FieldLabel>Tiêu đề đề thi (tùy chọn)</FieldLabel>
                      <Input
                        placeholder="Ví dụ: Đề kiểm tra Vật lý Chương 1-2"
                        value={config.title}
                        onChange={(e) => setConfig(prev => ({ ...prev, title: e.target.value }))}
                      />
                    </Field>
                  </FieldGroup>

                  {/* Exam Type */}
                  <FieldGroup>
                    <Field>
                      <FieldLabel>Loại đề thi</FieldLabel>
                      <RadioGroup
                        value={config.examType}
                        onValueChange={handleExamTypeChange}
                        className="flex flex-wrap gap-4"
                      >
                        <div className="flex items-center gap-2">
                          <RadioGroupItem value="mcq" id="mcq" />
                          <Label htmlFor="mcq">Chỉ trắc nghiệm</Label>
                        </div>
                        <div className="flex items-center gap-2">
                          <RadioGroupItem value="essay" id="essay" />
                          <Label htmlFor="essay">Chỉ tự luận</Label>
                        </div>
                        <div className="flex items-center gap-2">
                          <RadioGroupItem value="mixed" id="mixed" />
                          <Label htmlFor="mixed">Kết hợp</Label>
                        </div>
                      </RadioGroup>
                    </Field>
                  </FieldGroup>

                  {/* Question Counts */}
                  <div className="grid gap-4 sm:grid-cols-2">
                    {(config.examType === 'mcq' || config.examType === 'mixed') && (
                      <Field>
                        <FieldLabel>Số câu trắc nghiệm</FieldLabel>
                        <Input
                          type="number"
                          min={1}
                          max={50}
                          value={config.mcqCount}
                          onChange={(e) => setConfig(prev => ({ ...prev, mcqCount: parseInt(e.target.value) || 0 }))}
                        />
                      </Field>
                    )}
                    {(config.examType === 'essay' || config.examType === 'mixed') && (
                      <Field>
                        <FieldLabel>Số câu tự luận</FieldLabel>
                        <Input
                          type="number"
                          min={0}
                          max={10}
                          value={config.essayCount}
                          onChange={(e) => setConfig(prev => ({ ...prev, essayCount: parseInt(e.target.value) || 0 }))}
                        />
                      </Field>
                    )}
                  </div>

                  {/* Bloom Distribution */}
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <FieldLabel>Phân bố Bloom Taxonomy</FieldLabel>
                      <Badge variant={isBloomValid ? "default" : "destructive"}>
                        Tổng: {bloomSum}%
                      </Badge>
                    </div>
                    {(Object.keys(config.bloomDistribution) as BloomLevel[]).map((level) => (
                      <div key={level} className="space-y-2">
                        <div className="flex items-center justify-between text-sm">
                          <span>{BLOOM_LABELS[level]}</span>
                          <span className="font-medium">{config.bloomDistribution[level]}%</span>
                        </div>
                        <Slider
                          value={[config.bloomDistribution[level]]}
                          onValueChange={([value]) => handleBloomChange(level, value)}
                          max={100}
                          step={5}
                          className="cursor-pointer"
                        />
                      </div>
                    ))}
                    {!isBloomValid && (
                      <p className="text-sm text-destructive flex items-center gap-1">
                        <AlertCircle className="h-4 w-4" />
                        Tổng phần trăm phải bằng 100%
                      </p>
                    )}
                  </div>

                  {/* Strict Scope */}
                  <div className="flex items-center gap-3">
                    <Checkbox
                      id="strictScope"
                      checked={config.strictScope}
                      onCheckedChange={(checked) => 
                        setConfig(prev => ({ ...prev, strictScope: !!checked }))
                      }
                    />
                    <Label htmlFor="strictScope" className="cursor-pointer">
                      Chỉ dùng nội dung trong phạm vi đã chọn
                    </Label>
                  </div>

                  {/* User Prompt */}
                  <Field>
                    <FieldLabel>Hướng dẫn thêm cho AI (tùy chọn)</FieldLabel>
                    <Textarea
                      placeholder="Ví dụ: Tập trung vào bài tập tính toán, tránh lý thuyết thuần túy..."
                      value={config.userPrompt}
                      onChange={(e) => setConfig(prev => ({ ...prev, userPrompt: e.target.value }))}
                      maxLength={500}
                      rows={3}
                    />
                    <FieldDescription>
                      {config.userPrompt.length}/500 ký tự
                    </FieldDescription>
                  </Field>
                </CardContent>
              </Card>

              {/* Navigation */}
              <div className="lg:col-span-2 flex justify-between">
                <Button variant="outline" onClick={() => setStep(1)}>
                  <ChevronLeft className="mr-2 h-4 w-4" />
                  Quay lại
                </Button>
                <Button onClick={handleStartGeneration} disabled={!canProceedStep2}>
                  <Sparkles className="mr-2 h-4 w-4" />
                  Tạo đề
                </Button>
              </div>
            </div>
          )}

          {/* Step 3: Generation Live Viewer */}
          {step === 3 && examId && (
            <GenerationLiveViewer
              examId={examId}
              wsUrl={wsUrl || `/ws/exam/${examId}`}
              examType={config.examType}
              onApprove={handleApprove}
              onComplete={handleExamComplete}
            />
          )}
        </div>
      </main>
    </>
  )
}
