# GraphCards

GraphCards is a local flashcard program backed by FSRS. Each configured deck is one complete JSON,
TOML, or YAML file; `graphcards.toml` contains runtime settings and the list of deck files to load.

## Workspace configuration

```toml
state_path = ".graphcards/state.sqlite3"
display_timezone = "UTC"
decks = ["decks/capitals/deck.toml", "decks/planets/deck.json"]
```

The directory name is the stable deck identity. The optional `name` in a deck file is display
metadata only. RDF sources, SPARQL queries, and per-deck kinds are not configuration fields
anymore. JSON, TOML, and YAML decks can be mixed in one workspace, and paths are relative to the
workspace configuration file.

## Deck content

```json
{
  "name": "Capitals",
  "entities": [
    {"id": "france", "front": "France", "back": "Paris"},
    {"id": "germany", "front": "Germany", "back": "Berlin"},
    {"id": "italy", "label": "Rome"}
  ],
  "exercises": [
    {"id": "basic", "type": "basic", "entities": ["france"]},
    {
      "id": "choice",
      "type": "multiple_choice",
      "max_choices": 3,
      "choices": {"germany": ["france", "italy"]},
      "front_template": "{{ target.front|default(target.prompt)|default(target.question)|default(target.id) }} — {% for choice in choice_entities %}{{ choice.label|default(choice.back)|default(choice.answer)|default(choice.id) }}{% if not loop.last %} / {% endif %}{% endfor %}",
      "back_template": "Answer: {{ target.back|default(target.answer)|default(target.id) }}"
    }
  ]
}
```

Entity records require unique non-blank IDs and may contain any nested JSON-compatible data.
Generator records are strict. Basic generators schedule the listed entities. Multiple-choice
generators list each target entity’s exhaustive distractor choices inline; the target is always the
correct answer, and random choice selection/order does not participate in identity. `max_choices`
is an upper bound on rendered choices; the target is always included. Missing-sequence-item groups are
metadata, while their members are the scheduled targets in declared order. A member can belong to
only one group in a generator. Missing-sequence-item `window_size` is the total number of visible rows,
centered around the target; `0` shows the complete ordered group.
Scrambled-list generators map each target entity to an ordered list of related entities. The default
front shows the target and a shuffled list. The default back shows the configured order. The shuffle
is stored in the semantic exercise, so rendering does not shuffle the list again.
Analogy generators map each target entity to a list of source entities. The default template renders
the selected source and target `front`/`back` values as an “A is to B as C is to ?” exercise.
Each generator may override its type’s `front_template` and `back_template` in either deck format; omitted
templates use the built-in renderer defaults. Templates receive entity references with arbitrary
nested data and structural information only: basic (`entity: Entity`), multiple-choice
(`target: Entity`, `choice_entities: tuple[Entity, ...]`), missing-sequence-item (`target: Entity`,
`ordered_entities: tuple[Entity, ...]`, `rows: tuple[dict[str, object], ...]` with `position`,
`entity`, and `is_target`, plus `omitted_before: bool` and `omitted_after: bool`), and analogy
(`source: Entity`, `target: Entity`), and scrambled-list (`target: Entity`,
`scrambled_entities: tuple[Entity, ...]`, `ordered_entities: tuple[Entity, ...]`). Entity references expose `.id` and every ordinary top-level
record field directly, including a source field named `data` when present; `data` is never an
aggregate mapping. Templates choose which fields to render and use Jinja `default`/`is defined`
semantics to fall back when optional fields are missing. Templates are sandboxed, compiled,
and checked for unknown variables while loading the complete deck; whitespace in template sources
and rendered views is preserved.
Generated multiple-choice exercises record the selected and ordered entity IDs in `choices`;
rendering only resolves those references into entity objects and never reselects them.

Named entity groups can remove repetition across generators. Define an ordered, non-empty group at
the deck level and use its ID as a whole-list alias wherever a generator expects a list of entity
IDs:

```json
{
  "groups": [
    {"id": "european-countries", "entities": ["france", "germany", "italy"]}
  ],
  "exercises": [
    {"id": "basics", "type": "basic", "entities": "european-countries"}
  ]
}
```

Aliases are supported by `basic.entities`, multiple-choice `choices` values, missing-sequence-item group
member values, scrambled-list group values, analogy `sources` values, and common-relation `relations`
values. Each field must
use either a list of concrete entity IDs or one group ID string; group IDs cannot appear inside
lists, so `["france", "european-countries"]` is invalid. Group IDs must be unique, must not collide
with entity IDs, and group definitions cannot contain other group IDs. Expansion preserves the
declared group order, while generators continue to validate the resulting concrete IDs.

### Common-relation completion

Common-relation generators map each scheduled target directly to an ordered list of related entity
IDs. The target key is the stable card identity and answer:

```json
{
  "id": "common-locations",
  "type": "common_relation",
  "min_examples": 2,
  "max_related": 0,
  "relations": {
    "europe": ["france", "germany", "italy"]
  }
}
```

Each target produces one scheduled exercise and therefore one stable card identity, even when the
generated subset changes. Relationship wording is presentation-specific and can be supplied by a
custom template.
Groups must contain at least `min_examples` distinct related IDs (default `2`). `max_related` is
zero for all related IDs, or selects exactly `min(max_related, group size)` distinct IDs; a cap
below `min_examples` is invalid. Selection uses the generation RNG and restores declaration order
before storing the IDs in the semantic exercise payload, so rendering is stateless and does not
sample or reorder.

