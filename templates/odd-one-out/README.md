# Odd-one-out relations

This template demonstrates two entity-backed `odd_one_out` generators. Relation map keys are
existing target entities and card identities: `europe` is the target for the location exercise,
and `france` is the target for the border exercise.

Each relation defines two explicit entity lists:

```json
"europe": {
  "common": ["france", "germany", "italy"],
  "odd": ["egypt"]
}
```

The generator selects one entity from `odd` for each exercise. It never infers odd entities from
the entities that are absent from `common`. The two lists must be exclusive. Candidate order is
selected during generation, so templates only render the supplied `target`, `common_entities`,
`candidate_entities`, and `odd_entity` values.
