---
# graphcards-c20j
title: Deck exercise count should follow tested entities
status: completed
type: bug
priority: normal
created_at: 2026-07-28T00:18:27Z
updated_at: 2026-07-28T00:26:45Z
---

Deck exercise totals should represent the number of entities being tested for a deck, rather than multiplying that entity count by the number of exercise types per entity.

- [x] Locate the count/synchronization behavior and identify the incorrect multiplication
- [x] Implement entity-based exercise counting while preserving generator-specific exercise behavior
- [x] Add regression coverage for multiple exercise types targeting the same entities
- [x] Run quality gates, inspect status, and commit the bean with the implementation

## Summary of Changes

Changed deck generation and regeneration to schedule one exercise per unique targeted entity. Overlapping generators now use the lexicographically smallest generator ID as a stable owner, preventing generator-type multiplication while preserving deterministic identities and rejecting stale non-selected cards. Updated CLI/sync counts, tests, property coverage, README guidance, and the bundled capitals template.

Quality gates: 83 tests passed with `uv run pytest -W error`; `uv run ruff check .`; `uv run ruff format --check .`; and `uv build` passed. Three independent reviewers reported no actionable findings.
