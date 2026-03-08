const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// ─── Helper ────────────────────────────────────────────────────────

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
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
      // Pydantic 422 validation errors — extract readable messages
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

// ─── Types ─────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  full_name: string;
  department?: string;
  university?: string;
  is_email_verified?: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface Chapter {
  id: string;
  chapter_number: number;
  title: string;
  start_page?: number;
  end_page?: number;
  summary?: string;
  key_concepts?: string;
}

export interface TextbookListItem {
  id: string;
  title: string;
  file_name: string;
  file_type: string;
  file_size: number;
  status: string;
  version: number;
  total_chunks: number;
  chapter_count: number;
  created_at: string;
}

export interface Textbook {
  id: string;
  title: string;
  file_name: string;
  file_type: string;
  file_size: number;
  status: string;
  version: number;
  total_chunks: number;
  created_at: string;
  chapters: Chapter[];
}

export interface MCQOption {
  label: string;
  text: string;
}

export interface Question {
  id: string;
  question_number: number;
  question_type: string;
  bloom_level: string;
  difficulty_score: number;
  content: string;
  options?: MCQOption[];
  correct_answer: string;
  explanation?: string;
  source_citations?: string[];
  is_validated: boolean;
}

export interface Exam {
  id: string;
  title: string;
  textbook_id: string;
  exam_type: string;
  difficulty: string;
  status: string;
  chapters: number[];
  variant_number: number;
  total_questions: number;
  quality_score?: number;
  created_at: string;
  questions: Question[];
}

export interface ExamListItem {
  id: string;
  title: string;
  textbook_id: string;
  exam_type: string;
  difficulty: string;
  status: string;
  chapters: number[];
  total_questions: number;
  quality_score?: number;
  created_at: string;
}

export interface DifficultyDistribution {
  easy: number;
  medium: number;
  hard: number;
}

export interface ExamGenerationRequest {
  textbook_id: string;
  chapters: number[];
  prompt: string;
  exam_type: string;
  difficulty: string;
  question_distribution: {
    mcq: DifficultyDistribution;
    essay: DifficultyDistribution;
  };
  num_variants: number;
  gradually_increasing: boolean;
  constraints: {
    strict_grounding: boolean;
    allow_applied_questions: boolean;
    grade_level_scope?: string;
    creativity_level: number;
    bloom_levels: string[];
  };
}

export interface GenerationStep {
  step: number;
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  message?: string;
  progress?: number;
}

// ─── Auth API ──────────────────────────────────────────────────────

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

// ─── Textbooks API ─────────────────────────────────────────────────

export const textbooks = {
  list() {
    return request<TextbookListItem[]>("/textbooks/");
  },
  get(id: string) {
    return request<Textbook>(`/textbooks/${encodeURIComponent(id)}`);
  },
  upload(title: string, file: File) {
    const form = new FormData();
    form.append("title", title);
    form.append("file", file);
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

// ─── Exams API ─────────────────────────────────────────────────────

export const exams = {
  list() {
    return request<ExamListItem[]>("/exams/");
  },
  get(id: string) {
    return request<Exam>(`/exams/${encodeURIComponent(id)}`);
  },
  delete(id: string) {
    return request<{ message: string }>(`/exams/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },
};

// ─── Generation API ────────────────────────────────────────────────

export const generation = {
  generate(data: ExamGenerationRequest) {
    return request<Exam>("/generate/exam", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  /** SSE stream — returns a function to abort */
  generateStream(
    data: ExamGenerationRequest,
    onStep: (step: GenerationStep) => void,
    onComplete: (exam: Exam) => void,
    onError: (error: string) => void,
  ): () => void {
    const controller = new AbortController();

    (async () => {
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
        if (!reader) { onError("No response body"); return; }

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
              const parsed = JSON.parse(payload);
              if (parsed.questions) {
                onComplete(parsed as Exam);
              } else {
                onStep(parsed as GenerationStep);
              }
            } catch {
              // skip malformed
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== "AbortError") {
          onError(err.message);
        }
      }
    })();

    return () => controller.abort();
  },

  partialRegenerate(data: {
    exam_id: string;
    edits: {
      question_ids: string[];
      edit_prompt?: string;
      range_start?: number;
      range_end?: number;
      edit_type: string;
      new_content?: string;
    }[];
  }) {
    return request<Exam>("/generate/partial-regenerate", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
};
