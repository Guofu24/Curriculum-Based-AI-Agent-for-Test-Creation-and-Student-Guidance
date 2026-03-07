"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import {
  BrainCircuit,
  BookOpen,
  FileCheck,
  Sparkles,
  ArrowRight,
  Loader2,
} from "lucide-react"

export default function LoginPage() {
  const router = useRouter()
  const [isLoading, setIsLoading] = useState(false)

  function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setIsLoading(true)
    setTimeout(() => {
      router.push("/dashboard")
    }, 1200)
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
              <BrainCircuit className="h-5 w-5" />
            </div>
            <span className="text-xl font-semibold tracking-tight">ExamAI</span>
          </div>
        </div>

        <div className="relative z-10 flex flex-col gap-8">
          <div>
            <h1 className="text-4xl font-semibold leading-tight tracking-tight text-balance">
              Generate professional exams with AI intelligence.
            </h1>
            <p className="mt-4 text-lg text-primary-foreground/70 leading-relaxed max-w-md">
              Upload your textbooks, configure constraints, and let AI create validated, curriculum-aligned examinations in minutes.
            </p>
          </div>

          <div className="flex flex-col gap-4">
            <FeatureItem
              icon={<BookOpen className="h-4 w-4" />}
              title="Textbook-Grounded"
              description="Questions strictly derived from your uploaded materials"
            />
            <FeatureItem
              icon={<Sparkles className="h-4 w-4" />}
              title="AI-Powered Generation"
              description="Advanced language models with Bloom taxonomy support"
            />
            <FeatureItem
              icon={<FileCheck className="h-4 w-4" />}
              title="Constraint Validation"
              description="No hallucination, grade-level scope enforcement"
            />
          </div>
        </div>

        <div className="relative z-10">
          <p className="text-sm text-primary-foreground/50">
            Trusted by 500+ university lecturers worldwide
          </p>
        </div>
      </div>

      {/* Right Login Panel */}
      <div className="flex w-full lg:w-1/2 flex-col items-center justify-center px-6 py-12 bg-background">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <BrainCircuit className="h-4.5 w-4.5" />
            </div>
            <span className="text-lg font-semibold text-foreground">ExamAI</span>
          </div>

          <div className="mb-8">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Welcome back
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Sign in to your account to continue
            </p>
          </div>

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
                defaultValue="dr.smith@university.edu"
                required
              />
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password" className="text-sm font-medium text-foreground">
                  Password
                </Label>
                <button
                  type="button"
                  className="text-xs font-medium text-primary hover:text-primary/80 transition-colors"
                >
                  Forgot password?
                </button>
              </div>
              <Input
                id="password"
                type="password"
                placeholder="Enter your password"
                className="h-11"
                defaultValue="password123"
                required
              />
            </div>

            <div className="flex items-center gap-2">
              <Checkbox id="remember" defaultChecked />
              <Label htmlFor="remember" className="text-sm text-muted-foreground font-normal cursor-pointer">
                Remember me for 30 days
              </Label>
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

          <p className="mt-8 text-center text-xs text-muted-foreground">
            {"Don't have an account? "}
            <button className="font-medium text-primary hover:text-primary/80 transition-colors">
              Contact your administrator
            </button>
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
