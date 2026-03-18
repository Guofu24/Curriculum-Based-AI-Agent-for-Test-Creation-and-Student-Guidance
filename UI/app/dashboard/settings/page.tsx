"use client"

import { useState } from "react"
import { DashboardHeader } from "@/components/dashboard-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Badge } from "@/components/ui/badge"
import { Save, Loader2, User, Bell, Shield, FileText, Layers } from "lucide-react"
import { useAuth } from "@/components/auth-provider"

function RuntimeChip({ label }: { label: string }) {
  return (
    <Badge variant="outline" className="rounded-full px-3 py-1 text-xs">
      {label}
    </Badge>
  )
}

export default function SettingsPage() {
  const { user } = useAuth()
  const [isSaving, setIsSaving] = useState(false)

  const handleSave = () => {
    setIsSaving(true)
    setTimeout(() => setIsSaving(false), 1500)
  }

  return (
    <>
      <DashboardHeader title="Settings" />
      <div className="flex flex-1 flex-col gap-6 p-6 max-w-3xl">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Settings
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage your profile and review the fixed Phase 2 runtime constraints.
          </p>
        </div>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <User className="h-4 w-4 text-primary" />
              Profile Information
            </CardTitle>
            <CardDescription>Update your account and academic details.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label className="text-sm font-medium">Full Name</Label>
                <Input defaultValue={user?.full_name ?? ""} className="h-10" />
              </div>
              <div className="flex flex-col gap-2">
                <Label className="text-sm font-medium">Email</Label>
                <Input defaultValue={user?.email ?? ""} className="h-10" />
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label className="text-sm font-medium">Department</Label>
                <Input defaultValue={user?.department ?? ""} className="h-10" />
              </div>
              <div className="flex flex-col gap-2">
                <Label className="text-sm font-medium">University</Label>
                <Input defaultValue={user?.university ?? ""} className="h-10" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <FileText className="h-4 w-4 text-primary" />
              Active Runtime
            </CardTitle>
            <CardDescription>
              These controls are fixed by the current product phase and are shown here as read-only constraints.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
              <RuntimeChip label="Physics only" />
              <RuntimeChip label="Vietnamese output" />
              <RuntimeChip label="PDF only" />
              <RuntimeChip label="MCQ single-answer only" />
              <RuntimeChip label="Strict scope always on" />
              <RuntimeChip label="Evidence required" />
            </div>

            <div className="rounded-xl border bg-muted/20 p-4">
              <div className="flex items-start gap-3">
                <Layers className="mt-0.5 h-4 w-4 text-primary" />
                <div className="space-y-1 text-sm text-muted-foreground">
                  <p className="font-medium text-foreground">Phase 2 guardrails</p>
                  <p>The active flow is document - scope - exam spec - blueprint - generate - verify - review - version.</p>
                  <p>Language, subject, question type, and strict scope are enforced by backend services and are not user-configurable.</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Bell className="h-4 w-4 text-primary" />
              Notifications
            </CardTitle>
            <CardDescription>Preview the event types that matter in the current workflow.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="rounded-xl border p-4">
              <p className="text-sm font-medium text-foreground">Document processing</p>
              <p className="text-xs text-muted-foreground">Triggered when a PDF finishes parsing, sectioning, and indexing.</p>
            </div>
            <div className="rounded-xl border p-4">
              <p className="text-sm font-medium text-foreground">Exam generation and verification</p>
              <p className="text-xs text-muted-foreground">Triggered after generation completes and verifier results are available for review.</p>
            </div>
            <div className="rounded-xl border p-4">
              <p className="text-sm font-medium text-foreground">Review actions</p>
              <p className="text-xs text-muted-foreground">Covers regenerate, human edits, and publish actions captured in version history.</p>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Shield className="h-4 w-4 text-primary" />
              Security
            </CardTitle>
            <CardDescription>Manage your account security settings.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label className="text-sm font-medium">Change Password</Label>
              <div className="grid gap-3 sm:grid-cols-2">
                <Input type="password" placeholder="Current password" className="h-10" />
                <Input type="password" placeholder="New password" className="h-10" />
              </div>
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-foreground">Two-factor authentication</p>
                <p className="text-xs text-muted-foreground">Add an extra layer of security to your account.</p>
              </div>
              <Button variant="outline" size="sm">
                Enable
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="flex justify-end pb-6">
          <Button onClick={handleSave} disabled={isSaving} className="px-6">
            {isSaving ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            {isSaving ? "Saving..." : "Save Changes"}
          </Button>
        </div>
      </div>
    </>
  )
}
