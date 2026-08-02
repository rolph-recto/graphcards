from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from pydantic import ValidationError

from graphcards.config import AppConfig, FsrsSettings, load_config
from graphcards.errors import ConfigError
from tests.strategies import PROPERTY_SETTINGS, fsrs_fragments, valid_identity_strings


@given(fragment=fsrs_fragments())
@PROPERTY_SETTINGS
def test_valid_fsrs_settings_construct_a_scheduler_and_are_frozen(
    fragment: dict[str, object],
) -> None:
    # Property: every valid generated FSRS fragment builds a scheduler and remains frozen.
    settings = FsrsSettings.model_validate(fragment)
    assert settings.create_scheduler() is not None
    assert settings.model_copy() == settings
    with pytest.raises(ValidationError):
        settings.maximum_interval = settings.maximum_interval  # type: ignore[misc]


@given(value=valid_identity_strings)
@PROPERTY_SETTINGS
def test_fsrs_retention_and_bounds_reject_invalid_values(value: str) -> None:
    # Property: invalid retention types and non-positive intervals fail configuration validation.
    with pytest.raises(ValidationError):
        FsrsSettings(desired_retention=value)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        FsrsSettings(maximum_interval=0)


@given(state_name=valid_identity_strings)
@PROPERTY_SETTINGS
def test_state_paths_are_rejected_from_runtime_configuration(state_name: str) -> None:
    # Property: normal runtime configuration does not accept a SQLite state path.
    base = Path("/tmp") / state_name
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {"state_path": "state.sqlite3"},
            context={"base": base},
        )


def test_invalid_fsrs_library_values_are_translated_to_config_error(tmp_path: Path) -> None:
    # Property: library-level FSRS validation failures become repository-facing ConfigErrors.
    path = tmp_path / "graphcards.toml"
    path.write_text("[fsrs]\nmaximum_interval = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid configuration"):
        load_config(path)


def test_invalid_scheduler_configuration_is_user_facing(tmp_path: Path) -> None:
    # Property: invalid scheduler settings are exposed as controlled configuration errors.
    path = tmp_path / "graphcards.toml"
    path.write_text("[fsrs]\ndesired_retention = 2\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
