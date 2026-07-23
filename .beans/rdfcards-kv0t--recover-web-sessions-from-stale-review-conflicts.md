---
# rdfcards-kv0t
title: Recover web sessions from stale review conflicts
status: completed
type: bug
priority: normal
created_at: 2026-07-23T23:21:12Z
updated_at: 2026-07-23T23:22:57Z
blocking:
    - rdfcards-6xfp
---

A stale web CurrentCard raises StorageError, is rendered as HTTP 500, and remains in the session so reload/retry loops forever.

- [x] Represent stale-review conflicts distinctly from generic storage failures
- [x] Surface the conflict as HTTP 409
- [x] Refresh or invalidate the stale session state so reload recovers
- [x] Add an HTTP regression test
- [x] Run focused and full validation

## Summary of Changes

Added a distinct StaleReviewError storage subtype, translated it to an HTTP 409 at the study-session boundary, refreshed the active StoredCard snapshot while preserving revealed state, and added an end-to-end HTTP regression covering an external review, unchanged conflict history, GET recovery, and successful retry. Focused tests and all required repository validations pass.
