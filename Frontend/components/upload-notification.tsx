"use client"

import { useEffect, useRef, useState, useCallback } from 'react'
import { UploadProgress } from '@/lib/api'
import { Progress } from '@/components/ui/progress'
import { X, CheckCircle2, AlertCircle, FileText, Loader2 } from 'lucide-react'

export interface UploadItem extends UploadProgress {
  uploadWs?: ReturnType<typeof import('@/lib/api').createDocumentUploadWebSocket> | null
  dismissTimer?: ReturnType<typeof setTimeout>
}

function UploadNotificationItem({
  item,
  onDismiss,
}: {
  item: UploadItem
  onDismiss: (id: string) => void
}) {
  const isUploading = item.status === 'uploading'
  const isProcessing = item.status === 'processing'
  const isDone = item.status === 'completed'
  const isFailed = item.status === 'failed'

  const displayPercent = isUploading
    ? item.uploadPercent
    : item.processingPercent

  return (
    <div className="bg-background border rounded-lg shadow-lg p-3 w-72 flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <div className="flex-shrink-0 mt-0.5">
          {isDone ? (
            <CheckCircle2 className="h-4 w-4 text-green-500" />
          ) : isFailed ? (
            <AlertCircle className="h-4 w-4 text-red-500" />
          ) : (
            <FileText className="h-4 w-4 text-primary" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate" title={item.filename}>
            {item.filename}
          </p>
          <p className="text-xs text-muted-foreground">{item.message}</p>
        </div>
        <button
          onClick={() => onDismiss(item.documentId)}
          className="flex-shrink-0 text-muted-foreground hover:text-foreground transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <Progress value={displayPercent} className="h-1.5" />

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {displayPercent}%
        </span>
        {isProcessing && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            Đang xử lý
          </span>
        )}
        {isDone && (
          <span className="text-xs text-green-600 font-medium">Hoàn tất</span>
        )}
        {isFailed && (
          <span className="text-xs text-red-600 font-medium">Thất bại</span>
        )}
      </div>
    </div>
  )
}

interface UploadNotificationProps {
  uploads: UploadItem[]
  onDismiss: (id: string) => void
  isReady?: boolean
}

export function UploadNotification({ uploads, onDismiss, isReady = true }: UploadNotificationProps) {
  if (!isReady || uploads.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 items-end max-h-[60vh] overflow-y-auto">
      {uploads.map((item) => (
        <UploadNotificationItem
          key={item.documentId}
          item={item}
          onDismiss={onDismiss}
        />
      ))}
    </div>
  )
}

interface PersistedUploadItem {
  documentId: string
  filename: string
  uploadPercent: number
  processingStep: string
  processingPercent: number
  message: string
  status: 'uploading' | 'processing' | 'completed' | 'failed'
}

const STORAGE_KEY = 'exam_ai_active_uploads'

function _loadFromStorage(): Map<string, PersistedUploadItem> {
  if (typeof window === 'undefined') return new Map()
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return new Map()
    const arr: PersistedUploadItem[] = JSON.parse(raw)
    const map = new Map<string, PersistedUploadItem>()
    for (const item of arr) {
      map.set(item.documentId, item)
    }
    return map
  } catch {
    return new Map()
  }
}

function _saveToStorage(uploads: Map<string, UploadItem>) {
  if (typeof window === 'undefined') return
  try {
    const persistable: PersistedUploadItem[] = Array.from(uploads.values()).map(
      ({ documentId, filename, uploadPercent, processingStep, processingPercent, message, status }) => ({
        documentId, filename, uploadPercent, processingStep, processingPercent, message,
        status,
      })
    )
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(persistable))
  } catch {}
}

export function useUploadNotifications() {
  const [uploads, setUploads] = useState<Map<string, UploadItem>>(new Map())
  const [isReady, setIsReady] = useState(false)
  const isHydratedRef = useRef(false)

  useEffect(() => {
    const map = _loadFromStorage()
    if (map.size > 0) {
      setUploads(map)
    }
    setIsReady(true)
    isHydratedRef.current = true
  }, [])

  useEffect(() => {
    if (!isReady) return
    _saveToStorage(uploads)
  }, [uploads, isReady])

  const addUpload = useCallback((filename: string): string => {
    const id = `upload_${Date.now()}_${Math.random().toString(36).slice(2)}`
    setUploads(prev => {
      const next = new Map(prev)
      next.set(id, {
        documentId: id,
        filename,
        uploadPercent: 0,
        processingStep: '',
        processingPercent: 0,
        message: 'Đang upload...',
        status: 'uploading',
      })
      return next
    })
    return id
  }, [])

  const updateUpload = useCallback((id: string, update: Partial<UploadItem>) => {
    setUploads(prev => {
      const next = new Map(prev)
      const existing = next.get(id)
      if (existing) {
        next.set(id, { ...existing, ...update })
      }
      return next
    })
  }, [])

  const setDocumentId = useCallback((uploadId: string, documentId: string) => {
    setUploads(prev => {
      const next = new Map(prev)
      const existing = next.get(uploadId)
      if (existing) {
        next.delete(uploadId)
        next.set(documentId, { ...existing, documentId, status: 'processing' })
      }
      return next
    })
  }, [])

  const removeUpload = useCallback((id: string) => {
    setUploads(prev => {
      const next = new Map(prev)
      const item = next.get(id)
      if (item?.uploadWs) {
        item.uploadWs.close()
      }
      if (item?.dismissTimer) {
        clearTimeout(item.dismissTimer)
      }
      next.delete(id)
      return next
    })
  }, [])

  return { uploads, addUpload, updateUpload, setDocumentId, removeUpload, isReady }
}
