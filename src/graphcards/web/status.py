"""Card-status filtering, sorting, pagination, and presentation."""

from __future__ import annotations

import json
import math
import re
import shlex
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from statistics import fmean
from typing import cast
from zoneinfo import ZoneInfo

from fsrs import Rating
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator
from pyparsing import (
    FollowedBy,
    Forward,
    ParseBaseException,
    ParserElement,
    Regex,
    StringEnd,
    Suppress,
    ZeroOrMore,
)

from graphcards.decks import Entity
from graphcards.references import EntityId
from graphcards.scheduling import (
    InterdayLearningReviewOrder,
    NewCardGatherOrder,
    NewCardSortOrder,
    NewReviewOrder,
    ReviewSortOrder,
)
from graphcards.storage import CardStatus, ReviewRecord, datetime_as_utc, datetime_to_text

CARD_PAGE_SIZE = 100
MAX_SEARCH_LENGTH = 512
MAX_SEARCH_TERMS = 32
MAX_SEARCH_FIELD_LENGTH = 128
MAX_SEARCH_DEPTH = 16


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
    ENTITY_ID = "entity_id"
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


class InfoTab(StrEnum):
    DECK_STATUS = "deck_status"
    STATUS = "status"
    HISTORY = "history"
    GENERATORS = "generators"


class CardDetailTab(StrEnum):
    REVIEW_HISTORY = "history"
    GENERATORS = "generators"


@dataclass(frozen=True)
class SearchTerm:
    """One validated leaf in a card-status search expression."""

    kind: str
    value: str
    field: str | None = None
    operator: str | None = None
    operand: date | float | int | None = None


@dataclass(frozen=True)
class SearchNot:
    expression: SearchExpression


@dataclass(frozen=True)
class SearchGroup:
    expression: SearchExpression


@dataclass(frozen=True)
class SearchAnd:
    expressions: tuple[SearchExpression, ...]


@dataclass(frozen=True)
class SearchOr:
    expressions: tuple[SearchExpression, ...]


SearchExpression = SearchTerm | SearchNot | SearchGroup | SearchAnd | SearchOr


_COMPARISON_PATTERN = re.compile(
    r"^(reviews|due|last_review|stability|difficulty|retrievability)(!=|>=|<=|=|>|<)(.+)$"
)
_COMPARISON_KINDS = (
    "reviews",
    "due",
    "last_review",
    "stability",
    "difficulty",
    "retrievability",
)
_FIELD_PATTERN = re.compile(r"^field:([^=]+)=(.+)$")
_RAW_ATOM_PATTERN = r"""(?:(?:[^()\s"'\\]|\\.)+|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')+"""


def _reject_search_controls(value: str) -> None:
    if len(value) > MAX_SEARCH_LENGTH:
        raise ValueError(f"search must not exceed {MAX_SEARCH_LENGTH} characters")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value
    ):
        raise ValueError("search must not contain control characters")


def _comparison_operand(kind: str, value: str) -> date | float | int:
    if kind in {"due", "last_review"}:
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{kind} must use YYYY-MM-DD") from error
    if kind == "reviews":
        if not re.fullmatch(r"[+-]?\d+", value):
            raise ValueError("reviews must compare with an integer")
        return int(value)
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"{kind} must compare with a number") from error
    if not math.isfinite(number):
        raise ValueError(f"{kind} must compare with a finite number")
    return number


def _parse_search_term(token: str) -> SearchTerm:
    if not token:
        raise ValueError("search terms must not be empty")
    if token.startswith("field:"):
        match = _FIELD_PATTERN.fullmatch(token)
        if match is None:
            raise ValueError("field search must use field:name=value")
        field_name, field_value = match.groups()
        if not field_name.strip() or len(field_name) > MAX_SEARCH_FIELD_LENGTH:
            raise ValueError("field name is too long or empty")
        return SearchTerm("field", field_value, field=field_name)
    if token.startswith("id:"):
        entity_id = token.removeprefix("id:")
        if not entity_id:
            raise ValueError("id search must include a value")
        return SearchTerm("id", entity_id.casefold())
    if token.startswith("state:"):
        state = token.removeprefix("state:").casefold()
        if state not in {"new", "learning", "review", "relearning"}:
            raise ValueError("state search has an unknown state")
        return SearchTerm("state", state)
    if ":" in token:
        raise ValueError("search contains an unknown field prefix")
    comparison = _COMPARISON_PATTERN.fullmatch(token)
    if comparison is not None:
        kind, operator, raw_operand = comparison.groups()
        return SearchTerm(
            kind,
            raw_operand,
            operator=operator,
            operand=_comparison_operand(kind, raw_operand),
        )
    if any(
        token.startswith(kind) and len(token) > len(kind) and token[len(kind)] in "!<>=~"
        for kind in _COMPARISON_KINDS
    ):
        raise ValueError("search contains an invalid comparison operator")
    return SearchTerm("text", token.casefold())


