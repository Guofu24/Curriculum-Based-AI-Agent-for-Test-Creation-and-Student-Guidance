"use client"

import { useCallback, useEffect, useState, useRef } from "react"
import {
  BookOpen,
  CloudUpload,
  FileText,
  Layers,
  Loader2,
  MoreVertical,
  Trash2,
  Upload,
  X,
  CheckCircle,
  Clock,
  AlertCircle,
  Plus,
} from "lucide-react"
import {
  documents as documentsApi,
  courses as coursesApi,
  isReadyStatus,
  type DocumentListItem,
  type Course,
} from "@/lib/api"

function formatFileSize(bytes: number) {
  if (!bytes) return "—"
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} KB`
  return `${bytes} B`
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return "—"
  return new Date(iso).toLocaleDateString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  })
}

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase()
  if (s === "completed" || s === "indexed" || s === "processed" || s === "structured") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 text-xs px-2.5 py-1 font-medium border border-emerald-200 dark:border-emerald-800">
        <CheckCircle className="h-3 w-3" />
        Sẵn sàng
      </span>
    )
  }
  if (s === "processing" || s === "pending") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 text-xs px-2.5 py-1 font-medium border border-amber-200 dark:border-amber-800">
        <Clock className="h-3 w-3" />
        Đang xử lý
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300 text-xs px-2.5 py-1 font-medium border border-red-200 dark:border-red-800">
      <AlertCircle className="h-3 w-3" />
      Lỗi
    </span>
  )
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([])
  const [courses, setCourses] = useState<Course[]>([])
  const [loading, setLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [error, setError] = useState("")
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadData = useCallback(async () => {
    try {
      const [courseList, documentList] = await Promise.all([
        coursesApi.list(),
        documentsApi.listAll(),
      ])
      setCourses(courseList)
      setDocuments(documentList)
    } catch {
      setError("Không thể tải dữ liệu")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const handleUpload = useCallback(async (file: File) => {
    setIsUploading(true)
    setUploadProgress(10)
    setError("")

    const interval = setInterval(() => {
      setUploadProgress((p) => Math.min(p + 8, 90))
    }, 300)

    try {
      const title = file.name.replace(/\.[^.]+$/, "")
      await documentsApi.upload(title, file, { language: "vi" })
      setUploadProgress(100)
      await loadData()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload thất bại")
    } finally {
      clearInterval(interval)
      setIsUploading(false)
      setUploadProgress(0)
    }
  }, [loadData])

  const handleDelete = useCallback(async (id: string) => {
    setDeletingId(id)
    try {
      await documentsApi.delete(id)
      setDocuments((prev) => prev.filter((d) => d.id !== id))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Xóa thất bại")
    } finally {
      setDeletingId(null)
    }
  }, [])

  const readyCount = documents.filter((d) => isReadyStatus(d.status)).length

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b bg-background/60 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BookOpen className="h-4.5 w-4.5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-foreground">Tài liệu</h1>
            <p className="text-xs text-muted-foreground">{documents.length} tài liệu · {readyCount} sẵn sàng sinh đề</p>
          </div>
        </div>
        <button
          className="flex items-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 transition-colors"
          onClick={() => fileInputRef.current?.click()}
        >
          <Plus className="h-4 w-4" />
          Tải lên PDF
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center justify-between mx-6 mt-4 rounded-lg bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300 px-4 py-2.5 text-sm border border-red-200 dark:border-red-800">
          <span>{error}</span>
          <button onClick={() => setError("")}><X className="h-4 w-4" /></button>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void handleUpload(file)
          e.target.value = ""
        }}
      />

      <div className="flex-1 overflow-auto p-6">
        {/* Upload zone */}
        <div
          className={`relative rounded-2xl border-2 border-dashed p-8 mb-6 text-center transition-all ${isDragging ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"}`}
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setIsDragging(false)
            const file = e.dataTransfer.files[0]
            if (file) void handleUpload(file)
          }}
        >
          {isUploading ? (
            <div className="space-y-3">
              <Loader2 className="h-8 w-8 mx-auto text-primary animate-spin" />
              <p className="text-sm font-medium">Đang tải lên và xử lý...</p>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden mx-auto max-w-xs">
                <div className="h-full bg-primary transition-all duration-300" style={{ width: `${uploadProgress}%` }} />
              </div>
              <p className="text-xs text-muted-foreground">{uploadProgress}%</p>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                <CloudUpload className="h-6 w-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium">Kéo thả file PDF vào đây</p>
              <p className="text-xs text-muted-foreground">hoặc <button className="text-primary underline" onClick={() => fileInputRef.current?.click()}>chọn file</button> từ máy</p>
            </div>
          )}
        </div>

        {/* Document grid */}
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted mb-3">
              <FileText className="h-7 w-7 text-muted-foreground" />
            </div>
            <p className="text-sm font-medium">Chưa có tài liệu nào</p>
            <p className="text-xs text-muted-foreground mt-1">Tải lên PDF đầu tiên để bắt đầu sinh đề</p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="group relative rounded-xl border bg-card p-5 shadow-sm hover:shadow-md transition-all"
              >
                <div className="flex items-start justify-between">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <FileText className="h-5 w-5 text-primary" />
                  </div>
                  <div className="flex items-center gap-1">
                    <StatusBadge status={doc.status} />
                    <button
                      className="flex h-7 w-7 items-center justify-center rounded-md opacity-0 group-hover:opacity-100 hover:bg-destructive/10 transition-all"
                      onClick={() => void handleDelete(doc.id)}
                      disabled={deletingId === doc.id}
                    >
                      {deletingId === doc.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold text-foreground line-clamp-2 leading-snug">{doc.title}</h3>
                  <p className="text-xs text-muted-foreground mt-1">{formatFileSize(doc.file_size)} · {doc.file_type.toUpperCase()}</p>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2">
                  <div className="rounded-lg bg-muted/50 p-2.5 text-center">
                    <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                      <FileText className="h-3 w-3" />
                      Trang
                    </div>
                    <div className="mt-0.5 text-sm font-semibold text-foreground">{doc.total_pages_or_slides || "—"}</div>
                  </div>
                  <div className="rounded-lg bg-muted/50 p-2.5 text-center">
                    <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                      <Layers className="h-3 w-3" />
                      Chunks
                    </div>
                    <div className="mt-0.5 text-sm font-semibold text-foreground">{doc.total_chunks || "—"}</div>
                  </div>
                </div>

                <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                  <span>{formatDate(doc.created_at)}</span>
                  {doc.course_id && courses.find((c) => c.id === doc.course_id) && (
                    <span className="text-primary text-xs font-medium">
                      {courses.find((c) => c.id === doc.course_id)?.course_name}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
