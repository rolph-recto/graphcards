"""Card-status filtering, sorting, pagination, and presentation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from statistics import fmean
from typing import cast
from zoneinfo import ZoneInfo

from fsrs import Rating
from pydantic import BaseModel, ConfigDict, Field

from graphcards.models import TargetKind
from graphcards.storage import CardStatus, ReviewRecord, datetime_as_utc, datetime_to_text

CARD_PAGE_SIZE = 100


class ScheduleFilter(StrEnum):
    ALL = "all"
    NEW = "new"
    DUE = "due"
    FUTURE = "future"


class AvailabilityFilter(StrEnum):
    ALL = "all"
    AVAILABLE = "available"
    SUSPENDED = "suspended"


class FsrsStateFilter(StrEnum):
    ALL = "all"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


class CardSort(StrEnum):
    NEXT_REVIEW = "next_review"
    LAST_REVIEW = "last_review"
    REVIEW_COUNT = "review_count"
    STABILITY = "stability"
    DIFFICULTY = "difficulty"
    RETRIEVABILITY = "retrievability"


class SortDirection(StrEnum):
    ASCENDING = "asc"
    DESCENDING = "desc"


class HistoryRange(StrEnum):
    THIRTY_DAYS = "30d"
    NINETY_DAYS = "90d"
    ONE_YEAR = "1y"
    ALL = "all"


class CardStatusQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    availability: AvailabilityFilter = AvailabilityFilter.ALL
    schedule: ScheduleFilter = ScheduleFilter.ALL
    state: FsrsStateFilter = FsrsStateFilter.ALL
    sort: CardSort = CardSort.NEXT_REVIEW
    direction: SortDirection = SortDirection.ASCENDING
    range: HistoryRange = HistoryRange.NINETY_DAYS


@dataclass(frozen=True)
class StatusCard:
    status: CardStatus
    retrievability: float | None


@dataclass(frozen=True)
class DateView:
    relative: str
    exact: str
    display: str


@dataclass(frozen=True)
class StatusRow:
    status: CardStatus
    badges: tuple[str, ...]
    fsrs_label: str
    identity: str
    last_rating: str
    last_review: DateView | None
    next_review: DateView
    stability: str
    difficulty: str
    retrievability: str
    suspension_reason: str | None


@dataclass(frozen=True)
class PaginationView:
    first: int
    last: int
    total: int
    page: int
    pages: int
    previous_url: str | None
    next_url: str | None


@dataclass(frozen=True)
class HistoryBucket:
    label: str
    count: int


@dataclass(frozen=True)
class RatingView:
    label: str
    count: int
    percentage: float
    offset: float
    class_name: str


@dataclass(frozen=True)
class HistoryView:
    selected_range: HistoryRange
    range_label: str
    timezone: str
    total_reviews: int
    active_days: int
    current_streak: int
    longest_streak: int
    again_rate: str
    average_interval: str
    average_growth: str
    interval_coverage: str
    average_retrievability: str
    retrievability_coverage: str
    buckets: tuple[HistoryBucket, ...]
    volume_maximum: int
    ratings: tuple[RatingView, ...]


def schedule_matches(row: StatusCard, query: CardStatusQuery, now: datetime) -> bool:
    status = row.status
    if query.availability is AvailabilityFilter.AVAILABLE and status.suspended:
        return False
    if query.availability is AvailabilityFilter.SUSPENDED and not status.suspended:
        return False
    if query.schedule is ScheduleFilter.NEW and status.review_count != 0:
        return False
    if query.schedule is ScheduleFilter.DUE and status.due_at > now:
        return False
    if query.schedule is ScheduleFilter.FUTURE and status.due_at <= now:
        return False
    return query.state is FsrsStateFilter.ALL or status.fsrs_state == query.state.value


def _sort_value(row: StatusCard, sort: CardSort) -> datetime | float | int | None:
    status = row.status
    return {
        CardSort.NEXT_REVIEW: status.due_at,
        CardSort.LAST_REVIEW: status.last_review_at,
        CardSort.REVIEW_COUNT: status.review_count,
        CardSort.STABILITY: status.stability,
        CardSort.DIFFICULTY: status.difficulty,
        CardSort.RETRIEVABILITY: row.retrievability,
    }[sort]


def sort_status_cards(cards: list[StatusCard], query: CardStatusQuery) -> list[StatusCard]:
    ordered = sorted(cards, key=lambda row: row.status.card_id)
    present = [row for row in ordered if _sort_value(row, query.sort) is not None]
    missing = [row for row in ordered if _sort_value(row, query.sort) is None]
    present.sort(
        key=lambda row: _sort_value(row, query.sort),  # type: ignore[arg-type, return-value]
        reverse=query.direction is SortDirection.DESCENDING,
    )
    return present + missing


def _relative_time(value: datetime, now: datetime) -> str:
    seconds = round((datetime_as_utc(value) - datetime_as_utc(now)).total_seconds())
    absolute = abs(seconds)
    if absolute < 60:
        return "now"
    if absolute < 3600:
        amount, unit = max(1, round(absolute / 60)), "minute"
    elif absolute < 86400:
        amount, unit = max(1, round(absolute / 3600)), "hour"
    elif absolute < 31536000:
        amount, unit = max(1, round(absolute / 86400)), "day"
    else:
        amount, unit = max(1, round(absolute / 31536000)), "year"
    if amount != 1:
        unit += "s"
    return f"in {amount} {unit}" if seconds > 0 else f"{amount} {unit} ago"


def _human_datetime(value: datetime, timezone: ZoneInfo) -> str:
    local = datetime_as_utc(value).astimezone(timezone)
    hour = local.strftime("%I").lstrip("0") or "0"
    zone = local.tzname() or timezone.key
    return f"{local:%b} {local.day}, {local.year} at {hour}:{local:%M %p} {zone}"


def _date_view(value: datetime | None, now: datetime, timezone: ZoneInfo) -> DateView | None:
    if value is None:
        return None
    return DateView(
        relative=_relative_time(value, now),
        exact=datetime_to_text(value),
        display=_human_datetime(value, timezone),
    )


def _rating_label(rating: Rating | None) -> str:
    if rating is None:
        return "—"
    return {
        Rating.Again: "Again",
        Rating.Hard: "Hard",
        Rating.Good: "Good",
        Rating.Easy: "Easy",
    }[rating]


def status_row(
    row: StatusCard,
    now: datetime,
    timezone: ZoneInfo,
) -> StatusRow:
    status = row.status
    badges = ["Suspended"] if status.suspended else []
    if status.review_count == 0:
        badges.append("New")
    badges.extend(("Due" if status.due_at <= now else "Future", status.fsrs_state.title()))
    step = f" · step {status.fsrs_step}" if status.fsrs_step is not None else ""
    identity = " ".join(status.card_key.n3_terms)
    if status.card_key.target_kind is TargetKind.TRIPLE:
        identity += " ."
    return StatusRow(
        status=status,
        badges=tuple(badges),
        fsrs_label=status.fsrs_state.title() + step,
        identity=identity,
        last_rating=_rating_label(status.last_rating),
        last_review=_date_view(status.last_review_at, now, timezone),
        next_review=cast(DateView, _date_view(status.due_at, now, timezone)),
        stability=f"{status.stability:.2f} days" if status.stability is not None else "—",
        difficulty=f"{status.difficulty:.2f}" if status.difficulty is not None else "—",
        retrievability=(f"{row.retrievability:.1%}" if row.retrievability is not None else "—"),
        suspension_reason=status.suspension_reason,
    )


def _calendar_label(value: date) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def _range_start(selected: HistoryRange, today: date, review_days: set[date]) -> date:
    if selected is HistoryRange.THIRTY_DAYS:
        return today - timedelta(days=29)
    if selected is HistoryRange.NINETY_DAYS:
        return today - timedelta(days=89)
    if selected is HistoryRange.ONE_YEAR:
        return today - timedelta(days=364)
    return min(review_days) if review_days else today


def _streaks(review_days: set[date], today: date) -> tuple[int, int]:
    if not review_days:
        return 0, 0
    ordered = sorted(review_days)
    longest = run = 1
    for previous, current in zip(ordered, ordered[1:], strict=False):
        run = run + 1 if current - previous == timedelta(days=1) else 1
        longest = max(longest, run)

    last = ordered[-1]
    if last not in {today, today - timedelta(days=1)}:
        return 0, longest
    current_streak = 1
    cursor = last
    while cursor - timedelta(days=1) in review_days:
        cursor -= timedelta(days=1)
        current_streak += 1
    return current_streak, longest


def _bucket_key(value: date, selected: HistoryRange) -> date:
    if selected is HistoryRange.THIRTY_DAYS:
        return value
    if selected is HistoryRange.NINETY_DAYS:
        return value - timedelta(days=value.weekday())
    return _month_start(value)


def _bucket_keys(start: date, today: date, selected: HistoryRange) -> list[date]:
    if selected is HistoryRange.THIRTY_DAYS:
        return [start + timedelta(days=offset) for offset in range((today - start).days + 1)]
    if selected is HistoryRange.NINETY_DAYS:
        first = start - timedelta(days=start.weekday())
        return [first + timedelta(days=offset) for offset in range(0, (today - first).days + 1, 7)]
    keys: list[date] = []
    cursor = _month_start(start)
    while cursor <= today:
        keys.append(cursor)
        cursor = _next_month(cursor)
    return keys


def _bucket_label(value: date, selected: HistoryRange) -> str:
    if selected is HistoryRange.THIRTY_DAYS:
        return f"{value:%b} {value.day}"
    if selected is HistoryRange.NINETY_DAYS:
        end = value + timedelta(days=6)
        if value.month == end.month:
            return f"{value:%b} {value.day}–{end.day}"
        return f"{value:%b} {value.day}–{end:%b} {end.day}"
    return f"{value:%b %Y}"


def _duration_label(seconds: float) -> str:
    if seconds < 3600:
        return f"{seconds / 60:.1f} minutes"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 86400:.1f} days"


def history_view(
    records: tuple[ReviewRecord, ...],
    selected: HistoryRange,
    now: datetime,
    timezone: ZoneInfo,
) -> HistoryView:
    """Aggregate immutable review events for the status-page history section."""

    now = datetime_as_utc(now)
    today = now.astimezone(timezone).date()
    dated = tuple((record, record.reviewed_at.astimezone(timezone).date()) for record in records)
    review_days = {review_day for _, review_day in dated}
    start = _range_start(selected, today, review_days)
    ranged = tuple(record for record, review_day in dated if start <= review_day <= today)
    ranged_days = {record.reviewed_at.astimezone(timezone).date() for record in ranged}
    current_streak, longest_streak = _streaks(review_days, today)

    counts = Counter(
        _bucket_key(record.reviewed_at.astimezone(timezone).date(), selected) for record in ranged
    )
    buckets = tuple(
        HistoryBucket(
            label=_bucket_label(key, selected),
            count=counts[key],
        )
        for key in _bucket_keys(start, today, selected)
    )
    rating_counts = Counter(record.rating for record in ranged)
    total = len(ranged)
    rating_views: list[RatingView] = []
    offset = 0.0
    for rating in Rating:
        percentage = rating_counts[rating] / total * 100 if total else 0
        label = _rating_label(rating)
        rating_views.append(
            RatingView(
                label=label,
                count=rating_counts[rating],
                percentage=percentage,
                offset=offset,
                class_name=f"rating-{label.casefold()}",
            )
        )
        offset += percentage

    scheduled = [
        record.scheduled_interval_seconds
        for record in ranged
        if record.scheduled_interval_seconds is not None
    ]
    growth = [
        (record.scheduled_interval_seconds / record.previous_interval_seconds - 1) * 100
        for record in ranged
        if record.scheduled_interval_seconds is not None
        and record.previous_interval_seconds is not None
    ]
    retrievabilities = [
        record.retrievability for record in ranged if record.retrievability is not None
    ]
    again = rating_counts[Rating.Again]
    return HistoryView(
        selected_range=selected,
        range_label=f"{_calendar_label(start)}–{_calendar_label(today)}",
        timezone=timezone.key,
        total_reviews=total,
        active_days=len(ranged_days),
        current_streak=current_streak,
        longest_streak=longest_streak,
        again_rate=f"{again / total:.1%}" if total else "—",
        average_interval=_duration_label(fmean(scheduled)) if scheduled else "—",
        average_growth=f"{fmean(growth):+.1f}%" if growth else "—",
        interval_coverage=f"{len(growth)} of {total} review(s)",
        average_retrievability=(f"{fmean(retrievabilities):.1%}" if retrievabilities else "—"),
        retrievability_coverage=f"{len(retrievabilities)} of {total} review(s)",
        buckets=buckets,
        volume_maximum=max((bucket.count for bucket in buckets), default=1) or 1,
        ratings=tuple(rating_views),
    )


def pagination(
    query: CardStatusQuery,
    total: int,
    pages: int,
    page_url: Callable[[int], str],
) -> PaginationView:
    return PaginationView(
        first=(query.page - 1) * CARD_PAGE_SIZE + 1 if total else 0,
        last=min(query.page * CARD_PAGE_SIZE, total),
        total=total,
        page=query.page,
        pages=pages,
        previous_url=page_url(query.page - 1) if query.page > 1 else None,
        next_url=page_url(query.page + 1) if query.page < pages else None,
    )


SCHEDULE_OPTIONS = (
    (ScheduleFilter.ALL, "All"),
    (ScheduleFilter.NEW, "New"),
    (ScheduleFilter.DUE, "Due"),
    (ScheduleFilter.FUTURE, "Future"),
)
AVAILABILITY_OPTIONS = (
    (AvailabilityFilter.ALL, "All"),
    (AvailabilityFilter.AVAILABLE, "Available"),
    (AvailabilityFilter.SUSPENDED, "Suspended"),
)
STATE_OPTIONS = (
    (FsrsStateFilter.ALL, "All"),
    (FsrsStateFilter.LEARNING, "Learning"),
    (FsrsStateFilter.REVIEW, "Review"),
    (FsrsStateFilter.RELEARNING, "Relearning"),
)
SORT_OPTIONS = (
    (CardSort.NEXT_REVIEW, "Next review"),
    (CardSort.LAST_REVIEW, "Last review"),
    (CardSort.REVIEW_COUNT, "Review count"),
    (CardSort.STABILITY, "Stability"),
    (CardSort.DIFFICULTY, "Difficulty"),
    (CardSort.RETRIEVABILITY, "Retrievability"),
)
DIRECTION_OPTIONS = (
    (SortDirection.ASCENDING, "Ascending"),
    (SortDirection.DESCENDING, "Descending"),
)
HISTORY_RANGE_OPTIONS = (
    (HistoryRange.THIRTY_DAYS, "Last 30 days"),
    (HistoryRange.NINETY_DAYS, "Last 90 days"),
    (HistoryRange.ONE_YEAR, "Last year"),
    (HistoryRange.ALL, "All time"),
)
