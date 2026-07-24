---
# graphcards-a4l3
title: Remove terminal study command
status: completed
type: task
priority: normal
created_at: 2026-07-24T04:59:40Z
updated_at: 2026-07-24T05:05:53Z
---

Remove the graphcards CLI study subcommand and terminal review execution path; keep web study through serve, update docs/help/tests, and preserve shared study services used by the web interface.



## Summary of Changes

- Removed the `graphcards study` CLI subcommand, terminal reveal/rating helpers, and terminal-study tests.
- Kept `graphcards serve` as the web-only study entry point and preserved shared study services.
- Updated README and bundled template instructions to use the web interface.
