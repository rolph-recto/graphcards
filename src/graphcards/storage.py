"""SQLite persistence for global FSRS cards, deck membership, and reviews."""

from __future__ import annotations

import json
import math
import sqlite3
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fsrs import Card, Rating, ReviewLog
from pydantic import ConfigDict, Field, StrictFloat, StrictInt, ValidationError, field_validator

from graphcards.errors import DailyLimitError, StaleReviewError, StorageError
from graphcards.models import Card as SemanticCard
from graphcards.models import CardKey, FrozenModel, validation_message
from graphcards.scheduling import (
    DailyLimits,
    DailyUsage,
    DeckSchedulingSettings,
    QueueCounts,
    QueueKind,
    classify_card,
    local_day_bounds,
    queue_order,
    queue_selection_capacities,
)

SCHEMA_VERSION = 8
_PREVIOUS_SCHEMA_VERSION = 7
MAX_SUSPENSION_REASON_LENGTH = 500
_UNSAFE_REASON_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def normalize_suspension_reason(value: object) -> object:
    """Canonicalize user reason text and reject terminal control characters."""

    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        return None
    if any(
        unicodedata.category(character) in _UNSAFE_REASON_CATEGORIES for character in normalized
    ):
        raise ValueError(
            "suspension reason cannot contain control characters, format controls, "
            "or line separators"
        )
    return normalized


def utc_now() -> datetime:
    return datetime.now(UTC)


def datetime_as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StorageError("datetime values must be timezone-aware")
    return value.astimezone(UTC)


def datetime_to_text(value: datetime) -> str:
    """Encode timestamps in the one sortable UTC representation used by SQLite."""

    return datetime_as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _datetime_from_text(value: object) -> datetime:
    """Decode and validate timestamps read from storage."""

    if not isinstance(value, str):
        raise StorageError("stored timestamp is not text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StorageError("stored timestamp is invalid") from error
    parsed = datetime_as_utc(parsed)
    if datetime_to_text(parsed) != value:
        raise StorageError("stored timestamp is not canonical UTC")
    return parsed


def _strict_count(value: object, label: str) -> int:
    """Validate a SQLite count before it crosses the storage boundary."""

    if type(value) is not int or value < 0:
        raise StorageError(f"stored {label} count is invalid")
    return value


class StoredCard(FrozenModel):
    card_key: CardKey
    card_json: str

    def card(self) -> Card:
        try:
            card = Card.from_json(self.card_json)
            datetime_as_utc(card.due)
            if card.last_review is not None:
                datetime_as_utc(card.last_review)
            for value in (card.stability, card.difficulty):
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError("FSRS numeric field is invalid")
            return card
        except (json.JSONDecodeError, KeyError, OverflowError, TypeError, ValueError) as error:
            raise StorageError("stored card schedule is invalid") from error


class DeckStatus(FrozenModel):
    available: StrictInt = Field(ge=0)
    suspended: StrictInt = Field(ge=0)
    new: StrictInt = Field(ge=0)
    due: StrictInt = Field(ge=0)
    future: StrictInt = Field(ge=0)
    queue_counts: QueueCounts = Field(default_factory=QueueCounts)
    queue_order: tuple[QueueKind, ...] = ()
    scheduling: DeckSchedulingSettings = Field(default_factory=DeckSchedulingSettings)

    @property
    def queues(self) -> QueueCounts:
        """Return the due-card counts grouped by queue."""

        return self.queue_counts

    @property
    def settings(self) -> DeckSchedulingSettings:
        """Return the validated settings used for this status snapshot."""

        return self.scheduling


class DeckQueueStatus(DeckStatus):
    """Deck status with daily-limit accounting for legacy callers and CLI output."""

    hidden_counts: QueueCounts = Field(default_factory=QueueCounts)
    daily_usage: DailyUsage

    @property
    def hidden(self) -> QueueCounts:
        return self.hidden_counts

    @property
    def daily_limits(self) -> DailyLimits:
        return self.daily_usage.limits

    @property
    def hidden_card_counts(self) -> QueueCounts:
        return self.hidden_counts

    @property
    def studyable_due(self) -> int:
        return max(0, self.queue_counts.total - self.hidden_counts.total)

    @property
    def new_hidden(self) -> int:
        return self.hidden_counts.new

    @property
    def review_hidden(self) -> int:
        return self.hidden_counts.review


class CardStatus(FrozenModel):
    """Card-level schedule details used by the full status view."""

    card_key: CardKey
    card_json: str
    fsrs_state: str
    fsrs_step: int | None
    stability: float | None
    difficulty: float | None
    review_count: int
    due_at: datetime
    last_review_at: datetime | None
    last_rating: Rating | None
    suspended: bool
    suspension_reason: str | None
    queue: QueueKind = QueueKind.NEW

    @property
    def queue_kind(self) -> QueueKind:
        return self.queue

    def stored_card(self) -> StoredCard:
        """Rebuild the complete stored card used for read-only FSRS calculations."""

        return StoredCard(
            card_key=self.card_key,
            card_json=self.card_json,
        )


class SuspensionUpdate(FrozenModel):
    """Validated current suspension metadata for one deck membership."""

    reason: str | None = Field(default=None, max_length=MAX_SUSPENSION_REASON_LENGTH)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return normalize_suspension_reason(value)


class ReviewPayload(FrozenModel):
    """Validated immutable data stored in one review JSON document."""

    model_config = FrozenModel.model_config | ConfigDict(
        populate_by_name=True,
        serialize_by_alias=True,
    )

    fsrs_card_id: StrictInt = Field(alias="card_id")
    rating: Rating
    reviewed_at: datetime = Field(alias="review_datetime")
    review_duration: StrictInt | None = Field(default=None, ge=0)
    previous_interval_seconds: StrictFloat | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    scheduled_interval_seconds: StrictFloat | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    retrievability: StrictFloat | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    @field_validator("rating", mode="before")
    @classmethod
    def require_strict_rating(cls, value: object) -> object:
        if isinstance(value, (str, bool)):
            raise ValueError("rating must be an integer")
        return value

    @field_validator("reviewed_at", mode="before")
    @classmethod
    def require_datetime_value(cls, value: object) -> object:
        if isinstance(value, (bool, int, float)):
            raise ValueError("review_datetime must be a timestamp string")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def normalize_reviewed_at(cls, value: datetime) -> datetime:
        return datetime_as_utc(value)

    def as_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            separators=(",", ":"),
        )