def _parse_atom(source: str, location: int, tokens: Sequence[str]) -> SearchTerm:
    del source, location
    raw_token = tokens[0]
    try:
        decoded = shlex.split(raw_token, posix=True)
    except ValueError as error:
        raise ValueError("search contains an unmatched quote") from error
    if len(decoded) != 1:
        raise ValueError("search contains an invalid term")
    return _parse_search_term(decoded[0])


def _make_not(tokens: Sequence[object]) -> SearchNot:
    return SearchNot(cast(SearchExpression, tokens[0]))


def _make_parenthesized(tokens: Sequence[object]) -> SearchGroup:
    return SearchGroup(cast(SearchExpression, tokens[0]))


def _make_group(
    tokens: Sequence[object],
    group_type: type[SearchAnd] | type[SearchOr],
) -> SearchExpression:
    expressions = tuple(cast(SearchExpression, token) for token in tokens)
    return expressions[0] if len(expressions) == 1 else group_type(expressions)


def _build_search_parser() -> ParserElement:
    """Build the bounded boolean expression parser."""

    boolean_word = Regex(r"(?i:(?:AND|OR|NOT))(?=\s|\(|\)|$)")
    raw_atom = Regex(_RAW_ATOM_PATTERN)
    atom = (~boolean_word + raw_atom).set_parse_action(_parse_atom)
    and_operator = Regex(r"(?i:AND)(?=\s|\()")
    or_operator = Regex(r"(?i:OR)(?=\s|\()")
    not_operator = Regex(r"(?i:NOT)(?=\s|\()")

    primary = Forward()
    not_expression = Forward()
    and_expression = Forward()
    or_expression = Forward()

    primary <<= atom | (Suppress("(") + or_expression + Suppress(")")).set_parse_action(
        _make_parenthesized
    )
    not_expression <<= (not_operator.copy().suppress() + not_expression).set_parse_action(
        _make_not
    ) | primary
    implicit_and = FollowedBy(not_expression)
    and_expression <<= (
        not_expression
        + ZeroOrMore(
            (and_operator.copy().suppress() | implicit_and) + not_expression,
        )
    ).set_parse_action(lambda tokens: _make_group(tokens, SearchAnd))
    or_expression <<= (
        and_expression + ZeroOrMore(or_operator.copy().suppress() + and_expression)
    ).set_parse_action(lambda tokens: _make_group(tokens, SearchOr))
    return or_expression + StringEnd()


_SEARCH_PARSER = _build_search_parser()


def _search_shape(expression: SearchExpression, depth: int = 0) -> int:
    if depth > MAX_SEARCH_DEPTH:
        raise ValueError(f"search must not nest more than {MAX_SEARCH_DEPTH} levels")
    if isinstance(expression, SearchTerm):
        return 1
    if isinstance(expression, (SearchNot, SearchGroup)):
        return _search_shape(expression.expression, depth + 1)
    return sum(_search_shape(child, depth + 1) for child in expression.expressions)


def _plain_conjunction_constraints(
    expression: SearchExpression,
) -> dict[tuple[str, str | None], str] | None:
    if isinstance(expression, SearchTerm):
        if expression.kind not in {"field", "state"}:
            return {}
        return {
            (expression.kind, expression.field): expression.value.casefold(),
        }
    if isinstance(expression, SearchNot):
        return None
    if isinstance(expression, SearchGroup):
        return _plain_conjunction_constraints(expression.expression)
    if isinstance(expression, SearchOr):
        return None
    constraints: dict[tuple[str, str | None], str] = {}
    for child in expression.expressions:
        child_constraints = _plain_conjunction_constraints(child)
        if child_constraints is None:
            return None
        for key, value in child_constraints.items():
            previous = constraints.get(key)
            if previous is not None and previous != value:
                raise ValueError("search contains conflicting terms")
            constraints[key] = value
    return constraints


