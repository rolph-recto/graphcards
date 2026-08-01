---
# graphcards-nlbc
title: Add review actions and leech handling
status: todo
type: task
priority: normal
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:58Z
updated_at: 2026-07-31T17:33:04Z
parent: graphcards-gwut
---

Add review controls that help learners manage difficult cards.

## Plan

- [ ] Extend stored card membership with flags and bury state.
- [ ] Add bury and unbury actions for cards and future note siblings.
- [ ] Add set-due and reset operations with review-history rules.
- [ ] Add configurable leech thresholds and automatic suspension.
- [ ] Add card information with schedule and review history.
- [ ] Add routes, study actions, CLI actions, and tests.
- [ ] Run the project validation commands.

## Acceptance checks

- A learner can flag, bury, unbury, reset, and set a due date.
- A leech follows a configured threshold.
- A leech can suspend without deleting review history.
- Card information shows the schedule and review history.

## Detailed implementation plan

The existing plan items remain unchanged and unchecked. Use the phases below to deliver them.

### Phase 1: Define the action state

- [ ] Add strict Pydantic v2 models for flags, bury times, due-date input, review indexes, and card information.
- [ ] Keep FSRS schedule data in cards. Keep deck-specific action state in deck_cards.
- [ ] Store flag as an integer from 0 to 7. Use 0 for no flag. A flag must not change schedule or review history.
- [ ] Store buried_until as a nullable canonical UTC timestamp. Bury a card until the next local day in display_timezone. Let unbury clear the timestamp.
- [ ] Store leech as separate state. Do not write a system leech message into the user suspension reason.
- [ ] Define repository actions as bulk operations over explicit entity IDs. Current entity cards use a one-item group. A future note layer can resolve sibling IDs and call the same operation. Do not add a fake note model in this bean.

### Phase 2: Extend storage and scheduling

- [ ] Add repository methods for flag, unflag, bury, unbury, set due, reset, and card information.
- [ ] Make all membership actions validate an active deck membership. Make bulk actions atomic.
- [ ] Exclude suspended and currently buried cards from due, future, forgotten, and practice queues. Let an expired bury timestamp enter the queue without a manual cleanup write.
- [ ] Add buried, flag, leech, and current-schedule fields to CardStatus and DeckStatus. Keep total review history separate from the current schedule review count.
- [ ] Add schedule_generation to cards and review rows. A reset must increment the generation and create a fresh FSRS card due at the requested time.
- [ ] Keep all review rows immutable. A reset must not delete review history. Current schedule metrics must use the current generation. Card information must show the complete history.
- [ ] Set due by updating the FSRS card and its due_at mirror. Do not create a review row and do not change schedule_generation.
- [ ] Use the public fsrs 6.3 API for card creation and review transitions. Do not edit FSRS JSON fields without validation.

### Phase 3: Add leech policy

- [ ] Add leech_threshold to FsrsSettings. Use a strict integer from 1 to 1000 and a default of 8.
- [ ] Detect a lapse from the source FSRS state and an Again rating. Store the result with the review so later scheduler changes do not change past leech counts.
- [ ] Count lapses in the current schedule generation. On the threshold review, save the review and set leech and suspended in the same transaction.
- [ ] Preserve the review row when automatic leech suspension occurs. Allow resume without deleting the leech marker. Let reset clear the leech marker while leaving manual suspension unchanged.
- [ ] Pass the validated threshold from AppConfig through StudyController and StudyService to the repository save path.

### Phase 4: Add web actions and card information

- [ ] Add Pydantic form models for each action. Use strict action values, existing EntityId validation, bounded date and text fields, and existing CSRF checks.
- [ ] Add POST-only study routes for flag, unflag, bury, and unbury. Flag must keep the current card. Bury must advance the session. Refresh availability after every action.
- [ ] Add POST-only deck routes for flag, unflag, bury, unbury, set due, and reset. Use redirect-after-post and preserve card-status filters.
- [ ] Add action methods to StudyController. Resolve the deck and entity before any write. Return safe 404 or 409 failures for unknown, inactive, stale, or unavailable cards.
- [ ] Extend the study, card-status, and card-detail templates with controls for the actions. Keep GET requests read-only.
- [ ] Extend card detail with schedule data, flag, bury state, suspension state, leech state, and a review-history table. Show dates in display_timezone and keep IDs and reasons escaped.
- [ ] Add buried and leech indicators to deck and card status views. Keep the existing CSP, no-store headers, and safe application error handler.
- [ ] Rebuild the committed Tailwind stylesheet if template or source CSS changes require it.

