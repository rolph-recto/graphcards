---
# graphcards-o49w
title: Common-relation completion cards
status: completed
type: feature
priority: normal
created_at: 2026-07-24T19:52:30Z
updated_at: 2026-07-28T02:08:44Z
---

Add a common-relation completion card source that tests the shared endpoint of several triples.

Examples:

Object completion maps `europe` to `[france, germany, italy]`; the front lists those related
entities and asks for Europe. Subject completion uses the same direct mapping while reversing the
front presentation: `france` maps to `[germany, italy, spain]` and the front asks for France.

Configuration:

```json
{
  "id": "common-locations",
  "type": "common_relation",
  "direction": "object",
  "min_examples": 2,
  "max_related": 0,
  "relations": {
    "europe": ["france", "germany", "italy"]
  }
}
```

The strict entity-backed generator maps each target entity ID to an ordered list of related entity IDs.

Requirements:
- Use each target entity ID as the card identity and answer.
- direction = object displays related entities before the missing target; direction = subject displays the missing target before related entities.
- Require at least min_examples distinct related IDs per target; min_examples is configurable and defaults to two.
- Show related entity labels using label -> back -> answer -> id fallback.
- If max_related is zero, show all related IDs; otherwise select exactly min(max_related, group size) IDs during generation and preserve declaration order.
- Store selected IDs in semantic exercise data; rendering must not sample or reorder.
- Keep card data separate from presentation rendering and CardView output.
- Update validation, docs, templates, and behavioral tests for the direct target-to-list shape.

## Current Architecture Design

Implement only the strict entity-backed `deck.json` generator architecture. Typed generators are dispatched from validated JSON definitions, semantic `Exercise` data is generated before stateless Jinja rendering, and overlap keeps the repository's lexicographically-smallest generator-ID behavior. No TOML sources, SPARQL, RDF parsing/query bindings, migrations, compatibility shims, or retired extension APIs are in scope.

The `common_relation` generator maps each target directly to an ordered list of related entity IDs:
```json
{
  "id": "common-locations",
  "type": "common_relation",
  "direction": "object",
  "min_examples": 2,
  "max_related": 0,
  "relations": {
    "europe": ["france", "germany", "italy"]
  }
}
```

Each mapping key is target, card identity, and answer. Object direction asks for the shared target from related entities; subject direction reverses the presentation. Selection is performed during generation with the supplied RNG, preserving declaration order; the selected IDs are stored in the semantic payload and rendering never samples or reorders. Labels use `label -> back -> answer -> id`.

## Implementation Checklist

- [x] Add strict Pydantic models, generator registration, semantic payload generation, rendering, and deterministic preflight validation.
- [x] Add focused unit/property/CLI tests for dispatch, both directions, selection, payloads, fallbacks, validation, and runtime error translation.
- [x] Add README documentation and the bundled `common-relations/` deck.json/template example.
- [x] Run focused tests and all required `uv`/ruff/build checks.
- [x] Run independent behavioral, tests/edge-cases, validation/security, and API/docs reviews; fix all actionable findings.
- [x] Append `## Summary of Changes`, mark this bean completed, and commit scoped implementation plus bean changes.

## Summary of Changes

Implemented the strict entity-backed `common_relation` deck.json generator with object and subject directions, ordered capped selection, stable target-based identities, semantic payloads, fallback labels, custom template context, runtime validation, and exhaustive deterministic preflight coverage. Registered and exported the new Pydantic models, documented the schema and semantics, and added the bundled `common-relations/` template.

Added unit, property, CLI, malformed-input, runtime-error, and template validation coverage. Completed two independent review rounds covering behavior, tests/edge cases, validation/security, API/docs, and quality gates; fixed all actionable findings.

## Revision: Predicate Removed

The current implementation intentionally supersedes the predicate-bearing design above. `relations` is now a direct ordered mapping from each target entity ID to a list of related entity IDs:

```json
"relations": {
  "europe": ["france", "germany", "italy"]
}
```

Predicates are not configuration, semantic payload, validation, or template context. Relationship wording belongs in custom presentation templates. The default contexts are `target`, `related_entities`, and `direction`, and the default fronts render `related — ?` or `? — related`.

## Revision Summary

Removed the redundant predicate from the current implementation. `relations` now uses the direct target-to-ordered-list JSON shape; `CommonRelationGroup` and `predicate_id` were removed, default and custom template contexts no longer expose predicates, and relationship wording is presentation-owned. Added regression coverage for the obsolete nested shape and unavailable predicate context.

Validation for this revision: 169 tests passed, Ruff check/format passed, and the focused deck/property/CLI suite passed.
