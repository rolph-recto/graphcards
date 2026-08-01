---
# graphcards-0ql3
title: Add keyboard study and interval previews
status: todo
type: task
priority: high
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:57Z
updated_at: 2026-07-31T17:23:43Z
parent: graphcards-gwut
---

Make the study flow fast with a keyboard and show the next review time.

## Plan

- [ ] Inspect the study template, session state, and FSRS scheduler API.
- [ ] Add a study script for Space, Enter, and keys 1 through 4.
- [ ] Ignore shortcuts while the learner edits text or uses a form control.
- [ ] Show the next interval for each rating before the learner submits it.
- [ ] Prevent repeated shortcut submissions.
- [ ] Add accessible help text and browser tests.
- [ ] Run the project validation commands.

## Acceptance checks

- Space reveals an answer.
- Keys 1 through 4 submit the matching rating.
- Each rating shows its next interval.
- Keyboard use does not submit a form twice.

## Detailed implementation planning

The current plan and its unchecked checklist items remain in place. This section gives the implementation detail.

### Scope and user flow

- Keep the existing study POST forms as the source of truth.
- On `GET /study`, calculate interval previews only for the current revealed review card.
- Show one preview for each FSRS rating: Again, Hard, Good, and Easy.
- Do not show rating previews in a practice session. Show the existing Next action instead.
- Load one same-origin external script, `src/graphcards/web/static/study.js`, on the study template.
- Use Space and Enter to reveal the answer. In a practice session, use Space and Enter to activate Next after the answer is revealed.
- Use keys 1 through 4 for Again through Easy after the answer is revealed.
- Keep the existing form behavior when JavaScript is disabled.

### Data and API design

- Add a small immutable Pydantic v2 preview model. Use the repository FrozenModel base.
- Store the FSRS rating, the projected UTC due time, and the positive projected interval in seconds.
- Keep the human-readable interval label in the web presentation layer. Do not persist the label.
- Add a pure preview operation to `src/graphcards/app.py` on `StudyService`. It must call the configured FSRS scheduler and must not call `Repository.save_review`.
- Project all four ratings from the same validated source card and one captured UTC review time. Use a fresh card snapshot for each projection if the FSRS library can mutate a card.
- Calculate the interval from projected due time minus the captured review time. Preserve the configured FSRS settings, including fuzzing and maximum interval.
- Add a `StudySession` helper in `src/graphcards/web/study.py` that returns no previews before reveal, for practice cards, or when there is no current card.
- Use a small formatter for positive intervals. Cover minutes, hours, days, and years. Use a clear label such as “about 10 minutes” when the scheduler uses fuzzing.
- Add no new route, JSON endpoint, form field, token, or database column. The browser must submit the existing `/study/reveal`, `/study/rate`, and `/study/next` forms.

### Implementation phases and affected modules

1. In `src/graphcards/app.py` and the preview model, implement the non-persistent FSRS projection. Normalize datetimes to UTC. Validate finite, positive intervals with Pydantic. Share the scheduler boundary with the existing review path so the preview and submission use the same FSRS configuration.

2. In `src/graphcards/web/study.py` and `src/graphcards/web/app.py`, prepare the preview view data during the study page request. Use one preview calculation per page render. Keep the current reveal state, session token, card identity, and stale-review checks unchanged.

3. In `src/graphcards/web/templates/study.html`, add the interval text to each rating button. Add stable data attributes for the reveal, next, and four rating buttons. Add `aria-keyshortcuts` values and visible help text. Describe the shortcut scope and state that shortcuts do not run while the learner uses a form control. Keep interval values escaped by Jinja.

4. In `src/graphcards/web/static/study.js`, use a deferred, strict-mode script. Handle `event.key` values for Space, Enter, and 1 through 4. Ignore repeated keydown events, modifier-key combinations, IME composition, already-cancelled events, and targets inside `input`, `textarea`, `select`, `button`, contenteditable elements, or textbox roles. Prevent the default action only for a recognized shortcut. Submit a rating with the existing button and form so the named rating value is preserved.

5. Add a one-submit lock to the study forms. Set the lock before calling `requestSubmit`, disable the relevant buttons, and reject a later submit event from the same page. Keep the server-side reveal, current-card, session-token, and stale-review checks as the final duplicate and replay protection.

6. Use existing Tailwind utilities where possible. If the interval or help layout needs new classes, edit `src/graphcards/web/style.src.css` and rebuild the committed `src/graphcards/web/static/style.css` with the documented command. Verify that the new static JavaScript file is included in the wheel and source distribution.

