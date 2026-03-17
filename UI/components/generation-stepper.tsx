"use client"

import { useState, useEffect, useRef } from "react"
import { Check, Loader2, BookOpen, Database, Sparkles, ShieldCheck, FileCheck } from "lucide-react"
import { cn } from "@/lib/utils"
import type { GenerationStep as SSEStep } from "@/lib/api"

const defaultSteps = [
  { id: 1, label: "Building exam spec", description: "Normalizing your request into a structured exam specification", icon: BookOpen },
  { id: 2, label: "Planning blueprint", description: "Allocating scope, question types, and Bloom targets across the exam", icon: Database },
  { id: 3, label: "Retrieving evidence", description: "Finding the most relevant grounded content inside the selected scope", icon: Sparkles },
  { id: 4, label: "Generating and validating", description: "Creating questions and checking scope, quality, and answerability", icon: ShieldCheck },
  { id: 5, label: "Finalizing exam", description: "Saving the generated version and preparing it for review", icon: FileCheck },
]

export function GenerationStepper({
  steps: sseSteps,
  onComplete,
}: {
  steps?: SSEStep[]
  onComplete: () => void
}) {
  const calledRef = useRef(false)

  // Derive state from SSE steps
  const stepStatuses = defaultSteps.map((ds) => {
    const sse = sseSteps?.find((s) => s.step === ds.id)
    return sse?.status ?? "pending"
  })

  const completedCount = stepStatuses.filter((s) => s === "completed").length
  const allDone = completedCount === defaultSteps.length

  useEffect(() => {
    if (allDone && !calledRef.current) {
      calledRef.current = true
      const timer = setTimeout(onComplete, 800)
      return () => clearTimeout(timer)
    }
  }, [allDone, onComplete])

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="w-full max-w-lg">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
            <Sparkles className="h-7 w-7 text-primary animate-pulse" />
          </div>
          <h2 className="text-xl font-semibold tracking-tight text-foreground">
            Generating your exam
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            This usually takes 30-60 seconds
          </p>
        </div>

        <div className="flex flex-col gap-1">
          {defaultSteps.map((step, index) => {
            const status = stepStatuses[index]
            const isCompleted = status === "completed"
            const isActive = status === "running"
            const isFailed = status === "failed"
            const isPending = !isCompleted && !isActive && !isFailed
            const StepIcon = step.icon

            return (
              <div key={step.id} className="flex items-start gap-4">
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      "flex h-9 w-9 items-center justify-center rounded-xl border-2 transition-all duration-500",
                      isCompleted && "border-primary bg-primary text-primary-foreground",
                      isActive && "border-primary bg-primary/10 text-primary",
                      isFailed && "border-destructive bg-destructive/10 text-destructive",
                      isPending && "border-border bg-muted text-muted-foreground"
                    )}
                  >
                    {isCompleted ? (
                      <Check className="h-4 w-4" />
                    ) : isActive ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <StepIcon className="h-4 w-4" />
                    )}
                  </div>
                  {index < defaultSteps.length - 1 && (
                    <div
                      className={cn(
                        "w-0.5 h-8 transition-colors duration-500",
                        isCompleted ? "bg-primary" : "bg-border"
                      )}
                    />
                  )}
                </div>

                <div className="flex flex-col gap-0.5 pt-1.5">
                  <span
                    className={cn(
                      "text-sm font-medium transition-colors",
                      (isCompleted || isActive) && "text-foreground",
                      isFailed && "text-destructive",
                      isPending && "text-muted-foreground"
                    )}
                  >
                    {step.label}
                    {isCompleted && (
                      <span className="ml-2 text-xs text-primary font-normal">Done</span>
                    )}
                    {isFailed && (
                      <span className="ml-2 text-xs text-destructive font-normal">Failed</span>
                    )}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {step.description}
                  </span>
                </div>
              </div>
            )
          })}
        </div>

        <div className="mt-8">
          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
              style={{
                width: `${(completedCount / defaultSteps.length) * 100}%`,
              }}
            />
          </div>
          <p className="mt-2 text-center text-xs text-muted-foreground">
            {completedCount} of {defaultSteps.length} steps completed
          </p>
        </div>
      </div>
    </div>
  )
}
