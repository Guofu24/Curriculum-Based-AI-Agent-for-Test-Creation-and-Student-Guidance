# Evaluation

## Goal

Phase 2 adds a lightweight internal evaluation layer so the team can measure quality without introducing ACE.

## Dataset location

- Samples: `backend/evals/samples/physics_phase2_eval.json`
- Runner: `backend/evals/run_phase2_eval.py`

## Metrics

The current runner reports:

- scope violation rate
- evidence coverage rate
- retrieval hit quality
- verifier pass rate
- average regenerate count
- average human edit count

## Run

From `backend/`:

```bash
conda activate graduation
python evals/run_phase2_eval.py
```

Optional custom dataset:

```bash
conda activate graduation
python evals/run_phase2_eval.py --dataset evals/samples/physics_phase2_eval.json
```

## Sample schema

Each sample contains:

- `sample_id`
- `expected_scope_section_ids`
- `questions[]`

Each question can include:

- `question_text`
- `verification_status`
- `source_evidence[]`
- `retrieval.top_section_ids[]`
- `regenerate_count`
- `human_edit_count`

The format is intentionally simple so the team can grow it gradually without locking into a heavy benchmarking framework.
