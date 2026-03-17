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
import { Slider } from "@/components/ui/slider";
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
  Brain,
  ChevronRight,
  FileText,
  GraduationCap,
  Hash,
  Layers,
  Loader2,
  ShieldCheck,
  Sliders,
  Sparkles,
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

const bloomLevels = [
  "remember",
  "understand",
  "apply",
  "analyze",
  "evaluate",
  "create",
] as const;

function flattenNodes(nodes: CurriculumNode[]): CurriculumNode[] {
  return nodes.flatMap((node) => [node, ...flattenNodes(node.children || [])]);
}

function buildScopePayload(node: CurriculumNode): ScopeUnitPayload {
  return {
    scope_id: node.id || `${node.section_type}:${node.chapter_number}:${node.section_order}:${node.title}`,
    scope_type: node.section_type || "topic",
    title: node.title,
    chapter_number: node.chapter_number || 0,
    page_from: node.page_from ?? null,
    page_to: node.page_to ?? null,
    tags: [
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
  const [prompt, setPrompt] = useState("");
  const [instructions, setInstructions] = useState("");
  const [questionType, setQuestionType] = useState("mixed");
  const [mcqCounts, setMcqCounts] = useState({ easy: 5, medium: 3, hard: 2 });
  const [essayCounts, setEssayCounts] = useState({ easy: 1, medium: 1, hard: 1 });
  const [timeLimit, setTimeLimit] = useState("45");
  const [examCount, setExamCount] = useState(1);
  const [gradualDifficulty, setGradualDifficulty] = useState(false);
  const [strictGrounding, setStrictGrounding] = useState(true);
  const [strictScope, setStrictScope] = useState(true);
  const [appliedQuestions, setAppliedQuestions] = useState(true);
  const [gradeLevelScope, setGradeLevelScope] = useState("undergraduate");
  const [creativityLevel, setCreativityLevel] = useState([30]);
  const [bloomLevel, setBloomLevel] = useState<string>("apply");
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

  const totalMcq = mcqCounts.easy + mcqCounts.medium + mcqCounts.hard;
  const totalEssay = essayCounts.easy + essayCounts.medium + essayCounts.hard;
  const totalQuestions =
    questionType === "mcq" ? totalMcq : questionType === "essay" ? totalEssay : totalMcq + totalEssay;

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

  const updateCount = (
    setter: React.Dispatch<React.SetStateAction<{ easy: number; medium: number; hard: number }>>,
    level: "easy" | "medium" | "hard",
    delta: number,
  ) => {
    setter((previous) => ({
      ...previous,
      [level]: Math.max(0, Math.min(50, previous[level] + delta)),
    }));
  };

  const handleGenerate = useCallback(() => {
    if (!selectedDocumentItem || totalQuestions === 0) return;

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
      prompt:
        prompt.trim() ||
        `Generate a ${questionType} exam grounded in ${selectedDocumentItem.title}${
          selectedScope.length ? ` using ${selectedScope.length} selected scope units` : ""
        }.`,
      exam_type: questionType,
      difficulty: "custom",
      question_distribution: {
        mcq: questionType === "essay" ? { easy: 0, medium: 0, hard: 0 } : mcqCounts,
        essay: questionType === "mcq" ? { easy: 0, medium: 0, hard: 0 } : essayCounts,
      },
      num_variants: examCount,
      gradually_increasing: gradualDifficulty,
      constraints: {
        strict_grounding: strictGrounding,
        allow_applied_questions: appliedQuestions,
        strict_scope: strictScope,
        grade_level_scope: gradeLevelScope || undefined,
        creativity_level: creativityLevel[0] / 100,
        bloom_levels: [bloomLevel],
      },
      instructions: instructions.trim() || undefined,
      time_limit_minutes: Number(timeLimit) || undefined,
      output_language: "vi",
      strict_scope: strictScope,
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
  }, [
    appliedQuestions,
    bloomLevel,
    creativityLevel,
    essayCounts,
    examCount,
    gradualDifficulty,
    instructions,
    mcqCounts,
    prompt,
    questionType,
    selectedDocumentItem,
    selectedScope,
    strictGrounding,
    strictScope,
    timeLimit,
    totalQuestions,
    gradeLevelScope,
  ]);

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
              if (!generatedExamId) {
                setIsGenerating(false);
              }
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
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">Blueprint-first exam generation</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Select a document, choose the exact curriculum scope, and generate an exam that stays grounded in the uploaded material.
          </p>
        </div>

        {readyDocuments.length === 0 ? (
          <Card className="rounded-2xl border-dashed shadow-sm">
            <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
              <AlertCircle className="h-8 w-8 text-muted-foreground" />
              <div>
                <p className="text-base font-semibold text-foreground">No ready documents found</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Upload and process at least one document before generating an exam.
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
                          <SelectValue placeholder="Choose a processed document" />
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
                    <MiniStat label="Course" value={selectedDocumentItem?.course_id ? courses.find((course) => course.id === selectedDocumentItem.course_id)?.course_name || "Assigned" : "Personal"} icon={GraduationCap} />
                    <MiniStat label="Pages/Slides" value={String(selectedDocumentItem?.total_pages_or_slides || 0)} icon={FileText} />
                    <MiniStat label="Chunks" value={String(selectedDocumentItem?.total_chunks || 0)} icon={Layers} />
                  </div>

                  <div className="rounded-xl border p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-foreground">Curriculum scope</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Leave everything unchecked to generate from the whole document, or select specific units for strict scope.
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
                    <Sliders className="h-4 w-4 text-primary" />
                    Exam Controls
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-5">
                  <div className="space-y-2">
                    <Label>Exam type</Label>
                    <Select value={questionType} onValueChange={setQuestionType}>
                      <SelectTrigger className="h-11">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="mixed">Mixed</SelectItem>
                        <SelectItem value="mcq">Multiple choice</SelectItem>
                        <SelectItem value="essay">Essay</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Time limit (minutes)</Label>
                    <Input value={timeLimit} onChange={(event) => setTimeLimit(event.target.value)} />
                  </div>

                  <div className="space-y-2">
                    <Label>Generation prompt</Label>
                    <Textarea
                      value={prompt}
                      onChange={(event) => setPrompt(event.target.value)}
                      placeholder="Example: Create a midterm focused on core concepts with more application questions in later sections."
                      className="min-h-24"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>Instructions shown in exam</Label>
                    <Textarea
                      value={instructions}
                      onChange={(event) => setInstructions(event.target.value)}
                      placeholder="Example: Answer all questions. Show your work for essay items."
                      className="min-h-20"
                    />
                  </div>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
              <Card className="rounded-2xl shadow-sm">
                <CardHeader className="pb-4">
                  <CardTitle className="flex items-center gap-2 text-base font-semibold">
                    <Hash className="h-4 w-4 text-primary" />
                    Question Mix
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-5">
                  {(questionType === "mcq" || questionType === "mixed") && (
                    <DistributionEditor
                      title="Multiple choice"
                      counts={mcqCounts}
                      onChange={(level, delta) => updateCount(setMcqCounts, level, delta)}
                    />
                  )}
                  {(questionType === "essay" || questionType === "mixed") && (
                    <DistributionEditor
                      title="Essay"
                      counts={essayCounts}
                      onChange={(level, delta) => updateCount(setEssayCounts, level, delta)}
                    />
                  )}
                </CardContent>
              </Card>

              <Card className="rounded-2xl shadow-sm">
                <CardHeader className="pb-4">
                  <CardTitle className="flex items-center gap-2 text-base font-semibold">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                    Constraints
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-5">
                  <ToggleRow
                    label="Strict grounding"
                    description="Force the generator to stay close to retrieved evidence."
                    checked={strictGrounding}
                    onChange={setStrictGrounding}
                  />
                  <ToggleRow
                    label="Strict scope"
                    description="Do not step outside the selected curriculum units."
                    checked={strictScope}
                    onChange={setStrictScope}
                  />
                  <ToggleRow
                    label="Allow applied questions"
                    description="Permit reasoning and application while staying grounded."
                    checked={appliedQuestions}
                    onChange={setAppliedQuestions}
                  />
                  <ToggleRow
                    label="Gradually increase difficulty"
                    description="Arrange items from easier to harder over the exam."
                    checked={gradualDifficulty}
                    onChange={setGradualDifficulty}
                  />

                  <div className="space-y-2">
                    <Label>Target Bloom level</Label>
                    <Select value={bloomLevel} onValueChange={setBloomLevel}>
                      <SelectTrigger className="h-11">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {bloomLevels.map((level) => (
                          <SelectItem key={level} value={level}>
                            {level}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Academic level</Label>
                    <Input
                      value={gradeLevelScope}
                      onChange={(event) => setGradeLevelScope(event.target.value)}
                      placeholder="undergraduate"
                    />
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label>Creativity level</Label>
                      <span className="text-xs text-muted-foreground">{creativityLevel[0]}%</span>
                    </div>
                    <Slider value={creativityLevel} onValueChange={setCreativityLevel} max={100} step={5} />
                  </div>

                  <div className="space-y-2">
                    <Label>Variants</Label>
                    <Input
                      type="number"
                      min={1}
                      max={10}
                      value={examCount}
                      onChange={(event) => setExamCount(Number(event.target.value) || 1)}
                    />
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card className="rounded-2xl shadow-sm">
              <CardContent className="flex flex-col gap-4 p-5 md:flex-row md:items-center md:justify-between">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{totalQuestions} questions</Badge>
                    <Badge variant="outline">
                      {selectedScope.length > 0 ? `${selectedScope.length} scope units selected` : "Whole document scope"}
                    </Badge>
                    <Badge variant="outline">{selectedDocumentItem?.title || "No document"}</Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    The generator will create an exam blueprint first, retrieve only relevant evidence, and then generate questions per blueprint cell.
                  </p>
                </div>
                <Button size="lg" className="h-11 md:min-w-56" disabled={!selectedDocumentItem || totalQuestions === 0} onClick={handleGenerate}>
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

function DistributionEditor({
  title,
  counts,
  onChange,
}: {
  title: string;
  counts: { easy: number; medium: number; hard: number };
  onChange: (level: "easy" | "medium" | "hard", delta: number) => void;
}) {
  return (
    <div className="rounded-xl border p-4">
      <p className="text-sm font-medium text-foreground">{title}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {(["easy", "medium", "hard"] as const).map((level) => (
          <div key={level} className="rounded-lg bg-muted/30 p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">{level}</span>
              <span className="text-lg font-semibold text-foreground">{counts[level]}</span>
            </div>
            <div className="mt-3 flex gap-2">
              <Button variant="outline" size="sm" className="flex-1" onClick={() => onChange(level, -1)}>
                -
              </Button>
              <Button variant="outline" size="sm" className="flex-1" onClick={() => onChange(level, 1)}>
                +
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-xl border p-4">
      <div>
        <p className="text-sm font-medium text-foreground">{label}</p>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </div>
      <Checkbox checked={checked} onCheckedChange={(value) => onChange(value === true)} />
    </label>
  );
}
