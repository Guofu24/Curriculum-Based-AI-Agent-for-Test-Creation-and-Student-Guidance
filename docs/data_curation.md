# Data Curation

## Goal

Phase 3 eval data should help internal development, not just pad sample counts.

## Split policy

- Put fast-iteration cases in `backend/evals/datasets/physics/dev/`.
- Put confidence-check cases in `backend/evals/datasets/physics/held_out/`.
- Do not duplicate the same sample across both splits.

## Adding a new sample

1. Copy `backend/evals/datasets/physics/sample_template.json`.
2. Give it a stable `sample_id`.
3. Point it to a real document reference.
4. Define the selected scope and allowed section IDs.
5. Add question rows with evidence, retrieval, verifier expectation, and review friction fields when available.
6. Place it in `dev/` or `held_out/`.
7. Re-run `python evals/run_phase3_eval.py --split all`.

## Minimum useful fields

- `document.document_id`
- `scope.selected_scope`
- `scope.allowed_section_ids`
- `exam_request` or `normalized_spec`
- `questions[].retrieval`
- `questions[].source_evidence`
- `questions[].verification_status`
- `questions[].verifier_expectation`

## Good sample design

- Cover more than one chapter family over time.
- Include both clean passes and realistic failures.
- Include at least some cases with human edits or regenerate counts.
- Prefer samples that isolate one main weakness instead of mixing everything into one row.
