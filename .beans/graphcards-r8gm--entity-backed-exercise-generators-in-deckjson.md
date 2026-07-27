---
# graphcards-r8gm
title: Entity-backed exercise generators in deck.json
status: completed
type: feature
priority: normal
created_at: 2026-07-27T01:13:00Z
updated_at: 2026-07-27T05:34:47Z
---

Replace query-backed per-deck definitions with a data-driven deck.json model. A deck owns one validated entity registry and an ordered collection of type-specific exercise generators. Multiple exercise sources per deck are folded into this JSON deck model.

## Proposed contract

A deck file contains JSON with required top-level fields `entities` and `exercises`, plus optional `name` display metadata.

```json
{
  "name": "capitals",
  "entities": [
    {"id": "capital-france", "front": "Capital of France?", "back": "Paris"},
    {"id": "city-paris", "label": "Paris"},
    {"id": "city-berlin", "label": "Berlin"},
    {"id": "city-rome", "label": "Rome"},
    {"id": "europe", "label": "Europe"},
    {"id": "france", "label": "France"},
    {"id": "germany", "label": "Germany"}
  ],
  "exercises": [
    {
      "id": "capital-basic",
      "type": "basic",
      "entities": ["capital-france"]
    },
    {
      "id": "capital-choice",
      "type": "multiple_choice",
      "choices": {
        "capital-france": ["city-berlin", "city-rome"]
      }
    },
    {
      "id": "europe-order",
      "type": "ordered_list",
      "groups": {
        "europe": ["france", "germany"]
      }
    }
  ]
}
```

Entity records require a non-blank unique string `id` and may contain arbitrary JSON data. Generator records require a stable unique `id` and registered `type`; generator-specific fields are strict and all referenced entity and group IDs must resolve.

## Runtime model

- Introduce a `Deck` aggregate containing an immutable entity map and generator tuple.
- Introduce an `ExerciseGenerator` base class with a registry and `generate(entity_id)` method. Loading dispatches each JSON record to a concrete class.
- Add concrete basic, multiple-choice, and ordered-list generators. Each generator exposes its target entity IDs for synchronization and can generate one semantic exercise for a target ID.
- Preserve the card/presentation boundary: generators produce validated semantic exercise/card models; rendering remains type-specific and stateless.
- Use a stable exercise identity composed from generator ID and entity ID, so the same entity can intentionally participate in multiple generators without schedule collisions. Generator order must not affect identity.
- Synchronization uses the union of generated exercise identities for one deck. Duplicate target IDs within one generator are invalid; overlap across generators is allowed and creates distinct exercises.
- Ordered-list groups are entity IDs used as metadata and are not automatically scheduled. Their member IDs are the generated targets. A member may belong to only one group within one ordered-list generator.

## Validation and errors

- Invalid JSON, Pydantic failures, unknown generator types, duplicate IDs, malformed generator records, missing references, empty/duplicate choice lists, invalid ordered-list groups, and ambiguous multiple-choice definitions become the repository configuration error.
- Generation must reject an entity ID outside a generator scope with the repository presentation/generation error.
- Multiple-choice targets are always the correct answers. The `choices` mapping lists each target entity ID and its exhaustive distractor entity IDs inline. The target must be excluded from its distractor list; every reference must resolve and each list must satisfy the minimum-choice requirement.
- Decide whether generator IDs are required in JSON or can be derived. Stable explicit IDs are recommended for persistence and diagnostics.

## Acceptance criteria

- Load a representative deck.json into typed Pydantic v2 models and type-specific generators.
- Validate entity uniqueness and every generator reference before any study state is changed.
- Generate basic, multiple-choice, and ordered-list semantic exercises by entity ID.
- Prove stable exercise IDs, intentional cross-generator overlap, duplicate and missing-reference failures, and ordered-list group behavior.
- Wire CLI, web study, sync, status, suspension, review, templates/examples, and documentation to the new Deck aggregate.
- Replace or deliberately remove the old query/RDF deck path as a breaking configuration change, with no accidental compatibility layer.
- Run the repository quality gates and commit the implementation together with this bean file.

