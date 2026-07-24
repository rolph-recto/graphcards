---
# rdfcards-ynaa
title: Analogy cards for relational triple recall
status: completed
type: feature
priority: normal
created_at: 2026-07-24T01:09:35Z
updated_at: 2026-07-24T02:01:05Z
---

Add an analogy card type that tests an explicit target triple by showing an explicit source triple with the same relationship and hiding either the target object or target subject. Examples: Berlin : Germany :: Paris : ? and Berlin : Germany :: ? : France. The target triple remains the card identity and FSRS schedule; the hidden target term is the answer and the back shows it using a display label when available.

Approved design:
- Query contract: SELECT ?subject ?predicate ?object ?source_subject ?source_predicate ?source_object ?hide.
- ?subject, ?predicate, and ?object identify the target triple and are always fully bound.
- ?source_subject, ?source_predicate, and ?source_object provide the complete displayed analogy triple.
- Every target card must have at least one complete source triple in its query row; the source triple must be distinct from the target triple and is not itself a separate target card.
- ?hide is a literal enum with value subject or object and determines which target term is replaced by ?. The relation/predicate remains visible.
- The hidden target term itself supplies the answer; there is no separate ?answer binding.
- Each target triple is one scheduled card. If multiple valid target triples are returned, they produce separate cards and backs; duplicate rows for one target must agree on source triple, hide mode, and display metadata.
- Target and source predicates must match; learner-facing display labels are allowed.

Implementation still needs concrete Pydantic/config validation, label binding rules, CLI/web rendering, and behavior tests.

Clarification:
- Validation must reject a target triple that has no distinct source triple in its query row. The source triple is required to construct the analogy card, but it does not create a separate scheduled card.



## Work Checklist

- [x] Inspect existing card/query/config/CLI/web architecture
- [x] Implement analogy card validation, identity, scheduling, and rendering
- [x] Add behavior tests
- [x] Run review/fix rounds
- [x] Run quality gates and commit implementation



## Summary of Changes

Implemented the `analogy` deck kind for relational triple recall. It validates complete, distinct source triples with matching predicates and a strict `subject`/`object` hide literal; target triples alone define card identity and FSRS scheduling. Optional target/source label bindings render learner-facing analogy prompts and derived answers through the existing CLI and web study flows. Added unit, storage integration, CLI, and web behavior coverage. Completed two review rounds plus a follow-up fix round with no actionable findings; final quality gates pass with 238 tests.
