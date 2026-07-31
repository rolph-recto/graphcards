from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fsrs import Rating

from graphcards.app import StudyService
from graphcards.config import FsrsSettings
from graphcards.decks import Deck
from graphcards.errors import StaleReviewError, StorageError
from graphcards.models import Card, CardKey
from graphcards.storage import Repository


def test_sync_is_idempotent_and_counts_each_target_entity_once(deck: Deck, tmp_path: Path) -> None:
    expected = deck.generate_all(rng=random.Random(0))
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        first = service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        second = service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        active = repository.active_cards(deck.name)

    assert first == (3, 3)
    assert second == (3, 0)
    assert {card.card_key.entity_id for card in active} == set(expected)


def test_generator_changes_preserve_the_entity_schedule(
    deck_path: Path, tmp_path: Path, write_deck
) -> None:
    original = Deck.load(deck_path)
    changed_document = json.loads(deck_path.read_text(encoding="utf-8"))
    changed_document["exercises"][0]["id"] = "aaa-basics"
    changed_path = tmp_path / "changed" / "capitals" / "deck.json"
    write_deck(changed_path, changed_document)
    changed = Deck.load(changed_path)
    original_cards = original.generate_all(rng=random.Random(0))
    changed_cards = changed.generate_all(rng=random.Random(0))

    assert set(changed_cards) == set(original_cards)
    assert {
        card.generator_id for card in original_cards.values() if card.target_id == "france"
    } == {"basics"}
    assert {card.generator_id for card in changed_cards.values() if card.target_id == "france"} == {
        "aaa-basics"
    }

    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(original, datetime(2026, 1, 1, tzinfo=UTC))
        france = next(
            card
            for card in repository.active_cards(original.name)
            if card.card_key.entity_id == "france"
        )
        service.review(original, france, Rating.Good, datetime(2026, 1, 2, tzinfo=UTC))
        reviewed = repository.get_card(france.card_key)
        assert reviewed is not None
        reviewed_history = repository.review_history(
            original.name, datetime(2026, 1, 3, tzinfo=UTC)
        )
        service.sync(changed, datetime(2026, 1, 3, tzinfo=UTC))
        restored = repository.get_card(france.card_key)
        assert restored is not None

        rendered = service.render(changed, restored)
        final_history = repository.review_history(original.name, datetime(2026, 1, 3, tzinfo=UTC))

    assert restored.card_json == reviewed.card_json
    assert restored.card().due == reviewed.card().due
    assert final_history == reviewed_history
    assert rendered.card_key == restored.card_key
    assert changed.generate(restored.card_key).generator_id == "aaa-basics"


def test_same_entity_in_different_decks_has_separate_composite_identities(
    deck_path: Path, tmp_path: Path, write_deck
) -> None:
    first = Deck.load(deck_path)
    second_path = tmp_path / "second" / "deck.json"
    write_deck(second_path, json.loads(deck_path.read_text(encoding="utf-8")))
    second = Deck.load(second_path)
    first_card = next(
        card
        for card in first.generate_all(rng=random.Random(0)).values()
        if card.card_key.entity_id == "france"
    )
    second_card = next(
        card
        for card in second.generate_all(rng=random.Random(0)).values()
        if card.card_key.entity_id == "france"
    )

    assert first_card.card_key.entity_id == second_card.card_key.entity_id
    assert first_card.card_key.deck_id != second_card.card_key.deck_id
    assert first_card.card_key != second_card.card_key

    with Repository(tmp_path / "state.sqlite3") as repository:
        sync_time = datetime(2026, 1, 1, tzinfo=UTC)
        repository.sync_deck(first.name, first.generate_all(rng=random.Random(0)), sync_time)
        repository.sync_deck(second.name, second.generate_all(rng=random.Random(0)), sync_time)
        first_stored = repository.get_card(first_card.card_key)
        second_stored = repository.get_card(second_card.card_key)
        assert first_stored is not None
        assert second_stored is not None
        assert first_stored.card_key == first_card.card_key
        assert second_stored.card_key == second_card.card_key