Default labels use `label`, then `back`, then `answer`, then `id` for target and related entities.
Custom templates receive only `target` and `related_entities`; the default front displays one
`related — ?` line per related entity. The default back displays only the target label.

### Scrambled-list ordering

Scrambled-list generators use the same map-of-lists shape as missing-sequence-item generators, but
each map key is the target entity and each list is that target's ordered related entities:

```json
{
  "id": "planet-order",
  "type": "scrambled_list",
  "groups": {
    "solar-system": ["mercury", "venus", "earth", "mars"]
  }
}
```

Each target needs at least two unique related entities and cannot appear in its own list. Custom
templates receive `target`, `scrambled_entities`, and `ordered_entities`.

All entities, generators, IDs, and references are validated before a deck can be synchronized.
Each targeted entity produces one scheduled exercise. If multiple generators target the same entity,
the generator with the lexicographically smallest ID owns that entity's exercise; this keeps the
selected type independent of declaration order. Exercise IDs remain deterministic from the deck
directory identity, selected generator ID, and target entity ID.

### Odd-one-out relation cards

The `odd_one_out` generator uses explicit entity lists in the deck document. It does not load RDF
files or execute SPARQL queries. Each relation map key is an existing target entity and the stable
card identity.

```json
{
  "id": "locations",
  "type": "odd_one_out",
  "min_candidates": 3,
  "max_candidates": 0,
  "relations": {
    "europe": {
      "common": ["france", "germany", "italy"],
      "odd": ["egypt", "japan"]
    }
  }
}
```

The `common` and `odd` lists must contain declared, unique entity IDs, and the lists must be
exclusive. The generator selects exactly one entity from the explicit `odd` pool for each exercise;
it does not infer odd entities from the entities that are absent from `common`. The default minimum
is three displayed candidates, including the selected odd entity. `max_candidates` is zero for all
common entities plus the selected odd entity; a positive cap samples common entities and always
keeps the selected odd entity. The generated order is stored in the semantic exercise, so
rendering does not sample or reorder.

Each relation produces one card whose entity ID is the target entity. Default templates show the
target and candidate entities on the front and the odd entity on the back. Custom templates receive
`target`, `common_entities`, `candidate_entities`, and `odd_entity`.

### TOML authoring

TOML decks use `[[entities]]` and `[[exercises]]` arrays of tables. Generator maps such as
`choices`, `groups`, `sources`, and `relations` are nested TOML tables. Reusable entity groups use
`[[groups]]` tables:

```toml
name = "Capital study"

[[entities]]
id = "france"
front = "France"
back = "Paris"

[[entities]]
id = "germany"
front = "Germany"
back = "Berlin"

[[groups]]
id = "western-europe"
entities = ["france", "germany"]

[[exercises]]
id = "basics"
type = "basic"
entities = "western-europe"
```

A mixed workspace can list all supported formats:

```toml
decks = ["decks/capitals/deck.toml", "decks/planets/deck.json", "decks/languages/deck.yaml"]
```

Deck metadata must remain JSON-compatible. TOML native dates and times are rejected so JSON and
TOML documents validate the same domain model. File suffixes choose the parser; unsupported
extensions are rejected without inspecting their contents.

### YAML authoring

YAML decks use sequences for repeated `entities` and `exercises`, and mappings for generator data
such as `choices`, `groups`, `sources`, and `relations`. Reusable entity groups are a top-level
sequence of mappings:

```yaml
name: Capital study
entities:
  - id: france
    front: France
    back: Paris
  - id: germany
    front: Germany
    back: Berlin
groups:
  - id: western-europe
    entities: [france, germany]
exercises:
  - id: basics
    type: basic
    entities: western-europe
```

YAML loading uses a safe parser. Mapping keys must be unique strings, exactly one document is
allowed, and custom tags, merge keys, anchors, and aliases are rejected. YAML dates, sets, binary
values, non-finite numbers, and other non-JSON-native values are rejected; use quoted strings when
you need to preserve a value such as a date as text. The `.yaml` and `.yml` suffixes are
case-insensitive, and suffixes select the parser without content sniffing.

## Commands

```console
graphcards --config graphcards.toml validate
graphcards --config graphcards.toml sync
graphcards --config graphcards.toml status --full
graphcards --config graphcards.toml serve
```

`init --template` creates one of the bundled JSON deck examples. The SQLite state database keeps
FSRS schedules and review history; rendered exercise text is regenerated from the current deck.

The web deck page is opened through the `View Deck Info` link. It provides separate Card Status,
Review History, and Exercise Generators tabs. Card Status is a compact table of entity, review,
next-review, and FSRS data; use `More details` to open one entity's detail page while preserving
the current filters. The detail page lists every associated generator and shows the selected
non-persistent exercise in a shared preview panel on the right. The Exercise Generators tab uses
the same shared right-side preview panel, including for generators with no due cards, without
changing review or scheduling state or modifying generator sections. Review History applies its
date range as soon as it changes, and browser
suspension no longer requests or displays a reason; existing stored reasons remain compatible
with the state database.
