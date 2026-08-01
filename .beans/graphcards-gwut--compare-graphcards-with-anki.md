---
# graphcards-gwut
title: Reach Feature Parity with Anki
status: in-progress
type: epic
priority: normal
created_at: 2026-07-31T16:23:31Z
updated_at: 2026-07-31T16:39:45Z
---

Bring Graphcards to parity with Anki core user-facing capabilities across study, authoring, collection management, media, statistics, and portability. Adapt the parity target to Graphcards' RDF and source-entity architecture; do not treat this as a byte-for-byte clone. The child beans under this epic define the implementation work.

## Plan

- [ ] Confirm the parity baseline and map each target capability to a child bean.
- [ ] Implement and verify the high-priority study, scheduling, browser, filtered-deck, and authoring capabilities.
- [ ] Implement and verify review controls, media, image occlusion, statistics, and portability capabilities.
- [ ] Run the full validation workflow and record any deliberate Graphcards-specific differences.

## Acceptance checks

- [ ] Every in-scope parity gap has an implementation child bean with a plan and acceptance checks.
- [ ] Core study and collection workflows cover the agreed Anki parity baseline.
- [ ] Tests validate the new behavior without legacy compatibility requirements.
- [ ] The final parity report lists shipped capabilities and deliberate differences.

## Discovery summary

The initial comparison identified gaps in review controls, daily limits, browser and filtered study, note and card authoring, deck options, media, statistics, import and export, backups, and multi-device sync.
