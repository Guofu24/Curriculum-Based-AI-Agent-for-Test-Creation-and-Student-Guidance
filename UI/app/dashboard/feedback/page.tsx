"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { DashboardHeader } from "@/components/dashboard-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Activity, ArrowRight, Loader2, Search } from "lucide-react"
import {
  exams as examsApi,
  type FeedbackEvent,
  type FeedbackStoreSummary,
} from "@/lib/api"
import { humanReadableCategory, humanReadableSignal } from "@/lib/quality"

const emptySummary: FeedbackStoreSummary = {
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

export default function FeedbackPage() {
  const [summary, setSummary] = useState<FeedbackStoreSummary>(emptySummary)
  const [events, setEvents] = useState<FeedbackEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [stage, setStage] = useState("all")
  const [signal, setSignal] = useState("all")

  useEffect(() => {
    async function load() {
      try {
        const [summaryPayload, eventsPayload] = await Promise.all([
          examsApi.getFeedbackSummary(),
          examsApi.getFeedbackStore({ limit: 200 }),
        ])
        setSummary(summaryPayload)
        setEvents(eventsPayload)
      } catch {
        setSummary(emptySummary)
        setEvents([])
      } finally {
        setLoading(false)
      }
    }

    void load()
  }, [])

  const filtered = useMemo(() => {
    return events.filter((event) => {
      const haystack = `${event.exam_title || ""} ${event.signal_type} ${event.review_status || ""} ${(event.error_categories || []).join(" ")}`.toLowerCase()
      const matchesSearch = haystack.includes(search.toLowerCase())
      const stageValue = event.event_stage || event.workflow_stage || ""
      const matchesStage = stage === "all" || stageValue === stage
      const matchesSignal = signal === "all" || event.signal_type === signal
      return matchesSearch && matchesStage && matchesSignal
    })
  }, [events, search, stage, signal])

  return (
    <>
      <DashboardHeader title="Feedback Store" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Normalized feedback store
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Inspect the event stream that ACE will eventually learn from: verifier failures, regenerate requests, human edits, publish decisions, and playbook shadow logs.
            </p>
          </div>
          <Button variant="outline" asChild>
            <Link href="/dashboard/playbook">
              Open playbook
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          <FeedbackStat label="Total events" value={String(summary.total_events)} />
          <FeedbackStat label="Reviewed by human" value={String(summary.reviewed_by_human_count)} />
          <FeedbackStat label="Accepted / corrected" value={`${summary.accepted_count} / ${summary.corrected_count}`} />
          <FeedbackStat label="Linked eval samples" value={String(summary.linked_eval_count)} />
        </div>

        <Card className="rounded-2xl shadow-sm">
          <CardContent className="px-5 py-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search exam title, signal, review status, or error category..."
                  className="h-9 pl-9"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <Select value={stage} onValueChange={setStage}>
                  <SelectTrigger className="h-9 w-44">
                    <SelectValue placeholder="Stage" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All stages</SelectItem>
                    <SelectItem value="retrieval">Retrieval</SelectItem>
                    <SelectItem value="generation">Generation</SelectItem>
                    <SelectItem value="verification">Verification</SelectItem>
                    <SelectItem value="review">Review</SelectItem>
                    <SelectItem value="publish">Publish</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={signal} onValueChange={setSignal}>
                  <SelectTrigger className="h-9 w-56">
                    <SelectValue placeholder="Signal type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All signal types</SelectItem>
                    <SelectItem value="verifier_warning">Verifier warning</SelectItem>
                    <SelectItem value="verifier_failed">Verifier failed</SelectItem>
                    <SelectItem value="human_edit">Human edit</SelectItem>
                    <SelectItem value="regenerate_requested">Regenerate requested</SelectItem>
                    <SelectItem value="playbook_shadow">Playbook shadow</SelectItem>
                    <SelectItem value="exam_published">Exam published</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
          <Card className="rounded-2xl shadow-sm">
            <CardHeader>
              <CardTitle className="text-base font-semibold text-foreground">Top labels</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Signal types</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {summary.top_signal_types.map((item) => (
                    <Badge key={item.name} variant="outline">
                      {humanReadableSignal(item.name)} ({item.count})
                    </Badge>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Error categories</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {summary.top_error_categories.map((item) => (
                    <Badge key={item.category} variant="outline">
                      {humanReadableCategory(item.category)} ({item.count})
                    </Badge>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-2xl shadow-sm">
            <CardHeader>
              <CardTitle className="text-base font-semibold text-foreground">Event stream</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {loading ? (
                <div className="flex justify-center py-10">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : filtered.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">No feedback events matched the current filters.</p>
              ) : (
                filtered.map((event) => (
                  <div key={event.id} className="rounded-xl border p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary">{humanReadableSignal(event.signal_type)}</Badge>
                      {event.review_status ? <Badge variant="outline">{humanReadableCategory(event.review_status)}</Badge> : null}
                      {event.event_stage || event.workflow_stage ? <Badge variant="outline">{event.event_stage || event.workflow_stage}</Badge> : null}
                      {event.exam_title ? <Badge variant="outline">{event.exam_title}</Badge> : null}
                    </div>
                    {event.error_categories.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {event.error_categories.map((category) => (
                          <Badge key={`${event.id}-${category}`} variant="outline">
                            {humanReadableCategory(category)}
                          </Badge>
                        ))}
                      </div>
                    ) : null}
                    {event.payload ? (
                      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-lg bg-muted/20 p-3 text-xs text-muted-foreground">
                        {JSON.stringify(event.payload, null, 2)}
                      </pre>
                    ) : null}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

function FeedbackStat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="rounded-2xl shadow-sm">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Activity className="h-3.5 w-3.5" />
          {label}
        </div>
        <p className="mt-2 text-2xl font-semibold text-foreground">{value}</p>
      </CardContent>
    </Card>
  )
}
