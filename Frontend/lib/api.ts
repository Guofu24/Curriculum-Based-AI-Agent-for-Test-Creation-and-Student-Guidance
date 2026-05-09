// ExamAI API Client
// Based on SYSTEM_SPEC.md backend routes

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'

// Token management
export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('token')
}

export function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('refresh_token')
}

export function setTokens(accessToken: string, refreshToken: string) {
  localStorage.setItem('token', accessToken)
  localStorage.setItem('refresh_token', refreshToken)
}

export function clearTokens() {
  localStorage.removeItem('token')
  localStorage.removeItem('refresh_token')
}

// API fetch wrapper with auth
async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken()
  
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  }
  
  if (token) {
    (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`
  }
  
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  })
  
  if (!response.ok) {
    if (response.status === 401) {
      // Try refresh token
      const refreshed = await refreshAccessToken()
      if (refreshed) {
        // Retry the request
        return apiFetch<T>(endpoint, options)
      }
      clearTokens()
      throw new Error('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')
    }
    
    const error = await response.json().catch(() => ({ detail: 'Có lỗi xảy ra' }))
    throw new Error(error.detail || error.message || 'Có lỗi xảy ra')
  }
  
  return response.json()
}

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return false
  
  try {
    const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    
    if (!response.ok) return false
    
    const data = await response.json()
    localStorage.setItem('token', data.access_token)
    return true
  } catch {
    return false
  }
}

// ============ AUTH API ============
export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  full_name?: string
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserResponse {
  id: string
  email: string
  full_name: string | null
  role: string
  created_at: string
}

export const authApi = {
  login: async (data: LoginRequest): Promise<AuthResponse> => {
    const response = await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Đăng nhập thất bại' }))
      throw new Error(error.detail || 'Đăng nhập thất bại')
    }
    
    const result = await response.json()
    setTokens(result.access_token, result.refresh_token)
    return result
  },
  
  register: async (data: RegisterRequest): Promise<UserResponse> => {
    const response = await fetch(`${API_BASE_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Đăng ký thất bại' }))
      throw new Error(error.detail || 'Đăng ký thất bại')
    }
    
    return response.json()
  },
  
  logout: async (): Promise<void> => {
    const refreshToken = getRefreshToken()
    if (refreshToken) {
      try {
        await apiFetch('/auth/logout', {
          method: 'POST',
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
      } catch {
        // Ignore logout errors
      }
    }
    clearTokens()
  },
  
  me: async (): Promise<UserResponse> => {
    return apiFetch<UserResponse>('/auth/me')
  },
}

// ============ DOCUMENTS API ============
export interface Document {
  id: string
  original_filename: string
  title?: string
  file_type: string
  file_size?: number
  processing_status: 'pending' | 'processing' | 'completed' | 'failed' | 'indexed' | 'processed'
  status?: string
  course_id?: string
  version?: number
  chapter_count?: number
  total_chapters?: number
  total_pages_or_slides?: number
  total_chunks?: number
  heading_tree?: HeadingNode[]
  curriculum_tree?: CurriculumNode[]
  created_at: string
  updated_at?: string
}

export interface HeadingNode {
  title: string
  level: number
  chapter_id?: string
  children?: HeadingNode[]
}

export interface CurriculumNode {
  id: string
  title: string
  level: number
  parent_id?: string
  chapter_id?: string
  chunk_count?: number
}

export interface DocumentListResponse {
  items: Document[]
  total: number
  page: number
  limit: number
}

export const documentsApi = {
  list: async (page = 1, limit = 20): Promise<DocumentListResponse> => {
    return apiFetch<DocumentListResponse>(`/documents/?page=${page}&limit=${limit}`)
  },
  
  get: async (id: string): Promise<Document> => {
    return apiFetch<Document>(`/documents/${id}`)
  },
  
  getStatus: async (id: string): Promise<{ processing_status: string }> => {
    return apiFetch<{ processing_status: string }>(`/documents/${id}/status`)
  },
  
  upload: async (file: File): Promise<Document> => {
    const token = getToken()
    const formData = new FormData()
    formData.append('file', file)
    
    const response = await fetch(`${API_BASE_URL}/documents/upload`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    })
    
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload thất bại' }))
      throw new Error(error.detail || 'Upload thất bại')
    }
    
    return response.json()
  },
  
  delete: async (id: string): Promise<void> => {
    await apiFetch(`/documents/${id}`, { method: 'DELETE' })
  },
  
  getCurriculumTree: async (id: string): Promise<CurriculumNode[]> => {
    const res = await apiFetch<{ document_id: string; curriculum_tree: CurriculumNode[] }>(`/documents/${id}/curriculum-tree`)
    return res.curriculum_tree ?? res
  },
  
  updateCurriculumTree: async (id: string, nodes: CurriculumNode[]): Promise<void> => {
    await apiFetch(`/documents/${id}/curriculum-tree`, {
      method: 'PATCH',
      body: JSON.stringify({ curriculum_tree: nodes }),
    })
  },
  
  reprocess: async (id: string): Promise<void> => {
    await apiFetch(`/documents/${id}/reprocess`, { method: 'POST' })
  },
  
  refreshUrl: async (id: string): Promise<{ url: string }> => {
    // Backend returns { presigned_url } — map to { url } for consistency
    const res = await apiFetch<{ presigned_url?: string; url?: string }>(`/documents/${id}/refresh-url`)
    return { url: res.presigned_url ?? res.url ?? '' }
  },

  rescanStructure: async (id: string): Promise<void> => {
    await apiFetch(`/documents/${id}/rescan-structure`, { method: 'POST' })
  },
}

