"""Validated deck queue settings and study-queue domain helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from fsrs import Card, State
from pydantic import Field, StrictInt

from graphcards.errors import StorageError
from graphcards.models import FrozenModel

# A finite upper bound keeps an accidental configuration from creating an
# unbounded queue or a very large session in one request.
MAX_DAILY_LIMIT = 100_000


class DailyLimits(FrozenModel):
    """Per-local-day budgets for new cards and saved reviews."""

    new_cards_per_day: StrictInt = Field(default=20, ge=0, le=MAX_DAILY_LIMIT)
    reviews_per_day: StrictInt = Field(default=200, ge=0, le=MAX_DAILY_LIMIT)


class QueueKind(StrEnum):
    """The queue kinds used by scheduled study."""

    NEW = "new"
    LEARNING = "learning"
    RELEARNING = "relearning"
    REVIEW = "review"


class NewReviewOrder(StrEnum):
    """Placement of new cards relative to review cards."""

    REVIEWS_FIRST = "reviews_first"
    REVIEW_FIRST = "reviews_first"
    REVIEWS_BEFORE_NEW = "reviews_first"
    NEW_FIRST = "new_first"
    NEW_BEFORE_REVIEWS = "new_first"
    MIXED = "mixed"
    MIX = "mixed"


class InterdayLearningReviewOrder(StrEnum):
    """Placement of interday learning cards relative to review cards."""

    LEARNING_FIRST = "learning_first"
    LEARNING_BEFORE_REVIEWS = "learning_first"
    REVIEWS_FIRST = "reviews_first"
    REVIEW_FIRST = "reviews_first"
    REVIEWS_BEFORE_LEARNING = "reviews_first"
    MIXED = "mixed"
    MIX = "mixed"


class NewCardGatherOrder(StrEnum):
    """Supported ways to gather new cards before sorting them."""

    DECK = "deck"
    DECK_ORDER = "deck"
    DECK_THEN_RANDOM_NOTES = "deck_then_random_notes"
    ASCENDING_POSITION = "ascending_position"
    DESCENDING_POSITION = "descending_position"
    RANDOM_NOTES = "random_notes"
    RANDOM_CARDS = "random_cards"


class NewCardSortOrder(StrEnum):
    """Supported ways to sort cards after new-card gathering."""

    CARD_TYPE_THEN_ORDER_GATHERED = "card_type_then_order_gathered"
    ORDER_GATHERED = "order_gathered"
    CARD_TYPE_THEN_RANDOM = "card_type_then_random"
    RANDOM_NOTE_THEN_CARD_TYPE = "random_note_then_card_type"
    RANDOM = "random"


class ReviewSortOrder(StrEnum):
    """Supported review-card sort orders."""

    DUE_DATE = "due_date"
    DUE = "due_date"
    DUE_DATE_THEN_RANDOM = "due_date_then_random"
    DUE_DATE_THEN_DECK = "due_date_then_deck"
    DECK_THEN_DUE_DATE = "deck_then_due_date"
    ASCENDING_INTERVAL = "ascending_interval"
    DESCENDING_INTERVAL = "descending_interval"
    ASCENDING_EASE = "ascending_ease"
    DESCENDING_EASE = "descending_ease"
    RELATIVE_OVERDUENESS = "relative_overdueness"
    ASCENDING_RETRIEVABILITY = "ascending_retrievability"
    RANDOM = "random"


class DeckSchedulingSettings(FrozenModel):
    """Strict, persistent display-order settings for one deck.

    GraphCards has one deck per study selection. Choices that refer to Anki
    notes, card types, or subdecks use the stable entity order when that
    source concept is not present in GraphCards.
    """

    new_review_order: NewReviewOrder = NewReviewOrder.REVIEWS_FIRST
    interday_learning_review_order: InterdayLearningReviewOrder = (
        InterdayLearningReviewOrder.LEARNING_FIRST
    )
    new_card_gather_order: NewCardGatherOrder = NewCardGatherOrder.DECK
    new_card_sort_order: NewCardSortOrder = NewCardSortOrder.ORDER_GATHERED
    review_sort_order: ReviewSortOrder = ReviewSortOrder.DUE_DATE


# These aliases keep the domain name easy to discover at service and storage
# boundaries without creating multiple models with different validation rules.
QueueSettings = DeckSchedulingSettings
SchedulingSettings = DeckSchedulingSettings
DeckQueueSettings = DeckSchedulingSettings
QueueSchedulingSettings = DeckSchedulingSettings


class QueueCounts(FrozenModel):
    """Counts for the four scheduled queues."""

    new: StrictInt = Field(default=0, ge=0)
    learning: StrictInt = Field(default=0, ge=0)
    relearning: StrictInt = Field(default=0, ge=0)
    review: StrictInt = Field(default=0, ge=0)

    def for_queue(self, queue: QueueKind | str) -> int:
        """Return the count for one queue."""

        try:
            queue_kind = QueueKind(queue)
        except (TypeError, ValueError) as error:
            raise ValueError(f"unknown study queue {queue!r}") from error
        return getattr(self, queue_kind.value)

    @property
    def total(self) -> int:
        return self.new + self.learning + self.relearning + self.review

    @classmethod
    def from_counts(cls, counts: dict[QueueKind, int]) -> QueueCounts:
        return cls(
            new=counts.get(QueueKind.NEW, 0),
            learning=counts.get(QueueKind.LEARNING, 0),
            relearning=counts.get(QueueKind.RELEARNING, 0),
            review=counts.get(QueueKind.REVIEW, 0),
        )


class DailyUsage(FrozenModel):
    """Durable review usage for one local calendar day."""

    local_date: date
    limits: DailyLimits
    new_used: StrictInt = Field(default=0, ge=0)
    reviews_used: StrictInt = Field(default=0, ge=0)

    @property
    def local_date_display(self) -> str:
        """Return the local study date in the browser's long display format."""

        return self.local_date.strftime("%B %d, %Y")

    @property
    def day(self) -> date:
        return self.local_date

    @property
    def new_limit(self) -> int:
        return self.limits.new_cards_per_day

    @property
    def reviews_limit(self) -> int:
        return self.limits.reviews_per_day

    @property
    def new_remaining(self) -> int:
        return max(0, self.new_limit - self.new_used)

    @property
    def reviews_remaining(self) -> int:
        return max(0, self.reviews_limit - self.reviews_used)

    @property
    def remaining_new(self) -> int:
        return self.new_remaining

    @property
    def remaining_reviews(self) -> int:
        return self.reviews_remaining


