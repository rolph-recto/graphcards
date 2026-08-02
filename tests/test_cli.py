from __future__ import annotations

import json
import random
from io import StringIO
from pathlib import Path

import pytest

from graphcards.cli import main
from graphcards.config import load_config
from graphcards.decks import Deck
from graphcards.storage import DeckFileStateStore


def _write_template_config(path: Path, template_paths: list[Path]) -> Path:
    encoded = ", ".join(json.dumps(str(template_path)) for template_path in template_paths)
    path.write_text(f"templates_paths = [{encoded}]\n", encoding="utf-8")
    return path


def _source_template_config(tmp_path: Path) -> Path:
    return _write_template_config(
        tmp_path / "config.toml", [Path(__file__).parents[1] / "templates"]
    )


def test_setup_creates_user_config_and_template_library(tmp_path: Path) -> None:
    config_path = tmp_path / "profile" / "config.toml"
    output = StringIO()

    assert main(["--config", str(config_path), "setup"], output=output) == 0
    assert config_path.is_file()
    assert (config_path.parent / "templates").is_dir()
    config = load_config(config_path)
    assert config.templates_paths == ((config_path.parent / "templates").resolve(),)
    assert {path.name for path in config.templates_paths[0].iterdir()} >= {
        "analogy-capitals",
        "image-occlusion",
    }
    assert not list((config_path.parent / "templates").rglob("config.toml"))
    assert not list((config_path.parent / "templates").rglob("graphcards.toml"))
    assert "Created user-wide GraphCards setup" in output.getvalue()


def test_templates_lists_unique_configured_names(tmp_path: Path) -> None:
    config_path = _source_template_config(tmp_path)
    output = StringIO()

    assert main(["--config", str(config_path), "templates"], output=output) == 0
    assert {line for line in output.getvalue().splitlines()} >= {
        "analogy-capitals",
        "common-relations",
        "image-occlusion",
        "temporal-comparison",
    }


def test_init_creates_one_selected_deck_and_refuses_overwrite(tmp_path: Path) -> None:
    config_path = _source_template_config(tmp_path)
    workspace = tmp_path / "workspace"
    output = StringIO()

    original_config = config_path.read_bytes()
    assert (
        main(
            [
                "--config",
                str(config_path),
                "init",
                str(workspace),
                "--template",
                "analogy-capitals",
            ],
            output=output,
        )
        == 0
    )
    assert {path.relative_to(workspace) for path in workspace.rglob("*") if path.is_file()} == {
        Path("deck.json")
    }
    assert config_path.read_bytes() == original_config
    assert len(Deck.load(workspace / "deck.json").generate_all()) == 2
    assert (
        main(
            [
                "--config",
                str(config_path),
                "init",
                str(workspace),
                "--template",
                "analogy-capitals",
            ],
            output=StringIO(),
            error=StringIO(),
        )
        == 2
    )
    assert config_path.read_bytes() == original_config


@pytest.mark.parametrize("deck_format", ["json", "toml", "yaml"])
def test_init_selects_one_deck_format(tmp_path: Path, deck_format: str) -> None:
    config_path = _source_template_config(tmp_path)
    workspace = tmp_path / deck_format

    assert (
        main(
            [
                "--config",
                str(config_path),
                "init",
                str(workspace),
                "--template",
                "odd-one-out",
                "--format",
                deck_format,
            ],
            output=StringIO(),
        )
        == 0
    )
    assert (workspace / f"deck.{deck_format}").is_file()
    assert len([path for path in workspace.iterdir() if path.is_file()]) == 1
    assert {
        generator.type for generator in Deck.load(workspace / f"deck.{deck_format}").generators
    } == {"odd_one_out"}


