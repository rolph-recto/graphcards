---
# graphcards-iq4x
title: Add persistent daily limits and queue management
status: completed
type: task
priority: high
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:57Z
updated_at: 2026-07-31T22:17:25Z
parent: graphcards-gwut
---

Add Anki-style daily limits and queue control for each deck.

## Plan

- [x] Define strict Pydantic settings for new-card and review limits.
- [x] Store daily review counts with the configured display timezone.
- [x] Separate new, learning, relearning, and review queues.
- [x] Add queue order and limit logic to the study service.
- [x] Show limits, remaining counts, and hidden-card counts in the web UI and CLI.
- [x] Add tests for day boundaries, limits, multiple decks, and session restarts.
- [x] Run the project validation commands.

## Acceptance checks

- A deck never exceeds its daily limits.
- The dashboard shows remaining work.
- The queue uses the configured timezone.
- Practice sessions do not consume daily review limits.

## Detailed implementation plan

### Scope and design decisions

This bean adds daily limits and queue selection for normal scheduled study. It uses the existing FSRS card state and SQLite review history. It does not add filtered-deck behavior, review undo, leech rules, or note authoring.

- [x] Store the limits with each deck document. Add a `daily_limits` object that works in JSON, TOML, and YAML. Use strict Pydantic fields named `new_cards_per_day` and `reviews_per_day`.
- [x] Set the default limits to 20 new cards and 200 reviews per local day. Reject booleans, floats, negative values, unknown fields, and values above a safe implementation limit. Treat zero as no cards from that queue.
- [x] Keep `display_timezone` as the only timezone setting. Keep all stored timestamps in canonical UTC text. Convert a review time to the configured local date before counting it.
- [x] Use the existing `reviews` table as the durable source for daily usage. Count rows for review usage and count the first review event for each card for new-card usage. Do not add a second mutable counter table in this bean. This keeps counts correct after a process restart and avoids counter drift.
- [x] Define the queue kinds as `new`, `learning`, `relearning`, and `review`. Classify a card from its FSRS state. Report an invalid FSRS state as a `StorageError`.
- [x] Use one stable queue order: learning, relearning, review, then new. Sort cards inside each queue by due time and entity ID. Apply the daily limit to the new and review budgets. Apply the review budget to every saved, non-practice rating so the stored review count cannot exceed the configured limit.
- [x] Keep practice sessions outside the scheduler. Practice may show available cards, but it must not create a review row and must not use either daily budget.

### Phase 1: Add the domain and configuration models

Affected modules: `src/graphcards/scheduling.py` (new), `src/graphcards/decks/base.py`, `src/graphcards/models.py` if a shared immutable model is needed, and `src/graphcards/config.py` for validation wiring.

- [x] Add immutable Pydantic models for daily limits, daily usage, queue counts, and a queue plan. Use strict integer fields and non-negative bounds.
- [x] Add the optional `daily_limits` field to `DeckDocument` with a validated default. Expose it from `Deck` so the study service can use the limits without reading raw deck data.
- [x] Add a function that returns the half-open UTC interval for one local day. Build the next boundary from the next local calendar date. Do not assume that a local day is always 24 hours.
- [x] Add queue classification helpers that map the FSRS `New`, `Learning`, `Relearning`, and `Review` states to the four queue kinds.
- [x] Keep the model extra-field policy strict. Translate validation failures from deck loading into `ConfigError`, as the current deck loader does.

### Phase 2: Add persistent usage and queue reads

Affected module: `src/graphcards/storage.py`.

- [x] Add repository methods for daily usage, raw queue counts, and queue card reads. Each method must validate active memberships, card JSON, due mirrors, and review logs before it returns filtered data.
- [x] Count review usage with a parameterized UTC interval using `reviewed_at >= start` and `reviewed_at < end`. Count new usage from the first review event for each card, using review ID as the tie breaker when timestamps match.
- [x] Return immutable domain values instead of raw SQLite rows. Include the local date, both configured limits, both used counts, both remaining counts, each queue count, and hidden-card counts.
- [x] Add a queue argument or a queue-aware read path to distinguish cards that are due from cards that are merely active. Do not let suspended or inactive memberships enter any queue.
- [x] Keep `status()` useful for existing callers, but add the richer queue status as a separate repository result if that avoids mixing raw card totals with limit-filtered totals.
- [x] Validate every count before returning it. Reject negative or non-integer database values and translate malformed review timestamps or payloads into `StorageError`.

