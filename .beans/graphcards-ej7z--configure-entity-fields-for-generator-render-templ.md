---
# graphcards-ej7z
title: Configure entity fields for generator render templates
status: completed
type: feature
priority: normal
created_at: 2026-08-03T02:59:26Z
updated_at: 2026-08-03T06:01:39Z
---

Implement configurable Entity field selection for generator render templates.

## Checklist

- [x] Inventory render roles for all generators.
- [x] Add typed Pydantic render configuration with direct-field validation.
- [x] Define fallback and partial-map precedence.
- [x] Resolve values and document single-entity and collection render contexts.
- [x] Update built-in and bundled/custom templates.
- [x] Preserve semantic payloads, identity, scheduling, history, and review state.
- [x] Add behavior and JSON/TOML/YAML parity tests.
- [x] Update authoring and API documentation.
- [x] Run the required checks and inspect git status.

## Summary of Changes

- Added typed per-generator render slot maps with direct top-level Entity field validation.
- Updated each generator template to use its own slots, with explicit slots overriding fallback chains and omitted slots using fallbacks.
- Resolved slots before Jinja rendering for single entities, collections, rows, and cloze contexts.
- Preserved semantic exercise payloads, CardKey identity, scheduling, history, and review state.
- Updated bundled/demo decks, documentation, and behavior tests across JSON, TOML, and YAML.
- Verified pytest, Ruff, format, build, template preflight, and bean integrity.

## Correction

Simplify the presentation contract after review: use per-generator render slots declared by each exercise type and referenced by its built-in template. Remove the common front/back/label role model and unnecessary generic aliases.

## Follow-up

Remove truthiness filtering from render fallback resolution. Every slot uses the first present field, and no slot has special truthy behavior.

## Follow-up Result

Removed all truthiness filtering. Every slot now selects the first present fallback field, including empty, false, zero, and null values.

## Follow-up

Use frozen Pydantic v2 models for render-facing context values. Keep dataclasses only for parser, aggregate, and web structures that are outside render/configuration domain.

## Follow-up Result

Converted the render-facing EntityRenderValue and ClozeRenderValue from dataclasses to frozen Pydantic v2 models. Preserved direct Entity field access, safe template attribute handling, cloze whitespace, and immutability. Internal parser, runtime aggregate, and web dataclasses remain unchanged because they are not render/configuration models. Required pytest, Ruff, format, build, bean, and diff checks pass.

## Follow-up

Remove the cloze-specific render value wrapper. Expose cloze_id, cloze_value, front, and back directly in the template context, and verify that EntityRenderValue is the only render value model.

## Follow-up Result

Removed ClozeRenderValue entirely. Cloze templates now receive cloze_id, cloze_value, front, and back as direct context values. EntityRenderValue is the only render value model. Full tests, Ruff, format, build, bean integrity, and diff checks pass.

## Follow-up

Update bundled JSON/TOML/YAML template decks to include explicit front_template and back_template examples that reference each generator’s logical render slots. Update template README guidance for the direct cloze context.

## Follow-up Result

Updated all bundled and demo JSON, TOML, and YAML decks with explicit slot-based front_template and back_template examples. Collection templates use logical slots such as choice_label, related_label, row_label, candidate_label, and item_label; cloze templates use direct cloze values and entity_label. All 33 deck files load successfully and required checks pass.

## Follow-up

Remove redundant front_template and back_template entries from bundled/demo decks. Rely on each exercise generator’s built-in slot-based defaults and keep only render mappings in the example decks.

## Follow-up Result

Removed all redundant front_template and back_template entries from bundled and demo decks. The examples now rely on built-in generator templates and retain only render mappings. Updated cloze template documentation accordingly. All required checks pass.
