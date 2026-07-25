---
# graphcards-aokp
title: Odd-one-out relation cards
status: todo
type: feature
created_at: 2026-07-24T20:00:13Z
updated_at: 2026-07-24T20:00:13Z
---

Add an odd-one-out relation exercise paired with common-relation completion cards.

Object-direction example:

```text
France  located_in  Europe
Germany located_in  Europe
Italy   located_in  Europe
Egypt   located_in  Africa
```

The student selects Egypt as the subject that does not share the common relation.

Subject-direction example:

```text
France borders Germany
France borders Spain
France borders Italy
Germany borders Poland
```

The student selects Poland as the object that does not share the common relation.

Configuration:

```toml
[[decks.sources]]
kind = "odd_one_out"
target = "entity"
query = "queries/european-location-odd-one-out.rq"
direction = "object"
min_candidates = 3
max_candidates = 0  # 0 means show all
```

Query contract:

```sparql
SELECT ?group ?subject ?predicate ?object
       ?subject_label ?predicate_label ?object_label
WHERE {
  ...
}
```

Requirements:
- Require an explicit ?group binding to delimit one exercise.
- Use target = entity; the odd varying endpoint is the card identity and answer.
- direction = object means subjects are the candidate entities and all but one share one object; direction = subject means objects are the candidate entities and all but one share one subject.
- All rows in a group must use the same predicate. The odd row must differ only in the endpoint selected by direction; the other endpoint and predicate remain structurally consistent.
- Require exactly one odd candidate and at least min_candidates total candidates. min_candidates is configurable and defaults to three.
- Support max_candidates, defaulting to zero for unlimited. When capped, randomly sample common candidates during card generation while always retaining the odd candidate. Reject a cap smaller than min_candidates.
- Reject duplicate candidates, ambiguous groups, groups with no odd candidate, and groups with more than one differing endpoint.
- Candidate endpoints must be IRIs because the exercise tests an entity. Validate the shared endpoint according to RDF subject/object rules.
- Store the common endpoint, predicate, direction, candidate entities, and odd entity in the generated card data. The Presentation/Jinja template decides whether and how to show the common endpoint; it is not discarded during generation.
- Support optional subject_label, predicate_label, and object_label bindings with existing label fallback conventions.
- Randomize candidate order during card generation; Presentation receives no RNG and only renders the generated card data into CardView.
- Update extension APIs, configuration validation, docs, templates, and behavioral tests.
