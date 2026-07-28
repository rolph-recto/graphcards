"""SQLite persistence for global FSRS cards, deck membership, and reviews."""

from __future__ import annotations

import json
import math
import sqlite3
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from fsrs import Card, Rating, ReviewLog
from pydantic import ConfigDict, Field, StrictFloat, StrictInt, ValidationError, field_validator

from graphcards.errors import StaleReviewError, StorageError
from graphcards.models import Card as SemanticCard
from graphcards.models import CardKey, FrozenModel, validation_message

SCHEMA_VERSION = 5
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


class StoredCard(FrozenModel):
    card_id: str
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
    available: int
    suspended: int
    new: int
    due: int
    future: int


class CardStatus(FrozenModel):
    """Card-level schedule details used by the full status view."""

    card_id: str
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

    def stored_card(self) -> StoredCard:
        """Rebuild the complete stored card used for read-only FSRS calculations."""

        return StoredCard(
            card_id=self.card_id,
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
    card_id: str = Field(min_length=1)
    deck_name: str = Field(min_length=1)
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
        if current not in (0, SCHEMA_VERSION):
            raise StorageError(
                f"unsupported state schema version {current}; move or delete the database "
                "and recreate state"
            )
        if current == 0:
            self.connection.executescript(
                """
                CREATE TABLE cards (
                    card_id TEXT PRIMARY KEY,
                    target_kind TEXT NOT NULL CHECK (target_kind = 'entity'),
                    identity_json TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX cards_due_at_idx ON cards(due_at);

                CREATE TABLE deck_cards (
                    deck_name TEXT NOT NULL,
                    card_id TEXT NOT NULL REFERENCES cards(card_id),
                    active INTEGER NOT NULL CHECK (active IN (0, 1)),
                    suspended INTEGER NOT NULL DEFAULT 0 CHECK (suspended IN (0, 1)),
                    suspension_reason TEXT CHECK (
                        suspension_reason IS NULL OR (
                            length(suspension_reason) BETWEEN 1 AND 500
                            AND suspension_reason = trim(suspension_reason)
                        )
                    ),
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (deck_name, card_id)
                );
                CREATE INDEX deck_cards_active_idx ON deck_cards(deck_name, active);
                CREATE INDEX deck_cards_queue_idx
                    ON deck_cards(deck_name, active, suspended, card_id);

                CREATE TABLE reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id TEXT NOT NULL REFERENCES cards(card_id),
                    deck_name TEXT NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
                    reviewed_at TEXT NOT NULL,
                    review_json TEXT NOT NULL
                );
                CREATE INDEX reviews_card_idx ON reviews(card_id, reviewed_at);
                PRAGMA user_version = 5;
                """
            )
        try:
            with self.connection:
                self.connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS reviews_deck_time_idx
                    ON reviews(deck_name, reviewed_at, id)
                    """
                )
                self.connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS deck_cards_queue_idx
                    ON deck_cards(deck_name, active, suspended, card_id)
                    """
                )
        except sqlite3.Error as error:
            raise StorageError("state schema is incomplete or corrupt") from error

    def sync_deck(
        self, deck_name: str, cards: dict[str, SemanticCard], now: datetime
    ) -> tuple[int, int]:
        """Atomically reconcile one deck while preserving global card schedules."""

        now = datetime_as_utc(now)
        timestamp = datetime_to_text(now)
        created = 0
        with self.connection:
            # Membership is rebuilt for this deck only. The cards table is deliberately
            # untouched here so removed cards retain their FSRS state and review history.
            self.connection.execute(
                "UPDATE deck_cards SET active = 0 WHERE deck_name = ?", (deck_name,)
            )
            for card_id, semantic_card in cards.items():
                card_key = semantic_card.card_key
                if card_id != card_key.digest:
                    raise StorageError(f"card key {card_id} does not match its card identity hash")
                if card_key.deck_id != deck_name:
                    raise StorageError(f"card key {card_id} does not belong to deck {deck_name!r}")
                identity_json = json.dumps(
                    dict(
                        zip(
                            ("deck_id", "generator_id", "entity_id"),
                            card_key.identity_parts,
                            strict=True,
                        )
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                existing = self.connection.execute(
                    """
                    SELECT card_id, target_kind, identity_json, card_json, due_at
                    FROM cards WHERE card_id = ?
                    """,
                    (card_id,),
                ).fetchone()
                if existing is None:
                    card = Card(due=now)
                    self.connection.execute(
                        """
                        INSERT INTO cards (
                            card_id, target_kind, identity_json, card_json, due_at,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            card_id,
                            "entity",
                            identity_json,
                            card.to_json(),
                            # due_at mirrors the value inside card_json so SQLite
                            # can index and order due cards without parsing JSON.
                            datetime_to_text(card.due),
                            timestamp,
                            timestamp,
                        ),
                    )
                    created += 1
                else:
                    stored = self._stored_card(existing)
                    stored_key = stored.card_key
                    if stored_key != card_key or stored_key.digest != card_id:
                        raise StorageError(
                            f"stored identity for card hash {card_id} does not match "
                            "generated exercises"
                        )
                self.connection.execute(
                    """
                    INSERT INTO deck_cards (deck_name, card_id, active, last_seen_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(deck_name, card_id) DO UPDATE SET
                        active = 1,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (deck_name, card_id, timestamp),
                )
        return len(cards), created

    def suspend_card(self, deck_name: str, card_id: str, reason: str | None = None) -> None:
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
                WHERE deck_name = ? AND card_id = ? AND active = 1
                """,
                (update.reason, deck_name, card_id),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"card {card_id} is not a known member of deck {deck_name!r}")

    def resume_card(self, deck_name: str, card_id: str) -> None:
        """Resume one known deck membership and clear its current reason."""

        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE deck_cards
                SET suspended = 0, suspension_reason = NULL
                WHERE deck_name = ? AND card_id = ? AND active = 1
                """,
                (deck_name, card_id),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"card {card_id} is not a known member of deck {deck_name!r}")

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

    def card_available(self, deck_name: str, card_id: str) -> bool:
        """Return whether a known membership may currently enter a study queue."""

        state = self._card_membership_state(deck_name, card_id)
        if state is None:
            return False
        active, suspended, _reason = state
        return active and not suspended

    def card_suspended(self, deck_name: str, card_id: str) -> bool:
        """Return whether a current membership is suspended."""

        state = self._card_membership_state(deck_name, card_id)
        if state is None:
            return False
        active, suspended, _reason = state
        return active and suspended

    def has_membership(self, deck_name: str, card_id: str) -> bool:
        return self._card_membership_state(deck_name, card_id) is not None

    def _card_membership_state(
        self,
        deck_name: str,
        card_id: str,
    ) -> tuple[bool, bool, str | None] | None:
        row = self.connection.execute(
            """
            SELECT active, suspended, suspension_reason
            FROM deck_cards
            WHERE deck_name = ? AND card_id = ?
            """,
            (deck_name, card_id),
        ).fetchone()
        if row is None:
            return None
        return self._membership_state(
            row["active"],
            row["suspended"],
            row["suspension_reason"],
        )

    @staticmethod
    def _decode_identity(identity_json: object) -> CardKey:
        """Rebuild and validate the scoped identity stored beside card_id."""

        if not isinstance(identity_json, str):
            raise StorageError("stored card identity is not JSON text")
        try:
            values = json.loads(identity_json, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise StorageError("stored card identity is invalid JSON") from error
        if not isinstance(values, dict):
            raise StorageError("stored exercise identity must be a JSON object")
        required = {"deck_id", "generator_id", "entity_id"}
        if set(values) != required:
            raise StorageError("stored exercise identity has invalid fields")
        deck_id, generator_id, entity_id = (
            values["deck_id"],
            values["generator_id"],
            values["entity_id"],
        )
        if not all(
            isinstance(value, str) and value.strip() for value in (deck_id, generator_id, entity_id)
        ):
            raise StorageError("stored exercise identity has invalid scope IDs")
        try:
            return CardKey.exercise(deck_id, generator_id, entity_id)
        except ValidationError as error:
            raise StorageError("stored exercise identity is invalid") from error

    def due_cards(self, deck_name: str, now: datetime, limit: int | None) -> list[StoredCard]:
        self._validate_active_due_mirrors(deck_name)
        parameters: list[object] = [deck_name, datetime_to_text(now)]
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            parameters.append(limit)
        rows = self.connection.execute(
            """
            SELECT c.card_id, c.target_kind, c.identity_json, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.card_id = c.card_id
            WHERE dc.deck_name = ? AND dc.active = 1 AND dc.suspended = 0
              AND c.due_at <= ?
            ORDER BY c.due_at, c.card_id
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
            SELECT c.card_id, c.target_kind, c.identity_json, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.card_id = c.card_id
            WHERE dc.deck_name = ? AND dc.active = 1 AND dc.suspended = 0
            ORDER BY c.due_at, c.card_id
            """,
            (deck_name,),
        ).fetchall()
        return [self._stored_card(row) for row in rows]

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
            SELECT c.card_id, c.target_kind, c.identity_json, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.card_id = c.card_id
            WHERE dc.deck_name = ? AND dc.active = 1 AND dc.suspended = 0 AND EXISTS (
                SELECT 1
                FROM reviews AS r
                WHERE r.card_id = c.card_id AND r.rating = 1 AND r.reviewed_at >= ?
            )
            ORDER BY (
                SELECT MAX(r.reviewed_at)
                FROM reviews AS r
                WHERE r.card_id = c.card_id AND r.rating = 1
            ) DESC, c.card_id
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
            SELECT c.card_id, c.target_kind, c.identity_json, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.card_id = c.card_id
            WHERE dc.deck_name = ? AND dc.active = 1 AND dc.suspended = 0
              AND c.due_at > ? AND c.due_at <= ?
            ORDER BY c.due_at, c.card_id
            """
            + limit_sql,
            parameters,
        ).fetchall()
        return [self._stored_card(row) for row in rows]

    def get_card(self, card_id: str) -> StoredCard | None:
        row = self.connection.execute(
            """
            SELECT card_id, target_kind, identity_json, card_json, due_at
            FROM cards WHERE card_id = ?
            """,
            (card_id,),
        ).fetchone()
        return self._stored_card(row) if row is not None else None

    def _stored_card(self, row: sqlite3.Row) -> StoredCard:
        if row["target_kind"] != "entity":
            raise StorageError("stored card has an invalid exercise kind")
        card_key = self._decode_identity(row["identity_json"])
        if row["card_id"] != card_key.digest:
            raise StorageError(
                f"stored card identity does not match its card hash {row['card_id']}"
            )
        card_json = row["card_json"]
        if not isinstance(card_json, str):
            raise StorageError("stored card schedule is not JSON text")
        stored = StoredCard(
            card_id=row["card_id"],
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
            WHERE deck_name = ? AND active = 1
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
        rows = self.connection.execute(
            """
            SELECT c.card_id, c.target_kind, c.identity_json, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.card_id = c.card_id
            WHERE dc.deck_name = ? AND dc.active = 1
            """,
            (deck_name,),
        ).fetchall()
        for row in rows:
            self._stored_card(row)

    def save_review(
        self,
        card_id: str,
        deck_name: str,
        source_card_json: str,
        card: Card,
        review_log: ReviewLog,
        *,
        previous_interval_seconds: float | None,
        retrievability: float | None,
    ) -> str:
        """Persist updated FSRS state and its review log in one transaction."""

        # Validate the persisted fields before the indexed write predicate can
        # misclassify a corrupt membership as reviewable.
        self._card_membership_state(deck_name, card_id)
        reviewed_at = datetime_to_text(review_log.review_datetime)
        card_json = card.to_json()
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
            cursor = self.connection.execute(
                """
                UPDATE cards SET card_json = ?, due_at = ?, updated_at = ?
                WHERE card_id = ? AND card_json = ? AND EXISTS (
                    SELECT 1
                    FROM deck_cards AS dc
                    WHERE dc.deck_name = ? AND dc.card_id = cards.card_id
                      AND dc.active = 1 AND dc.suspended = 0
                )
                """,
                (
                    card_json,
                    datetime_to_text(card.due),
                    reviewed_at,
                    card_id,
                    source_card_json,
                    deck_name,
                ),
            )
            if cursor.rowcount != 1:
                exists = self.connection.execute(
                    "SELECT 1 FROM cards WHERE card_id = ?",
                    (card_id,),
                ).fetchone()
                if exists is None:
                    raise StaleReviewError(
                        f"cannot review missing card {card_id}; reload or sync before trying again"
                    )
                if not self.card_available(deck_name, card_id):
                    raise StorageError(
                        f"cannot review unavailable card {card_id} in deck {deck_name!r}"
                    )
                raise StaleReviewError(
                    f"cannot review stale card snapshot {card_id}; reload the card and try again"
                )
            self.connection.execute(
                """
                INSERT INTO reviews (card_id, deck_name, rating, reviewed_at, review_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    deck_name,
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
            return ReviewRecord(
                review_id=row["id"],
                card_id=row["card_id"],
                deck_name=row["deck_name"],
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
            SELECT id, card_id, deck_name, rating, reviewed_at, review_json
            FROM reviews
            WHERE deck_name = ? AND reviewed_at <= ?
            ORDER BY reviewed_at, id
            """,
            (deck_name, datetime_to_text(through)),
        ).fetchall()
        records: list[ReviewRecord] = []
        for row in rows:
            self._validate_review_membership(row["deck_name"], row["card_id"])
            records.append(self._review_record(row))
        return tuple(records)

    def status(self, deck_name: str, now: datetime) -> DeckStatus:
        self._validate_active_due_mirrors(deck_name)
        self._validate_review_logs(deck_name)
        timestamp = datetime_to_text(now)
        row = self.connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN dc.suspended = 0 THEN 1 ELSE 0 END), 0)
                    AS available,
                COALESCE(SUM(CASE WHEN dc.suspended = 1 THEN 1 ELSE 0 END), 0)
                    AS suspended,
                COALESCE(SUM(CASE WHEN dc.suspended = 0 AND NOT EXISTS (
                    SELECT 1 FROM reviews AS r WHERE r.card_id = c.card_id
                ) THEN 1 ELSE 0 END), 0) AS new,
                COALESCE(SUM(CASE WHEN dc.suspended = 0 AND c.due_at <= ?
                    THEN 1 ELSE 0 END), 0) AS due,
                COALESCE(SUM(CASE WHEN dc.suspended = 0 AND c.due_at > ?
                    THEN 1 ELSE 0 END), 0) AS future
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.card_id = c.card_id
            WHERE dc.deck_name = ? AND dc.active = 1
            """,
            (timestamp, timestamp, deck_name),
        ).fetchone()
        return DeckStatus(
            available=row["available"],
            suspended=row["suspended"],
            new=row["new"],
            due=row["due"],
            future=row["future"],
        )

    def card_statuses(self, deck_name: str) -> tuple[CardStatus, ...]:
        """Return active deck members in the same due-time order used for study."""

        self._validate_active_memberships(deck_name)
        self._validate_review_logs(deck_name)
        rows = self.connection.execute(
            """
            SELECT
                c.card_id,
                c.target_kind,
                c.identity_json,
                c.card_json,
                c.due_at,
                dc.active,
                dc.suspended,
                dc.suspension_reason,
                (
                    SELECT COUNT(*)
                    FROM reviews AS r
                    WHERE r.card_id = c.card_id
                ) AS review_count,
                (
                    SELECT r.reviewed_at
                    FROM reviews AS r
                    WHERE r.card_id = c.card_id
                    ORDER BY r.reviewed_at DESC, r.id DESC
                    LIMIT 1
                ) AS last_review_at,
                (
                    SELECT r.rating
                    FROM reviews AS r
                    WHERE r.card_id = c.card_id
                    ORDER BY r.reviewed_at DESC, r.id DESC
                    LIMIT 1
                ) AS last_rating
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.card_id = c.card_id
            WHERE dc.deck_name = ? AND dc.active = 1
            ORDER BY c.due_at, c.card_id
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
                    card_id=stored.card_id,
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
                )
            )
        return tuple(statuses)

    def _validate_review_logs(self, deck_name: str) -> None:
        rows = self.connection.execute(
            """
            SELECT id, card_id, deck_name, rating, reviewed_at, review_json
            FROM reviews
            WHERE deck_name = ? OR card_id IN (
                SELECT card_id FROM deck_cards WHERE deck_name = ?
            )
            """,
            (deck_name, deck_name),
        ).fetchall()
        for row in rows:
            if row["deck_name"] != deck_name:
                raise StorageError("stored review has a mismatched deck membership")
            self._validate_review_membership(row["deck_name"], row["card_id"])
            self._review_record(row)

    def _validate_review_membership(self, deck_name: object, card_id: object) -> None:
        if not isinstance(deck_name, str) or not isinstance(card_id, str):
            raise StorageError("stored review has invalid deck or card identity")
        exists = self.connection.execute(
            "SELECT 1 FROM deck_cards WHERE deck_name = ? AND card_id = ?",
            (deck_name, card_id),
        ).fetchone()
        if exists is None:
            raise StorageError("stored review has no matching deck membership")
