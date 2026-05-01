# Error Analysis

## Purpose

Phase 3 adds a small but explicit error-analysis layer so bad metrics can be traced back to the failing sample and question.

## Categories

The current runner groups failures into:

- `scope_leak`
- `weak_evidence`
- `retrieval_miss`
- `wrong_answer_key`
- `ambiguous_options`
- `duplicate_question`
- `verbatim_copy`
- `verifier_false_pass`
- `verifier_false_fail`

## Commands

From `backend/`:

```bash
python evals/run_error_analysis.py --split dev
python evals/run_error_analysis.py --split all --json-out evals/output/error_analysis.json
```

The console output lists the top categories and a short trace of sample/question IDs under each category.

## Tracing back to source

- For eval datasets, use the sample ID and question ID shown in the error report.
- For runtime feedback, inspect `GET /api/v1/exams/{exam_id}/feedback`.
- In the UI review page, inspect question activity and recent feedback signals for the current version.

## Runtime feedback filters

The feedback inspection endpoint supports:

- `exam_version_id`
- `question_id`
- `signal_type`
- `review_status`
- `limit`
