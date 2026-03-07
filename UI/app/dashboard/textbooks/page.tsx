"use client"

import { useState, useCallback } from "react"
import Link from "next/link"
import { DashboardHeader } from "@/components/dashboard-header"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Upload,
  FileText,
  MoreVertical,
  Trash2,
  Eye,
  Sparkles,
  CloudUpload,
  BookOpen,
  Calendar,
  Layers,
  Shield,
  X,
} from "lucide-react"

type TextbookStatus = "Processed" | "Processing"

interface Textbook {
  id: string
  name: string
  uploadDate: string
  chaptersDetected: number
  status: TextbookStatus
  fileSize: string
  fileType: string
}

const initialTextbooks: Textbook[] = [
  {
    id: "1",
    name: "Data Structures & Algorithms in Java",
    uploadDate: "Feb 28, 2026",
    chaptersDetected: 14,
    status: "Processed",
    fileSize: "24.5 MB",
    fileType: "PDF",
  },
  {
    id: "2",
    name: "Modern Operating Systems (5th Edition)",
    uploadDate: "Feb 25, 2026",
    chaptersDetected: 12,
    status: "Processed",
    fileSize: "31.2 MB",
    fileType: "PDF",
  },
  {
    id: "3",
    name: "Database System Concepts (7th Edition)",
    uploadDate: "Feb 22, 2026",
    chaptersDetected: 18,
    status: "Processed",
    fileSize: "28.8 MB",
    fileType: "PDF",
  },
  {
    id: "4",
    name: "Computer Networks - A Top Down Approach",
    uploadDate: "Mar 2, 2026",
    chaptersDetected: 0,
    status: "Processing",
    fileSize: "19.3 MB",
    fileType: "DOCX",
  },
]

export default function TextbooksPage() {
  const [textbooks, setTextbooks] = useState<Textbook[]>(initialTextbooks)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [detailBook, setDetailBook] = useState<Textbook | null>(null)

  const simulateUpload = useCallback(() => {
    setIsUploading(true)
    setUploadProgress(0)
    const interval = setInterval(() => {
      setUploadProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval)
          setIsUploading(false)
          setTextbooks((prev) => [
            {
              id: String(prev.length + 1),
              name: "Artificial Intelligence - A Modern Approach",
              uploadDate: "Mar 4, 2026",
              chaptersDetected: 0,
              status: "Processing",
              fileSize: "22.1 MB",
              fileType: "PDF",
            },
            ...prev,
          ])
          return 0
        }
        return prev + 8
      })
    }, 200)
  }, [])

  const handleDelete = (id: string) => {
    setTextbooks((prev) => prev.filter((t) => t.id !== id))
  }

  return (
    <>
      <DashboardHeader title="My Textbooks" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        {/* Page Header */}
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Textbook Library
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Upload and manage your textbooks for long-term use in exam generation.
            </p>
          </div>
          <Badge variant="secondary" className="w-fit mt-2 sm:mt-0 gap-1.5">
            <Shield className="h-3 w-3" />
            Saved for long-term use
          </Badge>
        </div>

        {/* Upload Area */}
        <div
          className={`relative rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${
            isDragging
              ? "border-primary bg-primary/5"
              : "border-border hover:border-primary/40 hover:bg-muted/30"
          }`}
          onDragOver={(e) => {
            e.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setIsDragging(false)
            simulateUpload()
          }}
        >
          {isUploading ? (
            <div className="flex flex-col items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10">
                <CloudUpload className="h-6 w-6 text-primary animate-pulse" />
              </div>
              <div className="w-full max-w-xs">
                <p className="text-sm font-medium text-foreground mb-2">
                  Uploading textbook...
                </p>
                <Progress value={uploadProgress} className="h-2" />
                <p className="mt-2 text-xs text-muted-foreground">
                  {uploadProgress}% complete
                </p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted">
                <Upload className="h-6 w-6 text-muted-foreground" />
              </div>
              <div>
                <p className="text-sm font-medium text-foreground">
                  Drag and drop your textbooks here
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Supports PDF and DOCX files up to 100MB
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={simulateUpload}
              >
                <Upload className="mr-2 h-3.5 w-3.5" />
                Browse files
              </Button>
            </div>
          )}
        </div>

        {/* Textbook Grid */}
        {textbooks.length === 0 ? (
          <EmptyState onUpload={simulateUpload} />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {textbooks.map((book) => (
              <TextbookCard
                key={book.id}
                book={book}
                onDelete={handleDelete}
                onViewDetails={setDetailBook}
              />
            ))}
          </div>
        )}

        {/* Details Dialog */}
        <Dialog open={!!detailBook} onOpenChange={() => setDetailBook(null)}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle className="text-lg">{detailBook?.name}</DialogTitle>
              <DialogDescription>
                Textbook details and metadata
              </DialogDescription>
            </DialogHeader>
            {detailBook && (
              <div className="flex flex-col gap-4 pt-2">
                <div className="grid grid-cols-2 gap-4">
                  <DetailItem icon={<Calendar className="h-4 w-4" />} label="Upload Date" value={detailBook.uploadDate} />
                  <DetailItem icon={<FileText className="h-4 w-4" />} label="File Type" value={detailBook.fileType} />
                  <DetailItem icon={<Layers className="h-4 w-4" />} label="Chapters" value={detailBook.chaptersDetected > 0 ? `${detailBook.chaptersDetected} detected` : "Analyzing..."} />
                  <DetailItem icon={<CloudUpload className="h-4 w-4" />} label="File Size" value={detailBook.fileSize} />
                </div>
                <div className="flex items-center gap-2 rounded-lg bg-muted/50 p-3">
                  <Shield className="h-4 w-4 text-primary shrink-0" />
                  <p className="text-xs text-muted-foreground">
                    This textbook is stored securely and available for all future exam generations.
                  </p>
                </div>
                {detailBook.status === "Processed" && (
                  <Button asChild className="w-full">
                    <Link href="/dashboard/generate">
                      <Sparkles className="mr-2 h-4 w-4" />
                      Generate Exam from this Textbook
                    </Link>
                  </Button>
                )}
              </div>
            )}
          </DialogContent>
        </Dialog>
      </div>
    </>
  )
}