### Phase 5: Add CLI actions

- [ ] Add flag, unflag, bury, unbury, set-due, reset, and info commands to cli.py.
- [ ] Use deck name and validated entity ID arguments. Parse set-due as an ISO local date in display_timezone and store local midnight as UTC.
- [ ] Make info print schedule, action state, and complete review history. Use safe user-facing errors for bad dates, unknown cards, invalid state, and storage corruption.
- [ ] Keep suspend and resume behavior consistent with the new leech and bury fields.

## Affected modules and dependencies

- src/graphcards/storage.py: Pydantic storage models, schema version, migration, queue predicates, action transactions, leech indexes, and card information queries.
- src/graphcards/config.py: validated leech threshold and configuration error translation.
- src/graphcards/app.py: review metadata, lapse detection, threshold flow, and service action methods.
- src/graphcards/web/study.py: current-card action rules, session advancement, stale-card handling, and completion counts.
- src/graphcards/web/controller.py: deck-scoped action authorization and card-information view construction.
- src/graphcards/web/status.py: filters, badges, status rows, and card-information presentation models.
- src/graphcards/web/app.py: strict form models, POST routes, redirects, and safe failures.
- src/graphcards/cli.py: new action and information commands.
- src/graphcards/web/templates/study.html, card_status.html, and card_detail.html: controls and information display.
- tests/test_config.py, tests/test_property_storage.py, tests/test_integration.py, tests/test_cli.py, tests/web/test_study.py, tests/web/test_status.py, and tests/web/test_app.py: behavior and security coverage.
- Use the existing Flask, fsrs, Pydantic, SQLite, datetime, and zoneinfo dependencies. Do not add a runtime dependency unless the public fsrs API requires one. Keep uv.lock current.

## Migration considerations

The repository currently accepts schema version 0 or 7. Bump the schema to version 8.

- [ ] Make a fresh database create the version 8 schema.
- [ ] Add one transactional v7 to v8 migration. Add defaults for flag, buried_until, leech, and schedule_generation. Add review generation and lapse index fields.
- [ ] Give migrated reviews generation 0 and lapse false. Start new leech counting at the migration point because old FSRS states cannot identify every historical lapse safely.
- [ ] Validate every new SQL mirror with Pydantic and StorageError. Set PRAGMA user_version only after the full transaction succeeds.
- [ ] Keep unknown schema versions rejected. Do not add compatibility shims or drop review rows.

## Security and error handling risks

- [ ] Keep all writes parameterized and transactional. Use the existing stale-snapshot check for schedule changes.
- [ ] Compare CSRF and session tokens with secrets.compare_digest. Keep action routes POST-only and use PRG redirects.
- [ ] Bound form size, entity IDs, flag values, dates, and reasons. Reject malformed UTF-8, control characters, naive datetimes, and invalid local dates.
- [ ] Translate Pydantic failures to the existing user-facing ConfigError, StorageError, or RequestFailure types. Translate SQLite and FSRS failures at the application boundary.
- [ ] Reject writes for unknown or inactive memberships. Do not let a stale session bury, reset, set due, or change a card owned by another deck.
- [ ] Handle local-midnight and DST conversion through display_timezone, then store only canonical UTC text.
- [ ] Keep leech suspension separate from a user reason. Preserve history if automatic suspension or reset fails part way through.
- [ ] Keep all action data escaped in Jinja. Do not mark entity IDs, reasons, or history values as safe HTML.

## Test strategy

- [ ] Test Pydantic bounds and configuration errors for flags, dates, leech thresholds, and invalid persisted values.
- [ ] Test flag and bury round trips, automatic bury expiry, unbury, bulk group updates, inactive membership rejection, and schedule preservation.
- [ ] Test set due with time zones and DST boundaries. Verify no review row is added.
- [ ] Test reset creates a new FSRS schedule, increments generation, preserves every old review, and separates current schedule counts from total history.
- [ ] Test the leech boundary at threshold minus one and threshold. Verify one transaction stores the review and suspension and does not delete history.
- [ ] Add property tests for action idempotence, queue exclusion, UTC canonicalization, stale snapshots, and storage corruption translation.
- [ ] Test study actions, session advancement, stale tokens, CSRF failures, malformed forms, and unavailable cards.
- [ ] Test status and detail pages for action controls, filter-preserving redirects, schedule data, review history, leech state, and escaped values. Verify GET action paths remain 405.
- [ ] Test CLI arguments, output, state changes, info output, and user-facing errors.
- [ ] Run uv run pytest -W error, uv run ruff check ., uv run ruff format --check ., and uv build. Run the Tailwind rebuild when templates or CSS change.