def parse_search_expression(value: str) -> SearchExpression | None:
    """Parse the bounded boolean search language used by the status page."""

    _reject_search_controls(value)
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = _SEARCH_PARSER.parse_string(normalized, parse_all=True)
    except ValueError:
        raise
    except ParseBaseException as error:
        raise ValueError("search contains invalid boolean syntax") from error
    expression = cast(SearchExpression, parsed[0])
    if _search_shape(expression) > MAX_SEARCH_TERMS:
        raise ValueError(f"search must not contain more than {MAX_SEARCH_TERMS} terms")
    _plain_conjunction_constraints(expression)
    return expression


def _iter_search_terms(expression: SearchExpression | None) -> tuple[SearchTerm, ...]:
    if expression is None:
        return ()
    if isinstance(expression, SearchTerm):
        return (expression,)
    if isinstance(expression, SearchNot):
        return _iter_search_terms(expression.expression)
    if isinstance(expression, SearchGroup):
        return _iter_search_terms(expression.expression)
    return tuple(term for child in expression.expressions for term in _iter_search_terms(child))


def parse_search_terms(value: str) -> tuple[SearchTerm, ...]:
    """Return the validated leaf terms from a boolean search expression."""

    return _iter_search_terms(parse_search_expression(value))


def normalize_search_text(value: str) -> str:
    """Normalize and validate one card-status search string."""

    normalized = value.strip()
    parse_search_expression(normalized)
    return normalized


class CardStatusQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    _parsed_search: SearchExpression | None = PrivateAttr(default=None)

    page: int = Field(default=1, ge=1)
    search: str = Field(default="", max_length=MAX_SEARCH_LENGTH)
    availability: AvailabilityFilter = AvailabilityFilter.ALL
    schedule: ScheduleFilter = ScheduleFilter.ALL
    state: FsrsStateFilter = FsrsStateFilter.ALL
    sort: CardSort = CardSort.NEXT_REVIEW
    direction: SortDirection = SortDirection.ASCENDING
    range: HistoryRange = HistoryRange.NINETY_DAYS
    tab: InfoTab = InfoTab.DECK_STATUS
    preview_entity: EntityId | None = None
    preview_generator: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("search")
    @classmethod
    def validate_search(cls, value: str) -> str:
        return normalize_search_text(value)

    @model_validator(mode="after")
    def validate_search_expression(self) -> CardStatusQuery:
        object.__setattr__(self, "_parsed_search", parse_search_expression(self.search))
        return self

    @property
    def search_expression(self) -> SearchExpression | None:
        """Return the parsed boolean expression used by all card rows."""

        return self._parsed_search

    @property
    def search_terms(self) -> tuple[SearchTerm, ...]:
        """Return the validated leaf terms for compatibility with status callers."""

        return _iter_search_terms(self._parsed_search)

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> CardStatusQuery:
        copied = super().model_copy(update=update, deep=deep)
        if update is not None and "search" in update:
            object.__setattr__(copied, "_parsed_search", parse_search_expression(copied.search))
        return copied


class CardDetailQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    availability: AvailabilityFilter = AvailabilityFilter.ALL
    schedule: ScheduleFilter = ScheduleFilter.ALL
    state: FsrsStateFilter = FsrsStateFilter.ALL
    sort: CardSort = CardSort.NEXT_REVIEW
    direction: SortDirection = SortDirection.ASCENDING
    range: HistoryRange = HistoryRange.NINETY_DAYS
    tab: CardDetailTab = CardDetailTab.GENERATORS
    preview_generator: str | None = Field(default=None, min_length=1, max_length=512)

    def status_query(self) -> CardStatusQuery:
        return CardStatusQuery(
            page=self.page,
            availability=self.availability,
            schedule=self.schedule,
            state=self.state,
            sort=self.sort,
            direction=self.direction,
            range=self.range,
            tab=InfoTab.STATUS,
        )


