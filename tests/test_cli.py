from __future__ import annotations

import random
from io import StringIO
from pathlib import Path

from graphcards.cli import main
from graphcards.config import load_config
from graphcards.decks import Deck
from graphcards.storage import Repository


def test_templates_lists_bundled_names_without_loading_config() -> None:
    output = StringIO()

    assert main(["--config", "missing.toml", "templates"], output=output) == 0
    assert {line for line in output.getvalue().splitlines()} >= {
        "analogy-capitals",
        "common-relations",
        "odd-one-out",
        "ordered-planets",
        "priority-capitals",
        "scrambled-planets",
        "temporal-comparison",
    }


def test_init_creates_template_workspace_and_refuses_overwrite(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = StringIO()

    assert main(["init", str(workspace), "--template", "analogy-capitals"], output=output) == 0
    assert (workspace / "deck.json").is_file()
    assert (workspace / "graphcards.toml").is_file()
    config = load_config(workspace / "graphcards.toml")
    assert config.decks[0].path == (workspace / "deck.json").resolve()
    deck = Deck.load(workspace / "deck.json")
    assert len(deck.generate_all()) == 2
    original_files = {
        path: path.read_bytes() for path in (workspace / "deck.json", workspace / "graphcards.toml")
    }
    assert main(["init", str(workspace)], output=StringIO(), error=StringIO()) == 2
    assert {path: path.read_bytes() for path in original_files} == original_files


def test_init_common_relations_template_validates(tmp_path: Path) -> None:
    workspace = tmp_path / "common-relations"
    assert main(["init", str(workspace), "--template", "common-relations"], output=StringIO()) == 0
    config = load_config(workspace / "graphcards.toml")
    assert config.decks[0].path == (workspace / "deck.json").resolve()
    deck = Deck.load(workspace / "deck.json")
    common_borders = next(
        generator for generator in deck.generators if generator.id == "common-borders"
    )
    assert common_borders.relations["france"] == ("germany", "italy", "spain")
    assert len(deck.generate_all()) == 2


def test_init_scrambled_planets_template_validates(tmp_path: Path) -> None:
    workspace = tmp_path / "scrambled-planets"
    assert main(["init", str(workspace), "--template", "scrambled-planets"], output=StringIO()) == 0
    config = load_config(workspace / "graphcards.toml")
    deck = Deck.load(workspace / "deck.json")

    assert config.decks[0].path == (workspace / "deck.json").resolve()
    assert len(deck.generate_all(rng=random.Random(0))) == 1
    assert deck.generators[0].type == "scrambled_list"


def test_init_temporal_comparison_template_validates(tmp_path: Path) -> None:
    workspace = tmp_path / "temporal-comparison"

    assert (
        main(["init", str(workspace), "--template", "temporal-comparison"], output=StringIO()) == 0
    )
    config = load_config(workspace / "graphcards.toml")
    deck = Deck.load(workspace / "deck.json")

    assert config.decks[0].path == (workspace / "deck.json").resolve()
    assert len(deck.generate_all(rng=random.Random(0))) == 3
    assert deck.generators[0].type == "temporal_comparison"


def test_init_odd_one_out_template_validates(tmp_path: Path) -> None:
    workspace = tmp_path / "odd-one-out"
    assert main(["init", str(workspace), "--template", "odd-one-out"], output=StringIO()) == 0
    config = load_config(workspace / "graphcards.toml")
    assert config.decks[0].path == (workspace / "deck.json").resolve()
    for filename in ("deck.json", "deck.toml", "deck.yaml"):
        deck = Deck.load(workspace / filename)
        assert len(deck.generate_all()) == 2
        assert {generator.type for generator in deck.generators} == {"odd_one_out"}


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
    assert "CARD ID" in output.getvalue()
    assert "capitals /" in output.getvalue()


def test_cli_suspend_and_resume_change_membership(
    deck_path: Path, tmp_path: Path, write_config
) -> None:
    config_path = write_config(tmp_path / "graphcards.toml", [deck_path])
    assert main(["--config", str(config_path), "sync"], output=StringIO()) == 0
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        card_id = repository.active_cards("capitals")[0].card_id

    assert (
        main(
            [
                "--config",
                str(config_path),
                "suspend",
                "capitals",
                card_id,
                "--reason",
                "later",
            ],
            output=StringIO(),
        )
        == 0
    )
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        card_status = next(
            status for status in repository.card_statuses("capitals") if status.card_id == card_id
        )
        assert card_status.suspended is True
        assert card_status.suspension_reason == "later"
        assert card_id not in {card.card_id for card in repository.active_cards("capitals")}

    assert (
        main(
            ["--config", str(config_path), "resume", "capitals", card_id],
            output=StringIO(),
        )
        == 0
    )
    with Repository(config.state_path) as repository:
        card_status = next(
            status for status in repository.card_statuses("capitals") if status.card_id == card_id
        )
        assert card_status.suspended is False
        assert card_status.suspension_reason is None
        assert card_id in {card.card_id for card in repository.active_cards("capitals")}


def test_cli_missing_configuration_is_user_facing_error(tmp_path: Path) -> None:
    error = StringIO()

    assert main(["--config", str(tmp_path / "missing.toml"), "validate"], error=error) == 2
    assert "configuration file not found" in error.getvalue()
