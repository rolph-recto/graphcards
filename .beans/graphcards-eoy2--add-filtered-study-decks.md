---
# graphcards-eoy2
title: Add filtered study decks
status: todo
type: task
priority: high
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:57Z
updated_at: 2026-07-31T17:23:36Z
parent: graphcards-gwut
---

Add saved study filters for cramming and focused review.

## Plan

- [ ] Reuse the card browser query model.
- [ ] Add a filtered-session model with query, limit, order, and home deck.
- [ ] Add custom study choices for new, due, forgotten, and tagged cards.
- [ ] Add a route to build, rebuild, empty, and study a filtered deck.
- [ ] Preserve normal scheduling rules and return cards to their home deck.
- [ ] Add tests for selection, order, rebuild, empty, and schedule effects.
- [ ] Run the project validation commands.

## Acceptance checks

- A learner can study an arbitrary card search.
- A learner can choose a limit and order.
- A filtered session does not lose the home deck.
- Rebuilding uses the saved filter.


## Detailed planning

### Dependency and scope

- Complete graphcards-03of, Add a card browser and search, before this bean.
- Reuse the browser bean query model and its pure card-matching evaluator. Do not copy the current status-page query model. The status model contains page, tab, and preview fields that do not belong in a saved study filter.
- The shared query API must accept a typed card status, its source Entity, its configured Deck, and the current time. It must match text, fields, tags, deck scope, schedule state, FSRS state, and review properties without depending on a Flask request.
- A filtered deck has two parts: a saved definition and a built card snapshot. Rebuild evaluates the saved definition again. Study uses the current snapshot and does not silently re-run the search.
- Store a full home card identity for every selected card: deck ID plus entity ID. Do not store only an entity ID. This prevents a card with the same entity ID in two decks from being mixed.
- A query may scope one or more configured decks. The selected card keeps its own home deck. A filtered session is a review session, not a practice session. Ratings must use the normal FSRS review path.

### Data and API design

- Add a validated FilteredDeckDefinition domain model. It must contain a stable filter ID, a display name, the semantic browser query, a card limit, an order, a direction when the shared query model needs one, and a query schema version.
- Use Pydantic v2 models with strict types, extra fields forbidden, bounded names and search terms, and the same control-character rules used for entity and storage identities.
- Keep limit semantics consistent with the current session form: zero means no limit, and nonzero values must not exceed MAX_SESSION_LIMIT. Store the value in the definition so rebuild does not depend on a later form submission.
- Store the browser query as canonical JSON. Exclude UI-only page, tab, preview, and pagination state. Store relative time choices such as forgotten within N days, rather than an already computed timestamp.
- Map the custom study choices to the shared query model:
  - New means review count is zero.
  - Due means the card due time is at or before the build time.
  - Forgotten means the card has an Again review in the selected recent time window, with the same meaning as Repository.forgotten_cards.
  - Tagged means an exact tag match in the entity tags field. A non-sequence tags value does not match.
  - An arbitrary text or field query uses the same field and term semantics as the card browser.
