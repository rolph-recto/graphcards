---
# graphcards-60os
title: Hypothesis property testing for models and web server
status: todo
type: task
created_at: 2026-07-24T20:09:55Z
updated_at: 2026-07-24T20:09:55Z
---

Add Hypothesis-based property testing for GraphCards data models, persistence boundaries, and web server behavior.

Tooling:
- Add Hypothesis to the development dependency group and keep uv.lock updated.
- Add reusable strategies for valid and invalid RDF identifiers, CardKeys, labels, card data, configuration fragments, stored cards, and URL/form inputs.
- Use bounded examples and deterministic test settings suitable for the repository quality gates.

Data-model and domain properties:
- CardKey construction and N3 serialization are round trips for valid entity and triple identities.
- Entity and triple identities remain distinct; triple term order is significant; canonical digests are deterministic and namespace-correct.
- Invalid entity terms, blank-node identities, non-IRI subjects/predicates, malformed N3 terms, and wrong target bindings are rejected with repository-facing validation errors.
- Frozen/Pydantic models reject mutation and preserve validated invariants after model copies.
- Multiple-choice generated displays contain the correct answer exactly once, contain no duplicate choices, respect max_choices, and select only from the highest available priority tiers before lower tiers.
- Ordered-list generated displays preserve valid contiguous positions, show exactly one hidden target, keep the target answer on the back, and produce valid bounded windows.
- Analogy generated displays preserve a distinct source triple with the matching predicate and derive the hidden answer consistently.
- Storage synchronization is idempotent for identical presentations, preserves global card identity and per-deck membership semantics, and does not create duplicate active memberships.
- Persisted card and review data can be decoded back into equivalent domain values; suspend/resume transitions preserve scheduling and review history invariants.

Web-server properties:
- Malformed query parameters, form fields, encoded values, CSRF tokens, session tokens, card IDs, and pagination inputs produce controlled client errors rather than 500 responses.
- Invalid or missing CSRF/session/card credentials do not mutate sessions, memberships, schedules, or review history.
- A valid study lifecycle obeys state transitions: session start creates a session, reveal is required before rating, valid rating records exactly one review, and stale or repeated actions are rejected without duplicate reviews.
- Refreshing a study page preserves the current card and session state; navigation does not unexpectedly advance or review a card.
- Suspended cards are excluded from active study sessions and suspension actions do not create reviews.
- Status filters, sorting, date ranges, and pagination remain safe and return valid responses for generated combinations, including empty results.
- User-controlled labels, reasons, and query values are escaped in HTML and cannot inject markup or alter form/session state.
- Valid requests return only documented status classes and preserve repository invariants across repeated or stale requests.

Prefer properties that assert domain and HTTP behavior rather than exact HTML layout. Keep focused example-based tests for specific presentation wording and route details.
