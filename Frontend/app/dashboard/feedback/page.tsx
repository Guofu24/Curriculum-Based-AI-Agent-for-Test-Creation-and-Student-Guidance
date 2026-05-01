"use client"

import { useState, useEffect, useCallback } from 'react'
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
  RefreshCw,
} from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import { feedbackApi, FeedbackEvent } from '@/lib/api'

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
  validation_warning: {
    label: 'Cảnh báo validation',
    icon: AlertTriangle,
    color: 'text-yellow-500 bg-yellow-500/10 border-yellow-500/20',
  },
  generation_error: {
    label: 'Lỗi sinh câu hỏi',
    icon: XCircle,
    color: 'text-red-500 bg-red-500/10 border-red-500/20',
  },
  publish: {
    label: 'Xuất bản',
    icon: CheckCircle2,
    color: 'text-green-500 bg-green-500/10 border-green-500/20',
  },
  edit_applied: {
    label: 'Đã chỉnh sửa',
    icon: Copy,
    color: 'text-blue-500 bg-blue-500/10 border-blue-500/20',
  },
} as const

export default function FeedbackPage() {
  const [filter, setFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | 'resolved' | 'unresolved'>('all')
  const [feedbackItems, setFeedbackItems] = useState<FeedbackEvent[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isError, setIsError] = useState(false)
  const [page, setPage] = useState(1)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const LIMIT = 50

  const fetchFeedback = useCallback(async (refresh = false) => {
    if (refresh) setIsRefreshing(true)
    else setIsLoading(true)
    setIsError(false)
    try {
      const reviewStatusParam = statusFilter === 'all' ? undefined
        : statusFilter === 'resolved' ? 'accepted,rejected,corrected' : 'pending'
      const signalTypeParam = filter === 'all' ? undefined : filter
      const res = await feedbackApi.list(page, LIMIT, signalTypeParam, reviewStatusParam || undefined)
      setFeedbackItems(res.items)
      setTotal(res.total)
    } catch {
      setIsError(true)
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [filter, statusFilter, page])

  useEffect(() => { fetchFeedback() }, [fetchFeedback])

  // Stats computed from all loaded items
  const stats = {
    total: total || feedbackItems.length,
    unresolved: feedbackItems.filter(f => !f.resolved).length,
    byType: Object.fromEntries(
      Object.keys(signalTypeConfig).map(t => [t, feedbackItems.filter(f => f.signal_type === t).length])
    ),
  }

  return (
    <>
      <DashboardHeader breadcrumbs={[{ label: 'Phản hồi' }]} />
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Kho phản hồi</h1>
              <p className="text-muted-foreground">
                Tín hiệu chất lượng từ AI pipeline
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => fetchFeedback(true)} disabled={isRefreshing}>
              <RefreshCw className={cn("h-4 w-4 mr-2", isRefreshing && "animate-spin")} />
              Làm mới
            </Button>
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
                  <Select value={filter} onValueChange={(v) => { setFilter(v); setPage(1) }}>
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
                  <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v as 'all' | 'resolved' | 'unresolved'); setPage(1) }}>
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
                  Hiển thị: {feedbackItems.length} / {total} phản hồi
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
              {isLoading ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <RefreshCw className="h-8 w-8 text-muted-foreground/50 mb-4 animate-spin" />
                  <p className="text-muted-foreground">Đang tải phản hồi...</p>
                </div>
              ) : isError ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <XCircle className="h-8 w-8 text-destructive mb-4" />
                  <p className="text-destructive font-medium mb-2">Không thể tải phản hồi</p>
                  <Button variant="outline" size="sm" onClick={() => fetchFeedback(true)}>
                    Thử lại
                  </Button>
                </div>
              ) : feedbackItems.length === 0 ? (
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
                    {feedbackItems.map((feedback) => {
                      const config = signalTypeConfig[feedback.signal_type as keyof typeof signalTypeConfig]
                      if (!config) return null
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
                              {feedback.exam_title || feedback.exam_id}
                            </Link>
                          </TableCell>
                          <TableCell className="hidden lg:table-cell text-muted-foreground text-sm">
                            {formatDateTime(feedback.created_at || feedback.timestamp || '')}
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