- Persist order as the validated browser sort and direction. If the browser model has no random order, add one validated random option. Use stable home-deck and entity-ID tie breakers for deterministic orders. Store the resulting position for random order.
- Add repository operations in src/graphcards/storage.py for saving and reading definitions, listing definitions, replacing a built snapshot atomically, reading snapshot members by position, and emptying a snapshot.
- Add filtered_decks and filtered_deck_cards tables. The definition table stores the ID, name, query JSON, limit, order, direction, timestamps, and built state. The member table stores filter ID, position, home deck ID, and entity ID. Use composite foreign keys where they fit the existing cards table. Keep filtered membership separate from cards, deck_cards, and reviews.
- The replace operation must delete and insert the snapshot in one transaction. A failed rebuild must leave the previous snapshot intact. An empty operation deletes only filtered membership rows and keeps the saved definition.
- Add a focused module for filtered study domain and orchestration, such as src/graphcards/web/filtered.py, if this keeps validation and snapshot selection out of Flask route functions. Keep storage records and web request models separate.
- Extend StudyController with create or save, build, rebuild, empty, list, and start operations. The controller must resolve every stored home deck through AppConfig before a card can be rendered or reviewed.
- Extend StudySession so normal sessions still use one Deck, while filtered sessions can resolve the Deck from each StoredCard.card_key.deck_id. Availability checks, rendering, suspension, stale-review recovery, and StudyService.review must all use that home deck.
- Add a FILTERED study mode or equivalent session source marker. It must report filtered-session text in the study page and must not use the PRACTICE no-scheduling behavior.
- Add web routes for the saved-filter list and create flow, plus POST routes for build, rebuild, empty, and start-study actions for one filter ID. The start route must redirect to the existing /study route so reveal, rate, next, and suspend keep one common study flow.
- Add a filtered-deck view or section to the deck hub. Show the saved query summary, built count, limit, order, and actions. Add custom-study controls for new, due, forgotten, and tagged choices. Keep all state-changing forms protected by the controller CSRF token.
- Update src/graphcards/web/templates/study.html to identify a filtered session and its source deck context. Update src/graphcards/web/templates/index.html or add a focused filtered-decks template. If new Tailwind classes are needed, update style.src.css and regenerate static/style.css with the repository command.

### Implementation phases

1. Query contract and dependency integration

   - Finish the shared Pydantic query model and evaluator from graphcards-03of.
   - Separate semantic matching and ordering from browser pagination and HTML presentation.
   - Add a stable evaluator result that includes the StoredCard, CardStatus, source Entity, and source Deck. This result is the input for filtered selection.
   - Confirm that saved filters do not store raw SQL, Python expressions, Jinja templates, or browser-only fields.

2. Persistent filtered definitions and snapshots

   - Add the Pydantic storage records and repository methods.
   - Add the filtered-deck tables and indexes for filter ID and position.
   - Validate stored query JSON, filter IDs, names, positions, home deck IDs, and entity IDs on every read.
   - Build a selection transaction that evaluates active configured cards, applies the saved query, applies the saved order, applies the limit, and stores the ordered home card keys.
   - Treat an empty match as a successful empty build. Do not treat it as a storage error.

3. Controller and study-session integration

   - Add controller methods for save, build, rebuild, empty, and start.
   - Make build and rebuild use the persisted definition. Rebuild must ignore changed form values and current browser URL values.
   - Keep a built card in the snapshot until empty or rebuild. A card reviewed after build can therefore remain in the current filtered session; a later rebuild decides whether it still matches.
   - Resolve each home deck before presentation. Skip a card that is no longer configured, active, or available using the existing safe session summary behavior.
   - Review and suspend through the home deck. Never change a card key to the filtered-deck ID. Never reset a due time or delete review history during build, rebuild, empty, or study.

4. Routes, templates, and error boundaries

   - Add strict form models for filter name, query fields, preset values, limit, order, and filter ID.
   - Use the existing URL-encoded form parser and size limits. Return a safe 400 for malformed or out-of-range input, a 404 for an unknown deck or filter, and a 409 when a study transition cannot use the current snapshot.
   - Keep filtered management routes outside the active study endpoint set so navigating to management ends the current in-memory session in the same way as the existing deck and status pages.
   - Render user values through normal Jinja escaping. Do not mark filter names, query text, tags, or summaries as safe HTML.
   - Preserve the existing no-store and security headers on all new pages and routes.

5. Behavior tests and quality gates

   - Add focused storage, controller, web, and property tests before running the full validation commands.
   - Update only existing tests that assert the changed StudySession API. Do not add legacy compatibility tests.
   - Rebuild the committed Tailwind stylesheet when templates change, then run the required project checks.

### Storage migration and compatibility

