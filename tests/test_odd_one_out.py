from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from graphcards.decks import Deck, OddOneOutExercise, OddOneOutExerciseGenerator
from graphcards.errors import ConfigError

ENTITIES = [
    {"id": "france", "label": "France"},
    {"id": "germany", "label": "Germany"},
    {"id": "italy", "label": "Italy"},
    {"id": "egypt", "label": "Egypt"},
    {"id": "japan", "label": "Japan"},
    {"id": "kenya", "label": "Kenya"},
    {"id": "europe", "label": "Europe"},
]


def document() -> dict[str, object]:
    return {
        "name": "Odd-one-out",
        "entities": ENTITIES,
        "exercises": [
            {
                "id": "relations",
                "type": "odd_one_out",
                "relations": {
                    "europe": {
                        "common": ["france", "germany", "italy"],
                        "odd": ["egypt", "japan", "kenya"],
                    }
                },
            }
        ],
    }


def write_json_deck(tmp_path: Path, raw: dict[str, object], name: str = "odd") -> Path:
    path = tmp_path / name / "deck.json"
    path.parent.mkdir()
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_generates_one_configured_odd_entity_with_target_identity(tmp_path: Path) -> None:
    deck = Deck.load(write_json_deck(tmp_path, document()))

    assert deck.target_entity_ids == ("europe",)
    exercise = next(iter(deck.generate_all(rng=random.Random(0)).values()))
    assert isinstance(exercise, OddOneOutExercise)
    assert exercise.card_key.entity_id == "europe"
    assert exercise.target_id == "europe"
    assert exercise.odd_id in {"egypt", "japan", "kenya"}
    assert set(exercise.common_ids) == {"france", "germany", "italy"}
    assert set(exercise.candidate_ids) == set(exercise.common_ids) | {exercise.odd_id}
    assert "direction" not in exercise.model_dump()
    assert "predicate" not in exercise.model_dump()

    view = deck.render(exercise)
    assert "Europe" in view.front
    assert exercise.odd_id.title() in view.back


def test_odd_pool_selection_varies_but_card_identity_is_stable(tmp_path: Path) -> None:
    deck = Deck.load(write_json_deck(tmp_path, document()))

    exercises = [
        next(iter(deck.generate_all(rng=random.Random(seed)).values())) for seed in range(12)
    ]
    assert {exercise.odd_id for exercise in exercises} >= {"egypt", "japan"}
    assert {exercise.card_key for exercise in exercises} == {exercises[0].card_key}


def test_max_candidates_samples_common_entities_and_keeps_selected_odd(tmp_path: Path) -> None:
    raw = document()
    generator = raw["exercises"][0]
    assert isinstance(generator, dict)
    generator["max_candidates"] = 3
    deck = Deck.load(write_json_deck(tmp_path, raw))

    exercise = next(iter(deck.generate_all(rng=random.Random(4)).values()))
    assert isinstance(exercise, OddOneOutExercise)
    assert len(exercise.candidate_ids) == 3
    assert len(exercise.common_ids) == 2
    assert exercise.odd_id in exercise.candidate_ids
    assert set(exercise.common_ids).issubset({"france", "germany", "italy"})


@pytest.mark.parametrize(
    "change, message",
    [
        (
            lambda relation: relation["odd"].__setitem__(0, "france"),
            "common and odd entities must be exclusive",
        ),
        (
            lambda relation: relation["common"].append("france"),
            "common entities must be unique",
        ),
        (
            lambda relation: relation["odd"].append("egypt"),
            "odd entities must be unique",
        ),
        (
            lambda relation: relation.__setitem__("common", []),
            "common entities must not be empty",
        ),
        (
            lambda relation: relation.__setitem__("odd", []),
            "odd entities must not be empty",
        ),
    ],
)
def test_invalid_entity_pools_are_configuration_errors(
    tmp_path: Path,
    change,
    message: str,
) -> None:
    raw = document()
    generator = raw["exercises"][0]
    assert isinstance(generator, dict)
    relations = generator["relations"]
    assert isinstance(relations, dict)
    relation = relations["europe"]
    assert isinstance(relation, dict)
    change(relation)

    with pytest.raises(ConfigError, match=message):
        Deck.load(write_json_deck(tmp_path, raw))


def test_unknown_common_entity_is_a_configuration_error(tmp_path: Path) -> None:
    raw = document()
    generator = raw["exercises"][0]
    assert isinstance(generator, dict)
    relations = generator["relations"]
    assert isinstance(relations, dict)
    relation = relations["europe"]
    assert isinstance(relation, dict)
    relation["common"][0] = "missing"

    with pytest.raises(ConfigError, match="unknown common entity"):
        Deck.load(write_json_deck(tmp_path, raw))


