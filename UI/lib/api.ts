const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
const SESSION_EXPIRED_EVENT = "examai:session-expired";

let refreshPromise: Promise<string | null> | null = null;

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("refresh_token");
}

function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("token", token);
}

function clearStoredSession(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("token");
  localStorage.removeItem("refresh_token");
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

async function authorizedFetch(
  path: string,
  options: RequestInit = {},
  allowRefresh = true,
): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (response.status !== 401 || !allowRefresh || path === "/auth/refresh-token") {
    return response;
  }

  const refreshedToken = await refreshAccessToken();
  if (!refreshedToken) {
    return response;
  }

  const retryHeaders: Record<string, string> = {
    ...(options.headers as Record<string, string>),
    Authorization: `Bearer ${refreshedToken}`,
  };
  if (!(options.body instanceof FormData) && !retryHeaders["Content-Type"]) {
    retryHeaders["Content-Type"] = "application/json";
  }

  return fetch(`${API_URL}${path}`, { ...options, headers: retryHeaders });
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    clearStoredSession();
    return null;
  }

  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const response = await fetch(`${API_URL}/auth/refresh-token`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });

        if (!response.ok) {
          clearStoredSession();
          return null;
        }

        const payload = await response.json() as {
          access_token?: string;
        };
        const nextToken = payload.access_token?.trim();
        if (!nextToken) {
          clearStoredSession();
          return null;
        }

        setToken(nextToken);
        return nextToken;
      } catch {
        clearStoredSession();
        return null;
      } finally {
        refreshPromise = null;
      }
    })();
  }

  return refreshPromise;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await authorizedFetch(path, options);

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

interface DocumentUploadOptions {
  course_id?: string;
  language?: string;
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
  error_categories: string[];
}

export interface EditOperation {
  id: string;
  edit_type: string;
  target_question_id?: string | null;
  target_slots: number[];
  prompt_used?: string | null;
  created_at: string;
}

export interface FeedbackEvent {
  id: string;
  exam_id: string;
  exam_title?: string | null;
  exam_version_id?: string | null;
  version_number?: number | null;
  actor_id?: string | null;
  signal_type: string;
  severity: string;
  workflow_stage?: string | null;
  event_stage?: string | null;
  event_source?: string | null;
  source_type?: string | null;
  source_ref?: string | null;
  review_status?: string | null;
  reviewed_by_human: boolean;
  question_id?: string | null;
  error_categories: string[];
  before_snapshot_ref?: string | null;
  after_snapshot_ref?: string | null;
  linked_eval_sample_id?: string | null;
  payload?: Record<string, unknown> | null;
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
  feedback_events: FeedbackEvent[];
}

export interface Exam {
  id: string;
  title: string;
  document_id: string;
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
  feedback_events?: FeedbackEvent[] | null;
  current_version?: ExamVersion | null;
  versions?: ExamVersion[] | null;
}

export interface ExamListItem {
  id: string;
  title: string;
  document_id: string;
  course_id?: string | null;
  exam_type: string;
  difficulty: string;
  status: string;
  chapters: number[];
  total_questions: number;
  strict_scope_flag: boolean;
  quality_score?: number | null;
  current_version_number?: number | null;
  version_count: number;
  verifier_pass_rate?: number | null;
  evidence_coverage_rate?: number | null;
  warning_count: number;
  regenerate_count: number;
  human_edit_count: number;
  feedback_event_count: number;
  created_at: string;
  updated_at?: string | null;
}

export interface ErrorCategoryCount {
  category: string;
  count: number;
}

export interface NamedCount {
  name: string;
  count: number;
}

export interface QualitySummary {
  documents_active: number;
  exams_generated: number;
  question_count: number;
  verifier_pass_rate: number;
  verifier_warning_rate: number;
  evidence_coverage_rate: number;
  scope_violation_rate: number;
  avg_regenerate_count: number;
  avg_human_edit_count: number;
  version_churn: number;
  top_error_categories: ErrorCategoryCount[];
  recent_warnings: FeedbackEvent[];
  last_updated_at?: string | null;
}

export interface FeedbackStoreSummary {
  total_events: number;
  reviewed_by_human_count: number;
  accepted_count: number;
  rejected_count: number;
  corrected_count: number;
  linked_eval_count: number;
  top_signal_types: NamedCount[];
  top_error_categories: ErrorCategoryCount[];
  recent_events: FeedbackEvent[];
  last_updated_at?: string | null;
}

