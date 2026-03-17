import type {
  Course,
  CourseCreateRequest,
  CurriculumNode,
  DocumentStatus,
  Exam,
  ExamGenerationRequest,
  ExamListItem,
  ExamVersion,
  GenerationStep,
  PartialEditRequest,
  Question,
  ScopeUnitPayload,
  Textbook,
  TextbookListItem,
  TokenResponse,
  User,
} from "./api";

const LOCAL_STATE_KEY = "exam-ai.local-state";
const LOCAL_MODE_KEY = "exam-ai.api-mode";
const LOCAL_TOKEN_PREFIX = "local-token:";
const LOCAL_REFRESH_PREFIX = "local-refresh:";

type LocalUserRecord = User & {
  password: string;
};

type LocalApiError = Error & {
  status: number;
};

type LocalAppState = {
  users: LocalUserRecord[];
  courses: Course[];
  textbooks: Textbook[];
  exams: Exam[];
  currentUserId: string | null;
};

function canUseBrowserStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function cloneValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function nowIso() {
  return new Date().toISOString();
}

function makeId(prefix: string) {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function makeError(status: number, message: string): LocalApiError {
  const error = new Error(message) as LocalApiError;
  error.status = status;
  return error;
}

function emptyState(): LocalAppState {
  return {
    users: [],
    courses: [],
    textbooks: [],
    exams: [],
    currentUserId: null,
  };
}

function readState(): LocalAppState {
  if (!canUseBrowserStorage()) {
    return emptyState();
  }

  const raw = window.localStorage.getItem(LOCAL_STATE_KEY);
  if (!raw) {
    return emptyState();
  }

  try {
    const parsed = JSON.parse(raw) as Partial<LocalAppState>;
    return {
      users: parsed.users ?? [],
      courses: parsed.courses ?? [],
      textbooks: parsed.textbooks ?? [],
      exams: parsed.exams ?? [],
      currentUserId: parsed.currentUserId ?? null,
    };
  } catch {
    return emptyState();
  }
}

function writeState(state: LocalAppState) {
  if (!canUseBrowserStorage()) return;
  window.localStorage.setItem(LOCAL_STATE_KEY, JSON.stringify(state));
}

function withComputedCourses(state: LocalAppState): LocalAppState {
  return {
    ...state,
    courses: state.courses.map((course) => {
      const owner = state.users.find((user) => user.id === course.owner_user_id);
      const documentCount = state.textbooks.filter((textbook) => textbook.course_id === course.id).length;
      return {
        ...course,
        membership_count: 1,
        document_count: documentCount,
        memberships: [
          {
            user_id: course.owner_user_id,
            role: "owner",
            full_name: owner?.full_name,
            email: owner?.email,
          },
        ],
      };
    }),
  };
}

function getLocalToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("token");
}

function getCurrentUserId(state: LocalAppState) {
  const token = getLocalToken();
  if (token?.startsWith(LOCAL_TOKEN_PREFIX)) {
    return token.slice(LOCAL_TOKEN_PREFIX.length);
  }
  return state.currentUserId;
}

function requireCurrentUser(state: LocalAppState): LocalUserRecord {
  const userId = getCurrentUserId(state);
  const user = state.users.find((candidate) => candidate.id === userId);
  if (!user) {
    throw makeError(401, "Please sign in to continue");
  }
  return user;
}

function toPublicUser(user: LocalUserRecord): User {
  const { password: _password, ...publicUser } = user;
  return publicUser;
}

function normalizeFileType(fileName: string) {
  const extension = fileName.split(".").pop()?.trim().toLowerCase();
  return extension || "file";
}

function buildCurriculumTree(title: string): CurriculumNode[] {
  const scopeId = makeId("scope");
  return [
    {
      id: scopeId,
      title,
      section_type: "chapter",
      section_order: 1,
      chapter_number: 1,
      page_from: 1,
      page_to: 1,
      scope_label: "chapter:1",
      summary: `Local fallback scope for ${title}.`,
      metadata: {
        source: "local-fallback",
      },
      children: [
        {
          id: makeId("scope"),
          title: `${title} - main ideas`,
          section_type: "topic",
          section_order: 1,
          chapter_number: 1,
          page_from: 1,
          page_to: 1,
          scope_label: "topic:1",
          summary: `Auto-created local topic for ${title}.`,
          metadata: {
            source: "local-fallback",
          },
          children: [],
        },
      ],
    },
  ];
}

