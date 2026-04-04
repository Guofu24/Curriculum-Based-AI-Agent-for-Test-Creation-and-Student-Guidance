"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import {
  AlertCircle,
  BookOpen,
  ChevronRight,
  FileText,
  Layers,
  Loader2,
  Sparkles,
  Wand2,
  CheckCircle2,
  RefreshCw,
} from "lucide-react"
import {
  documents as documentsApi,
  generation as generationApi,
  isReadyStatus,
  type DocumentListItem,
  type CurriculumNode,
  type ExamGenerationRequest,
} from "@/lib/api"
import { GenerationLoadingScreen } from "@/components/generation-loading-screen"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

function flattenNodes(nodes: CurriculumNode[]): CurriculumNode[] {
  return nodes.flatMap((node) => [node, ...flattenNodes(node.children || [])])
}

function buildScopePayload(node: CurriculumNode) {
  const scopeId = node.id || `${node.section_type}:${node.chapter_number}:${node.section_order}:${node.title}`
  return {
    scope_id: scopeId,
    section_id: node.id || undefined,
    scope_type: node.section_type || "topic",
    title: node.title,
    chapter_number: node.chapter_number || 0,
    page_from: node.page_from ?? null,
    page_to: node.page_to ?? null,
    tags: [
      `section:${node.id || scopeId}`,
      node.scope_label || `${node.section_type || "topic"}:${node.chapter_number || 0}`,
      ...(node.chapter_number ? [`chapter:${node.chapter_number}`] : []),
    ],
  }
}