class QueuePlan(FrozenModel):
    """One validated selection produced by the study queue planner."""

    cards: tuple[Any, ...] = ()
    queue_counts: QueueCounts = Field(default_factory=QueueCounts)
    hidden_counts: QueueCounts = Field(default_factory=QueueCounts)
    daily_usage: DailyUsage | None = None
    queue_order: tuple[QueueKind, ...] = ()
    requested_limit: StrictInt | None = Field(default=None, ge=0)

    @property
    def selected_cards(self) -> tuple[Any, ...]:
        return self.cards

    @property
    def available_count(self) -> int:
        return len(self.cards)

    @property
    def hidden_count(self) -> int:
        return self.hidden_counts.total


def local_day_interval(local_date: date, timezone: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the half-open UTC interval for one local calendar date."""

    if not isinstance(local_date, date) or isinstance(local_date, datetime):
        raise ValueError("local_date must be a calendar date")
    if not isinstance(timezone, ZoneInfo):
        raise ValueError("timezone must be a ZoneInfo")
    start_local = datetime.combine(local_date, time.min, tzinfo=timezone)
    end_local = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=timezone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def local_day_bounds(now: datetime, timezone: ZoneInfo) -> tuple[date, datetime, datetime]:
    """Return the local date and its half-open UTC interval for an instant."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    local_date = now.astimezone(timezone).date()
    start, end = local_day_interval(local_date, timezone)
    return local_date, start, end


def classify_card(card: Card, review_count: int | None = None) -> QueueKind:
    """Map an FSRS card and review history count to a queue."""

    if review_count is not None and (type(review_count) is not int or review_count < 0):
        raise StorageError("stored review count is invalid")
    if review_count == 0 or (
        review_count is None
        and card.last_review is None
        and card.stability is None
        and card.difficulty is None
    ):
        return QueueKind.NEW
    try:
        state = State(card.state)
    except (TypeError, ValueError) as error:
        raise StorageError("stored card has an invalid FSRS state") from error
    if state is State.Learning:
        return QueueKind.LEARNING
    if state is State.Relearning:
        return QueueKind.RELEARNING
    if state is State.Review:
        return QueueKind.REVIEW
    raise StorageError("stored card has an invalid FSRS state")


def is_interday_learning(card: Card, now: datetime, timezone: ZoneInfo) -> bool:
    """Return whether a due learning card crossed a local day boundary."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(timezone, ZoneInfo):
        raise ValueError("timezone must be a ZoneInfo")
    try:
        state = State(card.state)
    except (TypeError, ValueError) as error:
        raise StorageError("stored card has an invalid FSRS state") from error
    if state not in {State.Learning, State.Relearning} or card.last_review is None:
        return False
    if card.last_review.tzinfo is None or card.last_review.utcoffset() is None:
        raise StorageError("stored card has an invalid last-review timestamp")
    return card.last_review.astimezone(timezone).date() < now.astimezone(timezone).date()


def queue_order(settings: DeckSchedulingSettings) -> tuple[QueueKind, ...]:
    """Return the stable high-level queue order shown in deck status."""

    learning = (QueueKind.LEARNING, QueueKind.RELEARNING)
    review = (QueueKind.REVIEW,)
    new = (QueueKind.NEW,)

    if settings.interday_learning_review_order is InterdayLearningReviewOrder.REVIEWS_FIRST:
        if settings.new_review_order is NewReviewOrder.NEW_FIRST:
            return new + review + learning
        return review + new + learning
    if settings.new_review_order is NewReviewOrder.NEW_FIRST:
        return learning + new + review
    return learning + review + new


QUEUE_ORDER: tuple[QueueKind, ...] = (
    QueueKind.LEARNING,
    QueueKind.RELEARNING,
    QueueKind.REVIEW,
    QueueKind.NEW,
)


def queue_capacity(queue: QueueKind, usage: DailyUsage) -> int | None:
    """Return the number of cards that may be selected from one queue today."""

    if queue is QueueKind.NEW:
        return min(usage.new_remaining, usage.reviews_remaining)
    if queue in {QueueKind.LEARNING, QueueKind.RELEARNING, QueueKind.REVIEW}:
        return usage.reviews_remaining
    return None


def queue_selection_capacities(counts: QueueCounts, usage: DailyUsage) -> QueueCounts:
    """Return per-queue selections after consuming the shared review budget."""

    remaining_reviews = usage.reviews_remaining
    remaining_new = usage.new_remaining
    selected: dict[QueueKind, int] = {}
    for queue in QUEUE_ORDER:
        allowed = min(counts.for_queue(queue), remaining_reviews)
        if queue is QueueKind.NEW:
            allowed = min(allowed, remaining_new)
            remaining_new -= allowed
        remaining_reviews -= allowed
        selected[queue] = allowed
    return QueueCounts.from_counts(selected)


__all__ = [
    "MAX_DAILY_LIMIT",
    "DailyLimits",
    "DailyUsage",
    "DeckSchedulingSettings",
    "DeckQueueSettings",
    "InterdayLearningReviewOrder",
    "NewCardGatherOrder",
    "NewCardSortOrder",
    "NewReviewOrder",
    "QueueCounts",
    "QueueKind",
    "QueuePlan",
    "QueueSettings",
    "QueueSchedulingSettings",
    "ReviewSortOrder",
    "SchedulingSettings",
    "classify_card",
    "is_interday_learning",
    "local_day_bounds",
    "local_day_interval",
    "queue_capacity",
    "queue_order",
    "queue_selection_capacities",
]