function buildChaptersFromTree(tree: CurriculumNode[]) {
  const roots = tree.length > 0 ? tree : buildCurriculumTree("Untitled document");
  return roots.map((node, index) => ({
    id: makeId("chapter"),
    chapter_number: node.chapter_number || index + 1,
    title: node.title,
    start_page: node.page_from ?? 1,
    end_page: node.page_to ?? node.page_from ?? 1,
    summary: node.summary ?? undefined,
    key_concepts: [],
  }));
}

function toTextbookListItem(textbook: Textbook): TextbookListItem {
  return {
    id: textbook.id,
    course_id: textbook.course_id ?? null,
    title: textbook.title,
    file_name: textbook.file_name,
    file_type: textbook.file_type,
    file_size: textbook.file_size,
    status: textbook.status,
    version: textbook.version,
    total_pages_or_slides: textbook.total_pages_or_slides,
    total_chunks: textbook.total_chunks,
    chapter_count: textbook.chapters.length,
    created_at: textbook.created_at,
    updated_at: textbook.updated_at ?? null,
  };
}

function toDocumentStatus(textbook: Textbook): DocumentStatus {
  return {
    id: textbook.id,
    course_id: textbook.course_id ?? null,
    status: textbook.status,
    parse_error_message: null,
    total_pages_or_slides: textbook.total_pages_or_slides,
    total_chunks: textbook.total_chunks,
    updated_at: textbook.updated_at ?? null,
  };
}

function toExamListItem(exam: Exam): ExamListItem {
  return {
    id: exam.id,
    title: exam.title,
    textbook_id: exam.textbook_id,
    course_id: exam.course_id ?? null,
    exam_type: exam.exam_type,
    difficulty: exam.difficulty,
    status: exam.status,
    chapters: exam.chapters,
    total_questions: exam.total_questions,
    strict_scope_flag: exam.strict_scope_flag,
    quality_score: exam.quality_score ?? null,
    created_at: exam.created_at,
    updated_at: exam.updated_at ?? null,
  };
}

function findTextbook(state: LocalAppState, id: string) {
  return state.textbooks.find((textbook) => textbook.id === id);
}

function parseJsonBody<T>(body: BodyInit | null | undefined): T {
  if (typeof body !== "string") {
    throw makeError(400, "Invalid request body");
  }

  try {
    return JSON.parse(body) as T;
  } catch {
    throw makeError(400, "Invalid JSON payload");
  }
}

function createLocalTextbook(args: {
  title: string;
  file: File;
  courseId?: string;
  language?: string;
}): Textbook {
  const timestamp = nowIso();
  const curriculumTree = buildCurriculumTree(args.title);

  return {
    id: makeId("doc"),
    course_id: args.courseId ?? null,
    title: args.title,
    file_name: args.file.name,
    file_type: normalizeFileType(args.file.name),
    file_size: args.file.size,
    file_hash: null,
    file_storage_url: null,
    language: args.language ?? "vi",
    status: "processed",
    version: 1,
    total_pages_or_slides: 1,
    total_chunks: Math.max(1, Math.min(12, Math.ceil(args.file.size / 200_000))),
    created_at: timestamp,
    updated_at: timestamp,
    curriculum_tree: curriculumTree,
    chapters: buildChaptersFromTree(curriculumTree),
  };
}

