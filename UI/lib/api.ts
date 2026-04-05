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

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, headers });
  } catch (err) {
    const message =
      err instanceof TypeError && err.message === "Failed to fetch"
        ? "Cannot connect to server. Please check that the backend is running."
        : "Network error. Please check your connection.";
    throw new ApiError(0, message);
  }

  if (response.status !== 401 || !allowRefresh || path === "/auth/refresh") {
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

  let retryResponse: Response;
  try {
    retryResponse = await fetch(`${API_URL}${path}`, { ...options, headers: retryHeaders });
  } catch (err) {
    const message =
      err instanceof TypeError && err.message === "Failed to fetch"
        ? "Cannot connect to server. Please check that the backend is running."
        : "Network error. Please check your connection.";
    throw new ApiError(0, message);
  }
  return retryResponse;
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
        const response = await fetch(`${API_URL}/auth/refresh`, {
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
  return ["pending", "processing", "processed", "structured", "indexed"].includes(status.toLowerCase());
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

export interface DocumentUploadResponse {
  document_id: string;
  message: string;
  s3_key: string;
  processing_status?: string;
  uploaded_at?: string | null;
  created_at?: string | null;
}

export interface DocumentStatus {
  id: string;
  course_id?: string | null;
  status: string;
  parse_error_message?: string | null;
  total_pages_or_slides: number;
  total_chunks: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Document {
  id: string;
  course_id?: string | null;
  title: string;
  file_name: string;
  original_filename: string;
  file_type: string;
  file_size: number;
  file_hash?: string | null;
  file_storage_url?: string | null;
  language?: string | null;
  status: string;
  processing_status: string;
  version: number;
  total_pages_or_slides: number;
  total_chunks: number;
  created_at?: string | null;
  uploaded_at?: string | null;
  updated_at?: string | null;
  curriculum_tree: CurriculumNode[];
}

export interface DocumentListItem {
  id: string;
  course_id?: string | null;
  title: string;
  original_filename: string;
  file_name: string;
  file_type: string;
  file_size: number;
  status: string;
  processing_status: string;
  version: number;
  chapter_count?: number;
  created_at?: string | null;
  uploaded_at?: string | null;
  updated_at?: string | null;
  total_pages_or_slides: number;
  total_chunks: number;
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
  chapters: string[];
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
  chapters: string[];
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
  chapters: string[];
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
    return request<{ access_token: string; token_type: string; expires_in: number }>("/auth/refresh", {
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
  async listAll() {
    const res = await request<DocumentListItem[] | { items: DocumentListItem[] }>("/documents");
    return Array.isArray(res) ? res : (res.items ?? []);
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
    return request<DocumentUploadResponse>(path, {
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
    return request<{ document_id: string; curriculum_tree: CurriculumNode[] }>(
      `/documents/${encodeURIComponent(documentId)}/curriculum-tree`
    ).then((r) => r.curriculum_tree);
  },

  updateCurriculumTree(documentId: string, curriculumTree: CurriculumNode[]) {
    return request<{ document_id: string; curriculum_tree: CurriculumNode[] }>(
      `/documents/${encodeURIComponent(documentId)}/curriculum-tree`,
      {
        method: "PATCH",
        body: JSON.stringify({ curriculum_tree: curriculumTree }),
      }
    ).then((r) => r.curriculum_tree);
  },

  delete(documentId: string) {
    return request<{ message: string }>(`/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    });
  },

  rescanStructure(documentId: string) {
    return request<DocumentListItem>(
      `/documents/${encodeURIComponent(documentId)}/rescan-structure`,
      { method: "POST" }
    );
  },
};

export const exams = {
  list() {
    return request<ExamListItem[]>("/exams/");
  },

  get(examId: string) {
    return request<Exam>(`/exams/${encodeURIComponent(examId)}`);
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
  generate(data: ExamGenerationRequest): Promise<Exam & { job_id: string; websocket_url: string; message: string }> {
    return request<Exam & { job_id: string; websocket_url: string; message: string }>("/generate/exam", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  /**
   * Connect to the exam generation WebSocket for real-time progress.
   *
   * Usage:
   *   const gen = generation.connect(websocketUrl);
   *   gen.on("plan_step", (data) => { ... });
   *   gen.on("question_generated", (data) => { ... });
   *   gen.on("hitl_checkpoint", (data) => { ... });
   *   gen.on("validation_result", (data) => { ... });
   *   gen.on("completed", (data) => { ... });
   *   gen.on("error", (data) => { ... });
   *   gen.connect();
   *
   * Returns a GenerationClient with event handlers and lifecycle methods.
   * The client automatically replays stored events from Redis on connect (G19).
   */
  connect(
    websocketUrl: string,
    handlers: {
      onPlanStep?: (data: { step: number; total_steps: number; message: string }) => void;
      onQuestionGenerated?: (data: { question_id: string; question: Question }) => void;
      onHitlCheckpoint?: (data: { checkpoint_id: number; data: Record<string, unknown> }) => void;
      onValidationResult?: (data: { passed: boolean; issues_count: number; issues: unknown[] }) => void;
      onCompleted?: (data: { exam_id: string; status: string }) => void;
      onError?: (data: { message: string }) => void;
      onClarificationNeeded?: (data: { clarification_questions: unknown[] }) => void;
      onPipelinePaused?: (data: { checkpoint_id: number; message: string }) => void;
      onClose?: () => void;
    },
  ): GenerationClient {
    return new GenerationClient(websocketUrl, handlers);
  },

  partialRegenerate(data: { exam_id: string; edits: PartialEditRequest[] }) {
    return request<Exam>("/generate/partial-regenerate", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  approveBlueprint(examId: string, approved: boolean, feedback?: string) {
    return request(`/exams/${examId}/approve-blueprint`, {
      method: "POST",
      body: JSON.stringify({ approved, feedback }),
    });
  },

  rejectBlueprint(examId: string, feedback: string) {
    return request(`/exams/${examId}/reject-blueprint`, {
      method: "POST",
      body: JSON.stringify({ feedback }),
    });
  },
};

/**
 * WebSocket client for real-time exam generation.
 * Connects to /ws/exam/{exam_id} and dispatches typed events.
 */
export class GenerationClient {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: Parameters<typeof generation.connect>[1];
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 3;
  private shouldReconnect = true;

  constructor(url: string, handlers: Parameters<typeof generation.connect>[1]) {
    this.url = url;
    this.handlers = handlers;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
      };

      this.ws.onmessage = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data as string) as {
            type?: string;
            [key: string]: unknown;
          };
          switch (data.type) {
            case "plan_step":
              this.handlers.onPlanStep?.(data as { step: number; total_steps: number; message: string });
              break;
            case "question_generated":
              this.handlers.onQuestionGenerated?.(data as { question_id: string; question: Question });
              break;
            case "hitl_checkpoint":
              this.handlers.onHitlCheckpoint?.(data as { checkpoint_id: number; data: Record<string, unknown> });
              break;
            case "validation_result":
              this.handlers.onValidationResult?.(data as { passed: boolean; issues_count: number; issues: unknown[] });
              break;
            case "completed":
              this.handlers.onCompleted?.(data as { exam_id: string; status: string });
              break;
            case "error":
              this.handlers.onError?.(data as { message: string });
              break;
            case "clarification_needed":
              this.handlers.onClarificationNeeded?.(data as { clarification_questions: unknown[] });
              break;
            case "pipeline_paused":
              this.handlers.onPipelinePaused?.(data as { checkpoint_id: number; message: string });
              break;
          }
        } catch {
          // Ignore malformed messages
        }
      };

      this.ws.onerror = () => {
        this.handlers.onError?.({ message: "WebSocket connection error" });
      };

      this.ws.onclose = () => {
        this.handlers.onClose?.();
        if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
          this.reconnectAttempts++;
          setTimeout(() => this.connect(), 1000 * this.reconnectAttempts);
        }
      };
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Failed to connect";
      this.handlers.onError?.({ message });
    }
  }

  disconnect(): void {
    this.shouldReconnect = false;
    this.ws?.close();
  }
}

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
