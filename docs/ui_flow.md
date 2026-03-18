# UI Flow

## Active navigation

- Dashboard
- Courses & Documents
- Generate Exam
- Exam History
- Exam Review (`/dashboard/exams/[id]`)
- Settings

## Active user journey

1. Upload a PDF on the documents page.
2. Wait for parsing, sectioning, and indexing to complete.
3. Inspect the curriculum tree for the document.
4. Open the generate page.
5. Select a document and one or more scope units.
6. Enter the teacher request and optional exam instructions.
7. Generate the exam.
8. Review verifier results, source evidence, and feedback signals.
9. Edit or regenerate questions.
10. Save new versions and publish when ready.

## Hidden / removed from the active UI

- textbooks naming and routes
- guidance pages
- advanced export flows
- essay or mixed exam controls
- strict scope toggles
- multi-language selectors

## Manual check checklist

Use this when frontend automation is not available yet:

1. Open `/dashboard/documents` and confirm only document-first wording is visible.
2. Upload a PDF and confirm the detail dialog shows curriculum-tree readiness.
3. Open `/dashboard/generate` and confirm generation is blocked until at least one scope unit is selected.
4. Generate an exam and confirm the review page shows:
   - source evidence
   - verifier warnings/status
   - version selector
   - regenerate actions
   - edit actions
   - feedback signals
5. Open `/dashboard/history` and confirm only active actions remain.
6. Open `/dashboard/settings` and confirm runtime constraints are read-only.