// ============ EXAMS API ============
export type BloomLevel = 'nhan_biet' | 'thong_hieu' | 'van_dung' | 'van_dung_cao'
export type QuestionType = 'mcq' | 'essay' | 'dung_sai' | 'short_answer'
export type ExamStatus = 'draft' | 'ready_for_review' | 'regenerating' | 'published'

export interface DungSaiProposition {
  label: string
  text: string
  is_correct: boolean
}

export interface RubricItem {
  score: number | string
  description: string
}

export interface Question {
  id: string
  question_number?: number
  question_type?: string
  type?: string
  content: string
  options?: Array<{ label: string; text: string }>
  propositions?: DungSaiProposition[]
  correct_answer?: string
  unit?: string
  solution?: string
  rubric?: RubricItem[] | Record<string, unknown> | string
  explanation?: string
  bloom_level?: BloomLevel | string
  difficulty_score?: number
  chapter?: string
  scope_tags?: string[]
  quality_score?: number
  source_citations?: string[]
  warnings?: string[]
  validation_warnings?: string[]
  verification_status?: string
  is_human_edited?: boolean
  is_locked?: boolean
  is_validated?: boolean
  created_at?: string
  blueprint_cell_key?: string
  source_evidence?: Array<{
    chunk_id?: string
    document_id?: string
    section_id?: string
    chapter_number?: number
    page?: number
    parent_heading?: string
    text_preview?: string
    score?: number
    role?: string
  }>
}

export interface Exam {
  id: string
  title?: string
  exam_type?: string
  status?: string
  document_id?: string
  chapters?: string[]
  chapters_num?: number[]
  course_id?: string
  difficulty?: string
  variant_number?: number
  total_questions?: number
  instructions?: string
  output_language?: string
  strict_scope_flag?: boolean
  mcq_count?: number
  essay_count?: number
  bloom_distribution?: Record<BloomLevel, number>
  questions?: Question[]
  blueprint?: BlueprintSlot[]
  quality_score?: number
  verifier_pass_rate?: number
  evidence_coverage_rate?: number
  warning_count?: number
  cost_report?: {
    total_cost_usd: number
    total_tokens: number
  }
  created_at: string
  updated_at?: string
  published_at?: string
  exam_spec?: Record<string, unknown>
  selected_scope?: Array<Record<string, unknown>>
  quality_scores?: Array<Record<string, unknown>>
  grounding_reports?: Array<Record<string, unknown>>
  edit_impact_level?: string
  edit_history?: Array<Record<string, unknown>>
  feedback_events?: Array<Record<string, unknown>>
  current_version?: Record<string, unknown>
  versions?: Array<Record<string, unknown>>
}

