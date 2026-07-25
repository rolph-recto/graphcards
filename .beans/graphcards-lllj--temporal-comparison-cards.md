---
# graphcards-lllj
title: Temporal comparison cards
status: todo
type: feature
created_at: 2026-07-24T20:08:48Z
updated_at: 2026-07-24T20:08:48Z
---

Add a temporal-comparison card source that reuses the ordered-list query contract.

Query shape:

```sparql
SELECT ?entity ?group ?position ?label
WHERE {
  ...
}
```

Each group is an ordered timeline. For every event in a valid group, generate one entity card by selecting a different event from the same group during card generation.

Example prompt:

```text
Did the Signing of the Magna Carta happen before or after the Battle of Bouvines?
```

The answer is derived from the positions of the two events and is either `before` or `after`.

Configuration:

```toml
[[decks.sources]]
kind = "temporal_comparison"
target = "entity"
query = "queries/events.rq"
```

Requirements:
- Reuse the ordered-list projection exactly: ?entity, ?group, ?position, and ?label.
- Use target = entity; each event is the identity of one generated card.
- Validate groups with at least two events, strict 1-based positions, contiguous positions, one group per entity, and distinct entities.
- Generate one card per event, pairing it with a randomly selected different event from the same group. Random selection occurs during card generation; Presentation receives no RNG.
- Store both event entities, labels, group, and positions in the generated card data.
- Derive the answer from positions as before or after; reject impossible or ambiguous ordering data.
- Render the question and answer through the Presentation/Jinja/CardView pipeline.
- Support the existing label fallback behavior and ordered-list validation conventions.
- Exact dates and precision/close-enough grading are out of scope for this type; the ordered position is the temporal fact.
- Update extension APIs, configuration validation, documentation, templates, and behavioral tests.
