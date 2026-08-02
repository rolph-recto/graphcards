"""Study-session orchestration across JSON/TOML/YAML decks, SQLite, and FSRS."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fsrs import Rating, Scheduler

from graphcards.decks import Deck
from graphcards.errors import PresentationError, StorageError
from graphcards.models import Card, CardView
from graphcards.presentation import execute_cards, render_card
from graphcards.scheduling import (
    DailyLimits,
    DailyUsage,
    DeckSchedulingSettings,
    InterdayLearningReviewOrder,
    NewCardGatherOrder,
    NewCardSortOrder,
    NewReviewOrder,
    QueueCounts,
    QueueKind,
    QueuePlan,
    ReviewSortOrder,
    is_interday_learning,
    queue_selection_capacities,
)
from graphcards.storage import Repository, StoredCard, datetime_as_utc, utc_now


class StudyService:
    """Coordinate graph rendering, persistent state, and FSRS reviews."""

    def __init__(
        self,
        repository: Repository,
        scheduler: Scheduler,
        rng: random.Random | None = None,
        display_timezone: ZoneInfo | None = None,
    ) -> None:
        self.repository = repository
        self.scheduler = scheduler
        self.rng = rng or random.Random()
        self.display_timezone = display_timezone or ZoneInfo("UTC")

    def sync(self, deck: Deck, now: datetime | None = None) -> tuple[int, int]:
        cards = self.generate_all(deck)
        return self.repository.sync_deck(
            deck.name,
            cards,
            now or utc_now(),
            daily_limits=deck.daily_limits,
            scheduling=deck.scheduling,
        )

    def generate_all(self, deck: Deck) -> dict[str, Card]:
        """Generate every current semantic exercise from one validated deck."""

        return execute_cards(deck, rng=self.rng)

    def render_all(self, deck: Deck) -> dict[str, CardView]:
        """Generate and render all current cards at the application boundary."""

        return {
            entity_id: render_card(deck, card)
            for entity_id, card in self.generate_all(deck).items()
        }

    def render(self, deck: Deck, stored_card: StoredCard) -> CardView:
        cards = execute_cards(deck, stored_card.card_key, rng=self.rng)
        card = cards.get(stored_card.card_key.entity_id)
        if card is None:
            raise PresentationError(
                f"deck {deck.name!r} no longer generates entity {stored_card.card_key.entity_id!r}"
            )
        return render_card(deck, card)

    def scheduling(self, deck: Deck) -> DeckSchedulingSettings:
        """Return persisted settings, using deck-file defaults when unset."""

        return self.repository.deck_settings(deck.name, deck.scheduling)

    def deck_settings(self, deck: Deck) -> DeckSchedulingSettings:
        """Alias for the persisted settings lookup."""

        return self.scheduling(deck)

    def queue_settings(self, deck: Deck) -> DeckSchedulingSettings:
        """Alias for callers that use queue terminology."""

        return self.scheduling(deck)

    def daily_limits(self, deck: Deck) -> DailyLimits:
        """Return persisted daily limits, using deck-file defaults when unset."""

        return self.repository.daily_limits(deck.name, deck.daily_limits)

    def daily_usage(self, deck: Deck, now: datetime | None = None) -> DailyUsage:
        """Return durable usage for the deck's current local day."""

        current = datetime_as_utc(now or utc_now())
        return self.repository.daily_usage(
            deck.name,
            current,
            self.display_timezone,
            self.daily_limits(deck),
        )

    def queue_for_card(self, card: StoredCard) -> QueueKind:
        """Return a stored card's current queue kind."""

        return self.repository.queue_kind(card.card_key)

    def queue_plan(
        self,
        deck: Deck,
        mode: object = "due",
        now: datetime | None = None,
        requested_limit: int = 0,
        days: int = 1,
    ) -> QueuePlan:
        """Build a study selection using the deck's saved queue settings."""

        if type(requested_limit) is not int or requested_limit < 0:
            raise ValueError("requested session limit must be a non-negative integer")
        if type(days) is not int or days < 1:
            raise ValueError("study window must be a positive integer number of days")
        current = datetime_as_utc(now or utc_now())
        mode_value = getattr(mode, "value", mode)
        if not isinstance(mode_value, str):
            raise ValueError("study mode must be text")
        settings = self.scheduling(deck)
        usage = self.daily_usage(deck, current)
        session_limit = None if requested_limit == 0 else requested_limit

        if mode_value == "practice":
            cards = self.repository.active_cards(deck.name)
            self.rng.shuffle(cards)
            if session_limit is not None:
                cards = cards[:session_limit]
            return QueuePlan(
                cards=tuple(cards),
                queue_counts=self.repository.queue_counts(deck.name, current, due_only=False),
                daily_usage=usage,
                queue_order=tuple(
                    dict.fromkeys(self.repository.queue_kind(card.card_key) for card in cards)
                ),
                requested_limit=session_limit,
            )

        if mode_value == "due":
            candidates = self.repository.queue_cards(deck.name, current, due_only=True)
        elif mode_value == "forgotten":
            candidates = self.repository.forgotten_cards(
                deck.name,
                current - timedelta(days=days),
                None,
            )
        elif mode_value == "ahead":
            candidates = self.repository.future_cards(
                deck.name,
                current,
                current + timedelta(days=days),
                None,
            )
        else:
            raise ValueError(f"unknown study mode {mode_value!r}")

        ordered, counts = self._order_candidates(deck, candidates, settings, current)
        capacities = queue_selection_capacities(counts, usage)
        selected: list[StoredCard] = []
        hidden: dict[QueueKind, int] = {queue: 0 for queue in QueueKind}
        remaining_reviews = usage.reviews_remaining
        remaining_new = usage.new_remaining
        for card in ordered:
            queue = self.repository.queue_kind(card.card_key)
            allowed = remaining_reviews > 0
            if queue is QueueKind.NEW:
                allowed = allowed and remaining_new > 0
            if allowed:
                selected.append(card)
                remaining_reviews -= 1
                if queue is QueueKind.NEW:
                    remaining_new -= 1
            else:
                hidden[queue] += 1
        # Keep this validation in the service boundary. It catches an invalid
        # queue count before the per-card selection loop crosses storage data.
        for queue in QueueKind:
            if capacities.for_queue(queue) < 0:
                raise StorageError("stored queue capacity is invalid")
        if session_limit is not None:
            selected = selected[:session_limit]
        return QueuePlan(
            cards=tuple(selected),
            queue_counts=counts,
            hidden_counts=QueueCounts.from_counts(hidden),
            daily_usage=usage,
            queue_order=tuple(
                dict.fromkeys(self.repository.queue_kind(card.card_key) for card in selected)
            ),
            requested_limit=session_limit,
        )

    def plan_queue(
        self,
        deck: Deck,
        mode: object = "due",
        now: datetime | None = None,
        requested_limit: int = 0,
        days: int = 1,
    ) -> QueuePlan:
        """Alias for callers that describe queue planning as an action."""

        return self.queue_plan(deck, mode, now, requested_limit, days)

    @staticmethod
    def _interleave(first: list[StoredCard], second: list[StoredCard]) -> list[StoredCard]:
        combined: list[StoredCard] = []
        for index in range(max(len(first), len(second))):
            if index < len(first):
                combined.append(first[index])
            if index < len(second):
                combined.append(second[index])
        return combined

    def _order_candidates(
        self,
        deck: Deck,
        candidates: list[StoredCard],
        settings: DeckSchedulingSettings,
        now: datetime,
    ) -> tuple[list[StoredCard], QueueCounts]:
        grouped: dict[QueueKind, list[StoredCard]] = {queue: [] for queue in QueueKind}
        interday: list[StoredCard] = []
        intraday: list[StoredCard] = []
        for card in candidates:
            queue = self.repository.queue_kind(card.card_key)
            grouped[queue].append(card)
            if queue in {QueueKind.LEARNING, QueueKind.RELEARNING}:
                if is_interday_learning(card.card(), now, self.display_timezone):
                    interday.append(card)
                else:
                    intraday.append(card)

        counts = QueueCounts.from_counts({queue: len(cards) for queue, cards in grouped.items()})

        def learning_key(card: StoredCard) -> tuple[datetime, str]:
            return datetime_as_utc(card.card().due), card.card_key.entity_id

        intraday.sort(key=learning_key)
        interday.sort(key=learning_key)

        new_cards = self._sort_new_cards(grouped[QueueKind.NEW], settings)
        review_cards = self._sort_review_cards(grouped[QueueKind.REVIEW], settings, now)
        if settings.new_review_order is NewReviewOrder.NEW_FIRST:
            review_and_new = new_cards + review_cards
        elif settings.new_review_order is NewReviewOrder.MIXED:
            review_and_new = self._interleave(review_cards, new_cards)
        else:
            review_and_new = review_cards + new_cards

        if settings.interday_learning_review_order is InterdayLearningReviewOrder.LEARNING_FIRST:
            later = interday + review_and_new
        elif settings.interday_learning_review_order is InterdayLearningReviewOrder.MIXED:
            later = self._interleave(interday, review_and_new)
        else:
            later = review_and_new + interday
        return intraday + later, counts

    def _sort_new_cards(
        self,
        cards: list[StoredCard],
        settings: DeckSchedulingSettings,
    ) -> list[StoredCard]:
        gathered = list(cards)
        gathered.sort(key=lambda card: card.card_key.entity_id)
        if settings.new_card_gather_order in {
            NewCardGatherOrder.RANDOM_NOTES,
            NewCardGatherOrder.RANDOM_CARDS,
            NewCardGatherOrder.DECK_THEN_RANDOM_NOTES,
        }:
            self.rng.shuffle(gathered)
        elif settings.new_card_gather_order is NewCardGatherOrder.DESCENDING_POSITION:
            gathered.reverse()

        if settings.new_card_sort_order in {
            NewCardSortOrder.RANDOM,
            NewCardSortOrder.CARD_TYPE_THEN_RANDOM,
            NewCardSortOrder.RANDOM_NOTE_THEN_CARD_TYPE,
        }:
            self.rng.shuffle(gathered)
        return gathered

    def _sort_review_cards(
        self,
        cards: list[StoredCard],
        settings: DeckSchedulingSettings,
        now: datetime,
    ) -> list[StoredCard]:
        ordered = list(cards)
        option = settings.review_sort_order
        if option is ReviewSortOrder.RANDOM:
            self.rng.shuffle(ordered)
            return ordered

        def values(card: StoredCard) -> tuple[datetime, float, float, float, str]:
            source = card.card()
            due = datetime_as_utc(source.due)
            last_review = (
                datetime_as_utc(source.last_review) if source.last_review is not None else due
            )
            interval = max(0.0, (due - last_review).total_seconds())
            difficulty = source.difficulty if source.difficulty is not None else 0.0
            retrievability = 1.0
            if source.stability is not None and source.last_review is not None:
                try:
                    retrievability = self.scheduler.get_card_retrievability(
                        source,
                        current_datetime=now,
                    )
                except (OverflowError, TypeError, ValueError) as error:
                    raise StorageError("stored card retrievability is invalid") from error
            return due, interval, difficulty, retrievability, card.card_key.entity_id

        if option is ReviewSortOrder.DUE_DATE_THEN_RANDOM:
            self.rng.shuffle(ordered)
            ordered.sort(key=lambda card: values(card)[0])
        elif option in {ReviewSortOrder.DUE_DATE, ReviewSortOrder.DUE_DATE_THEN_DECK}:
            ordered.sort(key=lambda card: (values(card)[0], values(card)[4]))
        elif option is ReviewSortOrder.DECK_THEN_DUE_DATE:
            ordered.sort(key=lambda card: (values(card)[4], values(card)[0]))
        elif option is ReviewSortOrder.ASCENDING_INTERVAL:
            ordered.sort(key=lambda card: (values(card)[1], values(card)[4]))
        elif option is ReviewSortOrder.DESCENDING_INTERVAL:
            ordered.sort(key=lambda card: (values(card)[1], values(card)[4]), reverse=True)
        elif option is ReviewSortOrder.ASCENDING_EASE:
            ordered.sort(key=lambda card: (-values(card)[2], values(card)[4]))
        elif option is ReviewSortOrder.DESCENDING_EASE:
            ordered.sort(key=lambda card: (values(card)[2], values(card)[4]))
        elif option is ReviewSortOrder.RELATIVE_OVERDUENESS:
            ordered.sort(
                key=lambda card: (
                    max(0.0, (now - values(card)[0]).total_seconds()) / max(values(card)[1], 1.0),
                    values(card)[4],
                ),
                reverse=True,
            )
        elif option is ReviewSortOrder.ASCENDING_RETRIEVABILITY:
            ordered.sort(key=lambda card: (values(card)[3], values(card)[4]))
        return ordered

    def suspend(
        self,
        deck: Deck,
        entity_id: str,
        reason: str | None = None,
    ) -> None:
        """Suspend one membership without changing its global FSRS card."""

        self.repository.suspend_card(deck.name, entity_id, reason)

    def resume(self, deck: Deck, entity_id: str) -> None:
        """Resume one membership at its existing global FSRS schedule."""

        self.repository.resume_card(deck.name, entity_id)

    def suspend_many(
        self,
        deck: Deck,
        entity_ids: tuple[str, ...],
        reason: str | None = None,
    ) -> None:
        """Suspend several memberships without changing their global schedules."""

        self.repository.suspend_cards(deck.name, entity_ids, reason)

    def resume_many(self, deck: Deck, entity_ids: tuple[str, ...]) -> None:
        """Resume several memberships at their existing global schedules."""

        self.repository.resume_cards(deck.name, entity_ids)

    def review(
        self,
        deck: Deck,
        card: StoredCard,
        rating: Rating,
        now: datetime | None = None,
    ) -> StoredCard:
        if card.card_key.deck_id != deck.name:
            raise PresentationError(
                f"card {card.card_key.entity_id!r} does not belong to deck {deck.name!r}"
            )
        review_time = datetime_as_utc(now or utc_now())
        source_card = card.card()
        previous_interval_seconds = (
            (
                datetime_as_utc(source_card.due) - datetime_as_utc(source_card.last_review)
            ).total_seconds()
            if source_card.last_review is not None
            else None
        )
        retrievability = (
            self.scheduler.get_card_retrievability(
                source_card,
                current_datetime=review_time,
            )
            if source_card.stability is not None and source_card.last_review is not None
            else None
        )
        updated_card, review_log = self.scheduler.review_card(
            source_card, rating, review_datetime=review_time
        )
        card_json = self.repository.save_review(
            card.card_key,
            card.card_json,
            updated_card,
            review_log,
            previous_interval_seconds=previous_interval_seconds,
            retrievability=retrievability,
            daily_limits=self.daily_limits(deck),
            timezone=self.display_timezone,
        )
        return StoredCard(
            card_key=card.card_key,
            card_json=card_json,
        )