## Open decisions

- Exact entity data convention for prompts, answers, labels, and renderer metadata.
- Whether the deck file itself supplies the deck name or the containing path/config does.
- Multiple-choice distractors are inlined under each target entity in the generator `choices` mapping; no choice-pool IDs are defined.
- Whether all generators must have explicit IDs, and whether changing a generator ID intentionally starts a new FSRS schedule.

## Summary of Changes

Replaced query/RDF deck definitions with validated deck.json content and an immutable Deck aggregate. Added strict entity-backed basic, multiple-choice, and ordered-list generators with reference validation, deterministic generator-aware identities, semantic rendering, synchronized CLI/web/storage/FSRS paths, migrated templates/docs, and focused behavior coverage. Removed the obsolete RDF/query dependency and configuration path.

Quality gates: 18 tests passed with `uv run pytest -W error`; `uv run ruff check .`; `uv run ruff format --check .`; and `uv build` passed.

## Follow-up: Generator presentation settings

Added strict `max_choices` configuration to multiple-choice exercise generators and strict `window_size` configuration to ordered-list exercise generators in `deck.json`. Ordered-list rendering now uses the configured centered window with omission markers; bundled templates, README documentation, and behavior tests cover both settings.

Quality gates: 20 tests passed with `uv run pytest -W error`; `uv run ruff check .`; `uv run ruff format --check .`; and `uv build` passed.

## Follow-up: Inline multiple-choice choices

Changed multiple-choice generator definitions so `choices` maps each target entity ID directly to its exhaustive distractor entity IDs. Removed choice-pool IDs and target-to-pool indirection from runtime validation, generation, docs, bundled examples, and tests; the old schema is rejected by strict models.

## Follow-up: Explicit deck files in TOML

Changed the TOML `decks` field to accept a list of explicit deck file paths. Directory entries are rejected; all bundled templates, README examples, CLI/web fixtures, and configuration tests now use `deck.json` file paths.

## Follow-up: Restore analogy exercises

Restored an entity-backed analogy generator. Each target entity maps to a source entity, and semantic rendering uses the source and target entities’ front/back data. Added a dedicated module, bundled analogy template, README documentation, and behavior coverage.

## Follow-up: Analogy source lists

Analogy generator `sources` now maps every target entity ID to a list of source entity IDs, including one-element lists. Source selection is randomized at generation time without changing card identity.

## Follow-up: Render-time presentation data

Removed rendered front/back and multiple-choice prompt/choice payloads from generated exercise objects. Basic and multiple-choice exercises now carry only identity/target references; renderers resolve entity data, select choices, and inject template context at presentation time.



## Follow-up: Configurable generator templates

Added optional `front_template` and `back_template` fields to every typed exercise generator in `deck.json`. Deck loading validates nonblank template sources and compiles Jinja before runtime construction; renderers use configured templates with semantic per-type context and retain built-in defaults when omitted. Added behavior coverage for basic, multiple-choice, ordered-list, and analogy overrides plus malformed-template configuration errors, and documented the available context.

Focused tests: 22 passed with `uv run pytest -W error tests/test_decks_json.py`.


## Follow-up: Safe and whitespace-preserving templates

Hardened configurable Jinja with a sandbox, bounded source/cache size, per-generator context validation, and user-facing configuration errors for undeclared variables. Preserved intentional whitespace in template sources and rendered CardViews. Custom templates can use documented entity references (`entity`, `target`, `source`, `choice_entities`, and `ordered_entities`) to access stable IDs and nested entity data while retaining derived display context. Added security, whitespace, and nested-data behavior coverage.

Quality gates: 27 tests passed with `uv run pytest -W error`; `uv run ruff check .`; `uv run ruff format --check .`; and `uv build` passed.


## Follow-up: Bounded rendering

Bounded streamed template rendering now rejects outputs over one million characters as a `PresentationError`, preventing oversized card views from exhausting memory. Added behavior coverage.

Final focused tests: 23 passed with `uv run pytest -W error tests/test_decks_json.py`.