function buildQuestionContent(
  title: string,
  scope: ScopeUnitPayload | undefined,
  questionType: "mcq" | "essay",
  difficulty: "easy" | "medium" | "hard",
  index: number,
): Question {
  const scopeLabel = scope?.title || title;
  const prompt = questionType === "mcq"
    ? `Which option best matches the key point from ${scopeLabel} in ${difficulty} question ${index}?`
    : `Explain the most important idea from ${scopeLabel} and apply it in a classroom context for question ${index}.`;

  const sourceEvidence = [
    {
      chunk_id: `local-chunk-${index}`,
      chapter_number: scope?.chapter_number || 1,
      page: scope?.page_from ?? 1,
      parent_heading: scopeLabel,
      role: "support",
      score: 1,
      text_preview: `Locally generated placeholder evidence for ${scopeLabel}.`,
    },
  ];

  if (questionType === "mcq") {
    return {
      id: makeId("question"),
      question_number: index,
      blueprint_cell_key: `cell-${index}`,
      question_type: "mcq",
      bloom_level: "apply",
      difficulty_score: difficulty === "easy" ? 0.3 : difficulty === "medium" ? 0.6 : 0.85,
      content: prompt,
      options: [
        { label: "A", text: `An unrelated statement about ${scopeLabel}` },
        { label: "B", text: `A grounded statement derived from ${scopeLabel}` },
        { label: "C", text: `A partially correct statement about ${scopeLabel}` },
        { label: "D", text: `A distractor that changes the scope of ${scopeLabel}` },
      ],
      correct_answer: "B",
      explanation: `Option B stays closest to the uploaded material for ${scopeLabel}.`,
      source_citations: [`${scopeLabel} - local source`],
      source_evidence: sourceEvidence,
      scope_tags: scope?.tags ?? ["local-scope"],
      warnings: [],
      verification_status: "passed",
      is_human_edited: false,
      is_locked: false,
      is_validated: true,
    };
  }

  return {
    id: makeId("question"),
    question_number: index,
    blueprint_cell_key: `cell-${index}`,
    question_type: "essay",
    bloom_level: "analyze",
    difficulty_score: difficulty === "easy" ? 0.35 : difficulty === "medium" ? 0.65 : 0.9,
    content: prompt,
    correct_answer: `A strong answer should explain ${scopeLabel}, connect it to the uploaded material, and justify the reasoning clearly.`,
    rubric: {
      accuracy: 5,
      reasoning: 3,
      clarity: 2,
    },
    explanation: `This essay prompt is scoped to ${scopeLabel}.`,
    source_citations: [`${scopeLabel} - local source`],
    source_evidence: sourceEvidence,
    scope_tags: scope?.tags ?? ["local-scope"],
    warnings: [],
    verification_status: "passed",
    is_human_edited: false,
    is_locked: false,
    is_validated: true,
  };
}

function buildGeneratedQuestions(title: string, payload: ExamGenerationRequest) {
  const questions: Question[] = [];
  const scopes = payload.scope.length > 0
    ? payload.scope
    : [
        {
          scope_type: "document",
          title,
          chapter_number: 1,
          page_from: 1,
          page_to: 1,
          tags: ["whole-document"],
        },
      ];

  let questionNumber = 1;

  const pushQuestions = (
    type: "mcq" | "essay",
    counts: { easy: number; medium: number; hard: number },
  ) => {
    (["easy", "medium", "hard"] as const).forEach((difficulty) => {
      for (let index = 0; index < counts[difficulty]; index += 1) {
        const scope = scopes[(questionNumber - 1) % scopes.length];
        questions.push(buildQuestionContent(title, scope, type, difficulty, questionNumber));
        questionNumber += 1;
      }
    });
  };

  if (payload.exam_type === "mcq" || payload.exam_type === "mixed") {
    pushQuestions("mcq", payload.question_distribution.mcq);
  }

  if (payload.exam_type === "essay" || payload.exam_type === "mixed") {
    pushQuestions("essay", payload.question_distribution.essay);
  }

  return questions;
}

function buildExamVersion(
  versionNumber: number,
  questions: Question[],
  createdBy: string,
  changeSummary: string,
  editType?: string,
  targetQuestionId?: string,
): ExamVersion {
  return {
    id: makeId("version"),
    version_number: versionNumber,
    status: "draft",
    created_by: createdBy,
    parent_version_id: null,
    change_summary: changeSummary,
    created_at: nowIso(),
    questions: cloneValue(questions),
    edit_operations: editType
      ? [
          {
            id: makeId("edit"),
            edit_type: editType,
            target_question_id: targetQuestionId ?? null,
            prompt_used: null,
            created_at: nowIso(),
          },
        ]
      : [],
  };
}

