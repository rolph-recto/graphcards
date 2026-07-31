---
# graphcards-cpha
title: Change card identity to deck and entity
status: completed
type: feature
priority: normal
created_at: 2026-07-30T20:16:38Z
updated_at: 2026-08-03T06:13:29Z
---

Implement graphcards-yyfw: change card identity from (deck, generator, entity) to (deck, entity), with no backwards compatibility. Keep the digest as a derived storage ID initially. Update generation, rendering, storage, web flows, and behavior tests. Run required checks.\n\n- [x] Inspect current card identity, generation, rendering, storage, and web flows\n- [x] Implement the new (deck, entity) identity and derived digest storage ID\n- [x] Update behavior tests and run required checks\n- [x] Inspect git status and report changes without committing


- [x] Commit bean and implementation after user confirmation

## Summary of Changes

Changed card identity to deck and entity. Storage now uses `(deck_id, entity_id)` composite keys and foreign keys. Removed the GraphCards `card_id` and the unused digest from persistence, domain records, web forms, CLI output, and application flows. Retained generator IDs on exercises, updated runtime generator selection, storage, rendering, web flows, documentation, and behavior tests. Required checks pass. The implementation and bean are committed.

## Review Fixes

Removed the web form length limit for entity IDs. Scoped review-log validation to the requested deck. Added regression tests for long entity IDs and cross-deck review isolation. Required checks pass. The implementation and bean are committed.
