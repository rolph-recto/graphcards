---
# graphcards-03of
title: Add card search to the card status page
status: todo
type: task
priority: high
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:57Z
updated_at: 2026-07-31T19:35:33Z
parent: graphcards-gwut
---

Add search and filtering to the existing card status page.

## Product decision

The existing card status page is the sole UI surface for card search and filtering. Extend its existing card-status route, controller, status template, and current card-status data flow. Do not add a new browser page, a `/cards` collection route, or a new `card_browser.html` template. Keep the validated query model reusable by filtered study decks.

## Plan

- [ ] Define a validated card-status search query model.
- [ ] Search entity fields, tags, deck names, card states, and review properties.
- [ ] Extend the existing card status page with filtering, pagination, sorting, and selectable rows.
- [ ] Add bulk suspension for selected rows through the existing card-status action flow.
- [ ] Add saved searches to the existing card status page after the basic query path works.
- [ ] Add tests for query parsing, filtering, pagination, sorting, and bulk actions.
- [ ] Run the project validation commands.

## Acceptance checks

- [ ] A learner can search by text and card state on the existing card status page.
- [ ] A learner can search by field and tag on the existing card status page.
- [ ] A learner can sort and paginate the existing card status results.
- [ ] Invalid search syntax returns a safe error.
- [ ] There is no new browser page, `/cards` collection route, or `card_browser.html` template.

## Detailed implementation plan

The existing card status route is the starting point and the only page surface for this work. The current controller loads configured deck entities and the existing stored card status rows. Extend that current card-status data flow with validated search, filtering, sorting, pagination, selection, bulk actions, and saved searches. Do not add search columns to the SQLite card tables.

### Phase 1: Define the query contract

- [ ] Add a reusable `CardStatusQuery` model with Pydantic v2 validation and `extra="forbid"` in the existing status/query code. Do not add a browser module.
- [ ] Keep page numbers at one or greater. Keep the page size bounded by the existing `CARD_PAGE_SIZE` limit.
- [ ] Add a bounded `search` string. Reject control characters, overlong input, and more than a fixed number of terms.
- [ ] Reuse the current availability, schedule, FSRS state, sort, direction, and date-range enums.
- [ ] Keep the existing card-status deck scope as the only scope. Do not add a collection scope or a new collection route. Keep the `deck:<value>` search term for stable or display deck-name search.
- [ ] Parse one search language with AND semantics. Support quoted phrases and these typed terms:
  - `field:<name>=<value>` for a top-level entity field.
  - `tag:<value>` for a tag.
  - `deck:<value>` for a stable deck name or display name.
  - `state:<new|learning|review|relearning>` for the FSRS state.
  - `is:<new|due|future|suspended>` for card availability and schedule.
  - `rating:<again|hard|good|easy|none>` for the last review rating.
  - `reviews<op><integer>` for the review count.
  - `due<op><date>`, `last_review<op><date>`, `stability<op><number>`, `difficulty<op><number>`, and `retrievability<op><number>` for review properties. Use `<op>` from `= != >= <= > <`.
  - A bare word or phrase for a case-insensitive substring search across the entity ID, field names, scalar field values, tags, and deck names.
- [ ] Use the configured display timezone for date-only comparisons. Convert the date range to UTC before comparison with stored timestamps.
- [ ] Define a search expression model or AST. Store the parsed form in the request object so matching does not parse the same text for every row.
- [ ] Treat a top-level entity field named `tags` as tags when it is a string or a list of strings. Treat other JSON values as generic searchable data. Do not add a new tag column to the entity or card tables in this bean.
- [ ] Reject unmatched quotes, empty field names, invalid operators, invalid enum values, invalid dates or numbers, duplicate conflicting terms, and unknown syntax with a controlled client error.

### Phase 2: Extend the existing card-status read path and template

