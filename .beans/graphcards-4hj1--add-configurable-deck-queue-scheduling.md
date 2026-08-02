---
# graphcards-4hj1
title: Add configurable deck queue scheduling
status: completed
type: task
priority: normal
created_at: 2026-08-02T17:18:25Z
updated_at: 2026-08-02T17:45:34Z
parent: graphcards-gwut
---

Add per-deck study-order settings to the Deck status tab. Use supported scheduling choices instead of a free-form queue expression. Persist settings in the state database and apply them to study planning and queue status. Keep preset sharing and temporary Today only overrides out of this task.

## Checklist

- [x] Define validated per-deck scheduling settings.
- [x] Persist settings with deck defaults.
- [x] Add Deck status controls for new/review order.
- [x] Add controls for interday learning/review order.
- [x] Add controls for new-card gather and sort order.
- [x] Add controls for review sort order.
- [x] Apply settings to due-card selection and queue counts.
- [x] Add behavior and web tests.
- [x] Run the required checks.

## Summary of Changes

Added strict per-deck queue scheduling models and deck-file defaults, schema 8 persistence with 7-to-8 migration, queue-aware study planning and status counts, Deck status controls for new/review order, interday learning/review order, new-card gather and sort order, and review sort order. Added behavior and web tests, documentation, and rebuilt the Tailwind stylesheet.

Validation passed: 371 tests, Ruff check, Ruff format check, and uv build.
