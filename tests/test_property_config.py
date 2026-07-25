from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from graphcards.config import AppConfig, FsrsSettings
from graphcards.decks import BasicDeck, DeckDefinition
from tests.strategies import (
    PROPERTY_SETTINGS,
    config_fragments,
    deck_names,
    fsrs_fragments,
    iri_segments,
)


@given(fragment=fsrs_fragments)
@PROPERTY_SETTINGS
def test_valid_fsrs_fragments_build_a_scheduler(fragment: dict[str, object]) -> None:
    # Property: valid generated FSRS fragments construct schedulers and remain equal after copying.
    settings = FsrsSettings.model_validate(fragment)

    assert settings.create_scheduler() is not None
    assert settings.model_copy() == settings


@given(
    value=st.one_of(
        st.integers(max_value=0),
        st.floats(min_value=1.000001, max_value=100, allow_nan=False, allow_infinity=False),
        st.booleans(),
        st.text(max_size=4),
    )
)
@PROPERTY_SETTINGS
def test_invalid_fsrs_retention_is_rejected_at_the_configuration_boundary(
    value: object,
) -> None:
    # Property: out-of-range, non-numeric, and boolean retention values are rejected by validation.
    with pytest.raises(ValidationError):
        FsrsSettings(desired_retention=value)  # type: ignore[arg-type]


@given(fragment=config_fragments)
@PROPERTY_SETTINGS
def test_generated_app_config_fragments_resolve_paths_and_preserve_invariants(
    fragment: dict[str, object],
) -> None:
    # Property: generated app configuration fragments resolve relative paths and preserve
    # invariants.
    config = AppConfig.model_validate(fragment)

    assert config.state_path.is_absolute()
    assert all(source.is_absolute() for source in config.sources)
    assert config.model_copy() == config


@given(name=deck_names, query_name=iri_segments)
@PROPERTY_SETTINGS
def test_configured_deck_fragments_dispatch_to_validated_definitions(
    name: str,
    query_name: str,
) -> None:
    # Property: valid deck fragments dispatch to the registered definition with an absolute
    # query path.
    definition = DeckDefinition.from_config(
        {
            "kind": "basic",
            "name": name,
            "target": "triple",
            "query": Path(f"queries/{query_name}.rq"),
        }
    )

    assert isinstance(definition, BasicDeck)
    assert definition.name == name
    assert definition.query_path.is_absolute()


@given(name=deck_names)
@PROPERTY_SETTINGS
def test_configured_names_are_stripped_without_changing_valid_values(name: str) -> None:
    # Property: whitespace around an otherwise valid configured deck name is normalized away.
    deck = BasicDeck(
        name=f" {name} ",
        target="triple",
        query_path=Path("query.rq"),
    )

    assert deck.name == name
