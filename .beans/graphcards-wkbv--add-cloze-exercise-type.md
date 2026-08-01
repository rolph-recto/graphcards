---
# graphcards-wkbv
title: Add cloze exercise type
status: in-progress
type: feature
priority: normal
created_at: 2026-07-30T02:21:25Z
updated_at: 2026-07-30T18:19:07Z
---

Add a cloze exercise type for study cards.

Scope to define:
- The cloze source format and validation rules.
- The exercise data model and answer rules.
- The deck generation and presentation flow.
- The web UI behavior.
- Persistence, templates, documentation, and tests.

Plan:
- [ ] Define the cloze syntax and user behavior.
- [x] Map the existing exercise flow and extension points.
- [x] Define implementation tasks and test coverage.
- [ ] Review the plan with the user.

## Findings

- Exercise types use a registered Pydantic generator model.
- Each target entity produces one scheduled card.
- The generator stores semantic exercise data before it renders a front and a back.
- Deck loading validates JSON, TOML, and YAML with the same model.
- Card storage keeps generic identity data. No storage migration is needed.
- The web study page reveals the back and then accepts an FSRS rating. It does not collect typed answers.

## Proposed first slice

- Add a `cloze` generator that targets existing entities.
- Read the complete cloze sentence from the entity field named by `cloze_field`.
- Store answers in the entity text with stable markers such as `[[c1::Paris]]` and `[[c2::France]]`.
- Let `entities` contain either an entity ID string or an object with `id` and `cloze_ids`.
- A string selects every cloze in that entity. An object selects only its listed cloze IDs.
- Generate one card for each selected cloze.
- Hide only the selected cloze on the front. Show the other clozes. Show all clozes on the back.
- Include `cloze_id` in card identity so each selected cloze has its own study state.
- Keep typed answer entry and automatic grading out of this bean. Add a follow-up bean if the user wants typed recall.

## Implementation plan

- [ ] Confirm the marker syntax, multiple-marker behavior, and reveal-only scope.
- [x] Map the existing exercise flow and extension points.
- [ ] Add the Pydantic cloze generator and semantic exercise models.
- [ ] Extend `CardKey`, storage identity, and status views with `cloze_id`.
- [ ] Add parser validation and presentation error handling.
- [ ] Register the generator and expose its public types.
- [ ] Add JSON, TOML, and YAML deck examples.
- [ ] Add unit, integration, and property tests for valid and invalid cloze data.
- [ ] Document the format and limits in the README.
- [ ] Run the required checks: pytest with warnings as errors, Ruff, format check, and build.
- [ ] Inspect git status and report all changed files.
- [ ] Review the plan with the user.

## Example configuration

The entity stores the complete sentence and all answers. The generator selects clozes per entity:

```json
{
  "entities": [
    {
      "id": "capital-france",
      "cloze": "The capital of [[c1::France]] is [[c2::Paris]]."
    },
    {
      "id": "history-france",
      "cloze": "[[c1::1789]] marks the start of the French Revolution."
    }
  ],
  "exercises": [
    {
      "id": "fact-cloze",
      "type": "cloze",
      "cloze_field": "cloze",
      "entities": [
        "capital-france",
        {
          "id": "history-france",
          "cloze_ids": ["c1"]
        }
      ]
    }
  ]
}
```

The string entry creates cards for both `c1` and `c2` in `capital-france`. The object entry creates only the `c1` card for `history-france`.

## Card identity

Each generated card has a deck ID, generator ID, entity ID, and cloze ID. The cloze ID must be part of `CardKey` and stored identity.

The entity remains the source note. Each selected cloze has its own FSRS state.
