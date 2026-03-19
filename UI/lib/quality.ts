import type { EditOperation, Exam, ExamVersion, FeedbackEvent, Question } from "@/lib/api"

export function formatPercent(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A"
  return `${(value * 100).toFixed(1)}%`
}

export function countVerifierWarnings(questions: Question[]): number {
  return questions.reduce((total, question) => total + (question.warnings?.length || 0), 0)
}

export function countEvidenceCoverage(questions: Question[]): number {
  return questions.filter((question) => (question.source_evidence?.length || 0) > 0).length
}

export function getVerifierPassRate(questions: Question[]): number {
  if (questions.length === 0) return 0
  return questions.filter((question) => question.verification_status === "passed").length / questions.length
}

export function getEvidenceCoverageRate(questions: Question[]): number {
  if (questions.length === 0) return 0
  return countEvidenceCoverage(questions) / questions.length
}

export function feedbackTargetsQuestion(event: FeedbackEvent, questionId: string): boolean {
  if (event.question_id === questionId) return true
  const payload = event.payload || {}
  const targetIds = Array.isArray(payload.target_question_ids) ? payload.target_question_ids : []
  return targetIds.some((value) => String(value) === questionId)
}

export function getQuestionFeedbackEvents(version: ExamVersion | null | undefined, questionId: string): FeedbackEvent[] {
  if (!version) return []
  return (version.feedback_events || []).filter((event) => feedbackTargetsQuestion(event, questionId))
}

export function getPlaybookShadowEvents(events: FeedbackEvent[]): FeedbackEvent[] {
  return events.filter((event) => event.signal_type === "playbook_shadow")
}

export function countFeedbackBySignal(events: FeedbackEvent[], signal: string): number {
  return events.filter((event) => event.signal_type === signal).length
}

export function getQuestionEditOperations(version: ExamVersion | null | undefined, question: Question): EditOperation[] {
  if (!version) return []
  return (version.edit_operations || []).filter((operation) => {
    if (operation.target_question_id === question.id) return true
    if ((operation.target_slots || []).includes(question.question_number)) return true
    return false
  })
}

export function getLatestVersion(exam: Exam | null): ExamVersion | null {
  if (!exam) return null
  if (exam.current_version) return exam.current_version
  const versions = exam.versions || []
  if (versions.length === 0) return null
  return versions.reduce((latest, current) =>
    current.version_number > latest.version_number ? current : latest,
  )
}

export function getVersionChurn(exam: Exam | null): number {
  const latestVersion = getLatestVersion(exam)
  return Math.max((latestVersion?.version_number || 1) - 1, 0)
}

export function humanReadableSignal(signal: string): string {
  return signal.replaceAll("_", " ")
}

export function humanReadableCategory(category: string): string {
  return category.replaceAll("_", " ")
}
