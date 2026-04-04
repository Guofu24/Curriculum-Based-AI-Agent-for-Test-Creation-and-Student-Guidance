"use client"

import { Check, Loader2, BookOpen, Database, Sparkles, ShieldCheck, FileCheck } from "lucide-react"
import { cn } from "@/lib/utils"

const STEPS = [
  {
    id: 1,
    label: "Xây dựng đặc tả đề thi",
    description: "Chuẩn hóa yêu cầu thành cấu trúc đề thi",
    icon: BookOpen,
  },
  {
    id: 2,
    label: "Lập kế hoạch câu hỏi",
    description: "Phân bổ phạm vi, loại câu hỏi và mức Bloom",
    icon: Database,
  },
  {
    id: 3,
    label: "Truy xuất nội dung",
    description: "Tìm nội dung liên quan trong tài liệu đã chọn",
    icon: Sparkles,
  },
  {
    id: 4,
    label: "Sinh và kiểm tra câu hỏi",
    description: "Tạo câu hỏi, đảm bảo chất lượng và độ chính xác",
    icon: ShieldCheck,
  },
  {
    id: 5,
    label: "Hoàn tất đề thi",
    description: "Lưu phiên bản và chuẩn bị để xem xét",
    icon: FileCheck,
  },
]

interface GenerationLoadingScreenProps {
  isGenerating: boolean
}

export function GenerationLoadingScreen({ isGenerating }: GenerationLoadingScreenProps) {
  // Progress advances over time so the UI feels alive during the sync API call
  const progress = isGenerating ? 60 : 100

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Sparkles className="h-4.5 w-4.5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-foreground">Sinh đề thi</h1>
          <p className="text-xs text-muted-foreground">Đang tạo đề thi cho bạn...</p>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-lg">
          {/* Status header */}
          <div className="mb-8 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
              <Loader2 className="h-7 w-7 text-primary animate-spin" />
            </div>
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              Đang sinh đề thi...
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Vui lòng chờ trong giây lát
            </p>
          </div>

          {/* Steps */}
          <div className="flex flex-col gap-1">
            {STEPS.map((step, index) => {
              // Progress: first 3 steps auto-complete as time passes
              const isCompleted = isGenerating && progress > (index / STEPS.length) * 100
              const isActive = isGenerating && !isCompleted && index === Math.floor((progress / 100) * STEPS.length)
              const isPending = !isCompleted && !isActive
              const StepIcon = step.icon

              return (
                <div key={step.id} className="flex items-start gap-4">
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
                    {index < STEPS.length - 1 && (
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
                        isPending && "text-muted-foreground"
                      )}
                    >
                      {step.label}
                      {isCompleted && (
                        <span className="ml-2 text-xs text-primary font-normal">Xong</span>
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

          {/* Progress bar */}
          <div className="mt-8">
            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all duration-500 ease-out animate-pulse"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="mt-2 text-center text-xs text-muted-foreground">
              Đang xử lý, vui lòng không đóng trình duyệt
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