function TextbookCard({
  book,
  onDelete,
  onViewDetails,
}: {
  book: Textbook
  onDelete: (id: string) => void
  onViewDetails: (book: Textbook) => void
}) {
  return (
    <Card className="group relative rounded-2xl shadow-sm transition-shadow hover:shadow-md">
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 shrink-0">
            <BookOpen className="h-5 w-5 text-primary" />
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem onClick={() => onViewDetails(book)}>
                <Eye className="mr-2 h-4 w-4" />
                View details
              </DropdownMenuItem>
              {book.status === "Processed" && (
                <DropdownMenuItem asChild>
                  <Link href="/dashboard/generate">
                    <Sparkles className="mr-2 h-4 w-4" />
                    Generate exam
                  </Link>
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onClick={() => onDelete(book.id)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="mt-4">
          <h3 className="text-sm font-semibold text-foreground leading-snug line-clamp-2">
            {book.name}
          </h3>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {book.fileType} - {book.fileSize}
          </p>
        </div>

        <div className="mt-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Calendar className="h-3 w-3" />
            {book.uploadDate}
          </div>
          <Badge
            variant={book.status === "Processed" ? "secondary" : "outline"}
            className="text-xs"
          >
            {book.status === "Processing" && (
              <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
            )}
            {book.status}
          </Badge>
        </div>

        {book.status === "Processed" && (
          <div className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground rounded-lg bg-muted/50 px-3 py-2">
            <Layers className="h-3 w-3 shrink-0" />
            {book.chaptersDetected} chapters detected
          </div>
        )}

        {book.status === "Processing" && (
          <div className="mt-3">
            <Progress value={65} className="h-1.5" />
            <p className="mt-1.5 text-xs text-muted-foreground">Analyzing chapters...</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function DetailItem({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="flex items-start gap-2">
      <div className="mt-0.5 text-muted-foreground">{icon}</div>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm font-medium text-foreground">{value}</p>
      </div>
    </div>
  )
}

function EmptyState({ onUpload }: { onUpload: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed py-16 px-6 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted">
        <BookOpen className="h-7 w-7 text-muted-foreground" />
      </div>
      <h3 className="mt-4 text-base font-semibold text-foreground">
        No textbooks yet
      </h3>
      <p className="mt-1.5 text-sm text-muted-foreground max-w-sm">
        Upload your first textbook to start generating AI-powered exams from your course materials.
      </p>
      <Button className="mt-5" onClick={onUpload}>
        <Upload className="mr-2 h-4 w-4" />
        Upload Textbook
      </Button>
    </div>
  )
}