export interface ExamListResponse {
  items: Exam[]
  total: number
  page: number
  limit: number
}

export interface ExamGenerationRequest {
  document_id?: string | null
  use_builtin_knowledge?: boolean
  knowledge_namespace?: string | null  // Pinecone namespace for admin-uploaded textbook
  scope: string[]
  exam_type?: 'mcq' | 'essay' | 'mixed'
  exam_mode?: 'standard' | 'thpt_2025'
  mcq_count?: number
  essay_count?: number
  dung_sai_count?: number
  short_answer_count?: number
  bloom_distribution?: Record<BloomLevel, number>
  user_prompt?: string
  extra_instructions?: string
  strict_scope_flag?: boolean
  title?: string
}

export interface BlueprintSlot {
  question_id: string
  question_type?: string
  type?: string
  bloom_level?: string
  chapter?: string
  scope_tags?: string[]
  topic_hint?: string
  content_type?: string
  estimated_difficulty?: number
  [key: string]: unknown
}

export interface ExamVersion {
  id: string
  version_number: number
  change_type: 'generate' | 'edit_direct' | 'edit_prompt' | 'regenerate' | 'published' | 'restore'
  change_description: string
  created_at: string
  status?: string
  created_by?: string
  parent_version_id?: string
  questions?: unknown[]
  edit_operations?: unknown[]
  feedback_events?: unknown[]
}

export interface QualitySummary {
  total_exams: number
  avg_quality_score: number
  avg_verifier_pass_rate: number
  avg_evidence_coverage_rate: number
  warning_count: number
  timeline: Array<{
    date: string
    quality_score: number
    pass_rate: number
  }>
}