function generateExamRecord(state: LocalAppState, payload: ExamGenerationRequest): Exam {
  const user = requireCurrentUser(state);
  const textbook = payload.document_id
    ? findTextbook(state, payload.document_id)
    : payload.textbook_id
      ? findTextbook(state, payload.textbook_id)
      : undefined;

  if (!textbook) {
    throw makeError(404, "Please upload a document before generating an exam");
  }

  const questions = buildGeneratedQuestions(textbook.title, payload);
  if (questions.length === 0) {
    throw makeError(400, "Please add at least one question to generate an exam");
  }

  const createdAt = nowIso();
  const initialVersion = buildExamVersion(
    1,
    questions,
    user.id,
    "Initial local exam draft",
  );

  return {
    id: makeId("exam"),
    title: `${textbook.title} Exam`,
    textbook_id: textbook.id,
    course_id: textbook.course_id ?? null,
    exam_type: payload.exam_type,
    difficulty: payload.difficulty,
    status: "draft",
    chapters: payload.chapters,
    variant_number: Math.max(1, payload.num_variants || 1),
    total_questions: questions.length,
    instructions: payload.instructions ?? null,
    output_language: payload.output_language ?? "vi",
    strict_scope_flag: payload.strict_scope ?? payload.constraints.strict_scope,
    quality_score: 0.9,
    created_at: createdAt,
    updated_at: createdAt,
    published_at: null,
    questions: cloneValue(questions),
    exam_spec: {
      time_limit_minutes: payload.time_limit_minutes ?? null,
      prompt: payload.prompt,
      instructions: payload.instructions ?? null,
    },
    blueprint: {
      cells: questions.map((question) => ({
        key: question.blueprint_cell_key,
        question_type: question.question_type,
        bloom_level: question.bloom_level,
      })),
    },
    selected_scope: cloneValue(payload.scope).map((scope) => ({ ...scope })) as Record<string, unknown>[],
    quality_scores: null,
    grounding_reports: null,
    duplicate_groups: null,
    provider_logs: [
      {
        provider: "local",
        model: "frontend-fallback",
        latency_ms: 0,
        retry_count: 0,
        success: true,
        input_chars: payload.prompt.length,
        output_chars: questions.reduce((total, question) => total + question.content.length, 0),
      },
    ],
    edit_impact_level: null,
    edit_history: [],
    current_version: initialVersion,
    versions: [initialVersion],
  };
}

function renumberQuestions(questions: Question[]) {
  return questions.map((question, index) => ({
    ...question,
    question_number: index + 1,
  }));
}

function updateQuestionSet(
  questions: Question[],
  edit: PartialEditRequest,
  title: string,
): Question[] {
  const targetIds = new Set(edit.question_ids);
  const targetByRange = (question: Question) =>
    edit.question_ids.length === 0 &&
    edit.range_start !== undefined &&
    question.question_number >= edit.range_start &&
    question.question_number <= (edit.range_end ?? question.question_number);

  const isTarget = (question: Question) => targetIds.has(question.id) || targetByRange(question);

  switch (edit.edit_type) {
    case "edit_text":
      return questions.map((question) =>
        isTarget(question)
          ? {
              ...question,
              content: edit.new_content || question.content,
              is_human_edited: true,
            }
          : question,
      );
    case "edit_answer":
      return questions.map((question) =>
        isTarget(question)
          ? {
              ...question,
              correct_answer: edit.new_correct_answer || question.correct_answer,
              is_human_edited: true,
            }
          : question,
      );
    case "edit_bloom":
      return questions.map((question) =>
        isTarget(question)
          ? {
              ...question,
              bloom_level: edit.new_bloom_level || question.bloom_level,
              is_human_edited: true,
            }
          : question,
      );
    case "lock":
      return questions.map((question) => (isTarget(question) ? { ...question, is_locked: true } : question));
    case "unlock":
      return questions.map((question) => (isTarget(question) ? { ...question, is_locked: false } : question));
    case "delete":
      return renumberQuestions(questions.filter((question) => !isTarget(question)));
    case "regenerate":
      return questions.map((question) =>
        isTarget(question)
          ? {
              ...question,
              content: `${question.content} Revised locally for ${title}.`,
              explanation: edit.edit_prompt
                ? `Local revision note: ${edit.edit_prompt}`
                : `This question was refreshed locally for ${title}.`,
              warnings: [],
              is_human_edited: true,
            }
          : question,
      );
    default:
      return questions;
  }
}