def test_unknown_odd_entity_is_a_configuration_error(tmp_path: Path) -> None:
    raw = document()
    generator = raw["exercises"][0]
    assert isinstance(generator, dict)
    relations = generator["relations"]
    assert isinstance(relations, dict)
    relation = relations["europe"]
    assert isinstance(relation, dict)
    relation["odd"][0] = "missing"

    with pytest.raises(ConfigError, match="unknown odd entity"):
        Deck.load(write_json_deck(tmp_path, raw))


def test_invalid_candidate_limits_are_configuration_errors(tmp_path: Path) -> None:
    raw = document()
    generator = raw["exercises"][0]
    assert isinstance(generator, dict)
    generator["max_candidates"] = 2

    with pytest.raises(ConfigError, match="max_candidates"):
        Deck.load(write_json_deck(tmp_path, raw))


def test_custom_templates_receive_only_semantic_entity_context(tmp_path: Path) -> None:
    raw = document()
    generator = raw["exercises"][0]
    assert isinstance(generator, dict)
    generator["front_template"] = (
        "{{ target.id }}|"
        "{% for entity in common_entities %}{{ entity.id }}{% endfor %}|"
        "{% for entity in candidate_entities %}{{ entity.id }}{% endfor %}"
    )
    generator["back_template"] = "{{ odd_entity.id }}"
    deck = Deck.load(write_json_deck(tmp_path, raw))

    exercise = next(iter(deck.generate_all(rng=random.Random(0)).values()))
    assert isinstance(exercise, OddOneOutExercise)
    view = deck.render(exercise)
    assert view.front.startswith("europe|francegermanyitaly|")
    assert view.back == exercise.odd_id


def test_entity_group_aliases_expand_inside_common_and_odd_lists(tmp_path: Path) -> None:
    raw = document()
    raw["groups"] = [
        {"id": "europe-common", "entities": ["france", "germany", "italy"]},
        {"id": "location-odd", "entities": ["egypt", "japan"]},
    ]
    generator = raw["exercises"][0]
    assert isinstance(generator, dict)
    relations = generator["relations"]
    assert isinstance(relations, dict)
    relation = relations["europe"]
    assert isinstance(relation, dict)
    relation["common"] = "europe-common"
    relation["odd"] = "location-odd"

    deck = Deck.load(write_json_deck(tmp_path, raw))
    typed_generator = deck.generators[0]
    assert isinstance(typed_generator, OddOneOutExerciseGenerator)
    assert typed_generator.relations["europe"].common == ("france", "germany", "italy")
    assert typed_generator.relations["europe"].odd == ("egypt", "japan")


@pytest.mark.parametrize("suffix", ["json", "toml", "yaml"])
def test_supported_deck_formats_load_the_two_entity_pools(tmp_path: Path, suffix: str) -> None:
    directory = tmp_path / suffix
    directory.mkdir()
    path = directory / f"deck.{suffix}"
    if suffix == "json":
        path.write_text(json.dumps(document()), encoding="utf-8")
    elif suffix == "toml":
        path.write_text(
            """\
name = "Odd-one-out"

[[entities]]
id = "france"
label = "France"
[[entities]]
id = "germany"
label = "Germany"
[[entities]]
id = "italy"
label = "Italy"
[[entities]]
id = "egypt"
label = "Egypt"
[[entities]]
id = "japan"
label = "Japan"
[[entities]]
id = "kenya"
label = "Kenya"
[[entities]]
id = "europe"
label = "Europe"

[[exercises]]
id = "relations"
type = "odd_one_out"

[exercises.relations.europe]
common = ["france", "germany", "italy"]
odd = ["egypt", "japan", "kenya"]
""",
            encoding="utf-8",
        )
    else:
        path.write_text(
            """\
name: Odd-one-out
entities:
  - {id: france, label: France}
  - {id: germany, label: Germany}
  - {id: italy, label: Italy}
  - {id: egypt, label: Egypt}
  - {id: japan, label: Japan}
  - {id: kenya, label: Kenya}
  - {id: europe, label: Europe}
exercises:
  - id: relations
    type: odd_one_out
    relations:
      europe:
        common: [france, germany, italy]
        odd: [egypt, japan, kenya]
""",
            encoding="utf-8",
        )

    deck = Deck.load(path)
    exercise = next(iter(deck.generate_all(rng=random.Random(0)).values()))
    assert isinstance(exercise, OddOneOutExercise)
    assert exercise.odd_id in {"egypt", "japan", "kenya"}
