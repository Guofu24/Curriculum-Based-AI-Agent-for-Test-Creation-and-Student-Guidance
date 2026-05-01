# ACE Foundation

Phase 4 is **not** ACE core. It is the layer that makes ACE attach cleanly later.

## Active pieces

- normalized feedback store
- playbook bullet store
- reflection candidates
- offline warmup export
- feature-flagged playbook retrieval

## Runtime stance

- `off`: no playbook retrieval
- `shadow`: log which bullets would attach
- `limited`: attach a small approved set

The runtime is still strict-scope, Physics-only, Vietnamese-only, PDF-only, and MCQ-only.

## Still not active

- autonomous prompt rewriting
- online adaptation loops
- student guidance
- essay runtime
- DOCX/PPTX
- multi-subject orchestration
