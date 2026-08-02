---
# graphcards-dvoo
title: Add editable deck status settings
status: completed
type: task
priority: normal
created_at: 2026-08-02T16:49:24Z
updated_at: 2026-08-02T16:58:20Z
---

Move queue and daily-limit information into a Deck status tab. Add a form that lets users edit the deck daily limits and persist the values. Verify the behavior with web and storage tests.

## Checklist

- [x] Add a Deck status tab.
- [x] Move queue and daily-limit content into the tab.
- [x] Add editable daily limits and persistence.
- [x] Add behavior tests.
- [x] Run the required checks.

## Summary of Changes

Added a Deck status tab with queue metrics and editable daily limits. Persisted per-deck overrides in SQLite and applied them to web, CLI, and study scheduling. Added behavior tests and passed the required checks.
