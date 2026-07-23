---
# rdfcards-c3an
title: Recover web study when current card disappears
status: completed
type: bug
priority: normal
created_at: 2026-07-23T23:26:32Z
updated_at: 2026-07-23T23:28:15Z
blocking:
    - rdfcards-6xfp
---

Deleting a card after a web session starts makes rating return a generic 500, expose the card id, and retain a permanently stale CurrentCard.

- [x] Classify missing source card state as a typed stale-review conflict
- [x] Return a safe HTTP 409 without exposing internal identity
- [x] Recover or advance the session correctly, including when more cards remain
- [x] Add end-to-end HTTP regression coverage
- [x] Run focused and full validation

## Summary of Changes

Classified missing persisted card state as StaleReviewError with a useful CLI-facing reload/sync message. Web session recovery now returns a safe identity-free HTTP 409, records the vanished card as skipped, advances and loads the next card without incrementing completed reviews, and permits the session to continue. Added a multi-card HTTP regression covering deletion after reveal, unchanged history at conflict, next-card rendering, and successful review recovery. Focused tests and all required repository validations pass.
