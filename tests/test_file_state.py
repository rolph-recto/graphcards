from __future__ import annotations

import json
import random
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fsrs import Rating, Scheduler
from pydantic import ValidationError

from graphcards.app import StudyService
from graphcards.config import FsrsSettings
from graphcards.decks import Deck
from graphcards.errors import StaleReviewError, StateConflictError, StorageError
from graphcards.scheduling import DailyLimits, DeckSchedulingSettings, NewReviewOrder
from graphcards.state import EntityState, FsrsCardState, ReviewEvent, ReviewState
from graphcards.storage import DeckFileStateStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _format_deck(tmp_path: Path, extension: str) -> Deck:
    source = Path(f"src/graphcards/templates/capitals/deck.{extension}")
    path = tmp_path / f"capitals-{extension}" / f"deck.{extension}"
    path.parent.mkdir()
    shutil.copyfile(source, path)
    return Deck.load(path)


def _sync(deck: Deck) -> DeckFileStateStore:
    store = DeckFileStateStore(deck)
    store.sync_deck(deck, deck.generate_all(rng=random.Random(0)), NOW)
    return store


def test_review_state_models_reject_unknown_fields_duplicate_ids_and_bad_references() -> None:
    card_state = FsrsCardState(
        card_id=123,
        state=1,
        step=0,
        due=NOW,
    )
    with pytest.raises(ValidationError):
        EntityState(fsrs=card_state, unexpected=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="duplicate review"):
        ReviewState(
            revision=1,
            entities={"target": EntityState(fsrs=card_state)},
            reviews=(
                ReviewEvent(review_id=1, entity_id="target", rating=Rating.Good, reviewed_at=NOW),
                ReviewEvent(review_id=1, entity_id="target", rating=Rating.Easy, reviewed_at=NOW),
            ),
        )
    with pytest.raises(ValidationError, match="unknown entity"):
        ReviewState(
            revision=1,
            entities={"target": EntityState(fsrs=card_state)},
            reviews=(
                ReviewEvent(
                    review_id=1,
                    entity_id="missing",
                    rating=Rating.Good,
                    reviewed_at=NOW,
                ),
            ),
        )


@pytest.mark.parametrize("extension", ["json", "toml", "yaml"])
def test_state_round_trips_with_reviews_settings_and_suspensions(
    tmp_path: Path, extension: str
) -> None:
    deck = _format_deck(tmp_path, extension)
    store = _sync(deck)
    card = store.active_cards(deck)[0]
    service = StudyService(store, FsrsSettings().create_scheduler(), random.Random(0))
    reviewed = service.review(deck, card, Rating.Good, datetime(2026, 1, 2, tzinfo=UTC))
    store.suspend_card(deck, reviewed.card_key.entity_id, "focus")
    store.set_daily_limits(deck, DailyLimits(new_cards_per_day=3, reviews_per_day=4))
    store.set_deck_settings(deck, DeckSchedulingSettings(new_review_order=NewReviewOrder.NEW_FIRST))

    fresh_deck = Deck.load(deck.path)
    fresh_store = DeckFileStateStore(fresh_deck)
    fresh_status = next(
        item
        for item in fresh_store.card_statuses(fresh_deck)
        if item.card_key.entity_id == reviewed.card_key.entity_id
    )

    assert len(fresh_deck.document.review_state.reviews) == 1
    assert fresh_status.suspended is True
    assert fresh_status.suspension_reason == "focus"
    assert fresh_store.daily_limits(fresh_deck).new_cards_per_day == 3
    assert fresh_store.deck_settings(fresh_deck).new_review_order is NewReviewOrder.NEW_FIRST
    assert fresh_deck.document.review_state.revision == 5
    assert not list(deck.path.parent.glob("*.sqlite*"))