@dataclass(frozen=True)
class StatusCard:
    status: CardStatus
    entity: Entity
    retrievability: float | None
    generator_labels: tuple[str, ...] = ()


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
    entity_id: str
    selection_value: str
    generator_labels: tuple[str, ...]


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
class GeneratorRow:
    generator_id: str
    generator_type: str
    eligible_count: int
    due_count: int


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


@dataclass(frozen=True)
class CardReviewView:
    review_id: int
    reviewed_at: DateView
    rating: str
    previous_interval: str
    scheduled_interval: str
    retrievability: str


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


def _text_values(value: object) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        values: list[str] = []
        for key, child in value.items():
            values.append(str(key))
            values.extend(_text_values(child))
        return tuple(values)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(text for child in value for text in _text_values(child))
    if value is None:
        return ()
    return (str(value),)


def _entity_values(entity: Entity) -> dict[str, object]:
    return cast(dict[str, object], entity.model_dump(mode="python"))


def _compare(left: float | int | date, operator: str, right: float | int | date) -> bool:
    if operator == "=":
        return left == right
    if operator == "!=":
        return left != right
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    return left <= right


def search_matches(
    row: StatusCard,
    query: CardStatusQuery,
    now: datetime,
    timezone: ZoneInfo,
    *,
    deck_name: str,
    deck_display_name: str,
) -> bool:
    """Return whether one status-page card matches the parsed search expression."""

    entity = row.entity
    entity_values = _entity_values(entity)
    flattened = tuple(text.casefold() for text in _text_values(entity_values))
    status = row.status
    local_timezone = timezone

    def matches_term(term: SearchTerm) -> bool:
        if term.kind == "text":
            candidates = flattened + (deck_name.casefold(), deck_display_name.casefold())
            return any(term.value in candidate for candidate in candidates)
        if term.kind == "id":
            return term.value in status.card_key.entity_id.casefold()
        if term.kind == "field":
            field_value = entity_values.get(term.field or "")
            return field_value is not None and any(
                term.value.casefold() in item.casefold() for item in _text_values(field_value)
            )
        if term.kind == "state":
            if term.value == "new":
                matches = status.review_count == 0
            else:
                matches = status.fsrs_state == term.value
            return matches
        value: float | int | date | None
        if term.kind == "reviews":
            value = status.review_count
        elif term.kind == "due":
            value = datetime_as_utc(status.due_at).astimezone(local_timezone).date()
        elif term.kind == "last_review":
            value = (
                datetime_as_utc(status.last_review_at).astimezone(local_timezone).date()
                if status.last_review_at is not None
                else None
            )
        elif term.kind == "stability":
            value = status.stability
        elif term.kind == "difficulty":
            value = status.difficulty
        else:
            value = row.retrievability
        return (
            value is not None
            and term.operator is not None
            and term.operand is not None
            and _compare(value, term.operator, term.operand)
        )

    def matches_expression(expression: SearchExpression | None) -> bool:
        if expression is None:
            return True
        if isinstance(expression, SearchTerm):
            return matches_term(expression)
        if isinstance(expression, SearchNot):
            return not matches_expression(expression.expression)
        if isinstance(expression, SearchGroup):
            return matches_expression(expression.expression)
        if isinstance(expression, SearchAnd):
            return all(matches_expression(child) for child in expression.expressions)
        return any(matches_expression(child) for child in expression.expressions)

    return matches_expression(query.search_expression)


def _sort_value(row: StatusCard, sort: CardSort) -> datetime | float | int | str | None:
    status = row.status
    return {
        CardSort.ENTITY_ID: status.card_key.entity_id,
        CardSort.NEXT_REVIEW: status.due_at,
        CardSort.LAST_REVIEW: status.last_review_at,
        CardSort.REVIEW_COUNT: status.review_count,
        CardSort.STABILITY: status.stability,
        CardSort.DIFFICULTY: status.difficulty,
        CardSort.RETRIEVABILITY: row.retrievability,
    }[sort]


def sort_status_cards(cards: list[StatusCard], query: CardStatusQuery) -> list[StatusCard]:
    ordered = sorted(cards, key=lambda row: row.status.card_key.identity_parts)
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
    queue_label = status.queue.value.title()
    if queue_label.casefold() != status.fsrs_state.casefold():
        badges.append(queue_label)
    badges.append("Due" if status.due_at <= now else "Future")
    step = f" · step {status.fsrs_step}" if status.fsrs_step is not None else ""
    identity = status.card_key.entity_id
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
        entity_id=status.card_key.entity_id,
        selection_value=json.dumps(
            {
                "deck_id": status.card_key.deck_id,
                "entity_id": status.card_key.entity_id,
            },
            separators=(",", ":"),
        ),
        generator_labels=row.generator_labels,
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
    current_streak, longest_streak = _streaks(ranged_days, today)

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


