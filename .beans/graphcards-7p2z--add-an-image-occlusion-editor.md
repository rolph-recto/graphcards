---
# graphcards-7p2z
title: Add an image occlusion editor
status: todo
type: task
priority: normal
tags:
    - anki-gap
    - delegated
created_at: 2026-07-31T16:32:58Z
updated_at: 2026-07-31T17:32:39Z
parent: graphcards-gwut
---

Add an editor for image occlusion cards.

## Plan

- [ ] Extend the image occlusion model for rectangle, ellipse, and polygon shapes.
- [ ] Add hide-all and hide-one mask modes.
- [ ] Add a browser editor for selecting, moving, resizing, grouping, and deleting shapes.
- [ ] Add undo and redo in the editor.
- [ ] Define how edited occlusions are saved in the source-file workflow.
- [ ] Add rendering, validation, editor, and asset-security tests.
- [ ] Run the project validation commands.

## Acceptance checks

- A learner can create and edit occlusion shapes.
- Both mask modes render correctly.
- Undo and redo restore shape state.
- Deck-relative assets stay protected.

## Scope and user flows

- [ ] Define the create flow for a new image occlusion card.
- [ ] Define the open and edit flow for an existing card.
- [ ] Let the user add rectangle, ellipse, and polygon shapes.
- [ ] Let the user select, move, resize, group, ungroup, and delete shapes.
- [ ] Let the user switch between hide-all and hide-one mask modes.
- [ ] Define save, cancel, reload, and unsaved-change flows.
- [ ] Define pointer, keyboard, focus, and multi-select behavior.
- [ ] Define empty-image, invalid-shape, and failed-save states.

## Implementation phases and affected areas

- [ ] Phase 1: Define the canonical occlusion model and validation rules.
- [ ] Phase 2: Add shape editing state, selection state, and undo/redo history.
- [ ] Phase 3: Build the browser editor and its image-coordinate overlay.
- [ ] Phase 4: Connect editor state to source-file save and card rendering.
- [ ] Phase 5: Add security checks, error mapping, and focused tests.
- [ ] Update the domain model and Pydantic v2 validation.
- [ ] Update the storage or API boundary for load and save operations.
- [ ] Update editor templates, browser behavior, and Tailwind styles.
- [ ] Update image loading, source-relative asset handling, and render paths.
- [ ] Keep generated assets and committed build output out of the change unless the implementation requires them.

## Dependencies and sequencing

- [ ] Confirm the image, card, source-file, renderer, and asset contracts before implementation.
- [ ] Implement the canonical shape schema before editor gestures.
- [ ] Implement serialization and validation before save actions.
- [ ] Implement shape commands before undo and redo.
- [ ] Implement editor state before connecting the save API.
- [ ] Add rendering checks after the stored shape format is stable.
- [ ] Add asset security checks before image upload or image reload paths.
- [ ] Run focused tests after each phase, then run the project validation commands.

## Data/API and migration decisions

- [ ] Choose and document image-relative coordinates and rounding rules.
- [ ] Define shape fields for type, stable ID, geometry, order, and grouping.
- [ ] Define polygon point rules, minimum shape sizes, and valid bounds.
- [ ] Define the hide-all and hide-one mode representation.
- [ ] Define the load and save request and response shapes.
- [ ] Define an explicit format version for persisted occlusion data.
- [ ] Decide if current image occlusion data needs a migration and record the migration or no-op decision.
- [ ] Define how missing, unknown, or invalid fields fail validation.
- [ ] Define whether save is atomic and how a failed save preserves the editor state.

## Security and error handling

- [ ] Allow only supported image formats and enforce image size and dimension limits.
- [ ] Reject source-relative asset paths that escape the allowed source directory.
- [ ] Prevent unsafe active content from being loaded as an image asset.
- [ ] Enforce limits on shape count, polygon points, and request size.
- [ ] Map Pydantic, RDF parser, and storage corruption failures to user-facing errors.
- [ ] Keep parser, storage, and filesystem details out of browser error messages.
- [ ] Preserve the last valid editor state when load, validation, or save fails.
- [ ] Log enough context for diagnosis without logging image contents or sensitive paths.

## Focused test strategy

- [ ] Test model validation for every shape type, mask mode, bound, and malformed value.
- [ ] Test coordinate conversion, polygon normalization, grouping, and draw order.
- [ ] Test undo and redo across add, edit, move, resize, group, and delete commands.
- [ ] Test serialization, deserialization, version handling, and migration decisions.
- [ ] Test save and reload through the source-file workflow.
- [ ] Test rendering for both mask modes and all supported shape types.
- [ ] Test browser flows for selection, keyboard actions, focus, and unsaved changes.
- [ ] Test asset path, format, size, content, and request-limit failures.
- [ ] Test user-facing mappings for validation, parser, and storage failures.
- [ ] Run `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build` after implementation.

## Definition of done

- [ ] A user can create, edit, save, reload, and render an image occlusion card.
- [ ] Rectangle, ellipse, and polygon occlusions work with both mask modes.
- [ ] Selection, movement, resizing, grouping, deletion, undo, and redo work as defined.
- [ ] Stored data passes validation and follows the chosen version and migration rules.
- [ ] Source-relative assets remain inside the allowed source directory.
- [ ] Unsafe or oversized assets and malformed data receive safe user-facing errors.
- [ ] Focused behavior, rendering, editor, migration, and security tests pass.
- [ ] All project validation commands pass with no unrelated file changes.
- [ ] The acceptance checks above are verified against the completed implementation.
