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
    assert {card.card_id for card in active} == set(expected)


def test_suspension_survives_sync_and_excludes_card_from_queue(deck: Deck, tmp_path: Path) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        card = repository.active_cards("capitals")[0]
        repository.suspend_card("capitals", card.card_id, "pause")
        service.sync(deck, datetime(2026, 1, 2, tzinfo=UTC))
        status = repository.status("capitals", datetime(2026, 1, 2, tzinfo=UTC))
        available_ids = {item.card_id for item in repository.active_cards("capitals")}

    assert status.suspended == 1
    assert card.card_id not in available_ids


def test_review_records_fsrs_history_and_stale_snapshot_is_rejected(
    deck: Deck, tmp_path: Path
) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        stored = repository.active_cards("capitals")[0]
        before = repository.get_card(stored.card_id)
        assert before is not None
        service.review(deck, stored, Rating.Good, datetime(2026, 1, 2, tzinfo=UTC))
        after_first = repository.get_card(stored.card_id)
        assert after_first is not None
        assert after_first.card_json != before.card_json
        with pytest.raises(StaleReviewError):
            service.review(deck, stored, Rating.Good, datetime(2026, 1, 3, tzinfo=UTC))
        after_stale_retry = repository.get_card(stored.card_id)
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
            "UPDATE cards SET card_json = ? WHERE card_id = ?", ("{bad", card.card_id)
        )
        repository.connection.commit()

        with pytest.raises(StorageError, match="schedule"):
            repository.get_card(card.card_id)


def test_sync_rolls_back_membership_and_new_cards_on_generation_error(
    deck: Deck, tmp_path: Path
) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(deck, datetime(2026, 1, 1, tzinfo=UTC))
        before = {card.card_id for card in repository.active_cards(deck.name)}
        generated = service.generate_all(deck)
        bad_key = CardKey.exercise("wrong-deck", "new-generator", "new-target")
        candidate = dict(generated)
        candidate[bad_key.digest] = Card(card_key=bad_key)

        with pytest.raises(StorageError, match="does not belong to deck"):
            repository.sync_deck(deck.name, candidate, datetime(2026, 1, 2, tzinfo=UTC))

        after = {card.card_id for card in repository.active_cards(deck.name)}
        assert after == before
        assert repository.get_card(bad_key.digest) is None


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
    removed_id = next(card_id for card_id in original_cards if card_id not in reduced_cards)
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler(), random.Random(0))
        service.sync(original, datetime(2026, 1, 1, tzinfo=UTC))
        removed = repository.get_card(removed_id)
        assert removed is not None
        service.review(original, removed, Rating.Good, datetime(2026, 1, 1, tzinfo=UTC))
        reviewed = repository.get_card(removed_id)
        assert reviewed is not None
        service.sync(reduced, datetime(2026, 1, 2, tzinfo=UTC))
        current = repository.active_cards("capitals")
        assert not repository.card_available("capitals", removed_id)
        retained = repository.get_card(removed_id)
        service.sync(original, datetime(2026, 1, 3, tzinfo=UTC))
        restored = repository.get_card(removed_id)
        history = repository.review_history("capitals", datetime(2026, 1, 4, tzinfo=UTC))

    assert {card.card_id for card in current} == set(reduced_cards)
    assert retained == reviewed
    assert restored == reviewed
    assert len(history) == 1
