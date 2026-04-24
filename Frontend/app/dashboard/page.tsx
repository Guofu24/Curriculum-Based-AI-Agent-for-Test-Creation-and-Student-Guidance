"use client"

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import { Area, AreaChart, XAxis, YAxis, CartesianGrid } from 'recharts'
import {
  ClipboardList,
  FileText,
  TrendingUp,
  AlertTriangle,
  Sparkles,
  ArrowRight,
  Eye,
} from 'lucide-react'
import { examsApi, Exam, QualitySummary } from '@/lib/api'
import { StatusBadge } from '@/components/status-badge'
import { formatDate } from '@/lib/format'

// MOCK: Quality summary data (backend may return empty)
const MOCK_QUALITY_SUMMARY: QualitySummary = {
  total_exams: 12,
  avg_quality_score: 0.82,
  avg_verifier_pass_rate: 0.78,
  avg_evidence_coverage_rate: 0.91,
  warning_count: 5,
  timeline: [
    { date: '2026-03-28', quality_score: 0.75, pass_rate: 0.70 },
    { date: '2026-03-29', quality_score: 0.77, pass_rate: 0.72 },
    { date: '2026-03-30', quality_score: 0.80, pass_rate: 0.75 },
    { date: '2026-03-31', quality_score: 0.82, pass_rate: 0.78 },
    { date: '2026-04-01', quality_score: 0.84, pass_rate: 0.80 },
    { date: '2026-04-02', quality_score: 0.85, pass_rate: 0.80 },
    { date: '2026-04-03', quality_score: 0.86, pass_rate: 0.82 },
    { date: '2026-04-04', quality_score: 0.88, pass_rate: 0.85 },
  ],
}

const chartConfig = {
  quality_score: {
    label: 'Chất lượng',
    color: 'var(--color-chart-1)',
  },
  pass_rate: {
    label: 'Tỷ lệ đạt',
    color: 'var(--color-chart-2)',
  },
} satisfies ChartConfig

