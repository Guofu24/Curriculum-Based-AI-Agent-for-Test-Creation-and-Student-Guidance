# Playbook Model

## Bullet lifecycle

- `draft`
- `candidate`
- `approved`
- `archived`
- `rejected`

## Bullet fields

- `id`
- `status`
- `title`
- `bullet_type`
- `scope_json`
- `subject`
- `language`
- `question_type`
- `content`
- `rationale`
- `source_signals_json`
- `helpful_count`
- `harmful_count`
- `confidence`
- `tags_json`
- `created_from`
- `review_status`
- `version`
- `archived_at`

## Supported bullet types

- `hard_rule`
- `generation_heuristic`
- `failure_pattern`
- `review_heuristic`
- `verifier_hint`
- `subject_hint`

## Reflection candidates

Reflection candidates live in a separate table so the runtime never confuses:

- a candidate insight
- an approved operational bullet

Candidates can be:

- generated from eval + feedback
- promoted into approved bullets
- rejected
- merged by `merge_key`
