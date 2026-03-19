# Evaluation

Phase 4 keeps the **Phase 3 eval workflow** active and treats it as one of the main inputs into ACE foundation.

## Dataset layout

- Root: `backend/evals/datasets/physics/`
- Dev set: `backend/evals/datasets/physics/dev/`
- Held-out set: `backend/evals/datasets/physics/held_out/`
- Sample template: `backend/evals/datasets/physics/sample_template.json`
- Archived Phase 2 sample: `backend/evals/archive/phase2/physics_phase2_eval.json`

## Primary commands

From `backend/`:

```bash
conda activate graduation
python evals/run_phase3_eval.py --split dev
python evals/run_phase3_eval.py --split held_out
python evals/run_phase3_eval.py --split all --json-out evals/output/phase3_report.json --csv-out evals/output/phase3_questions.csv
python evals/run_error_analysis.py --split all --json-out evals/output/error_analysis.json
```

## Why it matters in Phase 4

- eval metrics still tell us where retrieval, generation, verifier behavior, and human friction are weak
- eval outputs now feed reflection candidates and playbook curation
- `linked_eval_sample_id` can be stored on feedback events when a runtime issue is tied back to a known eval case

## Related docs

- `phase3_eval_workflow.md`
- `error_analysis.md`
- `data_curation.md`
- `ace_foundation.md`
- `playbook_model.md`
