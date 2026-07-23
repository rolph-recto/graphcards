---
# rdfcards-owde
title: Priority-aware multiple-choice distractor selection
status: todo
type: feature
priority: high
created_at: 2026-07-23T21:30:06Z
updated_at: 2026-07-23T21:30:06Z
---

Add optional choice priority tiers and a deck-level max choice count. Always include the correct answer, then exhaust higher-priority distractors before lower-priority ones; randomize ties within a tier. Open decisions: binding datatype, missing-value default, max choice default, and whether invalid values are presentation or configuration errors. Acceptance criteria: documented query contract, strict validation, deterministic seeded tests, and CLI/web parity.