### Phase 3: Build the study queue and enforce limits

Affected modules: `src/graphcards/app.py`, `src/graphcards/web/controller.py`, `src/graphcards/web/study.py`, and `src/graphcards/errors.py`.

- [x] Add a `StudyService` queue-planning method. It must accept a deck, study mode, current UTC time, and requested session limit. It must return the selected cards plus per-queue hidden counts and daily usage.
- [x] For a due session, gather due cards by queue, apply the daily budgets, then apply the requested session limit. Keep the queue order stable. Do not count cards hidden only by a user-selected session limit as hidden by a daily limit.
- [x] Route forgotten and ahead sessions through the same budget check when they can create reviews. Keep their existing search window and order rules. Route practice through an explicit no-persistence path.
- [x] Re-evaluate daily usage when a session starts, when it advances, and when the local day changes. This prevents a long-lived session from using yesterday's remaining budget.
- [x] Recheck the limit inside the same SQLite transaction that updates the card and inserts the review. A stale session or a second process must receive a limit error instead of exceeding the cap.
- [x] Add a safe `DailyLimitError` under the repository error hierarchy. Include the queue or budget name and the remaining count for CLI and web callers, but do not expose SQL details.
- [x] Catch the limit error in `StudySession.rate()` and return a controlled conflict response. Leave the card state unchanged. Move the session to a valid next state or completion message so the learner cannot rate the same blocked card repeatedly.
- [x] Preserve the current stale-card and unavailable-card behavior. A failed limit check must not weaken the source-card snapshot check or membership check.
- [x] Pass the configured display timezone into `StudyService`. Add a testable clock or an explicit `now` path for queue and review operations instead of requiring tests to depend on the wall clock.

### Phase 4: Expose queue state in the web UI and CLI

Affected modules: `src/graphcards/web/status.py`, `src/graphcards/web/app.py`, `src/graphcards/web/controller.py`, `src/graphcards/web/templates/index.html`, `src/graphcards/web/templates/study.html`, `src/graphcards/web/templates/card_status.html`, and `src/graphcards/cli.py`.

- [x] Extend the controller dashboard data with queue totals, daily used counts, remaining counts, and hidden counts. Use the configured display timezone when showing the day label.
- [x] Update the deck dashboard to show new, learning, relearning, and review queues. Show the new and review limits, used values, remaining values, and cards hidden by those limits.
- [x] Make the main study action use the number of cards that the queue planner can show. Distinguish `no cards are due` from `the daily limit is reached`.
- [x] Show the current queue and remaining daily work on the study page. Keep practice text clear that it does not change scheduling or daily usage.
- [x] Add queue and daily-limit details to deck status. Keep the existing card-status filters and suspension actions separate from daily-limit counts.
- [x] Extend the CLI `status` output with queue totals, daily usage, remaining counts, and hidden counts. Add a queue column to the full card table if the result remains readable.
- [x] Validate all new form and query values with Pydantic. Do not accept a client-supplied limit or count as authoritative.
- [x] If new utility classes are needed, edit `style.src.css` and rebuild the committed stylesheet with the project Tailwind command during implementation. Do not hand-edit the generated stylesheet.

### Data, API, and dependency notes

- [x] Keep the public service boundary in `StudyService`; keep SQL and UTC interval details in `Repository`; keep rendering-specific view conversion in the web status module.
- [x] Use the existing `fsrs` package for state and due values, the existing Pydantic v2 models for validation, `zoneinfo.ZoneInfo` for local dates, and SQLite transactions for atomic review writes. Add no third-party dependency.
- [x] Keep `reviews` as the event source of truth. Practice remains unlogged because it does not schedule a card. A normal rating creates exactly one review event or no event on failure.
- [x] Define hidden counts as eligible cards that the daily plan could show but that the daily new or review budget removes. Report session-limit truncation separately or omit it from the hidden count.
- [x] Keep deck identity based on the existing directory name. Daily usage for two decks with the same entity ID must remain separate.

