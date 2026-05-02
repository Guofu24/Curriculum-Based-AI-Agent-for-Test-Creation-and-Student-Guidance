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
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  FileText,
  ChevronRight,
  ChevronDown,
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
  // Selected section IDs
  selectedSections: Set<string>
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
  selectedSections: new Set(),
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
  // Track which chapters have their sections dropdown open
  const [openChapterIds, setOpenChapterIds] = useState<Set<string>>(new Set())
  const [isLoadingDocs, setIsLoadingDocs] = useState(true)
  const [isLoadingCurriculum, setIsLoadingCurriculum] = useState(false)
  const [examId, setExamId] = useState<string | null>(null)
  const [wsUrl, setWsUrl] = useState<string | null>(null)

  // Fetch completed documents
  useEffect(() => {
    async function fetchDocuments() {
      try {
        const response = await documentsApi.list(1, 100)
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
        // NO auto-select — user must choose manually
      } catch (error) {
        console.error('Failed to fetch curriculum:', error)
      } finally {
        setIsLoadingCurriculum(false)
      }
    }
    fetchCurriculum()
  }, [config.documentId])

  // ── Helpers ──────────────────────────────────────────────────────────────

  const chapters = curriculum.filter(n => n.level === 1)
  const getSectionsForChapter = (chapterId: string) =>
    curriculum.filter(n => n.level === 2 && n.parent_id === chapterId)

  // Chapters that have at least one section selected
  const getSelectedChapterIds = (): Set<string> => {
    const ids = new Set<string>()
    config.selectedSections.forEach(secId => {
      const node = curriculum.find(n => n.id === secId)
      if (node?.parent_id) {
        ids.add(node.parent_id)
      }
    })
    return ids
  }

  // ── Section toggle ────────────────────────────────────────────────────────

  const toggleSection = (sectionId: string) => {
    setConfig(prev => {
      const next = new Set(prev.selectedSections)
      if (next.has(sectionId)) {
        next.delete(sectionId)
      } else {
        next.add(sectionId)
      }
      return { ...prev, selectedSections: next }
    })
  }

  // ── Select / deselect all sections within a chapter ──────────────────────

  const selectAllSections = (chapterId: string) => {
    const sections = getSectionsForChapter(chapterId)
    const allSectionIds = sections.map(s => s.id)
    const allSelected = allSectionIds.every(id => config.selectedSections.has(id))

    if (allSelected) {
      // Deselect all sections in this chapter
      setConfig(prev => {
        const next = new Set(prev.selectedSections)
        allSectionIds.forEach(id => next.delete(id))
        return { ...prev, selectedSections: next }
      })
    } else {
      // Select all sections in this chapter
      setConfig(prev => {
        const next = new Set(prev.selectedSections)
        allSectionIds.forEach(id => next.add(id))
        return { ...prev, selectedSections: next }
      })
    }
  }

  // ── Open / close sections dropdown ──────────────────────────────────────

  const toggleOpenChapter = (chapterId: string) => {
    setOpenChapterIds(prev => {
      const next = new Set(prev)
      if (next.has(chapterId)) {
        next.delete(chapterId)
      } else {
        next.add(chapterId)
      }
      return next
    })
  }

  // ── Deselect all ────────────────────────────────────────────────────────

  const handleDeselectAll = () => {
    setConfig(prev => ({ ...prev, selectedSections: new Set() }))
    toast.info('Đã bỏ chọn tất cả')
  }

  // ── Resolve scope for API ─────────────────────────────────────────────────

  const getDisplayScope = (): string[] => {
    const selectedNodeMap = new Map<string, CurriculumNode>()
    config.selectedSections.forEach(id => {
      const node = curriculum.find(n => n.id === id)
      if (node) selectedNodeMap.set(id, node)
    })

    // Group by chapter
    const byChapter = new Map<string, string[]>()
    selectedNodeMap.forEach((node, id) => {
      const parentId = node.parent_id ?? ''
      if (!byChapter.has(parentId)) byChapter.set(parentId, [])
      byChapter.get(parentId)!.push(node.title)
    })

    const result: string[] = []
    byChapter.forEach((sectionTitles, chapterId) => {
      const chapterNode = chapters.find(c => c.id === chapterId)
      const chapterTitle = chapterNode?.title ?? chapterId
      // If all sections of a chapter are selected → use just chapter title
      const chapterSections = getSectionsForChapter(chapterId)
      const allSectionsSelected = chapterSections.length > 0 &&
        chapterSections.every(s => config.selectedSections.has(s.id))

      if (allSectionsSelected) {
        result.push(chapterTitle)
      } else {
        // Only selected sections
        sectionTitles.forEach(title => {
          result.push(`${chapterTitle} > ${title}`)
        })
      }
    })

    return result
  }

  const handleSelectDocument = (docId: string) => {
    setConfig(prev => ({ ...prev, documentId: docId, selectedSections: new Set() }))
  }

  const handleBloomChange = (level: BloomLevel, value: number) => {
    setConfig(prev => ({
      ...prev,
      bloomDistribution: { ...prev.bloomDistribution, [level]: value }
    }))
  }

  const bloomSum = Object.values(config.bloomDistribution).reduce((a, b) => a + b, 0)
  const isBloomValid = bloomSum === 100

  const hasAnySelection = config.selectedSections.size > 0
  const canProceedStep1 = config.documentId !== ''
  const canProceedStep2 =
    hasAnySelection &&
    (config.mcqCount > 0 || config.essayCount > 0) &&
    isBloomValid

  const handleStartGeneration = async () => {
    if (!canProceedStep2) return

    const displayScope = getDisplayScope()

    try {
      const request: ExamGenerationRequest = {
        document_id: config.documentId,
        scope: displayScope,
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
  const selectedChapterIds = getSelectedChapterIds()

  // Count summary
  const selectedChapterCount = selectedChapterIds.size
  const selectedSectionCount = config.selectedSections.size

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
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <div>
                    <CardTitle>Phạm vi đề thi</CardTitle>
                    <CardDescription>
                      Chọn các phần cần thiết. Mỗi phần thuộc một chương.
                    </CardDescription>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleDeselectAll}
                    disabled={!hasAnySelection}
                    className="text-muted-foreground"
                  >
                    Bỏ chọn tất cả
                  </Button>
                </CardHeader>
                <CardContent>
                  {selectedDoc && (
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50 mb-4">
                      <FileText className="h-5 w-5 text-primary" />
                      <span className="font-medium truncate">
                        {selectedDoc.original_filename}
                      </span>
                      {hasAnySelection && (
                        <Badge variant="secondary" className="ml-auto shrink-0">
                          {selectedChapterCount > 0 && `${selectedChapterCount} chương`}
                          {selectedChapterCount > 0 && selectedSectionCount > 0 && ' + '}
                          {selectedSectionCount > 0 && `${selectedSectionCount} phần`}
                        </Badge>
                      )}
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
                        const sections = getSectionsForChapter(chapter.id)
                        const isChapterSelected = selectedChapterIds.has(chapter.id)
                        const isOpen = openChapterIds.has(chapter.id) || isChapterSelected
                        const selectedInChapter = sections.filter(s =>
                          config.selectedSections.has(s.id)
                        )
                        const allSectionIds = sections.map(s => s.id)
                        const allSectionsSelected =
                          sections.length > 0 &&
                          allSectionIds.every(id => config.selectedSections.has(id))
                        const someSectionsSelected =
                          sections.length > 0 &&
                          allSectionIds.some(id => config.selectedSections.has(id)) &&
                          !allSectionsSelected

                        return (
                          <div key={chapter.id} className="space-y-1">
                            {/* Chapter header (always collapsible, no chapter checkbox) */}
                            <div
                              className={cn(
                                "flex items-center gap-2 rounded-lg border p-3 cursor-pointer transition-colors",
                                isChapterSelected
                                  ? "border-primary bg-primary/5"
                                  : "hover:bg-muted/50"
                              )}
                              onClick={() => toggleOpenChapter(chapter.id)}
                            >
                              {/* Chapter title */}
                              <span className="flex-1 text-sm font-medium truncate">
                                {chapter.title}
                              </span>

                              {sections.length > 0 && (
                                <>
                                  {/* Section count badge */}
                                  <Badge
                                    variant={someSectionsSelected ? "default" : "outline"}
                                    className={cn(
                                      "text-xs shrink-0",
                                      allSectionsSelected && "bg-primary text-primary-foreground"
                                    )}
                                  >
                                    {selectedInChapter.length > 0
                                      ? `${selectedInChapter.length}/${sections.length} phần`
                                      : `${sections.length} phần`}
                                  </Badge>

                                  {/* Expand / collapse */}
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6 shrink-0"
                                    onClick={e => {
                                      e.stopPropagation()
                                      toggleOpenChapter(chapter.id)
                                    }}
                                    title={isOpen ? 'Thu gọn' : 'Mở rộng'}
                                  >
                                    {isOpen ? (
                                      <ChevronDown className="h-4 w-4" />
                                    ) : (
                                      <ChevronRight className="h-4 w-4" />
                                    )}
                                  </Button>
                                </>
                              )}

                              {chapter.chunk_count !== undefined && (
                                <Badge variant="secondary" className="text-xs shrink-0">
                                  {chapter.chunk_count}
                                </Badge>
                              )}
                            </div>

                            {/* Sections dropdown */}
                            {sections.length > 0 && (
                              <Collapsible open={isOpen}>
                                <CollapsibleContent>
                                  <div className="pl-10 pr-2 pb-2 space-y-1">
                                    {/* Select All sections */}
                                    <div
                                      className="flex items-center gap-2 py-1 cursor-pointer hover:text-foreground"
                                      onClick={() => selectAllSections(chapter.id)}
                                    >
                                      <Checkbox
                                        checked={allSectionsSelected}
                                        onCheckedChange={() => selectAllSections(chapter.id)}
                                        onClick={e => e.stopPropagation()}
                                        className="shrink-0"
                                      />
                                      <span className="flex-1 text-xs text-muted-foreground hover:text-foreground">
                                        {allSectionsSelected
                                          ? 'Bỏ chọn tất cả phần'
                                          : 'Chọn tất cả phần'}
                                      </span>
                                    </div>

                                    {/* Individual sections */}
                                    {sections.map((section) => {
                                      const isSectionSelected =
                                        config.selectedSections.has(section.id)

                                      return (
                                        <div
                                          key={section.id}
                                          className={cn(
                                            "flex items-center gap-2 rounded-md px-2 py-2 cursor-pointer transition-colors",
                                            isSectionSelected
                                              ? "bg-primary/5"
                                              : "hover:bg-muted/30"
                                          )}
                                          onClick={() => toggleSection(section.id)}
                                        >
                                          <Checkbox
                                            checked={isSectionSelected}
                                            onCheckedChange={() => toggleSection(section.id)}
                                            onClick={e => e.stopPropagation()}
                                            className="shrink-0"
                                          />
                                          <span
                                            className={cn(
                                              "flex-1 text-xs cursor-pointer truncate",
                                              isSectionSelected
                                                ? "font-medium"
                                                : "text-muted-foreground"
                                            )}
                                          >
                                            {section.title}
                                          </span>
                                          {section.chunk_count !== undefined && (
                                            <Badge
                                              variant="secondary"
                                              className="text-xs shrink-0"
                                            >
                                              {section.chunk_count}
                                            </Badge>
                                          )}
                                        </div>
                                      )
                                    })}
                                  </div>
                                </CollapsibleContent>
                              </Collapsible>
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
