---
# graphcards-03of
title: Add card search to the card status page
status: completed
type: task
priority: high
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:57Z
updated_at: 2026-08-02T16:19:41Z
parent: graphcards-gwut
---

Add search and filtering to the existing card status page.

## Product decision

The existing card status page is the sole UI surface for card search and filtering. Extend its existing card-status route, controller, status template, and current card-status data flow. Do not add a new browser page, a `/cards` collection route, or a new `card_browser.html` template. Keep the validated query model reusable by filtered study decks.

## Plan

- [x] Define a validated card-status search query model and boolean grammar.
- [x] Search entity fields, entity IDs, card states, and review properties.
- [x] Extend the existing card status page with search, pagination, and sorting; keep only the search bar, Sort By, and Direction controls.
- [x] Keep the atomic bulk-suspension action flow covered while deferring its selection bar and row-selection UI.
- Saved searches are deferred for now; the validated query model remains reusable by later work.
- [x] Add tests for query parsing, filtering, pagination, sorting, and bulk actions.
- [x] Run the project validation commands.

## Acceptance checks

- [x] A learner can search by text and card state on the existing card status page.
- [x] A learner can search by field and entity ID on the existing card status page.
- [x] A learner can sort and paginate the existing card status results.
- [x] Invalid search syntax stays on the card-status page and shows a red error bar; other invalid query parameters return safe client errors.
- [x] There is no new browser page, `/cards` collection route, or `card_browser.html` template.

## Detailed implementation plan

The existing card status route is the starting point and the only page surface for this work. The current controller loads configured deck entities and the existing stored card status rows. Extend that current card-status data flow with validated search, filtering, sorting, pagination, and bulk-action validation. Do not add search columns to the SQLite card tables.

### Phase 1: Define the query contract

- [x] Add a reusable `CardStatusQuery` model with Pydantic v2 validation and `extra="forbid"` in the existing status/query code. Do not add a browser module.
- [x] Keep page numbers at one or greater. Keep the page size bounded by the existing `CARD_PAGE_SIZE` limit.
- [x] Add a bounded `search` string. Reject control characters, overlong input, and more than a fixed number of terms.
- [x] Reuse the current availability, schedule, FSRS state, sort, direction, and date-range enums.
- [x] Keep the existing card-status deck scope as the only scope. Do not add a collection scope or a new collection route.
- [x] Parse a boolean search language with implicit and explicit AND, OR, NOT, parentheses, and quoted phrases. Support these typed terms:
  - `field:<name>=<value>` for a top-level entity field.
  - `id:<value>` for a case-insensitive entity-ID substring.
  - `state:<new|learning|review|relearning>` for the FSRS state.
  - `reviews<op><integer>` for the review count.
  - `due<op><date>`, `last_review<op><date>`, `stability<op><number>`, `difficulty<op><number>`, and `retrievability<op><number>` for review properties. Use `<op>` from `= != >= <= > <`.
  - A bare word or phrase for a case-insensitive substring search across the entity ID, field names, scalar field values, tags, and deck names. Dedicated `deck:`, `tag:`, `is:`, and `rating:` prefixes are not supported.
- [x] Use the configured display timezone for date-only comparisons. Convert the date range to UTC before comparison with stored timestamps.
- [x] Define an immutable search AST with term, AND, OR, NOT, and parenthesized nodes. Store the parsed form in the request object so matching does not parse the same text for every row.
- [x] Treat all entity JSON values as generic searchable data. Do not add a new tag column to the entity or card tables in this bean.
- [x] Reject unmatched quotes, invalid boolean syntax, empty field names, invalid operators, invalid enum values, invalid dates or numbers, excessive nesting, and unknown syntax with a controlled client error. Keep simple conjunction conflict validation and allow valid OR and NOT expressions.

### Phase 2: Extend the existing card-status read path and template

