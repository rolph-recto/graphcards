---
# graphcards-wv8e
title: Add undo for the last review
status: todo
type: task
priority: high
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:57Z
updated_at: 2026-07-31T17:23:54Z
parent: graphcards-gwut
---

Allow a learner to undo the last persisted review.

## Plan

- [ ] Inspect the FSRS card JSON and review row data.
- [ ] Add a transaction that restores the previous card state and removes or marks the last review.
- [ ] Add service, route, and study-page actions.
- [ ] Reject stale, repeated, and non-last undo requests.
- [ ] Add tests for rating, undo, restart, duplicate requests, and corrupt state.
- [ ] Run the project validation commands.

## Acceptance checks

- The last review can be undone once.
- The card schedule and review history return to the prior state.
- A stale undo returns a safe user-facing error.

## Detailed implementation plan

### 1. Define the undo contract

- [ ] Define the last review as the review row with the greatest reviews.id in the repository.
- [ ] Use the row ID for order. Do not use the review timestamp for order.
- [ ] Reject an older review, including a review for another card, as a non-last review.
- [ ] Define undo as a one-shot action. A second request for the same row must fail.
- [ ] Use a frozen Pydantic v2 model for a review receipt. Include the review ID, card key, pre-review card JSON, post-review card JSON, and prior card update time.
- [ ] Return the receipt with the reviewed card from StudyService.review. Update current callers to use the new result shape.

### 2. Persist the state that undo needs

Affected module: src/graphcards/storage.py.

- [ ] Add snapshot columns to reviews: pre-review card JSON, post-review card JSON, and prior updated_at.
- [ ] Require all three values for new review rows. Validate them with the existing stored-card and timestamp checks.
- [ ] Capture the old card row before the card update. Write the card update and the review row in one transaction.
- [ ] Make save_review return the new review ID and its receipt. Keep the card due mirror equal to the post-review FSRS card.
- [ ] Add Repository.latest_undoable_review to read the newest review and validate its snapshot.
- [ ] Add Repository.undo_last_review. Start an immediate SQLite transaction. Check the requested row, the global maximum review ID, the card key, and the current post-review JSON.
- [ ] Restore the pre-review JSON, its due mirror, and its prior update time. Delete the newest review row in the same transaction.
- [ ] Keep deck membership and suspension fields unchanged. Do not use a soft delete because current history and status queries treat every row as an active review.
- [ ] Check update and delete row counts. Roll back on every validation, SQLite, or snapshot failure.

### 3. Update schema handling

Affected module: src/graphcards/storage.py.

- [ ] Raise SCHEMA_VERSION from 7 to 8.
- [ ] Add the new columns to the fresh database schema.
- [ ] Add one v7 to v8 migration. Use nullable columns for old rows that have no snapshots.
- [ ] Keep old review history readable. Return a safe undo-unavailable error for an old row with missing snapshots.
- [ ] Keep the new application API focused on the new result shape. Do not add a broad old-API compatibility layer.
- [ ] Add one migration smoke test if the migration is implemented. Do not add a legacy compatibility test matrix.

### 4. Add service and session actions

Affected modules: src/graphcards/app.py, src/graphcards/web/study.py, and src/graphcards/errors.py.

- [ ] Add an UndoUnavailableError storage error for stale, repeated, missing, or non-last undo requests. Keep corrupt JSON and corrupt timestamps as StorageError.
- [ ] Add StudyService.undo_last_review as the service boundary for the repository undo operation.
- [ ] Store the pre-rating session position, card view, counters, card identity, and review receipt after a successful rating.
- [ ] Add StudySession.undo. Check the session token, review ID, entity ID, and the stored undo candidate before the service call.
- [ ] Restore the reviewed card at its old position after a successful undo. Show the answer so the learner can rate the card again.
- [ ] Clear the undo candidate after a successful undo or after another action advances the session. A new rating creates a new candidate.
- [ ] Keep the current session lifecycle. The session is in memory, but the review snapshot and repository undo operation survive a repository or service restart. Do not accept a page token from a session that no longer exists.

### 5. Add the web endpoint and page action

Affected modules: src/graphcards/web/app.py and src/graphcards/web/templates/study.html.

- [ ] Add a strict Pydantic form model for session_token, entity_id, and a positive review_id.
- [ ] Add POST /study/undo. Add the endpoint to the study-flow allowlist so it does not end the session.
- [ ] Use the existing session token as the study action capability. Do not expose card snapshots in the form.
- [ ] Show an Undo last review form after a successful rating. Show it on the completion view when the last rating ended the queue.
- [ ] Use the existing button styles when possible. If new CSS is needed, edit src/graphcards/web/style.src.css and rebuild the committed stylesheet.
- [ ] Redirect to the study page after success. Return a safe 409 message for stale, repeated, non-last, or changed-card requests.
- [ ] Return 400 for malformed forms and 403 for an invalid session token. Route storage corruption to the existing generic application error without exposing database details.

### 6. Test the behavior

Affected tests: tests/test_integration.py, tests/test_property_storage.py, tests/web/test_study.py, and tests/web/test_property_web.py.

- [ ] Test every FSRS rating: review, undo, exact card JSON and due restoration, and removal of the review from history.
- [ ] Test a card with an earlier review. Undo must restore the earlier schedule and keep the earlier history row.
- [ ] Test a review on a second card. An undo request for the first card must fail as non-last and must not change either card.
- [ ] Test duplicate undo requests. The first request restores once. The second request returns a conflict and makes no change.
- [ ] Close and reopen the repository after a review. Load the persisted latest receipt and undo it successfully.
- [ ] Test the final card in a study session. The completion page must offer undo and return to the restored card.
- [ ] Test that practice, reveal, suspend, and malformed rating actions do not create an undo candidate.
- [ ] Test wrong tokens, wrong entity IDs, wrong review IDs, missing rows, inactive cards, and changed post-review JSON.
- [ ] Corrupt each stored snapshot and timestamp in turn. The operation must raise a storage error, roll back, and keep the card and review row unchanged.
- [ ] Add property tests for rating choices, repeated calls, transaction rollback, and the latest-row rule.
- [ ] Run uv run pytest -W error, uv run ruff check ., uv run ruff format --check ., and uv build. Run the Tailwind command if the template source changes.

## Security and error handling

- [ ] Use Pydantic validation for all form and snapshot fields.
- [ ] Use constant-time comparison for the session token and require the token, entity ID, and review ID to match the in-memory candidate.
- [ ] Never trust a client-supplied snapshot or card schedule.
- [ ] Lock the undo transaction before checking the latest row. This prevents two undo requests from both restoring a card.
- [ ] Keep all expected stale and duplicate cases as controlled 409 responses. Keep corruption as a generic storage failure. Do not include raw SQL, JSON, or filesystem data in a response.

## Definition of done

- [ ] A new review stores enough state to restore the exact previous FSRS schedule.
- [ ] Only the newest persisted review can be undone, and it can be undone once.
- [ ] Undo restores the card schedule, due mirror, update time, and visible review history.
- [ ] Undo works through the repository and service after restart. An old in-memory session token does not work after restart.
- [ ] The study page offers undo after a rating, including after session completion, and lets the learner rate the restored card again.
- [ ] Stale, repeated, non-last, unauthorized, malformed, and corrupt requests make no partial changes.
- [ ] The bean remains todo until implementation and validation finish.
