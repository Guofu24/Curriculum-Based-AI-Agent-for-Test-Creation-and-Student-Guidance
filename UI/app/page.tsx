"use client"

import { useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { ApiError } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Activity,
  BookOpen,
  FileCheck,
  Sparkles,
  ArrowRight,
  Loader2,
  UserPlus,
} from "lucide-react"

export default function LoginPage() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<"login" | "register">("login")
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")

  // Login fields
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")

  // Register fields
  const [fullName, setFullName] = useState("")
  const [department, setDepartment] = useState("")
  const [university, setUniversity] = useState("")
  const [successMessage, setSuccessMessage] = useState("")

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setIsLoading(true)
    setError("")
    setSuccessMessage("")
    try {
      await login(email, password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed")
    } finally {
      setIsLoading(false)
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    setIsLoading(true)
    setError("")
    setSuccessMessage("")
    try {
      const message = await register({
        email,
        password,
        full_name: fullName,
        department: department || undefined,
        university: university || undefined,
      })
      // Show success message and switch to login mode
      setSuccessMessage(message)
      setMode("login")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-svh">
      {/* Left Branding Panel */}
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-between bg-primary p-12 text-primary-foreground relative overflow-hidden">
        <div className="absolute inset-0 opacity-[0.07]">
          <svg className="w-full h-full" viewBox="0 0 800 800" fill="none">
            <circle cx="400" cy="400" r="300" stroke="currentColor" strokeWidth="0.5" />
            <circle cx="400" cy="400" r="200" stroke="currentColor" strokeWidth="0.5" />
            <circle cx="400" cy="400" r="100" stroke="currentColor" strokeWidth="0.5" />
            <line x1="100" y1="400" x2="700" y2="400" stroke="currentColor" strokeWidth="0.5" />
            <line x1="400" y1="100" x2="400" y2="700" stroke="currentColor" strokeWidth="0.5" />
          </svg>
        </div>

        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-foreground/15 backdrop-blur-sm">
              <Activity className="h-5 w-5" />
            </div>
            <span className="text-xl font-semibold tracking-tight">ExamAI</span>
          </div>
        </div>

        <div className="relative z-10 flex flex-col gap-8">
          <div>
            <h1 className="text-4xl font-semibold leading-tight tracking-tight text-balance">
              Internal quality workspace for grounded Physics exam generation.
            </h1>
            <p className="mt-4 text-lg text-primary-foreground/70 leading-relaxed max-w-md">
              Upload Physics PDFs, generate scoped exams, inspect verifier signals, and turn teacher feedback into structured quality data.
            </p>
          </div>

          <div className="flex flex-col gap-4">
            <FeatureItem
              icon={<BookOpen className="h-4 w-4" />}
              title="Curriculum-Grounded"
              description="Scope, evidence, and retrieval stay anchored to uploaded course materials"
            />
            <FeatureItem
              icon={<Sparkles className="h-4 w-4" />}
              title="Generation + Review"
              description="Create exam versions, regenerate weak questions, and preserve edit history"
            />
            <FeatureItem
              icon={<FileCheck className="h-4 w-4" />}
              title="Quality Instrumentation"
              description="Verifier warnings, evidence traces, feedback labels, and playbook readiness for Phase 4 ACE foundation"
            />
          </div>
        </div>

        <div className="relative z-10">
          <p className="text-sm text-primary-foreground/50">
            Internal Phase 4 ACE foundation for Physics only
          </p>
        </div>
      </div>

      {/* Right Login Panel */}
      <div className="flex w-full lg:w-1/2 flex-col items-center justify-center px-6 py-12 bg-background">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <Activity className="h-4.5 w-4.5" />
            </div>
            <span className="text-lg font-semibold text-foreground">ExamAI</span>
          </div>

          <div className="mb-8">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              {mode === "login" ? "Welcome back" : "Create account"}
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {mode === "login"
                ? "Sign in to your account to continue"
                : "Register a new account to get started"}
            </p>
          </div>

          {successMessage && (
            <div className="mb-4 rounded-lg bg-green-500/10 px-4 py-3 text-sm text-green-600 dark:text-green-400">
              {successMessage}
            </div>
          )}

          {error && (
            <div className="mb-4 rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {mode === "login" ? (
            <form onSubmit={handleLogin} className="flex flex-col gap-5">
              <div className="flex flex-col gap-2">
                <Label htmlFor="email" className="text-sm font-medium text-foreground">
                  Email address
                </Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="lecturer@university.edu"
                  className="h-11"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password" className="text-sm font-medium text-foreground">
                    Password
                  </Label>
                </div>
                <Input
                  id="password"
                  type="password"
                  placeholder="Enter your password"
                  className="h-11"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>

              <Button
                type="submit"
                size="lg"
                className="h-11 w-full font-medium"
                disabled={isLoading}
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    Sign in
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </>
                )}
              </Button>
            </form>
          ) : (
            <form onSubmit={handleRegister} className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="reg-name" className="text-sm font-medium">Full name</Label>
                <Input
                  id="reg-name"
                  placeholder="Dr. John Doe"
                  className="h-11"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="reg-email" className="text-sm font-medium">Email</Label>
                <Input
                  id="reg-email"
                  type="email"
                  placeholder="lecturer@university.edu"
                  className="h-11"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="reg-password" className="text-sm font-medium">Password</Label>
                <Input
                  id="reg-password"
                  type="password"
                  placeholder="Minimum 8 characters"
                  className="h-11"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="reg-dept" className="text-sm font-medium">Department</Label>
                  <Input
                    id="reg-dept"
                    placeholder="Computer Science"
                    className="h-11"
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="reg-uni" className="text-sm font-medium">University</Label>
                  <Input
                    id="reg-uni"
                    placeholder="State University"
                    className="h-11"
                    value={university}
                    onChange={(e) => setUniversity(e.target.value)}
                  />
                </div>
              </div>
              <Button
                type="submit"
                size="lg"
                className="h-11 w-full font-medium"
                disabled={isLoading}
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    Create account
                    <UserPlus className="ml-2 h-4 w-4" />
                  </>
                )}
              </Button>
            </form>
          )}

          <p className="mt-8 text-center text-xs text-muted-foreground">
            {mode === "login" ? (
              <>
                {"Don't have an account? "}
                <button
                  className="font-medium text-primary hover:text-primary/80 transition-colors"
                  onClick={() => { setMode("register"); setError(""); setSuccessMessage("") }}
                >
                  Create one
                </button>
              </>
            ) : (
              <>
                {"Already have an account? "}
                <button
                  className="font-medium text-primary hover:text-primary/80 transition-colors"
                  onClick={() => { setMode("login"); setError(""); setSuccessMessage("") }}
                >
                  Sign in
                </button>
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  )
}

function FeatureItem({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode
  title: string
  description: string
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary-foreground/10">
        {icon}
      </div>
      <div>
        <p className="text-sm font-medium">{title}</p>
        <p className="text-sm text-primary-foreground/60">{description}</p>
      </div>
    </div>
  )
}
