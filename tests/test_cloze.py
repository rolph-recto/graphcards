from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

from graphcards.config import load_config
from graphcards.decks import ClozeExercise, ClozeExerciseGenerator, Deck
from graphcards.models import CardKey
from graphcards.storage import Repository
from graphcards.web.app import EXPECTED_HOST_CONFIG, create_flask_app
from graphcards.web.controller import StudyController

DOCUMENT = {
    "entities": [
        {
            "id": "capital",
            "sentence": "The capital of [[c1::France]] is [[c2::Paris]].",
        },
        {
            "id": "nested",
            "sentence": "([[c1::The answer is [[c2::Answer 1]] NOT CORRECT]])",
        },
        {"id": "unused", "sentence": "Unused [[c1::value]]."},
    ],
    "exercises": [
        {
            "id": "clozes",
            "type": "cloze",
            "cloze_field": "sentence",
            "entities": ["capital", {"id": "nested", "cloze_ids": ["c2"]}],
        }
    ],
}


def write_deck(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_cloze_schedules_selected_markers_and_renders_nested_answers(
    tmp_path: Path,
) -> None:
    deck = Deck.load(write_deck(tmp_path / "cloze" / "deck.json", json.dumps(DOCUMENT)))

    assert isinstance(deck.generators[0], ClozeExerciseGenerator)
    cards = deck.generate_all(rng=random.Random(0))
    exercises = tuple(cards.values())
    assert len(exercises) == 2
    assert all(isinstance(exercise, ClozeExercise) for exercise in exercises)
    assert {(exercise.target_id, exercise.cloze_id) for exercise in exercises} == {
        ("capital", "c1"),
        ("nested", "c2"),
    }

    capital_c1 = next(
        exercise
        for exercise in exercises
        if exercise.target_id == "capital" and exercise.cloze_id == "c1"
    )
    assert deck.render(capital_c1).front == "The capital of [...] is Paris."
    assert deck.render(capital_c1).back == "The capital of France is Paris."

    nested_c2 = next(exercise for exercise in exercises if exercise.target_id == "nested")
    assert deck.render(nested_c2).front == "(The answer is [...] NOT CORRECT)"
    assert deck.render(nested_c2).back == "(The answer is Answer 1 NOT CORRECT)"

    assert len({exercise.card_key.digest for exercise in exercises}) == 2
    assert len({exercise.card_key for exercise in exercises}) == 2


def test_cloze_identity_is_stored_with_one_fsrs_card_per_entity(tmp_path: Path) -> None:
    deck = Deck.load(write_deck(tmp_path / "cloze" / "deck.json", json.dumps(DOCUMENT)))
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Repository(tmp_path / "state.sqlite3") as repository:
        repository.sync_deck(deck.name, deck.generate_all(), now)
        cards = repository.active_cards(deck.name)
        assert len(cards) == 2
        assert "cloze_id" not in CardKey.model_fields
        assert repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2
        for card in cards:
            restored = repository.get_card(card.card_id)
            assert restored is not None
            assert restored.card_key == card.card_key


def test_cloze_variant_change_reuses_the_entity_schedule(tmp_path: Path) -> None:
    deck_path = write_deck(tmp_path / "cloze" / "deck.json", json.dumps(DOCUMENT))
    first_deck = Deck.load(deck_path)
    changed = json.loads(json.dumps(DOCUMENT))
    changed["exercises"][0]["entities"][0] = {
        "id": "capital",
        "cloze_ids": ["c2", "c1"],
    }
    deck_path.write_text(json.dumps(changed), encoding="utf-8")
    second_deck = Deck.load(deck_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    with Repository(tmp_path / "state.sqlite3") as repository:
        repository.sync_deck(first_deck.name, first_deck.generate_all(), now)
        repository.sync_deck(second_deck.name, second_deck.generate_all(), now)
        cards = repository.active_cards(second_deck.name)
        assert len(cards) == 2
        capital = next(card for card in cards if card.card_key.entity_id == "capital")
        assert second_deck.render(second_deck.generate(capital.card_key)).front == (
            "The capital of France is [...]."
        )


def test_cloze_json_toml_and_yaml_decks_share_generation(tmp_path: Path) -> None:
    json_path = write_deck(tmp_path / "cloze" / "deck.json", json.dumps(DOCUMENT))
    toml_path = write_deck(
        tmp_path / "cloze" / "deck.toml",
        """
[[entities]]
id = "capital"
sentence = "The capital of [[c1::France]] is [[c2::Paris]]."

[[entities]]
id = "nested"
sentence = "([[c1::The answer is [[c2::Answer 1]] NOT CORRECT]])"

[[entities]]
id = "unused"
sentence = "Unused [[c1::value]]."

[[exercises]]
id = "clozes"
type = "cloze"
cloze_field = "sentence"
entities = ["capital", {id = "nested", cloze_ids = ["c2"]}]
""",
    )
    yaml_path = write_deck(
        tmp_path / "cloze" / "deck.yaml",
        """
entities:
  - id: capital
    sentence: 'The capital of [[c1::France]] is [[c2::Paris]].'
  - id: nested
    sentence: '([[c1::The answer is [[c2::Answer 1]] NOT CORRECT]])'
  - id: unused
    sentence: 'Unused [[c1::value]].'
exercises:
  - id: clozes
    type: cloze
    cloze_field: sentence
    entities:
      - capital
      - id: nested
        cloze_ids: [c2]
""",
    )

    decks = tuple(Deck.load(path) for path in (json_path, toml_path, yaml_path))
    generated = [deck.generate_all(rng=random.Random(4)) for deck in decks]
    assert generated[0] == generated[1] == generated[2]
    assert {card_id: decks[0].render(card) for card_id, card in generated[0].items()} == {
        card_id: decks[2].render(card) for card_id, card in generated[2].items()
    }


def test_cloze_cards_are_named_in_status_and_detail_views(tmp_path: Path) -> None:
    deck_path = write_deck(tmp_path / "cloze" / "deck.json", json.dumps(DOCUMENT))
    config_path = write_deck(
        tmp_path / "graphcards.toml",
        f'state_path = "{tmp_path / "state.sqlite3"}"\ndecks = ["{deck_path}"]\n',
    )
    config = load_config(config_path)
    repository = Repository(config.state_path)
    controller = StudyController(config, repository, random.Random(0))
    app = create_flask_app(controller)
    app.config[EXPECTED_HOST_CONFIG] = "localhost"
    try:
        client = app.test_client()
        status = client.get("/decks/cloze/cards", headers={"Host": "localhost"})
        detail = client.get(
            "/decks/cloze/cards/detail/nested",
            headers={"Host": "localhost"},
        )
        assert status.status_code == 200
        assert b"capital" in status.data
        assert b"nested" in status.data
        assert detail.status_code == 200
        assert b"2 selected cloze(s)" in detail.data
    finally:
        repository.close()


def test_cloze_id_does_not_change_card_digest() -> None:
    first = CardKey.exercise("deck", "clozes", "capital")
    second = CardKey.exercise("deck", "clozes", "capital")

    assert first.digest == second.digest
    assert "cloze_id" not in CardKey.model_fields
