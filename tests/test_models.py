from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphcards.models import CardKey, CardView, Exercise


def test_exercise_keeps_generator_selection_outside_card_identity() -> None:
    key = CardKey.exercise("deck", "entity")

    exercise = Exercise(card_key=key, generator_id="other", target_id="entity")
    assert exercise.generator_id == "other"
    with pytest.raises(ValidationError, match="target ID"):
        Exercise(card_key=key, generator_id="other", target_id="other")


def test_card_view_preserves_rendered_whitespace() -> None:
    key = CardKey.exercise("deck", "entity")

    view = CardView(card_key=key, front="\n  front  \n", back="\nback\n")

    assert view.front == "\n  front  \n"
    assert view.back == "\nback\n"


def test_domain_models_are_frozen() -> None:
    key = CardKey.exercise("deck", "entity")
    view = CardView(card_key=key, front="front", back="back")

    with pytest.raises(ValidationError):
        view.front = "changed"  # type: ignore[misc]
