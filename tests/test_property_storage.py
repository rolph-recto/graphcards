from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fsrs import Rating
from hypothesis import given
from hypothesis import strategies as st
from rdflib import Graph, Literal

from graphcards.app import StudyService
from graphcards.config import FsrsSettings
from graphcards.decks import BasicCard, BasicDeck
from graphcards.errors import StaleReviewError, StorageError
from graphcards.storage import Repository
from tests.strategies import EXPENSIVE_PROPERTY_SETTINGS, basic_cards, card_keys

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
card_sets = st.lists(
    basic_cards(),
    min_size=1,
    max_size=5,
    unique_by=lambda card: card.card_key.digest,
).map(lambda cards: {card.card_key.digest: card for card in cards})


def _repository() -> tuple[TemporaryDirectory[str], Repository]:
    directory = TemporaryDirectory()
    return directory, Repository(Path(directory.name) / "state.sqlite3")


@given(cards=card_sets)
@EXPENSIVE_PROPERTY_SETTINGS
def test_identical_sync_is_idempotent_and_never_duplicates_memberships(
    cards: dict[str, BasicCard],
) -> None:
    # Property: syncing identical presentations is idempotent and never creates duplicate
    # memberships.
    directory, repository = _repository()
    try:
        first = repository.sync_deck("deck", cards, NOW)
        second = repository.sync_deck("deck", cards, NOW)

        assert first == (len(cards), len(cards))
        assert second == (len(cards), 0)
        assert {card.card_id for card in repository.active_cards("deck")} == set(cards)
        membership_count = repository.connection.execute(
            "SELECT COUNT(*) FROM deck_cards WHERE deck_name = ?", ("deck",)
        ).fetchone()[0]
        assert membership_count == len(cards)
    finally:
        repository.close()
        directory.cleanup()


@given(cards=card_sets)
@EXPENSIVE_PROPERTY_SETTINGS
def test_subset_sync_preserves_global_cards_but_deactivates_removed_memberships(
    cards: dict[str, BasicCard],
) -> None:
    # Property: syncing a subset deactivates removed memberships while retaining global card rows.
    directory, repository = _repository()
    try:
        repository.sync_deck("deck", cards, NOW)
        subset = dict(list(cards.items())[: max(1, len(cards) // 2)])
        repository.sync_deck("deck", subset, NOW)

        assert {card.card_id for card in repository.active_cards("deck")} == set(subset)
        assert repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == len(
            cards
        )
        active_rows = repository.connection.execute(
            "SELECT card_id FROM deck_cards WHERE deck_name = ? AND active = 1", ("deck",)
        ).fetchall()
        assert {row[0] for row in active_rows} == set(subset)
    finally:
        repository.close()
        directory.cleanup()


@given(key=card_keys)
@EXPENSIVE_PROPERTY_SETTINGS
def test_one_global_card_can_have_independent_memberships_in_multiple_decks(key: object) -> None:
    # Property: one global card identity can have independent membership rows in multiple decks.
    card = BasicCard(card_key=key, front=Literal("front"), back=Literal("back"))  # type: ignore[arg-type]
    cards = {key.digest: card}  # type: ignore[union-attr]
    directory, repository = _repository()
    try:
        repository.sync_deck("first", cards, NOW)
        repository.sync_deck("second", cards, NOW)
        assert repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
        assert repository.connection.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0] == 2
        assert repository.get_card(key.digest).card_key == key  # type: ignore[union-attr]
    finally:
        repository.close()
        directory.cleanup()


@given(cards=card_sets)
@EXPENSIVE_PROPERTY_SETTINGS
def test_persisted_identity_and_schedule_decode_to_equivalent_domain_values(
    cards: dict[str, BasicCard],
) -> None:
    # Property: persisted identities and schedules decode back to equivalent domain values.
    directory, repository = _repository()
    try:
        repository.sync_deck("deck", cards, NOW)
        for card_id, semantic_card in cards.items():
            restored = repository.get_card(card_id)
            assert restored is not None
            assert restored.card_id == card_id
            assert restored.card_key == semantic_card.card_key
            assert restored.card().due == NOW
    finally:
        repository.close()
        directory.cleanup()


@given(card=basic_cards())
@EXPENSIVE_PROPERTY_SETTINGS
def test_suspend_resume_preserves_schedule_and_excludes_suspended_cards(card: BasicCard) -> None:
    # Property: suspension excludes a card from study availability without changing its schedule,
    # and
    # resuming restores availability without changing that schedule.
    directory, repository = _repository()
    try:
        cards = {card.card_key.digest: card}
        repository.sync_deck("deck", cards, NOW)
        before = repository.get_card(card.card_key.digest)
        assert before is not None

        repository.suspend_card("deck", card.card_key.digest, "  needs review  ")
        assert not repository.card_available("deck", card.card_key.digest)
        assert repository.card_suspended("deck", card.card_key.digest)
        assert repository.active_cards("deck") == []
        assert repository.get_card(card.card_key.digest) == before

        repository.resume_card("deck", card.card_key.digest)
        assert repository.card_available("deck", card.card_key.digest)
        assert repository.get_card(card.card_key.digest) == before
    finally:
        repository.close()
        directory.cleanup()


@given(card=basic_cards())
@EXPENSIVE_PROPERTY_SETTINGS
def test_review_round_trip_records_one_event_and_rejects_stale_retries(card: BasicCard) -> None:
    # Property: one accepted review is persisted, while retrying the stale source snapshot is
    # rejected.
    directory, repository = _repository()
    try:
        repository.sync_deck("deck", {card.card_key.digest: card}, NOW)
        stored = repository.get_card(card.card_key.digest)
        assert stored is not None
        deck = BasicDeck(
            name="deck", target=card.card_key.target_kind, query_path=Path("unused.rq")
        )
        service = StudyService(Graph(), repository, FsrsSettings().create_scheduler())

        reviewed = service.review(deck, stored, Rating.Good, NOW)
        with pytest.raises(StaleReviewError):
            service.review(deck, stored, Rating.Good, NOW)

        assert reviewed.card().last_review == NOW
        assert repository.connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
        assert len(repository.review_history("deck", NOW)) == 1
    finally:
        repository.close()
        directory.cleanup()


@given(card=basic_cards())
@EXPENSIVE_PROPERTY_SETTINGS
def test_invalid_card_id_sync_rolls_back_membership_changes(card: BasicCard) -> None:
    # Property: a card-ID/identity mismatch rolls back the attempted synchronization update.
    directory, repository = _repository()
    try:
        cards = {card.card_key.digest: card}
        repository.sync_deck("deck", cards, NOW)
        with pytest.raises(StorageError, match="does not match"):
            repository.sync_deck("deck", {"0" * 64: card}, NOW)
        assert {item.card_id for item in repository.active_cards("deck")} == set(cards)
    finally:
        repository.close()
        directory.cleanup()
