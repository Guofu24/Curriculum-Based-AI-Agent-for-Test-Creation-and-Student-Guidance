"use client"

import { useEffect, useState, use, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  FileText,
  ChevronRight,
  ChevronDown,
  Save,
  RefreshCw,
  ExternalLink,
  BookOpen,
  Layers,
  Calendar,
  Trash2,
  Check,
} from 'lucide-react'
import { toast } from 'sonner'
import { documentsApi, Document, CurriculumNode as APICurriculumNode } from '@/lib/api'
import { StatusBadge } from '@/components/status-badge'
import { formatDateTime, formatFileSize } from '@/lib/format'
import { Spinner } from '@/components/ui/spinner'

interface PageParams {
  id: string
}

export default function DocumentDetailPage({ params }: { params: Promise<PageParams> }) {
  const { id } = use(params)
  const router = useRouter()
  const [document, setDocument] = useState<Document | null>(null)
  const [curriculumNodes, setCurriculumNodes] = useState<APICurriculumNode[]>([])
  // Chapter-level selection (always collapsed by default)
  const [selectedChapterIds, setSelectedChapterIds] = useState<Set<string>>(new Set())
  // Section-level selection, keyed by chapter_id
  const [selectedSectionIds, setSelectedSectionIds] = useState<Record<string, Set<string>>>({})
  // Track which chapters have their sections dropdown open
  const [openChapterIds, setOpenChapterIds] = useState<Set<string>>(new Set())
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isReprocessing, setIsReprocessing] = useState(false)
  const [isRescanning, setIsRescanning] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [editingNode, setEditingNode] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  useEffect(() => {
    async function fetchData() {
      try {
        const [docRes, curriculumRes] = await Promise.all([
          documentsApi.get(id),
          documentsApi.getCurriculumTree(id).catch(() => []),
        ])

        setDocument(docRes)
        setCurriculumNodes(curriculumRes)
        // NO auto-select — user must choose manually
      } catch (error) {
        console.error('Failed to fetch document:', error)
        toast.error('Không thể tải thông tin tài liệu')
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [id])

  // Build tree helpers
  const chapters = useMemo(() =>
    curriculumNodes.filter(node => node.level === 1),
    [curriculumNodes]
  )
  const getSectionsForChapter = (chapterId: string) =>
    curriculumNodes.filter(node => node.level === 2 && node.parent_id === chapterId)
  const getSubsectionsForSection = (sectionId: string) =>
    curriculumNodes.filter(node => node.level === 3 && node.parent_id === sectionId)

  // ── Chapter toggle ──────────────────────────────────────────────────────────
  const toggleChapter = (chapterId: string) => {
    setSelectedChapterIds(prev => {
      const next = new Set(prev)
      if (next.has(chapterId)) {
        next.delete(chapterId)
        // Also clear all sections under this chapter
        setSelectedSectionIds(prevSec => {
          const nextSec = { ...prevSec }
          delete nextSec[chapterId]
          return nextSec
        })
      } else {
        next.add(chapterId)
      }
      return next
    })
  }

  // ── Section toggle ─────────────────────────────────────────────────────────
  const toggleSection = (chapterId: string, sectionId: string) => {
    setSelectedSectionIds(prev => {
      const chapterSections = prev[chapterId] ?? new Set()
      const next = new Set(chapterSections)
      if (next.has(sectionId)) {
        next.delete(sectionId)
      } else {
        next.add(sectionId)
      }
      return { ...prev, [chapterId]: next }
    })
  }

  // ── Select / deselect all sections within a chapter ───────────────────────
  const selectAllSections = (chapterId: string) => {
    const sections = getSectionsForChapter(chapterId)
    const allSectionIds = sections.map(s => s.id)
    const currentlyAllSelected = allSectionIds.every(sid =>
      (selectedSectionIds[chapterId] ?? new Set()).has(sid)
    )

    if (currentlyAllSelected) {
      // Deselect all
      setSelectedSectionIds(prev => {
        const next = { ...prev }
        delete next[chapterId]
        return next
      })
    } else {
      // Select all
      setSelectedSectionIds(prev => ({
        ...prev,
        [chapterId]: new Set(allSectionIds),
      }))
    }
  }

  // ── Open / close sections dropdown for a chapter ──────────────────────────
  const toggleOpenChapter = (chapterId: string) => {
    setOpenChapterIds(prev => {
      const next = new Set(prev)
      if (next.has(chapterId)) {
        next.delete(chapterId)
      } else {
        next.add(chapterId)
      }
      return next
    })
  }

  // ── Save curriculum ───────────────────────────────────────────────────────
  const handleSaveCurriculum = async () => {
    // If chapter selected but no specific sections → treat as "whole chapter"
    // If chapter deselected → not included
    // If section selected → include only those sections
    const nodesToSave = curriculumNodes.filter(node => {
      if (node.level === 1) {
        return selectedChapterIds.has(node.id)
      }
      if (node.level === 2) {
        const parentId = node.parent_id ?? ''
        const isParentSelected = selectedChapterIds.has(parentId)
        if (!isParentSelected) return false
        const selectedInParent = selectedSectionIds[parentId]
        // If specific sections selected, use them; otherwise include all
        return !selectedInParent || selectedInParent.size === 0 || selectedInParent.has(node.id)
      }
      // Subsections: only include if parent section is included
      if (node.level === 3) {
        const parentId = node.parent_id ?? ''
        const grandparentId = curriculumNodes.find(n => n.id === parentId)?.parent_id ?? ''
        const isParentChapterSelected = selectedChapterIds.has(grandparentId)
        if (!isParentChapterSelected) return false
        const selectedInChapter = selectedSectionIds[grandparentId]
        if (!selectedInChapter || selectedInChapter.size === 0) return true
        return selectedInChapter.has(parentId)
      }
      return false
    })

    setIsSaving(true)
    try {
      await documentsApi.updateCurriculumTree(id, nodesToSave)
      toast.success('Đã lưu cấu trúc chương')
    } catch (error) {
      toast.error('Lưu thất bại')
    } finally {
      setIsSaving(false)
    }
  }

  const handleReprocess = async () => {
    setIsReprocessing(true)
    try {
      await documentsApi.reprocess(id)
      toast.success('Đang xử lý lại tài liệu...')
      const updated = await documentsApi.get(id)
      setDocument(updated)
    } catch (error) {
      toast.error('Không thể xử lý lại')
    } finally {
      setIsReprocessing(false)
    }
  }

  const handleRescanStructure = async () => {
    setIsRescanning(true)
    try {
      await documentsApi.rescanStructure(id)
      toast.success('Đang quét lại cấu trúc tài liệu...')
      const updated = await documentsApi.get(id)
      setDocument(updated)
      const tree = await documentsApi.getCurriculumTree(id)
      setCurriculumNodes(tree)
      // Reset selections
      setSelectedChapterIds(new Set())
      setSelectedSectionIds({})
    } catch (error) {
      toast.error('Không thể quét lại cấu trúc')
    } finally {
      setIsRescanning(false)
    }
  }

  const handleOpenFile = async () => {
    try {
      const { url } = await documentsApi.refreshUrl(id)
      window.open(url, '_blank')
    } catch (error) {
      toast.error('Không thể mở file')
    }
  }

  const handleDelete = async () => {
    try {
      await documentsApi.delete(id)
      toast.success('Đã xóa tài liệu')
      router.push('/dashboard/documents')
    } catch (error) {
      toast.error('Xóa thất bại')
    }
  }

  const handleEditTitle = (nodeId: string, currentTitle: string) => {
    setEditingNode(nodeId)
    setEditValue(currentTitle)
  }

  const handleSaveTitle = (nodeId: string) => {
    setCurriculumNodes(prev =>
      prev.map(node =>
        node.id === nodeId ? { ...node, title: editValue } : node
      )
    )
    setEditingNode(null)
    setEditValue('')
  }

  if (isLoading) {
    return (
      <>
        <DashboardHeader breadcrumbs={[
          { label: 'Tài liệu', href: '/dashboard/documents' },
          { label: 'Đang tải...' }
        ]} />
        <main className="flex-1 overflow-auto">
          <div className="container mx-auto p-6 space-y-6">
            <Skeleton className="h-10 w-64" />
            <div className="grid gap-6 lg:grid-cols-3">
              <Skeleton className="h-48 lg:col-span-1" />
              <Skeleton className="h-96 lg:col-span-2" />
            </div>
          </div>
        </main>
      </>
    )
  }

  if (!document) {
    return (
      <>
        <DashboardHeader breadcrumbs={[
          { label: 'Tài liệu', href: '/dashboard/documents' },
          { label: 'Không tìm thấy' }
        ]} />
        <main className="flex-1 overflow-auto">
          <div className="container mx-auto p-6">
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12">
                <FileText className="h-12 w-12 text-muted-foreground/50 mb-4" />
                <p className="text-lg font-medium">Không tìm thấy tài liệu</p>
                <Button className="mt-4" onClick={() => router.push('/dashboard/documents')}>
                  Quay lại
                </Button>
              </CardContent>
            </Card>
          </div>
        </main>
      </>
    )
  }

  const selectedCount = selectedChapterIds.size + Object.values(selectedSectionIds).reduce(
    (acc, s) => acc + s.size, 0
  )

  return (
    <>
      <DashboardHeader breadcrumbs={[
        { label: 'Tài liệu', href: '/dashboard/documents' },
        { label: document.original_filename }
      ]} />

      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6">
          {/* Header */}
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                <FileText className="h-6 w-6 text-primary" />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight">
                  {document.original_filename}
                </h1>
                <StatusBadge status={document.processing_status} />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={handleOpenFile}>
                <ExternalLink className="mr-2 h-4 w-4" />
                Xem file
              </Button>
              <Button
                variant="outline"
                onClick={handleReprocess}
                disabled={isReprocessing}
              >
                {isReprocessing ? (
                  <Spinner className="mr-2" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                Xử lý lại
              </Button>
              <Button
                variant="outline"
                onClick={handleRescanStructure}
                disabled={isRescanning}
              >
                {isRescanning ? (
                  <Spinner className="mr-2" />
                ) : (
                  <RefreshCw className={`mr-2 h-4 w-4 ${isRescanning ? 'animate-spin' : ''}`} />
                )}
                {isRescanning ? 'Đang quét...' : 'Quét lại cấu trúc'}
              </Button>
              <Button
                variant="destructive"
                onClick={() => setShowDeleteDialog(true)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Xóa
              </Button>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            {/* Document Info */}
            <Card className="lg:col-span-1">
              <CardHeader>
                <CardTitle>Thông tin tài liệu</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <InfoRow
                  icon={FileText}
                  label="Định dạng"
                  value={document.file_type?.toUpperCase() || 'N/A'}
                />
                <InfoRow
                  icon={Layers}
                  label="Kích thước"
                  value={document.file_size ? formatFileSize(document.file_size) : 'N/A'}
                />
                <InfoRow
                  icon={BookOpen}
                  label="Số chương"
                  value={document.total_chapters?.toString() || '0'}
                />
                <InfoRow
                  icon={Layers}
                  label="Số chunks"
                  value={document.total_chunks?.toString() || '0'}
                />
                <InfoRow
                  icon={Calendar}
                  label="Ngày upload"
                  value={formatDateTime(document.created_at)}
                />
                <div className="pt-2 border-t">
                  <p className="text-sm text-muted-foreground mb-1">Đã chọn</p>
                  <p className="text-lg font-semibold">
                    {selectedCount === 0 ? (
                      <span className="text-muted-foreground">Chưa chọn gì</span>
                    ) : (
                      <>
                        {selectedChapterIds.size} chương
                        {Object.values(selectedSectionIds).reduce((a, b) => a + b.size, 0) > 0 && (
                          <> + {Object.values(selectedSectionIds).reduce((a, b) => a + b.size, 0)} phần</>
                        )}
                      </>
                    )}
                  </p>
                </div>
              </CardContent>
            </Card>

            {/* Curriculum Tree */}
            <Card className="lg:col-span-2">
              <CardHeader className="flex flex-row items-center justify-between space-y-0">
                <div>
                  <CardTitle>Cấu trúc chương</CardTitle>
                  <CardDescription>
                    Chọn các chương và phần để sử dụng khi tạo đề. Để trống để bỏ chọn tất cả.
                  </CardDescription>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setSelectedChapterIds(new Set())
                      setSelectedSectionIds({})
                      toast.info('Đã bỏ chọn tất cả')
                    }}
                    disabled={selectedCount === 0}
                  >
                    Bỏ chọn tất cả
                  </Button>
                  <Button onClick={handleSaveCurriculum} disabled={isSaving}>
                    {isSaving ? (
                      <Spinner className="mr-2" />
                    ) : (
                      <Save className="mr-2 h-4 w-4" />
                    )}
                    Lưu thay đổi
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {chapters.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center">
                    <BookOpen className="h-12 w-12 text-muted-foreground/50 mb-4" />
                    <p className="text-muted-foreground">
                      Chưa có cấu trúc chương. Vui lòng xử lý lại tài liệu.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {chapters.map((chapter) => {
                      const sections = getSectionsForChapter(chapter.id)
                      const isChapterSelected = selectedChapterIds.has(chapter.id)
                      const isOpen = openChapterIds.has(chapter.id)
                      const selectedInChapter = selectedSectionIds[chapter.id] ?? new Set()
                      const allSectionIds = sections.map(s => s.id)
                      const allSectionsSelected = sections.length > 0 &&
                        allSectionIds.every(sid => selectedInChapter.has(sid))
                      const someSectionsSelected = sections.length > 0 &&
                        allSectionIds.some(sid => selectedInChapter.has(sid)) && !allSectionsSelected

                      return (
                        <div key={chapter.id} className="space-y-1">
                          {/* Chapter row */}
                          <div className="flex items-center gap-2 rounded-lg p-2 hover:bg-muted/50 transition-colors">
                            <Checkbox
                              checked={isChapterSelected}
                              onCheckedChange={() => toggleChapter(chapter.id)}
                              className="shrink-0"
                            />

                            <span className="flex-1 text-sm font-medium">
                              {chapter.title}
                            </span>

                            {sections.length > 0 && (
                              <>
                                {/* Section count badge */}
                                <Badge variant="secondary" className="text-xs">
                                  {selectedInChapter.size > 0
                                    ? `${selectedInChapter.size}/${sections.length} phần`
                                    : `${sections.length} phần`}
                                </Badge>

                                {/* Expand / collapse sections */}
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-6 w-6"
                                  onClick={() => toggleOpenChapter(chapter.id)}
                                  title={isOpen ? 'Thu gọn' : 'Mở rộng'}
                                >
                                  {isOpen ? (
                                    <ChevronDown className="h-4 w-4" />
                                  ) : (
                                    <ChevronRight className="h-4 w-4" />
                                  )}
                                </Button>
                              </>
                            )}
                          </div>

                          {/* Sections dropdown */}
                          {sections.length > 0 && (
                            <Collapsible open={isOpen}>
                              <CollapsibleContent>
                                <div className="pl-10 pr-2 pb-2 space-y-1">
                                  {/* Select All + header */}
                                  <div className="flex items-center gap-2 py-1">
                                    <Checkbox
                                      checked={allSectionsSelected}
                                      // indeterminate is tricky with shadcn, handle manually
                                      onCheckedChange={() => selectAllSections(chapter.id)}
                                      className="shrink-0"
                                    />
                                    <span
                                      className="flex-1 text-xs text-muted-foreground cursor-pointer hover:text-foreground"
                                      onClick={() => selectAllSections(chapter.id)}
                                    >
                                      {allSectionsSelected ? 'Bỏ chọn tất cả phần' : 'Chọn tất cả phần'}
                                    </span>
                                  </div>

                                  {/* Individual sections */}
                                  {sections.map((section) => {
                                    const isSectionSelected = selectedInChapter.has(section.id)

                                    return (
                                      <div key={section.id}>
                                        <div className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/30 transition-colors">
                                          <Checkbox
                                            checked={isSectionSelected}
                                            onCheckedChange={() =>
                                              toggleSection(chapter.id, section.id)
                                            }
                                            className="shrink-0"
                                          />
                                          <span
                                            className={`flex-1 text-xs cursor-pointer ${
                                              isSectionSelected
                                                ? 'font-medium'
                                                : 'text-muted-foreground'
                                            }`}
                                            onClick={() =>
                                              toggleSection(chapter.id, section.id)
                                            }
                                          >
                                            {section.title}
                                          </span>
                                        </div>

                                        {/* Subsections */}
                                        {(() => {
                                          const subs = getSubsectionsForSection(section.id)
                                          if (subs.length === 0) return null
                                          return (
                                            <div className="pl-10 space-y-0.5">
                                              {subs.map(sub => (
                                                <div
                                                  key={sub.id}
                                                  className="flex items-center gap-2 rounded px-2 py-1 hover:bg-muted/20 transition-colors text-xs text-muted-foreground"
                                                >
                                                  <span className="w-3 h-3 rounded-sm border border-muted-foreground/30 inline-block shrink-0" />
                                                  <span>{sub.title}</span>
                                                </div>
                                              ))}
                                            </div>
                                          )
                                        })()}
                                      </div>
                                    )
                                  })}
                                </div>
                              </CollapsibleContent>
                            </Collapsible>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </main>

      {/* Delete Dialog */}
      <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa tài liệu?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn xóa &quot;{document.original_filename}&quot;?
              Tất cả dữ liệu liên quan sẽ bị xóa vĩnh viễn.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function InfoRow({
  icon: Icon,
  label,
  value
}: {
  icon: React.ElementType
  label: string
  value: string
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="font-medium truncate">{value}</p>
      </div>
    </div>
  )
}
