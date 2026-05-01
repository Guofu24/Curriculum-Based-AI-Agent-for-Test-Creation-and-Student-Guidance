"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { 
  CheckCircle2, 
  Circle, 
  Loader2, 
  FileText, 
  Brain, 
  CheckSquare,
  Sparkles
} from "lucide-react"
import { cn } from "@/lib/utils"

interface GenerationStep {
  id: string
  title: string
  description: string
  status: "pending" | "running" | "completed" | "error"
  progress?: number
  icon: React.ReactNode
}

interface GenerationProgressProps {
  examId?: string
  onComplete?: () => void
}

export function GenerationProgress({ examId, onComplete }: GenerationProgressProps) {
  const [steps, setSteps] = useState<GenerationStep[]>([
    {
      id: "analyze",
      title: "Phân tích tài liệu",
      description: "Đang trích xuất nội dung và cấu trúc...",
      status: "pending",
      icon: <FileText className="h-5 w-5" />,
    },
    {
      id: "curriculum",
      title: "Xây dựng cây chương trình",
      description: "Đang phân loại theo thang Bloom...",
      status: "pending",
      icon: <Brain className="h-5 w-5" />,
    },
    {
      id: "generate",
      title: "Tạo câu hỏi",
      description: "Đang sinh câu hỏi với AI...",
      status: "pending",
      icon: <Sparkles className="h-5 w-5" />,
    },
    {
      id: "validate",
      title: "Kiểm tra chất lượng",
      description: "Đang đánh giá và tối ưu hóa...",
      status: "pending",
      icon: <CheckSquare className="h-5 w-5" />,
    },
  ])

  const [currentStepIndex, setCurrentStepIndex] = useState(0)
  const [overallProgress, setOverallProgress] = useState(0)

  // Simulate progress
  useEffect(() => {
    const timer = setInterval(() => {
      setSteps(prev => {
        const newSteps = [...prev]
        const currentStep = newSteps[currentStepIndex]
        
        if (!currentStep) return prev

        if (currentStep.status === "pending") {
          currentStep.status = "running"
          currentStep.progress = 0
        } else if (currentStep.status === "running") {
          currentStep.progress = Math.min((currentStep.progress || 0) + Math.random() * 15, 100)
          
          if (currentStep.progress >= 100) {
            currentStep.status = "completed"
            currentStep.progress = 100
            
            if (currentStepIndex < newSteps.length - 1) {
              setCurrentStepIndex(prev => prev + 1)
            } else {
              // All done
              setTimeout(() => {
                onComplete?.()
              }, 1000)
            }
          }
        }

        return newSteps
      })

      // Update overall progress
      setOverallProgress(prev => {
        const completedSteps = steps.filter(s => s.status === "completed").length
        const currentProgress = steps[currentStepIndex]?.progress || 0
        return ((completedSteps * 100 + currentProgress) / steps.length)
      })
    }, 200)

    return () => clearInterval(timer)
  }, [currentStepIndex, steps, onComplete])

  const getStepIcon = (step: GenerationStep) => {
    switch (step.status) {
      case "completed":
        return <CheckCircle2 className="h-5 w-5 text-emerald-500" />
      case "running":
        return <Loader2 className="h-5 w-5 text-primary animate-spin" />
      case "error":
        return <Circle className="h-5 w-5 text-destructive" />
      default:
        return <Circle className="h-5 w-5 text-muted-foreground/50" />
    }
  }

  return (
    <Card className="border-border/50 bg-card/80 backdrop-blur-sm">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Đang tạo đề thi
          </CardTitle>
          <Badge variant="outline" className="bg-primary/10 text-primary border-primary/30">
            {Math.round(overallProgress)}%
          </Badge>
        </div>
        <Progress value={overallProgress} className="h-2 mt-2" />
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {steps.map((step, index) => (
            <div
              key={step.id}
              className={cn(
                "flex items-start gap-4 p-3 rounded-lg transition-all",
                step.status === "running" && "bg-primary/5 border border-primary/20",
                step.status === "completed" && "opacity-60"
              )}
            >
              <div className="flex-shrink-0 mt-0.5">
                {getStepIcon(step)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "font-medium",
                    step.status === "running" && "text-primary",
                    step.status === "pending" && "text-muted-foreground"
                  )}>
                    {step.title}
                  </span>
                  {step.status === "running" && step.progress !== undefined && (
                    <span className="text-xs text-muted-foreground">
                      {Math.round(step.progress)}%
                    </span>
                  )}
                </div>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {step.description}
                </p>
                {step.status === "running" && step.progress !== undefined && (
                  <Progress value={step.progress} className="h-1 mt-2" />
                )}
              </div>
              <div className="flex-shrink-0 p-2 rounded-lg bg-muted/50">
                {step.icon}
              </div>
            </div>
          ))}
        </div>

        {/* Animated dots */}
        <div className="flex items-center justify-center gap-1 mt-6 pt-4 border-t border-border/50">
          <span className="text-sm text-muted-foreground">Vui lòng đợi</span>
          <span className="flex gap-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce"
                style={{ animationDelay: `${i * 0.2}s` }}
              />
            ))}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
