"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { DashboardHeader } from "@/components/dashboard-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Bot,
  FileText,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react"
import { useAuth } from "@/components/auth-provider"
import {
  exams as examsApi,
  playbook as playbookApi,
  type ExamListItem,
  type PlaybookOverview,
  type QualitySummary,
} from "@/lib/api"
import { formatPercent, humanReadableCategory, humanReadableSignal } from "@/lib/quality"

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

const emptySummary: QualitySummary = {
  documents_active: 0,
  exams_generated: 0,
  question_count: 0,
  verifier_pass_rate: 0,
  verifier_warning_rate: 0,
  evidence_coverage_rate: 0,
  scope_violation_rate: 0,
  avg_regenerate_count: 0,
  avg_human_edit_count: 0,
  version_churn: 0,
  top_error_categories: [],
  recent_warnings: [],
}

const emptyOverview: PlaybookOverview = {
  retrieval_mode: "off",
  retrieval_limit: 0,
  feedback_event_count: 0,
  approved_bullet_count: 0,
  candidate_bullet_count: 0,
  archived_bullet_count: 0,
  reflection_candidate_count: 0,
  promoted_candidate_count: 0,
  warmup_exam_case_count: 0,
  warmup_question_case_count: 0,
  warmup_feedback_case_count: 0,
  top_feedback_categories: [],
  recent_bullets: [],
  recent_candidates: [],
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [summary, setSummary] = useState<QualitySummary>(emptySummary)
  const [overview, setOverview] = useState<PlaybookOverview>(emptyOverview)
  const [recentExams, setRecentExams] = useState<ExamListItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [qualitySummary, playbookOverview, examList] = await Promise.all([
          examsApi.getQualitySummary(),
          playbookApi.getOverview(),
          examsApi.list(),
        ])
        setSummary(qualitySummary)
        setOverview(playbookOverview)
        setRecentExams(examList.slice(0, 4))
      } catch {
        setSummary(emptySummary)
        setOverview(emptyOverview)
        setRecentExams([])
      } finally {
        setLoading(false)
      }
    }
    void load()
  }, [])

  const firstName = user?.full_name?.split(" ")[0] ?? "there"
  const cards = [
    {
      title: "Active documents",
      value: summary.documents_active.toString(),
      note: "Processed PDFs feeding scoped retrieval",
      icon: BookOpen,
    },
    {
      title: "Exams generated",
      value: summary.exams_generated.toString(),
      note: "Stored internal review versions",
      icon: FileText,
    },
    {
      title: "Verifier pass rate",
      value: formatPercent(summary.verifier_pass_rate),
      note: "Current quality pulse across stored questions",
      icon: ShieldCheck,
    },
    {
      title: "Approved bullets",
      value: overview.approved_bullet_count.toString(),
      note: `Playbook retrieval: ${overview.retrieval_mode}`,
      icon: Bot,
    },
    {
      title: "Reflection candidates",
      value: overview.reflection_candidate_count.toString(),
      note: `${overview.promoted_candidate_count} promoted into the store`,
      icon: Sparkles,
    },
    {
      title: "Avg regenerate count",
      value: summary.avg_regenerate_count.toFixed(2),
      note: "Human friction after first generation",
      icon: RefreshCw,
    },
  ]

  return (
    <>
      <DashboardHeader title="ACE Foundation" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Phase 4 ACE foundation, {firstName}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Monitor quality metrics, inspect the normalized feedback store, and review which playbook bullets are ready for safe runtime retrieval.
            </p>
          </div>
          <Badge variant="secondary" className="w-fit gap-1.5">
            <Activity className="h-3.5 w-3.5" />
            Learning infrastructure, not adaptive runtime
          </Badge>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
          {cards.map((card) => (
            <Card key={card.title} className="rounded-2xl shadow-sm">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {card.title}
                </CardTitle>
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
                  <card.icon className="h-4 w-4 text-primary" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-semibold text-foreground">
                  {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : card.value}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{card.note}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base font-semibold text-foreground">Recent warnings</CardTitle>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/dashboard/feedback" className="text-xs text-muted-foreground">
                  Open feedback store
                  <ArrowRight className="ml-1 h-3 w-3" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {loading ? (
                <div className="flex justify-center py-10">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : summary.recent_warnings.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  No verifier warnings have been logged yet.
                </p>
              ) : (
                summary.recent_warnings.map((event) => (
                  <div key={event.id} className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary" className="capitalize">
                        {humanReadableSignal(event.signal_type)}
                      </Badge>
                      {event.review_status ? (
                        <Badge variant="outline" className="capitalize">
                          {humanReadableCategory(event.review_status)}
                        </Badge>
                      ) : null}
                      <span className="text-xs text-muted-foreground">{formatDate(event.created_at)}</span>
                    </div>
                    <p className="mt-2 text-sm text-foreground">
                      {(event.payload?.warnings as string[] | undefined)?.[0] || "Open feedback store to inspect this signal."}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Stage: {event.event_stage || event.workflow_stage || "verification"}
                    </p>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base font-semibold text-foreground">Playbook foundation</CardTitle>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/dashboard/playbook" className="text-xs text-muted-foreground">
                  Open playbook
                  <ArrowRight className="ml-1 h-3 w-3" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-xl border bg-muted/20 p-4">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Retrieval mode</p>
                <p className="mt-2 text-2xl font-semibold capitalize text-foreground">{overview.retrieval_mode}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Limit {overview.retrieval_limit} bullets per stage
                </p>
              </div>
              <div className="rounded-xl border bg-muted/20 p-4">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Warmup export</p>
                <p className="mt-2 text-sm text-foreground">
                  {overview.warmup_exam_case_count} exam cases, {overview.warmup_question_case_count} question cases, {overview.warmup_feedback_case_count} feedback cases
                </p>
              </div>
              <div className="rounded-xl border bg-muted/20 p-4">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Top learning signals</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {overview.top_feedback_categories.length === 0 ? (
                    <span className="text-sm text-muted-foreground">No labeled feedback yet.</span>
                  ) : (
                    overview.top_feedback_categories.map((item) => (
                      <Badge key={item.name} variant="outline" className="capitalize">
                        {humanReadableCategory(item.name)} ({item.count})
                      </Badge>
                    ))
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <Card className="rounded-2xl shadow-sm">
            <CardHeader>
              <CardTitle className="text-base font-semibold text-foreground">Foundation state</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <div className="rounded-xl border p-4">
                <p className="font-medium text-foreground">Feedback store</p>
                <p className="mt-1">
                  {overview.feedback_event_count} normalized events are available for future ACE learning, with query keys for exam, version, question, stage, severity, and error category.
                </p>
              </div>
              <div className="rounded-xl border p-4">
                <p className="font-medium text-foreground">Reflection layer</p>
                <p className="mt-1">
                  Candidate bullets stay separate from approved bullets so the runtime never behaves as if ACE is already fully adaptive.
                </p>
              </div>
              <div className="rounded-xl border p-4">
                <p className="font-medium text-foreground">Scoped rollout</p>
                <p className="mt-1">
                  Playbook retrieval is feature-flagged. `shadow` only logs what would attach; `limited` attaches a small approved set.
                </p>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base font-semibold text-foreground">Recent exams</CardTitle>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/dashboard/history" className="text-xs text-muted-foreground">
                  View history
                  <ArrowRight className="ml-1 h-3 w-3" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {loading ? (
                <div className="flex justify-center py-10">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : recentExams.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  No exam versions yet. Upload a PDF and generate the first reviewable version.
                </p>
              ) : (
                recentExams.map((exam) => (
                  <Link
                    key={exam.id}
                    href={`/dashboard/exams/${exam.id}`}
                    className="flex items-start justify-between gap-4 rounded-xl border p-4 transition-colors hover:bg-muted/40"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">{exam.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        v{exam.current_version_number || exam.version_count} • {exam.total_questions} questions • {formatPercent(exam.verifier_pass_rate)}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <Badge variant={exam.warning_count > 0 ? "outline" : "secondary"}>
                        {exam.warning_count > 0 ? `${exam.warning_count} warnings` : "Verifier clean"}
                      </Badge>
                      {exam.warning_count > 0 ? (
                        <AlertTriangle className="h-4 w-4 text-amber-600" />
                      ) : null}
                    </div>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}
