from __future__ import annotations

from hashlib import sha256

import pytest
from hypothesis import given
from pydantic import ValidationError

from graphcards.decks import Entity
from graphcards.models import CardKey, CardView, Exercise
from tests.strategies import (
    PROPERTY_SETTINGS,
    entity_data,
    invalid_identity_strings,
    json_values,
    nested_json,
    valid_identity_strings,
)


@given(deck=valid_identity_strings, generator=valid_identity_strings, entity=valid_identity_strings)
@PROPERTY_SETTINGS
def test_card_key_digest_is_deterministic_and_hexadecimal(
    deck: str, generator: str, entity: str
) -> None:
    # Property: the same scoped identity always yields a stable 64-character hex digest.
    key = CardKey.exercise(deck, generator, entity)
    assert key.digest == CardKey.exercise(deck, generator, entity).digest
    assert len(key.digest) == 64
    assert all(character in "0123456789abcdef" for character in key.digest)


def test_card_key_digest_uses_an_independent_length_prefixed_encoding() -> None:
    # Property: digest serialization includes explicit lengths, so concatenation is unambiguous.
    key = CardKey.exercise("deck", "generator", "entity")
    digest = sha256(b"graphcards:exercise:v1\0")
    for value in key.identity_parts:
        encoded = value.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    assert key.digest == digest.hexdigest()


@given(value=valid_identity_strings.filter(lambda value: value != "generator"))
@PROPERTY_SETTINGS
def test_card_key_digest_has_length_boundaries_and_order_sensitivity(value: str) -> None:
    # Property: changing a part or its order changes the identity, including at length boundaries.
    key = CardKey.exercise(value, "generator", "entity")
    assert key.digest != CardKey.exercise(value + "x", "generator", "entity").digest
    assert key.digest != CardKey.exercise("generator", value, "entity").digest
    assert CardKey.exercise("ab", "c", "d").digest != CardKey.exercise("a", "bc", "d").digest


@given(deck=valid_identity_strings, generator=valid_identity_strings, entity=valid_identity_strings)
@PROPERTY_SETTINGS
def test_exercise_identity_scope_matches_its_card_key(
    deck: str, generator: str, entity: str
) -> None:
    # Property: an Exercise may only carry the generator and target encoded in its CardKey.
    key = CardKey.exercise(deck, generator, entity)
    exercise = Exercise(card_key=key, generator_id=generator, target_id=entity)
    assert exercise.card_key == key
    with pytest.raises(ValidationError, match="generator ID"):
        Exercise(card_key=key, generator_id=generator + "x", target_id=entity)
    with pytest.raises(ValidationError, match="target ID"):
        Exercise(card_key=key, generator_id=generator, target_id=entity + "x")


@given(value=invalid_identity_strings)
@PROPERTY_SETTINGS
def test_blank_and_control_identity_parts_are_rejected(value: str) -> None:
    # Property: blank and control-character identity components never enter domain keys.
    with pytest.raises(ValidationError):
        CardKey.exercise(value, "generator", "entity")


@given(value=json_values)
@PROPERTY_SETTINGS
def test_entity_json_data_is_immutable_and_round_trips(value: object) -> None:
    # Property: entity JSON is defensively copied, immutable, and preserved by model round-trips.
    entity = Entity(id="entity", metadata=value)
    restored = Entity.model_validate(entity.model_dump())
    assert restored == entity
    assert restored.data["metadata"] == entity.data["metadata"]
    with pytest.raises((TypeError, AttributeError)):
        entity.data["metadata"] = "changed"  # type: ignore[index]


@given(data=entity_data)
@PROPERTY_SETTINGS
def test_entity_model_round_trip_preserves_arbitrary_json(data: dict[str, object]) -> None:
    # Property: every generated JSON-compatible entity payload survives validation and dumping.
    entity = Entity(id="entity", **data)
    restored = Entity.model_validate(entity.model_dump())
    assert restored.id == entity.id
    assert restored.data == entity.data


def test_entity_rejects_non_json_and_too_deep_data() -> None:
    # Property: unsupported Python objects and excessively nested JSON are rejected at validation.
    with pytest.raises(ValidationError, match="JSON-compatible"):
        Entity(id="entity", value=object())
    with pytest.raises(ValidationError, match="nested too deeply"):
        Entity(id="entity", nested=nested_json(102))


def test_domain_models_are_frozen_and_copies_preserve_validation() -> None:
    # Property: validated domain models are frozen while model copies retain equivalent values.
    key = CardKey.exercise("deck", "generator", "entity")
    view = CardView(card_key=key, front="front", back="back")
    with pytest.raises(ValidationError, match="frozen"):
        view.front = "changed"  # type: ignore[misc]
    assert view.model_copy() == view
    assert key.model_copy().model_dump() == key.model_dump()
