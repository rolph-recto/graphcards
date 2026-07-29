---
# graphcards-bqbd
title: Named entity groups in deck files
status: completed
type: feature
priority: normal
created_at: 2026-07-29T03:02:28Z
updated_at: 2026-07-29T04:02:59Z
---

Allow deck.json, deck.toml, and deck.yaml files to define named groups of entity IDs and allow those group IDs wherever exercise definitions currently accept lists of entity IDs. Resolve groups during deck validation so generators receive expanded entity IDs while preserving ordering and producing repository-facing configuration errors for invalid group references or definitions.\n\n- [x] Specify the deck-file schema and resolution semantics\n- [x] Identify validation and generator integration points\n- [x] Define JSON/TOML/YAML and generator coverage\n- [x] Implement named entity groups\n- [x] Add tests and documentation\n- [x] Run the repository verification commands\n


## Problem

Deck authors currently repeat the same entity-ID lists in every exercise generator. Add reusable, named groups at the deck-document level so the same set of entities can be referenced from any exercise field whose domain is an ordered list of entity IDs. This is configuration sugar: generators, semantic exercises, card identities, scheduling, and rendering continue to operate on concrete entity IDs.

## Proposed schema

Add an optional top-level `groups` sequence. Each group has a unique non-blank `id` and a non-empty ordered `entities` sequence containing concrete entity IDs:

```json
"groups": [
  {"id": "france-borders", "entities": ["germany", "italy", "spain"]}
]
```

The same shape is expressed as `[[groups]]` tables in TOML and a YAML sequence of mappings in YAML. Group IDs must be distinct from entity IDs so a reference is unambiguous. Group definitions cannot contain other group IDs; this keeps expansion acyclic and makes their meaning explicit.

A list-valued entity-reference slot accepts exactly one of two forms: its existing list of concrete entity IDs, or one group ID string that replaces the entire list. Group IDs are not valid items inside an entity-ID list, so `"entities": "european-countries"` is valid but `"entities": ["france", "european-countries"]` is invalid. Entity-ID map keys remain entity IDs and are not expanded.

Support all current list-valued generator fields:

- `basic.entities`
- `multiple_choice.choices[target]`
- `ordered_list.groups[group_id]` member lists
- `analogy.sources[target]`
- `common_relation.relations[target]`

Thus the motivating form, `"relations": {"france": "france-borders"}`, expands to the existing tuple `("germany", "italy", "spain")` before `common_relation` validation.

## Validation and resolution design

- Add a strict frozen Pydantic v2 group model and `DeckDocument.groups`, defaulting to an empty tuple for existing decks.
- In the document pre-validation path, build the group registry and normalize supported generator fields before the existing typed-generator dispatch. Keep malformed non-list values available for the normal Pydantic error boundary, but report unknown group references as configuration errors that identify the group and exercise field.
- In document post-validation, enforce unique entity IDs, unique group IDs, no group/entity ID collision, non-empty groups, unique group members, and group members that all exist in the entity registry. Preserve member order.
- Expand aliases only in the five list-valued fields above. Do not expand exercise map keys, entity records, template text, or group definitions.
- Preserve the expanded concrete IDs in generator models. No group names should enter semantic exercise payloads or template contexts, and existing duplicate/member/card-count validation should continue to apply after expansion.
- Let `Deck.load` continue translating Pydantic and resolution failures into path-qualified `ConfigError`; direct model validation should retain its current `ValidationError` behavior.

## Acceptance criteria

- [x] JSON, TOML, and YAML decks load the top-level group schema and support the same expansion semantics.
- [x] A group can replace a list in every supported generator field, including the scalar common-relation example; inline lists preserve their order and group expansion preserves the group declaration order.
- [x] Equivalent inline and grouped definitions generate the same target IDs, semantic exercises, card identities, and rendered views under the same RNG seeds.
- [x] Existing decks without `groups` behave unchanged, including validation, exercise counts, persistence identities, and rendering.
- [x] Invalid group IDs, duplicate IDs, entity/group collisions, empty or duplicate members, unknown members, unknown aliases, mixed inline/group lists, nested group definitions, and malformed field shapes fail before synchronization with useful `ConfigError` messages.
- [x] Group expansion cannot introduce silent duplicates; existing generator-specific duplicate and minimum-size rules are evaluated on the expanded list.
- [x] README authoring documentation includes JSON, TOML, and YAML examples and clearly states ordering, alias scope, and non-nesting rules.
- [x] Focused tests, property tests where useful, `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build` pass.

## Implementation plan

