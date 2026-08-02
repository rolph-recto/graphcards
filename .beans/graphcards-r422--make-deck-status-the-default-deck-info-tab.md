---
# graphcards-r422
title: Make Deck Status the default deck-info tab
status: completed
type: bug
priority: normal
created_at: 2026-08-02T17:56:50Z
updated_at: 2026-08-02T18:00:14Z
---

When a user visits /decks/<deck>/cards without an explicit tab, show the Deck status tab. Preserve explicit card-status navigation and redirects.

## Summary of Changes

The deck-info route now defaults CardStatusQuery to the Deck status tab. Card actions and explicit Card Status links preserve the card-status tab. Tests were updated to request Card Status explicitly where needed and to verify the new default.