export const examsApi = {
  list: async (page = 1, limit = 20, status?: ExamStatus): Promise<ExamListResponse> => {
    let url = `/exams/?page=${page}&limit=${limit}`
    if (status) url += `&status=${status}`
    const token = getToken()
    const headers: HeadersInit = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`

    const response = await fetch(`${API_BASE_URL}${url}`, { headers })
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Có lỗi xảy ra' }))
      throw new Error(error.detail || error.message || 'Có lỗi xảy ra')
    }
    const items: Exam[] = await response.json()
    const total = parseInt(response.headers.get('total-count') ?? String((items ?? []).length), 10)
    return { items: items ?? [], total, page, limit }
  },
  
  get: async (id: string): Promise<Exam> => {
    return apiFetch<Exam>(`/exams/${id}`)
  },
  
  delete: async (id: string): Promise<void> => {
    await apiFetch(`/exams/${id}`, { method: 'DELETE' })
  },
  
  getVersions: async (id: string): Promise<ExamVersion[]> => {
    return apiFetch<ExamVersion[]>(`/exams/${id}/versions`)
  },
  
  getHistory: async (id: string): Promise<ExamVersion[]> => {
    return apiFetch<ExamVersion[]>(`/exams/${id}/history`)
  },
  
  restoreVersion: async (examId: string, historyId: string): Promise<void> => {
    await apiFetch(`/exams/${examId}/history/${historyId}/restore`, { method: 'POST' })
  },
  
  updateQuestion: async (
    examId: string,
    questionId: string,
    data: Partial<Question>
  ): Promise<Question> => {
    return apiFetch<Question>(`/exams/${examId}/questions/${questionId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    })
  },
  
  editPrompt: async (examId: string, instruction: string): Promise<void> => {
    await apiFetch(`/exams/${examId}/edit-prompt`, {
      method: 'POST',
      body: JSON.stringify({ instruction }),
    })
  },
  
  regenerate: async (examId: string, questionIds?: string[]): Promise<void> => {
    await apiFetch(`/exams/${examId}/regenerate`, {
      method: 'POST',
      body: JSON.stringify({ question_ids: questionIds }),
    })
  },
  
  publish: async (examId: string): Promise<void> => {
    await apiFetch(`/exams/${examId}/publish`, { method: 'POST' })
  },
  
  approveBlueprint: async (examId: string): Promise<void> => {
    await apiFetch(`/exams/${examId}/approve-blueprint`, {
      method: 'POST',
      body: JSON.stringify({ approved: true }),
    })
  },
  
  rejectBlueprint: async (examId: string, feedback: string): Promise<void> => {
    if (!feedback || feedback.trim().length < 5) {
      throw new Error('Feedback phải có ít nhất 5 ký tự')
    }
    await apiFetch(`/exams/${examId}/reject-blueprint`, {
      method: 'POST',
      body: JSON.stringify({ feedback: feedback.trim() }),
    })
  },
  
  submitReview: async (
    examId: string,
    data: { approved: boolean; feedback?: string; direct_edits?: Record<string, unknown>[] }
  ): Promise<void> => {
    await apiFetch(`/exams/${examId}/submit-review`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  partialRegenerate: async (
    examId: string,
    data: { question_id: string; prompt?: string }
  ): Promise<{ question: Question; question_id: string }> => {
    return apiFetch<{ question: Question; question_id: string }>(
      `/exams/${examId}/partial-regenerate`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    )
  },

  getReviewData: async (examId: string): Promise<{ blueprint: BlueprintSlot[]; questions: Question[] }> => {
    return apiFetch(`/exams/${examId}/review-data`)
  },

  exportPdf: async (examId: string, includeAnswers = true): Promise<Blob> => {
    const token = getToken()
    const response = await fetch(
      `${API_BASE_URL}/exams/${examId}/export/pdf?include_answers=${includeAnswers}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }
    )
    if (!response.ok) throw new Error('Export PDF thất bại')
    return response.blob()
  },

  exportDocx: async (examId: string, includeAnswers = true): Promise<Blob> => {
    const token = getToken()
    const response = await fetch(
      `${API_BASE_URL}/exams/${examId}/export/docx?include_answers=${includeAnswers}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }
    )
    if (!response.ok) throw new Error('Export DOCX thất bại')
    return response.blob()
  },

  getQualitySummary: async (): Promise<QualitySummary> => {
    return apiFetch<QualitySummary>('/exams/quality-summary')
  },
}

// ============ FEEDBACK API ============
export interface FeedbackEvent {
  id: string
  exam_id: string
  exam_title: string | null
  timestamp: string
  signal_type: 'bloom_mismatch' | 'out_of_scope' | 'duplicate' | 'quality_low' | 'answer_incorrect' | 'validation_warning' | 'generation_error' | 'publish' | 'edit_applied'
  description: string
  resolved: boolean
  severity?: string
  review_status?: string
  question_id?: string | null
  error_categories?: string[]
  created_at?: string
}

export interface FeedbackStoreResponse {
  items: FeedbackEvent[]
  total: number
  page: number
  limit: number
}

export const feedbackApi = {
  list: async (
    page = 1,
    limit = 50,
    signalType?: string,
    reviewStatus?: string
  ): Promise<FeedbackStoreResponse> => {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) })
    if (signalType) params.set('signal_type', signalType)
    if (reviewStatus) params.set('review_status', reviewStatus)
    return apiFetch<FeedbackStoreResponse>(`/exams/feedback-store?${params}`)
  },
}

// ============ GENERATION API ============
export interface GenerationResponse {
  exam_id: string
  websocket_url: string
  scope_warning?: string
}

