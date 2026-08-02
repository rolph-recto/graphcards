from __future__ import annotations

import json
import random
from collections.abc import Callable
from pathlib import Path

import pytest

from graphcards.config import load_config
from graphcards.decks import Deck
from graphcards.storage import DeckFileStateStore
from graphcards.web.app import EXPECTED_HOST_CONFIG, create_flask_app
from graphcards.web.controller import StudyController


@pytest.fixture
def deck_path(tmp_path: Path) -> Path:
    directory = tmp_path / "capitals"
    directory.mkdir()
    path = directory / "deck.json"
    path.write_text(
        json.dumps(
            {
                "name": "Capital study",
                "entities": [
                    {"id": "france", "front": "France", "back": "Paris"},
                    {"id": "germany", "front": "Germany", "back": "Berlin"},
                    {"id": "italy", "label": "Rome"},
                    {"id": "spain", "label": "Madrid"},
                    {"id": "europe", "label": "Europe"},
                ],
                "exercises": [
                    {"id": "basics", "type": "basic", "entities": ["france"]},
                    {
                        "id": "choices",
                        "type": "multiple_choice",
                        "choices": {"italy": ["france", "spain"]},
                    },
                    {
                        "id": "order",
                        "type": "missing_sequence_item",
                        "groups": {"europe": ["france", "germany"]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def write_deck() -> Callable[[Path, dict[str, object]], Path]:
    def write(path: Path, document: dict[str, object]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    return write


@pytest.fixture
def write_config() -> Callable[..., Path]:
    def write(
        path: Path,
        decks: list[Path | str],
        *,
        fsrs: dict[str, object] | None = None,
    ) -> Path:
        deck_values = ", ".join(json.dumps(str(deck)) for deck in decks)
        lines = [f"decks = [{deck_values}]"]
        if fsrs:
            lines.append("[fsrs]")
            for key, value in fsrs.items():
                encoded = (
                    json.dumps(value).lower() if isinstance(value, bool) else json.dumps(value)
                )
                lines.append(f"{key} = {encoded}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    return write


@pytest.fixture
def web_context(
    deck_path: Path, tmp_path: Path, write_config: Callable
) -> tuple[object, StudyController, DeckFileStateStore]:
    config_path = write_config(tmp_path / "graphcards.toml", [deck_path])
    config = load_config(config_path)
    state_store = DeckFileStateStore(config.decks)
    controller = StudyController(config, state_store, random.Random(0))
    app = create_flask_app(controller)
    app.config[EXPECTED_HOST_CONFIG] = "localhost"
    try:
        yield app.test_client(), controller, state_store
    finally:
        state_store.close()


@pytest.fixture
def deck(deck_path: Path) -> Deck:
    return Deck.load(deck_path)