export interface PlaybookBullet {
  id: string;
  status: string;
  title: string;
  bullet_type: string;
  scope?: Record<string, unknown> | null;
  subject: string;
  language: string;
  question_type: string;
  content: string;
  rationale?: string | null;
  source_signals: Record<string, unknown>[];
  helpful_count: number;
  harmful_count: number;
  confidence: number;
  tags: string[];
  created_from?: string | null;
  review_status?: string | null;
  version: number;
  archived_at?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface ReflectionCandidate {
  id: string;
  status: string;
  category: string;
  subject: string;
  language: string;
  question_type: string;
  scope?: Record<string, unknown> | null;
  evidence?: Record<string, unknown> | null;
  proposed_title: string;
  proposed_bullet_type: string;
  proposed_bullet_text: string;
  rationale?: string | null;
  source_event_ids: string[];
  source_eval_sample_ids: string[];
  confidence: number;
  merge_key: string;
  review_notes?: string | null;
  promoted_bullet_id?: string | null;
  created_at: string;
  updated_at?: string | null;
  reviewed_at?: string | null;
}

export interface WarmupPreview {
  meta: {
    exported_at: string;
    exam_case_count: number;
    question_case_count: number;
    feedback_case_count: number;
    playbook_seed_count: number;
    reflection_candidate_count: number;
  };
  exam_cases: Record<string, unknown>[];
  question_cases: Record<string, unknown>[];
  feedback_cases: Record<string, unknown>[];
  playbook_seed: Record<string, unknown>[];
  reflection_candidates: Record<string, unknown>[];
}

export interface PlaybookOverview {
  retrieval_mode: string;
  retrieval_limit: number;
  feedback_event_count: number;
  approved_bullet_count: number;
  candidate_bullet_count: number;
  archived_bullet_count: number;
  reflection_candidate_count: number;
  promoted_candidate_count: number;
  warmup_exam_case_count: number;
  warmup_question_case_count: number;
  warmup_feedback_case_count: number;
  top_feedback_categories: NamedCount[];
  recent_bullets: PlaybookBullet[];
  recent_candidates: ReflectionCandidate[];
  last_reflection_run_at?: string | null;
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
  document_id?: string;
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
  };
  num_variants?: number;
  gradually_increasing?: boolean;
  constraints: {
    strict_grounding: boolean;
    allow_applied_questions: boolean;
    grade_level_scope?: string;
    creativity_level: number;
    bloom_levels: string[];
    max_concurrency?: number;
  };
  time_limit_minutes?: number;
  output_language?: string;
  bloom_distribution?: Record<string, number>;
  formatting_preferences?: Record<string, unknown>;
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
  listAll() {
    return request<DocumentListItem[]>("/documents");
  },

  list(courseId?: string) {
    if (!courseId) {
      return request<DocumentListItem[]>("/documents");
    }
    return request<DocumentListItem[]>(`/courses/${encodeURIComponent(courseId)}/documents`);
  },

  get(documentId: string) {
    return request<Document>(`/documents/${encodeURIComponent(documentId)}`);
  },

  upload(title: string, file: File, options?: DocumentUploadOptions) {
    const form = new FormData();
    form.append("title", title);
    form.append("language", options?.language || "vi");
    form.append("file", file);
    const path = options?.course_id
      ? `/courses/${encodeURIComponent(options.course_id)}/documents/upload`
      : "/documents/upload";
    return request<Document>(path, {
      method: "POST",
      body: form,
    });
  },

