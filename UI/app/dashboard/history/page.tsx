"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { DashboardHeader } from "@/components/dashboard-header"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Bot,
  History,
  Loader2,
  MoreVertical,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  exams as examsApi,
  type ExamListItem,
  type FeedbackStoreSummary,
} from "@/lib/api"
import { formatPercent } from "@/lib/quality"

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

const emptyFeedbackSummary: FeedbackStoreSummary = {
  total_events: 0,
  reviewed_by_human_count: 0,
  accepted_count: 0,
  rejected_count: 0,
  corrected_count: 0,
  linked_eval_count: 0,
  top_signal_types: [],
  top_error_categories: [],
  recent_events: [],
}

export default function HistoryPage() {
  const [searchQuery, setSearchQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [warningFilter, setWarningFilter] = useState<string>("all")
  const [deleteDialog, setDeleteDialog] = useState<ExamListItem | null>(null)
  const [exams, setExams] = useState<ExamListItem[]>([])
  const [feedbackSummary, setFeedbackSummary] = useState<FeedbackStoreSummary>(emptyFeedbackSummary)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [examList, summary] = await Promise.all([
          examsApi.list(),
          examsApi.getFeedbackSummary(),
        ])
        setExams(examList)
        setFeedbackSummary(summary)
      } catch {
        setExams([])
        setFeedbackSummary(emptyFeedbackSummary)
      } finally {
        setLoading(false)
      }
    }

    void load()
  }, [])

  const filtered = useMemo(() => {
    return exams.filter((exam) => {
      const haystack = `${exam.title} ${exam.document_id}`.toLowerCase()
      const matchesSearch = haystack.includes(searchQuery.toLowerCase())
      const matchesStatus = statusFilter === "all" || exam.status === statusFilter
      const matchesWarnings =
        warningFilter === "all"
          || (warningFilter === "with_warnings" && exam.warning_count > 0)
          || (warningFilter === "clean" && exam.warning_count === 0)
      return matchesSearch && matchesStatus && matchesWarnings
    })
  }, [exams, searchQuery, statusFilter, warningFilter])

  const hasFilters = searchQuery !== "" || statusFilter !== "all" || warningFilter !== "all"

  const clearFilters = () => {
    setSearchQuery("")
    setStatusFilter("all")
    setWarningFilter("all")
  }

  const handleDelete = async () => {
    if (!deleteDialog) return
    try {
      await examsApi.delete(deleteDialog.id)
      setExams((prev) => prev.filter((exam) => exam.id !== deleteDialog.id))
    } catch {
      // Ignore delete failures in the lightweight history view.
    }
    setDeleteDialog(null)
  }

  return (
    <>
      <DashboardHeader title="History" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Version churn and learning traces
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Track which exam runs keep regenerating, which edits were needed, and how much of that history is rich enough to seed playbook updates later.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          <HistoryStat label="Feedback events" value={String(feedbackSummary.total_events)} icon={History} />
          <HistoryStat label="Human reviewed" value={String(feedbackSummary.reviewed_by_human_count)} icon={ShieldCheck} />
          <HistoryStat label="Corrected" value={String(feedbackSummary.corrected_count)} icon={RefreshCw} />
          <HistoryStat label="Eval-linked" value={String(feedbackSummary.linked_eval_count)} icon={Bot} />
        </div>

        <Card className="rounded-2xl shadow-sm">
          <CardContent className="px-5 py-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search exams, documents, or versions..."
                  className="h-9 pl-9"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                  <SelectTrigger className="h-9 w-44">
                    <SelectValue placeholder="Status" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All statuses</SelectItem>
                    <SelectItem value="generated">Generated</SelectItem>
                    <SelectItem value="published">Published</SelectItem>
                    <SelectItem value="failed">Failed</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={warningFilter} onValueChange={setWarningFilter}>
                  <SelectTrigger className="h-9 w-44">
                    <SelectValue placeholder="Warnings" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All warning states</SelectItem>
                    <SelectItem value="with_warnings">With warnings</SelectItem>
                    <SelectItem value="clean">Verifier clean</SelectItem>
                  </SelectContent>
                </Select>
                {hasFilters ? (
                  <Button variant="ghost" size="icon" className="h-9 w-9" onClick={clearFilters}>
                    <X className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
            </div>
          </CardContent>
        </Card>

        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-16 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted">
              <History className="h-7 w-7 text-muted-foreground" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-foreground">
              {hasFilters ? "No matching review history" : "No exams yet"}
            </h3>
            <p className="mt-1.5 max-w-sm text-sm text-muted-foreground">
              {hasFilters
                ? "Try adjusting your filters to reveal the exam versions you want to inspect."
                : "Generate the first exam version to start collecting verifier, edit, and playbook shadow history."}
            </p>
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {filtered.map((exam) => (
              <Card key={exam.id} className="rounded-2xl shadow-sm">
                <CardContent className="p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link href={`/dashboard/exams/${exam.id}`} className="text-sm font-semibold text-foreground hover:text-primary">
                        {exam.title}
                      </Link>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Created {formatDate(exam.created_at)} • v{exam.current_version_number || exam.version_count} • {exam.total_questions} questions
                      </p>
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8">
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-44">
                        <DropdownMenuItem asChild>
                          <Link href={`/dashboard/exams/${exam.id}`}>Open review</Link>
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onClick={() => setDeleteDialog(exam)}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <Badge variant="secondary" className="capitalize">{exam.status}</Badge>
                    <Badge variant="outline">Pass {formatPercent(exam.verifier_pass_rate)}</Badge>
                    <Badge variant={exam.warning_count > 0 ? "outline" : "secondary"}>
                      {exam.warning_count > 0 ? `${exam.warning_count} warnings` : "Verifier clean"}
                    </Badge>
                  </div>

                  <div className="mt-4 grid gap-3 sm:grid-cols-4">
                    <HistoryStat label="Versions" value={String(exam.version_count)} icon={History} compact />
                    <HistoryStat label="Evidence" value={formatPercent(exam.evidence_coverage_rate)} icon={ShieldCheck} compact />
                    <HistoryStat label="Regens" value={String(exam.regenerate_count)} icon={RefreshCw} compact />
                    <HistoryStat label="Edits" value={String(exam.human_edit_count)} icon={TriangleAlert} compact />
                  </div>

                  <div className="mt-4">
                    <Button asChild variant="outline" className="w-full">
                      <Link href={`/dashboard/exams/${exam.id}`}>Inspect quality details</Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        <Dialog open={!!deleteDialog} onOpenChange={() => setDeleteDialog(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete exam</DialogTitle>
              <DialogDescription>
                This removes the exam and all of its stored quality history from the active workspace.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteDialog(null)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={() => void handleDelete()}>
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </>
  )
}

function HistoryStat({
  label,
  value,
  icon: Icon,
  compact = false,
}: {
  label: string
  value: string
  icon: typeof History
  compact?: boolean
}) {
  return (
    <div className={`rounded-xl border bg-muted/20 ${compact ? "p-3" : "p-4"}`}>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <p className={`${compact ? "mt-2 text-lg" : "mt-2 text-2xl"} font-semibold text-foreground`}>{value}</p>
    </div>
  )
}
