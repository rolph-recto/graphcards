---
# graphcards-bp8x
title: Remove redundant sync command
status: completed
type: task
priority: normal
created_at: 2026-08-03T01:26:38Z
updated_at: 2026-08-03T01:40:59Z
---

Remove the public graphcards sync command and its documentation because review state is generated and reconciled as part of normal deck-file operations. Preserve the internal initialization needed by status and web study, and update tests.



## Checklist

- [x] Remove the public `graphcards sync` command.
- [x] Keep automatic deck-state reconciliation for status and web startup.
- [x] Update documentation and tests.
- [x] Run the required validation commands.

## Notes

Implementation is complete in the working tree. The user confirmed the commit.



## Summary of Changes

Removed the public `graphcards sync` command. Status and web startup retain automatic review-state initialization and refresh behavior. Updated user documentation, storage error messages, and regression tests.