def test_init_common_relations_template_validates(tmp_path: Path) -> None:
    config_path = _source_template_config(tmp_path)
    workspace = tmp_path / "common-relations"
    assert (
        main(
            [
                "--config",
                str(config_path),
                "init",
                str(workspace),
                "--template",
                "common-relations",
            ],
            output=StringIO(),
        )
        == 0
    )
    deck = Deck.load(workspace / "deck.json")
    common_borders = next(
        generator for generator in deck.generators if generator.id == "common-borders"
    )
    assert common_borders.relations["france"] == ("germany", "italy", "spain")
    assert len(deck.generate_all()) == 2


def test_init_scrambled_planets_template_validates(tmp_path: Path) -> None:
    config_path = _source_template_config(tmp_path)
    workspace = tmp_path / "scrambled-planets"

    assert (
        main(
            [
                "--config",
                str(config_path),
                "init",
                str(workspace),
                "--template",
                "scrambled-planets",
            ],
            output=StringIO(),
        )
        == 0
    )
    deck = Deck.load(workspace / "deck.json")
    assert len(deck.generate_all(rng=random.Random(0))) == 1
    assert deck.generators[0].type == "scrambled_list"


def test_init_temporal_comparison_template_validates(tmp_path: Path) -> None:
    config_path = _source_template_config(tmp_path)
    workspace = tmp_path / "temporal-comparison"

    assert (
        main(
            [
                "--config",
                str(config_path),
                "init",
                str(workspace),
                "--template",
                "temporal-comparison",
            ],
            output=StringIO(),
        )
        == 0
    )
    deck = Deck.load(workspace / "deck.json")
    assert len(deck.generate_all(rng=random.Random(0))) == 3
    assert deck.generators[0].type == "temporal_comparison"


def test_validate_sync_and_full_status_use_json_deck(
    deck_path: Path, tmp_path: Path, write_config
) -> None:
    config_path = write_config(tmp_path / "graphcards.toml", [deck_path])
    output = StringIO()

    assert main(["--config", str(config_path), "validate"], output=output) == 0
    assert "Capital study: valid (3 cards)" in output.getvalue()
    assert main(["--config", str(config_path), "sync"], output=StringIO()) == 0
    output = StringIO()
    assert main(["--config", str(config_path), "status", "--full"], output=output) == 0
    assert "IDENTITY" in output.getvalue()
    assert "capitals /" in output.getvalue()


def test_cli_suspend_and_resume_change_membership(
    deck_path: Path, tmp_path: Path, write_config
) -> None:
    config_path = write_config(tmp_path / "graphcards.toml", [deck_path])
    assert main(["--config", str(config_path), "sync"], output=StringIO()) == 0
    config = load_config(config_path)
    with DeckFileStateStore(config.decks) as state_store:
        entity_id = state_store.active_cards("capitals")[0].card_key.entity_id

    assert (
        main(
            [
                "--config",
                str(config_path),
                "suspend",
                "capitals",
                entity_id,
                "--reason",
                "later",
            ],
            output=StringIO(),
        )
        == 0
    )
    config = load_config(config_path)
    with DeckFileStateStore(config.decks) as state_store:
        card_status = next(
            status
            for status in state_store.card_statuses("capitals")
            if status.card_key.entity_id == entity_id
        )
        assert card_status.suspended is True
        assert card_status.suspension_reason == "later"
        assert entity_id not in {
            card.card_key.entity_id for card in state_store.active_cards("capitals")
        }

    assert (
        main(
            ["--config", str(config_path), "resume", "capitals", entity_id],
            output=StringIO(),
        )
        == 0
    )
    with DeckFileStateStore(config.decks) as state_store:
        card_status = next(
            status
            for status in state_store.card_statuses("capitals")
            if status.card_key.entity_id == entity_id
        )
        assert card_status.suspended is False
        assert card_status.suspension_reason is None
        assert entity_id in {
            card.card_key.entity_id for card in state_store.active_cards("capitals")
        }


def test_cli_missing_configuration_is_user_facing_error(tmp_path: Path) -> None:
    error = StringIO()

    assert main(["--config", str(tmp_path / "missing.toml"), "validate"], error=error) == 2
    assert "configuration file not found" in error.getvalue()