## Definition of done

- A learner can flag and unflag a card from the study and deck views and from the CLI.
- A learner can bury and unbury a card. A buried card and any supplied future sibling IDs stay out of all study queues until the next local day or explicit unbury.
- A learner can set a due date. The action changes the schedule without adding a review.
- A learner can reset a card. The action creates a new schedule, preserves all old review rows, and does not erase review history.
- A leech is detected at the configured lapse threshold and is suspended without deleting the triggering review or older reviews.
- Card information shows FSRS schedule, current action state, total history, and review details in the configured time zone.
- Web and CLI actions reject invalid ownership, tokens, inputs, and corrupted storage with the repository user-facing error types.
- All required validation commands pass, generated assets are updated only when required, and the final git status contains no unrelated changes.



## Scope and User Flows

- [ ] Define the supported actions as flag, unflag, bury, unbury, set due, reset, suspend, resume, and card information.
- [ ] Define the study flow for each action, including whether the current card stays visible, whether the session advances, and when availability is refreshed.
- [ ] Define the deck-view flow for selecting one card or an explicit group of cards, confirming the target deck, and preserving active filters after the redirect.
- [ ] Define the CLI flow for deck selection, entity ID validation, local-date parsing, success output, and user-facing failure output.
- [ ] Define repeated-action behavior. Make flag, unflag, bury, unbury, suspend, and resume safe to repeat.
- [ ] Define the future note-sibling contract. Resolve sibling IDs outside this bean and pass only explicit card IDs to the shared bulk operation.
- [ ] Define the display-time rules. Show local dates in display_timezone and store action timestamps as canonical UTC values.

## Implementation Phases and Affected Areas

- [ ] Phase 0: Write the action contract and state-transition table for current schedule, review history, suspension, bury state, flags, and leech state.
- [ ] Phase 1: Update Pydantic storage models, schema version 8, migration code, indexes, queue predicates, and atomic repository transactions in storage.py.
- [ ] Phase 2: Update FsrsSettings, application validation, lapse detection, schedule-generation rules, and action service methods in config.py and app.py.
- [ ] Phase 3: Update study and deck controllers for ownership checks, stale-card checks, session advancement, status refresh, and card-information view data.
- [ ] Phase 4: Add strict web form models, POST routes, redirect handling, status filters, detail views, escaped history values, and action controls in the web modules and templates.
- [ ] Phase 5: Add CLI commands, argument parsing, output formatting, and error translation in cli.py.
- [ ] Phase 6: Update focused tests for storage, configuration, integration, web, and CLI behavior. Rebuild the committed stylesheet only if template or CSS changes require it.
- [ ] Record the responsibility of each changed module in the implementation notes before coding starts.

## Dependencies and Sequencing

- [ ] Agree on field names, defaults, valid ranges, and state transitions before changing storage or routes.
- [ ] Implement and test the v7 to v8 migration before code reads any new field.
- [ ] Implement Pydantic validation and storage transactions before application, web, or CLI callers.
- [ ] Implement schedule-generation and review-history rules before reset, info, and leech behavior.
- [ ] Thread the validated leech threshold from configuration through the application layer before adding automatic suspension.
- [ ] Add shared repository actions before adding study, deck, and CLI entry points.
- [ ] Add web and CLI adapters only after the repository result and error contracts are stable.
- [ ] Run focused tests after each phase, then run the full validation commands at the end.
- [ ] Keep the existing runtime dependency set unless the public fsrs API requires a documented change, and update uv.lock for any dependency change.

## Data/API and Migration Decisions

