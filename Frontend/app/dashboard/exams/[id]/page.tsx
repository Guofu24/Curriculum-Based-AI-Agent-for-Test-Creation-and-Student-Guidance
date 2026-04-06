"use client"

import { useEffect, useState, use } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Progress } from '@/components/ui/progress'
import { Spinner } from '@/components/ui/spinner'
import { FieldGroup, Field, FieldLabel } from '@/components/ui/field'
import {
  FileText,
  Download,
  Send,
  Edit3,
  RefreshCw,
  History,
  Check,
  X,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  BookOpen,
  TrendingUp,
} from 'lucide-react'
import { toast } from 'sonner'
import { 
  examsApi, 
  Exam, 
  Question, 
  ExamVersion,
  BlueprintSlot,
  BloomLevel 
} from '@/lib/api'
import { StatusBadge, BloomBadge, QuestionTypeBadge, ChangeTypeBadge } from '@/components/status-badge'
import { formatDateTime, formatPercent, formatCurrency } from '@/lib/format'
import { cn } from '@/lib/utils'

interface PageParams {
  id: string
}

const BLOOM_LABELS: Record<BloomLevel, string> = {
  nhan_biet: 'Nhận biết',
  thong_hieu: 'Thông hiểu',
  van_dung: 'Vận dụng',
  van_dung_cao: 'Vận dụng cao',
}

