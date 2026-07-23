---
# rdfcards-owde
title: Priority-aware multiple-choice distractor selection
status: completed
type: feature
priority: high
created_at: 2026-07-23T21:30:06Z
updated_at: 2026-07-23T22:43:00Z
---

Add optional choice priority tiers and a deck-level max choice count. Always include the correct answer, then exhaust higher-priority distractors before lower-priority ones; randomize ties within a tier. Open decisions: binding datatype, missing-value default, max choice default, and whether invalid values are presentation or configuration errors. Acceptance criteria: documented query contract, strict validation, deterministic seeded tests, and CLI/web parity.

## Summary of Changes

Implemented and merged in commit dec68d9. Added optional xsd:integer ?priority bindings with zero default, strict validation, priority-tier distractor selection, a max_choices deck setting with default four choices, correct-answer retention, tie randomization, CLI/web parity, documentation, templates, and regression coverage. Generated example workspaces were kept untracked.
