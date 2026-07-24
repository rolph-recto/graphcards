---
# rdfcards-szrv
title: Give OrderedListPresentation rendering responsibility
status: completed
type: task
priority: normal
created_at: 2026-07-24T03:35:29Z
updated_at: 2026-07-24T03:50:52Z
---

Move ordered-list window construction and presentation-specific validation from OrderedListDeck into OrderedListPresentation without changing study output or card identities. Add focused tests, run quality gates, and commit.\n\n- [x] Move presentation construction/rendering responsibility\n- [x] Add focused behavior and validation tests\n- [x] Run repository quality gates\n- [x] Commit implementation and bean

## Summary of Changes\n\nMoved ordered-list window state, invariant validation, prompt construction, and front rendering into OrderedListPresentation. OrderedListDeck now groups query rows and delegates presentation construction. Internal structured fields are excluded from serialization, preserving the card_key/front/back shape. Added focused assertions and passed all repository quality gates.

## Delivery\n\n- [x] Squash the presentation-responsibility commit into its parent
