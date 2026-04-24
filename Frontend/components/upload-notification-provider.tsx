"use client"

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import {
  UploadNotification,
  useUploadNotifications,
  UploadItem,
} from '@/components/upload-notification'
import {
  createDocumentUploadWebSocket,
  DocumentUploadEvent,
  Document,
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

  const activeUploadsRef = useRef<Map<string, { ws: ReturnType<typeof createDocumentUploadWebSocket>; uploadId: string }>>(new Map())
  const [hydrated, setHydrated] = useState(false)

  // Reconnect WebSocket for uploads restored from sessionStorage
  useEffect(() => {
    if (!hydrated) {
      setHydrated(true)
      return
    }
    for (const item of uploads.values()) {
      // Only reconnect if: has a real documentId (UUID), is still processing, and no active WS
      const isDocId = item.documentId.includes('-') && item.documentId.length === 36
      if (!isDocId) continue
      if (item.status === 'completed' || item.status === 'failed') continue
      if (activeUploadsRef.current.has(item.documentId)) continue

      const ws = createDocumentUploadWebSocket(item.documentId, (event: DocumentUploadEvent) => {
        if (event.type === 'processing_step') {
          updateUpload(item.documentId, {
            status: 'processing',
            processingStep: event.step || '',
            processingPercent: event.percent || 0,
            message: event.message || 'Đang xử lý...',
          })
        } else if (event.type === 'processing_completed') {
          updateUpload(item.documentId, {
            status: 'completed',
            processingPercent: 100,
            message: 'Xử lý hoàn tất!',
          })
          const timer = setTimeout(() => removeUpload(item.documentId), 5000)
          activeUploadsRef.current.set(item.documentId, { ws, uploadId: item.documentId })
        } else if (event.type === 'processing_failed') {
          updateUpload(item.documentId, {
            status: 'failed',
            message: event.error || 'Xử lý thất bại',
          })
        }
      })

      activeUploadsRef.current.set(item.documentId, { ws, uploadId: item.documentId })
    }
  }, [hydrated])

  const startUpload = useCallback((file: File): Promise<Document> => {
    return new Promise((resolve, reject) => {
      const uploadId = addUpload(file.name)
      const { uploadWithProgress } = require('@/lib/api')

      const xhr = new XMLHttpRequest()

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
              const ws = createDocumentUploadWebSocket(docId, (event: DocumentUploadEvent) => {
                if (event.type === 'processing_step') {
                  updateUpload(docId, {
                    status: 'processing',
                    processingStep: event.step || '',
                    processingPercent: event.percent || 0,
                    message: event.message || 'Đang xử lý...',
                  })
                } else if (event.type === 'processing_completed') {
                  updateUpload(docId, {
                    status: 'completed',
                    processingPercent: 100,
                    message: 'Xử lý hoàn tất!',
                  })
                  // Auto-dismiss after 5s
                  const timer = setTimeout(() => removeUpload(docId), 5000)
                  activeUploadsRef.current.set(docId, { ws, uploadId: docId })
                } else if (event.type === 'processing_failed') {
                  updateUpload(docId, {
                    status: 'failed',
                    message: event.error || 'Xử lý thất bại',
                  })
                }
              }, undefined, () => {
                // onClose: connection closed
              })

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
    if (entry?.ws) {
      entry.ws.close()
      activeUploadsRef.current.delete(id)
    }
    removeUpload(id)
  }, [removeUpload])

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
