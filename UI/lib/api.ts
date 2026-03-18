const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    let message: string;
    if (Array.isArray(body.detail)) {
      message = body.detail
        .map((err: { msg?: string; loc?: string[] }) => {
          const field = err.loc?.slice(-1)[0] || "field";
          const msg = err.msg?.replace(/^Value error, /, "") || "invalid";
          return `${field}: ${msg}`;
        })
        .join("; ");
    } else {
      message = body.detail || res.statusText;
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function isReadyStatus(status: string): boolean {
  return ["processed", "structured", "indexed"].includes(status.toLowerCase());
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  department?: string;
  university?: string;
  role?: string;
  is_email_verified?: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface CourseMembership {
  user_id: string;
  role: string;
  full_name?: string;
  email?: string;
}

export interface Course {
  id: string;
  owner_user_id: string;
  course_name: string;
  subject: string;
  academic_level?: string;
  description?: string;
  created_at: string;
  updated_at?: string;
  membership_count: number;
  document_count: number;
  memberships: CourseMembership[];
}

export interface CourseCreateRequest {
  course_name: string;
  subject: string;
  academic_level?: string;
  description?: string;
}

export interface Chapter {
  id: string;
  chapter_number: number;
  title: string;
  start_page?: number;
  end_page?: number;
  summary?: string;
  key_concepts?: string[];
}

export interface CurriculumNode {
  id?: string | null;
  title: string;
  section_type: string;
  section_order: number;
  chapter_number: number;
  page_from?: number | null;
  page_to?: number | null;
  scope_label?: string | null;
  summary?: string | null;
  metadata?: Record<string, unknown> | null;
  children: CurriculumNode[];
}

export interface DocumentStatus {
  id: string;
  course_id?: string | null;
  status: string;
  parse_error_message?: string | null;
  total_pages_or_slides: number;
  total_chunks: number;
  updated_at?: string | null;
}

export interface Document {
  id: string;
  course_id?: string | null;
  title: string;
  file_name: string;
  file_type: string;
  file_size: number;
  file_hash?: string | null;
  file_storage_url?: string | null;
  language?: string | null;
  status: string;
  version: number;
  total_pages_or_slides: number;
  total_chunks: number;
  created_at: string;
  updated_at?: string | null;
  curriculum_tree: CurriculumNode[];
}

export interface DocumentListItem {
  id: string;
  course_id?: string | null;
  title: string;
  file_name: string;
  file_type: string;
  file_size: number;
  status: string;
  version: number;
  total_pages_or_slides: number;
  total_chunks: number;
  chapter_count?: number;
  created_at: string;
  updated_at?: string | null;
}

export type TextbookListItem = DocumentListItem;

export interface Textbook extends Document {
  chapters: Chapter[];
}

export interface MCQOption {
  label: string;
  text: string;
}

export interface QualityScoreDetail {
  slot_number: number;
  answerability: number;
  grounding: number;
  clarity: number;
  ambiguity_risk: number;
  distractor_quality: number;
  bloom_alignment: number;
  difficulty_realism: number;
  overall: number;
  passed: boolean;
  recommendation: "keep" | "review" | "regenerate";
  notes: string[];
}

export interface ChunkTrace {
  chunk_index: number;
  chunk_id: string;
  stem_overlap: number;
  answer_overlap: number;
  is_best_for_answer: boolean;
}

export interface DistractorDetail {
  label: string;
  text: string;
  source_overlap: number;
  phrase_match: number;
  exceeds_correct: boolean;
}

export interface GroundingReportDetail {
  slot_number: number;
  lexical_overlap: number;
  ngram_overlap: number;
  phrase_overlap: number;
  answer_support_score: number;
  answer_supported: boolean;
  distractors_valid: boolean;
  verbatim_ratio: number;
  overall_score: number;
  grounding_pass: boolean;
  source_traceability: ChunkTrace[];
  distractor_details: DistractorDetail[];
  details: string[];
}

export interface DuplicateGroup {
  representative_slot: number;
  member_slots: number[];
  max_similarity: number;
}

export interface ProviderLog {
  provider: string;
  model: string;
  latency_ms: number;
  retry_count: number;
  success: boolean;
  error_type?: string;
  error_message?: string;
  input_chars: number;
  output_chars: number;
}

export interface SourceEvidence {
  document_id?: string | null;
  section_id?: string | null;
  chunk_id: string;
  chapter_number?: number | null;
  page?: number | null;
  parent_heading?: string | null;
  role?: string | null;
  score?: number | null;
  text_preview?: string | null;
}

export interface Question {
  id: string;
  question_number: number;
  blueprint_cell_key?: string | null;
  question_type: string;
  bloom_level: string;
  difficulty_score: number;
  content: string;
  options?: MCQOption[];
  correct_answer: string;
  rubric?: Record<string, unknown> | null;
  explanation?: string | null;
  source_citations?: string[];
  source_evidence?: SourceEvidence[];
  scope_tags: string[];
  warnings: string[];
  verification_status?: string | null;
  is_human_edited: boolean;
  is_locked: boolean;
  is_validated: boolean;
  quality_score_detail?: QualityScoreDetail | null;
  grounding_report_detail?: GroundingReportDetail | null;
}

export interface EditOperation {
  id: string;
  edit_type: string;
  target_question_id?: string | null;
  prompt_used?: string | null;
  created_at: string;
}

export interface ExamVersion {
  id: string;
  version_number: number;
  status: string;
  created_by: string;
  parent_version_id?: string | null;
  change_summary?: string | null;
  created_at: string;
  questions: Question[];
  edit_operations: EditOperation[];
}

export interface Exam {
  id: string;
  title: string;
  textbook_id: string;
  course_id?: string | null;
  exam_type: string;
  difficulty: string;
  status: string;
  chapters: number[];
  variant_number: number;
  total_questions: number;
  instructions?: string | null;
  output_language: string;
  strict_scope_flag: boolean;
  quality_score?: number | null;
  created_at: string;
  updated_at?: string | null;
  published_at?: string | null;
  questions: Question[];
  exam_spec?: Record<string, unknown> | null;
  blueprint?: Record<string, unknown> | null;
  selected_scope?: ScopeUnitPayload[] | null;
  quality_scores?: QualityScoreDetail[] | null;
  grounding_reports?: GroundingReportDetail[] | null;
  duplicate_groups?: DuplicateGroup[] | null;
  provider_logs?: ProviderLog[] | null;
  edit_impact_level?: "cosmetic" | "moderate" | "strong" | null;
  edit_history?: Record<string, unknown>[] | null;
  current_version?: ExamVersion | null;
  versions?: ExamVersion[] | null;
}

export interface ExamListItem {
  id: string;
  title: string;
  textbook_id: string;
  course_id?: string | null;
  exam_type: string;
  difficulty: string;
  status: string;
  chapters: number[];
  total_questions: number;
  strict_scope_flag: boolean;
  quality_score?: number | null;
  created_at: string;
  updated_at?: string | null;
}

export interface DifficultyDistribution {
  easy: number;
  medium: number;
  hard: number;
}

export interface ScopeUnitPayload {
  scope_id?: string;
  section_id?: string;
  scope_type: string;
  title?: string;
  chapter_number: number;
  page_from?: number | null;
  page_to?: number | null;
  tags: string[];
}

export interface ExamGenerationRequest {
  textbook_id?: string;
  document_id?: string;
  document_ids?: string[];
  course_id?: string;
  chapters: number[];
  scope: ScopeUnitPayload[];
  prompt: string;
  instructions?: string;
  total_questions: number;
  question_type?: string;
  exam_type?: string;
  difficulty?: string;
  question_distribution?: {
    mcq: DifficultyDistribution;
    essay: DifficultyDistribution;
  };
  num_variants?: number;
  gradually_increasing?: boolean;
  constraints: {
    strict_grounding: boolean;
    allow_applied_questions: boolean;
    strict_scope: boolean;
    grade_level_scope?: string;
    creativity_level: number;
    bloom_levels: string[];
    max_concurrency?: number;
  };
  time_limit_minutes?: number;
  output_language?: string;
  bloom_distribution?: Record<string, number>;
  formatting_preferences?: Record<string, unknown>;
  strict_scope?: boolean;
}

export interface GenerationStep {
  step: number;
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  message?: string;
  progress?: number;
}

export interface PartialEditRequest {
  question_ids: string[];
  edit_prompt?: string;
  range_start?: number;
  range_end?: number;
  edit_type: "regenerate" | "edit_text" | "edit_options" | "edit_answer" | "edit_bloom" | "lock" | "unlock" | "delete";
  new_content?: string;
  new_options?: MCQOption[];
  new_correct_answer?: string;
  new_bloom_level?: string;
}

export const auth = {
  login(email: string, password: string) {
    return request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  register(data: {
    email: string;
    password: string;
    full_name: string;
    department?: string;
    university?: string;
    role?: string;
  }) {
    return request<User>("/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  logout(refreshToken: string) {
    return request<{ message: string }>("/auth/logout", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  },

  refreshToken(refreshToken: string) {
    return request<{ access_token: string; token_type: string; expires_in: number }>("/auth/refresh-token", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  },

  me() {
    return request<User>("/auth/me");
  },
};

export const courses = {
  list() {
    return request<Course[]>("/courses/");
  },

  get(id: string) {
    return request<Course>(`/courses/${encodeURIComponent(id)}`);
  },

  create(data: CourseCreateRequest) {
    return request<Course>("/courses/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
};

export const documents = {
  list(courseId: string) {
    return request<Document[]>(`/courses/${encodeURIComponent(courseId)}/documents`);
  },

  upload(courseId: string, title: string, file: File, language = "vi") {
    const form = new FormData();
    form.append("title", title);
    form.append("language", language);
    form.append("file", file);
    return request<Document>(`/courses/${encodeURIComponent(courseId)}/documents/upload`, {
      method: "POST",
      body: form,
    });
  },

  status(documentId: string) {
    return request<DocumentStatus>(`/documents/${encodeURIComponent(documentId)}/status`);
  },

  getCurriculumTree(documentId: string) {
    return request<CurriculumNode[]>(`/documents/${encodeURIComponent(documentId)}/curriculum-tree`);
  },

  updateCurriculumTree(documentId: string, curriculumTree: CurriculumNode[]) {
    return request<CurriculumNode[]>(`/documents/${encodeURIComponent(documentId)}/curriculum-tree`, {
      method: "PATCH",
      body: JSON.stringify({ curriculum_tree: curriculumTree }),
    });
  },
};

export const textbooks = {
  list() {
    return request<TextbookListItem[]>("/textbooks/");
  },

  get(id: string) {
    return request<Textbook>(`/textbooks/${encodeURIComponent(id)}`);
  },

  upload(title: string, file: File, options?: { course_id?: string; language?: string }) {
    const form = new FormData();
    form.append("title", title);
    form.append("file", file);
    if (options?.course_id) form.append("course_id", options.course_id);
    if (options?.language) form.append("language", options.language);
    return request<Textbook>("/textbooks/upload", {
      method: "POST",
      body: form,
    });
  },

  delete(id: string) {
    return request<{ message: string }>(`/textbooks/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },
};

export const exams = {
  list() {
    return request<ExamListItem[]>("/exams/");
  },

  get(id: string) {
    return request<Exam>(`/exams/${encodeURIComponent(id)}`);
  },

  getVersions(id: string) {
    return request<ExamVersion[]>(`/exams/${encodeURIComponent(id)}/versions`);
  },

  publish(id: string) {
    return request<Exam>(`/exams/${encodeURIComponent(id)}/publish`, {
      method: "POST",
    });
  },

  delete(id: string) {
    return request<{ message: string }>(`/exams/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },
};

export const generation = {
  generate(data: ExamGenerationRequest) {
    return request<Exam>("/generate/exam", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  generateStream(
    data: ExamGenerationRequest,
    onStep: (step: GenerationStep) => void,
    onComplete: (exam: Exam) => void,
    onError: (error: string) => void,
  ): () => void {
    const controller = new AbortController();

    void (async () => {
      try {
        const token = getToken();
        const headers: Record<string, string> = {
          "Content-Type": "application/json",
        };
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetch(`${API_URL}/generate/exam/stream`, {
          method: "POST",
          headers,
          body: JSON.stringify(data),
          signal: controller.signal,
        });

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          onError(body.detail || res.statusText);
          return;
        }

        const reader = res.body?.getReader();
        if (!reader) {
          onError("No response body");
          return;
        }

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const payload = line.slice(6).trim();
            if (!payload) continue;

            try {
              const parsed = JSON.parse(payload) as GenerationStep & { type?: string; exam_id?: string; questions?: Question[] };
              if (parsed?.type === "complete" && parsed?.exam_id) {
                onComplete({ id: parsed.exam_id } as Exam);
              } else if (parsed?.type === "error") {
                onError(parsed.message || "Generation failed");
              } else if (parsed.questions) {
                onComplete(parsed as unknown as Exam);
              } else {
                onStep(parsed as GenerationStep);
              }
            } catch {
              // Ignore malformed lines from the stream.
            }
          }
        }
      } catch (error: unknown) {
        if (error instanceof Error && error.name !== "AbortError") {
          onError(error.message);
        }
      }
    })();

    return () => controller.abort();
  },

  partialRegenerate(data: { exam_id: string; edits: PartialEditRequest[] }) {
    return request<Exam>("/generate/partial-regenerate", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
};
