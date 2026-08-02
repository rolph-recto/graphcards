---
# graphcards-i131
title: Reject existing files in templates_paths
status: completed
type: bug
priority: normal
created_at: 2026-08-02T23:52:11Z
updated_at: 2026-08-02T23:53:57Z
---

Existing files listed in AppConfig.templates_paths must produce a ConfigError. Missing directories remain valid and contribute no templates. Add regression coverage for a file path and keep scaffold template discovery behavior explicit.



## Checklist

- [x] Reject existing non-directory template paths.
- [x] Add regression tests for config loading and direct template discovery.
- [x] Run focused and required validation checks.

## Summary of Changes

Reject existing non-directory `templates_paths` entries with user-facing configuration errors while preserving missing-directory behavior. Added regression coverage for config loading and direct template discovery.
