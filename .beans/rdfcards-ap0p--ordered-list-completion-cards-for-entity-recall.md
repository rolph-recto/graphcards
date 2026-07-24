---
# rdfcards-ap0p
title: Ordered-list completion cards for entity recall
status: completed
type: feature
priority: normal
created_at: 2026-07-24T01:09:42Z
updated_at: 2026-07-24T02:04:04Z
---

Add an ordered-list completion card type that tests a scheduled entity by showing a list grouped by ?group and ordered by ?position. The query selects exactly ?entity, ?group, ?position, and ?label. When testing an entity, RDFCards builds the full list for that entity’s group and replaces the row at that entity’s position with ?. The entity remains the card identity and FSRS schedule; the back shows the tested entity using its label.

Approved design:
- Query contract: SELECT ?entity ?group ?position ?label.
- Each row identifies one entity in one ordered list; ?group groups list members and ?position is a 1-based integer position.
- Each entity belongs to exactly one group per deck; each group has unique contiguous positions and at least two rows.
- Study-time rendering executes the full query without pre-binding ?entity, groups rows by ?group, then selects the target entity’s group in application code.
- The target entity’s row is replaced by ?; the back shows its ?label.
- Add deck-level window_size, default 5; window_size=0 means show the full list. For longer lists, show a contiguous window containing the tested entity, center it when possible, shift at boundaries, and show … for omitted items. Wrapping/cyclic sequences are out of scope.
- Labels are display text; entity identity remains the RDF IRI.

Implementation still needs concrete Pydantic/config validation, full-query execution path, window rendering details, CLI/web rendering, and behavior tests.



## Work Checklist

- [x] Implement ordered-list card model and rendering
- [x] Wire configuration, CLI, and web behavior
- [x] Add behavior-focused tests
- [x] Complete review/fix rounds
- [x] Run quality gates and commit scoped changes

## Summary of Changes

Implemented the registered ordered_list entity deck kind with strict Pydantic/domain validation, exact four-variable query enforcement, unbound full-query study rendering, contiguous centered/boundary-shifted windows, and label-backed answers while preserving entity FSRS identities. Added deck window_size validation/defaults, CLI and browser behavior coverage, documentation, and regression tests. Completed two review rounds plus a self-review; one domain reviewer remained unresponsive after bounded waits and reported no additional finding was available.
