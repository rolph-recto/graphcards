from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from graphcards.app import StudyService
from graphcards.cli import main
from graphcards.config import FsrsSettings, load_config
from graphcards.errors import ConfigError
from graphcards.storage import Repository


def test_config_and_cli_validate_sync_and_status(
    deck_path: Path, tmp_path: Path, write_config
) -> None:
    config_path = write_config(tmp_path / "graphcards.toml", [deck_path])
    config = load_config(config_path)
    assert config.deck("capitals").display_name == "Capital study"
    from io import StringIO

    output = StringIO()
    assert main(["--config", str(config_path), "validate"], output=output) == 0
    assert "Capital study: valid (4 cards)" in output.getvalue()
    output = StringIO()
    assert main(["--config", str(config_path), "sync"], output=output) == 0
    assert "Capital study: 4 current, 4 new" in output.getvalue()


def test_config_rejects_deck_directories(deck_path: Path, tmp_path: Path, write_config) -> None:
    config_path = write_config(tmp_path / "graphcards.toml", [deck_path.parent])
    with pytest.raises(ConfigError, match="not a directory|deck file"):
        load_config(config_path)


def test_sync_is_union_of_generators_and_review_path_preserves_identity(
    deck_path: Path, tmp_path: Path
) -> None:
    deck = __import__("graphcards.decks", fromlist=["Deck"]).Deck.load(deck_path)
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        active, created = service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        assert (active, created) == (4, 4)
        card = repository.active_cards(deck.name)[0]
        assert card.card_key.deck_id == deck.name
        assert card.card_key.generator_id is not None
        assert service.render(deck, card).front


def test_storage_reports_corrupt_scoped_identity(deck_path: Path, tmp_path: Path) -> None:
    deck = __import__("graphcards.decks", fromlist=["Deck"]).Deck.load(deck_path)
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler())
        service.sync(deck)
        card = repository.active_cards(deck.name)[0]
        repository.connection.execute(
            "UPDATE cards SET identity_json = ? WHERE card_id = ?",
            (json.dumps({"bad": True}), card.card_id),
        )
        repository.connection.commit()
        try:
            repository.get_card(card.card_id)
        except Exception as error:
            assert "identity" in str(error)
        else:
            raise AssertionError("corrupt identity was accepted")
