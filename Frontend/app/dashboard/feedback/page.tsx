"use client"

import { useState } from 'react'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  MessageSquare,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Copy,
  TrendingDown,
  Eye,
} from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import Link from 'next/link'
import { cn } from '@/lib/utils'

// MOCK: Feedback data (backend returns empty)
interface FeedbackEvent {
  id: string
  exam_id: string
  exam_title: string
  timestamp: string
  signal_type: 'bloom_mismatch' | 'out_of_scope' | 'duplicate' | 'quality_low' | 'answer_incorrect'
  description: string
  resolved: boolean
}

const MOCK_FEEDBACK: FeedbackEvent[] = [
  {
    id: '1',
    exam_id: 'exam-001',
    exam_title: 'Đề kiểm tra Vật lý Chương 1-2',
    timestamp: '2026-04-04T10:00:00Z',
    signal_type: 'bloom_mismatch',
    description: "Câu hỏi MCQ_003 có bloom_level 'thong_hieu' nhưng nội dung phù hợp 'nhan_biet'",
    resolved: false,
  },
  {
    id: '2',
    exam_id: 'exam-001',
    exam_title: 'Đề kiểm tra Vật lý Chương 1-2',
    timestamp: '2026-04-04T10:05:00Z',
    signal_type: 'out_of_scope',
    description: 'Câu hỏi ESSAY_001 vượt phạm vi: tham khảo nội dung từ Chương 3 không nằm trong scope',
    resolved: false,
  },
  {
    id: '3',
    exam_id: 'exam-002',
    exam_title: 'Đề thi Hóa học giữa kỳ',
    timestamp: '2026-04-03T14:30:00Z',
    signal_type: 'duplicate',
    description: 'Câu MCQ_005 và MCQ_008 có nội dung tương tự (similarity: 87%)',
    resolved: true,
  },
  {
    id: '4',
    exam_id: 'exam-002',
    exam_title: 'Đề thi Hóa học giữa kỳ',
    timestamp: '2026-04-03T14:35:00Z',
    signal_type: 'quality_low',
    description: 'Câu MCQ_010 có quality_score thấp (0.45) do thiếu bằng chứng từ tài liệu',
    resolved: false,
  },
  {
    id: '5',
    exam_id: 'exam-003',
    exam_title: 'Bài kiểm tra 15 phút Toán',
    timestamp: '2026-04-02T09:15:00Z',
    signal_type: 'answer_incorrect',
    description: 'Đáp án câu MCQ_002 có thể không chính xác: A = 15, nhưng tính toán cho ra 16',
    resolved: false,
  },
]

const signalTypeConfig = {
  bloom_mismatch: {
    label: 'Bloom không khớp',
    icon: AlertTriangle,
    color: 'text-amber-500 bg-amber-500/10 border-amber-500/20',
  },
  out_of_scope: {
    label: 'Ngoài phạm vi',
    icon: XCircle,
    color: 'text-red-500 bg-red-500/10 border-red-500/20',
  },
  duplicate: {
    label: 'Trùng lặp',
    icon: Copy,
    color: 'text-purple-500 bg-purple-500/10 border-purple-500/20',
  },
  quality_low: {
    label: 'Chất lượng thấp',
    icon: TrendingDown,
    color: 'text-orange-500 bg-orange-500/10 border-orange-500/20',
  },
  answer_incorrect: {
    label: 'Đáp án sai',
    icon: XCircle,
    color: 'text-destructive bg-destructive/10 border-destructive/20',
  },
}

