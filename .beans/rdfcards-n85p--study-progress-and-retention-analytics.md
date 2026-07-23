---
# rdfcards-n85p
title: Historical review analytics in the web UI
status: completed
type: feature
priority: normal
created_at: 2026-07-23T21:30:32Z
updated_at: 2026-07-23T22:53:04Z
---

Add a history section to the browser deck UI for trends that the existing status snapshot does not provide. Use immutable review records as the source of truth and show review volume over time, rating distribution and Again rate, study streaks, average interval growth, and FSRS retention or retrievability where available. Keep current active/new/due/future counts and per-card schedule details in status. Open decisions: exact charts and date range controls, local display timezone versus UTC storage, and treatment of suspended or inactive cards.

## Summary of Changes

Implemented and merged in commit 446e791. Added immutable review-history decoding and indexed queries, timezone-aware browser history views with selectable ranges, review-volume and rating summaries, streak and interval metrics, retrievability coverage, segmented rating visualization, and N3-safe card identity rendering. Existing status counts and schedule details remain available below the history section; generated example workspaces were kept untracked.