- [ ] Add a `CardStatusRow` value model that joins the current deck name, display name, validated `Entity`, `CardStatus`, generator labels, tags, and the derived FSRS retrievability value.
- [ ] Extend the existing card-status controller method. Keep its current loading flow: load each configured deck, call `Repository.card_statuses`, and join each row to `Deck.entities`. Keep storage responsible for schedule and review validation.
- [ ] Apply the parsed search expression and the existing status filters in memory. Do not build SQL from user text.
- [ ] Define deterministic ordering. Use deck name and entity ID as the final tie breakers for every sort. Put rows with a missing sort value after rows with a value, as the current status page does.
- [ ] Extend the existing card-status route, including the current deck-scoped route, to accept the validated query. Do not add `GET /cards` or any other collection route.
- [ ] Preserve the existing deck information tabs and card detail links on the card status page.
- [ ] Extend `card_status.html` with search controls and result controls. Do not add `card_browser.html` or another page template.
- [ ] Do not add a new browser link to `index.html`; rely on the existing card-status navigation.
- [ ] Show the deck name, entity ID, matched field or tag information, schedule state, review state, and action controls in each result row.
- [ ] Preserve the full validated query in filter, sort, detail, and pagination links. Reset the page to one after a new search or an action.
- [ ] Return a safe 404 when a requested page or deck does not exist. Return a safe 400 when the query is invalid.
- [ ] Use normal Jinja escaping for entity IDs, field names, field values, tags, deck names, and search text. Keep `|safe` limited to the existing trusted rendered exercise preview path.

### Phase 3: Add selectable rows and bulk suspension

- [ ] Define a Pydantic v2 bulk action model with a bounded collection of unique `CardKey` selections and the existing validated suspension reason.
- [ ] Add checkboxes to the existing card-status result page. Encode both deck identity and entity identity in each selection so a status-page action cannot cross a deck boundary by accident.
- [ ] Add bulk suspension handling to the existing card-status POST/action route and controller flow. Accept only URL-encoded form data, the current CSRF token, selected card keys, the suspension reason, and the current card-status query.
- [ ] Add an all-or-nothing `Repository.suspend_cards` operation. Validate every selected active membership before any update. Update all memberships in one transaction. Preserve card schedules and review history.
- [ ] Add the matching `StudyService` and `StudyController` methods. Revalidate every hidden selection against the current configured deck set and current membership state.
- [ ] Refresh an active study session for an affected deck after a successful action.
- [ ] Reject an empty selection, duplicate selection, unknown card, inactive membership, or stale selection without a partial update. Map stale state to a safe 404 or 409 response.
- [ ] Keep the existing single-card suspend and resume behavior. Share reason validation and membership checks with the bulk path.
- [ ] Limit the number of selected cards and the total form size. Use the existing form parser limits or raise them only to the smallest value required by the bounded selection model.

### Phase 4: Add saved searches after the basic query path works

- [ ] Define a validated `SavedSearch` model with a bounded name, a query version, a canonical serialized `CardStatusQuery`, and UTC creation and update timestamps.
- [ ] Store the parsed query form, not unvalidated raw input. Keep saved searches scoped to the current card-status deck unless a future model adds user ownership.
- [ ] Add `Repository` operations to create, list, load, update, and delete saved searches. Use parameterized SQL and validate every stored value on read.
- [ ] Add a `saved_searches` table with a unique name, canonical query JSON, version, and canonical UTC timestamps.
- [ ] Add CSRF-protected save, load, and delete actions to the existing card status page and its current controller flow. Redirect only to the local card-status route; do not create a saved-search page or collection route.
- [ ] Return a safe storage error when a saved query is corrupt or uses an unsupported query version. Do not execute a corrupt query.
- [ ] Keep the query parser and serialized AST independent from filtered study logic so `graphcards-eoy2` can reuse the same model.

### Affected modules and interfaces

- [ ] Update `src/graphcards/web/status.py` with the reusable query model, parsing and matching code, current status filters, row presentation, and pagination shared by the existing card-status route.
- [ ] Update `src/graphcards/web/controller.py` with existing card-status loading, entity and status joins, search execution, saved-search calls, and bulk-action ownership checks.
- [ ] Update `src/graphcards/web/app.py` only to extend the existing card-status route, query validation, form validation, bulk action handling, saved-search actions, safe redirects, and client-error translation. Do not add a collection route.
- [ ] Update `src/graphcards/storage.py` with the atomic bulk suspension operation and the saved-search schema and repository methods.
- [ ] Update `src/graphcards/app.py` with a service method for multiple suspensions if the controller should not call storage directly.
- [ ] Update `src/graphcards/web/templates/card_status.html` with the status-page search, selection, bulk-action, and saved-search controls. Do not add `card_browser.html` or another page template.
- [ ] Update `src/graphcards/web/style.src.css` for the existing status-page search controls, result selection, and bulk-action feedback. Rebuild the committed `src/graphcards/web/static/style.css` with the project Tailwind command.
- [ ] Update `status.js` only if the existing status-page row selection control needs a small same-origin enhancement. Keep the card status page usable without JavaScript.
- [ ] Add focused tests under `tests/web/` and storage tests with the existing repository property tests. Do not add a new runtime dependency or a new page-surface test suite.

