---
# rdfcards-uagj
title: Reject reviews from stale card snapshots
status: completed
type: bug
priority: normal
created_at: 2026-07-23T23:16:32Z
updated_at: 2026-07-23T23:18:22Z
blocking:
    - rdfcards-6xfp
---

Two sessions can review the same StoredCard snapshot. The later save overwrites newer FSRS state while retaining both review rows.

- [x] Make review persistence compare against the source card state
- [x] Raise a repository user-facing error on stale state
- [x] Add a regression test proving the write and review insert are atomic
- [x] Run focused and full validation

## Summary of Changes

Added compare-and-swap review persistence using the exact source card JSON, mapped stale snapshots to StorageError, and added an integration regression proving a rejected stale review leaves both card state and review history unchanged. Focused tests and all required repository validations pass.