function updateExamFromEdits(state: LocalAppState, examId: string, edits: PartialEditRequest[]) {
  const examIndex = state.exams.findIndex((candidate) => candidate.id === examId);
  if (examIndex < 0) {
    throw makeError(404, "Exam not found");
  }

  const currentExam = state.exams[examIndex];
  const user = requireCurrentUser(state);
  const textbook = findTextbook(state, currentExam.textbook_id);
  const title = textbook?.title || currentExam.title;
  const baseQuestions = cloneValue(currentExam.current_version?.questions || currentExam.questions);
  const nextQuestions = edits.reduce(
    (questions, edit) => updateQuestionSet(questions, edit, title),
    baseQuestions,
  );
  const renumbered = renumberQuestions(nextQuestions);
  const previousVersions = currentExam.versions && currentExam.versions.length > 0
    ? cloneValue(currentExam.versions)
    : currentExam.current_version
      ? [cloneValue(currentExam.current_version)]
      : [];
  const latestEdit = edits[edits.length - 1];
  const nextVersion = buildExamVersion(
    previousVersions.length + 1,
    renumbered,
    user.id,
    `Local ${latestEdit.edit_type} update`,
    latestEdit.edit_type,
    latestEdit.question_ids[0],
  );

  const updatedExam: Exam = {
    ...currentExam,
    total_questions: renumbered.length,
    questions: cloneValue(renumbered),
    status: currentExam.published_at ? currentExam.status : "draft",
    updated_at: nowIso(),
    current_version: nextVersion,
    versions: [...previousVersions, nextVersion],
  };

  state.exams[examIndex] = updatedExam;
  writeState(state);
  return cloneValue(updatedExam);
}

function publishExam(state: LocalAppState, examId: string) {
  const examIndex = state.exams.findIndex((candidate) => candidate.id === examId);
  if (examIndex < 0) {
    throw makeError(404, "Exam not found");
  }

  const publishedAt = nowIso();
  const updatedExam: Exam = {
    ...state.exams[examIndex],
    status: "published",
    published_at: publishedAt,
    updated_at: publishedAt,
  };

  state.exams[examIndex] = updatedExam;
  writeState(state);
  return cloneValue(updatedExam);
}

function decodePathValue(value: string) {
  return decodeURIComponent(value);
}

export function isLocalToken(token: string | null | undefined) {
  return token?.startsWith(LOCAL_TOKEN_PREFIX) ?? false;
}

export function isLocalModeEnabled() {
  return typeof window !== "undefined" && window.sessionStorage.getItem(LOCAL_MODE_KEY) === "local";
}

export function enableLocalMode() {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(LOCAL_MODE_KEY, "local");
}

export function isLocalFallbackActive() {
  return isLocalModeEnabled() || isLocalToken(getLocalToken());
}

