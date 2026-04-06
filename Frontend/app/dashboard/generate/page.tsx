"use client"

import { useEffect, useState, useCallback, useRef } from 'react'
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
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { FieldGroup, Field, FieldLabel, FieldDescription } from '@/components/ui/field'
import { Spinner } from '@/components/ui/spinner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  FileText,
  ChevronRight,
  ChevronLeft,
  Sparkles,
  Check,
  AlertCircle,
  AlertTriangle,
  BookOpen,
  Layers,
  Eye,
  RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'
import { 
  documentsApi, 
  generateApi,
  createExamWebSocket,
  Document, 
  CurriculumNode,
  ExamGenerationRequest,
  BloomLevel,
  WSEvent,
} from '@/lib/api'
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
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationEvents, setGenerationEvents] = useState<WSEvent[]>([])
  const [examId, setExamId] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [scopeWarning, setScopeWarning] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const eventsEndRef = useRef<HTMLDivElement>(null)

  // Fetch completed documents
  useEffect(() => {
    async function fetchDocuments() {
      try {
        const response = await documentsApi.list(1, 100)
        const completed = response.items.filter(
          doc => doc.processing_status === 'completed'
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

  // Auto-scroll events
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [generationEvents])

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

    setIsGenerating(true)
    setStep(3)
    setGenerationEvents([])
    setProgress(0)

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
        setScopeWarning(response.scope_warning)
        toast.warning(response.scope_warning)
      } else {
        setScopeWarning(null)
      }

      // Connect WebSocket
      wsRef.current = createExamWebSocket(
        response.exam_id,
        handleWSEvent,
        () => toast.error('Mất kết nối WebSocket'),
        () => console.log('WebSocket closed')
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Không thể bắt đầu tạo đề')
      setIsGenerating(false)
      setStep(2)
    }
  }

  const handleWSEvent = useCallback((event: WSEvent) => {
    setGenerationEvents(prev => [...prev, event])

    switch (event.type) {
      case 'plan_step':
        if (event.step && event.total_steps) {
          setProgress((event.step / event.total_steps) * 100)
        }
        break
      case 'question_generated':
        // Increment progress slightly
        setProgress(prev => Math.min(prev + 2, 95))
        break
      case 'completed':
        setProgress(100)
        setIsGenerating(false)
        toast.success('Đã tạo đề thi thành công!')
        wsRef.current?.close()
        break
      case 'error':
        setIsGenerating(false)
        toast.error(event.message || 'Có lỗi xảy ra')
        wsRef.current?.close()
        break
    }
  }, [])

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
                      {chapters.map((chapter) => (
                        <label
                          key={chapter.id}
                          className={cn(
                            "flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors",
                            config.scope.includes(chapter.title)
                              ? "border-primary bg-primary/5"
                              : "hover:bg-muted/50"
                          )}
                        >
                          <Checkbox
                            checked={config.scope.includes(chapter.title)}
                            onCheckedChange={() => toggleChapter(chapter.title)}
                          />
                          <span className="flex-1 truncate">{chapter.title}</span>
                          {chapter.chunk_count !== undefined && (
                            <Badge variant="secondary">
                              {chapter.chunk_count} chunks
                            </Badge>
                          )}
                        </label>
                      ))}
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
                        onValueChange={(v) => setConfig(prev => ({ ...prev, examType: v as ExamType }))}
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

          {/* Step 3: Generation Progress */}
          {step === 3 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {isGenerating ? (
                    <>
                      <Spinner />
                      Đang tạo đề thi...
                    </>
                  ) : progress === 100 ? (
                    <>
                      <Check className="h-5 w-5 text-primary" />
                      Hoàn thành!
                    </>
                  ) : (
                    <>
                      <AlertCircle className="h-5 w-5 text-destructive" />
                      Có lỗi xảy ra
                    </>
                  )}
                </CardTitle>
                <CardDescription>
                  {isGenerating 
                    ? "Vui lòng đợi trong khi AI đang sinh đề thi"
                    : progress === 100
                    ? "Đề thi đã được tạo thành công"
                    : "Quá trình tạo đề đã dừng"
                  }
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Progress Bar */}
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span>Tiến độ</span>
                    <span>{Math.round(progress)}%</span>
                  </div>
                  <Progress value={progress} className="h-2" />
                </div>

                {/* Events Log */}
                <div className="space-y-2">
                  <h4 className="font-medium text-sm">Nhật ký tạo đề</h4>
                  <ScrollArea className="h-[300px] rounded-lg border bg-muted/30 p-4">
                    <div className="space-y-2 font-mono text-sm">
                      {generationEvents.map((event, i) => (
                        <EventLogItem key={i} event={event} />
                      ))}
                      <div ref={eventsEndRef} />
                    </div>
                  </ScrollArea>
                </div>

                {/* Actions */}
                <div className="flex justify-between">
                  <Button
                    variant="outline"
                    onClick={() => {
                      setStep(2)
                      setIsGenerating(false)
                      setGenerationEvents([])
                      wsRef.current?.close()
                    }}
                    disabled={isGenerating}
                  >
                    <RefreshCw className="mr-2 h-4 w-4" />
                    Tạo đề mới
                  </Button>
                  
                  {examId && progress === 100 && (
                    <>
                      {scopeWarning && (
                        <Alert variant="warning" className="mb-4">
                          <AlertTriangle className="h-4 w-4" />
                          <AlertTitle>Cảnh báo phạm vi</AlertTitle>
                          <AlertDescription>
                            {scopeWarning}. Một số nội dung có thể bị giới hạn token.
                          </AlertDescription>
                        </Alert>
                      )}
                      <Button onClick={() => router.push(`/dashboard/exams/${examId}`)}>
                        <Eye className="mr-2 h-4 w-4" />
                        Xem đề
                      </Button>
                    </>
                  )}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </main>
    </>
  )
}

function EventLogItem({ event }: { event: WSEvent }) {
  const getEventDisplay = () => {
    switch (event.type) {
      case 'plan_step':
        return {
          icon: '📋',
          text: `Bước ${event.step}/${event.total_steps}: ${event.message}`,
          color: 'text-blue-500'
        }
      case 'question_generated':
        return {
          icon: '✅',
          text: `Đã sinh câu hỏi ${event.question_id}`,
          color: 'text-emerald-500'
        }
      case 'validation_result':
        return {
          icon: event.passed ? '✓' : '⚠',
          text: event.passed 
            ? `Kiểm tra đạt: ${event.issues_count} vấn đề` 
            : `Cần xem lại: ${event.issues_count} vấn đề`,
          color: event.passed ? 'text-emerald-500' : 'text-amber-500'
        }
      case 'hitl_checkpoint':
        return {
          icon: '⏸',
          text: `Checkpoint HITL #${event.checkpoint_id}`,
          color: 'text-purple-500'
        }
      case 'completed':
        return {
          icon: '🎉',
          text: `Hoàn thành! Chi phí: $${event.total_cost_usd?.toFixed(4) || '0.00'}`,
          color: 'text-primary'
        }
      case 'error':
        return {
          icon: '❌',
          text: `Lỗi: ${event.message}`,
          color: 'text-destructive'
        }
      default:
        return {
          icon: '•',
          text: JSON.stringify(event),
          color: 'text-muted-foreground'
        }
    }
  }

  const { icon, text, color } = getEventDisplay()

  return (
    <div className={cn("flex items-start gap-2", color)}>
      <span>{icon}</span>
      <span>{text}</span>
    </div>
  )
}
