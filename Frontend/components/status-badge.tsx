"use client"

import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'
import type { ExamStatus, BloomLevel } from '@/lib/api'

// Document & Exam Status Badge
type BadgeVariant = 'secondary' | 'default' | 'destructive' | 'outline'

interface StatusConfigEntry {
  label: string
  variant: BadgeVariant
  className?: string
  showSpinner?: boolean
}

type StatusConfig = Record<string, StatusConfigEntry>

const statusConfig: StatusConfig = {
  // Document statuses
  pending: { label: 'Đang chờ', variant: 'secondary' },
  processing: { label: 'Đang xử lý', variant: 'default', showSpinner: true },
  completed: { label: 'Hoàn thành', variant: 'default', className: 'bg-primary/10 text-primary border-primary/20' },
  indexed: { label: 'Hoàn thành', variant: 'default', className: 'bg-primary/10 text-primary border-primary/20' },
  processed: { label: 'Hoàn thành', variant: 'default', className: 'bg-primary/10 text-primary border-primary/20' },
  failed: { label: 'Lỗi', variant: 'destructive' },

  // Exam statuses
  draft: { label: 'Nháp', variant: 'secondary' },
  ready_for_review: { label: 'Chờ duyệt', variant: 'default', className: 'bg-warning/10 text-warning-foreground border-warning/20' },
  regenerating: { label: 'Đang tạo lại', variant: 'default', showSpinner: true },
  published: { label: 'Đã xuất bản', variant: 'default', className: 'bg-primary/10 text-primary border-primary/20' },
}

export function StatusBadge({ 
  status,
  className 
}: { 
  status: keyof typeof statusConfig | ExamStatus | string | unknown
  className?: string 
}) {
  const safeStatus = typeof status === 'string' ? status : 'unknown'
  const config = statusConfig[safeStatus] || {
    label: safeStatus,
    variant: 'secondary' as const,
  }
  
  return (
    <Badge 
      variant={config.variant} 
      className={cn(config.className, className)}
    >
      {config.showSpinner && <Spinner className="mr-1.5 h-3 w-3" />}
      {typeof config.label === 'string' ? config.label : safeStatus}
    </Badge>
  )
}

// Bloom Level Badge
const bloomConfig: Record<BloomLevel, { label: string; className: string }> = {
  nhan_biet: { 
    label: 'Nhận biết', 
    className: 'bg-blue-500/10 text-blue-600 border-blue-500/20 dark:text-blue-400' 
  },
  thong_hieu: { 
    label: 'Thông hiểu', 
    className: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20 dark:text-emerald-400' 
  },
  van_dung: { 
    label: 'Vận dụng', 
    className: 'bg-amber-500/10 text-amber-600 border-amber-500/20 dark:text-amber-400' 
  },
  van_dung_cao: { 
    label: 'Vận dụng cao', 
    className: 'bg-purple-500/10 text-purple-600 border-purple-500/20 dark:text-purple-400' 
  },
}

export function BloomBadge({ 
  level,
  className 
}: { 
  level: BloomLevel | string | unknown
  className?: string 
}) {
  const safeLevel = typeof level === 'string' ? level : 'thong_hieu'
  const config = bloomConfig[safeLevel as BloomLevel] || { label: safeLevel, className: '' }
  
  return (
    <Badge 
      variant="outline" 
      className={cn(config.className, className)}
    >
      {typeof config.label === 'string' ? config.label : safeLevel}
    </Badge>
  )
}

// Question Type Badge
export function QuestionTypeBadge({ 
  type,
  className 
}: { 
  type: 'mcq' | 'essay' | string | unknown
  className?: string 
}) {
  const safeType = typeof type === 'string' ? type : 'mcq'
  const config = safeType === 'mcq'
    ? { label: 'Trắc nghiệm', className: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/20 dark:text-cyan-400' }
    : { label: 'Tự luận', className: 'bg-pink-500/10 text-pink-600 border-pink-500/20 dark:text-pink-400' }
  
  return (
    <Badge 
      variant="outline" 
      className={cn(config.className, className)}
    >
      {config.label}
    </Badge>
  )
}

// Version Change Type Badge
const changeTypeConfig = {
  generate: { label: 'Tạo mới', className: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
  edit_direct: { label: 'Sửa tay', className: 'bg-amber-500/10 text-amber-600 border-amber-500/20' },
  edit_prompt: { label: 'Sửa AI', className: 'bg-purple-500/10 text-purple-600 border-purple-500/20' },
  regenerate: { label: 'Tạo lại', className: 'bg-orange-500/10 text-orange-600 border-orange-500/20' },
  published: { label: 'Xuất bản', className: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20' },
  restore: { label: 'Khôi phục', className: 'bg-gray-500/10 text-gray-600 border-gray-500/20' },
}

export function ChangeTypeBadge({
  type,
  className
}: {
  type: keyof typeof changeTypeConfig | string
  className?: string
}) {
  const safeType = typeof type === 'string' ? type : String(type)
  const config = changeTypeConfig[safeType as keyof typeof changeTypeConfig] || { label: safeType, className: '' }

  return (
    <Badge
      variant="outline"
      className={cn(config.className, className)}
    >
      {typeof config.label === 'string' ? config.label : safeType}
    </Badge>
  )
}