- [x] Add a `CardStatusRow` value model that joins the current deck name, display name, validated `Entity`, `CardStatus`, generator labels, and the derived FSRS retrievability value.
- [x] Extend the existing card-status controller method. Keep its current loading flow: load each configured deck, call `Repository.card_statuses`, and join each row to `Deck.entities`. Keep storage responsible for schedule and review validation.
- [x] Apply the parsed search expression and the existing status filters in memory. Do not build SQL from user text.
- [x] Define deterministic ordering. Use deck name and entity ID as the final tie breakers for every sort. Put rows with a missing sort value after rows with a value, as the current status page does.
- [x] Extend the existing card-status route, including the current deck-scoped route, to accept the validated query. Do not add `GET /cards` or any other collection route.
- [x] Preserve the existing deck information tabs and card detail links on the card status page.
- [x] Extend `card_status.html` with the search, Sort By, and Direction controls. Remove the availability, schedule, and FSRS-state dropdowns. Do not add `card_browser.html` or another page template.
- [x] Do not add a new browser link to `index.html`; rely on the existing card-status navigation.
- [x] Show the deck name, entity ID, matched field information, schedule state, review state, and action controls in each result row.
- [x] Preserve the full validated query in filter, sort, detail, and pagination links. Reset the page to one after a new search or an action.
- [x] Return a safe 404 when a requested page or deck does not exist. Keep non-search query validation as a safe 400; keep invalid search syntax on the card-status page with a red error bar.
- [x] Use normal Jinja escaping for entity IDs, field names, field values, deck names, and search text. Keep `|safe` limited to the existing trusted rendered exercise preview path.

### Phase 3: Keep bulk suspension validation (UI deferred)

- [x] Define a Pydantic v2 bulk action model with a bounded collection of unique `CardKey` selections and the existing validated suspension reason.
- [x] Defer row checkboxes and the bulk-action bar. Keep individual card actions on each result row.
- [x] Add bulk suspension handling to the existing card-status POST/action route and controller flow. Accept only URL-encoded form data, the current CSRF token, selected card keys, the suspension reason, and the current card-status query.
- [x] Add an all-or-nothing `Repository.suspend_cards` operation. Validate every selected active membership before any update. Update all memberships in one transaction. Preserve card schedules and review history.
- [x] Add the matching `StudyService` and `StudyController` methods. Revalidate every hidden selection against the current configured deck set and current membership state.
- [x] Refresh an active study session for an affected deck after a successful action.
- [x] Reject an empty selection, duplicate selection, unknown card, inactive membership, or stale selection without a partial update. Map stale state to a safe 404 or 409 response.
- [x] Keep the existing single-card suspend and resume behavior. Share reason validation and membership checks with the bulk path.
- [x] Limit the number of selected cards and the total form size. Use the existing form parser limits or raise them only to the smallest value required by the bounded selection model.

### Phase 4: Saved searches (deferred)

Saved searches are deferred for now. The card-status query model remains reusable by later work.







- [x] Keep the query parser independent from filtered study logic so `graphcards-eoy2` can reuse the same model.

### Affected modules and interfaces

- [x] Update `src/graphcards/web/status.py` with the reusable query model, pyparsing grammar, AST matching code, current status filters, row presentation, and pagination shared by the existing card-status route.
- [x] Update `src/graphcards/web/controller.py` with existing card-status loading, entity and status joins, search execution and bulk-action ownership checks.
- [x] Update `src/graphcards/web/app.py` only to extend the existing card-status route, query validation, form validation, bulk action handling, safe redirects, and client-error translation. Do not add a collection route.
- [x] Update `src/graphcards/storage.py` with the atomic bulk suspension operation.
- [x] Update `src/graphcards/app.py` with a service method for multiple suspensions if the controller should not call storage directly.
- [x] Update `src/graphcards/web/templates/card_status.html` with the status-page search and existing row-action controls. Do not add `card_browser.html` or another page template.
- [x] Update `src/graphcards/web/style.src.css` for the existing status-page search controls. Rebuild the committed `src/graphcards/web/static/style.css` with the project Tailwind command.
- [x] Update `status.js` only if the existing status-page row selection control needs a small same-origin enhancement. Keep the card status page usable without JavaScript.
- [x] Add focused tests under `tests/web/` and storage tests with the existing repository property tests. Use pyparsing for the boolean grammar and add no other runtime dependency or page-surface test suite.

### Dependencies and sequencing

- [x] Use the existing `Deck.entities` mapping, `Entity` arbitrary JSON fields, `Repository.card_statuses`, `StudyService.scheduler`, and CSRF token as the first implementation boundary.
- [x] Do not block the basic card-status search on `graphcards-lwb4`. Keep entity values generic so the later note and card model can supply canonical fields.
- [x] Make the query model the planned dependency for `graphcards-eoy2` filtered study decks.
- [x] Leave extension points for future flags from `graphcards-nlbc` and future daily-limit fields from `graphcards-iq4x`.
- [x] Keep the query and bulk-action paths after the read path passes their tests.

### Migration and compatibility decisions

