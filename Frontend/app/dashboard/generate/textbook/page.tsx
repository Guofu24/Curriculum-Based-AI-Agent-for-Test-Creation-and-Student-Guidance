"use client"

import { useCallback, useState } from 'react'
import { useRouter } from 'next/navigation'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Slider } from '@/components/ui/slider'
import { Badge } from '@/components/ui/badge'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Label } from '@/components/ui/label'
import { FieldGroup, Field, FieldLabel, FieldDescription } from '@/components/ui/field'
import {
  BookOpen,
  ChevronRight,
  ChevronLeft,
  Sparkles,
  Check,
  AlertCircle,
  Info,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  generateApi,
  examsApi,
  ExamGenerationRequest,
  BloomLevel,
} from '@/lib/api'
import { GenerationLiveViewer } from '@/components/generation-live-viewer'
import { cn } from '@/lib/utils'

type ExamType = 'mcq' | 'essay' | 'mixed'
type ExamMode = 'standard' | 'thpt_2025'

// Hard-coded Vật lí 12 chapters — update when textbook is crawled
const LY12_CHAPTERS = [
  {
    id: 'ch1',
    title: 'Chương 1: Dao động cơ học',
    topics: ['Dao động điều hòa', 'Con lắc lò xo', 'Con lắc đơn', 'Dao động tắt dần – Cộng hưởng'],
  },
  {
    id: 'ch2',
    title: 'Chương 2: Sóng cơ học và sóng âm',
    topics: ['Sóng cơ học', 'Sóng âm', 'Giao thoa sóng', 'Sóng dừng'],
  },
  {
    id: 'ch3',
    title: 'Chương 3: Điện xoay chiều',
    topics: ['Đại cương điện xoay chiều', 'Mạch R–L–C nối tiếp', 'Công suất điện xoay chiều', 'Máy biến áp – Truyền tải điện năng'],
  },
  {
    id: 'ch4',
    title: 'Chương 4: Dao động và sóng điện từ',
    topics: ['Mạch dao động LC', 'Điện từ trường', 'Sóng điện từ', 'Thông tin liên lạc bằng sóng vô tuyến'],
  },
  {
    id: 'ch5',
    title: 'Chương 5: Sóng ánh sáng',
    topics: ['Tán sắc ánh sáng', 'Giao thoa ánh sáng', 'Màu sắc ánh sáng – Quang phổ'],
  },
  {
    id: 'ch6',
    title: 'Chương 6: Lượng tử ánh sáng',
    topics: ['Hiện tượng quang điện', 'Thuyết lượng tử ánh sáng', 'Mẫu nguyên tử Bohr', 'Tia X'],
  },
  {
    id: 'ch7',
    title: 'Chương 7: Hạt nhân nguyên tử',
    topics: ['Cấu tạo hạt nhân', 'Năng lượng liên kết hạt nhân', 'Phóng xạ', 'Phản ứng hạt nhân', 'Phân hạch và nhiệt hạch'],
  },
]

interface TextbookConfig {
  selectedChapterIds: Set<string>
  examMode: ExamMode
  examType: ExamType
  mcqCount: number
  essayCount: number
  dungSaiCount: number
  shortAnswerCount: number
  bloomDistribution: Record<BloomLevel, number>
  userPrompt: string
  title: string
}

const defaultConfig: TextbookConfig = {
  selectedChapterIds: new Set(),
  examMode: 'standard',
  examType: 'mixed',
  mcqCount: 10,
  essayCount: 2,
  dungSaiCount: 0,
  shortAnswerCount: 0,
  bloomDistribution: { nhan_biet: 20, thong_hieu: 30, van_dung: 30, van_dung_cao: 20 },
  userPrompt: '',
  title: '',
}

const THPT_2025_CONFIG = {
  mcqCount: 18,
  dungSaiCount: 4,
  shortAnswerCount: 6,
  essayCount: 0,
  bloomDistribution: { nhan_biet: 40, thong_hieu: 30, van_dung: 20, van_dung_cao: 10 } as Record<BloomLevel, number>,
}

