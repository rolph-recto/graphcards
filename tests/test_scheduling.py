from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fsrs import Card, Rating, State
from pydantic import ValidationError

from graphcards.app import StudyService
from graphcards.config import FsrsSettings
from graphcards.decks import Deck
from graphcards.errors import DailyLimitError, StorageError
from graphcards.scheduling import (
    DailyLimits,
    DailyUsage,
    DeckSchedulingSettings,
    InterdayLearningReviewOrder,
    NewCardGatherOrder,
    NewCardSortOrder,
    NewReviewOrder,
    QueueKind,
    ReviewSortOrder,
    local_day_interval,
)
from graphcards.storage import Repository, datetime_to_text

NOW = datetime(2026, 1, 2, 12, tzinfo=UTC)
REVIEWED_AT = NOW - timedelta(days=1)


def _limited_deck(deck: Deck, limits: DailyLimits) -> Deck:
    return Deck.from_document(
        deck.document.model_copy(update={"daily_limits": limits}),
        name=deck.name,
        path=deck.path,
    )


def _force_schedule(
    repository: Repository,
    card_key,
    *,
    state: State,
    due: datetime,
    last_review: datetime,
    difficulty: float | None = None,
) -> None:
    stored = repository.get_card(card_key)
    assert stored is not None
    source = stored.card()
    card = Card(
        card_id=source.card_id,
        state=state,
        step=0 if state in {State.Learning, State.Relearning} else None,
        stability=None if state in {State.Learning, State.Relearning} else 10.0,
        difficulty=(
            difficulty if difficulty is not None else (None if state is not State.Review else 5.0)
        ),
        due=due,
        last_review=last_review,
    )
    repository.connection.execute(
        """
        UPDATE cards SET card_json = ?, due_at = ?
        WHERE deck_id = ? AND entity_id = ?
        """,
        (
            card.to_json(),
            datetime_to_text(due),
            card_key.deck_id,
            card_key.entity_id,
        ),
    )
    repository.connection.commit()


def _review_one(service: StudyService, deck: Deck, repository: Repository, entity_id: str):
    stored = next(
        card for card in repository.active_cards(deck.name) if card.card_key.entity_id == entity_id
    )
    service.review(deck, stored, Rating.Good, REVIEWED_AT)
    return repository.get_card(stored.card_key)


def test_scheduling_settings_are_strict_and_have_validated_defaults() -> None:
    defaults = DeckSchedulingSettings()

    assert defaults.new_review_order is NewReviewOrder.REVIEWS_FIRST
    assert defaults.interday_learning_review_order is InterdayLearningReviewOrder.LEARNING_FIRST
    assert defaults.new_card_gather_order is NewCardGatherOrder.DECK
    assert defaults.new_card_sort_order is NewCardSortOrder.ORDER_GATHERED
    assert defaults.review_sort_order is ReviewSortOrder.DUE_DATE

    with pytest.raises(ValidationError):
        DeckSchedulingSettings(new_review_order="free_form_queue")
    with pytest.raises(ValidationError):
        DeckSchedulingSettings.model_validate(
            {"review_sort_order": "due_date", "unexpected": "value"}
        )


def test_daily_limits_are_strict_and_have_validated_defaults() -> None:
    assert DailyLimits().new_cards_per_day == 20
    assert DailyLimits().reviews_per_day == 200
    with pytest.raises(ValidationError):
        DailyLimits(new_cards_per_day=True)
    with pytest.raises(ValidationError):
        DailyLimits(reviews_per_day=1.0)
    with pytest.raises(ValidationError):
        DailyLimits(new_cards_per_day=-1)
    with pytest.raises(ValidationError):
        DailyLimits(unknown=1)


def test_daily_usage_formats_local_date_for_display() -> None:
    usage = DailyUsage(local_date=date(2026, 8, 2), limits=DailyLimits())
    assert usage.local_date_display == "August 02, 2026"


def test_local_day_interval_uses_next_local_midnight_for_dst() -> None:
    start, end = local_day_interval(date(2026, 3, 8), ZoneInfo("America/New_York"))
    assert start == datetime(2026, 3, 8, 5, tzinfo=UTC)
    assert end == datetime(2026, 3, 9, 4, tzinfo=UTC)


