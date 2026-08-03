---
# graphcards-lwtw
title: Migrate GraphCards to a backend-free PWA and Electron app
status: draft
type: epic
priority: high
created_at: 2026-08-02T19:33:44Z
updated_at: 2026-08-02T19:33:44Z
---

# Migrate GraphCards to a backend-free PWA and Electron app

## Summary

Replace the Python and Flask application with one React and TypeScript application. Ship it as an offline-capable static PWA for current Chromium browsers and as a signed Apple Silicon Electron application. Store application data in IndexedDB. Transfer data between installations with manual archive export and import.

Use Zod for configuration and domain validation. Use `ts-fsrs` for browser-native FSRS scheduling.

## Architecture and interfaces

- Use pnpm, React, TypeScript, Vite, React Router, Tailwind CSS, Vitest, Playwright, and Dexie.
- Replace the Python package, Flask routes, Jinja pages, SQLite repository, CLI, `pyproject.toml`, and `uv.lock`.
- Update `AGENTS.md` to require Zod, pnpm, TypeScript checks, and the new build commands. Keep the Beans and commit rules.
- Use hash-based routes so the same renderer works on static hosts and with the Electron application protocol.
- Define strict Zod schemas for configuration, decks, entities, groups, all exercise-generator types, FSRS state, settings, review records, archives, and platform messages.
- Add a required UUID `id` to each deck document. Use it as the persistent deck identity. Keep `name` as display metadata.
- Replace custom Jinja execution with a restricted template interpreter. Support the documented variables, field access, loops, conditions, `default`, `is defined`, whitespace preservation, and automatic escaping. Reject unsupported syntax. Sanitize rendered HTML before DOM insertion.
- Define a typed `AppError` union for import, validation, template, storage, scheduling, archive, and platform failures. Convert parser, Zod, IndexedDB, FSRS, and corrupt-data failures at subsystem boundaries.

## Deck import, generation, and export

- Import one ZIP that contains exactly one JSON, TOML, or YAML deck document and its relative media assets.
- Reject duplicate fields, unsafe YAML features, invalid references, unsafe ZIP paths, duplicate archive entries, unsupported media, and missing assets.
- Validate and generate all cards before an IndexedDB change.
- On first import, create the deck and its initial FSRS cards.
- On re-import with an existing deck UUID, replace content and media in one transaction. Preserve schedules for unchanged entity IDs. Mark removed entities inactive and retain their reviews. Reactivate a returned entity with its prior schedule.
- Port every generator, renderer, preview, queue rule, daily limit, study mode, suspension action, search expression, sort option, history view, and statistic from the current application.
- Export a deck as a ZIP in the user-selected JSON, TOML, or YAML format. Preserve semantic data and template whitespace. Do not promise source comments or original formatting. Reject an export format when its data model cannot represent the deck and recommend JSON.

## IndexedDB persistence

Create versioned Dexie stores for:

- `decks`: normalized deck document, source format, timestamps, and active revision.
- `media`: compound deck and path key, blob, media type, and digest.
- `cards`: compound deck and entity key, `ts-fsrs` card state, due time, active and suspension state, timestamps, and optimistic revision.
- `reviews`: immutable UUID, deck and entity indexes, rating, UTC timestamp, duration, interval data, and retrievability.
- `deckSettings`: daily limits and queue settings by deck UUID.
- `meta`: database schema version and application metadata.

Use Dexie transactions for imports, reviews, suspension changes, settings, and restores. Check the card revision before each review to reject stale updates. Use `BroadcastChannel` to refresh other tabs after mutations. Use a browser lock for deck replacement and full archive restore.

Request persistent browser storage. Show a durable warning if the browser denies it. Show quota use and archive guidance in application settings.

## Backup and restore

- Define a versioned `.graphcards.zip` archive with a manifest, normalized deck documents, media, cards, reviews, settings, and SHA-256 digests.
- Validate the complete archive and all cross-record references before a write transaction.
- Restore atomically. Do not partially replace the current library after a validation or storage failure.
- Require explicit confirmation before a full restore replaces existing IndexedDB data.
- Keep PWA and Electron libraries separate. Use full archive export and import for manual transfer.

