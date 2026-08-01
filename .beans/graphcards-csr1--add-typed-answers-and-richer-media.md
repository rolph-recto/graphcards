---
# graphcards-csr1
title: Add typed answers and richer media
status: todo
type: task
priority: normal
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:58Z
updated_at: 2026-07-31T17:33:19Z
parent: graphcards-gwut
---

Add typed-answer grading and media support for language study.

## Plan

- [ ] Extend card views with typed-answer fields and comparison rules.
- [ ] Add a safe media reference model for audio, video, and images.
- [ ] Add media routes with type and path validation.
- [ ] Add browser playback and temporary microphone recording where supported.
- [ ] Add a media check for missing and unused files.
- [ ] Add tests for answer comparison, safe media paths, and media failures.
- [ ] Run the project validation commands.

## Acceptance checks

- A learner can type an answer before reveal.
- The UI shows useful answer differences.
- Safe media files play in a card.
- Unsafe and missing media paths fail safely.

## Elaborated plan

### Scope and user flows

- [ ] Define the learner flow: open a card, focus the typed-answer field, submit before reveal, then show the result and reveal controls.
- [ ] Define comparison feedback: show correct or incorrect state, useful differences, accepted answer variants, and an accessible text summary.
- [ ] Define the media flow: render approved audio, video, and image references in a card; show a clear fallback for missing, unsupported, or blocked media.
- [ ] Define the author or import flow for answer rules and media references, including the media check report for missing and unused files.
- [ ] Keep temporary microphone capture limited to supported browsers and the current card flow; define cancel, permission-denied, and cleanup behavior.

### Implementation phases and affected areas

- [ ] Phase 1: define Pydantic v2 answer, comparison-result, media-reference, and media-check models plus domain error mappings.
- [ ] Phase 2: implement deterministic typed-answer normalization and comparison rules, with no UI or storage logic in the grader.
- [ ] Phase 3: implement media resolution and routes in the configured media root, including content type, size, and path checks.
- [ ] Phase 4: connect card API or view models and templates to typed answers, comparison feedback, media playback, and temporary recording.
- [ ] Phase 5: add media diagnostics, remove temporary recordings after use, document the new contracts, and complete focused validation.
- [ ] Review affected card or domain, storage, web route, template or static client, media-check, and test areas before implementation starts.

### Dependencies and sequencing

- [ ] Agree on answer and media schemas before changing storage or API payloads.
- [ ] Implement and test pure answer grading before wiring form submission or browser feedback.
- [ ] Implement media validation and resolution before adding playback controls or recording integration.
- [ ] Apply storage or migration decisions before importing or serving new card data.
- [ ] Add API error mapping before UI work so the UI can handle every expected failure.
- [ ] Run the media check after reference extraction is available, then finish with the repository validation commands.

### Data/API and migration decisions

- [ ] Choose the canonical persisted shape for typed answers: answer mode, accepted answers, normalization options, and optional prompt metadata.
- [ ] Choose the canonical media-reference shape: media kind, logical identifier or relative path, declared type, and optional presentation metadata.
- [ ] Define submission and result contracts for raw input, normalized input, match state, difference details, and reveal behavior.
- [ ] Define media-serving and media-check contracts without exposing filesystem paths or unused internal fields.
- [ ] Define a deterministic migration or import transformation for current stored cards that lack the new fields, with empty or explicit defaults.
- [ ] Decide media size, duration, and supported-type limits, and record them in configuration validated by Pydantic v2.
- [ ] Decide whether answer variants and media references are stored inline or by stable identifiers, and document the choice before implementation.

### Security and error handling

- [ ] Normalize and validate every media reference against the configured media root; reject traversal, absolute paths, invalid encoding, and disallowed symlinks.
- [ ] Allow only an explicit media type and extension allowlist, and verify the served content type from trusted metadata or file inspection.
- [ ] Enforce input, file-size, and recording-duration limits before processing; clean up temporary recording files on success and failure.
- [ ] Escape answer text and difference output so learner input cannot inject HTML or script content.
- [ ] Translate Pydantic, RDF parser, storage corruption, missing media, and unsupported media failures into repository user-facing error types.
- [ ] Return safe, stable API errors without filesystem paths, stack traces, or sensitive card data.
- [ ] Handle browser permission denial, unsupported recording, interrupted playback, and unreadable files with recoverable UI states.

### Focused test strategy

- [ ] Test exact matches, configured variants, normalization rules, empty input, Unicode, whitespace, punctuation, and near-miss difference output.
- [ ] Test Pydantic validation for invalid answer rules, media kinds, paths, types, limits, and malformed API payloads.
- [ ] Test media path traversal, absolute paths, symlinks, missing files, wrong types, oversized files, and unused-file detection.
- [ ] Test route or API success and each mapped failure without leaking internal paths or exception details.
- [ ] Test migration or import transformation for cards with no new fields and cards with partial or invalid new data.
- [ ] Test template or client behavior for submit-before-reveal, feedback accessibility, playback fallback, recording permission denial, cancel, and cleanup.
- [ ] Keep tests behavior-focused and avoid tests that assert legacy internal shapes.

### Definition of done

- [ ] A learner can type an answer before reveal and receive deterministic, understandable feedback.
- [ ] Approved audio, video, and image media render or play from safe references.
- [ ] Missing, unused, unsupported, and unsafe media are reported or rejected with user-facing errors.
- [ ] Temporary microphone recording works where supported and leaves no orphaned temporary files.
- [ ] Canonical data or API contracts and the migration or import path are documented and covered by tests.
- [ ] Focused tests pass, then `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build` pass; rebuild Tailwind if web templates or CSS change.
- [ ] `graphcards-csr1` remains in `todo` until implementation and validation are complete.
