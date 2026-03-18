"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DashboardHeader } from "@/components/dashboard-header";
import { GenerationStepper } from "@/components/generation-stepper";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertCircle,
  BookOpen,
  ChevronRight,
  FileText,
  GraduationCap,
  Layers,
  Loader2,
  ShieldCheck,
  Wand2,
} from "lucide-react";
import {
  courses as coursesApi,
  documents as documentsApi,
  generation as generationApi,
  isReadyStatus,
  textbooks as textbooksApi,
  type Course,
  type CurriculumNode,
  type ExamGenerationRequest,
  type GenerationStep,
  type ScopeUnitPayload,
  type TextbookListItem,
} from "@/lib/api";

function flattenNodes(nodes: CurriculumNode[]): CurriculumNode[] {
  return nodes.flatMap((node) => [node, ...flattenNodes(node.children || [])]);
}

function buildScopePayload(node: CurriculumNode): ScopeUnitPayload {
  const scopeId =
    node.id || `${node.section_type}:${node.chapter_number}:${node.section_order}:${node.title}`;
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
  };
}

export default function GenerateExamPage() {
  const router = useRouter();
  const [courses, setCourses] = useState<Course[]>([]);
  const [documents, setDocuments] = useState<TextbookListItem[]>([]);
  const [loadingSources, setLoadingSources] = useState(true);
  const [selectedCourse, setSelectedCourse] = useState<string>("all");
  const [selectedDocument, setSelectedDocument] = useState<string>("");
  const [curriculumTree, setCurriculumTree] = useState<CurriculumNode[]>([]);
  const [loadingTree, setLoadingTree] = useState(false);
  const [selectedScopeIds, setSelectedScopeIds] = useState<string[]>([]);
  const [totalQuestions, setTotalQuestions] = useState("10");
  const [timeLimit, setTimeLimit] = useState("45");
  const [prompt, setPrompt] = useState("");
  const [instructions, setInstructions] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationSteps, setGenerationSteps] = useState<GenerationStep[]>([]);
  const [generationError, setGenerationError] = useState("");
  const [generatedExamId, setGeneratedExamId] = useState<string | null>(null);

  const loadSources = useCallback(async () => {
    try {
      const [courseList, documentList] = await Promise.all([
        coursesApi.list(),
        textbooksApi.list(),
      ]);
      setCourses(courseList);
      setDocuments(documentList);
    } finally {
      setLoadingSources(false);
    }
  }, []);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  const readyDocuments = useMemo(
    () => documents.filter((document) => isReadyStatus(document.status)),
    [documents],
  );

  const filteredDocuments = useMemo(() => {
    if (selectedCourse === "all") return readyDocuments;
    if (selectedCourse === "unassigned") {
      return readyDocuments.filter((document) => !document.course_id);
    }
    return readyDocuments.filter((document) => document.course_id === selectedCourse);
  }, [readyDocuments, selectedCourse]);

  useEffect(() => {
    if (!selectedDocument && filteredDocuments.length > 0) {
      setSelectedDocument(filteredDocuments[0].id);
      return;
    }
    if (selectedDocument && !filteredDocuments.some((document) => document.id === selectedDocument)) {
      setSelectedDocument(filteredDocuments[0]?.id || "");
    }
  }, [filteredDocuments, selectedDocument]);

  useEffect(() => {
    if (!selectedDocument) {
      setCurriculumTree([]);
      setSelectedScopeIds([]);
      return;
    }

    let cancelled = false;
    setLoadingTree(true);
    setSelectedScopeIds([]);
    void documentsApi
      .getCurriculumTree(selectedDocument)
      .then((tree) => {
        if (!cancelled) setCurriculumTree(tree);
      })
      .catch(() => {
        if (!cancelled) setCurriculumTree([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingTree(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedDocument]);

  const scopeNodes = useMemo(() => flattenNodes(curriculumTree), [curriculumTree]);
  const scopeNodeMap = useMemo(
    () => new Map(scopeNodes.map((node) => [buildScopePayload(node).scope_id || "", node])),
    [scopeNodes],
  );

  const selectedScope = useMemo(
    () =>
      selectedScopeIds
        .map((scopeId) => {
          const node = scopeNodeMap.get(scopeId);
          return node ? buildScopePayload(node) : null;
        })
        .filter((value): value is ScopeUnitPayload => value !== null),
    [scopeNodeMap, selectedScopeIds],
  );

  const selectedDocumentItem = readyDocuments.find((document) => document.id === selectedDocument) || null;
  const parsedQuestionCount = Number(totalQuestions) || 0;

  const toggleScope = useCallback((scopeId: string, checked: boolean) => {
    setSelectedScopeIds((current) => {
      if (checked) return Array.from(new Set([...current, scopeId]));
      return current.filter((id) => id !== scopeId);
    });
  }, []);

  const selectAllScope = useCallback(() => {
    setSelectedScopeIds(scopeNodes.map((node) => buildScopePayload(node).scope_id || "").filter(Boolean));
  }, [scopeNodes]);

  const clearScope = useCallback(() => {
    setSelectedScopeIds([]);
  }, []);

  const handleGenerate = useCallback(() => {
    if (!selectedDocumentItem || parsedQuestionCount <= 0) return;

    setIsGenerating(true);
    setGenerationError("");
    setGeneratedExamId(null);
    setGenerationSteps([]);

    const chapters = Array.from(
      new Set(selectedScope.filter((item) => item.chapter_number > 0).map((item) => item.chapter_number)),
    );

    const requestPayload: ExamGenerationRequest = {
      course_id: selectedDocumentItem.course_id || undefined,
      document_id: selectedDocumentItem.id,
      chapters,
      scope: selectedScope,
      prompt: prompt.trim(),
      instructions: instructions.trim() || undefined,
      total_questions: parsedQuestionCount,
      question_type: "mcq_single_answer",
      exam_type: "mcq",
      num_variants: 1,
      gradually_increasing: false,
      constraints: {
        strict_grounding: true,
        allow_applied_questions: false,
        strict_scope: true,
        creativity_level: 0,
        bloom_levels: ["remember", "understand", "apply", "analyze"],
        max_concurrency: 1,
      },
      time_limit_minutes: Number(timeLimit) || undefined,
      output_language: "vi",
      strict_scope: true,
      formatting_preferences: {
        subject: "physics",
        language: "vi",
      },
    };

    generationApi.generateStream(
      requestPayload,
      (step) =>
        setGenerationSteps((current) => {
          const existingIndex = current.findIndex((item) => item.step === step.step);
          if (existingIndex >= 0) {
            const next = [...current];
            next[existingIndex] = step;
            return next;
          }
          return [...current, step];
        }),
      (exam) => setGeneratedExamId(exam.id),
      (error) => {
        setGenerationError(error);
        setIsGenerating(false);
      },
    );
  }, [instructions, parsedQuestionCount, prompt, selectedDocumentItem, selectedScope, timeLimit]);

  useEffect(() => {
    if (!generatedExamId) return;
    router.push(`/dashboard/exams/${generatedExamId}`);
  }, [generatedExamId, router]);

  if (isGenerating) {
    return (
      <>
        <DashboardHeader title="Generate Exam" />
        {generationError ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="max-w-md text-center">
              <p className="mb-2 font-medium text-destructive">Generation failed</p>
              <p className="mb-4 text-sm text-muted-foreground">{generationError}</p>
              <Button
                onClick={() => {
                  setIsGenerating(false);
                  setGenerationError("");
                }}
              >
                Try again
              </Button>
            </div>
          </div>
        ) : (
          <GenerationStepper
            steps={generationSteps}
            onComplete={() => {
              if (!generatedExamId) setIsGenerating(false);
            }}
          />
        )}
      </>
    );
  }

  if (loadingSources) {
    return (
      <>
        <DashboardHeader title="Generate Exam" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </>
    );
  }

  return (
    <>
      <DashboardHeader title="Generate Exam" />
      <div className="flex flex-1 flex-col gap-6 p-6 max-w-6xl">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">Grounded exam generation</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Generate one Physics exam in Vietnamese from PDF content only. The system will parse your request into an exam spec, build a blueprint, retrieve evidence inside the selected scope, and save a reviewable version.
          </p>
        </div>

        {readyDocuments.length === 0 ? (
          <Card className="rounded-2xl border-dashed shadow-sm">
            <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
              <AlertCircle className="h-8 w-8 text-muted-foreground" />
              <div>
                <p className="text-base font-semibold text-foreground">No ready PDF documents found</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Upload and process at least one PDF before generating an exam.
                </p>
              </div>
              <Button asChild>
                <Link href="/dashboard/textbooks">
                  <ChevronRight className="mr-2 h-4 w-4" />
                  Go to document library
                </Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <>
            <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
              <Card className="rounded-2xl shadow-sm">
                <CardHeader className="pb-4">
                  <CardTitle className="flex items-center gap-2 text-base font-semibold">
                    <BookOpen className="h-4 w-4 text-primary" />
                    Scope Selection
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-5">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label>Select course</Label>
                      <Select value={selectedCourse} onValueChange={setSelectedCourse}>
                        <SelectTrigger className="h-11">
                          <SelectValue placeholder="Filter by course" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">All ready documents</SelectItem>
                          {documents.some((document) => isReadyStatus(document.status) && !document.course_id) && (
                            <SelectItem value="unassigned">Personal library</SelectItem>
                          )}
                          {courses.map((course) => (
                            <SelectItem key={course.id} value={course.id}>
                              {course.course_name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-2">
                      <Label>Select document</Label>
                      <Select value={selectedDocument} onValueChange={setSelectedDocument}>
                        <SelectTrigger className="h-11">
                          <SelectValue placeholder="Choose a processed PDF" />
                        </SelectTrigger>
                        <SelectContent>
                          {filteredDocuments.map((document) => (
                            <SelectItem key={document.id} value={document.id}>
                              {document.title}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-3">
                    <MiniStat
                      label="Course"
                      value={
                        selectedDocumentItem?.course_id
                          ? courses.find((course) => course.id === selectedDocumentItem.course_id)?.course_name || "Assigned"
                          : "Personal"
                      }
                      icon={GraduationCap}
                    />
                    <MiniStat label="Pages" value={String(selectedDocumentItem?.total_pages_or_slides || 0)} icon={FileText} />
                    <MiniStat label="Chunks" value={String(selectedDocumentItem?.total_chunks || 0)} icon={Layers} />
                  </div>

                  <div className="rounded-xl border p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-foreground">Curriculum scope</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Select chapter, lesson, topic, or subtopic. Retrieval will stay inside these sections only.
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" size="sm" onClick={selectAllScope} disabled={scopeNodes.length === 0}>
                          Select all
                        </Button>
                        <Button variant="ghost" size="sm" onClick={clearScope}>
                          Clear
                        </Button>
                      </div>
                    </div>

                    <div className="mt-4 rounded-xl bg-muted/25 p-4">
                      {loadingTree ? (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Loading curriculum tree...
                        </div>
                      ) : curriculumTree.length === 0 ? (
                        <p className="text-sm text-muted-foreground">
                          No structured tree is available for this document yet. The generator can still use the whole document.
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {curriculumTree.map((node) => (
                            <ScopeTreeNode
                              key={buildScopePayload(node).scope_id}
                              node={node}
                              selectedScopeIds={selectedScopeIds}
                              onToggle={toggleScope}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="rounded-2xl shadow-sm">
                <CardHeader className="pb-4">
                  <CardTitle className="flex items-center gap-2 text-base font-semibold">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                    MVP Controls
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-5">
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary">Vật lý</Badge>
                    <Badge variant="outline">Tiếng Việt</Badge>
                    <Badge variant="outline">PDF only</Badge>
                    <Badge variant="outline">MCQ single-answer</Badge>
                    <Badge variant="outline">Strict scope</Badge>
                  </div>

                  <div className="space-y-2">
                    <Label>Total questions</Label>
                    <Input
                      type="number"
                      min={1}
                      max={100}
                      value={totalQuestions}
                      onChange={(event) => setTotalQuestions(event.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>Time limit (minutes)</Label>
                    <Input value={timeLimit} onChange={(event) => setTimeLimit(event.target.value)} />
                  </div>

                  <div className="space-y-2">
                    <Label>Teacher request</Label>
                    <Textarea
                      value={prompt}
                      onChange={(event) => setPrompt(event.target.value)}
                      placeholder="Example: Tập trung nhiều hơn vào phần định luật bảo toàn và tránh câu quá dài."
                      className="min-h-24"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>Instructions shown in exam</Label>
                    <Textarea
                      value={instructions}
                      onChange={(event) => setInstructions(event.target.value)}
                      placeholder="Example: Chọn 1 đáp án đúng cho mỗi câu."
                      className="min-h-20"
                    />
                  </div>

                  <div className="rounded-xl border bg-muted/20 p-4 text-sm text-muted-foreground">
                    The generator will always parse your request into an exam spec first, then build a section-level blueprint before any question generation starts.
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card className="rounded-2xl shadow-sm">
              <CardContent className="flex flex-col gap-4 p-5 md:flex-row md:items-center md:justify-between">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{parsedQuestionCount} questions</Badge>
                    <Badge variant="outline">
                      {selectedScope.length > 0 ? `${selectedScope.length} scope units selected` : "Whole document scope"}
                    </Badge>
                    <Badge variant="outline">{selectedDocumentItem?.title || "No document"}</Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Each question will include source evidence linked to the selected document and scoped sections before it reaches review.
                  </p>
                </div>
                <Button
                  size="lg"
                  className="h-11 md:min-w-56"
                  disabled={!selectedDocumentItem || parsedQuestionCount <= 0}
                  onClick={handleGenerate}
                >
                  <Wand2 className="mr-2 h-4 w-4" />
                  Generate exam
                </Button>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </>
  );
}

function MiniStat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof BookOpen;
}) {
  return (
    <div className="rounded-xl border bg-muted/20 p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <p className="mt-2 text-lg font-semibold text-foreground">{value}</p>
    </div>
  );
}

function ScopeTreeNode({
  node,
  selectedScopeIds,
  onToggle,
  depth = 0,
}: {
  node: CurriculumNode;
  selectedScopeIds: string[];
  onToggle: (scopeId: string, checked: boolean) => void;
  depth?: number;
}) {
  const scopeId = buildScopePayload(node).scope_id || "";
  const checked = selectedScopeIds.includes(scopeId);

  return (
    <div>
      <div
        className="flex items-start gap-3 rounded-xl border bg-background px-3 py-3"
        style={{ marginLeft: `${depth * 14}px` }}
      >
        <Checkbox checked={checked} onCheckedChange={(value) => onToggle(scopeId, value === true)} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-foreground">{node.title}</p>
            <Badge variant="outline" className="capitalize">
              {node.section_type || "topic"}
            </Badge>
            {node.chapter_number > 0 && <Badge variant="secondary">Chapter {node.chapter_number}</Badge>}
          </div>
          {(node.summary || node.page_from || node.page_to) && (
            <p className="mt-1 text-xs text-muted-foreground">
              {node.summary || "Scoped curriculum unit"}
              {node.page_from || node.page_to ? ` · pages ${node.page_from || "?"}-${node.page_to || "?"}` : ""}
            </p>
          )}
        </div>
      </div>
      {(node.children || []).length > 0 && (
        <div className="mt-2 space-y-2">
          {node.children.map((child) => (
            <ScopeTreeNode
              key={buildScopePayload(child).scope_id}
              node={child}
              selectedScopeIds={selectedScopeIds}
              onToggle={onToggle}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}