1. **Model and normalization:** add the group model and a small, centrally tested resolver in `src/graphcards/decks/base.py`; invoke it before typed generator dispatch and retain validated groups on `DeckDocument`.
2. **Generator coverage:** exercise every list-valued field, including scalar aliases and explicit rejection of mixed lists, and verify expanded values reach the existing generator validators without changing generator APIs.
3. **Format parity:** extend the JSON/TOML/YAML parity fixtures with the same group declarations and aliases, including TOML `[[groups]]` syntax and YAML sequence syntax.
4. **Failures and invariants:** add behavioral tests for invalid group definitions/references, ordering, duplicate expansion, no-group compatibility, stable card identities, and repository-facing error translation; add property coverage for expansion/order invariants if it fits the existing strategies.
5. **Documentation and verification:** update README authoring guidance and, if an existing bundled example is changed to use a group, keep all three format examples aligned; run the repository gates and inspect `git status` for unrelated/generated files.

## Non-goals

- Nested or recursive groups.
- Group references in entity metadata, templates, generator map keys, workspace configuration, or runtime APIs.
- Changes to exercise generator algorithms, card payload schemas, persistence migrations, or web UI behavior.
- A second group syntax or format-specific behavior.

## Summary of Changes

Implemented top-level ordered entity groups for JSON, TOML, and YAML decks using a strict Pydantic model. Group IDs can replace complete list-valued fields in basic, multiple-choice, ordered-list, analogy, and common-relation generators; mixed inline/group lists and nested group definitions are rejected. Expansion occurs before typed generator validation, preserving concrete IDs, generator behavior, card identities, ordering, and rendering.

Added JSON/TOML/YAML parity, grouped-vs-inline generation/rendering, ordering, invalid-definition, unknown-alias, and mixed-list rejection tests. Documented the schema and format-specific syntax in README.md.

