from __future__ import annotations

import json
import random
from pathlib import Path
from typing import ClassVar, Literal

import pytest
from pydantic import StrictStr

from graphcards.decks import Deck, DeckDocument, ExerciseGenerator
from graphcards.errors import ConfigError
from graphcards.references import EntityIdList

ENTITIES = [
    {"id": "basic-a", "label": "Basic A"},
    {"id": "basic-b", "label": "Basic B"},
    {"id": "choice-target", "label": "Choice target"},
    {"id": "choice-a", "label": "Choice A"},
    {"id": "choice-b", "label": "Choice B"},
    {"id": "ordered-target", "label": "Ordered target"},
    {"id": "ordered-a", "label": "Ordered A"},
    {"id": "ordered-b", "label": "Ordered B"},
    {"id": "analogy-target", "label": "Analogy target"},
    {"id": "analogy-source-a", "label": "Analogy source A"},
    {"id": "analogy-source-b", "label": "Analogy source B"},
    {"id": "relation-target", "label": "Relation target"},
    {"id": "relation-a", "label": "Relation A"},
    {"id": "relation-b", "label": "Relation B"},
]

GROUPS = [
    {"id": "basic-targets", "entities": ["basic-a", "basic-b"]},
    {"id": "choice-distractors", "entities": ["choice-a", "choice-b"]},
    {"id": "ordered-members", "entities": ["ordered-a", "ordered-b"]},
    {
        "id": "analogy-sources",
        "entities": ["analogy-source-a", "analogy-source-b"],
    },
    {"id": "relation-members", "entities": ["relation-a", "relation-b"]},
]


def grouped_document() -> dict[str, object]:
    return {
        "name": "Grouped entities",
        "entities": [dict(entity) for entity in ENTITIES],
        "groups": [{"id": group["id"], "entities": list(group["entities"])} for group in GROUPS],
        "exercises": [
            {"id": "basic", "type": "basic", "entities": "basic-targets"},
            {
                "id": "choices",
                "type": "multiple_choice",
                "choices": {"choice-target": "choice-distractors"},
            },
            {
                "id": "ordered",
                "type": "ordered_list",
                "groups": {"ordered-target": "ordered-members"},
            },
            {
                "id": "analogy",
                "type": "analogy",
                "sources": {"analogy-target": "analogy-sources"},
            },
            {
                "id": "relations",
                "type": "common_relation",
                "relations": {"relation-target": "relation-members"},
            },
        ],
    }


def inline_document() -> dict[str, object]:
    document = grouped_document()
    document.pop("groups")
    exercises = document["exercises"]
    assert isinstance(exercises, list)
    exercises[0]["entities"] = ["basic-a", "basic-b"]
    exercises[1]["choices"] = {"choice-target": ["choice-a", "choice-b"]}
    exercises[2]["groups"] = {"ordered-target": ["ordered-a", "ordered-b"]}
    exercises[3]["sources"] = {"analogy-target": ["analogy-source-a", "analogy-source-b"]}
    exercises[4]["relations"] = {"relation-target": ["relation-a", "relation-b"]}
    return document