## Follow-up: Full template preflight and arithmetic guards

Deck loading now preflights every generated exercise before synchronization, including every configured analogy source, and rejects oversized template arithmetic before allocation. This closes source-specific nested-data failures and limits common CPU/intermediate-memory abuse while preserving sandboxed bounded rendering.

Final quality gates: 29 tests passed with `uv run pytest -W error`; `uv run ruff check .`; `uv run ruff format --check .`; and `uv build` passed.


## Follow-up: Generate-time multiple-choice selections

Restored random multiple-choice selection to `generate()`. `MultipleChoiceExercise.choices` now records the selected and ordered entity IDs, while `render()` only resolves those references into template context and never reselects or reshuffles them. Added behavior coverage proving generated choice payloads and render stability, and documented the semantic field.

Focused/full tests: 30 passed with `uv run pytest -W error`; `uv run ruff check .`; and `uv run ruff format --check .`.


## Follow-up: Restore JSON-deck behavior coverage

Restored and adapted the curated test coverage requested after the RDF-to-JSON migration. Added configuration/path validation, model invariants, generate-time multiple-choice order preservation, renderer error behavior, CLI/scaffold workflows, sync idempotence and membership suspension, FSRS review/stale snapshot handling, storage corruption, web app/study/status lifecycle and input safety, property-style generator invariants, analogy source validation/preflight, and explicit deck template initialization coverage. Obsolete RDF/query compatibility assertions were not restored.

Current quality gates: 68 tests passed with `uv run pytest -W error`; `uv run ruff check .`; and `uv run ruff format --check .`. Independent reviewer subagents could not be spawned because the configured agent thread limit was occupied; local review found no remaining test false positives.



## Follow-up: Fixture-based restored coverage

Replaced ad hoc valid deck/config string construction with shared pytest fixtures (`write_deck`, `write_config`, and lifecycle-safe `web_context`). Strengthened restored behavior assertions for scaffold overwrite safety, CLI suspension metadata, FSRS settings, exact generator unions, stale-review immutability, subset sync persistence/restoration, atomic sync rollback, semantic/template web parity, status filtering, analogy invariants, and malformed/repeated web submissions.

Final quality gates: 83 tests passed with `uv run pytest -W error`; `uv run ruff check .`; `uv run ruff format --check .`; and `uv build`.



## Follow-up: Collapse generator configuration and runtime objects

Consolidated `ExerciseGeneratorDefinition` and the runtime `ExerciseGenerator` hierarchy into one typed Pydantic generator hierarchy. `BasicExerciseGenerator`, `MultipleChoiceExerciseGenerator`, `OrderedListExerciseGenerator`, and `AnalogyExerciseGenerator` now validate their deck.json fields and implement generation/rendering directly. Deck supplies its identity and immutable entity mapping explicitly at generate/render call sites; obsolete `*Generator` runtime wrappers, record dispatch, and definition exports were removed.

Final quality gates: 83 tests passed with `uv run pytest -W error`; `uv run ruff check .`; `uv run ruff format --check .`; and `uv build`.



## Follow-up: Exercise generator operation context

Added the immutable `ExerciseGeneratorContext` object carrying `deck_id`, the entity mapping, and RNG. Deck now constructs and passes context objects to generator `generate()`, `render()`, and validation methods, removing repeated context keyword arguments from every concrete generator. Exported the context as part of the deck API and updated direct generator tests.

Final quality gates: 83 tests passed with `uv run pytest -W error`; `uv run ruff check .`; `uv run ruff format --check .`; and `uv build`.



## Follow-up: Template-driven entity rendering

Removed renderer-side `_display` and `_front` conversions. Render contexts now inject entity references and raw nested `.data` mappings, with only structural metadata for ordered-list layout. Built-in templates perform the default field selection/fallbacks, and custom generator templates in `deck.json` choose exactly which entity fields and formatting to render. Updated README context documentation and behavior tests.

Final quality gates: 83 tests passed with `uv run pytest -W error`; `uv run ruff check .`; `uv run ruff format --check .`; and `uv build`.
