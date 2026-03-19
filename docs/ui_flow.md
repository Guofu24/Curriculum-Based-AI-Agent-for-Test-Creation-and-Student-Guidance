# UI Flow

## Active navigation

- Quality Dashboard
- Documents
- Generate
- History
- Playbook
- Feedback
- Exam Review (`/dashboard/exams/[id]`)
- Settings

## Active Phase 4 journey

1. Upload a PDF on the documents page.
2. Wait for parsing, sectioning, and indexing to complete.
3. Inspect the curriculum tree and document readiness.
4. Open the generate page and pick a scoped slice of the document.
5. Enter the teacher request and optional exam instructions.
6. Generate the exam.
7. Review verifier signals, source evidence, playbook shadow hints, and version metrics.
8. Inspect question-level feedback activity, warnings, and evidence gaps.
9. Open `/dashboard/feedback` to inspect the normalized event stream.
10. Open `/dashboard/playbook` to inspect approved bullets, reflection candidates, and warmup preview counts.
11. Promote or reject candidates without pretending the runtime is already adaptive.
12. Publish when review is acceptable.

## What the UI now emphasizes

- system quality state, not just generation success
- feedback store quality and queryability
- candidate vs approved playbook separation
- playbook retrieval mode: `off`, `shadow`, or `limited`
- evidence visibility per question
- regenerate and edit history
- version churn and feedback summaries

## Manual check checklist

1. Open `/dashboard` and confirm the summary cards show both quality metrics and playbook foundation state.
2. Open `/dashboard/documents` and confirm the copy stays document-first and scope-readiness focused.
3. Open `/dashboard/generate` and confirm the page still emphasizes evidence grounding and traceability.
4. Generate an exam and confirm `/dashboard/exams/[id]` shows:
   - source evidence
   - verifier warnings
   - version metrics
   - question activity
   - playbook shadow hints when available
5. Open `/dashboard/history` and confirm the page still surfaces churn, edits, warnings, and feedback volume.
6. Open `/dashboard/playbook` and confirm approved bullets and reflection candidates are clearly separated.
7. Open `/dashboard/feedback` and confirm the store can be filtered by stage and signal type.
8. Open `/dashboard/settings` and confirm it describes Phase 4 foundation flags instead of generic profile controls.