def card_review_views(
    records: tuple[ReviewRecord, ...],
    now: datetime,
    timezone: ZoneInfo,
) -> tuple[CardReviewView, ...]:
    """Format every review record for one card, newest review first."""

    views: list[CardReviewView] = []
    for record in reversed(records):
        reviewed_at = cast(DateView, _date_view(record.reviewed_at, now, timezone))
        views.append(
            CardReviewView(
                review_id=record.review_id,
                reviewed_at=reviewed_at,
                rating=_rating_label(record.rating),
                previous_interval=(
                    _duration_label(record.previous_interval_seconds)
                    if record.previous_interval_seconds is not None
                    else "—"
                ),
                scheduled_interval=(
                    _duration_label(record.scheduled_interval_seconds)
                    if record.scheduled_interval_seconds is not None
                    else "—"
                ),
                retrievability=(
                    f"{record.retrievability:.1%}" if record.retrievability is not None else "—"
                ),
            )
        )
    return tuple(views)


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
    (CardSort.ENTITY_ID, "Entity ID"),
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
QUEUE_NEW_REVIEW_OPTIONS = (
    (NewReviewOrder.REVIEWS_FIRST, "Reviews before new cards"),
    (NewReviewOrder.NEW_FIRST, "New cards before reviews"),
    (NewReviewOrder.MIXED, "Mix new cards with reviews"),
)
QUEUE_INTERDAY_OPTIONS = (
    (InterdayLearningReviewOrder.LEARNING_FIRST, "Learning before reviews"),
    (InterdayLearningReviewOrder.REVIEWS_FIRST, "Reviews before learning"),
    (InterdayLearningReviewOrder.MIXED, "Mix learning with reviews"),
)
QUEUE_GATHER_OPTIONS = (
    (NewCardGatherOrder.DECK, "Deck order"),
    (NewCardGatherOrder.DECK_THEN_RANDOM_NOTES, "Deck, then random notes"),
    (NewCardGatherOrder.ASCENDING_POSITION, "Ascending position"),
    (NewCardGatherOrder.DESCENDING_POSITION, "Descending position"),
    (NewCardGatherOrder.RANDOM_NOTES, "Random notes"),
    (NewCardGatherOrder.RANDOM_CARDS, "Random cards"),
)
QUEUE_NEW_SORT_OPTIONS = (
    (NewCardSortOrder.CARD_TYPE_THEN_ORDER_GATHERED, "Card type, then order gathered"),
    (NewCardSortOrder.ORDER_GATHERED, "Order gathered"),
    (NewCardSortOrder.CARD_TYPE_THEN_RANDOM, "Card type, then random"),
    (NewCardSortOrder.RANDOM_NOTE_THEN_CARD_TYPE, "Random note, then card type"),
    (NewCardSortOrder.RANDOM, "Random"),
)
QUEUE_REVIEW_SORT_OPTIONS = (
    (ReviewSortOrder.DUE_DATE, "Due date"),
    (ReviewSortOrder.DUE_DATE_THEN_RANDOM, "Due date, then random"),
    (ReviewSortOrder.DUE_DATE_THEN_DECK, "Due date, then deck"),
    (ReviewSortOrder.DECK_THEN_DUE_DATE, "Deck, then due date"),
    (ReviewSortOrder.ASCENDING_INTERVAL, "Ascending interval"),
    (ReviewSortOrder.DESCENDING_INTERVAL, "Descending interval"),
    (ReviewSortOrder.ASCENDING_EASE, "Ascending ease"),
    (ReviewSortOrder.DESCENDING_EASE, "Descending ease"),
    (ReviewSortOrder.RELATIVE_OVERDUENESS, "Relative overdueness"),
    (ReviewSortOrder.ASCENDING_RETRIEVABILITY, "Ascending retrievability"),
    (ReviewSortOrder.RANDOM, "Random"),
)
