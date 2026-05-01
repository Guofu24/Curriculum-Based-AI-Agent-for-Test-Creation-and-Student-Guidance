# Phase 3 Eval Workflow

## Dataset structure

All active eval samples live under `backend/evals/datasets/physics/`.

- `dev/`: internal tuning set used while changing retrieval, generation, verifier, and review flows
- `held_out/`: reserved set for checking whether changes generalize
- `sample_template.json`: seed schema for new entries

Each sample should include:

- document reference
- selected scope
- exam request or normalized spec
- allowed scope or expected section coverage
- question rows
- evidence hints when available
- verifier expectation when available
- review friction fields such as regenerate count or human edit count

## Running the report

From `backend/`:

```bash
python evals/run_phase3_eval.py --split dev
python evals/run_phase3_eval.py --split held_out
python evals/run_phase3_eval.py --split all --json-out evals/output/phase3_report.json --csv-out evals/output/phase3_questions.csv
```

Console output is intended to answer one question quickly: is the current weakness primarily in scope control, retrieval, evidence, generation, verifier behavior, or review friction?

## Output artifacts

- Console summary: high-signal report for local iteration
- JSON output: full metrics and per-question rows for downstream inspection
- CSV output: flat question-level export for spreadsheet analysis

## Recommended iteration loop

1. Run the dev split after changing retrieval, generator, verifier, or review logic.
2. Inspect the top error categories.
3. Trace the failing sample IDs in the JSON or CSV output.
4. Fix the dominant failure mode.
5. Re-run dev.
6. Check held-out before calling the change stable.