- [x] Do not change the SQLite schema for search, filtering, sorting, or bulk suspension. These operations use current deck content and current card status data.
- [x] Keep the current storage schema. Do not add a saved-search table.
- [x] Continue to reject unsupported schema versions and corrupt stored values through `StorageError`. Do not add compatibility shims for obsolete internal models.
- [x] Keep the query model independent from storage schema changes.
- [x] Keep entity identity based on the existing deck path name and entity ID. Do not change card identity or resync rules.

### Security and error handling

- [x] Bound query length, term count, nesting depth, field name length, selected-card count, and form bytes before expensive work.
- [x] Use plain string comparison and numeric or date comparison. Do not compile user regular expressions.
- [x] Use the existing strict URL decoder and Pydantic validation. Translate non-search validation failures to a 400 `RequestFailure`; keep search parser failures on the existing card-status page with a generic red error bar.
- [x] Use constant-time CSRF comparison for every state-changing card-status action. Treat all hidden card selections and query fields as untrusted input.
- [x] Check current deck ownership and active membership for every suspend operation. Never trust a row from an older status-page response.
- [x] Translate storage corruption and SQLite failures to the repository or web safe error types. Do not expose SQL, Pydantic, parser, or file-system details.
- [x] Keep all entity data autoescaped. Do not pass arbitrary entity values to Jinja as trusted HTML.
- [x] Ensure card-status actions preserve the current study-session behavior.

### Test strategy

- [x] Add unit tests for valid terms, quoted phrases, boolean precedence, implicit AND, AND, OR, NOT, parentheses, quoted keywords, field lookup, nested scalar lookup, entity ID, card state, due dates, review counts, stability, difficulty, and retrievability.
- [x] Add unit tests for invalid boolean syntax, unknown fields, malformed dates and numbers, control characters, overlong queries, too many terms, excessive nesting, and conflicting conjunction terms.
- [x] Add property tests that show filtering is deterministic, sort tie breakers are stable, page concatenation equals the full ordered result, and no card appears on two pages.
- [x] Add web tests for the existing card-status route, search form, preserved query links, deck scope, empty results, invalid queries, page bounds, escaped entity data, and safe not-found responses. Do not add collection-route tests.
- [x] Add web tests for CSRF failures, empty and duplicate selections, stale selections, cross-deck selections, transaction rollback, successful bulk suspension, reason validation, and unchanged schedules and review history through the existing card-status action flow.
- [x] Add storage tests for all-or-nothing bulk updates and current membership checks.
- [x] Keep direct card-status searches on the validated query path.
- [x] Run the required validation commands after implementation: `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.

### Definition of done

- [x] A learner can use the existing card status page to search entity IDs, entity fields, card states, review properties, and boolean expressions.
- [x] A learner can sort results, move between pages, open card details, and keep the active query in each link.
- [x] The validated bulk-suspension path remains covered while its status-page selection UI is deferred.
- [x] Saved searches are deferred to a later bean.
- [x] Invalid search syntax, invalid selections, stale actions, and corrupt stored data produce safe user-facing errors.
- [x] The implementation has focused unit, property, card-status web, storage, and security tests.
- [x] The final implementation changes only the existing card-status surface and its supporting code, storage, styles, tests, generated stylesheet, and bean; it adds no new browser page, collection route, or page template.



## Summary of Changes

- Extend the existing deck card-status page with bounded search and typed filters.
- Search entity IDs, entity fields, card states, dates, and review properties with a pyparsing boolean AST; keep dedicated deck, tag, availability, and rating prefixes out of the DSL.
- Keep matching in memory and use deterministic sorting and pagination.
- Keep atomic bulk suspend and resume validation in the backend; defer the bulk-action bar and row-selection UI.
- Defer saved-search persistence and management to a later bean.

- Add focused parser, web, storage, rollback, and validation tests.
- Keep the existing card-status page as the only search surface; expose only the search bar, Sort By, and Direction controls.
- Do not add a browser page, a collection route, or a browser template.

Verification: 361 tests pass. Ruff check passes. Ruff format check passes. The package build passes. The committed Tailwind stylesheet is rebuilt.

Follow-up behavior: typed values may be quoted, for example `state:"review"` or `id:"earth"`. Syntax errors stay on the existing card-status page and render as a red error bar; no new page is used. The existing controls use Search and Clear. The typed DSL excludes `deck:`, `tag:`, `is:`, and `rating:`.



## Follow-up: Search controls

- [x] Add the id:<value> typed search term.
- [x] Add a Clear button beside Search on the existing card-status page.
- [x] Rename Apply to Search and test the controls.



## Follow-up: Reduce search prefixes

- [x] Remove the deck, tag, is, and rating typed search terms.
- [x] Update matching, documentation, and tests for the reduced DSL.