export default function GenerateExamPage() {
  const router = useRouter()
  const [documents, setDocuments] = useState<DocumentListItem[]>([])
  const [loadingSources, setLoadingSources] = useState(true)
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>("")
  const [curriculumTree, setCurriculumTree] = useState<CurriculumNode[]>([])
  const [loadingTree, setLoadingTree] = useState(false)
  const [selectedScopeIds, setSelectedScopeIds] = useState<string[]>([])
  const [totalQuestions, setTotalQuestions] = useState("10")
  const [timeLimit, setTimeLimit] = useState("45")
  const [prompt, setPrompt] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationError, setGenerationError] = useState("")
  const [generatedExamId, setGeneratedExamId] = useState<string | null>(null)
  const [rescanning, setRescanning] = useState(false)

  const loadSources = useCallback(async () => {
    try {
      const allDocs = await documentsApi.listAll()
      setDocuments(allDocs)
      if (allDocs.length > 0 && !selectedDocumentId) {
        setSelectedDocumentId(allDocs[0].id)
      }
    } finally {
      setLoadingSources(false)
    }
  }, [selectedDocumentId])

  useEffect(() => {
    void loadSources()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const readyDocuments = useMemo(
    () => documents.filter((d) => isReadyStatus(d.status)),
    [documents],
  )

  const selectedDocument = useMemo(
    () => documents.find((d) => d.id === selectedDocumentId) || null,
    [documents, selectedDocumentId],
  )

  // Load curriculum tree when document changes
  useEffect(() => {
    if (!selectedDocumentId) {
      setCurriculumTree([])
      setSelectedScopeIds([])
      return
    }
    let cancelled = false
    setLoadingTree(true)
    setSelectedScopeIds([])
    void documentsApi
      .getCurriculumTree(selectedDocumentId)
      .then((tree) => {
        if (!cancelled) {
          setCurriculumTree(tree)
          // Pre-select all scope nodes
          const flat = flattenNodes(tree)
          const ids = flat
            .map((n) => buildScopePayload(n).scope_id)
            .filter(Boolean)
          setSelectedScopeIds(ids as string[])
        }
      })
      .catch(() => {
        if (!cancelled) setCurriculumTree([])
      })
      .finally(() => {
        if (!cancelled) setLoadingTree(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedDocumentId])

  const scopeNodes = useMemo(() => flattenNodes(curriculumTree), [curriculumTree])
  const scopeNodeMap = useMemo(
    () => new Map(scopeNodes.map((n) => [buildScopePayload(n).scope_id || "", n])),
    [scopeNodes],
  )
  const selectedScope = useMemo(
    () =>
      selectedScopeIds
        .map((id) => {
          const node = scopeNodeMap.get(id)
          return node ? buildScopePayload(node) : null
        })
        .filter((v): v is NonNullable<typeof v> => v !== null),
    [scopeNodeMap, selectedScopeIds],
  )

  const toggleScope = useCallback((scopeId: string, checked: boolean) => {
    setSelectedScopeIds((prev) => {
      if (checked) return Array.from(new Set([...prev, scopeId]))
      return prev.filter((id) => id !== scopeId)
    })
  }, [])

  const selectAllScope = useCallback(() => {
    setSelectedScopeIds(
      scopeNodes.map((n) => buildScopePayload(n).scope_id || "").filter(Boolean) as string[],
    )
  }, [scopeNodes])

  const clearScope = useCallback(() => setSelectedScopeIds([]), [])

  const handleRescanStructure = useCallback(async () => {
    if (!selectedDocumentId) return
    setRescanning(true)
    try {
      await documentsApi.rescanStructure(selectedDocumentId)
      // Reload curriculum tree
      const tree = await documentsApi.getCurriculumTree(selectedDocumentId)
      setCurriculumTree(tree)
      const flat = flattenNodes(tree)
      const ids = flat.map((n) => buildScopePayload(n).scope_id).filter(Boolean)
      setSelectedScopeIds(ids as string[])
    } catch {
      // ignore — tree stays empty or as-is
    } finally {
      setRescanning(false)
    }
  }, [selectedDocumentId])

  // Redirect once generation completes (exam_id is set after the sync API returns)
  useEffect(() => {
    if (!generatedExamId) return
    router.push(`/dashboard/exams/${generatedExamId}`)
  }, [generatedExamId, router])

  const handleGenerate = useCallback(async () => {
    if (!selectedDocument || selectedScope.length === 0) return
    const qCount = Number(totalQuestions)
    if (qCount <= 0) return

    setIsGenerating(true)
    setGenerationError("")

    const requestPayload: ExamGenerationRequest = {
      document_id: selectedDocument.id,
      chapters: [],
      scope: selectedScope,
      prompt: prompt.trim(),
      instructions: "",
      total_questions: qCount,
      question_type: "mcq_single_answer",
      exam_type: "mcq",
      num_variants: 1,
      gradually_increasing: false,
      constraints: {
        strict_grounding: true,
        allow_applied_questions: false,
        creativity_level: 0,
        bloom_levels: ["remember", "understand", "apply", "analyze"],
        max_concurrency: 1,
      },
      time_limit_minutes: Number(timeLimit) || undefined,
      output_language: "vi",
      formatting_preferences: {
        subject: "physics",
        language: "vi",
      },
    }

    try {
      const result = await generationApi.generate(requestPayload)
      // setGeneratedExamId triggers redirect via useEffect above
      setGeneratedExamId(result.exam_id)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Sinh đề thất bại"
      setGenerationError(message)
      setIsGenerating(false)
    }
  }, [selectedDocument, selectedScope, totalQuestions, timeLimit, prompt])

  // Generation loading screen — animated stepper while request is in-flight
  if (isGenerating) {
    return (
      <GenerationLoadingScreen isGenerating={true} />
    )
  }

  // Initial loading
  if (loadingSources) {
    return (
      <div className="flex flex-col h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  // No ready documents
  if (readyDocuments.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-3 px-6 py-4 border-b">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Sparkles className="h-4.5 w-4.5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-foreground">Sinh đề thi</h1>
            <p className="text-xs text-muted-foreground">Tạo đề thi từ tài liệu</p>
          </div>
        </div>
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="max-w-sm text-center space-y-3">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-muted">
              <AlertCircle className="h-6 w-6 text-muted-foreground" />
            </div>
            <p className="text-sm font-semibold">Chưa có tài liệu sẵn sàng</p>
            <p className="text-xs text-muted-foreground">
              Hãy tải lên và chờ xử lý ít nhất một tài liệu PDF trước khi sinh đề.
            </p>
            <Button asChild>
              <a href="/dashboard/documents">
                <ChevronRight className="mr-1 h-4 w-4" />
                Tải tài liệu
              </a>
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b bg-background/60 backdrop-blur-sm">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Sparkles className="h-4.5 w-4.5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-foreground">Sinh đề thi</h1>
          <p className="text-xs text-muted-foreground">Tạo đề thi từ tài liệu đã xử lý</p>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {/* Step 1: Pick document */}
          <div className="rounded-xl border bg-card shadow-sm p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">1</div>
              <h2 className="text-base font-semibold text-foreground">Chọn tài liệu nguồn</h2>
            </div>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>Tài liệu</Label>
                <Select value={selectedDocumentId} onValueChange={setSelectedDocumentId}>
                  <SelectTrigger className="h-11">
                    <SelectValue placeholder="Chọn tài liệu..." />
                  </SelectTrigger>
                  <SelectContent>
                    {readyDocuments.map((doc) => (
                      <SelectItem key={doc.id} value={doc.id}>
                        <div className="flex items-center gap-2">
                          <BookOpen className="h-4 w-4 text-muted-foreground" />
                          {doc.title}
                          <span className="text-xs text-muted-foreground ml-1">
                            · {doc.total_pages_or_slides || "?"} trang
                          </span>
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {selectedDocument && (
                <div className="grid grid-cols-3 gap-3 p-3 rounded-lg bg-muted/40 border">
                  <div className="text-center">
                    <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                      <FileText className="h-3 w-3" />
                      Trang
                    </div>
                    <div className="mt-1 text-lg font-semibold">{selectedDocument.total_pages_or_slides || "—"}</div>
                  </div>
                  <div className="text-center">
                    <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                      <Layers className="h-3 w-3" />
                      Chunks
                    </div>
                    <div className="mt-1 text-lg font-semibold">{selectedDocument.total_chunks || "—"}</div>
                  </div>
                  <div className="text-center">
                    <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                      <CheckCircle2 className="h-3 w-3" />
                      Trạng thái
                    </div>
                    <div className="mt-1 text-sm font-medium text-emerald-600">
                      {selectedDocument.status}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Step 2: Scope selection */}
          <div className="rounded-xl border bg-card shadow-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">2</div>
                <h2 className="text-base font-semibold text-foreground">Chọn phạm vi câu hỏi</h2>
              </div>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={selectAllScope} disabled={scopeNodes.length === 0}>
                  Chọn tất cả
                </Button>
                <Button variant="ghost" size="sm" onClick={clearScope} disabled={selectedScopeIds.length === 0}>
                  Bỏ chọn
                </Button>
              </div>
            </div>

            {loadingTree ? (
              <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Đang tải cấu trúc tài liệu...
              </div>
            ) : curriculumTree.length === 0 ? (
              <div className="py-6 text-center space-y-3">
                <div className="flex flex-col items-center gap-2 text-sm text-muted-foreground">
                  <AlertCircle className="h-8 w-8 text-amber-500" />
                  <p>Tài liệu chưa có cấu trúc.</p>
                  <p className="text-xs text-muted-foreground">
                    Đang xử lý hoặc không tìm thấy heading tree. Thử quét lại cấu trúc.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRescanStructure}
                  disabled={rescanning}
                >
                  {rescanning ? (
                    <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Đang quét...</>
                  ) : (
                    <><RefreshCw className="mr-2 h-4 w-4" /> Quét lại cấu trúc</>
                  )}
                </Button>
              </div>
            ) : (
              <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                {scopeNodes.map((node) => {
                  const scopeId = buildScopePayload(node).scope_id || ""
                  const checked = selectedScopeIds.includes(scopeId)
                  const isChapter = node.section_type === "chapter"

                  return (
                    <div
                      key={scopeId}
                      className={`flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors cursor-pointer ${
                        isChapter
                          ? "bg-muted/60 font-medium"
                          : "hover:bg-muted/30"
                      }`}
                      style={{ marginLeft: isChapter ? 0 : `${Math.min((node.chapter_number - 1) * 16, 48)}px` }}
                      onClick={() => toggleScope(scopeId, !checked)}
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={(val) => toggleScope(scopeId, val === true)}
                        onClick={(e) => e.stopPropagation()}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-foreground truncate">{node.title}</div>
                        {node.page_from || node.page_to ? (
                          <div className="text-xs text-muted-foreground">
                            Trang {node.page_from || "?"}–{node.page_to || "?"}
                          </div>
                        ) : null}
                      </div>
                      <Badge variant="outline" className="text-xs shrink-0 capitalize">
                        {node.section_type}
                      </Badge>
                    </div>
                  )
                })}
              </div>
            )}

            <p className="mt-3 text-xs text-muted-foreground">
              {selectedScopeIds.length} / {scopeNodes.length} phần đã chọn
            </p>
          </div>

          {/* Step 3: Exam settings */}
          <div className="rounded-xl border bg-card shadow-sm p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">3</div>
              <h2 className="text-base font-semibold text-foreground">Cài đặt đề thi</h2>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Số câu hỏi</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={totalQuestions}
                  onChange={(e) => setTotalQuestions(e.target.value)}
                  className="h-11"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Thời gian (phút)</Label>
                <Input
                  type="number"
                  min={5}
                  max={180}
                  value={timeLimit}
                  onChange={(e) => setTimeLimit(e.target.value)}
                  className="h-11"
                />
              </div>
            </div>
            <div className="mt-4 space-y-1.5">
              <Label>Yêu cầu của giáo viên <span className="text-xs text-muted-foreground font-normal">(tuỳ chọn)</span></Label>
              <Textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Ví dụ: tập trung vào các định luật bảo toàn, câu hỏi ngắn gọn..."
                className="min-h-20 resize-none"
              />
            </div>
          </div>

          {/* Summary + Generate */}
          <div className="rounded-xl border bg-primary/5 shadow-sm p-6 flex items-center justify-between gap-4">
            <div className="space-y-1">
              <p className="text-sm font-medium text-foreground">
                {selectedDocument?.title || "—"}
              </p>
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">{Number(totalQuestions) || 0} câu</Badge>
                <Badge variant="outline">{selectedScopeIds.length} phạm vi</Badge>
                <Badge variant="outline">{timeLimit || "?"} phút</Badge>
                <Badge variant="outline">PDF · MCQ · Tiếng Việt</Badge>
              </div>
            </div>
            <Button
              size="lg"
              className="shrink-0 h-11 px-6"
              disabled={
                !selectedDocument ||
                selectedScopeIds.length === 0 ||
                !Number(totalQuestions)
              }
              onClick={handleGenerate}
            >
              <Wand2 className="mr-2 h-4 w-4" />
              Sinh đề thi
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
