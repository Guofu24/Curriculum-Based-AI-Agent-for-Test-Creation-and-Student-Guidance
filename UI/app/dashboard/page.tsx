"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { DashboardHeader } from "@/components/dashboard-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  BookOpen,
  FileText,
  Sparkles,
  TrendingUp,
  ArrowRight,
  Clock,
  Loader2,
} from "lucide-react"
import { useAuth } from "@/components/auth-provider"
import {
  textbooks as textbooksApi,
  exams as examsApi,
  type ExamListItem,
} from "@/lib/api"

function formatDate(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffH = Math.floor(diffMs / 3_600_000)
  if (diffH < 1) return "Just now"
  if (diffH < 24) return `${diffH} hours ago`
  const diffD = Math.floor(diffH / 24)
  if (diffD === 1) return "Yesterday"
  if (diffD < 7) return `${diffD} days ago`
  return d.toLocaleDateString()
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [textbookCount, setTextbookCount] = useState(0)
  const [examCount, setExamCount] = useState(0)
  const [totalQuestions, setTotalQuestions] = useState(0)
  const [recentExams, setRecentExams] = useState<ExamListItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [books, examList] = await Promise.all([
          textbooksApi.list(),
          examsApi.list(),
        ])
        setTextbookCount(books.length)
        setExamCount(examList.length)
        setTotalQuestions(examList.reduce((sum, e) => sum + e.total_questions, 0))
        setRecentExams(examList.slice(0, 3))
      } catch {
        // silently fail — user sees zeros
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const firstName = user?.full_name?.split(" ")[0] ?? "there"

  const stats = [
    {
      title: "Total Textbooks",
      value: textbookCount.toString(),
      icon: BookOpen,
    },
    {
      title: "Exams Generated",
      value: examCount.toString(),
      icon: FileText,
    },
    {
      title: "Questions Created",
      value: totalQuestions.toLocaleString(),
      icon: Sparkles,
    },
    {
      title: "Avg. Quality Score",
      value: "—",
      icon: TrendingUp,
    },
  ]
  return (
    <>
      <DashboardHeader title="Dashboard" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        {/* Welcome */}
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Good morning, {firstName}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {"Here's what's happening with your exams today."}
          </p>
        </div>

        {/* Stats Grid */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat) => (
            <Card key={stat.title} className="rounded-2xl shadow-sm">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {stat.title}
                </CardTitle>
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
                  <stat.icon className="h-4 w-4 text-primary" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-semibold text-foreground">
                  {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : stat.value}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Quick Actions & Recent Exams */}
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Quick Actions */}
          <Card className="rounded-2xl shadow-sm">
            <CardHeader>
              <CardTitle className="text-base font-semibold text-foreground">Quick Actions</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Button asChild className="w-full justify-start h-11" size="lg">
                <Link href="/dashboard/generate">
                  <Sparkles className="mr-2 h-4 w-4" />
                  Generate New Exam
                </Link>
              </Button>
              <Button asChild variant="outline" className="w-full justify-start h-11" size="lg">
                <Link href="/dashboard/textbooks">
                  <BookOpen className="mr-2 h-4 w-4" />
                  Upload Textbook
                </Link>
              </Button>
              <Button asChild variant="outline" className="w-full justify-start h-11" size="lg">
                <Link href="/dashboard/history">
                  <Clock className="mr-2 h-4 w-4" />
                  View Exam History
                </Link>
              </Button>
            </CardContent>
          </Card>

          {/* Recent Exams */}
          <Card className="lg:col-span-2 rounded-2xl shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base font-semibold text-foreground">Recent Exams</CardTitle>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/dashboard/history" className="text-xs text-muted-foreground">
                  View all
                  <ArrowRight className="ml-1 h-3 w-3" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-3">
                {loading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : recentExams.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-8 text-center">
                    No exams yet. Generate your first exam!
                  </p>
                ) : (
                  recentExams.map((exam) => (
                    <Link
                      key={exam.id}
                      href={`/dashboard/exams/${exam.id}`}
                      className="flex items-center justify-between rounded-xl border p-4 transition-colors hover:bg-muted/50"
                    >
                      <div className="flex flex-col gap-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-foreground truncate">
                            {exam.title}
                          </span>
                        </div>
                        <span className="text-xs text-muted-foreground truncate">
                          {exam.total_questions} questions - {exam.chapters.length > 0 ? `Ch. ${exam.chapters.join(", ")}` : "All chapters"}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0 ml-4">
                        <Badge variant="secondary" className="text-xs capitalize">
                          {exam.exam_type}
                        </Badge>
                        <Badge variant="outline" className="text-xs capitalize">
                          {exam.difficulty}
                        </Badge>
                        <span className="text-xs text-muted-foreground whitespace-nowrap hidden sm:inline">
                          {formatDate(exam.created_at)}
                        </span>
                      </div>
                    </Link>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}
