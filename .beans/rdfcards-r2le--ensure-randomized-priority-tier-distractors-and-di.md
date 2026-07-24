---
# rdfcards-r2le
title: Ensure randomized priority-tier distractors and display order
status: completed
type: task
priority: normal
created_at: 2026-07-24T00:06:07Z
updated_at: 2026-07-24T00:22:51Z
parent: rdfcards-owde
---

Refine multiple-choice rendering so both layers of randomness are explicit and covered by behavior tests. For each priority tier, randomize candidate order before taking the remaining slots; exhaust higher-priority tiers before lower-priority tiers; then independently shuffle the complete retained set, including the correct answer, for display. Use the existing study-session RNG, preserve deterministic seeded tests, and avoid assuming one fixed ordering. Verify that repeated renders vary the selected tied distractor subset whenever the candidate pool permits, while priority boundaries remain intact.

## Summary of Changes

Implemented and merged in commit dd086e6 (source worktree commit 416ae03). Priority-tier candidates are randomized before retention, the retained choices are independently shuffled for display, and the existing study-session RNG is preserved across repeated CLI and browser card renders. Added model, integration, CLI, web, template, and documentation coverage for tied-subset variation, priority boundaries, correct-answer inclusion, and display-order randomness. Four independent review/fix rounds completed with no remaining findings; 218 tests, Ruff, formatting, and uv build passed.
