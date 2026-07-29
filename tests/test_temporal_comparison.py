from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from graphcards.decks import (
    Deck,
    TemporalComparisonExercise,
    TemporalComparisonExerciseGenerator,
)
from graphcards.errors import ConfigError, PresentationError

ENTITIES = [
    {"id": "timeline", "label": "European events"},
    {"id": "magna-carta", "label": "Signing of the Magna Carta"},
    {"id": "bouvines", "label": "Battle of Bouvines"},
    {"id": "paris", "label": "Treaty of Paris"},
]


def document() -> dict[str, object]:
    return {
        "name": "Temporal study",
        "entities": [dict(entity) for entity in ENTITIES],
        "exercises": [
            {
                "id": "events",
                "type": "temporal_comparison",
                "groups": {"timeline": ["magna-carta", "bouvines", "paris"]},
            }
        ],
    }


def write_json(path: Path, value: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_temporal_comparison_generates_one_stable_card_per_event(tmp_path: Path) -> None:
    deck = Deck.load(write_json(tmp_path / "temporal" / "deck.json", document()))

    assert isinstance(deck.generators[0], TemporalComparisonExerciseGenerator)
    assert deck.target_entity_ids == ("magna-carta", "bouvines", "paris")

    exercises = deck.generate_all(rng=random.Random(0))
    assert len(exercises) == 3
    for exercise in exercises.values():
        assert isinstance(exercise, TemporalComparisonExercise)
        assert exercise.comparison_id != exercise.target_id
        assert exercise.target_position != exercise.comparison_position
        assert exercise.answer in {"before", "after"}
        assert deck.render(exercise).back == exercise.answer


def test_temporal_comparison_rendering_does_not_use_rng(tmp_path: Path) -> None:
    deck = Deck.load(write_json(tmp_path / "stable" / "deck.json", document()))
    exercise = next(iter(deck.generate_all(rng=random.Random(7)).values()))

    assert deck.render(exercise, rng=random.Random(1)) == deck.render(
        exercise, rng=random.Random(2)
    )


def test_temporal_comparison_custom_templates_receive_semantic_context(tmp_path: Path) -> None:
    value = document()
    generator = value["exercises"][0]
    assert isinstance(generator, dict)
    generator["front_template"] = (
        "{{ target.id }}|{{ comparison.id }}|{{ group.id }}|"
        "{{ target_position }}|{{ comparison_position }}"
    )
    generator["back_template"] = "{{ answer }}"
    deck = Deck.load(write_json(tmp_path / "custom" / "deck.json", value))

    exercise = next(iter(deck.generate_all(rng=random.Random(0)).values()))
    assert isinstance(exercise, TemporalComparisonExercise)
    assert deck.render(exercise).front == (
        f"{exercise.target_id}|{exercise.comparison_id}|timeline|"
        f"{exercise.target_position}|{exercise.comparison_position}"
    )
    assert deck.render(exercise).back == exercise.answer


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        ({}, "must define groups"),
        ({"timeline": ["magna-carta"]}, "at least two events"),
        ({"timeline": ["magna-carta", "magna-carta"]}, "duplicate events"),
        ({"timeline": ["timeline", "magna-carta"]}, "cannot contain its group entity"),
        ({"missing": ["magna-carta", "bouvines"]}, "unknown group entity"),
        ({"timeline": ["magna-carta", "missing"]}, "unknown event entity"),
        (
            {"timeline": ["magna-carta", "bouvines"], "other": ["bouvines", "paris"]},
            "belongs to multiple groups",
        ),
    ],
)
def test_temporal_comparison_rejects_invalid_configuration(
    groups: dict[str, list[str]], message: str, tmp_path: Path
) -> None:
    value = document()
    generator = value["exercises"][0]
    assert isinstance(generator, dict)
    generator["groups"] = groups

    with pytest.raises(ConfigError, match=message):
        Deck.load(write_json(tmp_path / "invalid" / "deck.json", value))


def test_temporal_comparison_rejects_inconsistent_runtime_payload(tmp_path: Path) -> None:
    deck = Deck.load(write_json(tmp_path / "malformed" / "deck.json", document()))
    generator = deck.generators[0]
    assert isinstance(generator, TemporalComparisonExerciseGenerator)
    malformed = TemporalComparisonExercise.model_construct(
        card_key=generator._key("magna-carta", deck.name),
        generator_id="events",
        target_id="magna-carta",
        group_id="timeline",
        comparison_id="bouvines",
        target_position=1,
        comparison_position=3,
    )

    with pytest.raises(PresentationError, match="missing or inconsistent"):
        deck.render(malformed)


@pytest.mark.parametrize("suffix", ["json", "toml", "yaml"])
def test_temporal_comparison_loads_all_supported_deck_formats(tmp_path: Path, suffix: str) -> None:
    directory = tmp_path / suffix
    directory.mkdir()
    path = directory / f"deck.{suffix}"
    if suffix == "json":
        path.write_text(json.dumps(document()), encoding="utf-8")
    elif suffix == "toml":
        path.write_text(
            """\
name = "Temporal study"

[[entities]]
id = "timeline"
label = "European events"

[[entities]]
id = "magna-carta"
label = "Signing of the Magna Carta"

[[entities]]
id = "bouvines"
label = "Battle of Bouvines"

[[entities]]
id = "paris"
label = "Treaty of Paris"

[[exercises]]
id = "events"
type = "temporal_comparison"
[exercises.groups]
timeline = ["magna-carta", "bouvines", "paris"]
""",
            encoding="utf-8",
        )
    else:
        path.write_text(
            """\
name: Temporal study
entities:
  - id: timeline
    label: European events
  - id: magna-carta
    label: Signing of the Magna Carta
  - id: bouvines
    label: Battle of Bouvines
  - id: paris
    label: Treaty of Paris
exercises:
  - id: events
    type: temporal_comparison
    groups:
      timeline: [magna-carta, bouvines, paris]
""",
            encoding="utf-8",
        )

    deck = Deck.load(path)
    assert isinstance(deck.generators[0], TemporalComparisonExerciseGenerator)
    assert len(deck.generate_all(rng=random.Random(0))) == 3