Verified with 271 tests, `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, `uv build`, and `git diff --check`.

## Follow-up: Bundled template example

Updated the bundled `common-relations` JSON template so `common-borders` defines and consumes the `france-borders` entity group. Added a CLI regression assertion that the scaffolded template expands the group to the expected ordered relation IDs.

## Follow-up: Generator-extensible group normalization

The current implementation keeps an exercise-type-to-fields switch in `DeckDocument` via `_expand_generator_groups`. Refactor this so group normalization is owned by the registered generator class and adding a new generator with groupable fields does not require editing the base document loader.

Recommended design:

- Add a default `ExerciseGenerator.normalize_group_references(value, groups)` classmethod that returns the raw definition unchanged.
- In `DeckDocument.dispatch_generators`, resolve the registered generator class first, call that hook, then run typed Pydantic validation. Remove the central exercise-type switch and `_expand_generator_groups`.
- Keep only generic direct-list and mapping-value expansion helpers in shared infrastructure, retaining whole-list alias semantics, path-aware errors, ordering, mixed-list rejection, and nested-group rejection.
- Override the hook in each existing generator: `basic.entities`, multiple-choice `choices` values, ordered-list `groups` values, analogy `sources` values, and common-relation `relations` values.
- Add a test-only registered generator with a previously unseen groupable field to prove that future generator support requires changes only in that generator and its tests.
- Preserve JSON/TOML/YAML behavior, no-group compatibility, semantic payloads, card identities, rendering, and repository-facing `ConfigError` translation. Add a concise README architecture note if useful.

Implementation checklist:

- [x] Add the generator-owned normalization hook and generic helpers.
- [x] Move current generator field knowledge out of `DeckDocument/base.py`.
- [x] Add extensibility and regression coverage across JSON/TOML/YAML behavior.
- [x] Update architecture documentation if needed.
- [x] Run all repository gates and commit the implementation with this bean.

## Revision: Recursive raw exercise-value expansion

The recursive approach supersedes the earlier generator-owned hook proposal. Use one generic resolver over raw exercise JSON values rather than separate direct-field/mapping helpers or per-generator field declarations.

Resolution boundaries:

- Walk exercise definition mappings and sequences recursively before typed generator dispatch.
- When a mapping value is a standalone string equal to a declared group ID, replace it with that group’s ordered entity-ID list.
- When a sequence contains a group ID, reject it as a mixed/group-in-list configuration error; do not expand it into nested list members.
- Preserve mapping keys exactly; do not resolve keys.
- Do not walk top-level `entities` or `groups` data, entity metadata, exercise `id`/`type`, or template fields. This prevents a literal group-named string from being rewritten outside list-reference positions and keeps nested group definitions invalid.
- After recursion, dispatch the unchanged typed generator registry and let existing Pydantic/reference validation handle the resulting concrete lists.

The tests should cover every current generator field, a future-shaped nested exercise value, excluded metadata/template strings, mapping-key preservation, mixed-list rejection, and JSON/TOML/YAML parity. This removes all exercise-type knowledge from the base resolver while retaining the existing whole-list alias semantics.

Updated implementation checklist:

- [x] Replace `_expand_generator_groups` with a bounded recursive raw-exercise resolver.
- [x] Define and test explicit recursion boundaries and group-in-list errors.
- [x] Preserve existing generator behavior, formats, errors, and no-group compatibility.
- [x] Update architecture documentation to describe recursive expansion.
- [x] Run all repository gates and commit the implementation with this bean.

## Revision: Schema-guided recursion

A raw recursive walk cannot infer semantic intent from JSON alone: a group-named string might be an entity-list alias, a literal option, metadata, or template text. Therefore recursion must be guided by the registered generator schema rather than matching every string value.

Use a reusable `EntityIdList` Pydantic/`Annotated` marker (or equivalent field metadata) on generator fields whose values are lists of entity IDs, including mapping values such as `dict[str, EntityIdList]`. The generic resolver may recurse through the raw exercise structure, but it only substitutes a standalone group ID at nodes whose schema position carries that marker. A group ID encountered inside a marked list is rejected; ordinary strings in unmarked fields are untouched. Top-level entities/groups, mapping keys, IDs, types, templates, and metadata are never eligible.

This preserves the extensibility goal without a central exercise-type switch: a new generator opts into group expansion by marking its entity-ID list field(s), while the shared recursive resolver handles traversal, ordering, errors, and JSON/TOML/YAML parity. If Pydantic annotation introspection proves too brittle for nested mapping values, the fallback is equivalent generator-owned field metadata—not an exercise-type table in `DeckDocument`.

Updated checklist:

- [x] Define the reusable entity-list schema marker and schema-guided recursive resolver.
- [x] Mark all current generator entity-ID list fields and remove the central type/field switch.
- [x] Test unmarked literals, metadata/templates/keys, marked aliases, and mixed-list rejection.
- [x] Preserve existing format behavior and documentation.
- [x] Run all repository gates and commit the implementation with this bean.

## Revision: Shared `EntityId` scalar

`EntityIdList` must be built on a reusable validated `EntityId` scalar rather than raw `StrictStr`.

Define the shared reference types in a common schema module (prefer a dedicated `src/graphcards/decks/references.py`, or the repository's existing equivalent):

- `EntityId`: a strict string with the current nonblank/control-character validation used for entity references.
- `EntityIdList`: an annotated tuple of `EntityId` values carrying the schema marker that identifies group-resolvable list positions.
- Mapping values that represent entity lists use `EntityIdList`; mapping keys and scalar fields that represent actual entity IDs use `EntityId` where applicable.

Replace `StrictStr` with `EntityId` for actual entity references consistently, including `Entity.id`, `EntityGroup.entities`, generator entity-reference fields and mapping keys/values, `Exercise.target_id`, `CardKey.entity_id`, and any other audited entity-reference field. Keep identifiers with different semantics—generator IDs, generator `type`, group IDs, deck IDs/names, and template strings—as their own strict string types rather than conflating them with `EntityId`.

Group expansion still occurs before final Pydantic validation: a standalone group reference is resolved only at a marked `EntityIdList` schema position, then each concrete member is validated as an `EntityId`. Preserve strict no-coercion behavior, existing nonblank/control-character errors, and mixed-list rejection.

Updated checklist:

- [x] Define the shared validated `EntityId` scalar and marked `EntityIdList` type.
- [x] Audit and replace `StrictStr` on actual entity references; retain distinct types for non-entity identifiers.
- [x] Mark all current generator entity-ID list fields and remove the central type/field switch.
- [x] Test unmarked literals, metadata/templates/keys, marked aliases, invalid entity IDs, and mixed-list rejection.
- [x] Preserve existing format behavior and documentation.
- [x] Run all repository gates and commit the implementation with this bean.

## Implementation Summary

Replaced the baked-in generator-type switch with schema-guided recursive normalization driven by `EntityIdList` annotations on registered generator fields. Added shared strict `EntityId` and `EntityIdList` types in `src/graphcards/references.py`, applied `EntityId` consistently to actual entity references, and kept generator IDs, group IDs, deck IDs, and template strings distinct.

Added a registered test-only generator proving new marked fields expand without changes to `DeckDocument`, while unmarked literals and metadata remain unchanged. Verified with 272 tests, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.
