---
# rdfcards-nljd
title: Rename project to GraphCards
status: completed
type: task
priority: normal
created_at: 2026-07-24T04:02:16Z
updated_at: 2026-07-24T04:11:29Z
---

Rename the project from rdfcards/RDFCards to graphcards/GraphCards across package metadata, import paths, CLI command, configuration/state defaults, documentation, templates, tests, and user-facing messages while preserving compatibility only where explicitly appropriate.



## Summary of Changes

Renamed the canonical package and CLI from rdfcards/RDFCards to graphcards/GraphCards, moved the source package to src/graphcards, updated imports, metadata, lockfile, config/state defaults, templates, demos, documentation, and tests. Card digest IDs now use the graphcards namespace as part of the completed rename.



## Follow-up

Updated the card digest domain-separation namespace from `rdfcards:` to `graphcards:` and added a regression assertion for the new digest.
