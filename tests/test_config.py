from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphcards.config import load_config
from graphcards.errors import ConfigError
from graphcards.scaffold import available_templates


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

    assert config.decks[0].path == deck_copy.resolve()


def test_empty_config_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "empty.toml"
    path.write_text("", encoding="utf-8")

    config = load_config(path)

    assert config.decks == ()
    assert config.display_timezone.key == "UTC"
    assert config.templates_paths == ((tmp_path / "templates").resolve(),)


def test_template_paths_preserve_order_and_resolve_from_config(tmp_path: Path) -> None:
    absolute = tmp_path / "absolute-templates"
    path = tmp_path / "profile" / "config.toml"
    path.parent.mkdir()
    path.write_text(
        'templates_paths = ["relative-templates", ' + f'"{absolute}"]\n', encoding="utf-8"
    )

    config = load_config(path)

    assert config.templates_paths == (
        (path.parent / "relative-templates").resolve(),
        absolute.resolve(),
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('templates_paths = "templates"\n', "templates_paths must be a non-empty list"),
        ("templates_paths = []\n", "at least one directory"),
        ("templates_paths = [1]\n", "each templates_paths entry"),
        ('templates_paths = ["templates", "./templates"]\n', "duplicate directory"),
    ],
)
def test_invalid_template_paths_are_rejected(tmp_path: Path, body: str, message: str) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_missing_template_directories_are_valid_but_produce_no_templates(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('templates_paths = ["missing"]\n', encoding="utf-8")

    config = load_config(path)

    assert config.templates_paths == ((tmp_path / "missing").resolve(),)
    assert available_templates(config.templates_paths) == ()


def test_existing_template_file_is_rejected(tmp_path: Path) -> None:
    template_file = tmp_path / "templates-file"
    template_file.write_text("not a directory", encoding="utf-8")
    path = tmp_path / "config.toml"
    path.write_text('templates_paths = ["templates-file"]\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="templates_paths entry must be a directory"):
        load_config(path)
    with pytest.raises(ConfigError, match="template path is not a directory"):
        available_templates((template_file,))


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