## React PWA

- Replace server-rendered pages with routes for the deck list, study session, deck status, card detail, history, generator previews, import, export, and settings.
- Keep study sessions in application memory. Persist each rating immediately.
- Preserve the current card-status filters, search grammar, pagination, bulk suspension, queue controls, daily limits, advanced study modes, and historical analytics.
- Add loading, empty, validation-error, storage-error, and recovery views.
- Use a generated service worker to precache the complete static application. Do not cache user data outside IndexedDB.
- Prompt before activation of an updated service worker. Do not reload during a study action, import, export, or restore.
- Provide an installable manifest, icons, offline startup, and an HTTPS-ready static build.

## Electron for macOS

- Package the same renderer with Electron Forge for `darwin-arm64`.
- Load packaged content through a custom application protocol, not `file://`.
- Enable context isolation and renderer sandboxing. Disable Node integration, unexpected navigation, new windows, and unneeded permissions. Apply a strict Content Security Policy.
- Expose only typed preload methods to open and save deck ZIPs and full archives. Do not expose raw IPC, arbitrary paths, Node modules, or general filesystem access.
- Add native Import, Export, Backup, Restore, and Quit menu actions.
- Provide local development packaging and local signed and notarized release commands. Read Apple credentials from environment variables. Do not add publishing or automatic-update infrastructure.

## Test plan

- Port behavior tests for each deck format, generator, cloze parser, image occlusion, template rule, scheduling rule, daily limit, search expression, status view, and history calculation.
- Add property tests for Zod schemas, entity references, generator output, queue selection, archive decoding, and corrupt IndexedDB records.
- Test semantic JSON, TOML, and YAML round trips, unsupported cross-format values, ZIP path attacks, missing media, duplicate entries, and invalid deck UUIDs.
- Test initial import, re-import with schedule retention, entity removal and return, transaction rollback, stale reviews, concurrent tabs, suspensions, settings, and archive replacement.
- Add React tests for deck import, study and rating, practice mode, status filtering, card details, history, export, restore confirmation, storage warnings, and error recovery.
- Add Playwright tests that load the PWA offline after its first visit and complete a study flow without network access.
- Add Electron smoke tests for startup, persistent IndexedDB, native import and export, preload validation, blocked navigation, and disabled Node access.
- Standardize local checks as `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm test`, `pnpm test:e2e`, `pnpm build:pwa`, and `pnpm make:mac`.

## Assumptions

- Current SQLite schedules and review history do not migrate.
- The Python CLI and workspace scaffolding commands do not remain.
- There is no in-app deck editor. Users edit exported JSON, TOML, or YAML files and re-import the ZIP.
- The new deck UUID is required. Existing deck files must receive one before import.
- The supported template subset is the compatibility contract. Exact Jinja compatibility is not required.
- The PWA and Electron app do not synchronize automatically.
- Chromium and Apple Silicon macOS are the first-release targets.
- Static hosting, release publication, and auto-update services are outside this migration.

## Implementation work

- [ ] Replace the Python project foundation with the pnpm, React, TypeScript, Vite, and Electron foundation.
- [ ] Port deck parsing, Zod validation, generators, rendering, scheduling, search, and analytics.
- [ ] Implement IndexedDB storage, transactional updates, concurrency control, and corruption handling.
- [ ] Implement deck ZIP import and export plus full archive backup and restore.
- [ ] Rebuild the complete web interface as an offline PWA.
- [ ] Add the secure Apple Silicon Electron wrapper and local signing flow.
- [ ] Port and expand behavior, property, PWA, and Electron tests.
- [ ] Remove the Python, Flask, SQLite, CLI, and uv implementation after parity checks pass.
- [ ] Update documentation, examples, deck UUIDs, and repository instructions.