export default function ExamDetailPage({ params }: { params: Promise<PageParams> }) {
  const { id } = use(params)
  const router = useRouter()
  const [exam, setExam] = useState<Exam | null>(null)
  const [versions, setVersions] = useState<ExamVersion[]>([])
  const [blueprint, setBlueprint] = useState<BlueprintSlot[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('questions')
  const [questionFilter, setQuestionFilter] = useState<'all' | 'mcq' | 'essay'>('all')
  const [editingQuestion, setEditingQuestion] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<Question>>({})
  const [isSaving, setIsSaving] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const [showPublishDialog, setShowPublishDialog] = useState(false)
  const [showEditPromptDialog, setShowEditPromptDialog] = useState(false)
  const [editPromptText, setEditPromptText] = useState('')
  const [showBlueprintActionDialog, setShowBlueprintActionDialog] = useState(false)
  const [blueprintAction, setBlueprintAction] = useState<'approve' | 'reject' | null>(null)
  const [blueprintFeedback, setBlueprintFeedback] = useState('')
  const [isBlueprintActing, setIsBlueprintActing] = useState(false)

  useEffect(() => {
    async function fetchData() {
      try {
        const [examRes, versionsRes] = await Promise.all([
          examsApi.get(id),
          examsApi.getVersions(id).catch(() => []),
        ])
        
        setExam(examRes)
        setVersions(versionsRes)

        // Get blueprint from examRes.blueprint (normalized to array by backend), fallback to getReviewData
        const examBlueprints = Array.isArray(examRes.blueprint) ? examRes.blueprint : []
        if (examBlueprints.length > 0) {
          setBlueprint(examBlueprints)
        } else {
          try {
            const reviewData = await examsApi.getReviewData(id)
            const raw = reviewData.blueprint
            setBlueprint(Array.isArray(raw) ? raw : [])
          } catch {
            // Blueprint not available
          }
        }
      } catch (error) {
        console.error('Failed to fetch exam:', error)
        toast.error('Không thể tải thông tin đề thi')
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [id])

  const handleExportPdf = async () => {
    setIsExporting(true)
    try {
      const blob = await examsApi.exportPdf(id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${exam?.title || 'exam'}.pdf`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Đã tải xuống PDF')
    } catch (error) {
      toast.error('Xuất PDF thất bại')
    } finally {
      setIsExporting(false)
    }
  }

  const handleExportDocx = async () => {
    setIsExporting(true)
    try {
      const blob = await examsApi.exportDocx(id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${exam?.title || 'exam'}.docx`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Đã tải xuống DOCX')
    } catch (error) {
      toast.error('Xuất DOCX thất bại')
    } finally {
      setIsExporting(false)
    }
  }

  const handlePublish = async () => {
    try {
      await examsApi.publish(id)
      setExam(prev => prev ? { ...prev, status: 'published' } : null)
      setShowPublishDialog(false)
      toast.success('Đã xuất bản đề thi')
    } catch (error) {
      toast.error('Xuất bản thất bại')
    }
  }

  const handleEditPrompt = async () => {
    if (!editPromptText.trim()) return
    
    try {
      await examsApi.editPrompt(id, editPromptText)
      setShowEditPromptDialog(false)
      setEditPromptText('')
      toast.success('Đang cập nhật đề thi bằng AI...')
      // Refresh exam data
      const updated = await examsApi.get(id)
      setExam(updated)
    } catch (error) {
      toast.error('Không thể cập nhật')
    }
  }

  const handleStartEditQuestion = (question: Question) => {
    setEditingQuestion(question.id)
    setEditForm({
      content: question.content,
      options: question.options,
      correct_answer: question.correct_answer,
      bloom_level: question.bloom_level,
      rubric: question.rubric,
    })
  }

  const handleSaveQuestion = async (questionId: string) => {
    setIsSaving(true)
    try {
      const updated = await examsApi.updateQuestion(id, questionId, editForm)
      setExam(prev => {
        if (!prev) return null
        return {
          ...prev,
          questions: prev.questions.map(q => 
            q.id === questionId ? { ...q, ...updated } : q
          )
        }
      })
      setEditingQuestion(null)
      toast.success('Đã lưu câu hỏi')
    } catch (error) {
      toast.error('Lưu thất bại')
    } finally {
      setIsSaving(false)
    }
  }

  const handleRegenerate = async () => {
    try {
      await examsApi.regenerate(id)
      toast.success('Đang tạo lại đề thi...')
      setExam(prev => prev ? { ...prev, status: 'regenerating' } : null)
    } catch (error) {
      toast.error('Không thể tạo lại')
    }
  }

  const handleApproveBlueprint = () => {
    setBlueprintAction('approve')
    setBlueprintFeedback('')
    setShowBlueprintActionDialog(true)
  }

  const handleRejectBlueprint = () => {
    setBlueprintAction('reject')
    setBlueprintFeedback('')
    setShowBlueprintActionDialog(true)
  }

  const handleBlueprintAction = async () => {
    if (!blueprintAction) return
    setIsBlueprintActing(true)
    try {
      if (blueprintAction === 'approve') {
        await examsApi.approveBlueprint(id)
        toast.success('Đã duyệt sườn đề. Pipeline đang tiếp tục...')
      } else {
        if (!blueprintFeedback.trim()) {
          toast.error('Vui lòng nhập phản hồi khi từ chối')
          setIsBlueprintActing(false)
          return
        }
        await examsApi.rejectBlueprint(id, blueprintFeedback)
        toast.success('Đã gửi phản hồi. Sườn đề mới đang được tạo...')
      }
      setShowBlueprintActionDialog(false)
      const reviewData = await examsApi.getReviewData(id)
      const raw2 = reviewData.blueprint
      setBlueprint(Array.isArray(raw2) ? raw2 : [])
    } catch (error) {
      toast.error(blueprintAction === 'approve' ? 'Không thể duyệt sườn đề' : 'Không thể gửi phản hồi')
    } finally {
      setIsBlueprintActing(false)
    }
  }

  if (isLoading) {
    return (
      <>
        <DashboardHeader breadcrumbs={[
          { label: 'Đề thi', href: '/dashboard/exams' },
          { label: 'Đang tải...' }
        ]} />
        <main className="flex-1 overflow-auto">
          <div className="container mx-auto p-6 space-y-6">
            <Skeleton className="h-12 w-96" />
            <Skeleton className="h-[600px] w-full" />
          </div>
        </main>
      </>
    )
  }

  if (!exam) {
    return (
      <>
        <DashboardHeader breadcrumbs={[
          { label: 'Đề thi', href: '/dashboard/exams' },
          { label: 'Không tìm thấy' }
        ]} />
        <main className="flex-1 overflow-auto">
          <div className="container mx-auto p-6">
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12">
                <FileText className="h-12 w-12 text-muted-foreground/50 mb-4" />
                <p className="text-lg font-medium">Không tìm thấy đề thi</p>
                <Button className="mt-4" onClick={() => router.push('/dashboard/exams')}>
                  Quay lại
                </Button>
              </CardContent>
            </Card>
          </div>
        </main>
      </>
    )
  }

  const filteredQuestions = exam.questions?.filter(q => 
    questionFilter === 'all' || q.type === questionFilter
  ) || []

  const mcqCount = exam.questions?.filter(q => q.type === 'mcq').length || 0
  const essayCount = exam.questions?.filter(q => q.type === 'essay').length || 0

  return (
    <>
      <DashboardHeader breadcrumbs={[
        { label: 'Đề thi', href: '/dashboard/exams' },
        { label: exam.title }
      ]} />
      
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Header */}
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                <FileText className="h-6 w-6 text-primary" />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight">{typeof exam.title === 'string' ? exam.title : 'Đề thi'}</h1>
                <div className="flex flex-wrap items-center gap-2 mt-1">
                  <StatusBadge status={exam.status} />
                  <Badge variant="outline">
                    {mcqCount} trắc nghiệm, {essayCount} tự luận
                  </Badge>
                </div>
              </div>
            </div>
            
            <div className="flex flex-wrap items-center gap-2">
              <Dialog open={showEditPromptDialog} onOpenChange={setShowEditPromptDialog}>
                <DialogTrigger asChild>
                  <Button variant="outline">
                    <Edit3 className="mr-2 h-4 w-4" />
                    Sửa AI
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Chỉnh sửa bằng AI</DialogTitle>
                    <DialogDescription>
                      Nhập hướng dẫn để AI điều chỉnh đề thi
                    </DialogDescription>
                  </DialogHeader>
                  <Textarea
                    placeholder="Ví dụ: Thay đổi các câu hỏi lý thuyết thành bài tập tính toán..."
                    value={editPromptText}
                    onChange={(e) => setEditPromptText(e.target.value)}
                    rows={4}
                  />
                  <DialogFooter>
                    <Button variant="outline" onClick={() => setShowEditPromptDialog(false)}>
                      Hủy
                    </Button>
                    <Button onClick={handleEditPrompt} disabled={!editPromptText.trim()}>
                      Cập nhật
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              <Button variant="outline" onClick={handleRegenerate}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Tạo lại
              </Button>

              <Button variant="outline" asChild>
                <Link href={`/dashboard/exams/${id}/history`}>
                  <History className="mr-2 h-4 w-4" />
                  Lịch sử
                </Link>
              </Button>

              <Button 
                variant="outline" 
                onClick={handleExportPdf}
                disabled={isExporting}
              >
                {isExporting ? <Spinner className="mr-2" /> : <Download className="mr-2 h-4 w-4" />}
                PDF
              </Button>

              <Button 
                variant="outline" 
                onClick={handleExportDocx}
                disabled={isExporting}
              >
                {isExporting ? <Spinner className="mr-2" /> : <Download className="mr-2 h-4 w-4" />}
                DOCX
              </Button>

              {exam.status !== 'published' && (
                <Button onClick={() => setShowPublishDialog(true)}>
                  <Send className="mr-2 h-4 w-4" />
                  Xuất bản
                </Button>
              )}
            </div>
          </div>

          {/* Tabs */}
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList>
              <TabsTrigger value="questions">Câu hỏi</TabsTrigger>
              <TabsTrigger value="blueprint">Sườn đề</TabsTrigger>
              <TabsTrigger value="quality">Chất lượng</TabsTrigger>
              <TabsTrigger value="history">Lịch sử</TabsTrigger>
            </TabsList>

            {/* Questions Tab */}
            <TabsContent value="questions" className="space-y-4">
              {/* Filter */}
              <div className="flex items-center gap-4">
                <Select
                  value={questionFilter}
                  onValueChange={(v) => setQuestionFilter(v as 'all' | 'mcq' | 'essay')}
                >
                  <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Lọc câu hỏi" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tất cả ({exam.questions?.length || 0})</SelectItem>
                    <SelectItem value="mcq">Trắc nghiệm ({mcqCount})</SelectItem>
                    <SelectItem value="essay">Tự luận ({essayCount})</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Questions List */}
              <ScrollArea className="h-[600px]">
                <div className="space-y-4 pr-4">
                  {filteredQuestions.map((question, index) => (
                    <QuestionCard
                      key={`${question.id}-${index}`}
                      question={question}
                      index={index + 1}
                      isEditing={editingQuestion === question.id}
                      editForm={editForm}
                      setEditForm={setEditForm}
                      isSaving={isSaving}
                      onStartEdit={() => handleStartEditQuestion(question)}
                      onSave={() => handleSaveQuestion(question.id)}
                      onCancel={() => setEditingQuestion(null)}
                    />
                  ))}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* Blueprint Tab */}
            <TabsContent value="blueprint">
              <Card>
                <CardHeader>
                  <CardTitle>Sườn đề (Blueprint)</CardTitle>
                  <CardDescription>
                    Cấu trúc đề thi theo Bloom Taxonomy
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {blueprint.length === 0 ? (
                    <div className="text-center py-8 text-muted-foreground">
                      Không có dữ liệu sườn đề
                    </div>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>ID</TableHead>
                          <TableHead>Loại</TableHead>
                          <TableHead>Bloom</TableHead>
                          <TableHead>Chương</TableHead>
                          <TableHead>Chủ đề</TableHead>
                          <TableHead>Độ khó</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {blueprint.map((slot, idx) => {
                          // Normalize fields that backend may return as objects instead of primitives
                          const difficulty = typeof slot.estimated_difficulty === 'number'
                            ? slot.estimated_difficulty
                            : 0
                          return (
                          <TableRow key={`${slot.question_id}-${idx}`}>
                            <TableCell className="font-mono text-sm">
                              {slot.question_id}
                            </TableCell>
                            <TableCell>
                              <QuestionTypeBadge type={typeof slot.type === 'string' ? slot.type : 'mcq'} />
                            </TableCell>
                            <TableCell>
                              <BloomBadge level={typeof slot.bloom_level === 'string' ? slot.bloom_level : 'thong_hieu'} />
                            </TableCell>
                            <TableCell className="max-w-[150px] truncate">
                              {typeof slot.chapter === 'string' ? slot.chapter : '-'}
                            </TableCell>
                            <TableCell className="max-w-[200px] truncate">
                              {typeof slot.topic_hint === 'string' ? slot.topic_hint : '-'}
                            </TableCell>
                            <TableCell>
                              <Progress
                                value={difficulty * 100}
                                className="w-16 h-2"
                              />
                            </TableCell>
                          </TableRow>
                        )})}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
                <CardFooter className="flex gap-3 border-t pt-4">
                  <Button onClick={handleApproveBlueprint} disabled={isBlueprintActing}>
                    <CheckCircle2 className="mr-2 h-4 w-4" />
                    Duyệt sườn đề
                  </Button>
                  <Button variant="outline" onClick={handleRejectBlueprint} disabled={isBlueprintActing}>
                    <XCircle className="mr-2 h-4 w-4" />
                    Từ chối
                  </Button>
                </CardFooter>
              </Card>
            </TabsContent>

            {/* Quality Tab */}
            <TabsContent value="quality">
              <div className="grid gap-6 lg:grid-cols-2">
                {/* Metrics */}
                <Card>
                  <CardHeader>
                    <CardTitle>Chỉ số chất lượng</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-6">
                    <MetricRow
                      icon={TrendingUp}
                      label="Điểm chất lượng"
                      value={exam.quality_score}
                      format={formatPercent}
                      good={0.8}
                    />
                    <MetricRow
                      icon={CheckCircle2}
                      label="Tỷ lệ đạt kiểm tra"
                      value={exam.verifier_pass_rate}
                      format={formatPercent}
                      good={0.8}
                    />
                    <MetricRow
                      icon={BookOpen}
                      label="Độ phủ bằng chứng"
                      value={exam.evidence_coverage_rate}
                      format={formatPercent}
                      good={0.9}
                    />
                    
                    {exam.cost_report && (
                      <div className="pt-4 border-t">
                        <p className="text-sm text-muted-foreground">Chi phí tạo đề</p>
                        <p className="text-2xl font-bold">
                          {formatCurrency(exam.cost_report.total_cost_usd)}
                        </p>
                        <p className="text-sm text-muted-foreground">
                          {exam.cost_report.total_tokens.toLocaleString()} tokens
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Warnings */}
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <AlertTriangle className="h-5 w-5 text-amber-500" />
                      Cảnh báo ({exam.warning_count || 0})
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {(exam.warning_count || 0) === 0 ? (
                      <div className="flex flex-col items-center justify-center py-8 text-center">
                        <CheckCircle2 className="h-12 w-12 text-primary/50 mb-4" />
                        <p className="text-muted-foreground">
                          Không có cảnh báo nào
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {exam.questions?.filter(q => q.validation_warnings?.length).map((q, idx) => (
                          <div key={`${q.id}-${idx}`} className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                            <p className="font-medium text-sm">{q.id}</p>
                            <ul className="mt-1 text-sm text-muted-foreground">
                              {q.validation_warnings?.map((w, i) => (
                                <li key={`${q.id}-warn-${i}`}>• {typeof w === 'string' ? w : JSON.stringify(w)}</li>
                              ))}
                            </ul>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            {/* History Tab */}
            <TabsContent value="history">
              <Card>
                <CardHeader>
                  <CardTitle>Lịch sử phiên bản</CardTitle>
                  <CardDescription>
                    Xem tất cả thay đổi của đề thi
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {versions.length === 0 ? (
                    <div className="text-center py-8 text-muted-foreground">
                      Chưa có lịch sử phiên bản
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {versions.map((version) => (
                        <div
                          key={version.id || `v${version.version_number}`}
                          className="flex items-start gap-4 p-4 rounded-lg border"
                        >
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted font-medium">
                            v{version.version_number}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <ChangeTypeBadge type={version.change_type} />
                              <span className="text-sm text-muted-foreground">
                                {formatDateTime(version.created_at)}
                              </span>
                            </div>
                            <p className="mt-1 text-sm">
                              {typeof version.change_description === 'string' ? version.change_description : JSON.stringify(version.change_description)}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  
                  <Button variant="outline" className="w-full mt-4" asChild>
                    <Link href={`/dashboard/exams/${id}/history`}>
                      Xem chi tiết lịch sử
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </main>

      {/* Publish Dialog */}
      <AlertDialog open={showPublishDialog} onOpenChange={setShowPublishDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xuất bản đề thi?</AlertDialogTitle>
            <AlertDialogDescription>
              Sau khi xuất bản, đề thi sẽ được đánh dấu hoàn thành.
              Bạn vẫn có thể chỉnh sửa sau đó.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={handlePublish}>
              Xuất bản
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Blueprint Action Dialog */}
      <AlertDialog open={showBlueprintActionDialog} onOpenChange={setShowBlueprintActionDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {blueprintAction === 'approve' ? 'Duyệt sườn đề?' : 'Từ chối sườn đề'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {blueprintAction === 'approve'
                ? 'Sau khi duyệt, hệ thống sẽ tiếp tục sinh câu hỏi.'
                : 'Nhập phản hồi để hệ thống tạo sườn đề mới phù hợp hơn.'}
            </AlertDialogDescription>
          </AlertDialogHeader>

          {blueprintAction === 'reject' && (
            <Textarea
              placeholder="Ví dụ: Tăng tỷ lệ câu khó lên 30%, tập trung vào bài tập tính toán..."
              value={blueprintFeedback}
              onChange={(e) => setBlueprintFeedback(e.target.value)}
              rows={3}
              className="mt-3"
            />
          )}

          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <Button
              onClick={handleBlueprintAction}
              disabled={isBlueprintActing || (blueprintAction === 'reject' && !blueprintFeedback.trim())}
            >
              {isBlueprintActing ? <Spinner className="mr-2" /> : null}
              {blueprintAction === 'approve' ? 'Duyệt' : 'Gửi phản hồi'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function QuestionCard({
  question,
  index,
  isEditing,
  editForm,
  setEditForm,
  isSaving,
  onStartEdit,
  onSave,
  onCancel,
}: {
  question: Question
  index: number
  isEditing: boolean
  editForm: Partial<Question>
  setEditForm: (form: Partial<Question>) => void
  isSaving: boolean
  onStartEdit: () => void
  onSave: () => void
  onCancel: () => void
}) {
  return (
    <Card className={cn(
      "transition-all",
      isEditing && "ring-2 ring-primary"
    )}>
      <CardContent className="pt-6">
        <div className="flex items-start gap-4">
          {/* Question Number */}
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary font-medium">
            {index}
          </div>

          <div className="flex-1 min-w-0 space-y-3">
            {/* Header */}
            <div className="flex flex-wrap items-center gap-2">
              <QuestionTypeBadge type={typeof question.type === 'string' ? question.type : 'mcq'} />
              <BloomBadge level={typeof question.bloom_level === 'string' ? question.bloom_level : 'thong_hieu'} />
              {typeof question.quality_score === 'number' && (
                <Badge variant="outline" className={
                  question.quality_score >= 0.8 ? 'text-primary' : 'text-amber-500'
                }>
                  {formatPercent(question.quality_score)}
                </Badge>
              )}
              {question.validation_warnings?.length > 0 && (
                <Badge variant="outline" className="text-amber-500">
                  <AlertTriangle className="mr-1 h-3 w-3" />
                  {question.validation_warnings.length} cảnh báo
                </Badge>
              )}
            </div>

            {/* Content */}
            {isEditing ? (
              <FieldGroup>
                <Field>
                  <FieldLabel>Nội dung câu hỏi</FieldLabel>
                  <Textarea
                    value={editForm.content || ''}
                    onChange={(e) => setEditForm({ ...editForm, content: e.target.value })}
                    rows={3}
                  />
                </Field>

                {question.type === 'mcq' && (
                  <>
                    <Field>
                      <FieldLabel>Đáp án A</FieldLabel>
                      <Input
                        value={editForm.options?.A || ''}
                        onChange={(e) => setEditForm({
                          ...editForm,
                          options: { ...editForm.options, A: e.target.value }
                        })}
                      />
                    </Field>
                    <Field>
                      <FieldLabel>Đáp án B</FieldLabel>
                      <Input
                        value={editForm.options?.B || ''}
                        onChange={(e) => setEditForm({
                          ...editForm,
                          options: { ...editForm.options, B: e.target.value }
                        })}
                      />
                    </Field>
                    <Field>
                      <FieldLabel>Đáp án C</FieldLabel>
                      <Input
                        value={editForm.options?.C || ''}
                        onChange={(e) => setEditForm({
                          ...editForm,
                          options: { ...editForm.options, C: e.target.value }
                        })}
                      />
                    </Field>
                    <Field>
                      <FieldLabel>Đáp án D</FieldLabel>
                      <Input
                        value={editForm.options?.D || ''}
                        onChange={(e) => setEditForm({
                          ...editForm,
                          options: { ...editForm.options, D: e.target.value }
                        })}
                      />
                    </Field>
                    <Field>
                      <FieldLabel>Đáp án đúng</FieldLabel>
                      <Select
                        value={editForm.correct_answer || ''}
                        onValueChange={(v) => setEditForm({ ...editForm, correct_answer: v })}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="A">A</SelectItem>
                          <SelectItem value="B">B</SelectItem>
                          <SelectItem value="C">C</SelectItem>
                          <SelectItem value="D">D</SelectItem>
                        </SelectContent>
                      </Select>
                    </Field>
                  </>
                )}

                {question.type === 'essay' && (
                  <Field>
                    <FieldLabel>Rubric chấm điểm</FieldLabel>
                    <Textarea
                      value={editForm.rubric || ''}
                      onChange={(e) => setEditForm({ ...editForm, rubric: e.target.value })}
                      rows={4}
                    />
                  </Field>
                )}

                <Field>
                  <FieldLabel>Bloom Level</FieldLabel>
                  <Select
                    value={editForm.bloom_level || ''}
                    onValueChange={(v) => setEditForm({ ...editForm, bloom_level: v as BloomLevel })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(Object.keys(BLOOM_LABELS) as BloomLevel[]).map((level) => (
                        <SelectItem key={level} value={level}>
                          {BLOOM_LABELS[level]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </FieldGroup>
            ) : (
              <>
                <p className="text-sm whitespace-pre-wrap">{typeof question.content === 'string' ? question.content : JSON.stringify(question.content)}</p>

                {question.type === 'mcq' && question.options && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {Object.entries(question.options).map(([key, value]) => (
                      <div
                      key={key}
                      className={cn(
                        "p-2 rounded-md text-sm",
                        key === question.correct_answer
                          ? "bg-primary/10 text-primary border border-primary/20"
                          : "bg-muted"
                      )}
                    >
                      <span className="font-medium">{key}.</span> {typeof value === 'string' ? value : JSON.stringify(value)}
                    </div>
                  ))}
                  </div>
                )}

                {question.type === 'essay' && question.rubric && (
                  <div className="p-3 rounded-md bg-muted text-sm">
                    <p className="font-medium mb-1">Rubric:</p>
                    <p className="whitespace-pre-wrap text-muted-foreground">{typeof question.rubric === 'string' ? question.rubric : JSON.stringify(question.rubric)}</p>
                  </div>
                )}

                {question.explanation && (
                  <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-800 dark:bg-blue-950/30">
                    <p className="text-xs font-medium uppercase tracking-wide text-blue-600 dark:text-blue-400">Giải thích</p>
                    <p className="mt-1 text-sm text-foreground">{question.explanation}</p>
                  </div>
                )}

                {question.source_evidence && question.source_evidence.length > 0 && (
                  <div className="mt-3 rounded-lg border bg-muted/30 p-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Nguồn bằng chứng</p>
                    <div className="mt-2 space-y-2">
                      {question.source_evidence.map((ev: Record<string, unknown>, i: number) => (
                        <div key={i} className="text-xs text-muted-foreground">
                          {ev.chunk_id ? <Badge variant="outline" className="mr-1 text-[10px]">{String(ev.chunk_id)}</Badge> : null}
                          {ev.page ? <span className="mr-1">Trang {String(ev.page)}</span> : null}
                          {ev.chapter_number ? <span className="mr-1">Chương {String(ev.chapter_number)}</span> : null}
                          {ev.text_preview ? <p className="mt-1 text-foreground/80">{String(ev.text_preview).slice(0, 120)}...</p> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {/* Actions */}
            <div className="flex items-center gap-2 pt-2">
              {isEditing ? (
                <>
                  <Button size="sm" onClick={onSave} disabled={isSaving}>
                    {isSaving ? <Spinner className="mr-2" /> : <Check className="mr-2 h-4 w-4" />}
                    Lưu
                  </Button>
                  <Button size="sm" variant="outline" onClick={onCancel}>
                    <X className="mr-2 h-4 w-4" />
                    Hủy
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="outline" onClick={onStartEdit}>
                  <Edit3 className="mr-2 h-4 w-4" />
                  Sửa
                </Button>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function MetricRow({
  icon: Icon,
  label,
  value,
  format,
  good,
}: {
  icon: React.ElementType
  label: string
  value?: number
  format: (v: number) => string
  good: number
}) {
  const isGood = value !== undefined && value >= good

  return (
    <div className="flex items-center gap-4">
      <div className={cn(
        "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
        isGood ? "bg-primary/10 text-primary" : "bg-amber-500/10 text-amber-500"
      )}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="flex-1">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="text-xl font-semibold">
          {value !== undefined ? format(value) : '-'}
        </p>
      </div>
      <Progress 
        value={(value || 0) * 100} 
        className="w-24 h-2"
      />
    </div>
  )
}
