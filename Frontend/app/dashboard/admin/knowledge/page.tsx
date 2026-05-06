"use client"

import { useEffect, useState } from 'react'
import { DashboardHeader } from '@/components/dashboard-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/components/auth-provider'
import { useRouter } from 'next/navigation'
import { UploadCloud, CheckCircle2, Loader2, Database, ChevronDown, BookOpen, FileText } from 'lucide-react'
import { adminApi } from '@/lib/api'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'

interface OutlineItem { chapter: string; sections: string[] }

export default function AdminKnowledgePage() {
  const { user } = useAuth()
  const router = useRouter()

  const [file, setFile] = useState<File | null>(null)
  const [namespace, setNamespace] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [result, setResult] = useState<{ message: string; items_saved: number; chunks_embedded: number } | null>(null)

  // Preview panel
  const [namespaces, setNamespaces] = useState<string[]>([])
  const [previewNS, setPreviewNS] = useState('')
  const [outline, setOutline] = useState<OutlineItem[]>([])
  const [isLoadingNS, setIsLoadingNS] = useState(true)
  const [isLoadingOutline, setIsLoadingOutline] = useState(false)
  const [openChapters, setOpenChapters] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (user && user.role !== 'admin') router.push('/dashboard')
  }, [user, router])

  useEffect(() => {
    adminApi.getNamespaces()
      .then(ns => {
        setNamespaces(ns)
        if (ns.length > 0) setPreviewNS(ns[0])
      })
      .finally(() => setIsLoadingNS(false))
  }, [result]) // Refresh after upload

  useEffect(() => {
    if (!previewNS) return
    setIsLoadingOutline(true)
    setOutline([])
    setOpenChapters(new Set())
    adminApi.getOutline(previewNS)
      .then(data => {
        setOutline(data)
        if (data.length > 0) setOpenChapters(new Set([data[0].chapter]))
      })
      .catch(() => toast.error('Không thể tải outline'))
      .finally(() => setIsLoadingOutline(false))
  }, [previewNS])

  if (user?.role !== 'admin') return null

  const handleUpload = async () => {
    if (!file) return toast.error('Vui lòng chọn file JSON')
    if (!namespace.trim()) return toast.error('Vui lòng nhập tên namespace')

    setIsUploading(true)
    setResult(null)
    try {
      const res = await adminApi.uploadKnowledge(namespace.trim(), file)
      setResult(res)
      toast.success('Upload và Embed thành công!')
      setFile(null)
      // Switch preview to the just-uploaded namespace
      setPreviewNS(namespace.trim())
    } catch (e: any) {
      toast.error(e.message || 'Có lỗi xảy ra')
    } finally {
      setIsUploading(false)
    }
  }

  const toggleChapter = (chapter: string) => {
    setOpenChapters(prev => {
      const next = new Set(prev)
      if (next.has(chapter)) next.delete(chapter); else next.add(chapter)
      return next
    })
  }

  const totalSections = outline.reduce((a, c) => a + c.sections.length, 0)

  return (
    <>
      <DashboardHeader breadcrumbs={[{ label: 'Quản trị viên' }, { label: 'Kiến thức có sẵn' }]} />
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6 space-y-6 max-w-6xl">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Quản lý kiến thức</h1>
            <p className="text-muted-foreground">Upload JSON sách giáo khoa để tự động nhúng vào Pinecone</p>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* ── Upload panel ── */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><UploadCloud className="h-5 w-5" />Upload JSON</CardTitle>
                <CardDescription>File JSON phải là mảng các object: chapter, title, content, url</CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="namespace">Namespace (Pinecone)</Label>
                  <Input id="namespace" value={namespace} onChange={e => setNamespace(e.target.value)}
                    placeholder="VD: textbook_ly12" />
                  <p className="text-xs text-muted-foreground">
                    Upload lại cùng namespace sẽ <span className="text-amber-400 font-medium">xóa và thay thế</span> dữ liệu cũ.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="file">File JSON</Label>
                  <Input id="file" type="file" accept=".json" onChange={e => setFile(e.target.files?.[0] ?? null)} />
                  {file && (
                    <p className="text-xs text-muted-foreground flex items-center gap-1">
                      <FileText className="h-3 w-3" />{file.name} ({(file.size / 1024).toFixed(1)} KB)
                    </p>
                  )}
                </div>

                {result && (
                  <Alert className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20">
                    <CheckCircle2 className="h-4 w-4" />
                    <AlertTitle>Hoàn tất</AlertTitle>
                    <AlertDescription>
                      Lưu <strong>{result.items_saved}</strong> mục vào DB · Embed <strong>{result.chunks_embedded}</strong> chunks lên Pinecone
                    </AlertDescription>
                  </Alert>
                )}
              </CardContent>
              <CardFooter>
                <Button onClick={handleUpload} disabled={!file || !namespace || isUploading} className="w-full">
                  {isUploading
                    ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Đang xử lý và nhúng dữ liệu...</>
                    : <><UploadCloud className="mr-2 h-4 w-4" />Upload &amp; Embed</>}
                </Button>
              </CardFooter>
            </Card>

            {/* ── Preview panel ── */}
            <Card>
              <CardHeader className="flex flex-row items-start justify-between space-y-0">
                <div>
                  <CardTitle className="flex items-center gap-2"><Database className="h-5 w-5" />Xem trước nội dung</CardTitle>
                  <CardDescription>Cấu trúc chương / bài hiện có trong DB</CardDescription>
                </div>
                {!isLoadingNS && namespaces.length > 0 && (
                  <Select value={previewNS} onValueChange={setPreviewNS}>
                    <SelectTrigger className="w-44 text-sm">
                      <SelectValue placeholder="Chọn namespace" />
                    </SelectTrigger>
                    <SelectContent>
                      {namespaces.map(ns => <SelectItem key={ns} value={ns}>{ns}</SelectItem>)}
                    </SelectContent>
                  </Select>
                )}
              </CardHeader>
              <CardContent>
                {isLoadingNS || isLoadingOutline ? (
                  <div className="space-y-3">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
                ) : namespaces.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-2">
                    <Database className="h-10 w-10 opacity-20" />
                    <p className="text-sm">Chưa có namespace nào. Hãy upload file JSON.</p>
                  </div>
                ) : outline.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-8">Namespace này chưa có dữ liệu.</p>
                ) : (
                  <>
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs text-muted-foreground">
                        <strong>{outline.length}</strong> chương · <strong>{totalSections}</strong> bài
                      </span>
                      <Button variant="ghost" size="sm" className="text-xs h-7"
                        onClick={() => setOpenChapters(openChapters.size > 0 ? new Set() : new Set(outline.map(c => c.chapter)))}>
                        {openChapters.size > 0 ? 'Thu gọn tất cả' : 'Mở rộng tất cả'}
                      </Button>
                    </div>
                    <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
                      {outline.map(item => (
                        <Collapsible key={item.chapter} open={openChapters.has(item.chapter)} onOpenChange={() => toggleChapter(item.chapter)}>
                          <CollapsibleTrigger asChild>
                            <button className="flex w-full items-center justify-between rounded-lg border border-border/50 px-3 py-2.5 hover:bg-muted/30 transition-colors text-left">
                              <div className="flex items-center gap-2 min-w-0">
                                <BookOpen className="h-4 w-4 text-primary shrink-0" />
                                <span className="text-sm font-medium truncate">{item.chapter}</span>
                              </div>
                              <div className="flex items-center gap-2 ml-2 shrink-0">
                                <Badge variant="secondary" className="text-xs">{item.sections.length} bài</Badge>
                                <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", openChapters.has(item.chapter) && "rotate-180")} />
                              </div>
                            </button>
                          </CollapsibleTrigger>
                          <CollapsibleContent>
                            <div className="ml-6 mt-1 mb-1 space-y-0.5 border-l border-border/40 pl-3">
                              {item.sections.map(section => (
                                <p key={section} className="text-xs text-muted-foreground py-1 leading-snug">• {section}</p>
                              ))}
                            </div>
                          </CollapsibleContent>
                        </Collapsible>
                      ))}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </>
  )
}
