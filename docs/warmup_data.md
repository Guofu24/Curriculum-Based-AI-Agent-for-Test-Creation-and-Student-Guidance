# Warmup Data

Phase 4 prepares an offline export for future ACE warmup.

## Export structure

- `exam_cases`
- `question_cases`
- `feedback_cases`
- `playbook_seed`
- `reflection_candidates`

## Export command

From `backend/`:

```bash
conda activate graduation
python evals/export_warmup_dataset.py --output evals/output/warmup_dataset.json
```

## Intended use

- bootstrap future offline ACE experiments
- inspect which exam versions are stable enough to treat as accepted cases
- join question history with feedback events and playbook seeds

This export is a foundation artifact, not an online learning loop.
