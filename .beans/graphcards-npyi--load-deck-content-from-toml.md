---
# graphcards-npyi
title: Load deck content from TOML
status: completed
type: feature
priority: normal
created_at: 2026-07-27T00:00:00Z
updated_at: 2026-07-28T04:10:15Z
---

Load deck content from TOML while preserving the existing JSON behavior and validation pipeline.

Requirements:

- [x] `Deck.load` selects the parser by case-insensitive suffix: `.json` retains the duplicate-key-aware JSON loader; `.toml` uses standard-library `tomllib`; unsupported extensions raise an explicit path-qualified ConfigError without content sniffing.
- [x] Both formats feed the same `DeckDocument` Pydantic v2 validation, reference checks, stable parent-directory deck identity, rendering preflight, card identity, and rendering behavior.
- [x] Translate TOML syntax, JSON parsing, I/O, Unicode, recursion/type/value, non-JSON-compatible TOML date/time metadata, Pydantic validation, unknown generator types, invalid nested generator data, missing/non-file paths, and rendering-preflight failures into the repository's user-facing ConfigError as appropriate. Preserve useful TOML parser location text.
- [x] TOML uses `[[entities]]` and `[[exercises]]`; nested `choices`, `groups`, `sources`, and `relations` are TOML tables. Cover basic, multiple_choice, ordered_list, analogy, and common_relation generators.
- [x] Prove JSON/TOML parity for validated documents, deterministic generated payloads/card identities under the same RNG seeds, and rendered views. Put equivalent JSON and TOML files in the same parent directory for identity comparison.
- [x] Prove relative TOML paths in `load_config`, mixed JSON/TOML workspaces, CLI validate and sync, unsupported/mixed-case suffixes, malformed/non-object TOML, bad generators/references/nested data, and TOML native date/time rejection. Preserve existing JSON/scaffold behavior.
- [x] Update format-specific docstrings/wording, README authoring docs with a minimal TOML deck and mixed workspace example, and CLI validate help text. Do not rewrite or convert existing JSON templates unless genuinely required.
- [x] Run focused tests while iterating and all required gates: `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.
- [x] Complete independent behavioral, tests/edge cases, error/config/security, and docs/quality reviews; fix all actionable findings.

## Summary of Changes

Implemented JSON/TOML deck loading with suffix-based parser selection, standard-library TOML parsing, shared Pydantic validation, error translation, parity tests across all five generators, mixed-workspace CLI/config coverage, and README/help/docstring updates. Added robust path, recursion, native date/time, scaffold symlink, and CLI persistence coverage. Corrected a pre-existing common-relation JSON rendering drift required by the existing tests/documentation and TOML rendering parity. All review passes are complete with no unresolved actionable findings.

Verified with 186 tests, `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, `uv build`, and `git diff --check`.
