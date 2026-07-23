"""Card-status filtering, sorting, pagination, and presentation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

from fsrs import Rating
from pydantic import BaseModel, ConfigDict, Field

from rdfcards.storage import CardStatus, datetime_as_utc, datetime_to_text

CARD_PAGE_SIZE = 100


class ScheduleFilter(StrEnum):
    ALL = "all"
    NEW = "new"
    DUE = "due"
    FUTURE = "future"


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


class CardStatusQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    schedule: ScheduleFilter = ScheduleFilter.ALL
    state: FsrsStateFilter = FsrsStateFilter.ALL
    sort: CardSort = CardSort.NEXT_REVIEW
    direction: SortDirection = SortDirection.ASCENDING


@dataclass(frozen=True)
class StatusCard:
    status: CardStatus
    retrievability: float | None


@dataclass(frozen=True)
class DateView:
    relative: str
    exact: str


@dataclass(frozen=True)
class StatusRow:
    status: CardStatus
    front: str | None
    badges: tuple[str, ...]
    fsrs_label: str
    identity: str
    last_rating: str
    last_review: DateView | None
    next_review: DateView
    stability: str
    difficulty: str
    retrievability: str


@dataclass(frozen=True)
class PaginationView:
    first: int
    last: int
    total: int
    page: int
    pages: int
    previous_url: str | None
    next_url: str | None


def schedule_matches(row: StatusCard, query: CardStatusQuery, now: datetime) -> bool:
    status = row.status
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


def _date_view(value: datetime | None, now: datetime) -> DateView | None:
    if value is None:
        return None
    return DateView(relative=_relative_time(value, now), exact=datetime_to_text(value))


def _rating_label(rating: Rating | None) -> str:
    if rating is None:
        return "—"
    return {
        Rating.Again: "Again",
        Rating.Hard: "Hard",
        Rating.Good: "Good",
        Rating.Easy: "Easy",
    }[rating]


def status_row(row: StatusCard, front: str | None, now: datetime) -> StatusRow:
    status = row.status
    badges = ["New"] if status.review_count == 0 else []
    badges.extend(("Due" if status.due_at <= now else "Future", status.fsrs_state.title()))
    step = f" · step {status.fsrs_step}" if status.fsrs_step is not None else ""
    return StatusRow(
        status=status,
        front=front,
        badges=tuple(badges),
        fsrs_label=status.fsrs_state.title() + step,
        identity=" ".join(status.card_key.n3_terms),
        last_rating=_rating_label(status.last_rating),
        last_review=_date_view(status.last_review_at, now),
        next_review=cast(DateView, _date_view(status.due_at, now)),
        stability=f"{status.stability:.2f} days" if status.stability is not None else "—",
        difficulty=f"{status.difficulty:.2f}" if status.difficulty is not None else "—",
        retrievability=(f"{row.retrievability:.1%}" if row.retrievability is not None else "—"),
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