export function handleLocalRequest<T>(path: string, options: RequestInit = {}): T {
  if (!canUseBrowserStorage()) {
    throw makeError(503, "Local fallback is only available in the browser");
  }

  const method = (options.method || "GET").toUpperCase();
  const normalizedPath = path.replace(/\/+$/, "") || "/";
  const state = withComputedCourses(readState());

  if (normalizedPath === "/auth/register" && method === "POST") {
    const payload = parseJsonBody<{
      email: string;
      password: string;
      full_name: string;
      department?: string;
      university?: string;
      role?: string;
    }>(options.body);

    if (state.users.some((user) => user.email.toLowerCase() === payload.email.toLowerCase())) {
      throw makeError(409, "Email already exists");
    }

    const user: LocalUserRecord = {
      id: makeId("user"),
      email: payload.email,
      full_name: payload.full_name,
      department: payload.department,
      university: payload.university,
      role: payload.role ?? "lecturer",
      is_email_verified: true,
      password: payload.password,
    };

    state.users.unshift(user);
    state.currentUserId = user.id;
    writeState(state);
    return cloneValue(toPublicUser(user)) as T;
  }

  if (normalizedPath === "/auth/login" && method === "POST") {
    const payload = parseJsonBody<{ email: string; password: string }>(options.body);
    const user = state.users.find((candidate) => candidate.email.toLowerCase() === payload.email.toLowerCase());
    if (!user || user.password !== payload.password) {
      throw makeError(401, "Invalid email or password");
    }

    state.currentUserId = user.id;
    writeState(state);

    const response: TokenResponse = {
      access_token: `${LOCAL_TOKEN_PREFIX}${user.id}`,
      refresh_token: `${LOCAL_REFRESH_PREFIX}${user.id}`,
      token_type: "bearer",
      expires_in: 60 * 60 * 12,
    };
    return response as T;
  }

  if (normalizedPath === "/auth/logout" && method === "POST") {
    state.currentUserId = null;
    writeState(state);
    return { message: "Signed out" } as T;
  }

  if (normalizedPath === "/auth/refresh-token" && method === "POST") {
    const currentUser = requireCurrentUser(state);
    return {
      access_token: `${LOCAL_TOKEN_PREFIX}${currentUser.id}`,
      token_type: "bearer",
      expires_in: 60 * 60 * 12,
    } as T;
  }

  if (normalizedPath === "/auth/me" && method === "GET") {
    return cloneValue(toPublicUser(requireCurrentUser(state))) as T;
  }

  if (normalizedPath === "/courses" && method === "GET") {
    const user = requireCurrentUser(state);
    return cloneValue(state.courses.filter((course) => course.owner_user_id === user.id)) as T;
  }

  if (normalizedPath === "/courses" && method === "POST") {
    const user = requireCurrentUser(state);
    const payload = parseJsonBody<CourseCreateRequest>(options.body);
    const course: Course = {
      id: makeId("course"),
      owner_user_id: user.id,
      course_name: payload.course_name,
      subject: payload.subject,
      academic_level: payload.academic_level,
      description: payload.description,
      created_at: nowIso(),
      updated_at: nowIso(),
      membership_count: 1,
      document_count: 0,
      memberships: [
        {
          user_id: user.id,
          role: "owner",
          full_name: user.full_name,
          email: user.email,
        },
      ],
    };

    state.courses.unshift(course);
    writeState(state);
    return cloneValue(course) as T;
  }

  const courseMatch = normalizedPath.match(/^\/courses\/([^/]+)$/);
  if (courseMatch && method === "GET") {
    requireCurrentUser(state);
    const id = decodePathValue(courseMatch[1]);
    const course = state.courses.find((candidate) => candidate.id === id);
    if (!course) {
      throw makeError(404, "Course not found");
    }
    return cloneValue(course) as T;
  }

  const courseDocumentsMatch = normalizedPath.match(/^\/courses\/([^/]+)\/documents$/);
  if (courseDocumentsMatch && method === "GET") {
    requireCurrentUser(state);
    const courseId = decodePathValue(courseDocumentsMatch[1]);
    const documents = state.textbooks.filter((textbook) => textbook.course_id === courseId);
    return cloneValue(documents) as T;
  }

  const courseUploadMatch = normalizedPath.match(/^\/courses\/([^/]+)\/documents\/upload$/);
  if (courseUploadMatch && method === "POST") {
    requireCurrentUser(state);
    if (!(options.body instanceof FormData)) {
      throw makeError(400, "Upload payload is missing");
    }

    const courseId = decodePathValue(courseUploadMatch[1]);
    const course = state.courses.find((candidate) => candidate.id === courseId);
    if (!course) {
      throw makeError(404, "Course not found");
    }

    const title = String(options.body.get("title") || "").trim();
    const language = String(options.body.get("language") || "vi");
    const file = options.body.get("file");

    if (!title || !(file instanceof File)) {
      throw makeError(400, "Please choose a file and document title");
    }

    const textbook = createLocalTextbook({
      title,
      file,
      courseId,
      language,
    });
    state.textbooks.unshift(textbook);
    writeState(state);
    return cloneValue(textbook) as T;
  }

  const documentStatusMatch = normalizedPath.match(/^\/documents\/([^/]+)\/status$/);
  if (documentStatusMatch && method === "GET") {
    requireCurrentUser(state);
    const id = decodePathValue(documentStatusMatch[1]);
    const textbook = findTextbook(state, id);
    if (!textbook) {
      throw makeError(404, "Document not found");
    }
    return cloneValue(toDocumentStatus(textbook)) as T;
  }

  const documentTreeMatch = normalizedPath.match(/^\/documents\/([^/]+)\/curriculum-tree$/);
  if (documentTreeMatch && method === "GET") {
    requireCurrentUser(state);
    const id = decodePathValue(documentTreeMatch[1]);
    const textbook = findTextbook(state, id);
    if (!textbook) {
      throw makeError(404, "Document not found");
    }
    return cloneValue(textbook.curriculum_tree) as T;
  }

  if (documentTreeMatch && method === "PATCH") {
    requireCurrentUser(state);
    const id = decodePathValue(documentTreeMatch[1]);
    const textbookIndex = state.textbooks.findIndex((candidate) => candidate.id === id);
    if (textbookIndex < 0) {
      throw makeError(404, "Document not found");
    }

    const payload = parseJsonBody<{ curriculum_tree: CurriculumNode[] }>(options.body);
    const curriculumTree = payload.curriculum_tree ?? [];
    const updatedTextbook: Textbook = {
      ...state.textbooks[textbookIndex],
      curriculum_tree: curriculumTree,
      chapters: buildChaptersFromTree(curriculumTree),
      updated_at: nowIso(),
    };
    state.textbooks[textbookIndex] = updatedTextbook;
    writeState(state);
    return cloneValue(updatedTextbook.curriculum_tree) as T;
  }

  if (normalizedPath === "/textbooks" && method === "GET") {
    const user = requireCurrentUser(state);
    const ownedCourseIds = new Set(state.courses.filter((course) => course.owner_user_id === user.id).map((course) => course.id));
    const textbooks = state.textbooks.filter(
      (textbook) => !textbook.course_id || ownedCourseIds.has(textbook.course_id),
    );
    return cloneValue(textbooks.map(toTextbookListItem)) as T;
  }

  if (normalizedPath === "/textbooks/upload" && method === "POST") {
    requireCurrentUser(state);
    if (!(options.body instanceof FormData)) {
      throw makeError(400, "Upload payload is missing");
    }

    const title = String(options.body.get("title") || "").trim();
    const language = String(options.body.get("language") || "vi");
    const courseId = String(options.body.get("course_id") || "").trim();
    const file = options.body.get("file");

    if (!title || !(file instanceof File)) {
      throw makeError(400, "Please choose a file and document title");
    }

    const textbook = createLocalTextbook({
      title,
      file,
      courseId: courseId || undefined,
      language,
    });
    state.textbooks.unshift(textbook);
    writeState(state);
    return cloneValue(textbook) as T;
  }

  const textbookMatch = normalizedPath.match(/^\/textbooks\/([^/]+)$/);
  if (textbookMatch && method === "GET") {
    requireCurrentUser(state);
    const id = decodePathValue(textbookMatch[1]);
    const textbook = findTextbook(state, id);
    if (!textbook) {
      throw makeError(404, "Document not found");
    }
    return cloneValue(textbook) as T;
  }

  if (textbookMatch && method === "DELETE") {
    requireCurrentUser(state);
    const id = decodePathValue(textbookMatch[1]);
    state.textbooks = state.textbooks.filter((textbook) => textbook.id !== id);
    state.exams = state.exams.filter((exam) => exam.textbook_id !== id);
    writeState(state);
    return { message: "Deleted" } as T;
  }

  if (normalizedPath === "/exams" && method === "GET") {
    requireCurrentUser(state);
    return cloneValue(state.exams.map(toExamListItem)) as T;
  }

  const examMatch = normalizedPath.match(/^\/exams\/([^/]+)$/);
  if (examMatch && method === "GET") {
    requireCurrentUser(state);
    const id = decodePathValue(examMatch[1]);
    const exam = state.exams.find((candidate) => candidate.id === id);
    if (!exam) {
      throw makeError(404, "Exam not found");
    }
    return cloneValue(exam) as T;
  }

  if (examMatch && method === "DELETE") {
    requireCurrentUser(state);
    const id = decodePathValue(examMatch[1]);
    state.exams = state.exams.filter((candidate) => candidate.id !== id);
    writeState(state);
    return { message: "Deleted" } as T;
  }

  const examVersionMatch = normalizedPath.match(/^\/exams\/([^/]+)\/versions$/);
  if (examVersionMatch && method === "GET") {
    requireCurrentUser(state);
    const id = decodePathValue(examVersionMatch[1]);
    const exam = state.exams.find((candidate) => candidate.id === id);
    if (!exam) {
      throw makeError(404, "Exam not found");
    }
    const versions = exam.versions && exam.versions.length > 0
      ? exam.versions
      : exam.current_version
        ? [exam.current_version]
        : [];
    return cloneValue(versions) as T;
  }

  const examPublishMatch = normalizedPath.match(/^\/exams\/([^/]+)\/publish$/);
  if (examPublishMatch && method === "POST") {
    requireCurrentUser(state);
    return publishExam(state, decodePathValue(examPublishMatch[1])) as T;
  }

  if (normalizedPath === "/generate/exam" && method === "POST") {
    const payload = parseJsonBody<ExamGenerationRequest>(options.body);
    const exam = generateExamRecord(state, payload);
    state.exams.unshift(exam);
    writeState(state);
    return cloneValue(exam) as T;
  }

  if (normalizedPath === "/generate/partial-regenerate" && method === "POST") {
    const payload = parseJsonBody<{ exam_id: string; edits: PartialEditRequest[] }>(options.body);
    return updateExamFromEdits(state, payload.exam_id, payload.edits) as T;
  }

  throw makeError(404, `No local handler for ${method} ${path}`);
}

