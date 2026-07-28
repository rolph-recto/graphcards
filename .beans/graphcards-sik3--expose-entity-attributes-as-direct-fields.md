---
# graphcards-sik3
title: Expose entity attributes as direct fields
status: completed
type: feature
priority: normal
created_at: 2026-07-28T02:20:45Z
updated_at: 2026-07-28T18:34:41Z
---

Change entity-backed deck content so every ordinary top-level attribute from each entity record is exposed and consumed as a direct Entity field rather than through a synthetic data bag. Treat this as a deliberate presentation and model API change while preserving stable IDs, immutable JSON-compatible values, round-trip serialization, and user-facing validation errors.


## Proposed contract

Entity JSON remains flat at the top level for ordinary attributes:

    {"id": "france", "front": "France", "back": "Paris", "facts": {"region": "Europe"}}

After validation, the entity exposes entity.id and every ordinary source key directly, including fields such as entity.front, entity.facts, entity.name, entity.wikidata_id, entity.coordinates, and entity.data when those keys are present. Nested values remain immutable JSON-compatible mappings or sequences. There is no synthetic aggregate .data mapping; a source key named data is only its own direct field. Serialization continues through Pydantic model validation and dumping.

Built-in templates and their fallback chains use direct attributes, for example entity.front, entity.prompt, entity.question, and entity.id. Missing optional attributes retain the current fallback behavior through explicit defined checks. Custom templates receive Entity references and access every ordinary field directly; no bundled documentation or example should teach a synthetic data-bag fallback.

## Implementation plan

- [x] Define the fully dynamic direct-attribute Entity contract, including reserved Pydantic names, missing-field behavior, and private serialization boundaries.
- [x] Refactor the Pydantic v2 Entity model so validated extra fields are first-class attribute access while preserving strict non-blank IDs, arbitrary nested JSON-compatible values, deep immutability, duplicate-key rejection, and model round trips.
- [x] Remove synthetic data-bag usage from built-in basic, multiple-choice, ordered-list, analogy, and common-relation templates and from any renderer-side helpers.
- [x] Update configurable-template validation and all template contexts and documentation so Entity references expose .id plus direct attributes with safe defined and fallback semantics.
- [x] Rewrite behavior and property tests to assert fully dynamic direct field access, rendering parity, missing-field fallbacks, nested-value immutability, invalid JSON rejection, and serialization round trips; ensure there is no synthetic data-bag contract.
- [x] Update README, bundled template READMEs and examples, and demo deck content to document the direct-attribute API and the breaking nature of the change.
- [x] Translate Pydantic and template failures into repository configuration or presentation errors at the existing boundaries.
- [x] Run focused tests and the full quality gates: uv run pytest -W error, uv run ruff check ., uv run ruff format --check ., and uv build; inspect status and commit only scoped implementation and bean files.

## Acceptance criteria

- A loaded record such as {"id": "france", "front": "France", "name": "France"} renders through entity.front and entity.name directly; a source key named data, when present, is also direct rather than an aggregate bag.
- All built-in generators render the same intended output for valid records, including existing front, prompt, question, back, answer, and label fallback chains.
- A custom template can read a declared top-level entity attribute directly, while unknown template variables and missing required values still fail with the repository presentation and configuration errors.
- Entity IDs remain stable and distinct from user attributes; duplicate JSON keys, invalid nested values, non-finite numbers, excessive nesting, and mutable aliasing remain rejected or prevented.
- Serialization and validation preserve every supported top-level and nested entity attribute without reintroducing a public data-bag contract.
- Tests, README, bundled templates, and demos contain no supported-API dependency on a synthetic .data.get(...) aggregate; ordinary source fields, including data when present, remain direct.

## Open decisions

- Use a fully dynamic validated-field representation; common display names are template conventions, not a whitelist or required static schema.
- Do not expose a public mapping view or synthetic aggregate; Pydantic serialization uses private model state, and templates cannot access Pydantic implementation internals. Reject only private names and the narrowly defined Pydantic implementation names that cannot safely coexist with Entity behavior.
- Use Jinja `is defined` and `default` semantics for missing optional direct attributes; built-in templates keep their existing explicit fallback chains, with no additional presentation helper.

## Summary of Changes

Implemented fully dynamic direct Entity attributes for every ordinary top-level JSON key, with a narrow reserved-name policy, immutable JSON-compatible nested values, duplicate-key-safe model and legacy parsing, and repository-facing validation/rendering errors. Migrated built-in and custom template usage, README and bundled template documentation, strategies, and behavior/property tests away from synthetic data-bag semantics while preserving display-field fallback conventions.

Final verification:
- uv run pytest -W error — 242 passed
- uv run ruff check . — passed
- uv run ruff format --check . — passed
- uv build — passed
- Independent behavior, tests/regressions, security/error-handling, and API/documentation review/fixer loops — no actionable findings.