### Dependencies

- Add no runtime dependency. Reuse the current Flask, Jinja, FSRS 6.3.x, and Pydantic v2 dependencies.
- The repository has no browser-test dependency today. Add a test-only Playwright dependency to the development group, update `uv.lock`, and install a Chromium browser in the CI workflow. Use a temporary threaded Werkzeug server in the browser fixture. Store all test state under `tmp_path`.
- Keep the browser test dependency out of the application package. Do not add a client-side FSRS implementation.

### Migration and compatibility decisions

- No SQLite migration is required. Existing `card_json`, review rows, schedules, and configuration files remain valid.
- Existing sessions, study modes, form actions, CSRF/session tokens, and redirect responses remain compatible.
- The preview is advisory. The later POST remains authoritative. A later review can differ by a small amount because time advances or FSRS fuzzing runs again.
- Do not send the stored card JSON or session token to JavaScript. The script can use the existing hidden form fields through the DOM.
- Scope selectors to the current study controls. Do not bind shortcuts by button text. This leaves room for the daily-limit, review-action, undo, and typed-answer beans to add controls later.
- Keep the page usable without JavaScript. This is progressive enhancement, not a new alternate study API.

### Security and error handling

- Keep the current `script-src 'self'` CSP. Do not add inline JavaScript, inline event handlers, remote scripts, or `eval`.
- Do not add a new CSRF path. Keyboard actions must submit the same hidden session token and entity ID that manual clicks submit.
- Ignore shortcuts in every form control. This prevents a learner from submitting a rating while editing a future typed-answer field or a suspension reason.
- Use `requestSubmit` or an equivalent button-preserving action. Do not use a raw form submission that drops the rating name and value.
- Treat interval data as untrusted view data. Escape it in the template and do not use `safe` for it.
- Translate scheduler projection failures, Pydantic preview validation failures, and corrupt stored-card failures into existing `StorageError` or `RequestFailure` paths. Do not expose FSRS, Pydantic, SQLite, or traceback details to the learner.
- Keep stale-card and repeated-action failures as controlled 4xx responses. A preview must never mutate review history or make a stale card reviewable.
- Bound preview work to four scheduler calls per page render. Do not accept a client-supplied list of ratings.

### Test strategy

- Add service-level tests for all four ratings, a new card, and a previously reviewed card. Use a fixed review time and deterministic FSRS settings where exact intervals are asserted.
- Assert that preview calculation does not change the stored card JSON, the current reveal state, the review history, or the repository row count.
- Test interval formatting at minute, hour, day, year, zero, negative, and non-finite boundaries. Reject invalid preview values through the Pydantic model.
- Extend web tests in `tests/web/test_study.py` to cover hidden and revealed pages, all four interval labels, practice-page behavior, help text, `aria-keyshortcuts`, the study script response, and the existing manual form lifecycle.
- Add property coverage for the invariant that one valid reveal followed by one rating creates exactly one review, even after repeated shortcut attempts or a stale response.
- Add real browser tests with Playwright. Cover Space reveal, Enter reveal, the 1-to-4 rating mapping, practice Next, ignored shortcuts in a focused textarea or other form control, held-key or repeated-key behavior, and one persisted review per action. Check that the four displayed intervals are present before the rating is submitted.
- Test the no-JavaScript path through the existing Flask client. Test the CSP and same-origin static asset response.
- Run the repository validation commands after implementation: `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`. Run the Tailwind rebuild command when the source stylesheet changes.

### Definition of done

- [ ] Space and Enter reveal an unrevealed answer.
- [ ] Space and Enter advance a revealed practice card.
- [ ] Keys 1, 2, 3, and 4 submit Again, Hard, Good, and Easy.
- [ ] Shortcuts do nothing while focus is in a form control or while a key repeats.
- [ ] A held key, double keydown, or duplicate submit creates at most one review.
- [ ] Each revealed review card shows a human-readable next interval for all four ratings.
- [ ] Interval previews use the configured server-side FSRS scheduler and do not persist state.
- [ ] Existing manual forms, stale-card errors, CSRF/session checks, and no-JavaScript study flow still work.
- [ ] The study page has visible accessible shortcut help and `aria-keyshortcuts` metadata.
- [ ] Browser tests and all project validation commands pass.
- [ ] No database migration is needed, and `git status` contains no generated database, cache, build artifact, or unrelated user file.
