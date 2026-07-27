from __future__ import annotations

import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from graphcards.decks import Deck, ExerciseGeneratorContext, MultipleChoiceExercise
from graphcards.errors import PresentationError
from graphcards.models import CardKey


def test_multiple_choice_rendering_preserves_generated_choice_order(
    tmp_path: Path, write_deck
) -> None:
    path = tmp_path / "choices" / "deck.json"
    write_deck(
        path,
        {
            "entities": [
                {"id": "target", "front": "Question", "back": "Answer"},
                {"id": "one", "label": "One"},
                {"id": "two", "label": "Two"},
                {"id": "three", "label": "Three"},
            ],
            "exercises": [
                {
                    "id": "choice",
                    "type": "multiple_choice",
                    "choices": {"target": ["one", "two", "three"]},
                    "front_template": (
                        "{% for choice in choice_entities %}{{ choice.data.get('label', "
                        "choice.data.get('back', choice.data.get('answer', choice.id))) }}"
                        "{% if not loop.last %}|{% endif %}{% endfor %}"
                    ),
                }
            ],
        },
    )
    deck = Deck.load(path)
    exercise = next(iter(deck.generate_all(rng=random.Random(7)).values()))

    assert isinstance(exercise, MultipleChoiceExercise)
    expected = []
    for choice_id in exercise.choices:
        data = deck.entities[choice_id].data
        expected.append(str(data.get("label", data.get("back", data.get("answer", choice_id)))))
    assert deck.render(exercise).front == "|".join(expected)


def test_multiple_choice_exercise_rejects_invalid_semantic_data() -> None:
    key = CardKey.exercise("deck", "choice", "target")

    with pytest.raises(ValidationError, match="target must be one of its choices"):
        MultipleChoiceExercise(
            card_key=key,
            generator_id="choice",
            target_id="target",
            choices=("other", "third"),
        )


def test_renderer_rejects_an_incompatible_semantic_exercise(deck: Deck) -> None:
    basic = next(generator for generator in deck.generators if generator.type == "basic")
    key = CardKey.exercise(deck.name, "choices", "france")
    exercise = MultipleChoiceExercise(
        card_key=key,
        generator_id="choices",
        target_id="france",
        choices=("france", "italy"),
    )

    with pytest.raises(PresentationError, match="cannot render"):
        basic.render(
            exercise,
            ExerciseGeneratorContext(deck.name, deck.entities, random.Random(0)),
        )
