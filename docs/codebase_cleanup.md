# Codebase Cleanup

## Active cleanup decisions in Phase 4

Removed because they were unused in the current runtime:

- placeholder image assets under `UI/public/`
- unused toast UI stack under `UI/components/ui/` and `UI/hooks/`
- stale frontend build artifact `UI/tsconfig.tsbuildinfo`
- deprecated Phase 2 hardening script
- old Phase 2 eval sample from the active dataset path

Archived instead of deleted:

- `backend/evals/archive/phase2/physics_phase2_eval.json`
- `docs/architecture_phase2.md` as a historical note

Kept for compatibility only:

- `backend/evals/run_phase2_eval.py`
- document aliases that still map to historical `textbooks` tables

Added in Phase 4 instead of resurrecting legacy code:

- a clean `playbook` router instead of reviving old agent wrappers
- a normalized feedback store query layer instead of overloading dashboard-only helpers
- a warmup export path instead of ad-hoc JSON dumps

## Cleanup rule of thumb

Delete or archive a file only after checking one of:

- import graph
- route wiring
- active UI navigation
- script entrypoints
- test references

If a file is still needed only for compatibility, keep it but label it clearly.