export default function DashboardPage() {
  const [recentExams, setRecentExams] = useState<Exam[]>([])
  const [qualitySummary, setQualitySummary] = useState<QualitySummary | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    async function fetchData() {
      try {
        const [examsRes, qualityRes] = await Promise.allSettled([
          examsApi.list(1, 5),
          examsApi.getQualitySummary(),
        ])

        if (examsRes.status === 'fulfilled') {
          setRecentExams(examsRes.value.items ?? [])
        }

        if (qualityRes.status === 'fulfilled') {
          setQualitySummary(qualityRes.value)
        } else {
          // Use mock data if API fails
          setQualitySummary(MOCK_QUALITY_SUMMARY)
        }
      } catch {
        // Use mock data on error
        setQualitySummary(MOCK_QUALITY_SUMMARY)
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [])

  const stats = qualitySummary || MOCK_QUALITY_SUMMARY

  return (
    <>
      <DashboardHeader />
      
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Welcome Section */}
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
              <p className="text-muted-foreground">
                Tổng quan hệ thống tạo đề thi tự động
              </p>
            </div>
            <Button asChild>
              <Link href="/dashboard/generate">
                <Sparkles className="mr-2 h-4 w-4" />
                Tạo đề mới
              </Link>
            </Button>
          </div>

          {/* Stats Cards */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <StatsCard
              title="Tổng đề thi"
              value={isLoading ? null : stats.total_exams}
              icon={ClipboardList}
              description="Đề đã tạo"
            />
            <StatsCard
              title="Chất lượng TB"
              value={isLoading ? null : `${Math.round(stats.avg_quality_score * 100)}%`}
              icon={TrendingUp}
              description="Điểm chất lượng"
              trend={stats.avg_quality_score > 0.8 ? 'up' : undefined}
            />
            <StatsCard
              title="Tỷ lệ đạt"
              value={isLoading ? null : `${Math.round(stats.avg_verifier_pass_rate * 100)}%`}
              icon={FileText}
              description="Qua kiểm tra AI"
            />
            <StatsCard
              title="Cảnh báo"
              value={isLoading ? null : stats.warning_count}
              icon={AlertTriangle}
              description="Cần xem lại"
              variant={stats.warning_count > 0 ? 'warning' : 'default'}
            />
          </div>

          {/* Charts and Recent Exams */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Quality Trend Chart */}
            <Card>
              <CardHeader>
                <CardTitle>Xu hướng chất lượng</CardTitle>
                <CardDescription>
                  Điểm chất lượng và tỷ lệ đạt qua thời gian
                </CardDescription>
              </CardHeader>
              <CardContent>
                {isLoading ? (
                  <Skeleton className="h-[300px] w-full" />
                ) : (
                  <ChartContainer config={chartConfig} className="h-[300px] w-full">
                    <AreaChart data={stats.timeline ?? []}>
                        <defs>
                          <linearGradient id="colorQuality" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="var(--color-chart-1)" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="var(--color-chart-1)" stopOpacity={0} />
                          </linearGradient>
                          <linearGradient id="colorPass" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="var(--color-chart-2)" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="var(--color-chart-2)" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                        <XAxis 
                          dataKey="date" 
                          tickFormatter={(value) => {
                            const date = new Date(value)
                            return `${date.getDate()}/${date.getMonth() + 1}`
                          }}
                          className="text-xs"
                        />
                        <YAxis 
                          tickFormatter={(value) => `${Math.round(value * 100)}%`}
                          domain={[0.5, 1]}
                          className="text-xs"
                        />
                        <ChartTooltip 
                          content={<ChartTooltipContent 
                            formatter={(value) => `${Math.round(Number(value) * 100)}%`}
                          />} 
                        />
                        <Area
                          type="monotone"
                          dataKey="quality_score"
                          name="Chất lượng"
                          stroke="var(--color-chart-1)"
                          fillOpacity={1}
                          fill="url(#colorQuality)"
                          strokeWidth={2}
                        />
                        <Area
                          type="monotone"
                          dataKey="pass_rate"
                          name="Tỷ lệ đạt"
                          stroke="var(--color-chart-2)"
                          fillOpacity={1}
                          fill="url(#colorPass)"
                          strokeWidth={2}
                        />
                      </AreaChart>
                  </ChartContainer>
                )}
              </CardContent>
            </Card>

            {/* Recent Exams */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0">
                <div>
                  <CardTitle>Đề thi gần đây</CardTitle>
                  <CardDescription>5 đề thi mới nhất</CardDescription>
                </div>
                <Button variant="ghost" size="sm" asChild>
                  <Link href="/dashboard/exams">
                    Xem tất cả
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              </CardHeader>
              <CardContent>
                {isLoading ? (
                  <div className="space-y-3">
                    {[...Array(5)].map((_, i) => (
                      <Skeleton key={i} className="h-12 w-full" />
                    ))}
                  </div>
                ) : recentExams.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-center">
                    <ClipboardList className="h-12 w-12 text-muted-foreground/50 mb-4" />
                    <p className="text-muted-foreground">Chưa có đề thi nào</p>
                    <Button className="mt-4" asChild>
                      <Link href="/dashboard/generate">
                        <Sparkles className="mr-2 h-4 w-4" />
                        Tạo đề đầu tiên
                      </Link>
                    </Button>
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Tiêu đề</TableHead>
                        <TableHead className="hidden sm:table-cell">Trạng thái</TableHead>
                        <TableHead className="hidden md:table-cell">Ngày tạo</TableHead>
                        <TableHead className="w-[50px]"></TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {recentExams.map((exam) => (
                        <TableRow key={exam.id}>
                          <TableCell className="font-medium">
                            <div className="flex flex-col">
                              <span className="truncate max-w-[200px]">{exam.title}</span>
                              <span className="text-xs text-muted-foreground sm:hidden">
                                <StatusBadge status={exam.status} />
                              </span>
                            </div>
                          </TableCell>
                          <TableCell className="hidden sm:table-cell">
                            <StatusBadge status={exam.status} />
                          </TableCell>
                          <TableCell className="hidden md:table-cell text-muted-foreground">
                            {formatDate(exam.created_at)}
                          </TableCell>
                          <TableCell>
                            <Button variant="ghost" size="icon" asChild>
                              <Link href={`/dashboard/exams/${exam.id}`}>
                                <Eye className="h-4 w-4" />
                              </Link>
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Quick Actions */}
          <Card>
            <CardHeader>
              <CardTitle>Bắt đầu nhanh</CardTitle>
              <CardDescription>Các thao tác thường dùng</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <QuickActionCard
                  title="Upload tài liệu"
                  description="Thêm PDF, DOCX, PPTX"
                  href="/dashboard/documents"
                  icon={FileText}
                />
                <QuickActionCard
                  title="Tạo đề mới"
                  description="Sinh đề thi từ tài liệu"
                  href="/dashboard/generate"
                  icon={Sparkles}
                />
                <QuickActionCard
                  title="Xem đề thi"
                  description="Quản lý đề đã tạo"
                  href="/dashboard/exams"
                  icon={ClipboardList}
                />
                <QuickActionCard
                  title="Xem phản hồi"
                  description="Tín hiệu từ AI pipeline"
                  href="/dashboard/feedback"
                  icon={AlertTriangle}
                />
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
    </>
  )
}

function StatsCard({
  title,
  value,
  icon: Icon,
  description,
  trend,
  variant = 'default',
}: {
  title: string
  value: string | number | null
  icon: React.ElementType
  description: string
  trend?: 'up' | 'down'
  variant?: 'default' | 'warning'
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className={`h-4 w-4 ${variant === 'warning' ? 'text-warning' : 'text-muted-foreground'}`} />
      </CardHeader>
      <CardContent>
        {value === null ? (
          <Skeleton className="h-8 w-20" />
        ) : (
          <div className="text-2xl font-bold">{value}</div>
        )}
        <p className="text-xs text-muted-foreground flex items-center gap-1">
          {trend === 'up' && <TrendingUp className="h-3 w-3 text-primary" />}
          {description}
        </p>
      </CardContent>
    </Card>
  )
}

function QuickActionCard({
  title,
  description,
  href,
  icon: Icon,
}: {
  title: string
  description: string
  href: string
  icon: React.ElementType
}) {
  return (
    <Link href={href}>
      <Card className="hover:bg-accent/50 transition-colors cursor-pointer h-full">
        <CardContent className="pt-6">
          <div className="flex items-start gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Icon className="h-5 w-5" />
            </div>
            <div>
              <h3 className="font-semibold">{title}</h3>
              <p className="text-sm text-muted-foreground">{description}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
