---
# graphcards-yyfw
title: Investigate card-key digest versus entity-backed FSRS scheduling
status: completed
type: task
priority: normal
created_at: 2026-07-30T19:19:02Z
updated_at: 2026-07-30T20:08:10Z
---

Determine if the card-key digest is redundant when FSRS scheduling is mapped to an entity. Trace identity creation, persistence, lookup, migration, and review validation. Record the conclusion and any follow-up recommendation.\n\n- [x] Trace card-key digest creation and use\n- [x] Trace FSRS scheduling identity and storage\n- [x] Compare identity semantics and lifecycle\n- [x] Record findings and follow-up recommendation

## Summary of Findings

The digest is not an FSRS identifier. FSRS stores its schedule in card_json and uses its own integer card_id in review logs. GraphCards uses the SHA-256 digest as the cards.card_id primary key, as the foreign-key target for deck_cards and reviews, as generated-card dictionary keys, and as browser/session card handles. The scoped identity JSON remains the source of truth for deck, generator, and entity; the digest is a derived compact surrogate and integrity check.

The digest is therefore logically derivable and can be removed only with a natural/composite-key redesign. More importantly, the current identity includes generator_id, so changing the selected generator creates a new schedule for the same entity. If schedules must survive generator changes, the identity must become deck plus entity and generator selection must be separated from scheduling.

## Follow-up Plan: Use deck and entity as card identity

1. Change CardKey to contain only deck_id and entity_id.
2. Keep generator_id on generated exercises and runtime generator selection.
3. Generate one card key for each deck and entity pair.
4. Resolve the current selected generator from the entity when GraphCards renders a stored card.
5. Keep the digest as a derived storage and transport ID in the first change.
6. Update identity JSON, storage checks, status views, web forms, and study sessions.

7. Add behavior tests for generator changes. The same deck and entity must keep the same schedule.
8. Add behavior tests for deck scope. The same entity in two decks must have separate schedules.
9. Run the required test, lint, format, and build commands.
