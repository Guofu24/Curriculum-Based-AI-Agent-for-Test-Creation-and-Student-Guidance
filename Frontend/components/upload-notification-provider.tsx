"use client"

import { createContext, useCallback, useContext, useEffect, useRef } from 'react'
import {
  UploadNotification,
  useUploadNotifications,
  UploadItem,
} from '@/components/upload-notification'
import {
  createDocumentUploadWebSocket,
  DocumentUploadEvent,
  Document,
  documentsApi,
} from '@/lib/api'

interface UploadNotificationContextValue {
  startUpload: (file: File) => Promise<Document>
  uploads: Map<string, UploadItem>
  dismissUpload: (id: string) => void
}

const UploadNotificationContext = createContext<UploadNotificationContextValue | null>(null)

export function UploadNotificationProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const { uploads, addUpload, updateUpload, setDocumentId, removeUpload, isReady } =
    useUploadNotifications()


  const activeUploadsRef = useRef<Map<string, { ws: ReturnType<typeof createDocumentUploadWebSocket>; uploadId: string; xhr?: XMLHttpRequest }>>(new Map())
  
  // Reconnect WebSocket for uploads restored from sessionStorage.
  // MUST depend on `isReady` (not a custom `hydrated` flag) because:
  //   hydrated flips true → uploads is still empty (sessionStorage hasn't loaded)
  //   sessionStorage loads → uploads populated, but [hydrated] effect doesn't re-run
  // `isReady` is set AFTER sessionStorage is read, so uploads is guaranteed populated.
  const processedOnRehydrate = useRef(new Set<string>())

  useEffect(() => {
    if (!isReady) return

    const DONE_STATUSES = new Set(['indexed', 'processed', 'completed'])
    const FAILED_STATUSES = new Set(['failed'])

    for (const item of uploads.values()) {
      // Only reconnect if: has a real documentId (UUID), is still processing, and no active WS
      const isDocId = item.documentId.includes('-') && item.documentId.length === 36
      if (!isDocId) continue
      if (item.status === 'completed' || item.status === 'failed') continue
      if (activeUploadsRef.current.has(item.documentId)) continue
      // Only process each id once per hydration
      if (processedOnRehydrate.current.has(item.documentId)) continue
      processedOnRehydrate.current.add(item.documentId)

      const docId = item.documentId

      // ── Check actual server status before reconnecting ──────────────────────
      // The upload might have finished while the page was closed/reloaded.
      // In that case there are no more WS events to receive, so we'd be stuck.
      documentsApi.getStatus(docId)
        .then((res) => {
          const serverStatus = res.processing_status

          if (DONE_STATUSES.has(serverStatus)) {
            // Server already done — mark completed and auto-dismiss
            updateUpload(docId, {
              status: 'completed',
              processingPercent: 100,
              message: serverStatus === 'indexed' ? 'Xử lý hoàn tất (đã indexing)!' : 'Xử lý hoàn tất!',
            })
            setTimeout(() => removeUpload(docId), 4000)
            return
          }

          if (FAILED_STATUSES.has(serverStatus)) {
            updateUpload(docId, { status: 'failed', message: 'Xử lý thất bại' })
            return
          }

          // Still processing on server — reconnect WS to keep getting updates
          const ws = createDocumentUploadWebSocket(docId, (event: DocumentUploadEvent) => {
            const isDone = event.type === 'processing_step' &&
              (event.step === 'done' || event.step === 'done_no_embed')

            if (isDone) {
              updateUpload(docId, {
                status: 'completed',
                processingPercent: 100,
                message: event.message || 'Xử lý hoàn tất!',
              })
              setTimeout(() => removeUpload(docId), 5000)
            } else if (event.type === 'processing_step') {
              updateUpload(docId, {
                status: 'processing',
                processingStep: event.step || '',
                processingPercent: event.percent || 0,
                message: event.message || 'Đang xử lý...',
              })
            } else if (event.type === 'processing_completed') {
              updateUpload(docId, { status: 'completed', processingPercent: 100, message: 'Xử lý hoàn tất!' })
              setTimeout(() => removeUpload(docId), 5000)
            } else if (event.type === 'processing_failed') {
              updateUpload(docId, { status: 'failed', message: event.error || 'Xử lý thất bại' })
            }
          })

          if (ws) {
            activeUploadsRef.current.set(docId, { ws, uploadId: docId })
          }
        })
        .catch(() => {
          // If status check fails (e.g. network error or 404), just dismiss the stuck item
          removeUpload(docId)
        })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isReady])

  const startUpload = useCallback((file: File): Promise<Document> => {
    return new Promise((resolve, reject) => {
      const uploadId = addUpload(file.name)
      const { uploadWithProgress } = require('@/lib/api')

      const xhr = new XMLHttpRequest()

      // Register XHR so dismissUpload can abort it during upload phase
      activeUploadsRef.current.set(uploadId, { ws: null as any, uploadId, xhr })

      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
          const percent = Math.round((e.loaded / e.total) * 100)
          updateUpload(uploadId, {
            uploadPercent: percent,
            message: percent < 100 ? 'Đang upload...' : 'Upload xong, đang xử lý...',
          })
        }
      })

      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const doc = JSON.parse(xhr.responseText) as Document
            const docId = doc.id || (doc as unknown as { document_id?: string }).document_id

            // Swap temp uploadId for real documentId
            if (docId) {
              activeUploadsRef.current.delete(uploadId)
              setDocumentId(uploadId, docId)

              updateUpload(docId, {
                status: 'processing',
                message: 'Đang chờ xử lý...',
                processingPercent: 0,
              })

              // Connect WebSocket for processing progress
              const DONE_STATUSES = new Set(['indexed', 'processed', 'completed'])
              let wsReceivedDone = false

              const handleWsEvent = (event: DocumentUploadEvent) => {
                const isDone = event.type === 'processing_step' &&
                  (event.step === 'done' || event.step === 'done_no_embed')

                if (isDone) {
                  wsReceivedDone = true
                  updateUpload(docId, {
                    status: 'completed',
                    processingPercent: 100,
                    message: event.message || 'Xử lý hoàn tất!',
                  })
                  // Auto-dismiss after 5s
                  setTimeout(() => removeUpload(docId), 5000)
                } else if (event.type === 'processing_step') {
                  updateUpload(docId, {
                    status: 'processing',
                    processingStep: event.step || '',
                    processingPercent: event.percent || 0,
                    message: event.message || 'Đang xử lý...',
                  })
                } else if (event.type === 'processing_completed') {
                  wsReceivedDone = true
                  updateUpload(docId, { status: 'completed', processingPercent: 100, message: 'Xử lý hoàn tất!' })
                  setTimeout(() => removeUpload(docId), 5000)
                } else if (event.type === 'processing_failed') {
                  wsReceivedDone = true
                  updateUpload(docId, { status: 'failed', message: event.error || 'Xử lý thất bại' })
                }
              }

              const handleWsClose = () => {
                // WS dropped before we got a terminal event — check server status as fallback
                if (wsReceivedDone) return
                documentsApi.getStatus(docId)
                  .then((res) => {
                    const st = res.processing_status
                    if (DONE_STATUSES.has(st)) {
                      updateUpload(docId, { status: 'completed', processingPercent: 100, message: 'Xử lý hoàn tất!' })
                      setTimeout(() => removeUpload(docId), 4000)
                    } else if (st === 'failed') {
                      updateUpload(docId, { status: 'failed', message: 'Xử lý thất bại' })
                    }
                    // If still 'processing'/'pending' — leave as-is; sessionStorage restore logic will pick it up on next load
                  })
                  .catch(() => { /* network error — leave notification as-is */ })
              }

              const ws = createDocumentUploadWebSocket(docId, handleWsEvent, undefined, handleWsClose)

              // Replace xhr entry with ws entry (xhr is done)
              activeUploadsRef.current.set(docId, { ws, uploadId: docId })
            }

            resolve(doc)
          } catch {
            reject(new Error('Invalid response from server'))
          }
        } else {
          try {
            const err = JSON.parse(xhr.responseText)
            updateUpload(uploadId, { status: 'failed', message: err.detail || 'Upload thất bại' })
            reject(new Error(err.detail || 'Upload thất bại'))
          } catch {
            updateUpload(uploadId, { status: 'failed', message: 'Upload thất bại' })
            reject(new Error('Upload thất bại'))
          }
        }
      })

      xhr.addEventListener('error', () => {
        updateUpload(uploadId, { status: 'failed', message: 'Không thể kết nối server' })
        reject(new Error('Upload thất bại — không thể kết nối server'))
      })

      xhr.addEventListener('abort', () => {
        removeUpload(uploadId)
        reject(new Error('Upload bị hủy'))
      })

      const formData = new FormData()
      formData.append('file', file)

      // Get token
      let token: string | null = null
      if (typeof window !== 'undefined') {
        token = localStorage.getItem('token')
      }

      const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'
      xhr.open('POST', `${API_BASE_URL}/documents/upload`)
      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      }

      xhr.send(formData)
    })
  }, [addUpload, updateUpload, setDocumentId, removeUpload])

  const dismissUpload = useCallback((id: string) => {
    const entry = activeUploadsRef.current.get(id)
    const item = uploads.get(id)
    const isActive = item && (item.status === 'uploading' || item.status === 'processing')

    // Close WebSocket
    if (entry?.ws) {
      entry.ws.close()
      activeUploadsRef.current.delete(id)
    }

    // Abort XHR if still uploading
    if (entry?.xhr) {
      entry.xhr.abort()
    }

    // If item was active with a real documentId → clean up server-side
    const isRealDocId = id.includes('-') && id.length === 36
    if (isActive && isRealDocId) {
      documentsApi.delete(id).catch(() => {
        // Best-effort: log but don't block UI
        console.warn(`[upload-cancel] Failed to delete document ${id} from server`)
      })
    }

    removeUpload(id)
  }, [removeUpload, uploads])

  return (
    <UploadNotificationContext.Provider value={{ startUpload, uploads, dismissUpload }}>
      <UploadNotification uploads={Array.from(uploads.values())} onDismiss={dismissUpload} isReady={isReady} />
      {children}
    </UploadNotificationContext.Provider>
  )
}

export function useUploadNotification() {
  const ctx = useContext(UploadNotificationContext)
  if (!ctx) {
    throw new Error('useUploadNotification must be used within UploadNotificationProvider')
  }
  return ctx
}
