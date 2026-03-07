"use client"

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
} from "lucide-react"

const stats = [
  {
    title: "Total Textbooks",
    value: "12",
    change: "+2 this month",
    icon: BookOpen,
  },
  {
    title: "Exams Generated",
    value: "47",
    change: "+8 this week",
    icon: FileText,
  },
  {
    title: "Questions Created",
    value: "1,284",
    change: "+156 this week",
    icon: Sparkles,
  },
  {
    title: "Avg. Quality Score",
    value: "94%",
    change: "+3% improvement",
    icon: TrendingUp,
  },
]

const recentExams = [
  {
    id: "1",
    title: "Data Structures Midterm",
    textbook: "Data Structures & Algorithms",
    chapters: "Ch. 1-5",
    type: "Mixed",
    difficulty: "Advanced",
    date: "2 hours ago",
  },
  {
    id: "2",
    title: "Operating Systems Quiz",
    textbook: "Modern Operating Systems",
    chapters: "Ch. 3",
    type: "Multiple Choice",
    difficulty: "Basic",
    date: "Yesterday",
  },
  {
    id: "3",
    title: "Database Final Exam",
    textbook: "Database System Concepts",
    chapters: "Ch. 1-12",
    type: "Essay",
    difficulty: "High Application",
    date: "3 days ago",
  },
]

export default function DashboardPage() {
  return (
    <>
      <DashboardHeader title="Dashboard" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        {/* Welcome */}
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Good morning, Dr. Smith
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
                <div className="text-2xl font-semibold text-foreground">{stat.value}</div>
                <p className="mt-1 text-xs text-muted-foreground">{stat.change}</p>
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
                {recentExams.map((exam) => (
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
                        {exam.textbook} - {exam.chapters}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0 ml-4">
                      <Badge variant="secondary" className="text-xs">
                        {exam.type}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {exam.difficulty}
                      </Badge>
                      <span className="text-xs text-muted-foreground whitespace-nowrap hidden sm:inline">
                        {exam.date}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}
