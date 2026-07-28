---
# graphcards-koc7
title: Rework web deck info into status, history, and exercise-generator tabs
status: completed
type: feature
priority: normal
created_at: 2026-07-28T18:48:05Z
updated_at: 2026-07-28T23:39:36Z
---

Rework the web deck information interface into separate status, review-history, and exercise-generator tabs.

## Requirements

- [x] Remove the Reason input/control from browser card suspension while keeping suspend/resume functional.
- [x] Remove the Review History Apply button and refresh immediately on date-range changes.
- [x] Rename View card status to View Deck Info.
- [x] Split deck information into independent Card Status, Review History, and Exercise Generators tabs with active-tab preservation.
- [x] Card Status shows entity IDs, associated generator IDs/types, and per-entity Generate exercise previews.
- [x] Exercise Generators lists every configured generator, including those without due cards, shows useful metadata, and supports non-persistent random previews.
- [x] Validate deck/card/generator ownership and handle stale, unknown, and targetless requests with repository-standard user-facing errors.
- [x] Preserve behavior outside this feature and add comprehensive browser behavior tests.
- [x] Run focused web tests and all repository quality gates.

## Implementation plan

- [x] Audit web routes, templates, status/history contexts, suspension forms, identity formatting, generator registry, and rendering APIs.
- [x] Define page context and validated preview action inputs.
- [x] Implement the tabbed information page and control cleanup.
- [x] Implement card- and generator-level random previews through the normal renderer without mutation.
- [x] Add behavior and regression tests for labels, tabs, controls, range updates, IDs, listings, previews, invalid inputs, tab state, and non-mutation.
- [x] Run independent behavioral, test/regression, error/security, and quality reviews; fix actionable findings until clean.
- [x] Update this bean with a Summary of Changes, mark completed, and commit only scoped implementation changes plus this bean.

## Product behavior

Exercise previews are non-persistent: they do not create reviews, alter FSRS state, suspend cards, or advance study queues. User-facing identifiers use entity IDs; internal card keys remain implementation details. Existing persisted suspension reasons are retained for compatibility but are no longer requested or displayed by the browser control.

## Summary of Changes

- Reworked Deck Info into independent Card Status, Review History, and Exercise Generators tabs with URL-preserved tab/range state.
- Removed browser suspension reasons, added entity/generator metadata, and added stateless random previews using normal deck rendering with isolated RNG and ownership validation.
- Added CSP-compatible immediate history refresh with a no-script fallback, accessible history bars, documentation, and comprehensive web regressions including invalid requests and non-mutation.
- Fixed history streaks to respect the selected date range.
- Verified focused web tests, 247 full tests with warnings as errors, Ruff lint, Ruff formatting, uv build, diff checks, and two independent review rounds with actionable findings fixed until clean.


## Consolidated Follow-up Changes

- Added validated card/entity detail pages with per-generator non-persistent previews.
- Moved generator previews into shared right-side panels on the Exercise Generators and card detail pages, preserving unchanged generator sections and responsive layout.
- Refined Card Status into compact entity, review history, next review, Schedule, FSRS Status, and Actions columns while preserving the user’s subsequent template refinements.
- Kept More details and Suspend/Resume behavior functional and compacted table/button spacing.
- Removed duplicate FSRS state badges from Schedule; FSRS state is shown only in FSRS Status.
- Added regression coverage for previews, ownership, non-mutation, table structure, action states, and FSRS badge separation.
