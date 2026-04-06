"use client"

import { useEffect, useState, use } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
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
  History,
  RotateCcw,
  Eye,
  ArrowLeft,
  FileText,
} from 'lucide-react'
import { toast } from 'sonner'
import { examsApi, Exam, ExamVersion } from '@/lib/api'
import { ChangeTypeBadge } from '@/components/status-badge'
import { formatDateTime } from '@/lib/format'

interface PageParams {
  id: string
}

export default function ExamHistoryPage({ params }: { params: Promise<PageParams> }) {
  const { id } = use(params)
  const router = useRouter()
  const [exam, setExam] = useState<Exam | null>(null)
  const [history, setHistory] = useState<ExamVersion[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [restoreTarget, setRestoreTarget] = useState<ExamVersion | null>(null)

  useEffect(() => {
    async function fetchData() {
      try {
        const [examRes, historyRes] = await Promise.all([
          examsApi.get(id),
          examsApi.getHistory(id).catch(() => []),
        ])
        
        setExam(examRes)
        setHistory(historyRes)
      } catch (error) {
        console.error('Failed to fetch history:', error)
        toast.error('Không thể tải lịch sử')
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [id])

  const handleRestore = async (version: ExamVersion) => {
    try {
      await examsApi.restoreVersion(id, version.id)
      toast.success(`Đã khôi phục về phiên bản ${version.version_number}`)
      setRestoreTarget(null)
      // Refresh data
      const [examRes, historyRes] = await Promise.all([
        examsApi.get(id),
        examsApi.getHistory(id),
      ])
      setExam(examRes)
      setHistory(historyRes)
    } catch (error) {
      toast.error('Khôi phục thất bại')
    }
  }

  if (isLoading) {
    return (
      <>
        <DashboardHeader breadcrumbs={[
          { label: 'Đề thi', href: '/dashboard/exams' },
          { label: 'Đang tải...' },
          { label: 'Lịch sử' }
        ]} />
        <main className="flex-1 overflow-auto">
          <div className="container mx-auto p-6 space-y-6">
            <Skeleton className="h-10 w-64" />
            <Skeleton className="h-[400px] w-full" />
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

  return (
    <>
      <DashboardHeader breadcrumbs={[
        { label: 'Đề thi', href: '/dashboard/exams' },
        { label: exam.title, href: `/dashboard/exams/${id}` },
        { label: 'Lịch sử' }
      ]} />
      
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Header */}
          <div className="flex items-center gap-4">
            <Button variant="outline" size="icon" asChild>
              <Link href={`/dashboard/exams/${id}`}>
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <div>
              <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
                <History className="h-6 w-6" />
                Lịch sử phiên bản
              </h1>
              <p className="text-muted-foreground">{exam.title}</p>
            </div>
          </div>

          {/* Timeline */}
          <Card>
            <CardHeader>
              <CardTitle>Dòng thời gian</CardTitle>
              <CardDescription>
                {history.length} phiên bản đã lưu
              </CardDescription>
            </CardHeader>
            <CardContent>
              {history.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <History className="h-12 w-12 text-muted-foreground/50 mb-4" />
                  <p className="text-muted-foreground">
                    Chưa có lịch sử phiên bản
                  </p>
                </div>
              ) : (
                <div className="relative">
                  {/* Timeline line */}
                  <div className="absolute left-5 top-0 bottom-0 w-px bg-border" />
                  
                  <div className="space-y-6">
                    {history.map((version, index) => (
                      <div key={version.id} className="relative flex gap-4">
                        {/* Timeline dot */}
                        <div className="relative flex h-10 w-10 shrink-0 items-center justify-center">
                          <div className={`h-4 w-4 rounded-full border-2 ${
                            index === 0 
                              ? 'bg-primary border-primary' 
                              : 'bg-background border-muted-foreground'
                          }`} />
                        </div>

                        {/* Content */}
                        <div className="flex-1 pb-6">
                          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 p-4 rounded-lg border bg-card">
                            <div className="space-y-1">
                              <div className="flex items-center gap-2">
                                <span className="font-semibold">
                                  Phiên bản {version.version_number}
                                </span>
                                <ChangeTypeBadge type={version.change_type} />
                              </div>
                              <p className="text-sm text-muted-foreground">
                                {version.change_description}
                              </p>
                              <p className="text-xs text-muted-foreground">
                                {formatDateTime(version.created_at)}
                              </p>
                            </div>

                            <div className="flex items-center gap-2">
                              <Button variant="outline" size="sm">
                                <Eye className="mr-2 h-4 w-4" />
                                Xem
                              </Button>
                              {index > 0 && (
                                <Button 
                                  variant="outline" 
                                  size="sm"
                                  onClick={() => setRestoreTarget(version)}
                                >
                                  <RotateCcw className="mr-2 h-4 w-4" />
                                  Khôi phục
                                </Button>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </main>

      {/* Restore Dialog */}
      <AlertDialog 
        open={!!restoreTarget} 
        onOpenChange={() => setRestoreTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Khôi phục phiên bản?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn khôi phục về phiên bản {restoreTarget?.version_number}? 
              Phiên bản hiện tại sẽ được lưu lại trong lịch sử.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={() => restoreTarget && handleRestore(restoreTarget)}>
              Khôi phục
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
