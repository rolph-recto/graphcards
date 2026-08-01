---
# graphcards-0eu1
title: Add advanced statistics and collection portability
status: todo
type: task
priority: normal
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:58Z
updated_at: 2026-07-31T17:33:44Z
parent: graphcards-gwut
---

Add deeper statistics and safe collection portability.

## Plan

- [ ] Add future-due, calendar, review-time, interval, retention, and hourly statistics.
- [ ] Add collection, deck, and filtered-search scopes.
- [ ] Add per-card history and exportable reports.
- [ ] Add text and packaged deck import and export.
- [ ] Add automatic backups, restore, and database checks.
- [ ] Define a sync protocol after note and card identities are stable.
- [ ] Add tests for report accuracy, package integrity, backup restore, and conflict handling.
- [ ] Run the project validation commands.

## Acceptance checks

- A learner can inspect future workload and retention.
- Statistics can use a deck or saved search.
- A collection can be backed up and restored.
- Import and export preserve content and scheduling.
- Sync conflicts do not lose reviews or edits.

## Scope and user flows

- [ ] Define the statistic set: future due, calendar, review time, interval, retention, and hourly activity.
- [ ] Define date, time zone, day boundary, and empty-result rules for every statistic.
- [ ] Define collection, deck, subdeck, and filtered-search scopes.
- [ ] Define the statistics flow: choose a scope and period, view a summary and trend, open card history, and export a report.
- [ ] Define the portability flow: create a backup or package, validate it, preview restore or import changes, apply the operation, and show the result.
- [ ] Define the sync flow: compare identities, show conflicts, keep review history, and require an explicit resolution.

## Implementation phases and affected areas

- [ ] Phase 1: write metric definitions, scope rules, package contracts, restore modes, and conflict rules.
- [ ] Phase 2: add domain and Pydantic v2 models for metrics, scopes, reports, packages, backups, and conflicts.
- [ ] Phase 3: add storage queries and aggregation services. Add indexes only when measured queries need them.
- [ ] Phase 4: add API operations and web views for statistics, history, report export, import, backup, validation, and restore.
- [ ] Phase 5: add text and packaged deck I/O, media handling, integrity checks, and migration steps.
- [ ] Phase 6: add sync after note and card identities are stable. Add conflict review and safe retry.
- [ ] Update affected areas together: domain, storage, API, web templates and Tailwind styles, import and export, backup and restore, sync, and user-facing errors.
- [ ] Keep long statistics and import work bounded. Add progress or clear status for operations that can take time.

## Dependencies and sequencing

- [ ] Decide note, card, deck, review, and media identities before package or sync work.
- [ ] Define schedule and review event semantics before calculating interval, retention, or review-time metrics.
- [ ] Build and test scope resolution before reuse in statistics, history, and report export.
- [ ] Define storage migrations before adding history or aggregate indexes.
- [ ] Build package manifest and integrity validation before import and restore.
- [ ] Complete backup and restore before sync. Use the backup as the recovery path.
- [ ] Gate each phase on accepted data and error contracts. Do not start sync until identity and conflict rules pass focused tests.

## Data/API and migration decisions

- [ ] Record the source fields for due date, review time, interval, rating, timestamp, deck, search match, and retention. Define how missing data is handled.
- [ ] Define metric formulas, rounding, buckets, sample limits, and time-zone conversion. Use one canonical time representation.
- [ ] Define request and response models for scope, period, pagination, report export, import preview, restore, and conflict resolution.
- [ ] Version report and package schemas. Include a manifest with schema version, collection metadata, counts, media list, and checksums.
- [ ] Define package contents: notes, cards, decks, scheduling, review history, filtered searches, and media. Mark optional content clearly.
- [ ] Choose text format rules for identifiers, tags, fields, newlines, Unicode, and duplicate records.
- [ ] Choose restore modes for a new collection, merge, and replace. Require a preview for merge and replace.
- [ ] Make migrations additive and repeatable. Store the migration version. Back up before a destructive migration.
- [ ] Define identity matching and conflict precedence. Preserve both review history and user edits when records conflict.
- [ ] Keep APIs explicit about partial results, unsupported schema versions, and rejected records.

## Security and error handling

- [ ] Treat text files, archives, media, and RDF input as untrusted.
- [ ] Reject path traversal, symlinks, unsafe archive entries, oversized files, decompression bombs, invalid checksums, and unsupported formats.
- [ ] Validate all external input with Pydantic v2 models and bounded sizes. Use parameterized storage queries.
- [ ] Translate Pydantic, RDF parser, package, and storage corruption failures into repository user-facing error types.
- [ ] Run import, restore, and migration in atomic transactions. Do not leave partial data after failure.
- [ ] Validate backups before restore. Preserve the original collection until restore succeeds.
- [ ] Avoid secrets and unnecessary personal data in packages, logs, and reports. Define media and sensitive-field rules.
- [ ] Limit statistics and history queries. Return a clear error when a request exceeds a safe limit.
- [ ] Define authorization checks for collection, import, restore, and sync operations.
- [ ] Make sync retries idempotent. Never silently discard reviews, edits, or unresolved conflicts.

## Focused test strategy

- [ ] Use fixed review fixtures to test each metric formula, boundary, bucket, and empty case.
- [ ] Test time-zone changes, daylight-saving transitions, date boundaries, and deterministic ordering.
- [ ] Test collection, deck, subdeck, and filtered-search scopes. Test no-match and invalid-scope cases.
- [ ] Test card history and report export for pagination, stable schema, and large but bounded data sets.
- [ ] Test text and package round trips with Unicode, tags, media, duplicate IDs, missing optional fields, and malformed records.
- [ ] Test manifest counts, checksums, schema versions, and rejected package entries.
- [ ] Test backup and restore for empty target, merge, replace, interrupted operation, corruption, and repeat restore.
- [ ] Test migration from each supported schema state and confirm data preservation.
- [ ] Test conflict cases where both sides change content, scheduling, and review history. Confirm explicit resolution.
- [ ] Test archive traversal, unsafe links, size limits, parser failures, storage corruption, and permission failures.
- [ ] Test API error mapping and user-visible messages.
- [ ] Run focused unit, integration, and API tests before the full project validation commands.

## Definition of done

- [ ] The statistics definitions, scopes, periods, and empty-result rules are documented and implemented.
- [ ] The web UI and API show statistics, card history, and exportable reports.
- [ ] Collection, deck, and filtered-search scopes produce the same results across UI, API, and reports.
- [ ] Text and package import and export preserve the agreed content, schedule, review history, and media.
- [ ] Backup validation and restore are atomic, repeatable, and recoverable.
- [ ] Migrations are versioned, tested, and safe for supported data.
- [ ] Sync uses stable identities, preserves reviews and edits, and reports conflicts.
- [ ] Security limits and user-facing error mappings are covered by tests.
- [ ] Required project validation commands pass: uv run pytest -W error, uv run ruff check ., uv run ruff format --check ., and uv build.
- [ ] Rebuild the committed Tailwind stylesheet when templates or source CSS change.
