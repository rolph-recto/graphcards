from __future__ import annotations

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
def test_exercise_identity_scope_matches_its_card_key(
    deck: str, generator: str, entity: str
) -> None:
    # Property: generator selection remains runtime metadata while the target stays keyed.
    key = CardKey.exercise(deck, entity)
    exercise = Exercise(card_key=key, generator_id=generator, target_id=entity)
    assert exercise.card_key == key
    assert Exercise(card_key=key, generator_id=generator + "x", target_id=entity).card_key == key
    with pytest.raises(ValidationError, match="target ID"):
        Exercise(card_key=key, generator_id=generator, target_id=entity + "x")


@given(value=invalid_identity_strings)
@PROPERTY_SETTINGS
def test_blank_and_control_identity_parts_are_rejected(value: str) -> None:
    # Property: blank and control-character identity components never enter domain keys.
    with pytest.raises(ValidationError):
        CardKey.exercise(value, "entity")


@given(value=json_values)
@PROPERTY_SETTINGS
def test_entity_json_data_is_immutable_and_round_trips(value: object) -> None:
    # Property: entity JSON is defensively copied, immutable, and preserved by model round-trips.
    entity = Entity(id="entity", metadata=value)
    restored = Entity.model_validate(entity.model_dump())
    assert restored == entity
    assert restored.metadata == entity.metadata
    assert not hasattr(entity, "data")
    with pytest.raises((TypeError, AttributeError)):
        entity.metadata["changed"] = "value"  # type: ignore[index]


@given(data=entity_data)
@PROPERTY_SETTINGS
def test_entity_model_round_trip_preserves_arbitrary_json(data: dict[str, object]) -> None:
    # Property: every generated JSON-compatible entity payload survives validation and dumping.
    entity = Entity(id="entity", **data)
    restored = Entity.model_validate(entity.model_dump())
    assert restored.id == entity.id
    assert restored.model_dump(exclude={"id"}) == entity.model_dump(exclude={"id"})


def test_entity_rejects_non_json_and_too_deep_data() -> None:
    # Property: unsupported Python objects and excessively nested JSON are rejected at validation.
    with pytest.raises(ValidationError, match="JSON-compatible"):
        Entity(id="entity", value=object())
    with pytest.raises(ValidationError, match="nested too deeply"):
        Entity(id="entity", nested=nested_json(102))
    for value, message in (
        (float("nan"), "JSON-compatible"),
        (float("inf"), "JSON-compatible"),
        (float("-inf"), "JSON-compatible"),
        ({1: "not a JSON object key"}, "object keys must be strings"),
    ):
        with pytest.raises(ValidationError, match=message):
            Entity(id="entity", value=value)


def test_entity_nested_json_is_deeply_immutable_and_defensively_copied() -> None:
    raw = {"items": [{"enabled": True}]}
    entity = Entity(id="entity", facts=raw)

    raw["items"][0]["enabled"] = False
    raw["items"].append({"enabled": False})
    assert entity.facts["items"] == (  # type: ignore[index]
        {"enabled": True},
    )
    with pytest.raises((TypeError, AttributeError)):
        entity.facts["items"].append({"enabled": False})  # type: ignore[index]
    with pytest.raises(TypeError):
        entity.facts["items"][0]["enabled"] = False  # type: ignore[index]


def test_entity_keeps_data_ordinary_and_rejects_reserved_model_fields() -> None:
    entity = Entity(id="entity", facts={"answer": 42})
    assert not hasattr(entity, "model_extra")
    copied = entity.model_copy(update={"data": {"answer": 42}})
    assert copied.data["answer"] == 42  # type: ignore[index]
    for field_name in (
        "model_dump",
        "model_dump_json",
        "model_copy",
        "model_construct",
        "model_fields",
        "model_validate",
        "_secret",
        "__secret",
    ):
        with pytest.raises(ValidationError, match="reserved entity field"):
            Entity(id="entity", **{field_name: "value"})


def test_entity_exposes_every_ordinary_top_level_field_directly() -> None:
    entity = Entity(
        id="entity",
        name="Example",
        wikidata_id="Q42",
        coordinates={"lat": 51.5, "lon": -0.1},
        data={"source": "imported", "tags": ["place"]},
        require_id="ordinary field",
        validate_extra_data="also ordinary",
    )

    assert entity.name == "Example"
    assert entity.wikidata_id == "Q42"
    assert entity.coordinates["lat"] == 51.5  # type: ignore[index]
    assert entity.data["source"] == "imported"  # type: ignore[index]
    assert entity.data["tags"] == ("place",)  # type: ignore[index]
    assert entity.require_id == "ordinary field"
    assert entity.validate_extra_data == "also ordinary"
    assert Entity.construct(id="constructed", name="valid").name == "valid"
    with pytest.raises(ValidationError, match="non-blank"):
        Entity.construct(id="")


def test_entity_json_validation_rejects_duplicate_fields() -> None:
    with pytest.raises(ValidationError, match="duplicate JSON field 'front'"):
        Entity.model_validate_json('{"id":"entity","front":"one","front":"two"}')


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{", "Expecting"),
        ('{"id":"entity","value":NaN}', "JSON-compatible"),
    ],
)
def test_entity_json_validation_rejects_malformed_and_nonfinite_values(
    payload: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Entity.model_validate_json(payload)


def test_domain_models_are_frozen_and_copies_preserve_validation() -> None:
    # Property: validated domain models are frozen while model copies retain equivalent values.
    key = CardKey.exercise("deck", "entity")
    view = CardView(card_key=key, front="front", back="back")
    with pytest.raises(ValidationError, match="frozen"):
        view.front = "changed"  # type: ignore[misc]
    assert view.model_copy() == view
    assert key.model_copy().model_dump() == key.model_dump()
