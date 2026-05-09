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
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { BookOpen, ChevronRight, ChevronLeft, ChevronDown, Sparkles, Check, AlertCircle, Info, Database } from 'lucide-react'
import { toast } from 'sonner'
import { generateApi, examsApi, adminApi, ExamGenerationRequest, BloomLevel } from '@/lib/api'
import { GenerationLiveViewer } from '@/components/generation-live-viewer'
import { cn } from '@/lib/utils'

type ExamType = 'mcq' | 'essay' | 'mixed'
type ExamMode = 'standard' | 'thpt_2025'

interface OutlineItem { chapter: string; sections: string[] }

interface TextbookConfig {
  namespace: string
  // Track selection per-section: key = "chapter|||section", value = true
  // A chapter is fully selected when ALL its sections are selected
  selectedSections: Set<string>
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
  namespace: '',
  selectedSections: new Set(),
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

const THPT_CONFIG = {
  mcqCount: 18, dungSaiCount: 4, shortAnswerCount: 6, essayCount: 0,
  bloomDistribution: { nhan_biet: 40, thong_hieu: 30, van_dung: 20, van_dung_cao: 10 } as Record<BloomLevel, number>,
}

const BLOOM_LABELS: Record<BloomLevel, string> = {
  nhan_biet: 'Nhận biết', thong_hieu: 'Thông hiểu', van_dung: 'Vận dụng', van_dung_cao: 'Vận dụng cao',
}

const sectionKey = (chapter: string, section: string) => `${chapter}|||${section}`

export default function TextbookGeneratePage() {
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [config, setConfig] = useState<TextbookConfig>(defaultConfig)
  const [examId, setExamId] = useState<string | null>(null)
  const [wsUrl, setWsUrl] = useState<string | null>(null)
  const [namespaces, setNamespaces] = useState<string[]>([])
  const [outline, setOutline] = useState<OutlineItem[]>([])
  const [isLoadingNS, setIsLoadingNS] = useState(true)
  const [isLoadingOutline, setIsLoadingOutline] = useState(false)
  const [openChapters, setOpenChapters] = useState<Set<string>>(new Set())

  useEffect(() => {
    adminApi.getNamespaces()
      .then(ns => {
        setNamespaces(ns)
        if (ns.length === 1) setConfig(prev => ({ ...prev, namespace: ns[0] }))
      })
      .catch(() => toast.error('Không thể tải danh sách nguồn kiến thức'))
      .finally(() => setIsLoadingNS(false))
  }, [])

  useEffect(() => {
    if (!config.namespace) return
    setIsLoadingOutline(true)
    setOutline([])
    setConfig(prev => ({ ...prev, selectedSections: new Set() }))
    setOpenChapters(new Set())
    adminApi.getOutline(config.namespace)
      .then(data => {
        setOutline(data)
        // Auto-open first chapter
        if (data.length > 0) setOpenChapters(new Set([data[0].chapter]))
      })
      .catch(() => toast.error('Không thể tải danh sách chương'))
      .finally(() => setIsLoadingOutline(false))
  }, [config.namespace])

  // ── Selection helpers ──────────────────────────────────────────────────────
  const isChapterFullySelected = (item: OutlineItem) =>
    item.sections.length > 0 && item.sections.every(s => config.selectedSections.has(sectionKey(item.chapter, s)))

  const isChapterPartiallySelected = (item: OutlineItem) =>
    item.sections.some(s => config.selectedSections.has(sectionKey(item.chapter, s))) && !isChapterFullySelected(item)

  const toggleSection = (chapter: string, section: string) => {
    setConfig(prev => {
      const next = new Set(prev.selectedSections)
      const k = sectionKey(chapter, section)
      if (next.has(k)) next.delete(k); else next.add(k)
      return { ...prev, selectedSections: next }
    })
  }

  const toggleChapter = (item: OutlineItem) => {
    const full = isChapterFullySelected(item)
    setConfig(prev => {
      const next = new Set(prev.selectedSections)
      for (const s of item.sections) {
        const k = sectionKey(item.chapter, s)
        if (full) next.delete(k); else next.add(k)
      }
      return { ...prev, selectedSections: next }
    })
  }

  const selectAll = () => {
    const all = new Set(outline.flatMap(c => c.sections.map(s => sectionKey(c.chapter, s))))
    setConfig(prev => ({ ...prev, selectedSections: all }))
  }

  const deselectAll = () => setConfig(prev => ({ ...prev, selectedSections: new Set() }))

  const toggleOpenChapter = (chapter: string) => {
    setOpenChapters(prev => {
      const next = new Set(prev)
      if (next.has(chapter)) next.delete(chapter); else next.add(chapter)
      return next
    })
  }

  // Scope passed to backend:
  //   - Fully selected chapter  → "Chapter name" (retrieve all sections)
  //   - Partially selected      → "Chapter name > Section name" per selected section
  const getScope = () => {
    const result: string[] = []
    for (const item of outline) {
      const selectedSecs = item.sections.filter(s => config.selectedSections.has(sectionKey(item.chapter, s)))
      if (selectedSecs.length === 0) continue
      if (selectedSecs.length === item.sections.length) {
        // Full chapter selected — backend retrieves all
        result.push(item.chapter)
      } else {
        // Partial: send each selected section as "Chapter > Section"
        for (const sec of selectedSecs) {
          result.push(`${item.chapter} > ${sec}`)
        }
      }
    }
    return result
  }

  // For display only: count distinct chapters that have ≥1 section selected
  const getScopeChapterCount = () => new Set(
    Array.from(config.selectedSections).map(k => k.split('|||')[0])
  ).size

  const bloomSum = Object.values(config.bloomDistribution).reduce((a, b) => a + b, 0)
  const isBloomValid = bloomSum === 100
  const totalQ = config.mcqCount + config.essayCount + config.dungSaiCount + config.shortAnswerCount
  const totalSectionsSelected = config.selectedSections.size
  const totalSections = outline.reduce((a, c) => a + c.sections.length, 0)
  const allSelected = totalSections > 0 && totalSectionsSelected === totalSections
  const canStep2 = config.namespace !== '' && totalSectionsSelected > 0
  const canGenerate = totalQ > 0 && isBloomValid

  const handleStartGeneration = async () => {
    if (!canGenerate) return
    try {
      const req: ExamGenerationRequest = {
        document_id: null,
        use_builtin_knowledge: true,
        knowledge_namespace: config.namespace,
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
      const res = await generateApi.startGeneration(req)
      setExamId(res.exam_id)
      if (res.scope_warning) toast.warning(res.scope_warning)
      setWsUrl(res.websocket_url || `/ws/exam/${res.exam_id}`)
      setStep(3)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Không thể bắt đầu tạo đề')
    }
  }

  const handleApprove = useCallback(async (id: string, approved: boolean, feedback?: string, checkpointId?: number) => {
    const cp = checkpointId ?? 1
    try {
      if (cp === 2) await examsApi.submitReview(id, { approved, feedback })
      else if (approved) await examsApi.approveBlueprint(id)
      else await examsApi.rejectBlueprint(id, feedback || 'Yêu cầu điều chỉnh.')
    } catch (err) { toast.error(err instanceof Error ? err.message : 'Có lỗi xảy ra') }
  }, [])

  const handleExamComplete = useCallback((id: string) => router.push(`/dashboard/exams/${id}`), [router])

  return (
    <>
      <DashboardHeader breadcrumbs={[{ label: 'Tạo đề' }, { label: 'Kiến thức có sẵn' }]} />
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-amber-500/10 text-amber-500">
              <BookOpen className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Sinh đề từ kiến thức có sẵn</h1>
              <p className="text-muted-foreground">Kiến thức được xây sẵn bởi Admin — không cần upload tài liệu</p>
            </div>
          </div>

          {!isLoadingNS && namespaces.length === 0 && (
            <div className="flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3">
              <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
              <p className="text-sm text-destructive">Chưa có nguồn kiến thức nào. Vui lòng liên hệ Admin để upload dữ liệu.</p>
            </div>
          )}

          {!isLoadingNS && namespaces.length > 0 && step < 3 && (
            <div className="flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 flex-wrap">
              <Database className="h-4 w-4 text-amber-500 shrink-0" />
              <span className="text-sm text-amber-200 flex-1">Nguồn kiến thức:</span>
              <Select value={config.namespace} onValueChange={val => setConfig(prev => ({ ...prev, namespace: val }))}>
                <SelectTrigger className="w-56 border-amber-500/40 bg-background text-sm">
                  <SelectValue placeholder="Chọn namespace..." />
                </SelectTrigger>
                <SelectContent>
                  {namespaces.map(ns => <SelectItem key={ns} value={ns}>{ns}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}

          {namespaces.length > 0 && (
            <div className="flex items-center gap-2">
              {[1, 2, 3].map(s => (
                <div key={s} className="flex items-center gap-2">
                  <div className={cn("flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium transition-colors", step >= s ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
                    {step > s ? <Check className="h-4 w-4" /> : s}
                  </div>
                  <span className={cn("text-sm hidden sm:inline", step >= s ? "text-foreground" : "text-muted-foreground")}>
                    {s === 1 && "Chọn chương / bài"}{s === 2 && "Cấu hình đề"}{s === 3 && "Tạo đề"}
                  </span>
                  {s < 3 && <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                </div>
              ))}
            </div>
          )}

          {/* ── Step 1: Chapter + Section ── */}
          {step === 1 && namespaces.length > 0 && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <div>
                  <CardTitle>Chọn chương &amp; bài học</CardTitle>
                  <CardDescription>
                    {config.namespace ? `Namespace: ${config.namespace}` : 'Chọn namespace ở trên trước'}
                  </CardDescription>
                </div>
                {outline.length > 0 && (
                  <Button variant="ghost" size="sm" onClick={allSelected ? deselectAll : selectAll} className="text-muted-foreground">
                    {allSelected ? 'Bỏ chọn tất cả' : 'Chọn tất cả'}
                  </Button>
                )}
              </CardHeader>
              <CardContent>
                {isLoadingOutline ? (
                  <div className="space-y-3">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}</div>
                ) : !config.namespace ? (
                  <div className="flex items-center gap-2 text-muted-foreground py-8 justify-center">
                    <Info className="h-4 w-4" /><span className="text-sm">Chọn nguồn kiến thức để xem danh sách</span>
                  </div>
                ) : outline.length === 0 ? (
                  <div className="flex items-center gap-2 text-muted-foreground py-8 justify-center">
                    <AlertCircle className="h-4 w-4" /><span className="text-sm">Namespace này chưa có dữ liệu</span>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {outline.map(item => {
                      const fully = isChapterFullySelected(item)
                      const partial = isChapterPartiallySelected(item)
                      const open = openChapters.has(item.chapter)
                      return (
                        <Collapsible key={item.chapter} open={open} onOpenChange={() => toggleOpenChapter(item.chapter)}>
                          <div className={cn(
                            "rounded-lg border transition-colors",
                            fully ? "border-primary bg-primary/5" : partial ? "border-primary/50 bg-primary/2" : "border-border/50"
                          )}>
                            {/* Chapter row */}
                            <div className="flex items-center gap-3 px-4 py-3">
                              <Checkbox
                                checked={fully}
                                data-state={partial ? 'indeterminate' : fully ? 'checked' : 'unchecked'}
                                onCheckedChange={() => toggleChapter(item)}
                                className="shrink-0"
                              />
                              <CollapsibleTrigger asChild>
                                <button className="flex flex-1 items-center justify-between text-left group">
                                  <div>
                                    <p className={cn("font-medium text-sm", (fully || partial) && "text-primary")}>{item.chapter}</p>
                                    <p className="text-xs text-muted-foreground mt-0.5">
                                      {item.sections.filter(s => config.selectedSections.has(sectionKey(item.chapter, s))).length}/{item.sections.length} bài được chọn
                                    </p>
                                  </div>
                                  <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
                                </button>
                              </CollapsibleTrigger>
                            </div>
                            {/* Sections */}
                            <CollapsibleContent>
                              <div className="border-t border-border/30 divide-y divide-border/20">
                                {item.sections.map(section => {
                                  const k = sectionKey(item.chapter, section)
                                  const selected = config.selectedSections.has(k)
                                  return (
                                    <div
                                      key={section}
                                      className={cn("flex items-start gap-3 px-4 py-2.5 cursor-pointer transition-colors hover:bg-muted/30 ml-7", selected && "bg-primary/5")}
                                      onClick={() => toggleSection(item.chapter, section)}
                                    >
                                      <Checkbox
                                        checked={selected}
                                        onCheckedChange={() => toggleSection(item.chapter, section)}
                                        onClick={e => e.stopPropagation()}
                                        className="mt-0.5 shrink-0"
                                      />
                                      <span className={cn("text-sm leading-snug", selected && "text-primary font-medium")}>{section}</span>
                                    </div>
                                  )
                                })}
                              </div>
                            </CollapsibleContent>
                          </div>
                        </Collapsible>
                      )
                    })}
                  </div>
                )}

                <div className="flex justify-between items-center mt-6">
                  <span className="text-sm text-muted-foreground">
                    {totalSectionsSelected > 0
                      ? `Đã chọn ${totalSectionsSelected} bài từ ${getScopeChapterCount()} chương`
                      : 'Chưa chọn bài nào'}
                  </span>
                  <Button onClick={() => setStep(2)} disabled={!canStep2}>
                    Tiếp theo <ChevronRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ── Step 2: Config ── */}
          {step === 2 && (
            <div className="grid gap-6 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>Phạm vi đề thi</CardTitle>
                  <CardDescription>Các chương &amp; bài đã chọn</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    {outline.filter(c => isChapterFullySelected(c) || isChapterPartiallySelected(c)).map(item => (
                      <div key={item.chapter} className="rounded-lg border border-primary/30 bg-primary/5 p-3">
                        <div className="flex items-center gap-2 mb-2">
                          <BookOpen className="h-4 w-4 text-primary shrink-0" />
                          <span className="text-sm font-semibold text-primary">{item.chapter}</span>
                        </div>
                        <div className="ml-6 space-y-1">
                          {item.sections.filter(s => config.selectedSections.has(sectionKey(item.chapter, s))).map(s => (
                            <p key={s} className="text-xs text-muted-foreground">• {s}</p>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  <Button variant="ghost" size="sm" className="mt-4 text-muted-foreground" onClick={() => setStep(1)}>
                    <ChevronLeft className="h-4 w-4 mr-1" />Thay đổi lựa chọn
                  </Button>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Cấu hình đề thi</CardTitle>
                  <CardDescription>Thiết lập số câu hỏi và phân bố Bloom</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <FieldGroup>
                    <Field>
                      <FieldLabel>Tiêu đề đề thi (tùy chọn)</FieldLabel>
                      <Input placeholder="Ví dụ: Đề kiểm tra Vật lý Chương 1-2" value={config.title}
                        onChange={e => setConfig(prev => ({ ...prev, title: e.target.value }))} />
                    </Field>
                  </FieldGroup>

                  <FieldGroup>
                    <Field>
                      <FieldLabel>Chế độ đề thi</FieldLabel>
                      <RadioGroup value={config.examMode} onValueChange={val => {
                        const mode = val as ExamMode
                        setConfig(prev => ({ ...prev, examMode: mode, ...(mode === 'thpt_2025' ? THPT_CONFIG : {}) }))
                      }} className="flex flex-wrap gap-4">
                        <div className="flex items-center gap-2"><RadioGroupItem value="standard" id="std" /><Label htmlFor="std">Tuỳ chỉnh</Label></div>
                        <div className="flex items-center gap-2"><RadioGroupItem value="thpt_2025" id="thpt" /><Label htmlFor="thpt" className="font-medium text-amber-400">Chuẩn THPT 2025</Label></div>
                      </RadioGroup>
                    </Field>
                  </FieldGroup>

                  {config.examMode === 'standard' && (
                    <FieldGroup>
                      <Field>
                        <FieldLabel>Loại đề thi</FieldLabel>
                        <RadioGroup value={config.examType} onValueChange={v => setConfig(prev => ({
                          ...prev, examType: v as ExamType,
                          ...(v === 'mcq' ? { essayCount: 0 } : v === 'essay' ? { mcqCount: 0 } : {})
                        }))} className="flex flex-wrap gap-4">
                          <div className="flex items-center gap-2"><RadioGroupItem value="mcq" id="mcq" /><Label htmlFor="mcq">Trắc nghiệm</Label></div>
                          <div className="flex items-center gap-2"><RadioGroupItem value="essay" id="essay" /><Label htmlFor="essay">Tự luận</Label></div>
                          <div className="flex items-center gap-2"><RadioGroupItem value="mixed" id="mixed" /><Label htmlFor="mixed">Kết hợp</Label></div>
                        </RadioGroup>
                      </Field>
                    </FieldGroup>
                  )}

                  <div className="grid gap-4 sm:grid-cols-2">
                    {(config.examMode === 'thpt_2025' || ['mcq', 'mixed'].includes(config.examType)) && (
                      <Field><FieldLabel>Trắc nghiệm (MCQ)</FieldLabel>
                        <Input type="number" min={0} max={50} value={config.mcqCount} disabled={config.examMode === 'thpt_2025'}
                          onChange={e => setConfig(prev => ({ ...prev, mcqCount: parseInt(e.target.value) || 0 }))} /></Field>
                    )}
                    {config.examMode === 'thpt_2025' && (<>
                      <Field><FieldLabel>Đúng-Sai</FieldLabel><Input type="number" value={config.dungSaiCount} disabled /></Field>
                      <Field><FieldLabel>Trả lời ngắn</FieldLabel><Input type="number" value={config.shortAnswerCount} disabled /></Field>
                    </>)}
                    {config.examMode === 'standard' && ['essay', 'mixed'].includes(config.examType) && (
                      <Field><FieldLabel>Tự luận</FieldLabel>
                        <Input type="number" min={0} max={10} value={config.essayCount}
                          onChange={e => setConfig(prev => ({ ...prev, essayCount: parseInt(e.target.value) || 0 }))} /></Field>
                    )}
                  </div>

                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <FieldLabel>Phân bố Bloom Taxonomy</FieldLabel>
                      <Badge variant={isBloomValid ? "default" : "destructive"}>Tổng: {bloomSum}%</Badge>
                    </div>
                    {(Object.keys(config.bloomDistribution) as BloomLevel[]).map(level => (
                      <div key={level} className="space-y-2">
                        <div className="flex items-center justify-between text-sm">
                          <span>{BLOOM_LABELS[level]}</span>
                          <span className="font-medium">{config.bloomDistribution[level]}%</span>
                        </div>
                        <Slider value={[config.bloomDistribution[level]]}
                          onValueChange={([v]) => setConfig(prev => ({ ...prev, bloomDistribution: { ...prev.bloomDistribution, [level]: v } }))}
                          max={100} step={5} disabled={config.examMode === 'thpt_2025'} className="cursor-pointer" />
                      </div>
                    ))}
                    {!isBloomValid && <p className="text-sm text-destructive flex items-center gap-1"><AlertCircle className="h-4 w-4" />Tổng phần trăm phải bằng 100%</p>}
                  </div>

                  <Field>
                    <FieldLabel>Hướng dẫn thêm (tùy chọn)</FieldLabel>
                    <Textarea placeholder="Ví dụ: Tập trung vào bài tập tính toán..." value={config.userPrompt}
                      onChange={e => setConfig(prev => ({ ...prev, userPrompt: e.target.value }))} maxLength={500} rows={3} />
                    <FieldDescription>{config.userPrompt.length}/500 ký tự</FieldDescription>
                  </Field>
                </CardContent>
              </Card>

              <div className="lg:col-span-2 flex justify-between">
                <Button variant="outline" onClick={() => setStep(1)}><ChevronLeft className="mr-2 h-4 w-4" />Quay lại</Button>
                <Button onClick={handleStartGeneration} disabled={!canGenerate}>
                  <Sparkles className="mr-2 h-4 w-4" />Tạo đề
                </Button>
              </div>
            </div>
          )}

          {step === 3 && examId && (
            <GenerationLiveViewer examId={examId} wsUrl={wsUrl || `/ws/exam/${examId}`}
              examType={config.examType} onApprove={handleApprove} onComplete={handleExamComplete} />
          )}
        </div>
      </main>
    </>
  )
}