const BLOOM_LABELS: Record<BloomLevel, string> = {
  nhan_biet: 'Nhận biết',
  thong_hieu: 'Thông hiểu',
  van_dung: 'Vận dụng',
  van_dung_cao: 'Vận dụng cao',
}

export default function TextbookGeneratePage() {
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [config, setConfig] = useState<TextbookConfig>(defaultConfig)
  const [examId, setExamId] = useState<string | null>(null)
  const [wsUrl, setWsUrl] = useState<string | null>(null)

  const toggleChapter = (id: string) => {
    setConfig(prev => {
      const next = new Set(prev.selectedChapterIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { ...prev, selectedChapterIds: next }
    })
  }

  const selectAll = () => {
    setConfig(prev => ({ ...prev, selectedChapterIds: new Set(LY12_CHAPTERS.map(c => c.id)) }))
  }

  const deselectAll = () => {
    setConfig(prev => ({ ...prev, selectedChapterIds: new Set() }))
  }

  const handleBloomChange = (level: BloomLevel, value: number) => {
    setConfig(prev => ({ ...prev, bloomDistribution: { ...prev.bloomDistribution, [level]: value } }))
  }

  const bloomSum = Object.values(config.bloomDistribution).reduce((a, b) => a + b, 0)
  const isBloomValid = bloomSum === 100
  const totalQuestions = config.mcqCount + config.essayCount + config.dungSaiCount + config.shortAnswerCount
  const canProceedStep1 = config.selectedChapterIds.size > 0
  const canProceedStep2 = totalQuestions > 0 && isBloomValid

  const getScope = (): string[] =>
    LY12_CHAPTERS
      .filter(c => config.selectedChapterIds.has(c.id))
      .map(c => c.title)

  const handleStartGeneration = async () => {
    if (!canProceedStep2) return

    try {
      const request: ExamGenerationRequest = {
        document_id: null,
        use_builtin_knowledge: true,
        scope: getScope(),
        exam_mode: config.examMode,
        exam_type: config.examType,
        mcq_count: config.mcqCount,
        essay_count: config.essayCount,
        dung_sai_count: config.dungSaiCount,
        short_answer_count: config.shortAnswerCount,
        bloom_distribution: config.bloomDistribution,
        user_prompt: config.userPrompt || undefined,
        title: config.title || undefined,
      }

      const response = await generateApi.startGeneration(request)
      setExamId(response.exam_id)

      if (response.scope_warning) {
        toast.warning(response.scope_warning)
      }

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

  const handleExamComplete = useCallback((id: string) => {
    router.push(`/dashboard/exams/${id}`)
  }, [router])

  const allSelected = LY12_CHAPTERS.every(c => config.selectedChapterIds.has(c.id))

  return (
    <>
      <DashboardHeader breadcrumbs={[{ label: 'Tạo đề' }, { label: 'Vật lí 12' }]} />

      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Header */}
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-amber-500/10 text-amber-500">
              <BookOpen className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Sinh đề từ SGK Vật lí 12</h1>
              <p className="text-muted-foreground">
                Kiến thức được xây sẵn từ sách giáo khoa — không cần upload tài liệu
              </p>
            </div>
          </div>

          {/* Knowledge source banner */}
          <div className="flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
            <Info className="h-4 w-4 text-amber-500 shrink-0" />
            <p className="text-sm text-amber-200">
              Nguồn kiến thức: <span className="font-medium">SGK Vật lí 12 – Chương trình GDPT 2018</span>.
              Hệ thống sẽ truy xuất nội dung từ namespace đã được index sẵn.
            </p>
          </div>

          {/* Step Indicator */}
          <div className="flex items-center gap-2">
            {[1, 2, 3].map((s) => (
              <div key={s} className="flex items-center gap-2">
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium transition-colors",
                    step >= s ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                  )}
                >
                  {step > s ? <Check className="h-4 w-4" /> : s}
                </div>
                <span className={cn("text-sm hidden sm:inline", step >= s ? "text-foreground" : "text-muted-foreground")}>
                  {s === 1 && "Chọn chương"}
                  {s === 2 && "Cấu hình đề"}
                  {s === 3 && "Tạo đề"}
                </span>
                {s < 3 && <ChevronRight className="h-4 w-4 text-muted-foreground" />}
              </div>
            ))}
          </div>

          {/* Step 1: Chapter selection */}
          {step === 1 && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <div>
                  <CardTitle>Chọn chương</CardTitle>
                  <CardDescription>Chọn các chương để sinh câu hỏi từ đó</CardDescription>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={allSelected ? deselectAll : selectAll}
                  className="text-muted-foreground"
                >
                  {allSelected ? 'Bỏ chọn tất cả' : 'Chọn tất cả'}
                </Button>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {LY12_CHAPTERS.map((chapter) => {
                    const isSelected = config.selectedChapterIds.has(chapter.id)
                    return (
                      <div
                        key={chapter.id}
                        className={cn(
                          "rounded-lg border p-4 cursor-pointer transition-colors",
                          isSelected ? "border-primary bg-primary/5" : "border-border/50 hover:bg-muted/30"
                        )}
                        onClick={() => toggleChapter(chapter.id)}
                      >
                        <div className="flex items-start gap-3">
                          <Checkbox
                            checked={isSelected}
                            onCheckedChange={() => toggleChapter(chapter.id)}
                            onClick={e => e.stopPropagation()}
                            className="mt-0.5 shrink-0"
                          />
                          <div className="min-w-0 flex-1">
                            <p className={cn("font-medium text-sm", isSelected && "text-primary")}>
                              {chapter.title}
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                              {chapter.topics.join(' · ')}
                            </p>
                          </div>
                          {isSelected && <Check className="h-4 w-4 text-primary shrink-0 mt-0.5" />}
                        </div>
                      </div>
                    )
                  })}
                </div>

                <div className="flex justify-between items-center mt-6">
                  <span className="text-sm text-muted-foreground">
                    {config.selectedChapterIds.size > 0
                      ? `Đã chọn ${config.selectedChapterIds.size} chương`
                      : 'Chưa chọn chương nào'}
                  </span>
                  <Button onClick={() => setStep(2)} disabled={!canProceedStep1}>
                    Tiếp theo
                    <ChevronRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Step 2: Exam config */}
          {step === 2 && (
            <div className="grid gap-6 lg:grid-cols-2">
              {/* Left: selected chapters summary */}
              <Card>
                <CardHeader>
                  <CardTitle>Phạm vi đề thi</CardTitle>
                  <CardDescription>Các chương đã chọn</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {LY12_CHAPTERS.filter(c => config.selectedChapterIds.has(c.id)).map(chapter => (
                      <div key={chapter.id} className="flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
                        <BookOpen className="h-4 w-4 text-primary shrink-0" />
                        <span className="text-sm font-medium">{chapter.title}</span>
                      </div>
                    ))}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-4 text-muted-foreground"
                    onClick={() => setStep(1)}
                  >
                    <ChevronLeft className="h-4 w-4 mr-1" />
                    Thay đổi chương
                  </Button>
                </CardContent>
              </Card>

              {/* Right: Exam config */}
              <Card>
                <CardHeader>
                  <CardTitle>Cấu hình đề thi</CardTitle>
                  <CardDescription>Thiết lập số câu hỏi và phân bố Bloom</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
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

                  <FieldGroup>
                    <Field>
                      <FieldLabel>Chế độ đề thi</FieldLabel>
                      <RadioGroup
                        value={config.examMode}
                        onValueChange={(val) => {
                          const mode = val as ExamMode
                          if (mode === 'thpt_2025') {
                            setConfig(prev => ({ ...prev, examMode: mode, ...THPT_2025_CONFIG }))
                          } else {
                            setConfig(prev => ({ ...prev, examMode: mode }))
                          }
                        }}
                        className="flex flex-wrap gap-4"
                      >
                        <div className="flex items-center gap-2">
                          <RadioGroupItem value="standard" id="mode-standard" />
                          <Label htmlFor="mode-standard">Tuỳ chỉnh</Label>
                        </div>
                        <div className="flex items-center gap-2">
                          <RadioGroupItem value="thpt_2025" id="mode-thpt" />
                          <Label htmlFor="mode-thpt" className="font-medium text-amber-400">
                            Chuẩn THPT 2025 (18 TN + 4 Đúng-Sai + 6 Ngắn)
                          </Label>
                        </div>
                      </RadioGroup>
                    </Field>
                  </FieldGroup>

                  {config.examMode === 'standard' && (
                    <FieldGroup>
                      <Field>
                        <FieldLabel>Loại đề thi</FieldLabel>
                        <RadioGroup
                          value={config.examType}
                          onValueChange={(v) => {
                            const t = v as ExamType
                            setConfig(prev => ({
                              ...prev,
                              examType: t,
                              ...(t === 'mcq' ? { essayCount: 0 } : {}),
                              ...(t === 'essay' ? { mcqCount: 0 } : {}),
                            }))
                          }}
                          className="flex flex-wrap gap-4"
                        >
                          <div className="flex items-center gap-2">
                            <RadioGroupItem value="mcq" id="tb-mcq" />
                            <Label htmlFor="tb-mcq">Chỉ trắc nghiệm</Label>
                          </div>
                          <div className="flex items-center gap-2">
                            <RadioGroupItem value="essay" id="tb-essay" />
                            <Label htmlFor="tb-essay">Chỉ tự luận</Label>
                          </div>
                          <div className="flex items-center gap-2">
                            <RadioGroupItem value="mixed" id="tb-mixed" />
                            <Label htmlFor="tb-mixed">Kết hợp</Label>
                          </div>
                        </RadioGroup>
                      </Field>
                    </FieldGroup>
                  )}

                  <div className="grid gap-4 sm:grid-cols-2">
                    {(config.examMode === 'thpt_2025' || config.examType === 'mcq' || config.examType === 'mixed') && (
                      <Field>
                        <FieldLabel>Trắc nghiệm (MCQ)</FieldLabel>
                        <Input
                          type="number"
                          min={0}
                          max={50}
                          value={config.mcqCount}
                          disabled={config.examMode === 'thpt_2025'}
                          onChange={(e) => setConfig(prev => ({ ...prev, mcqCount: parseInt(e.target.value) || 0 }))}
                        />
                      </Field>
                    )}
                    {config.examMode === 'thpt_2025' && (
                      <>
                        <Field>
                          <FieldLabel>Đúng-Sai (THPT)</FieldLabel>
                          <Input type="number" value={config.dungSaiCount} disabled />
                        </Field>
                        <Field>
                          <FieldLabel>Trả lời ngắn</FieldLabel>
                          <Input type="number" value={config.shortAnswerCount} disabled />
                        </Field>
                      </>
                    )}
                    {config.examMode === 'standard' && (config.examType === 'essay' || config.examType === 'mixed') && (
                      <Field>
                        <FieldLabel>Tự luận</FieldLabel>
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
                          disabled={config.examMode === 'thpt_2025'}
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

                  <Field>
                    <FieldLabel>Hướng dẫn thêm cho AI (tùy chọn)</FieldLabel>
                    <Textarea
                      placeholder="Ví dụ: Tập trung vào bài tập tính toán, tránh lý thuyết thuần túy..."
                      value={config.userPrompt}
                      onChange={(e) => setConfig(prev => ({ ...prev, userPrompt: e.target.value }))}
                      maxLength={500}
                      rows={3}
                    />
                    <FieldDescription>{config.userPrompt.length}/500 ký tự</FieldDescription>
                  </Field>
                </CardContent>
              </Card>

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

          {/* Step 3: Live viewer */}
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
