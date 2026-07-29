---
# graphcards-lllj
title: Temporal comparison cards
status: completed
type: feature
priority: normal
created_at: 2026-07-24T20:08:48Z
updated_at: 2026-07-29T18:40:02Z
---

Implement temporal-comparison cards within the current entity-backed deck architecture.

The current codebase loads JSON, TOML, and YAML deck documents. It does not load RDF sources or execute SPARQL queries. Use the existing `DeckDocument`, `ExerciseGenerator` registry, ordered entity-group configuration, Pydantic v2 validation, and `Presentation`/Jinja/`CardView` rendering flow.

Implementation plan:

- [x] Add `src/graphcards/decks/temporal_comparison.py` with a registered `temporal_comparison` generator and a `TemporalComparisonExercise` model.
- [x] Reuse the ordered-group shape used by `missing_sequence_item`: each group contains at least two distinct event entity IDs, list order is the strict 1-based position, each event belongs to one group, and every reference is validated against the deck entity registry.
- [x] Schedule one card for each event entity. During `generate`, select a different event from the target event's group with the supplied RNG. Store the target ID, selected comparison ID, group ID, and both positions in the semantic exercise so `render` does not use RNG.
- [x] Derive the answer from the stored positions. Return `before` when the target position is lower and `after` when it is higher. Reject invalid or ambiguous exercise data with the repository's existing user-facing error types.
- [x] Define the built-in front and back templates and the allowed custom-template context. Expose entity references plus the group, target position, comparison position, and answer. Keep the existing label fallback order and the stateless `Presentation`/Jinja/`CardView` contract.
- [x] Export the new generator and exercise from `src/graphcards/decks/__init__.py`. Confirm generator dispatch and target ownership work with the existing `DeckDocument` and `Deck` logic.
- [x] Add the bundled `src/graphcards/templates/temporal-comparison/` template. Include `README.md`, `deck.json`, `deck.toml`, `deck.yaml`, and `graphcards.toml`. Use a small timeline example and show the before/after card behavior. Ensure the template is listed by `graphcards templates` and copied by `graphcards init --template`.
- [x] Add behavioral and property tests for valid generation, different-event selection, position-based answers, invalid groups, unknown references, malformed semantic exercises, custom template context, label fallbacks, and JSON/TOML/YAML loading.
- [x] Update `README.md` with the generator configuration, semantic exercise data, template context, and the fact that positions come from declared group order. Keep exact dates and precision grading out of scope.
- [x] Run `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`. Inspect `git status` and do not stage generated workspaces, databases, build artifacts, caches, or unrelated user files.

Acceptance criteria:

- A valid temporal-comparison deck loads in all three supported deck formats.
- Each event receives one stable card, and each generated comparison event is different but belongs to the same group.
- Rendering is deterministic for a stored exercise and produces only `before` or `after` from the stored positions.
- Invalid configuration and presentation failures use the repository's existing error boundaries.
- The new bundled template is available through the existing scaffold and CLI commands.

## Summary of Changes

Implemented temporal-comparison cards in the current entity-backed architecture.

- Added the registered generator and semantic exercise model.
- Added position-based before/after generation with stateless rendering.
- Added JSON, TOML, and YAML bundled template files.
- Added documentation, behavioral tests, format tests, and scaffold tests.
- Verification passed: 318 tests, Ruff check, Ruff format check, and `uv build`.
