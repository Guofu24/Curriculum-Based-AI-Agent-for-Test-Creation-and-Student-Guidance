"use client"

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Empty } from '@/components/ui/empty'
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination'
import {
  ClipboardList,
  Sparkles,
  Trash2,
  Eye,
  FileText,
  AlertTriangle,
} from 'lucide-react'
import { toast } from 'sonner'
import { examsApi, Exam, ExamStatus } from '@/lib/api'
import { StatusBadge } from '@/components/status-badge'
import { formatDateTime, formatPercent } from '@/lib/format'

const ITEMS_PER_PAGE = 10

export default function ExamsPage() {
  const [exams, setExams] = useState<Exam[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<ExamStatus | 'all'>('all')
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    async function fetchExams() {
      setIsLoading(true)
      try {
        const status = statusFilter === 'all' ? undefined : statusFilter
        const response = await examsApi.list(page, ITEMS_PER_PAGE, status)
        setExams(response.items ?? [])
        setTotal(response.total)
      } catch (error) {
        console.error('Failed to fetch exams:', error)
        toast.error('Không thể tải danh sách đề thi')
      } finally {
        setIsLoading(false)
      }
    }

    fetchExams()
  }, [page, statusFilter])

  const handleDelete = async (exam: Exam) => {
    try {
      await examsApi.delete(exam.id)
      setExams(prev => prev.filter(e => e.id !== exam.id))
      setTotal(prev => prev - 1)
      toast.success('Đã xóa đề thi')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Xóa thất bại')
    }
  }

  const totalPages = Math.ceil(total / ITEMS_PER_PAGE)

  return (
    <>
      <DashboardHeader breadcrumbs={[{ label: 'Đề thi' }]} />
      
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Header */}
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Đề thi</h1>
              <p className="text-muted-foreground">
                Quản lý tất cả đề thi đã tạo
              </p>
            </div>
            <Button asChild>
              <Link href="/dashboard/generate">
                <Sparkles className="mr-2 h-4 w-4" />
                Tạo đề mới
              </Link>
            </Button>
          </div>

          {/* Filters */}
          <Card>
            <CardContent className="py-4">
              <div className="flex items-center gap-4">
                <span className="text-sm text-muted-foreground">Lọc theo:</span>
                <Select
                  value={statusFilter}
                  onValueChange={(value) => {
                    setStatusFilter(value as ExamStatus | 'all')
                    setPage(1)
                  }}
                >
                  <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Trạng thái" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tất cả</SelectItem>
                    <SelectItem value="draft">Nháp</SelectItem>
                    <SelectItem value="ready_for_review">Chờ duyệt</SelectItem>
                    <SelectItem value="regenerating">Đang tạo lại</SelectItem>
                    <SelectItem value="published">Đã xuất bản</SelectItem>
                  </SelectContent>
                </Select>
                
                <span className="text-sm text-muted-foreground ml-auto">
                  Tổng: {total} đề thi
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Exams Table */}
          <Card>
            <CardContent className="p-0">
              {isLoading ? (
                <div className="p-6 space-y-4">
                  {[...Array(5)].map((_, i) => (
                    <Skeleton key={i} className="h-16 w-full" />
                  ))}
                </div>
              ) : exams.length === 0 ? (
                <Empty
                  icon={ClipboardList}
                  title="Chưa có đề thi nào"
                  description={
                    statusFilter !== 'all'
                      ? "Không có đề thi nào với trạng thái này"
                      : "Tạo đề thi đầu tiên để bắt đầu"
                  }
                >
                  {statusFilter === 'all' && (
                    <Button className="mt-4" asChild>
                      <Link href="/dashboard/generate">
                        <Sparkles className="mr-2 h-4 w-4" />
                        Tạo đề đầu tiên
                      </Link>
                    </Button>
                  )}
                </Empty>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tiêu đề</TableHead>
                      <TableHead>Loại</TableHead>
                      <TableHead className="hidden sm:table-cell">Trạng thái</TableHead>
                      <TableHead className="hidden md:table-cell">Số câu</TableHead>
                      <TableHead className="hidden lg:table-cell">Chất lượng</TableHead>
                      <TableHead className="hidden lg:table-cell">Cảnh báo</TableHead>
                      <TableHead className="hidden xl:table-cell">Ngày tạo</TableHead>
                      <TableHead className="w-[100px]">Thao tác</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {exams.map((exam) => (
                      <TableRow key={exam.id}>
                        <TableCell>
                          <div className="flex items-center gap-3">
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                              <FileText className="h-5 w-5 text-primary" />
                            </div>
                            <div className="min-w-0">
                              <Link
                                href={`/dashboard/exams/${exam.id}`}
                                className="font-medium hover:text-primary truncate block max-w-[200px]"
                              >
                                {exam.title}
                              </Link>
                              <p className="text-xs text-muted-foreground sm:hidden">
                                <StatusBadge status={exam.status} />
                              </p>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <span className="text-sm capitalize">
                            {exam.exam_type === 'mcq' && 'Trắc nghiệm'}
                            {exam.exam_type === 'essay' && 'Tự luận'}
                            {exam.exam_type === 'mixed' && 'Kết hợp'}
                          </span>
                        </TableCell>
                        <TableCell className="hidden sm:table-cell">
                          <StatusBadge status={exam.status} />
                        </TableCell>
                        <TableCell className="hidden md:table-cell">
                          {exam.total_questions ?? ((exam.mcq_count ?? 0) + (exam.essay_count ?? 0))}
                        </TableCell>
                        <TableCell className="hidden lg:table-cell">
                          {exam.quality_score !== undefined ? (
                            <span className={exam.quality_score >= 0.8 ? 'text-primary' : 'text-amber-500'}>
                              {formatPercent(exam.quality_score)}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                        </TableCell>
                        <TableCell className="hidden lg:table-cell">
                          {exam.warning_count !== undefined && exam.warning_count > 0 ? (
                            <span className="flex items-center gap-1 text-amber-500">
                              <AlertTriangle className="h-4 w-4" />
                              {exam.warning_count}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">0</span>
                          )}
                        </TableCell>
                        <TableCell className="hidden xl:table-cell text-muted-foreground">
                          {formatDateTime(exam.created_at)}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <Button variant="ghost" size="icon" asChild>
                              <Link href={`/dashboard/exams/${exam.id}`}>
                                <Eye className="h-4 w-4" />
                              </Link>
                            </Button>
                            
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive">
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>Xóa đề thi?</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    Bạn có chắc muốn xóa &quot;{exam.title}&quot;? 
                                    Hành động này không thể hoàn tác.
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>Hủy</AlertDialogCancel>
                                  <AlertDialogAction
                                    onClick={() => handleDelete(exam)}
                                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                  >
                                    Xóa
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Pagination */}
          {totalPages > 1 && (
            <Pagination>
              <PaginationContent>
                <PaginationItem>
                  <PaginationPrevious 
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    className={page === 1 ? 'pointer-events-none opacity-50' : 'cursor-pointer'}
                  />
                </PaginationItem>
                
                {[...Array(Math.min(totalPages, 5))].map((_, i) => {
                  const pageNum = i + 1
                  return (
                    <PaginationItem key={pageNum}>
                      <PaginationLink
                        onClick={() => setPage(pageNum)}
                        isActive={page === pageNum}
                        className="cursor-pointer"
                      >
                        {pageNum}
                      </PaginationLink>
                    </PaginationItem>
                  )
                })}
                
                <PaginationItem>
                  <PaginationNext
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    className={page === totalPages ? 'pointer-events-none opacity-50' : 'cursor-pointer'}
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          )}
        </div>
      </main>
    </>
  )
}