def test_removed_entity_state_returns_when_entity_is_added_again(
    deck_path: Path, write_deck
) -> None:
    deck = Deck.load(deck_path)
    store = _sync(deck)
    service = StudyService(store, FsrsSettings().create_scheduler(), random.Random(0))
    card = next(item for item in store.active_cards(deck) if item.card_key.entity_id == "italy")
    entity_id = card.card_key.entity_id
    service.review(deck, card, Rating.Good, datetime(2026, 1, 2, tzinfo=UTC))
    reviewed_state = Deck.load(deck.path).document.review_state.entities[entity_id]

    raw = json.loads(deck.path.read_text(encoding="utf-8"))
    original_choices = raw["exercises"][1]
    raw["exercises"] = [raw["exercises"][0], raw["exercises"][2]]
    write_deck(deck.path, raw)
    reduced = Deck.load(deck.path)
    reduced_store = DeckFileStateStore(reduced)
    reduced_store.sync_deck(
        reduced,
        reduced.generate_all(rng=random.Random(0)),
        datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert entity_id not in {
        item.card_key.entity_id for item in reduced_store.active_cards(reduced)
    }
    assert Deck.load(deck.path).document.review_state.entities[entity_id] == reviewed_state

    raw["exercises"].insert(1, original_choices)
    write_deck(deck.path, raw)
    restored = Deck.load(deck.path)
    restored_store = _sync(restored)
    assert restored_store.get_card(restored, card.card_key).card().last_review is not None
    assert len(restored_store.review_history(restored, datetime(2026, 1, 4, tzinfo=UTC))) == 1


def test_stale_card_and_external_file_edits_are_conflicts(deck: Deck) -> None:
    first = _sync(deck)
    card = first.active_cards(deck)[0]
    second_deck = Deck.load(deck.path)
    second = DeckFileStateStore(second_deck)
    second_card = second.active_cards(second_deck)[0]
    service = StudyService(second, FsrsSettings().create_scheduler(), random.Random(0))
    service.review(second_deck, second_card, Rating.Good, datetime(2026, 1, 2, tzinfo=UTC))
    updated, log = Scheduler(enable_fuzzing=False).review_card(
        card.card(), Rating.Good, review_datetime=datetime(2026, 1, 3, tzinfo=UTC)
    )
    with pytest.raises(StaleReviewError):
        first.save_review(
            card.card_key,
            card.card_json,
            updated,
            log,
            previous_interval_seconds=None,
            retrievability=None,
            expected_digest=card.snapshot_digest,
            expected_revision=card.state_revision,
        )

    before = deck.path.read_bytes()
    deck.path.write_bytes(before.replace(b"Capital study", b"Changed"))
    with pytest.raises(StateConflictError):
        first.suspend_card(deck, card.card_key.entity_id, "changed")
    assert b"Changed" in deck.path.read_bytes()


def test_atomic_write_failure_leaves_the_original_file_unchanged(
    deck: Deck, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _sync(deck)
    before = deck.path.read_bytes()

    def fail_replace(_source: str | bytes | Path, _destination: str | bytes | Path) -> None:
        raise OSError("replacement failed")

    monkeypatch.setattr("graphcards.storage.os.replace", fail_replace)
    with pytest.raises(StorageError, match="atomically write"):
        store.suspend_card(deck, store.active_cards(deck)[0].card_key.entity_id, "blocked")
    assert deck.path.read_bytes() == before


def test_corrupt_state_is_a_storage_error_and_is_not_reset(deck: Deck) -> None:
    _sync(deck)
    before = deck.path.read_bytes()
    raw = json.loads(before)
    raw["review_state"]["entities"][next(iter(raw["review_state"]["entities"]))]["fsrs"]["due"] = (
        "bad"
    )
    deck.path.write_text(json.dumps(raw), encoding="utf-8")
    corrupted = deck.path.read_bytes()
    with pytest.raises(StorageError):
        Deck.load(deck.path)
    assert deck.path.read_bytes() == corrupted
    assert deck.path.read_bytes() != before