def test_daily_limit_override_is_persistent(deck: Deck, tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite3"
    with Repository(state_path) as repository:
        assert repository.daily_limits(deck.name, deck.daily_limits) == deck.daily_limits
        saved = repository.set_daily_limits(
            deck.name,
            DailyLimits(new_cards_per_day=7, reviews_per_day=11),
        )
        assert saved == DailyLimits(new_cards_per_day=7, reviews_per_day=11)
        assert repository.daily_limits(deck.name, deck.daily_limits) == saved

    with Repository(state_path) as repository:
        assert repository.daily_limits(deck.name, deck.daily_limits) == saved


def test_daily_usage_is_persistent_and_review_limit_is_atomic(deck: Deck, tmp_path: Path) -> None:
    limited = _limited_deck(deck, DailyLimits(new_cards_per_day=1, reviews_per_day=1))
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(
            repository,
            FsrsSettings(enable_fuzzing=False).create_scheduler(),
            display_timezone=ZoneInfo("UTC"),
        )
        service.sync(limited, now)
        cards = repository.active_cards(limited.name)
        service.review(limited, cards[0], Rating.Good, now)
        before = repository.get_card(cards[1].card_key)
        assert before is not None

        with pytest.raises(DailyLimitError, match="daily reviews limit reached"):
            service.review(limited, before, Rating.Good, now)

        assert repository.get_card(cards[1].card_key) == before
        usage = repository.daily_usage(limited.name, now, ZoneInfo("UTC"), limited.daily_limits)
        assert (usage.new_used, usage.reviews_used) == (1, 1)
        assert len(repository.review_history(limited.name, now)) == 1


def test_queue_plan_applies_new_and_review_budgets(deck: Deck, tmp_path: Path) -> None:
    limited = _limited_deck(deck, DailyLimits(new_cards_per_day=1, reviews_per_day=1))
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(
            repository,
            FsrsSettings(enable_fuzzing=False).create_scheduler(),
            display_timezone=ZoneInfo("UTC"),
        )
        service.sync(limited, now)
        plan = service.plan_queue(limited, "due", now, 0)
        first_queue = service.queue_for_card(plan.cards[0])

    assert plan.queue_counts.new == 3
    assert plan.hidden_counts.new == 2
    assert len(plan.cards) == 1
    assert first_queue is QueueKind.NEW


def test_deck_defaults_and_persisted_settings_round_trip(deck_path: Path, tmp_path: Path) -> None:
    document = json.loads(deck_path.read_text(encoding="utf-8"))
    document["scheduling"] = {
        "new_review_order": "new_first",
        "review_sort_order": "ascending_interval",
    }
    configured_path = tmp_path / "configured" / "deck.json"
    configured_path.parent.mkdir()
    configured_path.write_text(json.dumps(document), encoding="utf-8")
    deck = Deck.load(configured_path)
    settings = DeckSchedulingSettings(
        new_review_order=NewReviewOrder.NEW_FIRST,
        interday_learning_review_order=InterdayLearningReviewOrder.REVIEWS_FIRST,
        new_card_gather_order=NewCardGatherOrder.RANDOM_CARDS,
        new_card_sort_order=NewCardSortOrder.RANDOM,
        review_sort_order=ReviewSortOrder.DESCENDING_INTERVAL,
    )

    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler())
        service.sync(deck, NOW)
        assert repository.deck_settings(deck.name, deck.scheduling) == deck.scheduling
        repository.set_deck_settings(deck.name, settings)
        repository.close()
        with Repository(tmp_path / "state.sqlite3") as reopened:
            assert reopened.deck_settings(deck.name, deck.scheduling) == settings


