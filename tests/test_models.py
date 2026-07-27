from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphcards.models import CardKey, CardView, Exercise


def test_card_key_digest_is_stable_and_order_sensitive() -> None:
    first = CardKey.exercise("deck", "generator", "entity")
    same = CardKey.exercise("deck", "generator", "entity")
    changed = CardKey.exercise("deck", "entity", "generator")

    assert first.digest == same.digest
    assert first.digest != changed.digest


def test_card_key_length_prefixes_prevent_boundary_ambiguity() -> None:
    assert CardKey.exercise("ab", "c", "d").digest != CardKey.exercise("a", "bc", "d").digest


def test_exercise_rejects_identity_scope_mismatches() -> None:
    key = CardKey.exercise("deck", "generator", "entity")

    with pytest.raises(ValidationError, match="generator ID"):
        Exercise(card_key=key, generator_id="other", target_id="entity")
    with pytest.raises(ValidationError, match="target ID"):
        Exercise(card_key=key, generator_id="generator", target_id="other")


def test_card_view_preserves_rendered_whitespace() -> None:
    key = CardKey.exercise("deck", "generator", "entity")

    view = CardView(card_key=key, front="\n  front  \n", back="\nback\n")

    assert view.front == "\n  front  \n"
    assert view.back == "\nback\n"


def test_domain_models_are_frozen() -> None:
    key = CardKey.exercise("deck", "generator", "entity")
    view = CardView(card_key=key, front="front", back="back")

    with pytest.raises(ValidationError):
        view.front = "changed"  # type: ignore[misc]
