"use client"

import { useEffect, useState } from "react"
import { DashboardHeader } from "@/components/dashboard-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Archive,
  Bot,
  Check,
  Loader2,
  RefreshCw,
  Sparkles,
  XCircle,
} from "lucide-react"
import {
  playbook as playbookApi,
  type PlaybookBullet,
  type PlaybookOverview,
  type ReflectionCandidate,
  type WarmupPreview,
} from "@/lib/api"

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

const emptyWarmup: WarmupPreview = {
  meta: {
    exported_at: "",
    exam_case_count: 0,
    question_case_count: 0,
    feedback_case_count: 0,
    playbook_seed_count: 0,
    reflection_candidate_count: 0,
  },
  exam_cases: [],
  question_cases: [],
  feedback_cases: [],
  playbook_seed: [],
  reflection_candidates: [],
}

export default function PlaybookPage() {
  const [overview, setOverview] = useState<PlaybookOverview>(emptyOverview)
  const [bullets, setBullets] = useState<PlaybookBullet[]>([])
  const [candidates, setCandidates] = useState<ReflectionCandidate[]>([])
  const [warmup, setWarmup] = useState<WarmupPreview>(emptyWarmup)
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = async () => {
    try {
      const [overviewPayload, bulletsPayload, candidatesPayload, warmupPayload] = await Promise.all([
        playbookApi.getOverview(),
        playbookApi.listBullets({ limit: 50 }),
        playbookApi.listCandidates({ limit: 50 }),
        playbookApi.getWarmupPreview(),
      ])
      setOverview(overviewPayload)
      setBullets(bulletsPayload)
      setCandidates(candidatesPayload)
      setWarmup(warmupPayload)
    } finally {
      setLoading(false)
      setBusyId(null)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const runAction = async (id: string | null, action: () => Promise<unknown>) => {
    setBusyId(id)
    try {
      await action()
      await load()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <DashboardHeader title="Playbook" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Playbook bullet store
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Review approved bullets, inspect reflection candidates, and keep retrieval mode constrained while the product is still in ACE foundation.
            </p>
          </div>
          <Button onClick={() => void runAction("generate", () => playbookApi.generateCandidates())} disabled={busyId === "generate"}>
            {busyId === "generate" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
            Generate reflection candidates
          </Button>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          <SummaryCard title="Retrieval mode" value={overview.retrieval_mode} note={`limit ${overview.retrieval_limit}`} />
          <SummaryCard title="Approved bullets" value={String(overview.approved_bullet_count)} note="runtime-eligible items" />
          <SummaryCard title="Candidates" value={String(overview.reflection_candidate_count)} note={`${overview.promoted_candidate_count} promoted`} />
          <SummaryCard title="Warmup cases" value={String(warmup.meta.question_case_count)} note={`${warmup.meta.feedback_case_count} feedback cases`} />
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base font-semibold text-foreground">Approved and archived bullets</CardTitle>
              <Badge variant="outline" className="capitalize">
                {overview.retrieval_mode}
              </Badge>
            </CardHeader>
            <CardContent className="space-y-3">
              {loading ? (
                <div className="flex justify-center py-10">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : bullets.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">No playbook bullets yet.</p>
              ) : (
                bullets.map((bullet) => (
                  <div key={bullet.id} className="rounded-xl border p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary" className="capitalize">{bullet.bullet_type.replaceAll("_", " ")}</Badge>
                        <Badge variant="outline" className="capitalize">{bullet.status}</Badge>
                        <Badge variant="outline">confidence {bullet.confidence.toFixed(2)}</Badge>
                      </div>
                      {bullet.status !== "archived" ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void runAction(bullet.id, () => playbookApi.archiveBullet(bullet.id))}
                          disabled={busyId === bullet.id}
                        >
                          {busyId === bullet.id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Archive className="mr-2 h-4 w-4" />}
                          Archive
                        </Button>
                      ) : null}
                    </div>
                    <p className="mt-3 text-sm font-medium text-foreground">{bullet.title}</p>
                    <p className="mt-2 text-sm text-muted-foreground">{bullet.content}</p>
                    {bullet.tags.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {bullet.tags.map((tag) => (
                          <Badge key={`${bullet.id}-${tag}`} variant="outline">{tag}</Badge>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card className="rounded-2xl shadow-sm">
            <CardHeader>
              <CardTitle className="text-base font-semibold text-foreground">Reflection candidates</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {loading ? (
                <div className="flex justify-center py-10">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : candidates.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  Generate candidates from feedback and eval signals to start the review loop.
                </p>
              ) : (
                candidates.map((candidate) => (
                  <div key={candidate.id} className="rounded-xl border p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary" className="capitalize">{candidate.category.replaceAll("_", " ")}</Badge>
                      <Badge variant="outline" className="capitalize">{candidate.status}</Badge>
                      <Badge variant="outline">{candidate.proposed_bullet_type.replaceAll("_", " ")}</Badge>
                    </div>
                    <p className="mt-3 text-sm font-medium text-foreground">{candidate.proposed_title}</p>
                    <p className="mt-2 text-sm text-muted-foreground">{candidate.proposed_bullet_text}</p>
                    <p className="mt-2 text-xs text-muted-foreground">
                      confidence {candidate.confidence.toFixed(2)} • eval refs {candidate.source_eval_sample_ids.length} • feedback refs {candidate.source_event_ids.length}
                    </p>
                    {candidate.status === "candidate" ? (
                      <div className="mt-3 flex gap-2">
                        <Button size="sm" onClick={() => void runAction(candidate.id, () => playbookApi.promoteCandidate(candidate.id))} disabled={busyId === candidate.id}>
                          {busyId === candidate.id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}
                          Promote
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => void runAction(candidate.id, () => playbookApi.rejectCandidate(candidate.id))} disabled={busyId === candidate.id}>
                          <XCircle className="mr-2 h-4 w-4" />
                          Reject
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="text-base font-semibold text-foreground">Warmup export preview</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-4">
            <WarmupStat label="Exam cases" value={String(warmup.meta.exam_case_count)} />
            <WarmupStat label="Question cases" value={String(warmup.meta.question_case_count)} />
            <WarmupStat label="Feedback cases" value={String(warmup.meta.feedback_case_count)} />
            <WarmupStat label="Seed bullets" value={String(warmup.meta.playbook_seed_count)} />
          </CardContent>
        </Card>
      </div>
    </>
  )
}

function SummaryCard({ title, value, note }: { title: string; value: string; note: string }) {
  return (
    <Card className="rounded-2xl shadow-sm">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Bot className="h-3.5 w-3.5" />
          {title}
        </div>
        <p className="mt-2 text-2xl font-semibold text-foreground capitalize">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  )
}

function WarmupStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border bg-muted/20 p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-foreground">{value}</p>
    </div>
  )
}
