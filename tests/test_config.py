from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphcards.config import load_config
from graphcards.errors import ConfigError


def test_paths_are_relative_to_config_file(
    deck_path: Path, tmp_path: Path, write_deck, write_config
) -> None:
    workspace = tmp_path / "workspace"
    deck_directory = workspace / "capitals"
    deck_copy = write_deck(
        deck_directory / "deck.json", json.loads(deck_path.read_text(encoding="utf-8"))
    )
    config_path = write_config(workspace / "graphcards.toml", ["capitals/deck.json"])

    config = load_config(config_path)

    assert config.state_path == workspace / "state.sqlite3"
    assert config.decks[0].path == deck_copy.resolve()


def test_empty_config_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "empty.toml"
    path.write_text("", encoding="utf-8")

    config = load_config(path)

    assert config.decks == ()
    assert config.display_timezone.key == "UTC"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('decks = "deck.json"\n', "decks must be a list"),
        ("unknown = true\n", "Extra inputs are not permitted"),
        ('display_timezone = "Not/AZone"\n', "invalid configuration"),
    ],
)
def test_invalid_workspace_configuration_is_rejected(
    tmp_path: Path, body: str, message: str
) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config(path)


@pytest.mark.parametrize(
    "fsrs",
    [
        {"desired_retention": 0},
        {"maximum_interval": 0},
        {"learning_steps_minutes": [0]},
        {"relearning_steps_minutes": [0]},
    ],
)
def test_invalid_fsrs_settings_are_rejected(
    tmp_path: Path, write_config, fsrs: dict[str, object]
) -> None:
    path = write_config(tmp_path / "invalid-fsrs.toml", [], fsrs=fsrs)

    with pytest.raises(ConfigError, match="invalid configuration"):
        load_config(path)


def test_fsrs_settings_are_loaded_from_toml(tmp_path: Path, write_config) -> None:
    path = write_config(
        tmp_path / "configured.toml",
        [],
        fsrs={
            "desired_retention": 0.95,
            "maximum_interval": 100,
            "learning_steps_minutes": [2],
            "relearning_steps_minutes": [3],
            "enable_fuzzing": False,
        },
    )

    settings = load_config(path).fsrs

    assert settings.desired_retention == 0.95
    assert settings.maximum_interval == 100
    assert settings.learning_steps_minutes == (2,)
    assert settings.relearning_steps_minutes == (3,)
    assert settings.enable_fuzzing is False


def test_deck_entries_must_be_explicit_regular_files(tmp_path: Path) -> None:
    directory = tmp_path / "deck"
    directory.mkdir()
    path = tmp_path / "config.toml"
    path.write_text('decks = ["deck"]\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="not a directory|deck file"):
        load_config(path)


def test_missing_deck_file_is_a_configuration_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('decks = ["missing/deck.json"]\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="could not access deck file|not found"):
        load_config(path)


def test_unknown_deck_name_reports_configured_names(
    deck_path: Path, tmp_path: Path, write_config
) -> None:
    config_path = write_config(tmp_path / "config.toml", [deck_path])
    config = load_config(config_path)

    with pytest.raises(ConfigError, match="unknown deck.*capitals"):
        config.deck("missing")