- [ ] Define one repository result shape for single-card actions and bulk actions. Include changed entity IDs, current action state, current schedule, and any session-advance signal needed by callers.
- [ ] Require explicit deck and entity IDs for every write. Do not infer ownership from a display name or an unchecked request field.
- [ ] Make repository action calls atomic. A failed target or invalid state must leave every target in the operation unchanged.
- [ ] Use nullable buried_until, integer flag values from 0 through 7, a separate leech marker, a separate suspension reason, and schedule_generation as the persisted state contract.
- [ ] Keep FSRS schedule fields and review rows as separate concerns. Set due changes the schedule only; reset creates a new generation; reviews remain immutable.
- [ ] Define card information as a read-only projection of current schedule, current action state, and all review generations. Do not expose raw storage objects to templates or CLI formatters.
- [ ] Store local-midnight input as canonical UTC after display_timezone conversion. Reject ambiguous or invalid local dates according to the repository time-zone policy.
- [ ] Create schema version 8 with all new columns, defaults, constraints, and indexes required by the action and queue queries.
- [ ] Implement one transactional v7 to v8 migration. Set migrated reviews to generation 0 with lapse false, and start new leech counting at the migration boundary.
- [ ] Validate migrated values through Pydantic and StorageError handling before setting PRAGMA user_version.
- [ ] Preserve unknown-schema rejection and avoid compatibility shims, destructive history cleanup, or partial migrations.
- [ ] Document the rollback boundary: any migration, reset, or leech-suspension failure must roll back all related state.

## Security and Error Handling

- [ ] Authorize every write against an active deck membership before performing the state change.
- [ ] Keep action routes POST-only, enforce CSRF checks, compare tokens with secrets.compare_digest, and use redirect-after-POST.
- [ ] Reuse stale-snapshot validation for schedule mutations and reject stale study or deck actions with the repository's safe conflict response.
- [ ] Bound request bodies, IDs, flags, dates, reasons, and group sizes. Reject malformed UTF-8, control characters, naive datetimes, and invalid time-zone conversions.
- [ ] Use parameterized SQL and one transaction for each logical action, including the triggering review and automatic leech suspension.
- [ ] Map Pydantic, SQLite, RDF or FSRS, and storage-corruption failures to the repository's user-facing error types at the correct boundary.
- [ ] Return safe 404, 405, 409, or validation failures without revealing deck ownership, internal paths, SQL details, or raw exception text.
- [ ] Preserve manual suspension reasons separately from the system leech marker. Do not let user input replace, clear, or forge leech state.
- [ ] Escape entity IDs, reasons, schedule values, and review history in every HTML and CLI presentation path.
- [ ] Validate redirect targets and preserve only approved deck and filter parameters after a POST.
- [ ] Keep no-store headers and the existing CSP on pages that show or mutate review state.

## Focused Test Strategy

- [ ] Add model tests for strict flags, dates, timestamps, generation values, threshold bounds, action values, and invalid persisted state.
- [ ] Add migration tests for fresh version 8 databases, v7 to v8 conversion, defaults, review generation values, lapse values, atomic rollback, and unknown versions.
- [ ] Add storage tests for action round trips, idempotence, explicit bulk targets, inactive memberships, atomic failure, queue exclusion, expiry, and schedule preservation.
- [ ] Add schedule tests for set due, reset, generation-specific counts, immutable history, time zones, DST boundaries, and no review row on set due.
- [ ] Add leech tests at threshold minus one, threshold, and above threshold. Verify the triggering review and suspension commit together and all history remains present.
- [ ] Add web tests for POST-only behavior, CSRF, stale tokens, malformed forms, ownership failures, session advancement, filter-preserving redirects, escaped values, and safe status codes.
- [ ] Add CLI tests for valid and invalid arguments, local-date conversion, output, info history, state changes, unknown cards, and translated storage failures.
- [ ] Add property tests for action idempotence, UTC canonicalization, queue exclusion, generation isolation, and transaction rollback.
- [ ] Run the required validation commands with warnings treated as errors after focused tests pass. Run the Tailwind rebuild only when the committed template or source stylesheet changes.

## Definition of Done

- [ ] The scope and state-transition contract is documented and matches the implemented behavior.
- [ ] Schema version 8 is created and the v7 to v8 migration is transactional, validated, and covered by tests.
- [ ] Study, deck, and CLI users can complete all supported review actions with correct schedule, history, queue, and time-zone behavior.
- [ ] Leech detection uses the configured threshold, preserves the triggering review, and keeps leech state separate from manual suspension data.
- [ ] Card information shows current schedule, action state, and complete review history without exposing unsafe values.
- [ ] Invalid ownership, stale state, CSRF, malformed input, time-zone, FSRS, database, and storage-corruption failures use safe user-facing errors.
- [ ] Focused tests and all required validation commands pass. Generated assets change only when required.
- [ ] The final worktree contains only intentional changes for this bean, and the bean is ready to move from todo only after all checklist items are checked.
