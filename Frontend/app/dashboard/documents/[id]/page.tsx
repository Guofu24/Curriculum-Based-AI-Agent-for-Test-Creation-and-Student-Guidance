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
} from 'lucide-react'
import { toast } from 'sonner'
import { documentsApi, Document, CurriculumNode as APICurriculumNode } from '@/lib/api'
import { CurriculumTree, FlatCurriculumNode } from '@/components/curriculum-tree'
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
  const [selectedChapterIds, setSelectedChapterIds] = useState<Set<string>>(new Set())
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
        
        // Initialize selected chapters
        const chapters = curriculumRes
          .filter(node => node.level === 1)
          .map(node => node.id)
        setSelectedChapterIds(new Set(chapters))
      } catch (error) {
        console.error('Failed to fetch document:', error)
        toast.error('Không thể tải thông tin tài liệu')
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [id])

  const handleSaveCurriculum = async () => {
    setIsSaving(true)
    try {
      await documentsApi.updateCurriculumTree(id, curriculumNodes)
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
      const chapters = tree
        .filter(node => node.level === 1)
        .map(node => node.id)
      setSelectedChapterIds(new Set(chapters))
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

  const toggleChapter = (nodeId: string) => {
    setSelectedChapterIds(prev => {
      const next = new Set(prev)
      if (next.has(nodeId)) {
        next.delete(nodeId)
      } else {
        next.add(nodeId)
      }
      return next
    })
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

  // Build tree structure from flat curriculum
  const chapters = curriculumNodes.filter(node => node.level === 1)
  const getChildren = (parentId: string) => 
    curriculumNodes.filter(node => node.parent_id === parentId)

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
              </CardContent>
            </Card>

            {/* Curriculum Tree */}
            <Card className="lg:col-span-2">
              <CardHeader className="flex flex-row items-center justify-between space-y-0">
                <div>
                  <CardTitle>Cấu trúc chương</CardTitle>
                  <CardDescription>
                    Chọn các chương sẽ sử dụng khi tạo đề
                  </CardDescription>
                </div>
                <Button onClick={handleSaveCurriculum} disabled={isSaving}>
                  {isSaving ? (
                    <Spinner className="mr-2" />
                  ) : (
                    <Save className="mr-2 h-4 w-4" />
                  )}
                  Lưu thay đổi
                </Button>
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
                    {chapters.map((chapter) => (
                      <ChapterNode
                        key={chapter.id}
                        node={chapter}
                        children={getChildren(chapter.id)}
                        getChildren={getChildren}
                        isSelected={selectedChapterIds.has(chapter.id)}
                        onToggle={() => toggleChapter(chapter.id)}
                        editingNode={editingNode}
                        editValue={editValue}
                        setEditValue={setEditValue}
                        onEditTitle={handleEditTitle}
                        onSaveTitle={handleSaveTitle}
                        onCancelEdit={() => setEditingNode(null)}
                      />
                    ))}
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

function ChapterNode({
  node,
  children,
  getChildren,
  isSelected,
  onToggle,
  editingNode,
  editValue,
  setEditValue,
  onEditTitle,
  onSaveTitle,
  onCancelEdit,
}: {
  node: APICurriculumNode
  children: APICurriculumNode[]
  getChildren: (id: string) => APICurriculumNode[]
  isSelected: boolean
  onToggle: () => void
  editingNode: string | null
  editValue: string
  setEditValue: (value: string) => void
  onEditTitle: (id: string, title: string) => void
  onSaveTitle: (id: string) => void
  onCancelEdit: () => void
}) {
  const [isOpen, setIsOpen] = useState(true)
  const hasChildren = children.length > 0
  const isEditing = editingNode === node.id

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 rounded-lg p-2 hover:bg-muted/50 transition-colors">
        {hasChildren ? (
          <Collapsible open={isOpen} onOpenChange={setIsOpen}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="icon" className="h-6 w-6">
                {isOpen ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </Button>
            </CollapsibleTrigger>
          </Collapsible>
        ) : (
          <div className="w-6" />
        )}

        {node.level === 1 && (
          <Checkbox
            checked={isSelected}
            onCheckedChange={onToggle}
            className="shrink-0"
          />
        )}

        {isEditing ? (
          <div className="flex-1 flex items-center gap-2">
            <Input
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              className="h-8"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSaveTitle(node.id)
                if (e.key === 'Escape') onCancelEdit()
              }}
            />
            <Button size="sm" onClick={() => onSaveTitle(node.id)}>
              Lưu
            </Button>
          </div>
        ) : (
          <span
            className="flex-1 text-sm cursor-pointer hover:text-primary"
            onClick={() => onEditTitle(node.id, node.title)}
          >
            {node.title}
          </span>
        )}

        {node.chunk_count !== undefined && (
          <Badge variant="secondary" className="text-xs">
            {node.chunk_count} chunks
          </Badge>
        )}
      </div>

      {hasChildren && (
        <Collapsible open={isOpen}>
          <CollapsibleContent className="pl-6 space-y-1">
            {children.map((child) => (
              <ChapterNode
                key={child.id}
                node={child}
                children={getChildren(child.id)}
                getChildren={getChildren}
                isSelected={false}
                onToggle={() => {}}
                editingNode={editingNode}
                editValue={editValue}
                setEditValue={setEditValue}
                onEditTitle={onEditTitle}
                onSaveTitle={onSaveTitle}
                onCancelEdit={onCancelEdit}
              />
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}