export const generateApi = {
  startGeneration: async (data: ExamGenerationRequest): Promise<GenerationResponse> => {
    return apiFetch<GenerationResponse>('/generate/exam', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  // TODO: Add partial regenerate UI using generateApi.partialRegenerate()
  partialRegenerate: async (request: {
    exam_id: string
    edits: Array<
      | { action: 'delete'; question_id: string }
      | { action: 'lock'; question_id: string }
      | { action: 'edit_text'; question_id: string; content: string }
      | { action: 'edit_answer'; question_id: string; correct_answer: string }
      | { action: 'edit_bloom'; question_id: string; bloom_level: BloomLevel }
      | { action: 'edit_options'; question_id: string; options: Record<string, string> }
    >
  }): Promise<void> => {
    await apiFetch('/generate/partial-regenerate', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  },
}

// ============ ADMIN API ============
export const adminApi = {
  getUsers: async (page = 1, limit = 20): Promise<{ items: UserResponse[]; total: number }> => {
    return apiFetch<{ items: UserResponse[]; total: number }>(`/admin/users?page=${page}&limit=${limit}`)
  },

  getNamespaces: async (): Promise<string[]> => {
    const res = await apiFetch<{ namespaces: string[] }>('/admin/knowledge/namespaces')
    return res.namespaces
  },

  getChapters: async (namespace: string): Promise<string[]> => {
    const res = await apiFetch<{ namespace: string; chapters: string[] }>(`/admin/knowledge/chapters?namespace=${encodeURIComponent(namespace)}`)
    return res.chapters
  },

  getOutline: async (namespace: string): Promise<{ chapter: string; sections: string[] }[]> => {
    const res = await apiFetch<{ namespace: string; outline: { chapter: string; sections: string[] }[] }>(`/admin/knowledge/outline?namespace=${encodeURIComponent(namespace)}`)
    return res.outline
  },

  uploadKnowledge: async (namespace: string, file: File): Promise<{ message: string; items_saved: number; chunks_embedded: number }> => {
    const token = getToken()
    const formData = new FormData()
    formData.append('namespace', namespace)
    formData.append('file', file)

    const response = await fetch(`${API_BASE_URL}/admin/knowledge/textbook`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload thất bại' }))
      throw new Error(error.detail || 'Upload thất bại')
    }

    return response.json()
  },
}

// ============ WEBSOCKET EVENTS ============
export type WSEventType =
  | 'plan_step'
  | 'question_generated'
  | 'validation_result'
  | 'hitl_checkpoint'
  | 'completed'
  | 'error'
  | 'clarification_needed'
  | 'pipeline_paused'

export interface WSEvent {
  type: WSEventType
  step?: number
  total_steps?: number
  message?: string
  question_id?: string
  question?: Question
  passed?: boolean
  issues_count?: number
  issues?: Array<{ type: string; message: string }>
  checkpoint_id?: number
  data?: unknown
  exam_id?: string
  total_cost_usd?: number
  agent?: string
  questions?: string[]
  reason?: string
}

// ── WebSocket URL helper ────────────────────────────────────────────────────
function getWebSocketUrl(examId: string): string {
  if (typeof window === 'undefined') {
    return `ws://localhost:8000/ws/exam/${examId}`
  }
  const wsBaseUrl = process.env.NEXT_PUBLIC_WS_URL || ''
  if (wsBaseUrl) {
    return `${wsBaseUrl}/${examId}`
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const hostname = window.location.hostname
  // In dev (port 3000/3001/...), always route to backend on port 8000.
  // In production, use the same host as the page.
  const backendPort = (hostname === 'localhost' || hostname === '127.0.0.1') ? '8000' : window.location.port
  return `${protocol}//${hostname}:${backendPort}/ws/exam/${examId}`
}

export function createExamWebSocket(
  examId: string,
  onEvent: (event: WSEvent) => void,
  onError?: (error: Event) => void,
  onClose?: () => void
): WebSocket {
  let ws: WebSocket | undefined
  let reconnectAttempts = 0
  const MAX_RECONNECT_ATTEMPTS = 5
  const BASE_RECONNECT_DELAY = 1000

  const connect = () => {
    const wsUrl = getWebSocketUrl(examId)
    ws = new WebSocket(wsUrl)

    ws.onmessage = async (event) => {
      try {
        const raw = event.data instanceof Blob
          ? await event.data.text()
          : event.data
        const data = JSON.parse(raw) as WSEvent
        onEvent(data)
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
      onError?.(error)
    }

    ws.onclose = (event) => {
      console.log('WebSocket closed:', event.code, event.reason)
      onClose?.()
      if (event.code !== 1000 && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++
        const delay = BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttempts - 1)
        console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`)
        setTimeout(connect, delay)
      } else if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        console.error('Max reconnect attempts reached')
      }
    }
  }

  connect()
  return ws!
}

// ============ PARTIAL REGENERATE API (FIX 10) ============
export type PartialEditAction =
  | { action: 'delete'; question_id: string }
  | { action: 'lock'; question_id: string }
  | { action: 'edit_text'; question_id: string; content: string }
  | { action: 'edit_answer'; question_id: string; correct_answer: string }
  | { action: 'edit_bloom'; question_id: string; bloom_level: BloomLevel }
  | { action: 'edit_options'; question_id: string; options: Record<string, string> }

export interface PartialRegenerateRequest {
  exam_id: string
  edits: PartialEditAction[]
}

// ============ DOCUMENT UPLOAD WEBSOCKET HELPERS ============

export type DocumentUploadEventType =
  | 'upload_progress'
  | 'processing_step'
  | 'processing_completed'
  | 'processing_failed'

export interface DocumentUploadEvent {
  type: DocumentUploadEventType
  document_id: string
  percent?: number
  step?: string
  message?: string
  filename?: string
  error?: string
}

function getDocumentWsUrl(documentId: string): string {
  if (typeof window === 'undefined') {
    return `ws://localhost:8000/ws/document/${documentId}`
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const hostname = window.location.hostname
  const port = (hostname === 'localhost' || hostname === '127.0.0.1') ? '8000' : window.location.port
  return `${protocol}//${hostname}:${port}/ws/document/${documentId}`
}

export function createDocumentUploadWebSocket(
  documentId: string,
  onEvent: (event: DocumentUploadEvent) => void,
  onError?: (error: Event) => void,
  onClose?: () => void
): WebSocket | null {
  if (typeof window === 'undefined') return null

  let ws: WebSocket | undefined
  try {
    const wsUrl = getDocumentWsUrl(documentId)
    ws = new WebSocket(wsUrl)
  } catch {
    return null
  }

  ws.onmessage = async (event) => {
    try {
      const raw = event.data instanceof Blob
        ? await event.data.text()
        : event.data
      const data = JSON.parse(raw) as DocumentUploadEvent
      onEvent(data)
    } catch (e) {
      console.error('Failed to parse upload WebSocket message:', e)
    }
  }

  ws.onerror = (error) => {
    console.error('Document upload WebSocket error:', error)
    onError?.(error)
  }

  ws.onclose = (event) => {
    onClose?.()
    if (event.code !== 1000) {
      console.log('Document upload WebSocket closed unexpectedly:', event.code)
    }
  }

  return ws
}

export interface UploadProgress {
  documentId: string
  filename: string
  uploadPercent: number
  processingStep: string
  processingPercent: number
  message: string
  status: 'uploading' | 'processing' | 'completed' | 'failed'
}

export function uploadWithProgress(
  file: File,
  onProgress: (uploadPercent: number) => void
): Promise<Document> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100)
        onProgress(percent)
      }
    })

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const doc = JSON.parse(xhr.responseText) as Document
          resolve(doc)
        } catch {
          reject(new Error('Invalid response from server'))
        }
      } else {
        try {
          const err = JSON.parse(xhr.responseText)
          reject(new Error(err.detail || 'Upload thất bại'))
        } catch {
          reject(new Error(`Upload thất bại (status ${xhr.status})`))
        }
      }
    })

    xhr.addEventListener('error', () => {
      reject(new Error('Upload thất bại — không thể kết nối server'))
    })

    xhr.addEventListener('abort', () => {
      reject(new Error('Upload bị hủy'))
    })

    const formData = new FormData()
    formData.append('file', file)

    const token = getToken()
    xhr.open('POST', `${API_BASE_URL}/documents/upload`)
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    }

    xhr.send(formData)
  })
}
