from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from graphcards.decks import (
    Deck,
    DeckDocument,
    ScrambledListExercise,
    ScrambledListExerciseGenerator,
)
from graphcards.errors import ConfigError, PresentationError

ENTITIES = [
    {"id": "target", "label": "Target"},
    {"id": "one", "label": "One"},
    {"id": "two", "label": "Two"},
    {"id": "three", "label": "Three"},
]


def document() -> dict[str, object]:
    return {
        "name": "Scrambled study",
        "entities": [dict(entity) for entity in ENTITIES],
        "exercises": [
            {
                "id": "order",
                "type": "scrambled_list",
                "groups": {"target": ["one", "two", "three"]},
            }
        ],
    }


def write_json(path: Path, value: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_scrambled_list_generator_is_dispatched_and_shuffles_once(
    tmp_path: Path,
) -> None:
    deck = Deck.load(write_json(tmp_path / "scrambled" / "deck.json", document()))

    assert isinstance(deck.generators[0], ScrambledListExerciseGenerator)
    card = next(iter(deck.generate_all(rng=random.Random(0)).values()))
    assert isinstance(card, ScrambledListExercise)
    assert card.target_id == "target"
    assert card.ordered_ids == ("one", "two", "three")
    assert set(card.scrambled_ids) == set(card.ordered_ids)
    assert card.scrambled_ids != card.ordered_ids
    assert deck.render(card, rng=random.Random(99)).front.startswith("Target:\n")
    assert deck.render(card).back == "1. One\n2. Two\n3. Three"


def test_scrambled_list_generation_is_seeded_and_rendering_does_not_rescramble(
    tmp_path: Path,
) -> None:
    deck = Deck.load(write_json(tmp_path / "stable" / "deck.json", document()))
    first = next(iter(deck.generate_all(rng=random.Random(7)).values()))
    second = next(iter(deck.generate_all(rng=random.Random(7)).values()))
    different = next(iter(deck.generate_all(rng=random.Random(8)).values()))

    assert first == second
    assert first.card_key == different.card_key
    assert deck.render(first, rng=random.Random(1)) == deck.render(first, rng=random.Random(2))


def test_scrambled_list_custom_templates_receive_target_and_both_orders(
    tmp_path: Path,
) -> None:
    value = document()
    exercises = value["exercises"]
    assert isinstance(exercises, list)
    exercises[0].update(
        {
            "front_template": (
                "{{ target.id }}|{% for entity in scrambled_entities %}{{ entity.id }}{% endfor %}"
            ),
            "back_template": (
                "{{ target.label }}|{% for entity in ordered_entities %}{{ entity.id }}{% endfor %}"
            ),
        }
    )
    deck = Deck.load(write_json(tmp_path / "custom" / "deck.json", value))
    card = next(iter(deck.generate_all(rng=random.Random(0)).values()))

    assert isinstance(card, ScrambledListExercise)
    assert deck.render(card).front == "target|" + "".join(card.scrambled_ids)
    assert deck.render(card).back == "Target|onetwothree"


def test_scrambled_list_accepts_named_entity_group_alias(tmp_path: Path) -> None:
    value = document()
    value["groups"] = [{"id": "ordered-related", "entities": ["one", "two", "three"]}]
    exercises = value["exercises"]
    assert isinstance(exercises, list)
    exercises[0]["groups"] = {"target": "ordered-related"}

    deck = Deck.load(write_json(tmp_path / "alias" / "deck.json", value))
    generator = deck.generators[0]
    assert isinstance(generator, ScrambledListExerciseGenerator)
    assert generator.groups["target"] == ("one", "two", "three")


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        ({}, "must define groups"),
        ({"target": ["one"]}, "at least two related"),
        ({"target": ["one", "one"]}, "duplicate related"),
        ({"target": ["target", "one"]}, "cannot be one"),
        ({"missing": ["one", "two"]}, "unknown"),
        ({"target": ["one", "missing"]}, "unknown"),
    ],
)
def test_scrambled_list_rejects_invalid_configuration(
    groups: dict[str, list[str]], message: str, tmp_path: Path
) -> None:
    value = document()
    exercises = value["exercises"]
    assert isinstance(exercises, list)
    exercises[0]["groups"] = groups

    with pytest.raises(ConfigError, match=message):
        Deck.load(write_json(tmp_path / "invalid" / "deck.json", value))


def test_scrambled_list_rejects_inconsistent_runtime_payload(tmp_path: Path) -> None:
    deck = Deck.load(write_json(tmp_path / "malformed" / "deck.json", document()))
    generator = deck.generators[0]
    assert isinstance(generator, ScrambledListExerciseGenerator)
    malformed = ScrambledListExercise.model_construct(
        card_key=generator._key("target", deck.name),
        generator_id="order",
        target_id="target",
        ordered_ids=("one", "two", "three"),
        scrambled_ids=("one", "one", "three"),
    )

    with pytest.raises(PresentationError, match="missing or inconsistent"):
        deck.render(malformed)


def test_scrambled_list_loads_from_json_toml_and_yaml(tmp_path: Path) -> None:
    directory = tmp_path / "formats"
    json_path = write_json(directory / "deck.json", document())
    toml_path = directory / "deck.toml"
    toml_path.write_text(
        """\
name = "Scrambled study"

[[entities]]
id = "target"
label = "Target"

[[entities]]
id = "one"
label = "One"

[[entities]]
id = "two"
label = "Two"

[[entities]]
id = "three"
label = "Three"

[[exercises]]
id = "order"
type = "scrambled_list"
[exercises.groups]
target = ["one", "two", "three"]
""",
        encoding="utf-8",
    )
    yaml_path = directory / "deck.yaml"
    yaml_path.write_text(
        """\
name: Scrambled study
entities:
  - id: target
    label: Target
  - id: one
    label: One
  - id: two
    label: Two
  - id: three
    label: Three
exercises:
  - id: order
    type: scrambled_list
    groups:
      target: [one, two, three]
""",
        encoding="utf-8",
    )

    decks = [Deck.load(path) for path in (json_path, toml_path, yaml_path)]
    assert all(isinstance(deck.generators[0], ScrambledListExerciseGenerator) for deck in decks)
    assert decks[0].document.model_dump() == decks[1].document.model_dump()
    assert decks[1].document.model_dump() == decks[2].document.model_dump()
    for seed in (0, 7, 99):
        cards = [next(iter(deck.generate_all(rng=random.Random(seed)).values())) for deck in decks]
        assert cards[0] == cards[1] == cards[2]


def test_scrambled_list_document_dispatches_from_json() -> None:
    parsed = DeckDocument.model_validate(document())
    assert isinstance(parsed.exercises[0], ScrambledListExerciseGenerator)
