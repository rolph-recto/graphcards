from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fsrs import Rating
from hypothesis import given
from hypothesis import strategies as st

from graphcards.app import StudyService
from graphcards.config import FsrsSettings
from graphcards.decks import Deck
from graphcards.errors import StaleReviewError, StorageError
from graphcards.models import Card as SemanticCard
from graphcards.models import CardKey
from graphcards.storage import Repository, datetime_as_utc, datetime_to_text
from tests.strategies import (
    EXPENSIVE_PROPERTY_SETTINGS,
    PROPERTY_SETTINGS,
    aware_datetimes,
    card_keys,
    valid_identity_strings,
)

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


@st.composite
def semantic_cards(draw: st.DrawFn) -> SemanticCard:
    return SemanticCard(card_key=draw(card_keys()))


@st.composite
def card_sets(draw: st.DrawFn) -> dict[str, SemanticCard]:
    cards = draw(
        st.lists(
            semantic_cards(),
            min_size=1,
            max_size=5,
            unique_by=lambda card: card.card_key.entity_id,
        )
    )
    return {card.card_key.entity_id: card for card in cards}


@st.composite
def rollback_card_sets(draw: st.DrawFn) -> dict[str, SemanticCard]:
    cards = draw(
        st.lists(
            semantic_cards(),
            min_size=2,
            max_size=5,
            unique_by=lambda card: card.card_key.entity_id,
        )
    )
    return {card.card_key.entity_id: card for card in cards}


def _repository(tmp_path) -> Repository:
    path = tmp_path / "state.sqlite3"
    path.unlink(missing_ok=True)
    return Repository(path)


def test_repository_can_be_constructed_for_each_generated_database(tmp_path) -> None:
    # Property: a fresh repository always exposes a valid empty status view.
    with _repository(tmp_path) as repository:
        assert repository.status("deck", NOW).available == 0


def test_bulk_suspension_is_all_or_nothing(tmp_path) -> None:
    first = SemanticCard(card_key=CardKey.exercise("deck", "first"))
    second = SemanticCard(card_key=CardKey.exercise("deck", "second"))
    path = tmp_path / "state.sqlite3"
    with Repository(path) as repository:
        repository.sync_deck("deck", {"first": first, "second": second}, NOW)
        with pytest.raises(StorageError):
            repository.suspend_cards("deck", ("first", "missing"), "focus")
        assert repository.card_available("deck", "first")
        assert repository.card_available("deck", "second")
        repository.suspend_cards("deck", ("first", "second"), "focus")
        assert repository.card_suspended("deck", "first")
        assert repository.card_suspended("deck", "second")
        repository.resume_cards("deck", ("first", "second"))
        assert repository.card_available("deck", "first")
        assert repository.card_available("deck", "second")
        assert repository.connection.execute("PRAGMA user_version").fetchone()[0] == 8


def test_inactive_memberships_cannot_be_changed_by_stale_actions(tmp_path) -> None:
    # Property: stale actions cannot mutate a membership that a sync deactivated.
    card = SemanticCard(card_key=CardKey.exercise("deck", "entity"))
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", {card.card_key.entity_id: card}, NOW)
        repository.sync_deck("deck", {}, NOW)
        with pytest.raises(StorageError):
            repository.suspend_card("deck", card.card_key.entity_id, "stale")
        repository.sync_deck("deck", {card.card_key.entity_id: card}, NOW)
        assert repository.card_available("deck", card.card_key.entity_id)


@given(value=aware_datetimes())
@PROPERTY_SETTINGS
def test_aware_datetime_serialization_is_canonical(value: datetime) -> None:
    # Property: aware datetimes serialize to canonical UTC text and round-trip exactly.
    encoded = datetime_to_text(value)
    restored = datetime.fromisoformat(encoded.replace("Z", "+00:00"))
    assert encoded.endswith("Z")
    assert restored == datetime_as_utc(value)


@given(cards=card_sets())
@EXPENSIVE_PROPERTY_SETTINGS
def test_identical_sync_is_idempotent_and_does_not_duplicate_memberships(
    cards: dict[str, SemanticCard], tmp_path
) -> None:
    # Property: syncing the same card set twice is idempotent and creates no duplicate links.
    with _repository(tmp_path) as repository:
        assert repository.sync_deck("deck", cards, NOW) == (len(cards), len(cards))
        assert repository.sync_deck("deck", cards, NOW) == (len(cards), 0)
        assert {card.card_key.entity_id for card in repository.active_cards("deck")} == set(cards)
        count = repository.connection.execute(
            "SELECT COUNT(*) FROM deck_cards WHERE deck_id = ?", ("deck",)
        ).fetchone()[0]
        assert count == len(cards)


