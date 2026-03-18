"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { DashboardHeader } from "@/components/dashboard-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  BookOpen,
  Calendar,
  CloudUpload,
  Eye,
  FileText,
  FolderOpen,
  GraduationCap,
  Layers,
  Loader2,
  MoreVertical,
  Plus,
  Shield,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  courses as coursesApi,
  documents as documentsApi,
  isReadyStatus,
  textbooks as textbooksApi,
  type Course,
  type CurriculumNode,
  type TextbookListItem,
} from "@/lib/api";

function formatFileSize(bytes: number) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} KB`;
  return `${bytes} B`;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function countTreeNodes(nodes: CurriculumNode[]): number {
  return nodes.reduce((total, node) => total + 1 + countTreeNodes(node.children || []), 0);
}

function flattenTitles(nodes: CurriculumNode[], depth = 0): string[] {
  return nodes.flatMap((node) => [
    `${"  ".repeat(depth)}${node.title}`,
    ...flattenTitles(node.children || [], depth + 1),
  ]);
}

type CollectionFilter = "all" | "unassigned" | `course:${string}`;

export default function TextbooksPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [documents, setDocuments] = useState<TextbookListItem[]>([]);
  const [selectedCollection, setSelectedCollection] = useState<CollectionFilter>("all");
  const [loading, setLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [detailDocument, setDetailDocument] = useState<TextbookListItem | null>(null);
  const [detailCurriculum, setDetailCurriculum] = useState<CurriculumNode[]>([]);
  const [loadingCurriculum, setLoadingCurriculum] = useState(false);
  const [error, setError] = useState("");
  const [creatingCourse, setCreatingCourse] = useState(false);
  const [courseName, setCourseName] = useState("");
  const [courseSubject, setCourseSubject] = useState("Vật lý");
  const [courseLevel, setCourseLevel] = useState("");
  const [courseDescription, setCourseDescription] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadData = useCallback(async () => {
    try {
      const [courseList, documentList] = await Promise.all([
        coursesApi.list(),
        textbooksApi.list(),
      ]);
      setCourses(courseList);
      setDocuments(documentList);
    } catch (loadError: unknown) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load courses and documents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    if (selectedCollection !== "all") return;
    if (courses.length > 0) {
      setSelectedCollection(`course:${courses[0].id}`);
      return;
    }
    if (documents.some((document) => !document.course_id)) {
      setSelectedCollection("unassigned");
    }
  }, [courses, documents, selectedCollection]);

  const selectedCourseId = selectedCollection.startsWith("course:")
    ? selectedCollection.slice("course:".length)
    : null;

  const selectedCourse = courses.find((course) => course.id === selectedCourseId) || null;

  const filteredDocuments = useMemo(() => {
    if (selectedCollection === "all") return documents;
    if (selectedCollection === "unassigned") {
      return documents.filter((document) => !document.course_id);
    }
    return documents.filter((document) => document.course_id === selectedCourseId);
  }, [documents, selectedCollection, selectedCourseId]);

  const processedCount = filteredDocuments.filter((document) => isReadyStatus(document.status)).length;

  const handleCreateCourse = useCallback(async () => {
    if (!courseName.trim() || !courseSubject.trim()) {
      setError("Course name and subject are required");
      return;
    }

    setCreatingCourse(true);
    setError("");
    try {
      const created = await coursesApi.create({
        course_name: courseName.trim(),
        subject: courseSubject.trim(),
        academic_level: courseLevel.trim() || undefined,
        description: courseDescription.trim() || undefined,
      });
      setCourses((previous) => [created, ...previous]);
      setSelectedCollection(`course:${created.id}`);
      setCourseName("");
      setCourseSubject("");
      setCourseLevel("");
      setCourseDescription("");
    } catch (createError: unknown) {
      setError(createError instanceof Error ? createError.message : "Failed to create course");
    } finally {
      setCreatingCourse(false);
    }
  }, [courseDescription, courseLevel, courseName, courseSubject]);

  const handleUpload = useCallback(async (file: File) => {
    setIsUploading(true);
    setUploadProgress(10);
    setError("");

    const interval = setInterval(() => {
      setUploadProgress((current) => Math.min(current + 6, 90));
    }, 250);

    try {
      const title = file.name.replace(/\.[^.]+$/, "");
      if (selectedCourseId) {
        await documentsApi.upload(selectedCourseId, title, file, "vi");
      } else {
        await textbooksApi.upload(title, file);
      }
      setUploadProgress(100);
      await loadData();
    } catch (uploadError: unknown) {
      setError(uploadError instanceof Error ? uploadError.message : "Upload failed");
    } finally {
      clearInterval(interval);
      setIsUploading(false);
      setUploadProgress(0);
    }
  }, [loadData, selectedCourseId]);

  const handleFileSelect = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    void handleUpload(files[0]);
  }, [handleUpload]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await textbooksApi.delete(id);
      setDocuments((previous) => previous.filter((document) => document.id !== id));
      if (detailDocument?.id === id) {
        setDetailDocument(null);
        setDetailCurriculum([]);
      }
    } catch (deleteError: unknown) {
      setError(deleteError instanceof Error ? deleteError.message : "Delete failed");
    }
  }, [detailDocument]);

  const openDetails = useCallback(async (document: TextbookListItem) => {
    setDetailDocument(document);
    setDetailCurriculum([]);
    setLoadingCurriculum(true);
    try {
      const tree = await documentsApi.getCurriculumTree(document.id);
      setDetailCurriculum(tree);
    } catch {
      setDetailCurriculum([]);
    } finally {
      setLoadingCurriculum(false);
    }
  }, []);

  return (
    <>
      <DashboardHeader title="Courses & Documents" />
      <div className="flex flex-1 flex-col gap-6 p-6">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Course and Document Library
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Organize course spaces, upload teaching materials, and prepare structured scope for exam generation.
            </p>
          </div>
          <Badge variant="secondary" className="w-fit gap-1.5">
            <Shield className="h-3 w-3" />
            Grounded document workflow
          </Badge>
        </div>

        {error && (
          <div className="flex items-center justify-between rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">
            <span>{error}</span>
            <button onClick={() => setError("")} aria-label="Dismiss error">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={(event) => handleFileSelect(event.target.files)}
        />

        <div className="grid gap-6 xl:grid-cols-[1.15fr_1.85fr]">
          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="pb-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <GraduationCap className="h-4 w-4 text-primary" />
                Create Course
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="course-name">Course name</Label>
                  <Input
                    id="course-name"
                    placeholder="Physics 101"
                    value={courseName}
                    onChange={(event) => setCourseName(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="course-subject">Subject</Label>
                  <Input
                    id="course-subject"
                    placeholder="Vật lý"
                    value={courseSubject}
                    onChange={(event) => setCourseSubject(event.target.value)}
                    readOnly
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="course-level">Academic level</Label>
                  <Input
                    id="course-level"
                    placeholder="Undergraduate"
                    value={courseLevel}
                    onChange={(event) => setCourseLevel(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="course-description">Description</Label>
                  <Input
                    id="course-description"
                    placeholder="Semester 1 mechanics course"
                    value={courseDescription}
                    onChange={(event) => setCourseDescription(event.target.value)}
                  />
                </div>
              </div>

              <Button onClick={() => void handleCreateCourse()} disabled={creatingCourse}>
                {creatingCourse ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="mr-2 h-4 w-4" />
                )}
                {creatingCourse ? "Creating..." : "Create course"}
              </Button>
            </CardContent>
          </Card>

          <Card className="rounded-2xl shadow-sm">
            <CardHeader className="pb-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <FolderOpen className="h-4 w-4 text-primary" />
                Collections
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-wrap gap-2">
                <FilterChip
                  active={selectedCollection === "all"}
                  label={`All documents (${documents.length})`}
                  onClick={() => setSelectedCollection("all")}
                />
                {documents.some((document) => !document.course_id) && (
                  <FilterChip
                    active={selectedCollection === "unassigned"}
                    label={`Personal library (${documents.filter((document) => !document.course_id).length})`}
                    onClick={() => setSelectedCollection("unassigned")}
                  />
                )}
                {courses.map((course) => (
                  <FilterChip
                    key={course.id}
                    active={selectedCollection === `course:${course.id}`}
                    label={`${course.course_name} (${course.document_count})`}
                    onClick={() => setSelectedCollection(`course:${course.id}`)}
                  />
                ))}
              </div>

              <div
                className={`rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${
                  isDragging ? "border-primary bg-primary/5" : "border-border hover:border-primary/40 hover:bg-muted/30"
                }`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setIsDragging(true);
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setIsDragging(false);
                  handleFileSelect(event.dataTransfer.files);
                }}
              >
                {isUploading ? (
                  <div className="flex flex-col items-center gap-4">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10">
                      <CloudUpload className="h-6 w-6 animate-pulse text-primary" />
                    </div>
                    <div className="w-full max-w-xs">
                      <p className="mb-2 text-sm font-medium text-foreground">
                        Uploading and structuring document...
                      </p>
                      <div className="h-2 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary transition-all"
                          style={{ width: `${uploadProgress}%` }}
                        />
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">{uploadProgress}% complete</p>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-4">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted">
                      <Upload className="h-6 w-6 text-muted-foreground" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {selectedCourse
                          ? `Upload into ${selectedCourse.course_name}`
                          : "Upload into your personal library"}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Supports PDF only. Structured curriculum and retrieval evidence will be built from this source.
                      </p>
                    </div>
                    <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
                      <Upload className="mr-2 h-3.5 w-3.5" />
                      Browse files
                    </Button>
                  </div>
                )}
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <SummaryCard label="Courses" value={courses.length.toString()} icon={GraduationCap} />
                <SummaryCard label="Documents in view" value={filteredDocuments.length.toString()} icon={BookOpen} />
                <SummaryCard label="Ready for generation" value={processedCount.toString()} icon={Sparkles} />
              </div>
            </CardContent>
          </Card>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : filteredDocuments.length === 0 ? (
          <Card className="rounded-2xl border-dashed shadow-sm">
            <CardContent className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted">
                <BookOpen className="h-7 w-7 text-muted-foreground" />
              </div>
              <div>
                <p className="text-base font-semibold text-foreground">No documents in this collection</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Create a course or upload your first document to start building curriculum-aware exams.
                </p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filteredDocuments.map((document) => (
              <DocumentCard
                key={document.id}
                document={document}
                course={courses.find((course) => course.id === document.course_id) || null}
                onDelete={handleDelete}
                onViewDetails={openDetails}
              />
            ))}
          </div>
        )}

        <Dialog open={!!detailDocument} onOpenChange={() => setDetailDocument(null)}>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{detailDocument?.title}</DialogTitle>
              <DialogDescription>
                Review processing status, curriculum structure, and generation readiness for this document.
              </DialogDescription>
            </DialogHeader>
            {detailDocument && (
              <div className="flex flex-col gap-5 pt-2">
                <div className="grid gap-3 sm:grid-cols-2">
                  <DetailItem label="Upload date" value={formatDate(detailDocument.created_at)} icon={<Calendar className="h-4 w-4" />} />
                  <DetailItem label="Status" value={detailDocument.status} icon={<Shield className="h-4 w-4" />} />
                  <DetailItem label="File type" value={detailDocument.file_type.toUpperCase()} icon={<FileText className="h-4 w-4" />} />
                  <DetailItem label="File size" value={formatFileSize(detailDocument.file_size)} icon={<CloudUpload className="h-4 w-4" />} />
                </div>

                <div className="rounded-xl border bg-muted/30 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-foreground">Curriculum tree</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        The extracted tree is what the generator uses for strict scope selection.
                      </p>
                    </div>
                    {isReadyStatus(detailDocument.status) && (
                      <Button asChild size="sm">
                        <Link href="/dashboard/generate">
                          <Sparkles className="mr-2 h-4 w-4" />
                          Generate exam
                        </Link>
                      </Button>
                    )}
                  </div>

                  <div className="mt-4 rounded-lg border bg-background p-3">
                    {loadingCurriculum ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading curriculum tree...
                      </div>
                    ) : detailCurriculum.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        No curriculum tree is available yet. The document may still be processing or it was uploaded through the legacy flow.
                      </p>
                    ) : (
                      <div className="space-y-3">
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Layers className="h-3.5 w-3.5" />
                          {countTreeNodes(detailCurriculum)} scope nodes extracted
                        </div>
                        <div className="max-h-64 overflow-y-auto rounded-lg bg-muted/30 p-3">
                          {flattenTitles(detailCurriculum).map((title) => (
                            <p key={title} className="py-0.5 text-sm text-foreground">
                              {title}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </DialogContent>
        </Dialog>
      </div>
    </>
  );
}

function FilterChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-background text-foreground hover:border-primary/40 hover:bg-muted"
      }`}
    >
      {label}
    </button>
  );
}

