"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { DashboardHeader } from "@/components/dashboard-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Search,
  MoreVertical,
  Eye,
  Copy,
  Trash2,
  Filter,
  X,
  History,
  FileText,
  Loader2,
} from "lucide-react"
import {
  exams as examsApi,
  type ExamListItem,
} from "@/lib/api"

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

export default function HistoryPage() {
  const [searchQuery, setSearchQuery] = useState("")
  const [typeFilter, setTypeFilter] = useState<string>("all")
  const [difficultyFilter, setDifficultyFilter] = useState<string>("all")
  const [deleteDialog, setDeleteDialog] = useState<ExamListItem | null>(null)
  const [exams, setExams] = useState<ExamListItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    examsApi.list()
      .then(setExams)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = exams.filter((exam) => {
    const matchesSearch =
      exam.title.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesType = typeFilter === "all" || exam.exam_type === typeFilter
    const matchesDifficulty =
      difficultyFilter === "all" || exam.difficulty === difficultyFilter
    return matchesSearch && matchesType && matchesDifficulty
  })

  const hasFilters =
    searchQuery !== "" || typeFilter !== "all" || difficultyFilter !== "all"

  const clearFilters = () => {
    setSearchQuery("")
    setTypeFilter("all")
    setDifficultyFilter("all")
  }

  const handleDelete = async () => {
    if (deleteDialog) {
      try {
        await examsApi.delete(deleteDialog.id)
        setExams((prev) => prev.filter((e) => e.id !== deleteDialog.id))
      } catch {
        // silently fail
      }
      setDeleteDialog(null)
    }
  }

  const typeBadgeVariant = (type: string) => {
    switch (type) {
      case "mcq":
        return "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-400 dark:border-blue-800"
      case "essay":
        return "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-400 dark:border-amber-800"
      case "mixed":
        return "bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-950 dark:text-indigo-400 dark:border-indigo-800"
      default:
        return ""
    }
  }

  const diffBadgeVariant = (diff: string) => {
    switch (diff) {
      case "basic":
        return "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-400 dark:border-emerald-800"
      case "advanced":
        return "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-400 dark:border-amber-800"
      case "high_application":
        return "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950 dark:text-rose-400 dark:border-rose-800"
      default:
        return "bg-muted text-muted-foreground"
    }
  }

  return (
    <>
      <DashboardHeader title="Exam History" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        {/* Page Header */}
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Exam History
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            View, duplicate, and manage all your previously generated exams.
          </p>
        </div>

        {/* Filters */}
        <Card className="rounded-2xl shadow-sm">
          <CardContent className="py-4 px-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search exams or textbooks..."
                  className="h-9 pl-9"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
              <div className="flex items-center gap-2">
                <Select value={typeFilter} onValueChange={setTypeFilter}>
                  <SelectTrigger className="h-9 w-40">
                    <Filter className="mr-2 h-3.5 w-3.5 text-muted-foreground" />
                    <SelectValue placeholder="Type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Types</SelectItem>
                    <SelectItem value="mcq">Multiple Choice</SelectItem>
                    <SelectItem value="essay">Essay</SelectItem>
                    <SelectItem value="mixed">Mixed</SelectItem>
                  </SelectContent>
                </Select>
                <Select
                  value={difficultyFilter}
                  onValueChange={setDifficultyFilter}
                >
                  <SelectTrigger className="h-9 w-44">
                    <Filter className="mr-2 h-3.5 w-3.5 text-muted-foreground" />
                    <SelectValue placeholder="Difficulty" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Difficulties</SelectItem>
                    <SelectItem value="basic">Basic</SelectItem>
                    <SelectItem value="advanced">Advanced</SelectItem>
                    <SelectItem value="high_application">High Application</SelectItem>
                    <SelectItem value="custom">Custom</SelectItem>
                  </SelectContent>
                </Select>
                {hasFilters && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-9 w-9 shrink-0"
                    onClick={clearFilters}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Table */}
        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed py-16 px-6 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted">
              <History className="h-7 w-7 text-muted-foreground" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-foreground">
              {hasFilters ? "No matching exams" : "No exams yet"}
            </h3>
            <p className="mt-1.5 text-sm text-muted-foreground max-w-sm">
              {hasFilters
                ? "Try adjusting your filters or search query."
                : "Generate your first exam to see it here."}
            </p>
            {hasFilters && (
              <Button variant="outline" className="mt-4" onClick={clearFilters}>
                Clear filters
              </Button>
            )}
          </div>
        ) : (
          <Card className="rounded-2xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-xs font-medium">Date</TableHead>
                    <TableHead className="text-xs font-medium">Exam Title</TableHead>
                    <TableHead className="text-xs font-medium hidden lg:table-cell">Chapters</TableHead>
                    <TableHead className="text-xs font-medium">Type</TableHead>
                    <TableHead className="text-xs font-medium hidden sm:table-cell">Difficulty</TableHead>
                    <TableHead className="text-xs font-medium text-right w-10">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((exam) => (
                    <TableRow key={exam.id} className="group">
                      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                        {formatDate(exam.created_at)}
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/dashboard/exams/${exam.id}`}
                          className="text-sm font-medium text-foreground hover:text-primary transition-colors"
                        >
                          {exam.title}
                        </Link>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {exam.total_questions} questions
                        </p>
                      </TableCell>
                      <TableCell className="hidden lg:table-cell">
                        <span className="text-sm text-muted-foreground">
                          Ch. {exam.chapters.join(", ")}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={`text-xs whitespace-nowrap capitalize ${typeBadgeVariant(exam.exam_type)}`}
                        >
                          {exam.exam_type}
                        </Badge>
                      </TableCell>
                      <TableCell className="hidden sm:table-cell">
                        <Badge
                          variant="outline"
                          className={`text-xs whitespace-nowrap capitalize ${diffBadgeVariant(exam.difficulty)}`}
                        >
                          {exam.difficulty.replace("_", " ")}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
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
                            <DropdownMenuItem asChild>
                              <Link href={`/dashboard/exams/${exam.id}`}>
                                <Eye className="mr-2 h-4 w-4" />
                                View exam
                              </Link>
                            </DropdownMenuItem>
                            <DropdownMenuItem>
                              <Copy className="mr-2 h-4 w-4" />
                              Duplicate
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-destructive focus:text-destructive"
                              onClick={() => setDeleteDialog(exam)}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        )}

        {/* Delete Dialog */}
        <Dialog open={!!deleteDialog} onOpenChange={() => setDeleteDialog(null)}>
          <DialogContent className="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>Delete exam</DialogTitle>
              <DialogDescription>
                Are you sure you want to delete &ldquo;{deleteDialog?.title}&rdquo;? This action cannot be undone.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteDialog(null)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={handleDelete}>
                <Trash2 className="mr-2 h-4 w-4" />
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </>
  )
}