@given(cards=card_sets())
@EXPENSIVE_PROPERTY_SETTINGS
def test_subset_sync_deactivates_memberships_but_preserves_global_cards(
    cards: dict[str, SemanticCard], tmp_path
) -> None:
    # Property: subset sync deactivates removed links while retaining global card rows.
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", cards, NOW)
        subset = dict(list(cards.items())[: max(1, len(cards) // 2)])
        repository.sync_deck("deck", subset, NOW)
        assert {card.card_key.entity_id for card in repository.active_cards("deck")} == set(subset)
        assert repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == len(
            cards
        )
        assert repository.connection.execute(
            "SELECT COUNT(*) FROM deck_cards WHERE deck_id = ? AND active = 0", ("deck",)
        ).fetchone()[0] == len(cards) - len(subset)


@given(key=card_keys(), other_deck=valid_identity_strings.filter(lambda value: value != "deck"))
@EXPENSIVE_PROPERTY_SETTINGS
def test_deck_scoped_global_identity_and_membership_remain_independent(
    key, other_deck: str, tmp_path
) -> None:
    # Property: identical card identities remain distinct when scoped to different decks.
    other_key = type(key).exercise(other_deck, key.entity_id)
    cards = {key.entity_id: SemanticCard(card_key=key)}
    other_cards = {other_key.entity_id: SemanticCard(card_key=other_key)}
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", cards, NOW)
        repository.sync_deck(other_deck, other_cards, NOW)
        assert repository.get_card(key).card_key == key
        assert repository.get_card(other_key).card_key == other_key
        assert repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2


@given(card=semantic_cards())
@EXPENSIVE_PROPERTY_SETTINGS
def test_persisted_cards_round_trip_to_equivalent_domain_values(
    card: SemanticCard, tmp_path
) -> None:
    # Property: persisted semantic cards round-trip without changing their domain identity.
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", {card.card_key.entity_id: card}, NOW)
        restored = repository.get_card(card.card_key)
        assert restored is not None
        assert restored.card_key == card.card_key
        assert restored.card().due == NOW


@given(card=semantic_cards(), reason=st.one_of(st.none(), valid_identity_strings))
@EXPENSIVE_PROPERTY_SETTINGS
def test_suspend_resume_preserves_schedule_and_availability(
    card: SemanticCard, reason: str | None, tmp_path
) -> None:
    # Property: suspend/resume changes availability only, preserving the stored schedule.
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", {card.card_key.entity_id: card}, NOW)
        before = repository.get_card(card.card_key)
        repository.suspend_card("deck", card.card_key.entity_id, reason)
        assert repository.card_suspended("deck", card.card_key.entity_id)
        assert repository.active_cards("deck") == []
        assert repository.get_card(card.card_key) == before
        repository.resume_card("deck", card.card_key.entity_id)
        assert repository.card_available("deck", card.card_key.entity_id)
        assert repository.get_card(card.card_key) == before


@given(card=semantic_cards(), rating=st.sampled_from(list(Rating)))
@EXPENSIVE_PROPERTY_SETTINGS
def test_one_review_round_trip_rejects_a_stale_snapshot(
    card: SemanticCard, rating: Rating, tmp_path
) -> None:
    # Property: one review commits once, and replaying its stale snapshot is rejected.
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", {card.card_key.entity_id: card}, NOW)
        stored = repository.get_card(card.card_key)
        assert stored is not None
        service = StudyService(repository, FsrsSettings(enable_fuzzing=False).create_scheduler())
        reviewed = service.review(_deck_for_storage(tmp_path), stored, rating, NOW)
        with pytest.raises(StaleReviewError):
            service.review(_deck_for_storage(tmp_path), stored, rating, NOW)
        assert reviewed.card().last_review == NOW
        assert len(repository.review_history("deck", NOW)) == 1


@given(cards=rollback_card_sets())
@EXPENSIVE_PROPERTY_SETTINGS
def test_sync_rolls_back_after_partial_card_id_mismatch(
    cards: dict[str, SemanticCard], tmp_path
) -> None:
    # Property: a failed multi-card sync rolls back all card and membership changes.
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", cards, NOW)
        before = {item.card_key.entity_id for item in repository.active_cards("deck")}
        before_global = repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        bad_entity = "not-the-generated-entity"
        assert bad_entity not in cards
        candidate = dict(cards)
        new_card = SemanticCard(card_key=CardKey.exercise("deck", "new-entity"))
        assert new_card.card_key.entity_id not in cards
        candidate[new_card.card_key.entity_id] = new_card
        candidate[bad_entity] = new_card
        with pytest.raises(StorageError):
            repository.sync_deck("deck", candidate, NOW)
        assert {item.card_key.entity_id for item in repository.active_cards("deck")} == before
        assert (
            repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            == before_global
        )


@given(card=semantic_cards())
@EXPENSIVE_PROPERTY_SETTINGS
def test_corrupt_persisted_payloads_are_storage_errors(card: SemanticCard, tmp_path) -> None:
    # Property: corrupt persisted card JSON is translated into StorageError.
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", {card.card_key.entity_id: card}, NOW)
        repository.connection.execute(
            "UPDATE cards SET card_json = ? WHERE deck_id = ? AND entity_id = ?",
            ("{bad", card.card_key.deck_id, card.card_key.entity_id),
        )
        repository.connection.commit()
        with pytest.raises(StorageError):
            repository.get_card(card.card_key)


@given(card=semantic_cards(), field=st.sampled_from(["card_json", "due_at"]))
@EXPENSIVE_PROPERTY_SETTINGS
def test_committed_schedule_corruption_is_rejected(
    card: SemanticCard, field: str, tmp_path
) -> None:
    # Property: corrupt committed card schedule fields cannot escape as raw parser errors.
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", {card.card_key.entity_id: card}, NOW)
        value = "{bad" if field == "card_json" else "not-a-timestamp"
        repository.connection.execute(
            f"UPDATE cards SET {field} = ? WHERE deck_id = ? AND entity_id = ?",
            (value, card.card_key.deck_id, card.card_key.entity_id),
        )
        repository.connection.commit()
        with pytest.raises(StorageError):
            repository.get_card(card.card_key)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("review_json", "{bad"),
        ("review_json", "{}"),
        ("rating", Rating.Again.value),
        ("deck_id", "other"),
    ],
)
def test_committed_review_corruption_is_rejected(tmp_path, column: str, value: object) -> None:
    # Property: corrupt review payloads are rejected consistently by every history/status reader.
    card = SemanticCard(card_key=CardKey.exercise("deck", "entity"))
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", {card.card_key.entity_id: card}, NOW)
        stored = repository.get_card(card.card_key)
        assert stored is not None
        service = StudyService(repository, FsrsSettings(enable_fuzzing=False).create_scheduler())
        service.review(_deck_for_storage(tmp_path), stored, Rating.Good, NOW)
        repository.connection.execute("PRAGMA foreign_keys = OFF")
        repository.connection.execute(f"UPDATE reviews SET {column} = ?", (value,))
        repository.connection.commit()
        with pytest.raises(StorageError):
            repository.review_history("other" if column == "deck_id" else "deck", NOW)
        if column == "deck_id":
            repository.status("deck", NOW)
            with pytest.raises(StorageError):
                repository.card_statuses("deck")
        else:
            with pytest.raises(StorageError):
                repository.status("deck", NOW)
            with pytest.raises(StorageError):
                repository.card_statuses("deck")


def test_status_ignores_reviews_from_other_decks(tmp_path) -> None:
    # Property: one deck's review corruption or history does not affect another deck's status.
    first = SemanticCard(card_key=CardKey.exercise("deck", "first"))
    second = SemanticCard(card_key=CardKey.exercise("other", "second"))
    with _repository(tmp_path) as repository:
        repository.sync_deck("deck", {first.card_key.entity_id: first}, NOW)
        repository.sync_deck("other", {second.card_key.entity_id: second}, NOW)
        stored = repository.get_card(second.card_key)
        assert stored is not None
        service = StudyService(repository, FsrsSettings(enable_fuzzing=False).create_scheduler())
        service.review(_deck_for_storage(tmp_path, "other"), stored, Rating.Good, NOW)

        status = repository.status("deck", NOW)
        assert status.available == 1
        assert status.new == 1
        assert len(repository.card_statuses("deck")) == 1


def _deck_for_storage(tmp_path, name: str = "deck") -> Deck:
    path = tmp_path / name / "deck.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text('{"entities":[],"exercises":[]}', encoding="utf-8")
    return Deck.load(path)