### Dependencies and sequencing

- [ ] Use the existing `Deck.entities` mapping, `Entity` arbitrary JSON fields, `Repository.card_statuses`, `StudyService.scheduler`, and CSRF token as the first implementation boundary.
- [ ] Do not block the basic card-status search on `graphcards-lwb4`. Isolate tag extraction so the later note and card model can supply canonical tags.
- [ ] Make the query model the planned dependency for `graphcards-eoy2` filtered study decks and later saved-search consumers.
- [ ] Leave extension points for future flags from `graphcards-nlbc` and future daily-limit fields from `graphcards-iq4x`.
- [ ] Keep saved-search persistence after the read path and bulk action pass their tests.

### Migration and compatibility decisions

- [ ] Do not change the SQLite schema for search, filtering, sorting, or bulk suspension. These operations use current deck content and current card status data.
- [ ] Bump the storage schema version only when saved searches are added. Add a transaction that creates the saved-search table from the current supported schema version. Create the complete latest schema for a new database.
- [ ] Continue to reject unsupported schema versions and corrupt stored values through `StorageError`. Do not add compatibility shims for obsolete internal models.
- [ ] Version the saved-query JSON. Reject a version that the current parser does not support.
- [ ] Keep entity identity based on the existing deck path name and entity ID. Do not change card identity or resync rules.

### Security and error handling

- [ ] Bound query length, term count, field name length, selected-card count, and form bytes before expensive work.
- [ ] Use plain string comparison and numeric or date comparison. Do not compile user regular expressions.
- [ ] Use the existing strict URL decoder and Pydantic validation. Translate parser and validation failures to a 400 `RequestFailure` with a generic card-status search message.
- [ ] Use constant-time CSRF comparison for every state-changing card-status action. Treat all hidden card selections and query fields as untrusted input.
- [ ] Check current deck ownership and active membership for every suspend operation. Never trust a row from an older status-page response.
- [ ] Translate storage corruption and SQLite failures to the repository or web safe error types. Do not expose SQL, Pydantic, parser, or file-system details.
- [ ] Keep all entity data autoescaped. Do not pass arbitrary entity values to Jinja as trusted HTML.
- [ ] Ensure search and saved-search actions end an active study session in the same way as the current non-study card-status actions.

### Test strategy

- [ ] Add unit tests for valid terms, quoted phrases, field lookup, nested scalar lookup, tags, stable and display deck names, card state, last rating, due dates, review counts, stability, difficulty, and retrievability.
- [ ] Add unit tests for invalid syntax, unknown fields, malformed dates and numbers, control characters, overlong queries, too many terms, and conflicting terms.
- [ ] Add property tests that show filtering is deterministic, sort tie breakers are stable, page concatenation equals the full ordered result, and no card appears on two pages.
- [ ] Add web tests for the existing card-status route, search form, preserved query links, deck scope, empty results, invalid queries, page bounds, escaped entity data, and safe not-found responses. Do not add collection-route tests.
- [ ] Add web tests for CSRF failures, empty and duplicate selections, stale selections, cross-deck selections, transaction rollback, successful bulk suspension, reason validation, and unchanged schedules and review history through the existing card-status action flow.
- [ ] Add storage tests for all-or-nothing bulk updates, current membership checks, saved-search round trips, corrupt saved-query JSON, and the supported schema upgrade.
- [ ] Add tests that saved searches reuse the same parsed query behavior as direct card-status searches and that a saved query cannot change the selected deck or escape the local status route.
- [ ] Run the required validation commands after implementation: `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.

### Definition of done

- [ ] A learner can use the existing card status page to search entity IDs, entity fields, tags, deck names, card states, and review properties.
- [ ] A learner can sort results, move between pages, open card details, and keep the active query in each link.
- [ ] A learner can select visible rows and suspend them in one atomic action without changing schedule or review history.
- [ ] A learner can save, load, and delete a validated search from the existing card status page after the basic query path works.
- [ ] Invalid search syntax, invalid selections, stale actions, and corrupt stored data produce safe user-facing errors.
- [ ] The implementation has focused unit, property, card-status web, storage, migration, and security tests.
- [ ] The final implementation changes only the existing card-status surface and its supporting code, storage, styles, tests, generated stylesheet, and bean; it adds no new browser page, collection route, or page template.
