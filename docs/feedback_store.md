# Feedback Store

The feedback store is the normalized event layer for ACE foundation.

## Core query keys

- `exam_id`
- `exam_version_id`
- `question_id`
- `signal_type`
- `event_stage`
- `severity`
- `actor_id`
- `source_type`
- `source_ref`
- `review_status`
- `error_categories_json`
- `before_snapshot_ref`
- `after_snapshot_ref`
- `linked_eval_sample_id`
- `created_at`

## Current event families

- retrieval summaries
- verifier warnings / failures
- human edits
- regenerate requests
- publish events
- playbook shadow events

## Why this matters

This is the layer that future ACE workflows should learn from, instead of scraping ad-hoc payloads from multiple services.
