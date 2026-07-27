from __future__ import annotations

import random
from pathlib import Path

import pytest

from graphcards.decks import (
    AnalogyExercise,
    Deck,
    ExerciseGeneratorContext,
    MultipleChoiceExercise,
)
from graphcards.errors import ConfigError


def test_multiple_choice_invariants_hold_across_random_generations(deck: Deck) -> None:
    generator = next(item for item in deck.generators if item.type == "multiple_choice")
    distractors = generator.choices["france"]
    maximum = generator.max_choices

    for seed in range(25):
        exercise = generator.generate(
            "france", ExerciseGeneratorContext(deck.name, deck.entities, random.Random(seed))
        )
        assert isinstance(exercise, MultipleChoiceExercise)
        assert exercise.target_id in exercise.choices
        assert len(exercise.choices) <= maximum
        assert set(exercise.choices) <= {"france", *distractors}
        assert len(exercise.choices) == len(set(exercise.choices))
        assert all(choice_id in deck.entities for choice_id in exercise.choices)


def test_analogy_generation_uses_only_declared_sources(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "analogy" / "deck.json"
    write_deck(
        path,
        {
            "entities": [{"id": "source-a"}, {"id": "source-b"}, {"id": "target"}],
            "exercises": [
                {
                    "id": "analogy",
                    "type": "analogy",
                    "sources": {"target": ["source-a", "source-b"]},
                }
            ],
        },
    )
    deck = Deck.load(path)
    generator = deck.generators[0]

    exercises = [
        generator.generate(
            "target", ExerciseGeneratorContext(deck.name, deck.entities, random.Random(seed))
        )
        for seed in range(25)
    ]

    assert all(isinstance(exercise, AnalogyExercise) for exercise in exercises)
    assert {exercise.source_id for exercise in exercises} <= {"source-a", "source-b"}
    assert {exercise.card_key.digest for exercise in exercises} == {exercises[0].card_key.digest}


def test_analogy_preflight_checks_every_declared_source(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "analogy-invalid" / "deck.json"
    write_deck(
        path,
        {
            "entities": [
                {"id": "good", "front": "Good", "answer": "G"},
                {"id": "bad", "front": "Bad"},
                {"id": "target", "front": "Target"},
            ],
            "exercises": [
                {
                    "id": "analogy",
                    "type": "analogy",
                    "sources": {"target": ["good", "bad"]},
                    "front_template": "{{ source.data.get('answer').value }}",
                }
            ],
        },
    )

    with pytest.raises(ConfigError, match="could not render card template"):
        Deck.load(path)


@pytest.mark.parametrize(
    ("sources", "message"),
    [
        ({}, "define analogy sources"),
        ({"target": []}, "at least one source"),
        ({"target": ["source", "source"]}, "duplicate sources"),
        ({"target": ["target"]}, "cannot use itself"),
        ({"target": ["missing"]}, "unknown source"),
    ],
)
def test_analogy_rejects_invalid_source_declarations(
    tmp_path: Path, write_deck, sources: dict[str, list[str]], message: str
) -> None:
    path = tmp_path / f"invalid-{len(message)}" / "deck.json"
    write_deck(
        path,
        {
            "entities": [{"id": "source"}, {"id": "target"}],
            "exercises": [{"id": "analogy", "type": "analogy", "sources": sources}],
        },
    )

    with pytest.raises(ConfigError, match=message):
        Deck.load(path)
