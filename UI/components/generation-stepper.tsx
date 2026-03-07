"use client"

import { useState, useEffect } from "react"
import { Check, Loader2, BookOpen, Database, Sparkles, ShieldCheck, FileCheck } from "lucide-react"
import { cn } from "@/lib/utils"

const steps = [
  {
    id: 1,
    label: "Parsing textbook",
    description: "Extracting content from selected chapters",
    icon: BookOpen,
    duration: 2000,
  },
  {
    id: 2,
    label: "Retrieving knowledge",
    description: "Building knowledge graph from textbook content",
    icon: Database,
    duration: 2500,
  },
  {
    id: 3,
    label: "Generating questions",
    description: "AI is crafting exam questions based on your configuration",
    icon: Sparkles,
    duration: 3000,
  },
  {
    id: 4,
    label: "Validating constraints",
    description: "Checking hallucination, scope, and difficulty alignment",
    icon: ShieldCheck,
    duration: 1500,
  },
  {
    id: 5,
    label: "Finalizing exam",
    description: "Formatting and organizing the final exam document",
    icon: FileCheck,
    duration: 1000,
  },
]

export function GenerationStepper({
  onComplete,
}: {
  onComplete: () => void
}) {
  const [currentStep, setCurrentStep] = useState(0)
  const [completedSteps, setCompletedSteps] = useState<number[]>([])

  useEffect(() => {
    if (currentStep >= steps.length) {
      const timer = setTimeout(onComplete, 600)
      return () => clearTimeout(timer)
    }

    const timer = setTimeout(() => {
      setCompletedSteps((prev) => [...prev, currentStep])
      setCurrentStep((prev) => prev + 1)
    }, steps[currentStep].duration)

    return () => clearTimeout(timer)
  }, [currentStep, onComplete])

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
          {steps.map((step, index) => {
            const isCompleted = completedSteps.includes(index)
            const isActive = currentStep === index
            const isPending = !isCompleted && !isActive
            const StepIcon = step.icon

            return (
              <div key={step.id} className="flex items-start gap-4">
                {/* Step Indicator */}
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      "flex h-9 w-9 items-center justify-center rounded-xl border-2 transition-all duration-500",
                      isCompleted && "border-primary bg-primary text-primary-foreground",
                      isActive && "border-primary bg-primary/10 text-primary",
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
                  {index < steps.length - 1 && (
                    <div
                      className={cn(
                        "w-0.5 h-8 transition-colors duration-500",
                        isCompleted ? "bg-primary" : "bg-border"
                      )}
                    />
                  )}
                </div>

                {/* Step Content */}
                <div className="flex flex-col gap-0.5 pt-1.5">
                  <span
                    className={cn(
                      "text-sm font-medium transition-colors",
                      isCompleted && "text-foreground",
                      isActive && "text-foreground",
                      isPending && "text-muted-foreground"
                    )}
                  >
                    {step.label}
                    {isCompleted && (
                      <span className="ml-2 text-xs text-primary font-normal">Done</span>
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

        {/* Progress Bar */}
        <div className="mt-8">
          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
              style={{
                width: `${((completedSteps.length) / steps.length) * 100}%`,
              }}
            />
          </div>
          <p className="mt-2 text-center text-xs text-muted-foreground">
            Step {Math.min(currentStep + 1, steps.length)} of {steps.length}
          </p>
        </div>
      </div>
    </div>
  )
}
