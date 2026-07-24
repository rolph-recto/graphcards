---
# rdfcards-0b8j
title: Audit and safely simplify merged card implementations
status: completed
type: task
priority: normal
created_at: 2026-07-24T02:10:38Z
updated_at: 2026-07-24T02:18:05Z
---

Audit recent ordered-list and analogy additions plus surrounding code for behavior-preserving simplifications.

- [x] Inspect recent merges and identify duplication/branching/API candidates with risk
- [x] Implement only clearly safe simplifications with focused tests
- [x] Run full repository quality gates
- [x] Review git status, document deferred candidates, and commit changes

## Plan and risk assessment

1. Establish a clean baseline and inspect both merged feature commits plus shared config, presentation, storage, CLI, and web paths.
2. Implement only low-risk candidates: centralize Pydantic error formatting; share strict RDF integer parsing; remove duplicate analogy hide validation; declare deck target/default constraints on deck kinds; reduce analogy duplicate comparison to source identity and computed display values.
3. Preserve exact exception and rendering behavior with focused analogy, ordered-list, config, model, and storage tests.
4. Run pytest with warnings as errors, Ruff lint, Ruff format check, and build.
5. Review status/diff, document deferred candidates, and commit source/tests plus this bean.

Deferred unless further evidence lowers risk: generalizing ordered-list full-query execution hooks, replacing kind-specific config fields with a generic options model, splitting the deck hierarchy into modules, or removing the OrderedList compatibility alias.

## Summary of Changes

- Centralized first-error Pydantic message extraction and reused it for presentation and storage error translation.
- Consolidated strict RDF integer parsing used by multiple-choice priorities and ordered-list positions while preserving messages and bounds.
- Moved target requirements and option defaults onto deck kinds so configuration no longer imports and branches over every concrete kind.
- Removed the analogy model validator's duplicate hide check and reduced duplicate comparison to source identity, hide mode, and the computed learner-facing front/back text.
- Added focused tests for inherited ordered-list constraints, display-equivalent analogy labels, and distinct analogy sources with identical rendered text.
- Verified 265 tests with warnings as errors, Ruff lint, Ruff formatting, and source/wheel builds.

## Deferred candidates

- Ordered-list full-query rendering remains an explicit presentation-layer special case. Generalizing it would change the custom DeckKind execution contract and add hooks for query binding, projection, and grouping; that extension-surface risk outweighs one contained branch.
- A generic per-kind configuration-options model would require product decisions about the public TOML shape and compatibility, so the existing max_choices/window_size fields remain.
- Splitting decks.py would primarily move code and raise merge-conflict risk without simplifying behavior.
- The OrderedList alias is retained because removing it could break programmatic callers.