class ReviewRecord(FrozenModel):
    """One immutable review event decoded and checked against its SQL mirrors."""

    review_id: int = Field(gt=0)
    card_key: CardKey
    rating: Rating
    reviewed_at: datetime
    previous_interval_seconds: float | None
    scheduled_interval_seconds: float | None
    retrievability: float | None


class Repository:
    """Own the schema and transactional persistence operations."""

    def __init__(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StorageError(
                f"could not prepare state database directory {path.parent}"
            ) from error
        self.path = path
        try:
            self.connection = sqlite3.connect(path)
        except sqlite3.Error as error:
            raise StorageError(f"could not open state database {path}") from error
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            self._initialize_schema()
        except sqlite3.Error as error:
            self.connection.close()
            raise StorageError("state database schema is corrupt") from error

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize_schema(self) -> None:
        current = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if current not in (0, _PREVIOUS_SCHEMA_VERSION, SCHEMA_VERSION):
            raise StorageError(
                f"unsupported state schema version {current}; move or delete the database "
                "and recreate state"
            )
        if current == 0:
            self.connection.executescript(
                """
                CREATE TABLE cards (
                    deck_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    target_kind TEXT NOT NULL CHECK (target_kind = 'entity'),
                    card_json TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (deck_id, entity_id)
                );
                CREATE INDEX cards_due_at_idx ON cards(due_at);

                CREATE TABLE deck_cards (
                    deck_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK (active IN (0, 1)),
                    suspended INTEGER NOT NULL DEFAULT 0 CHECK (suspended IN (0, 1)),
                    suspension_reason TEXT CHECK (
                        suspension_reason IS NULL OR (
                            length(suspension_reason) BETWEEN 1 AND 500
                            AND suspension_reason = trim(suspension_reason)
                        )
                    ),
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (deck_id, entity_id),
                    FOREIGN KEY (deck_id, entity_id)
                        REFERENCES cards(deck_id, entity_id)
                );
                CREATE INDEX deck_cards_active_idx ON deck_cards(deck_id, active);
                CREATE INDEX deck_cards_queue_idx
                    ON deck_cards(deck_id, active, suspended, entity_id);

                CREATE TABLE reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deck_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
                    reviewed_at TEXT NOT NULL,
                    review_json TEXT NOT NULL,
                    FOREIGN KEY (deck_id, entity_id)
                        REFERENCES cards(deck_id, entity_id)
                );
                CREATE INDEX reviews_card_idx ON reviews(deck_id, entity_id, reviewed_at);
                CREATE TABLE deck_settings (
                    deck_id TEXT PRIMARY KEY,
                    new_cards_per_day INTEGER NOT NULL DEFAULT 20 CHECK (
                        new_cards_per_day BETWEEN 0 AND 100000
                    ),
                    reviews_per_day INTEGER NOT NULL DEFAULT 200 CHECK (
                        reviews_per_day BETWEEN 0 AND 100000
                    ),
                    new_review_order TEXT NOT NULL DEFAULT 'reviews_first',
                    interday_learning_review_order TEXT NOT NULL DEFAULT 'learning_first',
                    new_card_gather_order TEXT NOT NULL DEFAULT 'deck',
                    new_card_sort_order TEXT NOT NULL DEFAULT 'order_gathered',
                    review_sort_order TEXT NOT NULL DEFAULT 'due_date'
                );
                PRAGMA user_version = 8;
                """
            )
            current = SCHEMA_VERSION
        elif current == _PREVIOUS_SCHEMA_VERSION:
            try:
                with self.connection:
                    self.connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS deck_settings (
                            deck_id TEXT PRIMARY KEY,
                            new_cards_per_day INTEGER NOT NULL DEFAULT 20 CHECK (
                                new_cards_per_day BETWEEN 0 AND 100000
                            ),
                            reviews_per_day INTEGER NOT NULL DEFAULT 200 CHECK (
                                reviews_per_day BETWEEN 0 AND 100000
                            ),
                            new_review_order TEXT NOT NULL DEFAULT 'reviews_first',
                            interday_learning_review_order TEXT NOT NULL DEFAULT 'learning_first',
                            new_card_gather_order TEXT NOT NULL DEFAULT 'deck',
                            new_card_sort_order TEXT NOT NULL DEFAULT 'order_gathered',
                            review_sort_order TEXT NOT NULL DEFAULT 'due_date'
                        )
                        """
                    )
                    self.connection.execute("PRAGMA user_version = 8")
            except sqlite3.Error as error:
                raise StorageError("state schema migration failed") from error
            current = SCHEMA_VERSION
        try:
            with self.connection:
                self.connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS reviews_deck_time_idx
                    ON reviews(deck_id, reviewed_at, id)
                    """
                )
                self.connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS deck_cards_queue_idx
                    ON deck_cards(deck_id, active, suspended, entity_id)
                    """
                )
                self.connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS deck_settings (
                        deck_id TEXT PRIMARY KEY,
                        new_cards_per_day INTEGER NOT NULL DEFAULT 20 CHECK (
                            new_cards_per_day BETWEEN 0 AND 100000
                        ),
                        reviews_per_day INTEGER NOT NULL DEFAULT 200 CHECK (
                            reviews_per_day BETWEEN 0 AND 100000
                        ),
                        new_review_order TEXT NOT NULL DEFAULT 'reviews_first',
                        interday_learning_review_order TEXT NOT NULL DEFAULT 'learning_first',
                        new_card_gather_order TEXT NOT NULL DEFAULT 'deck',
                        new_card_sort_order TEXT NOT NULL DEFAULT 'order_gathered',
                        review_sort_order TEXT NOT NULL DEFAULT 'due_date'
                    )
                    """
                )
                setting_columns = {
                    row["name"]
                    for row in self.connection.execute("PRAGMA table_info(deck_settings)")
                }
                missing_columns = (
                    ("new_cards_per_day", "INTEGER NOT NULL DEFAULT 20"),
                    ("reviews_per_day", "INTEGER NOT NULL DEFAULT 200"),
                    ("new_review_order", "TEXT NOT NULL DEFAULT 'reviews_first'"),
                    (
                        "interday_learning_review_order",
                        "TEXT NOT NULL DEFAULT 'learning_first'",
                    ),
                    ("new_card_gather_order", "TEXT NOT NULL DEFAULT 'deck'"),
                    ("new_card_sort_order", "TEXT NOT NULL DEFAULT 'order_gathered'"),
                    ("review_sort_order", "TEXT NOT NULL DEFAULT 'due_date'"),
                )
                for column, definition in missing_columns:
                    if column not in setting_columns:
                        self.connection.execute(
                            f"ALTER TABLE deck_settings ADD COLUMN {column} {definition}"
                        )
        except sqlite3.Error as error:
            raise StorageError("state schema is incomplete or corrupt") from error

    @staticmethod
    def _settings_values(settings: DeckSchedulingSettings) -> tuple[str, ...]:
        return (
            settings.new_review_order.value,
            settings.interday_learning_review_order.value,
            settings.new_card_gather_order.value,
            settings.new_card_sort_order.value,
            settings.review_sort_order.value,
        )

    @staticmethod
    def _settings_from_row(row: sqlite3.Row) -> DeckSchedulingSettings:
        try:
            return DeckSchedulingSettings(
                new_review_order=row["new_review_order"],
                interday_learning_review_order=row["interday_learning_review_order"],
                new_card_gather_order=row["new_card_gather_order"],
                new_card_sort_order=row["new_card_sort_order"],
                review_sort_order=row["review_sort_order"],
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("stored deck scheduling settings are invalid") from error

    def deck_settings(
        self,
        deck_name: str,
        defaults: DeckSchedulingSettings | None = None,
    ) -> DeckSchedulingSettings:
        """Return persisted settings or the validated deck-file defaults."""

        row = self.connection.execute(
            """
            SELECT deck_id, new_review_order, interday_learning_review_order,
                   new_card_gather_order, new_card_sort_order, review_sort_order
            FROM deck_settings
            WHERE deck_id = ?
            """,
            (deck_name,),
        ).fetchone()
        if row is None:
            return defaults or DeckSchedulingSettings()
        return self._settings_from_row(row)

    def get_deck_settings(
        self,
        deck_name: str,
        defaults: DeckSchedulingSettings | None = None,
    ) -> DeckSchedulingSettings:
        """Alias for the explicit read operation used by service callers."""

        return self.deck_settings(deck_name, defaults)

    @staticmethod
    def _daily_limits_from_row(row: sqlite3.Row) -> DailyLimits:
        try:
            return DailyLimits(
                new_cards_per_day=row["new_cards_per_day"],
                reviews_per_day=row["reviews_per_day"],
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("stored daily limit settings are invalid") from error

    def daily_limits(self, deck_name: str, defaults: DailyLimits | None = None) -> DailyLimits:
        """Return persisted daily limits or validated deck-file defaults."""

        try:
            fallback = DailyLimits.model_validate(defaults or DailyLimits())
            row = self.connection.execute(
                """
                SELECT new_cards_per_day, reviews_per_day
                FROM deck_settings
                WHERE deck_id = ?
                """,
                (deck_name,),
            ).fetchone()
        except (sqlite3.Error, TypeError, ValueError, ValidationError) as error:
            raise StorageError("could not read daily limit settings") from error
        return fallback if row is None else self._daily_limits_from_row(row)

    def set_daily_limits(self, deck_name: str, limits: DailyLimits) -> DailyLimits:
        """Persist validated daily limits for one deck."""

        try:
            validated = DailyLimits.model_validate(limits)
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("daily limit settings are invalid") from error
        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO deck_settings (deck_id, new_cards_per_day, reviews_per_day)
                    VALUES (?, ?, ?)
                    ON CONFLICT(deck_id) DO UPDATE SET
                        new_cards_per_day = excluded.new_cards_per_day,
                        reviews_per_day = excluded.reviews_per_day
                    """,
                    (deck_name, validated.new_cards_per_day, validated.reviews_per_day),
                )
        except sqlite3.Error as error:
            raise StorageError("could not save daily limit settings") from error
        return validated

    def set_deck_settings(
        self,
        deck_name: str,
        settings: DeckSchedulingSettings,
    ) -> DeckSchedulingSettings:
        """Persist one complete, validated deck setting record."""

        try:
            validated = (
                settings
                if isinstance(settings, DeckSchedulingSettings)
                else DeckSchedulingSettings.model_validate(settings)
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("deck scheduling settings are invalid") from error
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO deck_settings (
                    deck_id, new_review_order, interday_learning_review_order,
                    new_card_gather_order, new_card_sort_order, review_sort_order
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(deck_id) DO UPDATE SET
                    new_review_order = excluded.new_review_order,
                    interday_learning_review_order = excluded.interday_learning_review_order,
                    new_card_gather_order = excluded.new_card_gather_order,
                    new_card_sort_order = excluded.new_card_sort_order,
                    review_sort_order = excluded.review_sort_order
                """,
                (deck_name, *self._settings_values(validated)),
            )
        return validated

    def _ensure_deck_settings(
        self,
        deck_name: str,
        defaults: DeckSchedulingSettings,
        daily_defaults: DailyLimits | None = None,
    ) -> None:
        try:
            validated_daily = DailyLimits.model_validate(daily_defaults or DailyLimits())
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("daily limit defaults are invalid") from error
        row = self.connection.execute(
            "SELECT * FROM deck_settings WHERE deck_id = ?",
            (deck_name,),
        ).fetchone()
        if row is not None:
            self._settings_from_row(row)
            self._daily_limits_from_row(row)
            return
        self.connection.execute(
            """
            INSERT INTO deck_settings (
                deck_id, new_cards_per_day, reviews_per_day,
                new_review_order, interday_learning_review_order,
                new_card_gather_order, new_card_sort_order, review_sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deck_name,
                validated_daily.new_cards_per_day,
                validated_daily.reviews_per_day,
                *self._settings_values(defaults),
            ),
        )

    def sync_deck(
        self,
        deck_name: str,
        cards: dict[str, SemanticCard],
        now: datetime,
        scheduling: DeckSchedulingSettings | None = None,
        daily_limits: DailyLimits | None = None,
    ) -> tuple[int, int]:
        """Atomically reconcile one deck while preserving global card schedules."""

        now = datetime_as_utc(now)
        timestamp = datetime_to_text(now)
        created = 0
        with self.connection:
            if scheduling is not None:
                self._ensure_deck_settings(deck_name, scheduling, daily_limits)
            # Membership is rebuilt for this deck only. The cards table is deliberately
            # untouched here so removed cards retain their FSRS state and review history.
            self.connection.execute(
                "UPDATE deck_cards SET active = 0 WHERE deck_id = ?", (deck_name,)
            )
            for entity_id, semantic_card in cards.items():
                card_key = semantic_card.card_key
                if entity_id != card_key.entity_id:
                    raise StorageError(f"card key {entity_id} does not match its entity identity")
                if card_key.deck_id != deck_name:
                    raise StorageError(
                        f"card key {entity_id} does not belong to deck {deck_name!r}"
                    )
                existing = self.connection.execute(
                    """
                    SELECT deck_id, entity_id, target_kind, card_json, due_at
                    FROM cards WHERE deck_id = ? AND entity_id = ?
                    """,
                    (deck_name, entity_id),
                ).fetchone()
                if existing is None:
                    card = Card(due=now)
                    self.connection.execute(
                        """
                        INSERT INTO cards (
                            deck_id, entity_id, target_kind, card_json, due_at,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            deck_name,
                            entity_id,
                            "entity",
                            card.to_json(),
                            datetime_to_text(card.due),
                            timestamp,
                            timestamp,
                        ),
                    )
                    created += 1
                else:
                    stored = self._stored_card(existing)
                    if stored.card_key != card_key:
                        raise StorageError(
                            f"stored identity for {deck_name}/{entity_id} does not match "
                            "generated exercises"
                        )
                self.connection.execute(
                    """
                    INSERT INTO deck_cards (deck_id, entity_id, active, last_seen_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(deck_id, entity_id) DO UPDATE SET
                        active = 1,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (deck_name, entity_id, timestamp),
                )
        return len(cards), created

    def suspend_card(self, deck_name: str, entity_id: str, reason: str | None = None) -> None:
        """Suspend one known deck membership without changing its global schedule."""

        try:
            update = SuspensionUpdate(reason=reason)
        except ValidationError as error:
            raise StorageError(validation_message(error)) from error
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE deck_cards
                SET suspended = 1, suspension_reason = ?
                WHERE deck_id = ? AND entity_id = ? AND active = 1
                """,
                (update.reason, deck_name, entity_id),
            )
            if cursor.rowcount != 1:
                raise StorageError(
                    f"entity {entity_id} is not a known member of deck {deck_name!r}"
                )

    def resume_card(self, deck_name: str, entity_id: str) -> None:
        """Resume one known deck membership and clear its current reason."""

        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE deck_cards
                SET suspended = 0, suspension_reason = NULL
                WHERE deck_id = ? AND entity_id = ? AND active = 1
                """,
                (deck_name, entity_id),
            )
            if cursor.rowcount != 1:
                raise StorageError(
                    f"entity {entity_id} is not a known member of deck {deck_name!r}"
                )

    def suspend_cards(
        self,
        deck_name: str,
        entity_ids: tuple[str, ...],
        reason: str | None = None,
    ) -> None:
        """Suspend several active memberships atomically."""

        try:
            update = SuspensionUpdate(reason=reason)
        except ValidationError as error:
            raise StorageError(validation_message(error)) from error
        self._update_memberships(deck_name, entity_ids, suspended=True, reason=update.reason)

    def resume_cards(self, deck_name: str, entity_ids: tuple[str, ...]) -> None:
        """Resume several active memberships atomically."""

        self._update_memberships(deck_name, entity_ids, suspended=False, reason=None)

    def _update_memberships(
        self,
        deck_name: str,
        entity_ids: tuple[str, ...],
        *,
        suspended: bool,
        reason: str | None,
    ) -> None:
        if not entity_ids or len(entity_ids) != len(set(entity_ids)):
            raise StorageError("card selection must contain unique entities")
        placeholders = ", ".join("?" for _ in entity_ids)
        with self.connection:
            rows = self.connection.execute(
                f"""
                SELECT entity_id
                FROM deck_cards
                WHERE deck_id = ? AND active = 1 AND entity_id IN ({placeholders})
                """,
                (deck_name, *entity_ids),
            ).fetchall()
            if {row["entity_id"] for row in rows} != set(entity_ids):
                raise StorageError("one or more selected cards is no longer active")
            if suspended:
                cursor = self.connection.execute(
                    f"""
                    UPDATE deck_cards
                    SET suspended = 1, suspension_reason = ?
                    WHERE deck_id = ? AND active = 1 AND entity_id IN ({placeholders})
                    """,
                    (reason, deck_name, *entity_ids),
                )
            else:
                cursor = self.connection.execute(
                    f"""
                    UPDATE deck_cards
                    SET suspended = 0, suspension_reason = NULL
                    WHERE deck_id = ? AND active = 1 AND entity_id IN ({placeholders})
                    """,
                    (deck_name, *entity_ids),
                )
            if cursor.rowcount != len(entity_ids):
                raise StorageError("card selection changed during the update")

    @staticmethod
    def _membership_state(
        active: object,
        suspended: object,
        reason: object,
    ) -> tuple[bool, bool, str | None]:
        if type(active) is not int or active not in (0, 1):
            raise StorageError("stored deck membership has an invalid active state")
        if type(suspended) is not int or suspended not in (0, 1):
            raise StorageError("stored deck membership has an invalid suspension state")
        if reason is not None and (
            not isinstance(reason, str)
            or not reason
            or len(reason) > MAX_SUSPENSION_REASON_LENGTH
            or reason != reason.strip()
            or any(
                unicodedata.category(character) in _UNSAFE_REASON_CATEGORIES for character in reason
            )
        ):
            raise StorageError("stored deck membership has an invalid suspension reason")
        if not suspended and reason is not None:
            raise StorageError("stored resumed deck membership still has a suspension reason")
        return bool(active), bool(suspended), reason

    def card_available(self, deck_name: str, entity_id: str) -> bool:
        """Return whether a known membership may currently enter a study queue."""

        state = self._card_membership_state(deck_name, entity_id)
        if state is None:
            return False
        active, suspended, _reason = state
        return active and not suspended

    def card_suspended(self, deck_name: str, entity_id: str) -> bool:
        """Return whether a current membership is suspended."""

        state = self._card_membership_state(deck_name, entity_id)
        if state is None:
            return False
        active, suspended, _reason = state
        return active and suspended

    def has_membership(self, deck_name: str, entity_id: str) -> bool:
        return self._card_membership_state(deck_name, entity_id) is not None

    def _card_membership_state(
        self,
        deck_name: str,
        entity_id: str,
    ) -> tuple[bool, bool, str | None] | None:
        row = self.connection.execute(
            """
            SELECT active, suspended, suspension_reason
            FROM deck_cards
            WHERE deck_id = ? AND entity_id = ?
            """,
            (deck_name, entity_id),
        ).fetchone()
        if row is None:
            return None
        return self._membership_state(
            row["active"],
            row["suspended"],
            row["suspension_reason"],
        )

    def due_cards(self, deck_name: str, now: datetime, limit: int | None) -> list[StoredCard]:
        self._validate_active_due_mirrors(deck_name)
        parameters: list[object] = [deck_name, datetime_to_text(now)]
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            parameters.append(limit)
        rows = self.connection.execute(
            """
            SELECT c.deck_id, c.entity_id, c.target_kind, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.deck_id = c.deck_id AND dc.entity_id = c.entity_id
            WHERE dc.deck_id = ? AND dc.active = 1 AND dc.suspended = 0
              AND c.due_at <= ?
            ORDER BY c.due_at, c.entity_id
            """
            + limit_sql,
            parameters,
        ).fetchall()
        return [self._stored_card(row) for row in rows]

    def active_cards(self, deck_name: str) -> list[StoredCard]:
        """Return every available deck member in schedule order."""

        self._validate_active_memberships(deck_name)
        rows = self.connection.execute(
            """
            SELECT c.deck_id, c.entity_id, c.target_kind, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.deck_id = c.deck_id AND dc.entity_id = c.entity_id
            WHERE dc.deck_id = ? AND dc.active = 1 AND dc.suspended = 0
            ORDER BY c.due_at, c.entity_id
            """,
            (deck_name,),
        ).fetchall()
        return [self._stored_card(row) for row in rows]

    def _queue_records(
        self,
        deck_name: str,
    ) -> list[tuple[StoredCard, QueueKind]]:
        """Read and validate active, unsuspended cards with their queue kinds."""

        self._validate_active_memberships(deck_name)
        self._validate_review_logs(deck_name)
        rows = self.connection.execute(
            """
            SELECT
                c.deck_id,
                c.entity_id,
                c.target_kind,
                c.card_json,
                c.due_at,
                (
                    SELECT COUNT(*)
                    FROM reviews AS r
                    WHERE r.deck_id = c.deck_id AND r.entity_id = c.entity_id
                ) AS review_count
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.deck_id = c.deck_id AND dc.entity_id = c.entity_id
            WHERE dc.deck_id = ? AND dc.active = 1 AND dc.suspended = 0
            """,
            (deck_name,),
        ).fetchall()
        records: list[tuple[StoredCard, QueueKind]] = []
        for row in rows:
            stored = self._stored_card(row)
            queue = classify_card(stored.card(), _strict_count(row["review_count"], "review"))
            records.append((stored, queue))
        records.sort(
            key=lambda item: (datetime_as_utc(item[0].card().due), item[0].card_key.entity_id)
        )
        return records

    def queue_cards(
        self,
        deck_name: str,
        now: datetime,
        queue: QueueKind | str | None = None,
        *,
        due_only: bool = True,
    ) -> list[StoredCard]:
        """Return validated cards grouped in the default queue order."""

        current = datetime_as_utc(now)
        queue_kind = None if queue is None else QueueKind(queue)
        queue_priority = {
            QueueKind.LEARNING: 0,
            QueueKind.RELEARNING: 1,
            QueueKind.REVIEW: 2,
            QueueKind.NEW: 3,
        }
        records = [
            (card, card_queue)
            for card, card_queue in self._queue_records(deck_name)
            if (queue_kind is None or card_queue is queue_kind)
            and (not due_only or datetime_as_utc(card.card().due) <= current)
        ]
        records.sort(
            key=lambda item: (
                queue_priority[item[1]],
                datetime_as_utc(item[0].card().due),
                item[0].card_key.entity_id,
            )
        )
        return [card for card, _queue in records]

    def queue_counts(
        self,
        deck_name: str,
        now: datetime,
        *,
        due_only: bool = True,
    ) -> QueueCounts:
        """Count active, unsuspended cards in each queue."""

        current = datetime_as_utc(now)
        counts = {queue: 0 for queue in QueueKind}
        for card, queue in self._queue_records(deck_name):
            if not due_only or datetime_as_utc(card.card().due) <= current:
                counts[queue] += 1
        return QueueCounts.from_counts(counts)

    def queue_kind(self, card_key: CardKey) -> QueueKind:
        """Return the current queue for one active stored card."""

        for stored, queue in self._queue_records(card_key.deck_id):
            if stored.card_key == card_key:
                return queue
        raise StorageError(
            f"card {card_key.entity_id!r} is not an active member of deck {card_key.deck_id!r}"
        )

    def daily_usage(
        self,
        deck_name: str,
        now: datetime,
        timezone: ZoneInfo,
        limits: DailyLimits,
    ) -> DailyUsage:
        """Count durable review events in the current configured local day."""

        try:
            local_date, start, end = local_day_bounds(now, timezone)
            validated_limits = DailyLimits.model_validate(limits)
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("daily usage settings are invalid") from error
        self._validate_active_due_mirrors(deck_name)
        self._validate_review_logs(deck_name)
        new_used, reviews_used = self._daily_usage_counts(
            deck_name,
            datetime_to_text(start),
            datetime_to_text(end),
        )
        return DailyUsage(
            local_date=local_date,
            limits=validated_limits,
            new_used=new_used,
            reviews_used=reviews_used,
        )

    def _daily_usage_counts(
        self,
        deck_name: str,
        start: str,
        end: str,
    ) -> tuple[int, int]:
        reviews_row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM reviews
            WHERE deck_id = ? AND reviewed_at >= ? AND reviewed_at < ?
            """,
            (deck_name, start, end),
        ).fetchone()
        new_row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM reviews AS first_review
            WHERE first_review.deck_id = ?
              AND first_review.reviewed_at >= ?
              AND first_review.reviewed_at < ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM reviews AS earlier_review
                  WHERE earlier_review.deck_id = first_review.deck_id
                    AND earlier_review.entity_id = first_review.entity_id
                    AND (
                        earlier_review.reviewed_at < first_review.reviewed_at
                        OR (
                            earlier_review.reviewed_at = first_review.reviewed_at
                            AND earlier_review.id < first_review.id
                        )
                    )
              )
            """,
            (deck_name, start, end),
        ).fetchone()
        return (
            _strict_count(new_row["count"], "new-card usage"),
            _strict_count(reviews_row["count"], "review usage"),
        )

    def forgotten_cards(
        self,
        deck_name: str,
        since: datetime,
        limit: int | None,
    ) -> list[StoredCard]:
        """Return available cards failed since a timestamp, newest failure first."""

        # Validate every active identity and due mirror before the review predicate can
        # silently omit a corrupt card that has no matching Again review.
        self.active_cards(deck_name)
        self._validate_review_logs(deck_name)
        parameters: list[object] = [deck_name, datetime_to_text(since)]
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            parameters.append(limit)
        rows = self.connection.execute(
            """
            SELECT c.deck_id, c.entity_id, c.target_kind, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.deck_id = c.deck_id AND dc.entity_id = c.entity_id
            WHERE dc.deck_id = ? AND dc.active = 1 AND dc.suspended = 0 AND EXISTS (
                SELECT 1
                FROM reviews AS r
                WHERE r.deck_id = c.deck_id AND r.entity_id = c.entity_id
                  AND r.rating = 1 AND r.reviewed_at >= ?
            )
            ORDER BY (
                SELECT MAX(r.reviewed_at)
                FROM reviews AS r
                WHERE r.deck_id = c.deck_id AND r.entity_id = c.entity_id AND r.rating = 1
            ) DESC, c.entity_id
            """
            + limit_sql,
            parameters,
        ).fetchall()
        return [self._stored_card(row) for row in rows]

    def future_cards(
        self,
        deck_name: str,
        after: datetime,
        through: datetime,
        limit: int | None,
    ) -> list[StoredCard]:
        """Return available cards due after now through an inclusive horizon."""

        self._validate_active_due_mirrors(deck_name)
        parameters: list[object] = [
            deck_name,
            datetime_to_text(after),
            datetime_to_text(through),
        ]
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            parameters.append(limit)
        rows = self.connection.execute(
            """
            SELECT c.deck_id, c.entity_id, c.target_kind, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.deck_id = c.deck_id AND dc.entity_id = c.entity_id
            WHERE dc.deck_id = ? AND dc.active = 1 AND dc.suspended = 0
              AND c.due_at > ? AND c.due_at <= ?
            ORDER BY c.due_at, c.entity_id
            """
            + limit_sql,
            parameters,
        ).fetchall()
        return [self._stored_card(row) for row in rows]

    def get_card(self, card_key: CardKey) -> StoredCard | None:
        row = self.connection.execute(
            """
            SELECT deck_id, entity_id, target_kind, card_json, due_at
            FROM cards WHERE deck_id = ? AND entity_id = ?
            """,
            (card_key.deck_id, card_key.entity_id),
        ).fetchone()
        return self._stored_card(row) if row is not None else None

    def _stored_card(self, row: sqlite3.Row) -> StoredCard:
        if row["target_kind"] != "entity":
            raise StorageError("stored card has an invalid exercise kind")
        try:
            card_key = CardKey.exercise(row["deck_id"], row["entity_id"])
        except (TypeError, ValidationError) as error:
            raise StorageError("stored card identity is invalid") from error
        card_json = row["card_json"]
        if not isinstance(card_json, str):
            raise StorageError("stored card schedule is not JSON text")
        stored = StoredCard(
            card_key=card_key,
            card_json=card_json,
        )
        mirrored_due = _datetime_from_text(row["due_at"])
        if mirrored_due != datetime_as_utc(stored.card().due):
            raise StorageError("stored card due timestamp does not match its schedule")
        return stored

    def _validate_active_due_mirrors(self, deck_name: str) -> None:
        """Validate all active mirrors before an indexed filter can omit corruption."""

        self._validate_active_memberships(deck_name)

    def _validate_active_memberships(self, deck_name: str) -> None:
        """Validate availability state before indexed predicates can omit corruption."""

        rows = self.connection.execute(
            """
            SELECT active, suspended, suspension_reason
            FROM deck_cards
            WHERE deck_id = ? AND active = 1
            """,
            (deck_name,),
        ).fetchall()
        for row in rows:
            self._membership_state(
                row["active"],
                row["suspended"],
                row["suspension_reason"],
            )
        self._validate_all_active_card_mirrors(deck_name)

    def _validate_all_active_card_mirrors(self, deck_name: str) -> None:
        missing = self.connection.execute(
            """
            SELECT dc.deck_id, dc.entity_id
            FROM deck_cards AS dc
            LEFT JOIN cards AS c
                ON c.deck_id = dc.deck_id AND c.entity_id = dc.entity_id
            WHERE dc.deck_id = ? AND dc.active = 1 AND c.deck_id IS NULL
            """,
            (deck_name,),
        ).fetchone()
        if missing is not None:
            raise StorageError("active deck membership has no matching stored card")
        rows = self.connection.execute(
            """
            SELECT c.deck_id, c.entity_id, c.target_kind, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.deck_id = c.deck_id AND dc.entity_id = c.entity_id
            WHERE dc.deck_id = ? AND dc.active = 1
            """,
            (deck_name,),
        ).fetchall()
        for row in rows:
            self._stored_card(row)

    def save_review(
        self,
        card_key: CardKey,
        source_card_json: str,
        card: Card,
        review_log: ReviewLog,
        *,
        previous_interval_seconds: float | None,
        retrievability: float | None,
        daily_limits: DailyLimits | None = None,
        timezone: ZoneInfo | None = None,
    ) -> str:
        """Persist updated FSRS state and its review log in one transaction."""

        # Validate the persisted fields before the indexed write predicate can
        # misclassify a corrupt membership as reviewable.
        deck_name = card_key.deck_id
        entity_id = card_key.entity_id
        self._card_membership_state(deck_name, entity_id)
        reviewed_at = datetime_to_text(review_log.review_datetime)
        card_json = card.to_json()
        usage_bounds: tuple[str, str] | None = None
        validated_limits: DailyLimits | None = None
        if daily_limits is not None:
            if timezone is None:
                raise StorageError("daily usage timezone is required")
            try:
                validated_limits = DailyLimits.model_validate(daily_limits)
                _local_date, start, end = local_day_bounds(review_log.review_datetime, timezone)
            except (TypeError, ValueError, ValidationError) as error:
                raise StorageError("daily usage settings are invalid") from error
            self._validate_review_logs(deck_name)
            usage_bounds = (datetime_to_text(start), datetime_to_text(end))
        try:
            payload = ReviewPayload(
                fsrs_card_id=review_log.card_id,
                rating=review_log.rating,
                reviewed_at=review_log.review_datetime,
                review_duration=review_log.review_duration,
                previous_interval_seconds=previous_interval_seconds,
                scheduled_interval_seconds=(
                    datetime_as_utc(card.due) - datetime_as_utc(review_log.review_datetime)
                ).total_seconds(),
                retrievability=retrievability,
            )
        except ValidationError as error:
            raise StorageError("review analytics metadata is invalid") from error
        with self.connection:
            if validated_limits is not None and usage_bounds is not None:
                new_used, reviews_used = self._daily_usage_counts(
                    deck_name,
                    usage_bounds[0],
                    usage_bounds[1],
                )
                if reviews_used >= validated_limits.reviews_per_day:
                    raise DailyLimitError("reviews", 0)
                first_review = self.connection.execute(
                    """
                    SELECT 1
                    FROM reviews
                    WHERE deck_id = ? AND entity_id = ?
                    LIMIT 1
                    """,
                    (deck_name, entity_id),
                ).fetchone()
                if first_review is None and new_used >= validated_limits.new_cards_per_day:
                    raise DailyLimitError("new", 0)
            cursor = self.connection.execute(
                """
                UPDATE cards SET card_json = ?, due_at = ?, updated_at = ?
                WHERE deck_id = ? AND entity_id = ? AND card_json = ? AND EXISTS (
                    SELECT 1
                    FROM deck_cards AS dc
                    WHERE dc.deck_id = cards.deck_id AND dc.entity_id = cards.entity_id
                      AND dc.deck_id = ? AND dc.entity_id = ?
                      AND dc.active = 1 AND dc.suspended = 0
                )
                """,
                (
                    card_json,
                    datetime_to_text(card.due),
                    reviewed_at,
                    deck_name,
                    entity_id,
                    source_card_json,
                    deck_name,
                    entity_id,
                ),
            )
            if cursor.rowcount != 1:
                exists = self.connection.execute(
                    "SELECT 1 FROM cards WHERE deck_id = ? AND entity_id = ?",
                    (deck_name, entity_id),
                ).fetchone()
                if exists is None:
                    raise StaleReviewError(
                        f"cannot review missing card {deck_name}/{entity_id}; reload or sync "
                        "before trying again"
                    )
                if not self.card_available(deck_name, entity_id):
                    raise StorageError(
                        f"cannot review unavailable entity {entity_id} in deck {deck_name!r}"
                    )
                raise StaleReviewError(
                    f"cannot review stale card snapshot {deck_name}/{entity_id}; reload the card "
                    "and try again"
                )
            self.connection.execute(
                """
                INSERT INTO reviews (deck_id, entity_id, rating, reviewed_at, review_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    deck_name,
                    entity_id,
                    review_log.rating.value,
                    reviewed_at,
                    payload.as_json(),
                ),
            )
        return card_json

    @staticmethod
    def _review_record(row: sqlite3.Row) -> ReviewRecord:
        review_json = row["review_json"]
        if not isinstance(review_json, str):
            raise StorageError("stored review log is not JSON text")
        try:
            payload_data = json.loads(review_json, object_pairs_hook=_unique_json_object)
            payload = ReviewPayload.model_validate(payload_data)
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as error:
            raise StorageError("stored review log is invalid") from error
        reviewed_at = _datetime_from_text(row["reviewed_at"])
        try:
            rating = Rating(row["rating"])
        except (TypeError, ValueError) as error:
            raise StorageError("stored review has an invalid rating") from error
        if payload.reviewed_at != reviewed_at or payload.rating is not rating:
            raise StorageError("stored review log does not match its indexed fields")
        try:
            card_key = CardKey.exercise(row["deck_id"], row["entity_id"])
            return ReviewRecord(
                review_id=row["id"],
                card_key=card_key,
                rating=rating,
                reviewed_at=reviewed_at,
                previous_interval_seconds=payload.previous_interval_seconds,
                scheduled_interval_seconds=payload.scheduled_interval_seconds,
                retrievability=payload.retrievability,
            )
        except ValidationError as error:
            raise StorageError("stored review record is invalid") from error

    def review_history(self, deck_name: str, through: datetime) -> tuple[ReviewRecord, ...]:
        """Return immutable deck review events through a UTC instant."""

        rows = self.connection.execute(
            """
            SELECT id, deck_id, entity_id, rating, reviewed_at, review_json
            FROM reviews
            WHERE deck_id = ? AND reviewed_at <= ?
            ORDER BY reviewed_at, id
            """,
            (deck_name, datetime_to_text(through)),
        ).fetchall()
        records: list[ReviewRecord] = []
        for row in rows:
            self._validate_review_membership(row["deck_id"], row["entity_id"])
            records.append(self._review_record(row))
        return tuple(records)

    def status(
        self,
        deck_name: str,
        now: datetime,
        scheduling: DeckSchedulingSettings | None = None,
    ) -> DeckStatus:
        """Return deck totals and the settings used for queue planning."""

        self._validate_active_due_mirrors(deck_name)
        self._validate_review_logs(deck_name)
        timestamp = datetime_to_text(now)
        settings = self.deck_settings(deck_name, scheduling)
        row = self.connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN dc.suspended = 0 THEN 1 ELSE 0 END), 0)
                    AS available,
                COALESCE(SUM(CASE WHEN dc.suspended = 1 THEN 1 ELSE 0 END), 0)
                    AS suspended,
                COALESCE(SUM(CASE WHEN dc.suspended = 0 AND NOT EXISTS (
                    SELECT 1 FROM reviews AS r
                    WHERE r.deck_id = c.deck_id AND r.entity_id = c.entity_id
                ) THEN 1 ELSE 0 END), 0) AS new,
                COALESCE(SUM(CASE WHEN dc.suspended = 0 AND c.due_at <= ?
                    THEN 1 ELSE 0 END), 0) AS due,
                COALESCE(SUM(CASE WHEN dc.suspended = 0 AND c.due_at > ?
                    THEN 1 ELSE 0 END), 0) AS future
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.deck_id = c.deck_id AND dc.entity_id = c.entity_id
            WHERE dc.deck_id = ? AND dc.active = 1
            """,
            (timestamp, timestamp, deck_name),
        ).fetchone()
        return DeckStatus(
            available=_strict_count(row["available"], "available"),
            suspended=_strict_count(row["suspended"], "suspended"),
            new=_strict_count(row["new"], "new"),
            due=_strict_count(row["due"], "due"),
            future=_strict_count(row["future"], "future"),
            queue_counts=self.queue_counts(deck_name, now),
            queue_order=queue_order(settings),
            scheduling=settings,
        )

    def queue_status(
        self,
        deck_name: str,
        now: datetime,
        scheduling: DeckSchedulingSettings | ZoneInfo | None = None,
        timezone: ZoneInfo | DailyLimits | None = None,
        limits: DailyLimits | None = None,
    ) -> DeckQueueStatus:
        """Return queue status with daily limits for CLI and web callers.

        The positional ``timezone, limits`` form remains accepted for the CLI
        and older controller call sites while the scheduling settings stay
        available through the regular deck status response.
        """

        actual_scheduling: DeckSchedulingSettings | None
        actual_timezone: ZoneInfo
        actual_limits: DailyLimits
        if isinstance(scheduling, ZoneInfo):
            actual_scheduling = None
            actual_timezone = scheduling
            actual_limits = (
                timezone if isinstance(timezone, DailyLimits) else limits or DailyLimits()
            )
        else:
            actual_scheduling = scheduling
            actual_timezone = timezone if isinstance(timezone, ZoneInfo) else ZoneInfo("UTC")
            actual_limits = limits or self.daily_limits(deck_name)
        base = self.status(deck_name, now, actual_scheduling)
        queue_counts = self.queue_counts(deck_name, now)
        daily = self.daily_usage(deck_name, now, actual_timezone, actual_limits)
        capacities = queue_selection_capacities(queue_counts, daily)
        hidden_values = {
            queue: max(0, queue_counts.for_queue(queue) - capacities.for_queue(queue))
            for queue in QueueKind
        }
        return DeckQueueStatus(
            available=base.available,
            suspended=base.suspended,
            new=base.new,
            due=base.due,
            future=base.future,
            queue_counts=queue_counts,
            queue_order=base.queue_order,
            scheduling=base.scheduling,
            hidden_counts=QueueCounts.from_counts(hidden_values),
            daily_usage=daily,
        )

    def card_statuses(self, deck_name: str) -> tuple[CardStatus, ...]:
        """Return active deck members in the same due-time order used for study."""

        self._validate_active_memberships(deck_name)
        self._validate_review_logs(deck_name)
        rows = self.connection.execute(
            """
            SELECT
                c.deck_id,
                c.entity_id,
                c.target_kind,
                c.card_json,
                c.due_at,
                dc.active,
                dc.suspended,
                dc.suspension_reason,
                (
                    SELECT COUNT(*)
                    FROM reviews AS r
                    WHERE r.deck_id = c.deck_id AND r.entity_id = c.entity_id
                ) AS review_count,
                (
                    SELECT r.reviewed_at
                    FROM reviews AS r
                    WHERE r.deck_id = c.deck_id AND r.entity_id = c.entity_id
                    ORDER BY r.reviewed_at DESC, r.id DESC
                    LIMIT 1
                ) AS last_review_at,
                (
                    SELECT r.rating
                    FROM reviews AS r
                    WHERE r.deck_id = c.deck_id AND r.entity_id = c.entity_id
                    ORDER BY r.reviewed_at DESC, r.id DESC
                    LIMIT 1
                ) AS last_rating
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.deck_id = c.deck_id AND dc.entity_id = c.entity_id
            WHERE dc.deck_id = ? AND dc.active = 1
            ORDER BY c.due_at, c.entity_id
            """,
            (deck_name,),
        ).fetchall()
        statuses: list[CardStatus] = []
        for row in rows:
            stored = self._stored_card(row)
            _active, suspended, suspension_reason = self._membership_state(
                row["active"],
                row["suspended"],
                row["suspension_reason"],
            )
            card = stored.card()
            history_last_review = (
                _datetime_from_text(row["last_review_at"])
                if row["last_review_at"] is not None
                else None
            )
            card_last_review = (
                datetime_as_utc(card.last_review) if card.last_review is not None else None
            )
            last_rating_value = row["last_rating"]
            if history_last_review != card_last_review or (history_last_review is None) != (
                last_rating_value is None
            ):
                raise StorageError("stored card schedule and review history do not match")
            try:
                last_rating = Rating(last_rating_value) if last_rating_value is not None else None
            except ValueError as error:
                raise StorageError("stored review has an invalid rating") from error
            statuses.append(
                CardStatus(
                    card_key=stored.card_key,
                    card_json=stored.card_json,
                    fsrs_state=card.state.name.lower(),
                    fsrs_step=card.step,
                    stability=card.stability,
                    difficulty=card.difficulty,
                    review_count=row["review_count"],
                    due_at=datetime_as_utc(card.due),
                    last_review_at=history_last_review,
                    last_rating=last_rating,
                    suspended=suspended,
                    suspension_reason=suspension_reason,
                    queue=classify_card(card, _strict_count(row["review_count"], "review")),
                )
            )
        return tuple(statuses)

    def _validate_review_logs(self, deck_name: str) -> None:
        rows = self.connection.execute(
            """
            SELECT id, deck_id, entity_id, rating, reviewed_at, review_json
            FROM reviews
            WHERE deck_id = ?
            """,
            (deck_name,),
        ).fetchall()
        for row in rows:
            self._validate_review_membership(row["deck_id"], row["entity_id"])
            self._review_record(row)

    def _validate_review_membership(self, deck_name: object, entity_id: object) -> None:
        if not isinstance(deck_name, str) or not isinstance(entity_id, str):
            raise StorageError("stored review has invalid deck or card identity")
        exists = self.connection.execute(
            "SELECT 1 FROM deck_cards WHERE deck_id = ? AND entity_id = ?",
            (deck_name, entity_id),
        ).fetchone()
        if exists is None:
            raise StorageError("stored review has no matching deck membership")