export default function FeedbackPage() {
  const [filter, setFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | 'resolved' | 'unresolved'>('all')

  const filteredFeedback = MOCK_FEEDBACK.filter((f) => {
    if (filter !== 'all' && f.signal_type !== filter) return false
    if (statusFilter === 'resolved' && !f.resolved) return false
    if (statusFilter === 'unresolved' && f.resolved) return false
    return true
  })

  const stats = {
    total: MOCK_FEEDBACK.length,
    unresolved: MOCK_FEEDBACK.filter((f) => !f.resolved).length,
    byType: Object.keys(signalTypeConfig).reduce((acc, type) => {
      acc[type] = MOCK_FEEDBACK.filter((f) => f.signal_type === type).length
      return acc
    }, {} as Record<string, number>),
  }

  return (
    <>
      <DashboardHeader breadcrumbs={[{ label: 'Phản hồi' }]} />
      
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Header */}
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Kho phản hồi</h1>
            <p className="text-muted-foreground">
              Tín hiệu chất lượng từ AI pipeline
            </p>
          </div>

          {/* Stats Cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
                    <MessageSquare className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Tổng phản hồi</p>
                    <p className="text-2xl font-bold">{stats.total}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-500/10">
                    <AlertTriangle className="h-5 w-5 text-amber-500" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Chưa xử lý</p>
                    <p className="text-2xl font-bold">{stats.unresolved}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <CheckCircle2 className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Đã xử lý</p>
                    <p className="text-2xl font-bold">{stats.total - stats.unresolved}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-destructive/10">
                    <XCircle className="h-5 w-5 text-destructive" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Đáp án sai</p>
                    <p className="text-2xl font-bold">{stats.byType.answer_incorrect || 0}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Filters */}
          <Card>
            <CardContent className="py-4">
              <div className="flex flex-wrap items-center gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">Loại:</span>
                  <Select value={filter} onValueChange={setFilter}>
                    <SelectTrigger className="w-[180px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Tất cả</SelectItem>
                      <SelectItem value="bloom_mismatch">Bloom không khớp</SelectItem>
                      <SelectItem value="out_of_scope">Ngoài phạm vi</SelectItem>
                      <SelectItem value="duplicate">Trùng lặp</SelectItem>
                      <SelectItem value="quality_low">Chất lượng thấp</SelectItem>
                      <SelectItem value="answer_incorrect">Đáp án sai</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">Trạng thái:</span>
                  <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as 'all' | 'resolved' | 'unresolved')}>
                    <SelectTrigger className="w-[150px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Tất cả</SelectItem>
                      <SelectItem value="unresolved">Chưa xử lý</SelectItem>
                      <SelectItem value="resolved">Đã xử lý</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <span className="ml-auto text-sm text-muted-foreground">
                  Hiển thị: {filteredFeedback.length} phản hồi
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Feedback Table */}
          <Card>
            <CardHeader>
              <CardTitle>Danh sách phản hồi</CardTitle>
              <CardDescription>
                Tín hiệu chất lượng từ quá trình tạo đề
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {filteredFeedback.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <MessageSquare className="h-12 w-12 text-muted-foreground/50 mb-4" />
                  <p className="text-muted-foreground">
                    Không có phản hồi nào
                  </p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Loại</TableHead>
                      <TableHead>Mô tả</TableHead>
                      <TableHead className="hidden md:table-cell">Đề thi</TableHead>
                      <TableHead className="hidden lg:table-cell">Thời gian</TableHead>
                      <TableHead>Trạng thái</TableHead>
                      <TableHead className="w-[80px]"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredFeedback.map((feedback) => {
                      const config = signalTypeConfig[feedback.signal_type]
                      const Icon = config.icon

                      return (
                        <TableRow key={feedback.id}>
                          <TableCell>
                            <Badge 
                              variant="outline" 
                              className={cn("gap-1", config.color)}
                            >
                              <Icon className="h-3 w-3" />
                              {config.label}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <p className="text-sm max-w-[400px]">{feedback.description}</p>
                          </TableCell>
                          <TableCell className="hidden md:table-cell">
                            <Link 
                              href={`/dashboard/exams/${feedback.exam_id}`}
                              className="text-sm text-primary hover:underline"
                            >
                              {feedback.exam_title}
                            </Link>
                          </TableCell>
                          <TableCell className="hidden lg:table-cell text-muted-foreground text-sm">
                            {formatDateTime(feedback.timestamp)}
                          </TableCell>
                          <TableCell>
                            {feedback.resolved ? (
                              <Badge variant="outline" className="text-primary bg-primary/10 border-primary/20">
                                <CheckCircle2 className="mr-1 h-3 w-3" />
                                Đã xử lý
                              </Badge>
                            ) : (
                              <Badge variant="outline" className="text-amber-500 bg-amber-500/10 border-amber-500/20">
                                <AlertTriangle className="mr-1 h-3 w-3" />
                                Chờ xử lý
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell>
                            <Button variant="ghost" size="icon" asChild>
                              <Link href={`/dashboard/exams/${feedback.exam_id}`}>
                                <Eye className="h-4 w-4" />
                              </Link>
                            </Button>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </main>
    </>
  )
}