def write_json(path: Path, document: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@ExerciseGenerator.register
class MarkedProbeExerciseGenerator(ExerciseGenerator):
    """Test-only generator proving group expansion follows annotations, not type names."""

    type: Literal["marked_probe"] = "marked_probe"
    type_name = "marked_probe"
    entity_sets: dict[StrictStr, EntityIdList]
    literal: StrictStr
    metadata: dict[StrictStr, StrictStr]
    template_context_names: ClassVar[frozenset[str]] = frozenset()

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(self.entity_sets)

    def generate(self, entity_id: str, context) -> object:
        raise NotImplementedError

    def render(self, exercise, context) -> object:
        raise NotImplementedError


TOML_GROUPS = """\
name = "Grouped entities"

[[entities]]
id = "basic-a"
label = "Basic A"

[[entities]]
id = "basic-b"
label = "Basic B"

[[entities]]
id = "choice-target"
label = "Choice target"

[[entities]]
id = "choice-a"
label = "Choice A"

[[entities]]
id = "choice-b"
label = "Choice B"

[[entities]]
id = "ordered-target"
label = "Ordered target"

[[entities]]
id = "ordered-a"
label = "Ordered A"

[[entities]]
id = "ordered-b"
label = "Ordered B"

[[entities]]
id = "analogy-target"
label = "Analogy target"

[[entities]]
id = "analogy-source-a"
label = "Analogy source A"

[[entities]]
id = "analogy-source-b"
label = "Analogy source B"

[[entities]]
id = "relation-target"
label = "Relation target"

[[entities]]
id = "relation-a"
label = "Relation A"

[[entities]]
id = "relation-b"
label = "Relation B"

[[groups]]
id = "basic-targets"
entities = ["basic-a", "basic-b"]

[[groups]]
id = "choice-distractors"
entities = ["choice-a", "choice-b"]

[[groups]]
id = "ordered-members"
entities = ["ordered-a", "ordered-b"]

[[groups]]
id = "analogy-sources"
entities = ["analogy-source-a", "analogy-source-b"]

[[groups]]
id = "relation-members"
entities = ["relation-a", "relation-b"]

[[exercises]]
id = "basic"
type = "basic"
entities = "basic-targets"

[[exercises]]
id = "choices"
type = "multiple_choice"
[exercises.choices]
choice-target = "choice-distractors"

[[exercises]]
id = "ordered"
type = "ordered_list"
[exercises.groups]
ordered-target = "ordered-members"

[[exercises]]
id = "analogy"
type = "analogy"
[exercises.sources]
analogy-target = "analogy-sources"

[[exercises]]
id = "relations"
type = "common_relation"
[exercises.relations]
relation-target = "relation-members"
"""

YAML_GROUPS = """\
name: Grouped entities
entities:
  - id: basic-a
    label: Basic A
  - id: basic-b
    label: Basic B
  - id: choice-target
    label: Choice target
  - id: choice-a
    label: Choice A
  - id: choice-b
    label: Choice B
  - id: ordered-target
    label: Ordered target
  - id: ordered-a
    label: Ordered A
  - id: ordered-b
    label: Ordered B
  - id: analogy-target
    label: Analogy target
  - id: analogy-source-a
    label: Analogy source A
  - id: analogy-source-b
    label: Analogy source B
  - id: relation-target
    label: Relation target
  - id: relation-a
    label: Relation A
  - id: relation-b
    label: Relation B
groups:
  - id: basic-targets
    entities: [basic-a, basic-b]
  - id: choice-distractors
    entities: [choice-a, choice-b]
  - id: ordered-members
    entities: [ordered-a, ordered-b]
  - id: analogy-sources
    entities: [analogy-source-a, analogy-source-b]
  - id: relation-members
    entities: [relation-a, relation-b]
exercises:
  - id: basic
    type: basic
    entities: basic-targets
  - id: choices
    type: multiple_choice
    choices:
      choice-target: choice-distractors
  - id: ordered
    type: ordered_list
    groups:
      ordered-target: ordered-members
  - id: analogy
    type: analogy
    sources:
      analogy-target: analogy-sources
  - id: relations
    type: common_relation
    relations:
      relation-target: relation-members
"""


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_groups_expand_all_generator_list_fields_and_preserve_order(tmp_path: Path) -> None:
    deck = Deck.load(write_json(tmp_path / "grouped" / "deck.json", grouped_document()))

    assert deck.document.groups[0].id == "basic-targets"
    assert deck.generators[0].entities == ("basic-a", "basic-b")
    assert deck.generators[1].choices["choice-target"] == ("choice-a", "choice-b")
    assert deck.generators[2].groups["ordered-target"] == ("ordered-a", "ordered-b")
    assert deck.generators[3].sources["analogy-target"] == (
        "analogy-source-a",
        "analogy-source-b",
    )
    assert deck.generators[4].relations["relation-target"] == ("relation-a", "relation-b")


def test_grouped_and_inline_decks_have_equal_generation_and_rendering(tmp_path: Path) -> None:
    grouped = Deck.load(write_json(tmp_path / "parity" / "grouped.json", grouped_document()))
    inline = Deck.load(write_json(tmp_path / "parity" / "inline.json", inline_document()))

    assert grouped.target_entity_ids == inline.target_entity_ids
    for seed in (0, 7, 99):
        grouped_cards = grouped.generate_all(rng=random.Random(seed))
        inline_cards = inline.generate_all(rng=random.Random(seed))
        assert grouped_cards == inline_cards
        assert {
            card_id: grouped.render(card, rng=random.Random(seed))
            for card_id, card in grouped_cards.items()
        } == {
            card_id: inline.render(card, rng=random.Random(seed))
            for card_id, card in inline_cards.items()
        }


def test_groups_have_json_toml_yaml_parity(tmp_path: Path) -> None:
    directory = tmp_path / "parity"
    json_deck = Deck.load(write_json(directory / "deck.json", grouped_document()))
    toml_deck = Deck.load(write_text(directory / "deck.toml", TOML_GROUPS))
    yaml_deck = Deck.load(write_text(directory / "deck.yaml", YAML_GROUPS))

    assert toml_deck.document.model_dump() == json_deck.document.model_dump()
    assert yaml_deck.document.model_dump() == json_deck.document.model_dump()
    for seed in (0, 7, 99):
        expected = json_deck.generate_all(rng=random.Random(seed))
        assert toml_deck.generate_all(rng=random.Random(seed)) == expected
        assert yaml_deck.generate_all(rng=random.Random(seed)) == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entities", ["basic-a", "basic-targets"]),
        ("choices", {"choice-target": ["choice-a", "choice-distractors"]}),
        ("groups", {"ordered-target": ["ordered-a", "ordered-members"]}),
        ("sources", {"analogy-target": ["analogy-source-a", "analogy-sources"]}),
        ("relations", {"relation-target": ["relation-a", "relation-members"]}),
    ],
)
def test_group_ids_cannot_be_mixed_into_entity_lists(
    tmp_path: Path, field: str, value: object
) -> None:
    document = grouped_document()
    exercises = document["exercises"]
    assert isinstance(exercises, list)
    exercise = next(item for item in exercises if field in item)
    exercise[field] = value

    with pytest.raises(ConfigError, match="must contain concrete entity IDs"):
        Deck.load(write_json(tmp_path / field / "deck.json", document))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document["groups"].append(
            {"id": "basic-targets", "entities": ["basic-a"]}
        ),
        lambda document: document["groups"].append({"id": "basic-a", "entities": ["basic-b"]}),
        lambda document: document["groups"].append({"id": "empty", "entities": []}),
        lambda document: document["groups"].append(
            {"id": "duplicates", "entities": ["basic-a", "basic-a"]}
        ),
        lambda document: document["groups"].append(
            {"id": "missing", "entities": ["not-an-entity"]}
        ),
        lambda document: document["groups"].append({"id": "nested", "entities": ["basic-targets"]}),
    ],
)
def test_invalid_group_definitions_are_config_errors(tmp_path: Path, mutation) -> None:
    document = grouped_document()
    mutation(document)

    with pytest.raises(ConfigError):
        Deck.load(write_json(tmp_path / "invalid" / "deck.json", document))


def test_unknown_group_alias_is_a_config_error(tmp_path: Path) -> None:
    document = grouped_document()
    exercises = document["exercises"]
    assert isinstance(exercises, list)
    exercises[0]["entities"] = "not-a-group"

    with pytest.raises(ConfigError, match="must name a known entity group"):
        Deck.load(write_json(tmp_path / "unknown" / "deck.json", document))


def test_new_generator_uses_entity_list_markers_without_base_changes() -> None:
    document = grouped_document()
    document["exercises"] = [
        {
            "id": "probe",
            "type": "marked_probe",
            "entity_sets": {"targets": "basic-targets"},
            "literal": "basic-targets",
            "metadata": {"group-shaped-value": "basic-targets"},
        }
    ]

    parsed = DeckDocument.model_validate(document)
    generator = parsed.exercises[0]

    assert isinstance(generator, MarkedProbeExerciseGenerator)
    assert generator.entity_sets == {"targets": ("basic-a", "basic-b")}
    assert generator.literal == "basic-targets"
    assert generator.metadata == {"group-shaped-value": "basic-targets"}
