"""SQLite persistence for global FSRS cards, deck membership, and reviews."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fsrs import Card, Rating, ReviewLog

from rdfcards.decks import DeckKind
from rdfcards.errors import StorageError
from rdfcards.models import CardKey, RdfModel, TargetKind

SCHEMA_VERSION = 3


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


class StoredCard(RdfModel):
    card_id: str
    card_key: CardKey
    card_json: str

    def card(self) -> Card:
        try:
            return Card.from_json(self.card_json)
        except (json.JSONDecodeError, KeyError, OverflowError, TypeError, ValueError) as error:
            raise StorageError("stored card schedule is invalid") from error


class DeckStatus(RdfModel):
    active: int
    new: int
    due: int
    future: int


class CardStatus(RdfModel):
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

    def stored_card(self) -> StoredCard:
        """Rebuild the complete stored card used for read-only FSRS calculations."""

        return StoredCard(
            card_id=self.card_id,
            card_key=self.card_key,
            card_json=self.card_json,
        )


class Repository:
    """Own the schema and transactional persistence operations."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            self._initialize_schema()
        except Exception:
            self.connection.close()
            raise

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
                    target_kind TEXT NOT NULL CHECK (target_kind IN ('triple', 'entity')),
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
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (deck_name, card_id)
                );
                CREATE INDEX deck_cards_active_idx ON deck_cards(deck_name, active);

                CREATE TABLE reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id TEXT NOT NULL REFERENCES cards(card_id),
                    deck_name TEXT NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
                    reviewed_at TEXT NOT NULL,
                    review_json TEXT NOT NULL
                );
                CREATE INDEX reviews_card_idx ON reviews(card_id, reviewed_at);
                PRAGMA user_version = 3;
                """
            )

    def sync_deck(
        self, deck_name: str, presentations: dict[str, DeckKind], now: datetime
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
            for card_id, presentation in presentations.items():
                card_key = presentation.card_key
                if card_id != card_key.digest:
                    raise StorageError(
                        f"presentation key {card_id} does not match its card identity hash"
                    )
                identity_json = json.dumps(
                    card_key.n3_terms, ensure_ascii=False, separators=(",", ":")
                )
                existing = self.connection.execute(
                    """
                    SELECT target_kind, identity_json
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
                            card_key.target_kind.value,
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
                    stored_key = self._decode_identity(
                        existing["target_kind"], existing["identity_json"]
                    )
                    if stored_key != card_key or stored_key.digest != card_id:
                        raise StorageError(
                            f"stored identity for card hash {card_id} does not match query results"
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
        return len(presentations), created

    @staticmethod
    def _decode_identity(target_kind: object, identity_json: object) -> CardKey:
        """Rebuild and validate the discriminated identity stored beside card_id."""

        try:
            target = TargetKind(target_kind)
        except (TypeError, ValueError) as error:
            raise StorageError(f"stored card has unknown target kind {target_kind!r}") from error
        if not isinstance(identity_json, str):
            raise StorageError("stored card identity is not JSON text")
        try:
            values = json.loads(identity_json)
        except (json.JSONDecodeError, TypeError) as error:
            raise StorageError("stored card identity is invalid JSON") from error
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise StorageError("stored card identity must be a JSON array of N3 strings")
        return CardKey.from_n3(target, tuple(values))

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
            WHERE dc.deck_name = ? AND dc.active = 1 AND c.due_at <= ?
            ORDER BY c.due_at, c.card_id
            """
            + limit_sql,
            parameters,
        ).fetchall()
        return [self._stored_card(row) for row in rows]

    def active_cards(self, deck_name: str) -> list[StoredCard]:
        """Return every active deck member in schedule order."""

        rows = self.connection.execute(
            """
            SELECT c.card_id, c.target_kind, c.identity_json, c.card_json, c.due_at
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.card_id = c.card_id
            WHERE dc.deck_name = ? AND dc.active = 1
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
        """Return active cards failed since a timestamp, newest failure first."""

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
            WHERE dc.deck_name = ? AND dc.active = 1 AND EXISTS (
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
        """Return active cards due after now through an inclusive horizon."""

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
            WHERE dc.deck_name = ? AND dc.active = 1
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
        card_key = self._decode_identity(row["target_kind"], row["identity_json"])
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

        self.active_cards(deck_name)

    def save_review(
        self,
        card_id: str,
        deck_name: str,
        card: Card,
        review_log: ReviewLog,
    ) -> str:
        """Persist updated FSRS state and its review log in one transaction."""

        reviewed_at = datetime_to_text(review_log.review_datetime)
        card_json = card.to_json()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE cards SET card_json = ?, due_at = ?, updated_at = ?
                WHERE card_id = ?
                """,
                (
                    card_json,
                    datetime_to_text(card.due),
                    reviewed_at,
                    card_id,
                ),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"cannot review unknown card {card_id}")
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
                    review_log.to_json(),
                ),
            )
        return card_json

    def status(self, deck_name: str, now: datetime) -> DeckStatus:
        self._validate_active_due_mirrors(deck_name)
        timestamp = datetime_to_text(now)
        row = self.connection.execute(
            """
            SELECT
                COUNT(*) AS active,
                COALESCE(SUM(CASE WHEN NOT EXISTS (
                    SELECT 1 FROM reviews AS r WHERE r.card_id = c.card_id
                ) THEN 1 ELSE 0 END), 0) AS new,
                COALESCE(SUM(CASE WHEN c.due_at <= ? THEN 1 ELSE 0 END), 0) AS due,
                COALESCE(SUM(CASE WHEN c.due_at > ? THEN 1 ELSE 0 END), 0) AS future
            FROM cards AS c
            JOIN deck_cards AS dc ON dc.card_id = c.card_id
            WHERE dc.deck_name = ? AND dc.active = 1
            """,
            (timestamp, timestamp, deck_name),
        ).fetchone()
        return DeckStatus(
            active=row["active"], new=row["new"], due=row["due"], future=row["future"]
        )

    def card_statuses(self, deck_name: str) -> tuple[CardStatus, ...]:
        """Return active deck members in the same due-time order used for study."""

        rows = self.connection.execute(
            """
            SELECT
                c.card_id,
                c.target_kind,
                c.identity_json,
                c.card_json,
                c.due_at,
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
                )
            )
        return tuple(statuses)