### Migration and compatibility

- [x] Do not change the current card identity or FSRS JSON shape. Existing deck files that omit `daily_limits` must load with the validated defaults.
- [x] Because daily usage comes from the existing review events, this design needs no new counter-table migration and preserves review history across normal application restarts.
- [x] Review the current `SCHEMA_VERSION = 7` initialization path before implementation. If the final queue metadata design requires a schema column, use a new schema version and an atomic fresh-schema change, or fail with the repository's existing unsupported-schema `StorageError`. Do not silently guess queue data or delete a user's database.
- [x] Do not add legacy compatibility tests. Add only behavior tests for the new limits, queue model, and the current supported schema.

### Security and error handling

- [x] Enforce limits on the server and inside the write transaction. Do not rely on disabled buttons, hidden fields, in-memory session counters, or a dashboard read.
- [x] Use parameterized SQL for deck IDs, queue names, and time intervals. Use a half-open interval so a review at the next local midnight belongs to the next day.
- [x] Translate invalid Pydantic settings into `ConfigError`, invalid FSRS or review data into `StorageError`, and a reached budget into `DailyLimitError`. Keep raw parser, Pydantic, and SQLite errors out of web responses.
- [x] Preserve CSRF checks, session tokens, expected-host checks, form size limits, and no-store security headers on all new or changed routes.
- [x] Make limit failures atomic. A failed review must not update `cards`, insert `reviews`, or consume a daily count.

### Test strategy

- [x] Add configuration tests for defaults, JSON/TOML/YAML deck settings, zero limits, negative and boolean values, oversized values, unknown fields, and invalid timezone values.
- [x] Add repository tests for local-day boundaries in at least UTC and a non-UTC zone. Cover reviews just before and after midnight, repeated reviews of one card, multiple decks, and a process/repository restart.
- [x] Add queue tests for all four FSRS states, stable queue order, suspended cards, inactive memberships, due versus future cards, requested session limits, and hidden counts.
- [x] Add service tests that prove a deck cannot exceed either daily budget, that a second stale session is rejected at write time, that the next local day restores the budget, and that practice creates no review event.
- [x] Add web tests for dashboard counts, limit-reached messaging, study-page queue labels, controlled limit conflicts, CSRF rejection, and unchanged practice behavior.
- [x] Add CLI tests for the new status fields and for user-facing limit and storage errors.
- [x] Add property tests for non-negative counts, `used + remaining = limit` when the budget is finite, no duplicate card identities in a plan, and no review row from a practice action.
- [x] Run the required validation commands only after implementation: `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, `uv build`, and the Tailwind rebuild when templates or source CSS change.

## Definition of done

- [x] Each deck has strict, validated new-card and review limits with documented defaults.
- [x] Daily usage survives a repository and application restart and follows the configured display timezone, including local day boundaries.
- [x] The study queue separates new, learning, relearning, and review cards and uses the defined order.
- [x] A normal session cannot exceed its daily budgets, even when a stale session or second process submits a rating.
- [x] Practice sessions do not change FSRS state, review history, or daily usage.
- [x] The web dashboard, study page, deck information page, and CLI show limits, remaining counts, and hidden-card counts.
- [x] Corrupt configuration, FSRS data, review data, and storage state produce the repository's user-facing error types.
- [x] Focused tests and the full project validation workflow pass, and the final worktree check excludes generated workspaces, databases, caches, and unrelated user files.

## Summary of Changes

Implemented strict per-deck daily limits with validated defaults, timezone-aware durable usage counts, deterministic learning/relearning/review/new queue planning, and atomic review-limit enforcement. Added storage corruption and daily-limit error translation, dynamic study-session handling, web dashboard/study/deck status reporting, CLI status reporting, documentation, and behavior tests. Rebuilt the committed Tailwind stylesheet.

Validation passed: 342 tests, Ruff lint, Ruff format check, and uv build.