def test_suspension_survives_sync_and_excludes_card_from_queue(deck: Deck, tmp_path: Path) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        card = repository.active_cards("capitals")[0]
        repository.suspend_card("capitals", card.card_key.entity_id, "pause")
        service.sync(deck, datetime(2026, 1, 2, tzinfo=UTC))
        status = repository.status("capitals", datetime(2026, 1, 2, tzinfo=UTC))
        available_entities = {
            item.card_key.entity_id for item in repository.active_cards("capitals")
        }

    assert status.suspended == 1
    assert card.card_key.entity_id not in available_entities


def test_review_records_fsrs_history_and_stale_snapshot_is_rejected(
    deck: Deck, tmp_path: Path
) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        stored = repository.active_cards("capitals")[0]
        before = repository.get_card(stored.card_key)
        assert before is not None
        service.review(deck, stored, Rating.Good, datetime(2026, 1, 2, tzinfo=UTC))
        after_first = repository.get_card(stored.card_key)
        assert after_first is not None
        assert after_first.card_json != before.card_json
        with pytest.raises(StaleReviewError):
            service.review(deck, stored, Rating.Good, datetime(2026, 1, 3, tzinfo=UTC))
        after_stale_retry = repository.get_card(stored.card_key)
        history = repository.review_history("capitals", datetime(2026, 1, 4, tzinfo=UTC))

    assert len(history) == 1
    assert after_stale_retry is not None
    assert after_stale_retry.card_json == after_first.card_json


def test_corrupt_stored_schedule_is_reported_as_storage_error(deck: Deck, tmp_path: Path) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        card = repository.active_cards("capitals")[0]
        repository.connection.execute(
            "UPDATE cards SET card_json = ? WHERE deck_id = ? AND entity_id = ?",
            ("{bad", card.card_key.deck_id, card.card_key.entity_id),
        )
        repository.connection.commit()

        with pytest.raises(StorageError, match="schedule"):
            repository.get_card(card.card_key)


def test_sync_rolls_back_membership_and_new_cards_on_generation_error(
    deck: Deck, tmp_path: Path
) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        before = {card.card_key.entity_id for card in repository.active_cards(deck.name)}
        generated = service.generate_all(deck)
        bad_key = CardKey.exercise("wrong-deck", "new-target")
        candidate = dict(generated)
        candidate[bad_key.entity_id] = Card(card_key=bad_key)

        with pytest.raises(StorageError, match="does not belong to deck"):
            repository.sync_deck(deck.name, candidate, datetime(2026, 1, 2, tzinfo=UTC))

        after = {card.card_key.entity_id for card in repository.active_cards(deck.name)}
        assert after == before
        assert repository.get_card(bad_key) is None


def test_subset_sync_deactivates_removed_membership(
    deck_path: Path, tmp_path: Path, write_deck
) -> None:
    raw = json.loads(deck_path.read_text(encoding="utf-8"))
    raw["exercises"] = [raw["exercises"][0]]
    reduced_path = tmp_path / "copy" / "capitals" / "deck.json"
    write_deck(reduced_path, raw)
    original = Deck.load(deck_path)
    reduced = Deck.load(reduced_path)
    original_cards = original.generate_all(rng=random.Random(0))
    reduced_cards = reduced.generate_all(rng=random.Random(0))
    removed_entity = next(
        entity_id for entity_id in original_cards if entity_id not in reduced_cards
    )
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(original, datetime(2026, 1, 1, tzinfo=UTC))
        removed = repository.get_card(original_cards[removed_entity].card_key)
        assert removed is not None
        service.review(original, removed, Rating.Good, datetime(2026, 1, 1, tzinfo=UTC))
        reviewed = repository.get_card(removed.card_key)
        assert reviewed is not None
        service.sync(reduced, datetime(2026, 1, 2, tzinfo=UTC))
        current = repository.active_cards("capitals")
        assert not repository.card_available("capitals", removed.card_key.entity_id)
        retained = repository.get_card(removed.card_key)
        service.sync(original, datetime(2026, 1, 3, tzinfo=UTC))
        restored = repository.get_card(removed.card_key)
        history = repository.review_history("capitals", datetime(2026, 1, 4, tzinfo=UTC))

    assert {card.card_key.entity_id for card in current} == set(reduced_cards)
    assert retained == reviewed
    assert restored == reviewed
    assert len(history) == 1
