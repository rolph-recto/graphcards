---
# graphcards-4jfn
title: Add cloze exercise type
status: completed
type: feature
priority: normal
created_at: 2026-07-30T18:29:54Z
updated_at: 2026-07-30T19:40:51Z
---

Implement bean graphcards-wkbv.

- [x] Add cloze models, parsing, generation, and CardKey identity.
- [x] Update storage and web status/detail views.
- [x] Add JSON, TOML, and YAML templates and README documentation.
- [x] Add behavior tests.
- [x] Run required checks.

The requested upstream bean ID is graphcards-wkbv; this local beans store did not contain it.

## Summary of Changes

Added recursive cloze parsing and generation with stable `(entity, cloze_id)` card identities. Updated deck scheduling, storage identity decoding, status/detail previews, documentation, templates, and tests.

Checks passed: `uv run pytest -W error` (322 passed), `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.


## Follow-up: shared cloze scheduling

- [x] Remove cloze ID from CardKey digest.
- [x] Schedule one FSRS card per cloze entity.
- [x] Update tests and documentation.
- [x] Run required checks.


## Follow-up Summary

Cloze IDs no longer affect CardKey digests. Each entity now has one FSRS card, and changing the selected rendered cloze variant reuses that schedule.

Checks passed: `uv run pytest -W error` (324 passed), `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.


## Final Correction

Removed `cloze_id` from the CardKey model and storage identity completely. Cloze IDs remain only in generator selection and semantic rendering payloads.
