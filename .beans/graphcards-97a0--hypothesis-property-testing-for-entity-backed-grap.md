---
# graphcards-97a0
title: Hypothesis property testing for entity-backed GraphCards
status: completed
type: task
priority: normal
created_at: 2026-07-28T00:10:44Z
updated_at: 2026-07-28T01:00:07Z
---

Implement the approved Hypothesis property-testing plan against the current entity-backed GraphCards implementation. Preserve graphcards-60os as completed historical work.

- [x] Add shared bounded Hypothesis strategies and deterministic settings.
- [x] Add model and configuration properties with repository-facing validation assertions.
- [x] Convert deck coverage to genuine Hypothesis properties for valid and invalid documents.
- [x] Add bounded storage synchronization, scheduling, serialization, and rollback properties.
- [x] Add bounded status/web filter, malformed-input, security, and lifecycle properties.
- [x] Ensure CI selections reference existing property modules and remain within the timeout.
- [x] Run focused tests, full pytest, ruff, format check, and uv build.
- [x] Run independent review/fix loops until no actionable findings remain.
- [x] Inspect status, append ## Summary of Changes, and commit only scoped changes plus this bean.

No production API or persistence-schema changes are intended unless shrinking exposes a minimal real defect.

## Summary of Changes

- Added bounded deterministic Hypothesis strategies for identities, JSON entity data, deck documents/generators, storage values, datetimes, status queries, tokens, card IDs, and URL/form inputs.
- Added genuine model/config, deck, storage, status/history, malformed-input, security, and study-lifecycle property suites; the dedicated five-file property selection now contains 69 tests.
- Added minimal production hardening exposed by the properties: bounded status query/session inputs, safe web error messages, inactive-membership action protection, review-log referential validation, and controlled concurrent stale-rating conflicts.
- Updated CI to use uv sync --locked and run ruff, format, build, normal tests, and the five-minute Hypothesis job.
- Completed independent behavioral, test-quality, security/error, and CI review/fix loops with no actionable findings remaining.
