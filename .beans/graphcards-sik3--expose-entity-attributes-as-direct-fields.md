---
# graphcards-sik3
title: Expose entity attributes as direct fields
status: in-progress
type: feature
priority: normal
created_at: 2026-07-28T02:20:45Z
updated_at: 2026-07-28T03:26:58Z
---

Change entity-backed deck content so top-level attributes from each entity record are exposed and consumed as direct Entity fields or properties rather than accessed through the Entity.data mapping. Treat this as a deliberate presentation and model API change while preserving stable IDs, immutable JSON-compatible values, round-trip serialization, and user-facing validation errors.


## Proposed contract

Entity JSON remains flat at the top level for ordinary attributes:

    {"id": "france", "front": "France", "back": "Paris", "facts": {"region": "Europe"}}

After validation, every ordinary top-level JSON attribute from the entity record is exposed directly with the same field name, not collected under a special data mapping. The example fields entity.front, entity.back, and entity.facts are illustrative only; arbitrary source fields such as entity.name, entity.wikidata_id, or entity.coordinates are equally valid. Nested values retain their original JSON structure while being exposed immutably. The public .data mapping is removed from the template-facing Entity API; serialization must continue through Pydantic model validation and dumping rather than requiring callers to index a data bag.

Built-in templates and their fallback chains use direct attributes, for example entity.front, entity.prompt, entity.question, and entity.id. Missing optional attributes retain the current fallback behavior through explicit defined checks. Custom templates receive Entity references and access fields directly; no bundled documentation or example should teach .data.get(...).

## Implementation plan

- [ ] Define the direct-attribute Entity contract, including dynamic top-level fields, reserved Pydantic names, missing-field behavior, and whether any internal serialization helper remains private.
- [ ] Refactor the Pydantic v2 Entity model so validated extra fields are first-class attribute access while preserving strict non-blank IDs, arbitrary nested JSON-compatible values, deep immutability, duplicate-key rejection, and model round trips.
- [ ] Remove .data usage from built-in basic, multiple-choice, ordered-list, analogy, and common-relation templates and from any renderer-side helpers.
- [ ] Update configurable-template validation and all template contexts and documentation so Entity references expose .id plus direct attributes with safe defined and fallback semantics.
- [ ] Rewrite behavior and property tests to assert direct field access, rendering parity, missing-field fallbacks, nested-value immutability, invalid JSON rejection, and serialization round trips; ensure .data is no longer part of the supported contract.
- [ ] Update README, bundled template READMEs and examples, and demo deck content to document the direct-attribute API and the breaking nature of the change.
- [ ] Translate Pydantic and template failures into repository configuration or presentation errors at the existing boundaries.
- [ ] Run focused tests and the full quality gates: uv run pytest -W error, uv run ruff check ., uv run ruff format --check ., and uv build; inspect status and commit only scoped implementation and bean files.

## Acceptance criteria

- A loaded record such as {"id": "france", "front": "France"} renders through entity.front and does not require entity.data.
- All built-in generators render the same intended output for valid records, including existing front, prompt, question, back, answer, and label fallback chains.
- A custom template can read a declared top-level entity attribute directly, while unknown template variables and missing required values still fail with the repository presentation and configuration errors.
- Entity IDs remain stable and distinct from user attributes; duplicate JSON keys, invalid nested values, non-finite numbers, excessive nesting, and mutable aliasing remain rejected or prevented.
- Serialization and validation preserve every supported top-level and nested entity attribute without reintroducing a public data-bag contract.
- Tests, README, bundled templates, and demos contain no supported-API dependency on .data.get(...).

## Open decisions

- Use a fully dynamic validated-field representation that mirrors every ordinary top-level key in the source JSON. Common display names are template conventions only, not a field whitelist or a required static Entity schema.
- Decide which names are intrinsically reserved by the Entity implementation because they cannot safely be represented as direct fields; do not reserve ordinary source names merely because they are not among the built-in display conventions. The old data bag must disappear as special behavior; a source JSON key named data, if valid under the reserved-name policy, is an ordinary direct field.
- Whether missing direct attributes should be handled only with Jinja is defined checks or with a small presentation helper that centralizes fallback selection.
