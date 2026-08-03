# Add entities and generators

This tutorial edits the same deck model in JSON, TOML, or YAML. The loader selects the parser from
the file extension. Each entity needs a unique, non-blank `id`; other fields are available to
generator templates.

## Add entities and references

The smallest JSON deck is:

```json
{
  "name": "Capitals",
  "entities": [
    {"id": "france", "front": "France", "back": "Paris"},
    {"id": "germany", "front": "Germany", "back": "Berlin"}
  ],
  "exercises": [
    {"id": "basic", "type": "basic", "entities": ["france", "germany"]}
  ]
}
```

Generator references must name existing entities. Named groups can provide an ordered alias:

```json
{
  "groups": [{"id": "countries", "entities": ["france", "germany"]}],
  "exercises": [{"id": "basic", "type": "basic", "entities": "countries"}]
}
```

The group is expanded before generator reference validation. A group ID cannot be mixed with
concrete IDs in one list.

## Use TOML

TOML uses arrays of tables for entities and generators:

```toml
name = "Capitals"

[[entities]]
id = "france"
front = "France"
back = "Paris"

[[entities]]
id = "germany"
front = "Germany"
back = "Berlin"

[[exercises]]
id = "basic"
type = "basic"
entities = ["france", "germany"]
```

## Use YAML

The same content in YAML is:

```yaml
name: Capitals
entities:
  - id: france
    front: France
    back: Paris
  - id: germany
    front: Germany
    back: Berlin
exercises:
  - id: basic
    type: basic
    entities: [france, germany]
```

GraphCards uses a safe YAML loader. It rejects duplicate keys, aliases, anchors, merge keys, and
non-JSON values.

## Choose a generator

The current generator types are:

- `basic` schedules listed entities.
- `multiple_choice` selects a target and explicit distractors.
- `missing_sequence_item` hides one member of an ordered group.
- `scrambled_list` shows a shuffled related list and answers with the declared order.
- `analogy` relates source entities to a target entity.
- `cloze` hides marked spans such as `[[capital::Paris]]`.
- `image_occlusion` hides a normalized rectangle in a deck-relative image asset.
- `common_relation` asks for related entities for each target.
- `odd_one_out` selects one item from an explicit odd list.
- `temporal_comparison` compares positions in an ordered event group.

For example, a multiple-choice generator names its target and distractor pool:

```json
{
  "id": "capital-choice",
  "type": "multiple_choice",
  "choices": {"france": ["germany"]},
  "max_choices": 2
}
```

Generator-specific fields and template contexts are demonstrated in the built-in templates. List
them with `graphcards templates`, then initialize a copy in the format you want.

## Validate and inspect cards

Run validation after every content change:

```console
graphcards --config ~/.graphcards/config.toml validate
```

This checks the complete entity set, generator references, templates, and deterministic rendering.
Use Python when you need the generated semantic data or rendered views:

```python
from graphcards.decks import Deck

deck = Deck.load("/home/me/graphcards-study/capitals/deck.json")
cards = deck.generate_all()
for entity_id, card in cards.items():
    print(entity_id, deck.render(card).front)
```

Then run `graphcards status` to initialize or refresh study state and `graphcards serve` to review
the cards.
