---
# graphcards-z7mn
title: Scrambled-list exercises for ordered related entities
status: completed
type: feature
priority: normal
created_at: 2026-07-29T17:53:36Z
updated_at: 2026-07-29T18:19:23Z
---

Add a new `scrambled_list` entity-backed exercise type.

## Design

Use the same map-of-lists configuration shape as `missing_sequence_item`, with a different meaning for the map key:

```json
{
  "id": "planet-order",
  "type": "scrambled_list",
  "groups": {
    "solar-system": ["mercury", "venus", "earth", "mars"]
  }
}
```

For this type, each map key is the target entity ID. Each list is the target's ordered list of related entity IDs. Keep the field name `groups` to match the existing missing-sequence-item configuration shape.

The generator schedules one card for each map key. The generated exercise stores the target ID and one shuffled permutation of the related IDs. The generator uses the supplied RNG and does not shuffle again during rendering. When there are at least two related entities, the generated permutation must differ from the configured order.

The default front shows the target and the related entities in scrambled order. The default back shows the related entities in the configured order. Custom templates can access `target`, `scrambled_entities`, and `ordered_entities`. The target is not part of the related list.

## Scope

- Add Pydantic v2 generator and exercise models with strict validation.
- Register and export the new generator and exercise.
- Validate non-blank target and related IDs, known references, at least two related entities, unique related entities, and no target self-reference.
- Validate generated exercise payloads and translate malformed render state into the repository's presentation errors.
- Cover JSON, TOML, and YAML loading through the existing shared generator pipeline.
- Add behavior tests for generation, stable rendering, shuffled order, custom templates, invalid configuration, invalid references, and malformed exercise payloads.
- Update README configuration and template-context documentation.
- Keep the change focused on the new exercise type. Do not add compatibility aliases for old names.
- Run the required quality gates and inspect git status. Do not commit without explicit user confirmation.

- [x] Implement the scrambled-list generator and exercise models
- [x] Register and export the new exercise type
- [x] Add behavior and property coverage
- [x] Update documentation and examples where required
- [x] Run the required verification commands
- [x] Inspect git status and summarize scoped changes
- [x] Commit the implementation and bean after explicit user confirmation

## Summary of Changes

Implemented the `scrambled_list` exercise type with strict Pydantic validation, seeded stored shuffles, stable rendering, custom template contexts, JSON/TOML/YAML loading, named group aliases, behavior tests, property coverage, and README documentation. Added and tested the bundled `scrambled-planets` template in JSON, TOML, and YAML. Verified with 303 tests, Ruff, formatting, diff checks, and `uv build`.
