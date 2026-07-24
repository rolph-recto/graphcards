---
# rdfcards-8f8u
title: Unify deck configuration and execution hierarchy
status: completed
type: task
priority: normal
created_at: 2026-07-24T03:05:26Z
updated_at: 2026-07-24T03:16:22Z
---

Replace the split DeckDefinition/DeckKind design with registered concrete deck definitions and presentation-only models while preserving TOML and user-facing behavior.

- [x] Introduce presentation-only models and concrete registered deck definitions
- [x] Move query execution/grouping into deck definitions and migrate application callers
- [x] Migrate behavioral tests and document the new extension API
- [x] Run all quality gates and inspect generated/unrelated files
- [x] Complete the bean and commit the staged refactor

## Summary of Changes

- Replaced the dual-role DeckKind hierarchy with registered concrete DeckDefinition subclasses that own typed configuration, query execution, validation, and grouping.
- Added presentation-only models for basic, analogy, multiple-choice, and ordered-list cards and migrated application, storage, CLI, and web typing.
- Preserved the existing TOML kind names and query behavior while allowing custom definition subclasses to register kind-specific fields.
- Split the former decks.py module into a deck package organized by kind and removed the obsolete aliases and generic constructor API.
- Updated behavioral tests and README extension guidance.
- Verified 264 tests with warnings as errors, Ruff lint and formatting, source distribution build, and wheel build; no generated repository artifacts were present.
