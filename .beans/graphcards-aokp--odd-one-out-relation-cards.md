---
# graphcards-aokp
title: Implement odd-one-out relation cards in the current deck model
status: completed
type: feature
priority: normal
created_at: 2026-07-24T20:00:13Z
updated_at: 2026-07-29T16:01:01Z
---

Refactor `odd_one_out` to use two entity lists, `common` and `odd`. This plan replaces the current row-based configuration. Do not create a new bean.

## Current repository state

- Decks use JSON, TOML, or YAML files.
- Exercise types are registered Pydantic v2 generator models.
- `common_relation` maps one existing entity ID to a list of related entity IDs.
- Card identity uses `CardKey.entity_id`.
- The current `odd_one_out` implementation uses relation rows, predicates, direction, and row labels.
- The packaged `odd-one-out` template uses the current row format.

## New configuration contract

Use the same outer shape as `common_relation`. The relation value contains two entity lists:

```json
{
  "id": "location-odd-one-out",
  "type": "odd_one_out",
  "relations": {
    "europe": {
      "common": ["france", "germany", "italy"],
      "odd": ["egypt", "japan"]
    }
  }
}
```

Rules:

- The relation map key must be an existing entity ID and remains the card identity.
- `common` must contain unique, declared entity IDs.
- `odd` must contain unique, declared entity IDs.
- `common` and `odd` must not overlap.
- `odd` is an eligible answer pool. Generation selects exactly one odd entity from it.
- Each generated card has one answer. A larger `odd` list provides controlled variation across generations.
- `min_candidates` defaults to three and counts the displayed common entities plus the selected odd entity.
- `max_candidates` defaults to zero. Zero displays all common entities plus one selected odd entity. A positive cap samples common entities and always retains the selected odd entity. Reject a cap below `min_candidates`.
- Generation selects the odd entity and candidate order. Rendering does not sample or reorder.
- The generator has no `direction`, predicate, relation rows, RDF validation, or row-label fields.
- Templates use entity fields for labels and relationship wording is presentation-specific.

The key entity is the shared relation target. The generator must not infer odd entities from the rest of the deck. The explicit `odd` list is the configuration boundary.

## Implementation plan

1. **Replace the configuration model.**
   - Add an `OddOneOutRelation` Pydantic model with `common` and `odd` entity lists.
   - Use the existing entity-list alias marker so both fields support a top-level named entity group when the whole field is one group ID.
   - Remove row, subject, predicate, object, direction, and row-label fields from the odd-one-out generator configuration.
   - Add a Pydantic model validator that rejects any non-empty intersection between `common` and `odd` with a repository-facing configuration error.
   - Validate duplicate IDs, empty lists, unknown references, and invalid candidate limits.
   - Keep the relation map key as the existing entity target.

2. **Refactor semantic generation.**
   - Update `OddOneOutExercise` to store the target entity, selected common entity IDs, and selected odd entity ID.
   - Remove predicate, direction, binding-label, and RDF-row data from the semantic payload.
   - Select one odd entity from the configured `odd` pool with the generation RNG.
   - Sample common entities when `max_candidates` requires a cap. Always include the selected odd entity.
   - Preserve stable card identity from deck ID, generator ID, and the relation map key.

3. **Refactor presentation.**
   - Define a generic odd-one-out template context with the target entity, common entities, candidate entities, and odd entity.
   - Add default templates that show the target and candidate labels on the front and the odd label on the back.
   - Preserve custom template validation and translate malformed semantic payloads into `PresentationError`.
   - Remove direction-specific and predicate-specific template context names.

4. **Update the packaged template.**
   - Change the `odd-one-out` JSON, TOML, and YAML decks to use `common` and `odd` lists.
   - Use existing entity keys such as `europe` and `france`.
   - Update the template README to explain answer-pool selection and candidate limits.
   - Keep the scaffold template name unchanged.

5. **Update tests.**
   - Test generator dispatch with the new shape in JSON, TOML, and YAML.
   - Test common and odd reference validation, duplicate IDs, overlaps, empty lists, and unknown IDs.
   - Include a direct overlap test that proves an entity present in both lists cannot load.
   - Test that every generated exercise has one odd answer from the configured odd pool.
   - Test odd-pool variation with a seeded RNG and stable card identity across different selections.
   - Test common sampling, candidate order, minimum and maximum limits, custom templates, and malformed payloads.
   - Test top-level entity-group aliases for both `common` and `odd` fields.
   - Test the packaged template through the scaffold command.
   - Remove tests for row predicates, direction, and row labels.

6. **Update documentation.**
   - Replace the row-based README example with the two-list example.
   - Explain that `odd` is an explicit configured pool, not the complement of the deck entities.
   - Explain that one odd entity is selected for each generated exercise.
   - State that RDF parsing, SPARQL execution, predicates, and directional relation rows are out of scope.

7. **Verify and finish.**
   - Run `uv run pytest -W error`.
   - Run `uv run ruff check .` and `uv run ruff format --check .`.
   - Run `uv build`.
   - Rebuild Tailwind only if web templates or CSS change.
   - Inspect `git status`. Do not stage generated workspaces, databases, build artifacts, caches, or unrelated user files.
   - Commit the implementation, tests, documentation, packaged template, and this bean file together. Prefix the commit subject with `[graphcards-aokp]`.

## Acceptance criteria

- A current JSON, TOML, or YAML deck accepts the two-list `odd_one_out` shape.
- Each relation key is a declared entity and is the stable card identity.
- Each generated card contains exactly one selected odd entity from the configured `odd` pool.
- Common candidates and the selected odd candidate are stored before rendering.
- Candidate limits and randomization behave as documented.
- Custom and default templates render without direction or predicate context.
- Entity-group aliases work for both lists.
- The packaged `odd-one-out` template validates in all supported deck formats.
- All required quality commands pass.

## Non-goals

- Inferring odd entities from the complement of the deck.
- RDF parsing, SPARQL execution, or relation-row loading.
- Adding a new card identity model or synthetic relation entities.
- Preserving the current row-based `odd_one_out` configuration.

## Summary of Changes

Implemented the new explicit entity-pool contract for `odd_one_out`.

- Replaced relation rows, predicates, and direction with `common` and `odd` entity lists.
- Added Pydantic validation for non-empty unique pools and exclusive common/odd membership.
- Kept the relation key as the target entity and stable card identity.
- Added odd-pool selection, common candidate sampling, stable candidate order, and candidate-limit validation.
- Simplified semantic and template contexts to entity IDs and entity objects.
- Added nested entity-group alias expansion for both pools.
- Updated JSON, TOML, YAML, README documentation, and tests.
- Verified with 289 tests, Ruff checks, format checks, and `uv build`.

## Merged Scope

The completed graphcards-wc5q template work is merged into this bean. Its packaged JSON, TOML, YAML, README, and scaffold-validation coverage are part of the odd-one-out implementation and its verification.
