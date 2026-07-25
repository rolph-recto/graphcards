---
# graphcards-o49w
title: Common-relation completion cards
status: todo
type: feature
created_at: 2026-07-24T19:52:30Z
updated_at: 2026-07-24T19:52:30Z
---

Add a common-relation completion card source that tests the shared endpoint of several triples.

Examples:

Object completion:

```text
France  located_in  Europe
Germany located_in  Europe
Italy   located_in  Europe
```

The front lists the related subjects and asks for the common object; the back shows Europe.

Subject completion:

```text
France borders Germany
France borders Spain
France borders Italy
```

The front lists the related objects and asks for the common subject; the back shows France.

Configuration:

```toml
[[decks.sources]]
kind = "common_relation"
target = "entity"
query = "queries/locations.rq"
direction = "object"
min_examples = 2
max_related = 0  # 0 means show all
```

Query contract:

```sparql
SELECT ?subject ?predicate ?object
       ?subject_label ?predicate_label ?object_label
WHERE {
  ...
}
```

Requirements:
- Use target = entity; the shared endpoint is the card identity and answer.
- direction = object means subjects vary and the common object is the answer; direction = subject means objects vary and the common subject is the answer.
- Group rows by predicate and shared endpoint.
- Require at least min_examples distinct triples per group; min_examples is configurable and defaults to two.
- Reject groups whose rows do not share one predicate, contain duplicate/conflicting rows, or do not have distinct varying endpoints.
- Require ?predicate so the relationship can be validated and optionally labeled in the prompt.
- Show the related endpoints on the front and only the shared endpoint answer on the back.
- If max_related is zero, show all related endpoints; otherwise randomly select up to max_related related endpoints during card generation. Reject a max_related value smaller than min_examples.
- Support optional subject_label, predicate_label, and object_label bindings using the existing label fallback conventions.
- Keep card data separate from Presentation rendering and CardView output as specified by the separate card-data/rendering bean.
- Update extension APIs, configuration validation, docs, templates, and behavioral tests.
