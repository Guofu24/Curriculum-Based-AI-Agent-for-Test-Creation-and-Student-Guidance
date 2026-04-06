"use client"

import { useState, useCallback } from "react"
import { useDropzone } from "react-dropzone"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { 
  Upload, 
  FileText, 
  X, 
  CheckCircle2, 
  AlertCircle,
  File
} from "lucide-react"

interface UploadedFile {
  id: string
  name: string
  size: number
  type: string
  progress: number
  status: "uploading" | "completed" | "error"
  error?: string
}

interface FileUploadProps {
  onFilesUploaded?: (files: File[]) => void
  accept?: Record<string, string[]>
  maxFiles?: number
  maxSize?: number
  className?: string
}

const defaultAccept = {
  "application/pdf": [".pdf"],
  "application/msword": [".doc"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "text/plain": [".txt"],
}

export function FileUpload({
  onFilesUploaded,
  accept = defaultAccept,
  maxFiles = 10,
  maxSize = 50 * 1024 * 1024, // 50MB
  className,
}: FileUploadProps) {
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([])

  const simulateUpload = (file: File) => {
    const fileId = Math.random().toString(36).substring(7)
    const newFile: UploadedFile = {
      id: fileId,
      name: file.name,
      size: file.size,
      type: file.type,
      progress: 0,
      status: "uploading",
    }

    setUploadedFiles(prev => [...prev, newFile])

    // Simulate upload progress
    let progress = 0
    const interval = setInterval(() => {
      progress += Math.random() * 20
      if (progress >= 100) {
        progress = 100
        clearInterval(interval)
        setUploadedFiles(prev =>
          prev.map(f =>
            f.id === fileId
              ? { ...f, progress: 100, status: "completed" as const }
              : f
          )
        )
      } else {
        setUploadedFiles(prev =>
          prev.map(f => (f.id === fileId ? { ...f, progress } : f))
        )
      }
    }, 200)
  }

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      acceptedFiles.forEach(file => {
        simulateUpload(file)
      })
      onFilesUploaded?.(acceptedFiles)
    },
    [onFilesUploaded]
  )

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    accept,
    maxFiles,
    maxSize,
  })

  const removeFile = (fileId: string) => {
    setUploadedFiles(prev => prev.filter(f => f.id !== fileId))
  }

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return "0 B"
    const k = 1024
    const sizes = ["B", "KB", "MB", "GB"]
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i]
  }

  const getFileIcon = (type: string) => {
    if (type.includes("pdf")) return <FileText className="h-5 w-5 text-red-400" />
    if (type.includes("word") || type.includes("document")) return <FileText className="h-5 w-5 text-blue-400" />
    return <File className="h-5 w-5 text-muted-foreground" />
  }

  return (
    <div className={cn("space-y-4", className)}>
      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={cn(
          "relative border-2 border-dashed rounded-xl p-8 transition-all cursor-pointer",
          "hover:border-primary/50 hover:bg-primary/5",
          isDragActive && "border-primary bg-primary/10",
          isDragReject && "border-destructive bg-destructive/10"
        )}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center text-center">
          <div className={cn(
            "flex h-14 w-14 items-center justify-center rounded-full mb-4 transition-colors",
            isDragActive ? "bg-primary/20" : "bg-muted"
          )}>
            <Upload className={cn(
              "h-7 w-7 transition-colors",
              isDragActive ? "text-primary" : "text-muted-foreground"
            )} />
          </div>
          <h3 className="font-medium mb-1">
            {isDragActive ? "Thả file vào đây" : "Kéo thả file hoặc nhấn để chọn"}
          </h3>
          <p className="text-sm text-muted-foreground mb-4">
            Hỗ trợ PDF, DOC, DOCX, TXT (tối đa 50MB)
          </p>
          <Button type="button" variant="outline" size="sm">
            Chọn file
          </Button>
        </div>
      </div>

      {/* Uploaded files list */}
      {uploadedFiles.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">
            File đã tải lên ({uploadedFiles.length})
          </h4>
          <div className="space-y-2">
            {uploadedFiles.map(file => (
              <div
                key={file.id}
                className={cn(
                  "flex items-center gap-3 p-3 rounded-lg border transition-colors",
                  file.status === "completed" && "border-emerald-500/30 bg-emerald-500/5",
                  file.status === "error" && "border-destructive/30 bg-destructive/5",
                  file.status === "uploading" && "border-border bg-muted/30"
                )}
              >
                {getFileIcon(file.type)}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">
                      {file.name}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {formatFileSize(file.size)}
                    </span>
                  </div>
                  {file.status === "uploading" && (
                    <Progress value={file.progress} className="h-1 mt-1.5" />
                  )}
                  {file.error && (
                    <p className="text-xs text-destructive mt-1">{file.error}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {file.status === "uploading" && (
                    <span className="text-xs text-muted-foreground">
                      {Math.round(file.progress)}%
                    </span>
                  )}
                  {file.status === "completed" && (
                    <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                  )}
                  {file.status === "error" && (
                    <AlertCircle className="h-5 w-5 text-destructive" />
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                    onClick={() => removeFile(file.id)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
