---
# rdfcards-covl
title: Add ordered-list and analogy templates
status: completed
type: feature
priority: normal
created_at: 2026-07-24T02:09:47Z
updated_at: 2026-07-24T02:14:58Z
---

Create reusable example templates demonstrating ordered-list and analogy card types.

- [x] Inspect current template and card-type configuration
- [x] Add ordered-list and analogy templates
- [x] Add or update tests/documentation
- [x] Run the required verification commands
- [x] Inspect git status and summarize changes

## Summary of Changes

Added the ordered-planets and analogy-capitals bundled templates, each with RDF data, SPARQL query, configuration, and usage README. Added CLI validation and integration coverage for template discovery, card counts, bounded ordered-list rendering, and both analogy hide modes. Full pytest, Ruff lint, Ruff format, and uv build checks pass; build artifacts and unrelated untracked workspaces were left unstaged.
