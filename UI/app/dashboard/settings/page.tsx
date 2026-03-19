"use client"

import { useEffect, useState } from "react"
import { DashboardHeader } from "@/components/dashboard-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Activity, Bot, FileText, Layers, Shield, Tags } from "lucide-react"
import { useAuth } from "@/components/auth-provider"
import { playbook as playbookApi, type PlaybookOverview } from "@/lib/api"

function RuntimeChip({ label }: { label: string }) {
  return (
    <Badge variant="outline" className="rounded-full px-3 py-1 text-xs">
      {label}
    </Badge>
  )
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

export default function SettingsPage() {
  const { user } = useAuth()
  const [overview, setOverview] = useState<PlaybookOverview>(emptyOverview)

  useEffect(() => {
    playbookApi.getOverview().then(setOverview).catch(() => setOverview(emptyOverview))
  }, [])

  return (
    <>
      <DashboardHeader title="Settings" />
      <div className="flex max-w-4xl flex-1 flex-col gap-6 p-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Phase 4 foundation settings
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            This page stays intentionally narrow. It exposes the current runtime boundary and playbook retrieval mode without pretending ACE is already an autonomous adaptive system.
          </p>
        </div>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Shield className="h-4 w-4 text-primary" />
              Active runtime boundary
            </CardTitle>
            <CardDescription>The current product scope is still enforced by backend rules.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
              <RuntimeChip label="Physics only" />
              <RuntimeChip label="Vietnamese output" />
              <RuntimeChip label="PDF only" />
              <RuntimeChip label="MCQ single-answer" />
              <RuntimeChip label="Strict scope always on" />
              <RuntimeChip label="Evidence required" />
            </div>
            <div className="rounded-xl border bg-muted/20 p-4 text-sm text-muted-foreground">
              No essay runtime, DOCX/PPTX ingestion, multi-subject setup, student guidance, or autonomous ACE controls are exposed here.
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="rounded-2xl shadow-sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <Bot className="h-4 w-4 text-primary" />
                Playbook retrieval
              </CardTitle>
              <CardDescription>Feature-flagged runtime context attachment.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <div className="rounded-xl border p-4">
                <p className="font-medium capitalize text-foreground">Mode: {overview.retrieval_mode}</p>
                <p className="mt-1">`off` disables retrieval, `shadow` logs what would attach, and `limited` attaches a small approved bullet set.</p>
              </div>
              <div className="rounded-xl border p-4">
                <p className="font-medium text-foreground">Approved bullets</p>
                <p className="mt-1">{overview.approved_bullet_count} runtime-eligible bullets with a retrieval cap of {overview.retrieval_limit} per stage.</p>
              </div>
              <div className="rounded-xl border p-4">
                <p className="font-medium text-foreground">Reflection queue</p>
                <p className="mt-1">{overview.reflection_candidate_count} candidate insights are waiting outside the runtime until explicitly promoted.</p>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-2xl shadow-sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <Activity className="h-4 w-4 text-primary" />
                Feedback and warmup state
              </CardTitle>
              <CardDescription>What Phase 4 prepares for future ACE learning.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <div className="rounded-xl border p-4">
                <p className="font-medium text-foreground">Feedback events</p>
                <p className="mt-1">{overview.feedback_event_count} normalized events are available for query by exam, version, question, stage, source, and error category.</p>
              </div>
              <div className="rounded-xl border p-4">
                <p className="font-medium text-foreground">Warmup export</p>
                <p className="mt-1">{overview.warmup_exam_case_count} exam cases, {overview.warmup_question_case_count} question cases, and {overview.warmup_feedback_case_count} feedback cases are exportable as offline ACE foundation data.</p>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Tags className="h-4 w-4 text-primary" />
              Feedback labels
            </CardTitle>
            <CardDescription>Current labeling states exposed by the backend.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="flex flex-wrap gap-2">
              <RuntimeChip label="logged" />
              <RuntimeChip label="needs_review" />
              <RuntimeChip label="reviewed_by_human" />
              <RuntimeChip label="corrected" />
              <RuntimeChip label="rejected" />
              <RuntimeChip label="accepted" />
            </div>
            <div className="rounded-xl border bg-muted/20 p-4">
              These states are part of the learning substrate. They tell us which signals were only observed, which ones a lecturer corrected, and which versions became publishable.
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Layers className="h-4 w-4 text-primary" />
              Operator context
            </CardTitle>
            <CardDescription>Who is using the current workspace.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-xl border bg-muted/20 p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">User</p>
              <p className="mt-2 text-sm font-medium text-foreground">{user?.full_name ?? "Unknown user"}</p>
              <p className="mt-1 text-xs text-muted-foreground">{user?.email ?? ""}</p>
            </div>
            <div className="rounded-xl border bg-muted/20 p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Compatibility note</p>
              <p className="mt-2 text-sm text-foreground">Some persistence still uses historical textbook tables, but the active API and UI stay document-first with playbook retrieval guarded by a feature flag.</p>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <FileText className="h-4 w-4 text-primary" />
              Still out of scope
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <RuntimeChip label="No ACE core" />
            <RuntimeChip label="No autonomous loops" />
            <RuntimeChip label="No student guidance" />
            <RuntimeChip label="No essay runtime" />
            <RuntimeChip label="No DOCX/PPTX" />
            <RuntimeChip label="No multi-subject" />
          </CardContent>
        </Card>
      </div>
    </>
  )
}
