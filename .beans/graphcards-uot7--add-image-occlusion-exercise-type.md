---
# graphcards-uot7
title: Add image occlusion exercise type
status: completed
type: feature
priority: normal
created_at: 2026-07-31T00:35:44Z
updated_at: 2026-07-31T01:44:47Z
---

Add an Anki-inspired image occlusion exercise type. Users should view an image with hidden marked regions and recall the hidden content.

## Plan

- [x] Inspect the current exercise model, storage, authoring flow, review flow, and test patterns.
- [x] Define the image occlusion data model and validation rules.
- [x] Add authoring support for an image and one or more rectangular occlusion regions.
- [x] Add review support that hides one target region and checks the users answer.
- [x] Add progress, scoring, and next-card behavior that match existing exercise types.
- [x] Add user-facing error handling for invalid images, regions, and stored data.
- [x] Add behavior tests for model, authoring, review, persistence, and edge cases.
- [x] Update the Tailwind-built stylesheet and user documentation if needed.
- [x] Run the required checks: pytest with warnings as errors, Ruff check, Ruff format check, and uv build.

## Scope and Design

- Use rectangles only in the first version. Keep polygons out of scope.
- Use the current self-rating flow. Keep typed answer checks out of scope.
- Store the image as a deck-relative local raster asset path in the exercise configuration. Call the field image_path.
- Store each occluded part as its own entity. Each part stores answer data, such as its label. It does not store the image ID or its position.
- Keep all region values in the range 0 to 1. Require positive width and height.
- Create one FSRS card for each occluded-part entity. Use the part entity ID as the card identity. Require each target entity to have one image-occlusion placement in the first version.
- Show the image with one target region hidden on the front. Show the image with the region visible and the answer label on the back.
- Keep image uploads, image editing, OCR, polygon masks, and typed grading out of the first version.

## Architecture Plan

- Add Pydantic v2 models for image paths, occlusion target entities, occlusion placements, and image occlusion exercises.
- Register an image occlusion generator with the existing generator registry.
- Validate exercise image paths, duplicate target IDs, bounds, positive sizes, and target references before deck sync.
- Keep the existing one-card-per-entity storage model. The target entities make each occlusion a stable card target.
- Derive generator targets from the exercise occlusion placements. Update reference checks, status labels, and ordering for image-occlusion target entities.
- Replace the text-only card view contract with a safe structured view for text and image occlusion content.
- Keep templates from receiving raw unsafe HTML.
- Add a deck-scoped image asset route. Resolve paths against the deck directory, reject traversal, reject unsupported media types, and translate missing or unreadable files to repository error types.
- Update the study page and Tailwind source to draw image regions as overlays.
- Add accessible answer text and keep the normal reveal and rating flow.

## Test Plan

- Test valid and invalid region geometry with Pydantic behavior tests.
- Test generator selection, one card per region, stable card keys, and deterministic rendering.
- Test deck-relative asset serving, traversal rejection, missing files, unsupported files, and storage failures.
- Test study reveal, rating, practice next, suspension, and status views for occlusion target entities.
- Test JSON, TOML, and YAML parity and the example template.

## Delivery Order

- [x] Add occlusion target entities and occlusion placement models.
- [x] Add the image occlusion generator and target reference checks.
- [x] Add safe asset serving and structured study rendering.
- [x] Add examples, tests, and documentation.
- [x] Run pytest with warnings as errors, Ruff check, Ruff format check, and uv build.

## Notes

The current app stores one FSRS card per entity, which fits this design because each occluded part is an entity. The image occlusion work must still add structured image content to the card view.

## Jinja Template Contract

The image occlusion generator can expose these template values:

- image_url: a safe deck-scoped URL for the image.
- image_alt: accessible image text.
- target: the answer entity.
- placement: the target rectangle with left, top, width, and height percentages.
- front_template and back_template: HTML fragments for the image card.

Example front template:

```jinja
<figure class="image-occlusion">
  <img src="{{ image_url|e }}" alt="{{ image_alt|e }}">
  <span class="image-occlusion__mask"
        style="left: {{ placement.left }}%; top: {{ placement.top }}%;
               width: {{ placement.width }}%; height: {{ placement.height }}%;"
        aria-label="Hidden answer"></span>
</figure>
```

Example back template:

```jinja
<figure class="image-occlusion">
  <img src="{{ image_url|e }}" alt="{{ image_alt|e }}">
  <span class="image-occlusion__answer"
        style="left: {{ placement.left }}%; top: {{ placement.top }}%;
               width: {{ placement.width }}%; height: {{ placement.height }}%;">
    {{ target.answer|e }}
  </span>
</figure>
```

The renderer must validate the numeric placement values and escape text. The study page must render this content as a trusted card fragment or structured view. It must not print arbitrary deck text as raw HTML.

## Progress

- [x] Enable HTML in Jinja card templates while autoescaping inserted values.
- [x] Render generated card fragments in study, card status, and card detail views.
- [x] Allow same-origin images in the web content security policy.
- [x] Add tests for HTML output, value escaping, and study-page rendering.

The image-specific generator, asset route, and image overlay styles are complete.

## Summary of Changes

Implemented the image occlusion exercise type with normalized rectangular targets, one FSRS card per target entity, escaped Jinja HTML rendering, safe deck-scoped image serving, Tailwind overlay styles, JSON/TOML/YAML examples, documentation, and behavior tests. Required checks pass.
