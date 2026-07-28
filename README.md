# GraphCards

GraphCards is a local flashcard program backed by FSRS. Each configured deck is one complete
`deck.json` file; `graphcards.toml` contains runtime settings and the list of deck files to load.

## Workspace configuration

```toml
state_path = ".graphcards/state.sqlite3"
display_timezone = "UTC"
decks = ["decks/capitals/deck.json", "decks/planets/deck.json"]
```

The directory name is the stable deck identity. The optional `name` in `deck.json` is display
metadata only. RDF sources, SPARQL queries, and per-deck kinds are not configuration fields
anymore.

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
      "front_template": "{{ target.data.get('front') }} — {% for choice in choice_entities %}{{ choice.data.get('label') }}{% if not loop.last %} / {% endif %}{% endfor %}",
      "back_template": "Answer: {{ target.data.get('back') }}"
    }
  ]
}
```

Entity records require unique non-blank IDs and may contain any nested JSON-compatible data.
Generator records are strict. Basic generators schedule the listed entities. Multiple-choice
generators list each target entity’s exhaustive distractor choices inline; the target is always the
correct answer, and random choice selection/order does not participate in identity. `max_choices`
is an upper bound on rendered choices; the target is always included. Ordered-list groups are
metadata, while their members are the scheduled targets in declared order. A member can belong to
only one group in a generator. Ordered-list `window_size` is the total number of visible rows,
centered around the target; `0` shows the complete ordered group.
Analogy generators map each target entity to a list of source entities. The default template renders
the selected source and target `front`/`back` values as an “A is to B as C is to ?” exercise.
Each generator may override its type’s `front_template` and `back_template` in `deck.json`; omitted
templates use the built-in renderer defaults. Templates receive entity references with arbitrary
nested data and structural information only: basic (`entity: Entity`), multiple-choice
(`target: Entity`, `choice_entities: tuple[Entity, ...]`), ordered-list (`target: Entity`,
`ordered_entities: tuple[Entity, ...]`, `rows: tuple[dict[str, object], ...]` with `position`,
`entity`, and `is_target`, plus `omitted_before: bool` and `omitted_after: bool`), and analogy
(`source: Entity`, `target: Entity`). Entity references expose `.id` and `.data`; templates choose
which fields to render and how to fall back when data is missing. Templates are sandboxed, compiled,
and checked for unknown variables while loading the complete deck; whitespace in template sources
and rendered views is preserved.
Generated multiple-choice exercises record the selected and ordered entity IDs in `choices`;
rendering only resolves those references into entity objects and never reselects them.

### Common-relation completion

Common-relation generators map each scheduled target directly to an ordered list of related entity
IDs. The target key is the stable card identity and answer:

```json
{
  "id": "common-locations",
  "type": "common_relation",
  "direction": "object",
  "min_examples": 2,
  "max_related": 0,
  "relations": {
    "europe": ["france", "germany", "italy"]
  }
}
```

`object` asks for the shared target; `subject` asks for the shared target from the opposite side.
Relationship wording is presentation-specific and can be supplied by a custom template. Each
target produces one scheduled exercise and therefore one stable card identity, even when the
generated subset changes.
Groups must contain at least `min_examples` distinct related IDs (default `2`). `max_related` is
zero for all related IDs, or selects exactly `min(max_related, group size)` distinct IDs; a cap
below `min_examples` is invalid. Selection uses the generation RNG and restores declaration order
before storing the IDs in the semantic exercise payload, so rendering is stateless and does not
sample or reorder.

Default labels use `label`, then `back`, then `answer`, then `id` for target and related entities.
Custom templates receive only `target`, `related_entities`, and `direction`; the default front
displays one `related — ?` line per related entity for object direction and `? — related` for
subject direction. The default back displays only the target label.

All entities, generators, IDs, and references are validated before a deck can be synchronized.
Each targeted entity produces one scheduled exercise. If multiple generators target the same entity,
the generator with the lexicographically smallest ID owns that entity's exercise; this keeps the
count entity-based and makes the selected type independent of JSON declaration order. Exercise IDs
remain deterministic from the deck directory identity, selected generator ID, and target entity ID.

## Commands

```console
graphcards --config graphcards.toml validate
graphcards --config graphcards.toml sync
graphcards --config graphcards.toml status --full
graphcards --config graphcards.toml serve
```

`init --template` creates one of the bundled JSON deck examples. The SQLite state database keeps
FSRS schedules and review history; rendered exercise text is regenerated from the current deck.