export function handleLocalGenerateStream(
  payload: ExamGenerationRequest,
  onStep: (step: GenerationStep) => void,
  onComplete: (exam: Exam) => void,
  onError: (error: string) => void,
): () => void {
  try {
    const state = withComputedCourses(readState());
    const exam = generateExamRecord(state, payload);
    const steps: GenerationStep[] = [
      {
        step: 1,
        name: "Building exam spec",
        status: "running",
        progress: 10,
        message: "Preparing your local exam request.",
      },
      {
        step: 1,
        name: "Building exam spec",
        status: "completed",
        progress: 20,
      },
      {
        step: 2,
        name: "Planning blueprint",
        status: "running",
        progress: 35,
      },
      {
        step: 2,
        name: "Planning blueprint",
        status: "completed",
        progress: 45,
      },
      {
        step: 3,
        name: "Retrieving evidence",
        status: "running",
        progress: 60,
      },
      {
        step: 3,
        name: "Retrieving evidence",
        status: "completed",
        progress: 70,
      },
      {
        step: 4,
        name: "Generating and validating",
        status: "running",
        progress: 82,
      },
      {
        step: 4,
        name: "Generating and validating",
        status: "completed",
        progress: 92,
      },
      {
        step: 5,
        name: "Finalizing exam",
        status: "running",
        progress: 96,
      },
      {
        step: 5,
        name: "Finalizing exam",
        status: "completed",
        progress: 100,
      },
    ];

    let cancelled = false;
    const timers = steps.map((step, index) =>
      window.setTimeout(() => {
        if (cancelled) return;
        onStep(step);

        if (index === steps.length - 1) {
          const nextState = withComputedCourses(readState());
          nextState.exams.unshift(exam);
          writeState(nextState);
          onComplete(cloneValue(exam));
        }
      }, 220 * (index + 1)),
    );

    return () => {
      cancelled = true;
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Local generation failed";
    onError(message);
    return () => {};
  }
}

export function downloadLocalExamAsDocx(id: string, filename: string) {
  const state = withComputedCourses(readState());
  const exam = state.exams.find((candidate) => candidate.id === id);
  if (!exam) {
    throw makeError(404, "Exam not found");
  }

  const content = [
    exam.title,
    "",
    ...(exam.instructions ? [exam.instructions, ""] : []),
    ...exam.questions.flatMap((question) => {
      const lines = [`${question.question_number}. ${question.content}`];
      if (question.options?.length) {
        lines.push(...question.options.map((option) => `   ${option.label}. ${option.text}`));
      }
      lines.push(`Answer: ${question.correct_answer}`);
      if (question.explanation) {
        lines.push(`Explanation: ${question.explanation}`);
      }
      lines.push("");
      return lines;
    }),
  ].join("\r\n");

  const blob = new Blob([content], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(anchor);
}