def test_schema_seven_state_migrates_to_persisted_queue_settings(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    repository = Repository(path)
    repository.connection.execute("DROP TABLE deck_settings")
    repository.connection.execute("PRAGMA user_version = 7")
    repository.connection.commit()
    repository.close()

    with Repository(path) as migrated:
        assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == 8
        settings = DeckSchedulingSettings(new_review_order=NewReviewOrder.NEW_FIRST)
        assert migrated.set_deck_settings("deck", settings) == settings
        assert migrated.deck_settings("deck") == settings


def test_corrupt_persisted_queue_settings_are_storage_errors(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with Repository(path) as repository:
        repository.connection.execute(
            """
            INSERT INTO deck_settings (
                deck_id, new_review_order, interday_learning_review_order,
                new_card_gather_order, new_card_sort_order, review_sort_order
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("deck", "not-supported", "learning_first", "deck", "order_gathered", "due_date"),
        )
        repository.connection.commit()
        with pytest.raises(StorageError, match="settings"):
            repository.deck_settings("deck")


def test_queue_plan_applies_new_review_and_review_sort_settings(deck: Deck, tmp_path: Path) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler())
        service.sync(deck, NOW - timedelta(days=2))
        reviewed = _review_one(service, deck, repository, "france")
        assert reviewed is not None
        _force_schedule(
            repository,
            reviewed.card_key,
            state=State.Review,
            due=NOW,
            last_review=REVIEWED_AT,
            difficulty=5.0,
        )

        default_plan = service.queue_plan(deck, now=NOW)
        assert default_plan.queue_counts == service.repository.queue_counts(deck.name, NOW)
        assert default_plan.queue_counts.review == 1
        assert default_plan.queue_counts.new == 2
        assert default_plan.cards[0].card_key.entity_id == "france"

        repository.set_deck_settings(
            deck.name,
            DeckSchedulingSettings(
                new_review_order=NewReviewOrder.NEW_FIRST,
                review_sort_order=ReviewSortOrder.DUE_DATE,
            ),
        )
        new_first_plan = service.plan_queue(deck, now=NOW)
        assert new_first_plan.cards[0].card_key.entity_id != "france"

        repository.set_deck_settings(
            deck.name,
            DeckSchedulingSettings(review_sort_order=ReviewSortOrder.ASCENDING_EASE),
        )
        _review_one(service, deck, repository, "germany")
        germany = repository.get_card(
            next(
                card.card_key
                for card in repository.active_cards(deck.name)
                if card.card_key.entity_id == "germany"
            )
        )
        assert germany is not None
        _force_schedule(
            repository,
            germany.card_key,
            state=State.Review,
            due=NOW,
            last_review=REVIEWED_AT,
            difficulty=2.0,
        )
        ease_plan = service.queue_plan(deck, now=NOW)
        assert [card.card_key.entity_id for card in ease_plan.cards[:2]] == ["france", "germany"]


def test_interday_learning_order_is_applied_to_the_study_plan(deck: Deck, tmp_path: Path) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler())
        service.sync(deck, NOW - timedelta(days=2))
        learning = _review_one(service, deck, repository, "france")
        review = _review_one(service, deck, repository, "germany")
        assert learning is not None and review is not None
        _force_schedule(
            repository,
            learning.card_key,
            state=State.Learning,
            due=NOW,
            last_review=REVIEWED_AT,
        )
        _force_schedule(
            repository,
            review.card_key,
            state=State.Review,
            due=NOW,
            last_review=REVIEWED_AT,
        )

        repository.set_deck_settings(
            deck.name,
            DeckSchedulingSettings(
                new_review_order=NewReviewOrder.REVIEWS_FIRST,
                interday_learning_review_order=InterdayLearningReviewOrder.LEARNING_FIRST,
            ),
        )
        learning_first = service.queue_plan(deck, now=NOW)
        assert [card.card_key.entity_id for card in learning_first.cards[:2]] == [
            "france",
            "germany",
        ]

        repository.set_deck_settings(
            deck.name,
            DeckSchedulingSettings(
                new_review_order=NewReviewOrder.REVIEWS_FIRST,
                interday_learning_review_order=InterdayLearningReviewOrder.REVIEWS_FIRST,
            ),
        )
        reviews_first = service.queue_plan(deck, now=NOW)
        review_order = [card.card_key.entity_id for card in reviews_first.cards]
        assert review_order.index("germany") < review_order.index("france")


def test_queue_classification_reports_all_supported_fsrs_states(deck: Deck, tmp_path: Path) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        service = StudyService(repository, FsrsSettings().create_scheduler())
        service.sync(deck, NOW)
        learning = _review_one(service, deck, repository, "france")
        relearning = _review_one(service, deck, repository, "germany")
        review = _review_one(service, deck, repository, "italy")
        assert learning is not None and relearning is not None and review is not None
        _force_schedule(
            repository, learning.card_key, state=State.Learning, due=NOW, last_review=REVIEWED_AT
        )
        _force_schedule(
            repository,
            relearning.card_key,
            state=State.Relearning,
            due=NOW,
            last_review=REVIEWED_AT,
        )
        _force_schedule(
            repository, review.card_key, state=State.Review, due=NOW, last_review=REVIEWED_AT
        )

        counts = repository.queue_counts(deck.name, NOW)
        assert counts.learning == 1
        assert counts.relearning == 1
        assert counts.review == 1
        assert counts.new == 0
        assert service.queue_plan(deck, now=NOW).queue_order == (
            QueueKind.LEARNING,
            QueueKind.RELEARNING,
            QueueKind.REVIEW,
        )