- Increase the SQLite schema version from 7 to 8.
- Add an additive 7-to-8 migration that creates the filtered-deck tables and indexes in one transaction, sets PRAGMA user_version to 8, and leaves cards, deck_cards, and reviews unchanged.
- A fresh database must create the complete version 8 schema. Unknown schema versions must keep using the existing StorageError path.
- No old filtered-deck data exists, so do not add compatibility aliases for old table names, old query shapes, or old route parameters. Store a query schema version so a future incompatible query can fail as a controlled StorageError instead of being executed.
- Emptying or rebuilding must never delete or move the home card row, deck membership row, schedule JSON, due mirror, or review row. The only rows that those actions may change are filtered definition timestamps and filtered membership rows.

### Security and error handling

- Validate all filter definitions with Pydantic v2. Use bounded text, bounded term counts, bounded form and query sizes, strict enums, and extra-field rejection.
- Use parameterized SQL. Map each order enum to a fixed column or Python key. Never insert a user-supplied order, field name, or query fragment into SQL.
- Verify that every selected home card belongs to a configured deck and that its current composite identity matches storage before rendering, reviewing, or suspending it.
- Keep CSRF validation on create, build, rebuild, empty, and study-start forms. Keep the per-session token and entity check on reveal, rate, next, and suspend actions.
- Translate malformed request models into RequestFailure with a safe 400 message. Translate unknown configured decks and filtered IDs into safe 404 messages. Translate stale review and unavailable-card cases into the existing 409 recovery messages.
- Translate corrupt saved query JSON, corrupt filtered membership, invalid stored positions, and broken foreign-key state into StorageError. Let the existing web error boundary return a generic 500 without exposing SQL, JSON, or filesystem details.
- A presentation failure for one filtered card must skip that card and continue the session, as it does for normal study. It must not remove the saved filter or mutate the home schedule.

### Test strategy

- Add model tests for strict query parsing, unknown fields, duplicate or malformed saved JSON, control characters, limit bounds, order values, relative forgotten windows, tag shape, and canonical serialization.
- Add storage tests for fresh version 8 schema, the additive version 7 migration, definition round trips, snapshot positions, composite home identities, atomic rebuild rollback, empty behavior, corrupt rows, and unknown filter IDs.
- Add selection tests for new, due, forgotten, arbitrary field text, exact tags, deck scope, suspended and inactive exclusion, limit behavior, stable order, random order with a seeded RNG, and rebuild after schedule or entity changes.
- Add cross-deck tests with the same entity ID in two decks. Assert that each stored member retains its own home deck and that reviews and review history are written to that home deck only.
- Add study-session tests for reveal and rating, normal FSRS changes, suspension, removed or unavailable home cards, stale review snapshots, completion summaries, and the rule that filtered sessions are not practice sessions.
- Add web tests for save, list, build, rebuild, empty, and start routes; custom-study presets; CSRF failures; malformed and oversized forms; unknown IDs; safe empty results; session cleanup; and escaped user text.
- Add property tests for snapshot replacement and empty invariants: filtered operations must not change home card schedules, home memberships, or review history.
- Run:
  - uv run pytest -W error
  - uv run ruff check .
  - uv run ruff format --check .
  - uv build
  - uv run tailwindcss -i src/graphcards/web/style.src.css -o src/graphcards/web/static/style.css --minify

## Definition of done

- [ ] The browser query model and evaluator are shared with filtered study. No second search grammar exists.
- [ ] A learner can save and build an arbitrary validated search over supported fields, tags, deck scope, card state, and review properties.
- [ ] A learner can choose new, due, forgotten, or tagged custom study, a bounded limit, and a validated order.
- [ ] Build and rebuild use the saved definition. Rebuild replaces the snapshot atomically. Empty removes only filtered membership.
- [ ] A filtered session shows and reviews the selected cards while retaining every card home deck.
- [ ] Ratings update normal FSRS state and review history in the home deck. Filtered operations do not reset or delete home scheduling data.
- [ ] Same-entity cards from different decks remain distinct throughout build, study, review, rebuild, and empty.
- [ ] Invalid requests, stale cards, corrupt storage, and presentation failures produce the planned safe errors.
- [ ] Focused tests and all project validation commands pass. Git status contains only intentional scoped changes and no generated workspace, database, cache, or unrelated user files.
