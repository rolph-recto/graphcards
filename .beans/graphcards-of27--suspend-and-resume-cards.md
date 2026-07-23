---
# graphcards-of27
title: Suspend and resume cards
status: completed
type: feature
priority: high
created_at: 2026-07-23T21:30:18Z
updated_at: 2026-07-25T01:21:07Z
---

Add an explicit suspension control that removes a card from due, practice, and ahead queues without deleting its FSRS schedule or review history. Show suspension state in status views and make sync preserve it when a card reappears. Approved decisions: suspension is per deck membership; reasons are optional current-state text and are not review history; both CLI and browser controls are included.

## Implementation

- [x] Add schema v4 and migrate v3 state without resetting schedules or reviews
- [x] Add suspension persistence, sync preservation, queue exclusion, and review guards
- [x] Add status counts, filters, and CLI suspend/resume controls
- [x] Add browser status and study-session controls
- [x] Add migration, repository, CLI, and browser behavior tests
- [x] Document suspension semantics and schema v4
- [x] Pass pytest, Ruff, formatting, build, and final worktree inspection

## Summary of Changes

Implemented per-deck card suspension with optional current reasons, schema v4 and atomic v3 migration, sync preservation, exclusion from due/practice/forgotten/ahead queues, guarded reviews, available/suspended status counts and filters, CLI suspend/resume commands, browser status and study controls, comprehensive behavior tests, and documentation.

## Merge Notes

Merged into main in commit 061ce35. Added a follow-up compatibility fix for stale browser rating submissions in commit 08daa1f so deleted cards still produce the actionable conflict response while availability refresh remains active for reveal and suspension actions. The bean is ready for implementation follow-up or review.