  uploadToCourse(courseId: string, title: string, file: File, language = "vi") {
    return documents.upload(title, file, { course_id: courseId, language });
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

  delete(documentId: string) {
    return request<{ message: string }>(`/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    });
  },
};

export const exams = {
  list() {
    return request<ExamListItem[]>("/exams/");
  },

  getQualitySummary() {
    return request<QualitySummary>("/exams/quality-summary");
  },

  getFeedbackSummary() {
    return request<FeedbackStoreSummary>("/exams/feedback-summary");
  },

  getFeedbackStore(params?: {
    exam_version_id?: string;
    question_id?: string;
    signal_type?: string;
    review_status?: string;
    actor_id?: string;
    event_stage?: string;
    error_category?: string;
    linked_eval_sample_id?: string;
    limit?: number;
  }) {
    const search = new URLSearchParams();
    if (params?.exam_version_id) search.set("exam_version_id", params.exam_version_id);
    if (params?.question_id) search.set("question_id", params.question_id);
    if (params?.signal_type) search.set("signal_type", params.signal_type);
    if (params?.review_status) search.set("review_status", params.review_status);
    if (params?.actor_id) search.set("actor_id", params.actor_id);
    if (params?.event_stage) search.set("event_stage", params.event_stage);
    if (params?.error_category) search.set("error_category", params.error_category);
    if (params?.linked_eval_sample_id) search.set("linked_eval_sample_id", params.linked_eval_sample_id);
    if (params?.limit) search.set("limit", String(params.limit));
    const suffix = search.size > 0 ? `?${search.toString()}` : "";
    return request<FeedbackEvent[]>(`/exams/feedback-store${suffix}`);
  },

  get(id: string) {
    return request<Exam>(`/exams/${encodeURIComponent(id)}`);
  },

  getVersions(id: string) {
    return request<ExamVersion[]>(`/exams/${encodeURIComponent(id)}/versions`);
  },

  getFeedback(
    id: string,
    params?: {
      exam_version_id?: string;
      question_id?: string;
      signal_type?: string;
      review_status?: string;
      actor_id?: string;
      event_stage?: string;
      error_category?: string;
      linked_eval_sample_id?: string;
      limit?: number;
    },
  ) {
    const search = new URLSearchParams();
    if (params?.exam_version_id) search.set("exam_version_id", params.exam_version_id);
    if (params?.question_id) search.set("question_id", params.question_id);
    if (params?.signal_type) search.set("signal_type", params.signal_type);
    if (params?.review_status) search.set("review_status", params.review_status);
    if (params?.actor_id) search.set("actor_id", params.actor_id);
    if (params?.event_stage) search.set("event_stage", params.event_stage);
    if (params?.error_category) search.set("error_category", params.error_category);
    if (params?.linked_eval_sample_id) search.set("linked_eval_sample_id", params.linked_eval_sample_id);
    if (params?.limit) search.set("limit", String(params.limit));
    const suffix = search.size > 0 ? `?${search.toString()}` : "";
    return request<FeedbackEvent[]>(`/exams/${encodeURIComponent(id)}/feedback${suffix}`);
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
        const res = await authorizedFetch("/generate/exam/stream", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
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

export const playbook = {
  getOverview() {
    return request<PlaybookOverview>("/playbook/overview");
  },

  listBullets(params?: { status?: string; bullet_type?: string; limit?: number }) {
    const search = new URLSearchParams();
    if (params?.status) search.set("status", params.status);
    if (params?.bullet_type) search.set("bullet_type", params.bullet_type);
    if (params?.limit) search.set("limit", String(params.limit));
    const suffix = search.size > 0 ? `?${search.toString()}` : "";
    return request<PlaybookBullet[]>(`/playbook/bullets${suffix}`);
  },

  archiveBullet(id: string) {
    return request<PlaybookBullet>(`/playbook/bullets/${encodeURIComponent(id)}/archive`, {
      method: "POST",
    });
  },

  listCandidates(params?: { status?: string; limit?: number }) {
    const search = new URLSearchParams();
    if (params?.status) search.set("status", params.status);
    if (params?.limit) search.set("limit", String(params.limit));
    const suffix = search.size > 0 ? `?${search.toString()}` : "";
    return request<ReflectionCandidate[]>(`/playbook/candidates${suffix}`);
  },

  generateCandidates() {
    return request<ReflectionCandidate[]>("/playbook/candidates/generate", {
      method: "POST",
    });
  },

  promoteCandidate(id: string) {
    return request<PlaybookBullet>(`/playbook/candidates/${encodeURIComponent(id)}/promote`, {
      method: "POST",
    });
  },

  rejectCandidate(id: string) {
    return request<ReflectionCandidate>(`/playbook/candidates/${encodeURIComponent(id)}/reject`, {
      method: "POST",
    });
  },

  getWarmupPreview() {
    return request<WarmupPreview>("/playbook/warmup-preview");
  },
};
