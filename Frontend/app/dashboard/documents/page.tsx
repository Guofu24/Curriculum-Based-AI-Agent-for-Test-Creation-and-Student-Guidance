"use client"

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Empty } from '@/components/ui/empty'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Progress } from '@/components/ui/progress'
import {
  FileText,
  Upload,
  Trash2,
  Eye,
  RefreshCw,
  FileType,
  File,
} from 'lucide-react'
import { toast } from 'sonner'
import { documentsApi, Document } from '@/lib/api'
import { StatusBadge } from '@/components/status-badge'
import { formatDateTime, formatFileSize } from '@/lib/format'
import { cn } from '@/lib/utils'

const FILE_ICONS: Record<string, React.ElementType> = {
  pdf: FileText,
  docx: File,
  pptx: FileType,
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [pollingIds, setPollingIds] = useState<Set<string>>(new Set())

  const fetchDocuments = useCallback(async () => {
    try {
      const response = await documentsApi.list(1, 50)
      setDocuments(response.items)
      
      // Find documents that need polling
      const needsPolling = response.items.filter(
        (doc) => doc.processing_status === 'processing' || doc.processing_status === 'pending'
      )
      setPollingIds(new Set(needsPolling.map(doc => doc.id)))
    } catch (error) {
      console.error('Failed to fetch documents:', error)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  // Poll for processing documents
  useEffect(() => {
    if (pollingIds.size === 0) return

    const interval = setInterval(async () => {
      const currentIds = Array.from(pollingIds)
      if (currentIds.length === 0) return

      const completedIds: string[] = []

      for (const id of currentIds) {
        try {
          const status = await documentsApi.getStatus(id)
          setDocuments(prevDocs => {
            const idx = prevDocs.findIndex(d => d.id === id)
            if (idx === -1) return prevDocs
            if (prevDocs[idx].processing_status === status.processing_status) return prevDocs
            const name = prevDocs[idx].original_filename
            if (status.processing_status === 'completed') {
              toast.success(`Tài liệu "${name}" đã xử lý xong`)
              completedIds.push(id)
            } else if (status.processing_status === 'failed') {
              toast.error(`Xử lý tài liệu "${name}" thất bại`)
              completedIds.push(id)
            }
            const next = [...prevDocs]
            next[idx] = { ...next[idx], processing_status: status.processing_status as Document['processing_status'] }
            return next
          })
        } catch (error) {
          console.error(`Failed to poll status for ${id}:`, error)
        }
      }

      if (completedIds.length > 0) {
        setPollingIds(prev => {
          const next = new Set(prev)
          completedIds.forEach(cid => next.delete(cid))
          return next
        })
      }
    }, 3000)

    return () => clearInterval(interval)
  }, [pollingIds])

  const handleUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return

    const file = files[0]
    const allowedTypes = [
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ]

    if (!allowedTypes.includes(file.type)) {
      toast.error('Chỉ hỗ trợ file PDF, DOCX, PPTX')
      return
    }

    setIsUploading(true)
    setUploadProgress(0)

    // Simulate progress
    const progressInterval = setInterval(() => {
      setUploadProgress(prev => Math.min(prev + 10, 90))
    }, 200)

    try {
      const newDoc = await documentsApi.upload(file)
      setUploadProgress(100)
      clearInterval(progressInterval)

      toast.success('Upload thành công! Đang xử lý tài liệu...')

      if (newDoc.id) {
        setDocuments(prev => [newDoc, ...prev])
        setPollingIds(prev => new Set([...prev, newDoc.id!]))
      } else {
        // Fallback: backend returned document_id instead of id — refetch list
        const response = await documentsApi.list(1, 50)
        setDocuments(response.items)
        setPollingIds(new Set(
          response.items
            .filter(d => d.processing_status === 'processing' || d.processing_status === 'pending')
            .map(d => d.id)
        ))
      }
    } catch (error) {
      clearInterval(progressInterval)
      toast.error(error instanceof Error ? error.message : 'Upload thất bại')
    } finally {
      setIsUploading(false)
      setUploadProgress(0)
    }
  }

  const handleDelete = async (doc: Document) => {
    try {
      await documentsApi.delete(doc.id)
      setDocuments(prev => prev.filter(d => d.id !== doc.id))
      toast.success('Đã xóa tài liệu')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Xóa thất bại')
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    handleUpload(e.dataTransfer.files)
  }

  return (
    <>
      <DashboardHeader breadcrumbs={[{ label: 'Tài liệu' }]} />
      
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Header */}
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Tài liệu</h1>
              <p className="text-muted-foreground">
                Upload và quản lý tài liệu giảng dạy
              </p>
            </div>
            <Button onClick={() => document.getElementById('file-input')?.click()}>
              <Upload className="mr-2 h-4 w-4" />
              Upload tài liệu
            </Button>
            <input
              id="file-input"
              type="file"
              accept=".pdf,.docx,.pptx"
              className="hidden"
              onChange={(e) => handleUpload(e.target.files)}
            />
          </div>

          {/* Upload Zone */}
          <Card
            className={cn(
              "border-2 border-dashed transition-colors cursor-pointer",
              isDragging && "border-primary bg-primary/5",
              isUploading && "pointer-events-none opacity-70"
            )}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => !isUploading && document.getElementById('file-input')?.click()}
          >
            <CardContent className="flex flex-col items-center justify-center py-12">
              {isUploading ? (
                <div className="w-full max-w-xs space-y-4">
                  <div className="flex items-center justify-center">
                    <RefreshCw className="h-8 w-8 animate-spin text-primary" />
                  </div>
                  <Progress value={uploadProgress} className="h-2" />
                  <p className="text-center text-sm text-muted-foreground">
                    Đang upload... {uploadProgress}%
                  </p>
                </div>
              ) : (
                <>
                  <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 mb-4">
                    <Upload className="h-6 w-6 text-primary" />
                  </div>
                  <p className="text-lg font-medium">
                    Kéo thả file vào đây
                  </p>
                  <p className="text-sm text-muted-foreground">
                    hoặc click để chọn file (PDF, DOCX, PPTX)
                  </p>
                </>
              )}
            </CardContent>
          </Card>

          {/* Documents Table */}
          <Card>
            <CardContent className="p-0">
              {isLoading ? (
                <div className="p-6 space-y-4">
                  {[...Array(5)].map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : documents.length === 0 ? (
                <Empty
                  icon={FileText}
                  title="Chưa có tài liệu nào"
                  description="Upload tài liệu đầu tiên để bắt đầu tạo đề thi"
                />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tên file</TableHead>
                      <TableHead className="hidden sm:table-cell">Loại</TableHead>
                      <TableHead>Trạng thái</TableHead>
                      <TableHead className="hidden md:table-cell">Chương</TableHead>
                      <TableHead className="hidden lg:table-cell">Kích thước</TableHead>
                      <TableHead className="hidden lg:table-cell">Ngày upload</TableHead>
                      <TableHead className="w-[100px]">Thao tác</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {documents.map((doc) => {
                      const fileType = doc.file_type?.toLowerCase() || 'pdf'
                      const FileIcon = FILE_ICONS[fileType] || FileText

                      return (
                        <TableRow key={doc.id}>
                          <TableCell>
                            <div className="flex items-center gap-3">
                              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                                <FileIcon className="h-5 w-5 text-primary" />
                              </div>
                              <div className="min-w-0">
                                <p className="font-medium truncate max-w-[200px] lg:max-w-[300px]">
                                  {doc.original_filename}
                                </p>
                                <p className="text-xs text-muted-foreground sm:hidden">
                                  {fileType.toUpperCase()}
                                </p>
                              </div>
                            </div>
                          </TableCell>
                          <TableCell className="hidden sm:table-cell">
                            <span className="uppercase text-xs font-medium text-muted-foreground">
                              {fileType}
                            </span>
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={doc.processing_status} />
                          </TableCell>
                          <TableCell className="hidden md:table-cell text-muted-foreground">
                            {doc.total_chapters ?? '-'}
                          </TableCell>
                          <TableCell className="hidden lg:table-cell text-muted-foreground">
                            {doc.file_size ? formatFileSize(doc.file_size) : '-'}
                          </TableCell>
                          <TableCell className="hidden lg:table-cell text-muted-foreground">
                            {formatDateTime(doc.created_at)}
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1">
                              <Button 
                                variant="ghost" 
                                size="icon" 
                                asChild
                                disabled={doc.processing_status !== 'completed'}
                              >
                                <Link href={`/dashboard/documents/${doc.id}`}>
                                  <Eye className="h-4 w-4" />
                                </Link>
                              </Button>
                              
                              <AlertDialog>
                                <AlertDialogTrigger asChild>
                                  <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive">
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                </AlertDialogTrigger>
                                <AlertDialogContent>
                                  <AlertDialogHeader>
                                    <AlertDialogTitle>Xóa tài liệu?</AlertDialogTitle>
                                    <AlertDialogDescription>
                                      Bạn có chắc muốn xóa &quot;{doc.original_filename}&quot;? 
                                      Hành động này không thể hoàn tác.
                                    </AlertDialogDescription>
                                  </AlertDialogHeader>
                                  <AlertDialogFooter>
                                    <AlertDialogCancel>Hủy</AlertDialogCancel>
                                    <AlertDialogAction
                                      onClick={() => handleDelete(doc)}
                                      className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                    >
                                      Xóa
                                    </AlertDialogAction>
                                  </AlertDialogFooter>
                                </AlertDialogContent>
                              </AlertDialog>
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </main>
    </>
  )
}
