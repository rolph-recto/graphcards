---
# graphcards-cj0o
title: Rename ordered-list exercise type to missing-sequence-item
status: completed
type: task
priority: normal
created_at: 2026-07-29T17:31:49Z
updated_at: 2026-07-29T17:48:40Z
---

Rename the exercise type from ordered_list to missing_sequence_item across the new GraphCards codebase. Use the new name only. Do not add backwards compatibility aliases or tests.

- [x] Find all ordered_list references
- [x] Rename implementation identifiers and type values
- [x] Update examples and documentation
- [x] Update tests and fixtures
- [x] Run validation checks and inspect git status
- [x] Commit implementation and bean after explicit confirmation

## Summary of Changes

Renamed the exercise type to missing_sequence_item, renamed the Python generator and exercise classes, updated deck templates and documentation, updated tests and fixtures, and verified the project with pytest, Ruff, formatting, package build, and diff checks.
