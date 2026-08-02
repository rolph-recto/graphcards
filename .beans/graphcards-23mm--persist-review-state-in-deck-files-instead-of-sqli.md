---
# graphcards-23mm
title: Persist review state in deck files instead of SQLite
status: completed
type: feature
priority: high
tags:
    - storage
    - deck-files
created_at: 2026-08-02T19:43:43Z
updated_at: 2026-08-03T05:48:17Z
---

# Persist review state in deck files instead of SQLite

## Goal

Move all durable study state from SQLite into the deck file that owns the cards. Keep the current Python and Flask application in this bean. Do not add a second database.

## Scope

- Store the FSRS schedule for every known entity.
- Store the complete immutable review history and its analytics values.
- Store suspension state and the current suspension reason.
- Store per-deck queue settings and daily-limit overrides.
- Keep state for removed entities so a later deck edit can restore the old schedule and history.
- Derive active membership from the current generated deck content.
- Keep the user-wide display timezone and the deck file list in the user-wide `config.toml` at `~/.graphcards/config.toml`.
- Remove `state_path` from the user-wide configuration.

## State document

Add an optional, strict top-level `review_state` object to `DeckDocument`. Use a versioned model with this shape:

- `version`: state schema version.
- `revision`: monotonic write revision for conflict checks and diagnostics.
- `entities`: map from entity ID to FSRS card data, suspension data, and the last-seen metadata that the application needs.
- `reviews`: ordered review events with a stable ID, entity ID, rating, UTC timestamp, duration, interval values, and retrievability.
- `settings`: optional saved daily limits and queue settings that override deck-file defaults.

Use entity IDs as the state keys. Keep the deck directory as the runtime deck identity. Retain state entries that do not have a current generated card. Reject duplicate review IDs, invalid entity references, invalid timestamps, invalid FSRS values, unknown fields, and unsupported state versions with a user-facing storage error.

Represent state with Pydantic v2 models. Convert FSRS parser failures, Pydantic failures, malformed timestamps, and corrupt review data at the storage boundary. Do not silently discard or reset corrupt state.

## File write rules

- Read and write the same JSON, TOML, or YAML extension.
- Convert the complete document to JSON-compatible values before serialization.
- Add the required TOML writer dependency and use the existing safe YAML parser and a safe YAML writer.
- Preserve content and state semantics across a load-write-load cycle.
- Use stable output formatting for each format. Do not promise to preserve source comments or exact whitespace.
- Acquire a per-deck file lock before a state mutation.
- Compare the full file digest after taking the lock. Use `review_state.revision` as an application-owned state version for diagnostics and optimistic checks. Reject an external edit instead of overwriting it.
- Write a temporary file in the deck directory, flush and sync it, replace the original atomically, and sync the directory when the platform supports it.
- Leave the original file unchanged when validation, serialization, locking, or replacement fails.
- Report an external edit as a controlled conflict that asks the CLI or web user to reload the deck.

## Implementation plan

- [x] Add strict Pydantic models for the versioned review state, card state, review events, and saved deck settings.
- [x] Add JSON, TOML, and YAML state serialization with semantic round-trip tests.
- [x] Implement a deck-file state store that reads state, initializes new cards, preserves removed cards, and writes state atomically.
- [x] Move sync, queue reads, daily usage, status reads, review history, suspension actions, and settings updates from SQLite operations to the deck-file state store.
- [x] Preserve stale card snapshot checks and add stale deck-file revision checks to each mutating operation.
- [x] Update `StudyService`, the CLI, the web server, and the web error handlers to use the new store and to show write and conflict failures safely.
- [x] Remove the optional SQLite migration command and module at user request. Keep deck-file persistence as the only supported runtime storage path.
- [x] Remove the normal `Repository` and SQLite schema path. Remove `state_path`, SQLite error handling, and database setup from runtime configuration and templates. Do not keep a compatibility layer for the old internal repository API.
- [x] Update deck fixtures, example files, README text, and CLI help to describe the in-file state and supported commands.
- [x] Replace database tests with behavior tests for file persistence, corruption handling, atomic failure, external edits, removed and returned entities, settings, suspensions, review history, and all three deck formats.
- [x] Run `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.

## Acceptance checks

- [x] A new deck without `review_state` loads and syncs. Sync writes the initial state into the deck file.
- [x] A rating updates the FSRS schedule and appends one review event in one atomic file replacement.
- [x] A fresh process reads the same schedule, history, daily usage, settings, and suspension state without a SQLite file.
- [x] The queue, status, history, daily-limit, and card-detail views keep their current behavior.
- [x] A removed entity keeps its state. A later re-added entity resumes its old schedule and history.
- [x] An external deck edit or stale card snapshot cannot overwrite newer state.
- [x] A corrupt state document produces a repository error and leaves the deck file unchanged.
- [x] JSON, TOML, and YAML decks preserve valid content and review state after repeated writes.
- [x] The CLI does not expose a SQLite migration command; normal runtime storage uses deck files only.
- [x] Normal application startup and operation do not create or open SQLite state databases.
- [x] All required validation commands pass.

## Out of scope

- Automatic merge of two independently edited deck files.
- Byte-for-byte preservation of comments or source formatting.
- Importing or deleting an old SQLite state file.
- A deck editor or a change to the exercise-generation model.

## Design note

This bean targets the current Python and Flask application. It is separate from the draft PWA and Electron rewrite, which proposes IndexedDB as its storage layer. Choose one storage design before implementing both efforts.


## Revision meaning

`review_state.revision` is an application-owned optimistic concurrency token. Start it at `1` when GraphCards first writes the state object. Increase it by one after each successful state write: sync, review, suspend, resume, or settings update. It tells a process which state version it loaded. The full file digest remains the authoritative conflict check because a manual content edit can leave the revision unchanged.

Example:

```json
{
  "review_state": {
    "version": 1,
    "revision": 7,
    "entities": {
      "capital-france": {
        "fsrs": {
          "card_id": 123,
          "state": 3,
          "step": null,
          "stability": 2.3,
          "difficulty": 5.1,
          "due": "2026-08-03T12:00:00Z",
          "last_review": "2026-08-02T12:00:00Z"
        },
        "suspended": false,
        "suspension_reason": null
      }
    },
    "reviews": [],
    "settings": {}
  }
}
```

## Summary of Changes

Persisted review state in each JSON, TOML, or YAML deck with strict Pydantic models, atomic writes, file conflict checks, and runtime CLI/web integration. Removed the SQLite migration command and module at user request. Updated documentation, templates, and behavior tests.