function SummaryCard({
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
      <p className="mt-2 text-2xl font-semibold text-foreground">{value}</p>
    </div>
  );
}

function DocumentCard({
  document,
  course,
  onDelete,
  onViewDetails,
}: {
  document: TextbookListItem;
  course: Course | null;
  onDelete: (id: string) => void;
  onViewDetails: (document: TextbookListItem) => void;
}) {
  const ready = isReadyStatus(document.status);

  return (
    <Card className="group rounded-2xl shadow-sm transition-shadow hover:shadow-md">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
            <BookOpen className="h-5 w-5 text-primary" />
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100">
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem onClick={() => onViewDetails(document)}>
                <Eye className="mr-2 h-4 w-4" />
                View details
              </DropdownMenuItem>
              {ready && (
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
                onClick={() => onDelete(document.id)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="mt-4">
          <h3 className="line-clamp-2 text-sm font-semibold text-foreground">{document.title}</h3>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {document.file_type.toUpperCase()} · {formatFileSize(document.file_size)}
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Badge variant={ready ? "secondary" : "outline"} className="capitalize">
            {document.status}
          </Badge>
          {course ? (
            <Badge variant="outline">{course.course_name}</Badge>
          ) : (
            <Badge variant="outline">Personal library</Badge>
          )}
        </div>

        <div className="mt-4 grid gap-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <Calendar className="h-3.5 w-3.5" />
            {formatDate(document.created_at)}
          </div>
          <div className="flex items-center gap-2">
            <Layers className="h-3.5 w-3.5" />
            {document.chapter_count ? `${document.chapter_count} chapters detected` : `${document.total_chunks} chunks indexed`}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function DetailItem({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border bg-muted/20 p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {icon}
        {label}
      </div>
      <p className="mt-2 text-sm font-medium text-foreground">{value}</p>
    </div>
  );
}
