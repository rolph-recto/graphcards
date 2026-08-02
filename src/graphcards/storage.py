"""Atomic review-state persistence for JSON, TOML, and YAML deck files."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import random
import tempfile
import threading
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import tomlkit
from fsrs import Card, Rating, ReviewLog
from pydantic import Field, StrictInt, ValidationError, field_validator
from yaml import safe_dump

from graphcards.errors import DailyLimitError, StaleReviewError, StateConflictError, StorageError
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
from graphcards.state import (
    MAX_SUSPENSION_REASON_LENGTH,
    EntityState,
    FsrsCardState,
    ReviewEvent,
    ReviewState,
    SavedDeckSettings,
)

if TYPE_CHECKING:
    from graphcards.decks import Deck


def normalize_suspension_reason(value: object) -> object:
    """Normalize a user-facing suspension reason."""

    try:
        return EntityState.model_validate(
            {
                "fsrs": {
                    "card_id": 1,
                    "state": 1,
                    "step": 0,
                    "due": "1970-01-01T00:00:00Z",
                },
                "suspended": True,
                "suspension_reason": value,
            }
        ).suspension_reason
    except ValidationError as error:
        raise ValueError(validation_message(error)) from error


def utc_now() -> datetime:
    """Return the current timezone-aware UTC instant."""

    return datetime.now(UTC)


def datetime_as_utc(value: datetime) -> datetime:
    """Require an aware timestamp and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise StorageError("datetime values must be timezone-aware")
    return value.astimezone(UTC)


def datetime_to_text(value: datetime) -> str:
    """Encode a timestamp in one stable UTC representation."""

    return datetime_as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _datetime_from_text(value: object) -> datetime:
    """Decode and validate a canonical UTC timestamp from persisted state."""

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
    """Validate one count before it crosses the storage boundary."""

    if type(value) is not int or value < 0:
        raise StorageError(f"stored {label} count is invalid")
    return value


class StoredCard(FrozenModel):
    """One FSRS card snapshot returned by the deck-file store."""

    card_key: CardKey
    card_json: str
    snapshot_digest: str | None = None
    state_revision: StrictInt | None = None

    def card(self) -> Card:
        try:
            card = Card.from_json(self.card_json)
            datetime_as_utc(card.due)
            if card.last_review is not None:
                datetime_as_utc(card.last_review)
            for value in (card.stability, card.difficulty):
                if value is not None and (not math.isfinite(value) or value <= 0):
                    raise ValueError("FSRS numeric field is invalid")
            FsrsCardState.from_card(card)
            return card
        except (json.JSONDecodeError, KeyError, OverflowError, TypeError, ValueError) as error:
            raise StorageError("stored card schedule is invalid") from error


class DeckStatus(FrozenModel):
    """Summary counts for one deck's current generated membership."""

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
        """Return counts grouped by study queue."""

        return self.queue_counts

    @property
    def settings(self) -> DeckSchedulingSettings:
        """Return the validated settings used by this status snapshot."""

        return self.scheduling


class DeckQueueStatus(DeckStatus):
    """Deck status with daily-limit accounting."""

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
    """Card-level schedule details used by CLI and web status views."""

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
    snapshot_digest: str | None = None
    state_revision: StrictInt | None = None

    @property
    def queue_kind(self) -> QueueKind:
        return self.queue

    def stored_card(self) -> StoredCard:
        """Rebuild the complete card snapshot used by review operations."""

        return StoredCard(
            card_key=self.card_key,
            card_json=self.card_json,
            snapshot_digest=self.snapshot_digest,
            state_revision=self.state_revision,
        )


class SuspensionUpdate(FrozenModel):
    """Validated suspension metadata for one mutation."""

    reason: str | None = Field(default=None, max_length=MAX_SUSPENSION_REASON_LENGTH)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return normalize_suspension_reason(value)


class ReviewRecord(FrozenModel):
    """Review history data exposed to the presentation layer."""

    review_id: int = Field(gt=0)
    card_key: CardKey
    rating: Rating
    reviewed_at: datetime
    previous_interval_seconds: float | None
    scheduled_interval_seconds: float | None
    retrievability: float | None


class _StateSnapshot(FrozenModel):
    digest: str
    revision: int | None


class DeckFileStateStore:
    """Read and atomically mutate review state embedded in deck files.

    One store can serve all configured decks. The deck directory remains the runtime identity;
    the state document is always read from and written back to the deck's existing extension.
    """

    _thread_locks: dict[Path, threading.Lock] = {}
    _thread_locks_guard = threading.Lock()

    def __init__(self, decks: Deck | Iterable[Deck] | Mapping[str, Deck] | None = None) -> None:
        self._decks: dict[str, Deck] = {}
        if decks is not None:
            if isinstance(decks, Mapping):
                values = decks.values()
            elif hasattr(decks, "name") and hasattr(decks, "path"):
                values = (decks,)
            else:
                values = decks
            for deck in values:
                self._decks[deck.name] = deck
        self._snapshots: dict[str, _StateSnapshot] = {}

    def __enter__(self) -> DeckFileStateStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the no-op store lifecycle used by the server and CLI."""

    def _resolve_deck(self, value: Deck | str | Path) -> Deck:
        if hasattr(value, "name") and hasattr(value, "path"):
            deck = value
            self._decks[deck.name] = deck
            return deck
        if isinstance(value, Path):
            try:
                from graphcards.decks import Deck as DeckType

                deck = DeckType.load(value)
            except Exception as error:
                raise StorageError(f"could not load deck file {value}") from error
            self._decks[deck.name] = deck
            return deck
        if isinstance(value, str) and value in self._decks:
            return self._decks[value]
        available = ", ".join(sorted(self._decks)) or "none"
        raise StorageError(f"unknown deck {value!r}; configured decks: {available}")

    @staticmethod
    def _digest(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def _lock_for(cls, path: Path) -> threading.Lock:
        with cls._thread_locks_guard:
            return cls._thread_locks.setdefault(path, threading.Lock())

    @classmethod
    @contextlib.contextmanager
    def _file_lock(cls, path: Path):
        """Acquire a process and OS lock beside one deck file."""

        lock = cls._lock_for(path)
        lock_path = path.with_name(f".{path.name}.graphcards.lock")
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock, lock_path.open("a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except OSError as error:
            raise StorageError(f"could not lock deck file {path}") from error

    @staticmethod
    def _read_bytes(path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as error:
            raise StorageError(f"could not read deck file {path}") from error

    def _load_current(self, deck: Deck) -> tuple[Deck, bytes, str]:
        raw = self._read_bytes(deck.path)
        try:
            from graphcards.decks import Deck as DeckType

            current = DeckType.load(deck.path)
        except StorageError:
            raise
        except Exception as error:
            raise StorageError(f"could not load deck file {deck.path}: {error}") from error
        return current, raw, self._digest(raw)

    @staticmethod
    def _state_or_error(deck: Deck, current: Deck) -> ReviewState:
        state = current.document.review_state
        if state is None:
            raise StorageError(
                f"deck {deck.display_name!r} has no review state; synchronize the deck first"
            )
        return state

    def _read_state(self, value: Deck | str | Path) -> tuple[Deck, ReviewState, str]:
        deck = self._resolve_deck(value)
        current, raw, digest = self._load_current(deck)
        state = self._state_or_error(deck, current)
        self._snapshots[deck.name] = _StateSnapshot(digest=digest, revision=state.revision)
        self._decks[deck.name] = current
        return current, state, digest

    def _expected_snapshot(
        self,
        deck: Deck,
        expected_digest: str | None,
        expected_revision: int | None,
    ) -> _StateSnapshot | None:
        known = self._snapshots.get(deck.name)
        if expected_digest is not None:
            return _StateSnapshot(digest=expected_digest, revision=expected_revision)
        return known

    @staticmethod
    def _conflict(
        deck: Deck, expected: _StateSnapshot, actual_digest: str, actual_revision: int | None
    ) -> StateConflictError:
        expected_revision_text = (
            str(expected.revision) if expected.revision is not None else "unknown"
        )
        actual_revision_text = str(actual_revision) if actual_revision is not None else "unknown"
        return StateConflictError(
            f"deck file {deck.path} changed; reload the deck before writing "
            f"(revision {expected_revision_text} is not {actual_revision_text})"
        )

    @staticmethod
    def _initial_state(
        cards: Mapping[str, SemanticCard],
        now: datetime,
    ) -> ReviewState:
        entities: dict[str, EntityState] = {}
        for entity_id, semantic_card in cards.items():
            if entity_id != semantic_card.card_key.entity_id:
                raise StorageError(f"card key {entity_id} does not match its entity identity")
            try:
                card_state = FsrsCardState.from_card(Card(due=now))
                entities[entity_id] = EntityState(
                    fsrs=card_state,
                    last_seen_at=now,
                )
            except (TypeError, ValueError, ValidationError) as error:
                raise StorageError("could not initialize FSRS card state") from error
        try:
            return ReviewState(revision=1, entities=entities)
        except ValidationError as error:
            raise StorageError("could not initialize review state") from error

    @staticmethod
    def _document_values(document: object) -> dict[str, object]:
        try:
            return document.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
                serialize_as_any=True,
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("review state cannot be serialized") from error

    @staticmethod
    def _serialize(path: Path, values: Mapping[str, object]) -> bytes:
        try:
            extension = path.suffix.lower()
            if extension == ".json":
                text = json.dumps(
                    values,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            elif extension == ".toml":
                text = tomlkit.dumps(values)
            elif extension in {".yaml", ".yml"}:
                text = safe_dump(
                    values,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            else:
                raise ValueError(f"unsupported deck file extension {path.suffix!r}")
            return (text.rstrip("\n") + "\n").encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as error:
            raise StorageError(f"could not serialize deck file {path}") from error

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            return
        finally:
            os.close(descriptor)

    @classmethod
    def _atomic_write(cls, path: Path, document: object) -> str:
        values = cls._document_values(document)
        payload = cls._serialize(path, values)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary = Path(temporary_file.name)
                temporary_file.write(payload)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary, path)
            temporary = None
            cls._sync_directory(path.parent)
        except (OSError, UnicodeError) as error:
            raise StorageError(f"could not atomically write deck file {path}") from error
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink()
        return cls._digest(payload)

    def _write_state(
        self,
        deck: Deck,
        current: Deck,
        state: ReviewState,
        raw: bytes,
        expected: _StateSnapshot | None,
    ) -> tuple[ReviewState, str]:
        actual_digest = self._digest(raw)
        actual_revision = (
            current.document.review_state.revision if current.document.review_state else None
        )
        if expected is not None and (
            actual_digest != expected.digest
            or (expected.revision is not None and expected.revision != actual_revision)
        ):
            raise self._conflict(deck, expected, actual_digest, actual_revision)
        try:
            document = current.document.model_copy(update={"review_state": state})
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("review state cannot be attached to the deck document") from error
        digest = self._atomic_write(deck.path, document)
        self._decks[deck.name] = current
        self._snapshots[deck.name] = _StateSnapshot(digest=digest, revision=state.revision)
        return state, digest

    def _mutate(
        self,
        value: Deck | str | Path,
        change: Callable[[Deck, ReviewState], tuple[ReviewState, Any]],
        *,
        expected_digest: str | None = None,
        expected_revision: int | None = None,
        allow_initialize: bool = False,
        now: datetime | None = None,
        stale_review: bool = False,
    ) -> Any:
        deck = self._resolve_deck(value)
        expected = self._expected_snapshot(deck, expected_digest, expected_revision)
        with self._file_lock(deck.path):
            current, raw, _digest = self._load_current(deck)
            state = current.document.review_state
            if state is None:
                if not allow_initialize:
                    self._state_or_error(deck, current)
                if expected is not None and (
                    self._digest(raw) != expected.digest or expected.revision is not None
                ):
                    raise self._conflict(deck, expected, self._digest(raw), None)
                generated = current.generate_all(rng=random.Random(0))
                state = self._initial_state(generated, datetime_as_utc(now or utc_now()))
            else:
                if expected is not None:
                    actual_digest = self._digest(raw)
                    if actual_digest != expected.digest or (
                        expected.revision is not None and expected.revision != state.revision
                    ):
                        if (
                            stale_review
                            and expected.revision is not None
                            and expected.revision != state.revision
                        ):
                            raise StaleReviewError(
                                "cannot review stale card snapshot; reload the card and try again"
                            )
                        raise self._conflict(deck, expected, actual_digest, state.revision)
            try:
                changed, result = change(current, state)
                if changed.revision != state.revision:
                    raise StorageError("review-state mutation changed its revision unexpectedly")
                changed = changed.model_copy(update={"revision": state.revision + 1})
            except StorageError:
                raise
            except (TypeError, ValueError, ValidationError) as error:
                raise StorageError(f"could not validate review-state mutation: {error}") from error
            _state, _new_digest = self._write_state(deck, current, changed, raw, None)
            return result

    def sync_deck(
        self,
        value: Deck | str,
        cards: Mapping[str, SemanticCard],
        now: datetime,
        scheduling: DeckSchedulingSettings | None = None,
        daily_limits: DailyLimits | None = None,
    ) -> tuple[int, int]:
        """Reconcile current generated entities while retaining removed state."""

        del scheduling, daily_limits
        deck = self._resolve_deck(value)
        now = datetime_as_utc(now)
        expected = self._snapshots.get(deck.name)
        generated = dict(cards)
        for entity_id, card in generated.items():
            if entity_id != card.card_key.entity_id:
                raise StorageError(f"card key {entity_id} does not match its entity identity")
            if card.card_key.deck_id != deck.name:
                raise StorageError(f"card key {entity_id} does not belong to deck {deck.name!r}")
        with self._file_lock(deck.path):
            current, raw, digest = self._load_current(deck)
            if expected is not None and digest != expected.digest:
                raise self._conflict(
                    deck,
                    expected,
                    digest,
                    current.document.review_state.revision
                    if current.document.review_state
                    else None,
                )
            state = current.document.review_state
            if state is None:
                state = self._initial_state(generated, now)
                created = len(generated)
                self._write_state(deck, current, state, raw, None)
                return len(generated), created
            entities = dict(state.entities)
            created = 0
            for entity_id, semantic_card in generated.items():
                del semantic_card
                existing = entities.get(entity_id)
                if existing is None:
                    card_state = FsrsCardState.from_card(Card(due=now))
                    entities[entity_id] = EntityState(fsrs=card_state, last_seen_at=now)
                    created += 1
                else:
                    entities[entity_id] = existing.model_copy(update={"last_seen_at": now})
            try:
                updated = ReviewState(
                    version=state.version,
                    revision=state.revision + 1,
                    entities=entities,
                    reviews=state.reviews,
                    settings=state.settings,
                )
            except ValidationError as error:
                raise StorageError("stored review state is invalid") from error
            self._write_state(deck, current, updated, raw, None)
            return len(generated), created

    def _active_ids(self, deck: Deck) -> tuple[str, ...]:
        try:
            return tuple(deck.target_entity_ids)
        except (AttributeError, TypeError, ValueError) as error:
            raise StorageError("deck generated entity identities are invalid") from error

    @staticmethod
    def _reviews_for(state: ReviewState, entity_id: str | None = None) -> tuple[ReviewEvent, ...]:
        return tuple(
            event for event in state.reviews if entity_id is None or event.entity_id == entity_id
        )

    def _stored_card(
        self,
        deck: Deck,
        entity_id: str,
        entity_state: EntityState,
        digest: str,
        revision: int,
    ) -> StoredCard:
        try:
            card = entity_state.fsrs.to_card()
            card_key = CardKey.exercise(deck.name, entity_id)
            return StoredCard(
                card_key=card_key,
                card_json=card.to_json(),
                snapshot_digest=digest,
                state_revision=revision,
            )
        except (TypeError, ValueError, ValidationError, OverflowError) as error:
            raise StorageError("stored card schedule is invalid") from error

    def _active_records(
        self,
        value: Deck | str,
        *,
        include_suspended: bool,
    ) -> tuple[Deck, ReviewState, str, tuple[tuple[StoredCard, EntityState], ...]]:
        deck, state, digest = self._read_state(value)
        records: list[tuple[StoredCard, EntityState]] = []
        for entity_id in self._active_ids(deck):
            entity_state = state.entities.get(entity_id)
            if entity_state is None:
                raise StorageError(
                    f"deck {deck.display_name!r} has no state for current entity {entity_id!r}; "
                    "synchronize the deck"
                )
            if include_suspended or not entity_state.suspended:
                records.append(
                    (
                        self._stored_card(deck, entity_id, entity_state, digest, state.revision),
                        entity_state,
                    )
                )
        return deck, state, digest, tuple(records)

    def deck_settings(
        self,
        value: Deck | str,
        defaults: DeckSchedulingSettings | None = None,
    ) -> DeckSchedulingSettings:
        deck, state, _digest = self._read_state(value)
        if state.settings is not None and state.settings.queue_settings is not None:
            return state.settings.queue_settings
        return defaults or deck.scheduling

    def get_deck_settings(
        self,
        value: Deck | str,
        defaults: DeckSchedulingSettings | None = None,
    ) -> DeckSchedulingSettings:
        return self.deck_settings(value, defaults)

    def daily_limits(
        self,
        value: Deck | str,
        defaults: DailyLimits | None = None,
    ) -> DailyLimits:
        deck, state, _digest = self._read_state(value)
        if state.settings is not None and state.settings.daily_limits is not None:
            return state.settings.daily_limits
        return defaults or deck.daily_limits

    def set_daily_limits(
        self,
        value: Deck | str,
        limits: DailyLimits,
        *,
        expected_digest: str | None = None,
        expected_revision: int | None = None,
    ) -> DailyLimits:
        try:
            validated = DailyLimits.model_validate(limits)
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("daily limit settings are invalid") from error

        def change(_deck: Deck, state: ReviewState) -> tuple[ReviewState, DailyLimits]:
            current = state.settings or SavedDeckSettings()
            return (
                state.model_copy(
                    update={"settings": current.model_copy(update={"daily_limits": validated})}
                ),
                validated,
            )

        return self._mutate(
            value,
            change,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
            allow_initialize=True,
        )

    def set_deck_settings(
        self,
        value: Deck | str,
        settings: DeckSchedulingSettings,
        *,
        expected_digest: str | None = None,
        expected_revision: int | None = None,
    ) -> DeckSchedulingSettings:
        try:
            validated = (
                settings
                if isinstance(settings, DeckSchedulingSettings)
                else DeckSchedulingSettings.model_validate(settings)
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("deck scheduling settings are invalid") from error

        def change(_deck: Deck, state: ReviewState) -> tuple[ReviewState, DeckSchedulingSettings]:
            current = state.settings or SavedDeckSettings()
            return (
                state.model_copy(
                    update={"settings": current.model_copy(update={"queue_settings": validated})}
                ),
                validated,
            )

        return self._mutate(
            value,
            change,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
            allow_initialize=True,
        )

    def _membership_state(
        self,
        value: Deck | str,
        entity_id: str,
    ) -> tuple[Deck, ReviewState, str, EntityState, bool]:
        deck, state, digest = self._read_state(value)
        entity_state = state.entities.get(entity_id)
        if entity_state is None:
            raise StorageError(f"entity {entity_id} is not known in deck {deck.name!r}")
        active = entity_id in set(self._active_ids(deck))
        return deck, state, digest, entity_state, active

    def has_membership(self, value: Deck | str, entity_id: str) -> bool:
        try:
            _deck, _state, _digest, _entity, active = self._membership_state(value, entity_id)
        except StorageError:
            return False
        return active

    def card_available(self, value: Deck | str, entity_id: str) -> bool:
        try:
            _deck, _state, _digest, entity, active = self._membership_state(value, entity_id)
        except StorageError:
            return False
        return active and not entity.suspended

    def card_suspended(self, value: Deck | str, entity_id: str) -> bool:
        try:
            _deck, _state, _digest, entity, active = self._membership_state(value, entity_id)
        except StorageError:
            return False
        return active and entity.suspended

    def _update_memberships(
        self,
        value: Deck | str,
        entity_ids: tuple[str, ...],
        *,
        suspended: bool,
        reason: str | None,
        expected_digest: str | None = None,
        expected_revision: int | None = None,
    ) -> None:
        if not entity_ids or len(entity_ids) != len(set(entity_ids)):
            raise StorageError("card selection must contain unique entities")
        try:
            update = SuspensionUpdate(reason=reason)
        except ValidationError as error:
            raise StorageError(validation_message(error)) from error

        def change(deck: Deck, state: ReviewState) -> tuple[ReviewState, None]:
            active_ids = set(self._active_ids(deck))
            if not set(entity_ids).issubset(active_ids):
                raise StorageError("one or more selected cards is no longer active")
            entities = dict(state.entities)
            for entity_id in entity_ids:
                existing = entities.get(entity_id)
                if existing is None:
                    raise StorageError("one or more selected cards is not known")
                entities[entity_id] = existing.model_copy(
                    update={
                        "suspended": suspended,
                        "suspension_reason": update.reason if suspended else None,
                    }
                )
            return state.model_copy(update={"entities": entities}), None

        self._mutate(
            value,
            change,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
            allow_initialize=True,
        )

    def suspend_card(
        self,
        value: Deck | str,
        entity_id: str,
        reason: str | None = None,
        *,
        expected_digest: str | None = None,
        expected_revision: int | None = None,
    ) -> None:
        self._update_memberships(
            value,
            (entity_id,),
            suspended=True,
            reason=reason,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
        )

    def resume_card(
        self,
        value: Deck | str,
        entity_id: str,
        *,
        expected_digest: str | None = None,
        expected_revision: int | None = None,
    ) -> None:
        self._update_memberships(
            value,
            (entity_id,),
            suspended=False,
            reason=None,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
        )

    def suspend_cards(
        self,
        value: Deck | str,
        entity_ids: tuple[str, ...],
        reason: str | None = None,
        *,
        expected_digest: str | None = None,
        expected_revision: int | None = None,
    ) -> None:
        self._update_memberships(
            value,
            entity_ids,
            suspended=True,
            reason=reason,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
        )

    def resume_cards(
        self,
        value: Deck | str,
        entity_ids: tuple[str, ...],
        *,
        expected_digest: str | None = None,
        expected_revision: int | None = None,
    ) -> None:
        self._update_memberships(
            value,
            entity_ids,
            suspended=False,
            reason=None,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
        )

    def active_cards(self, value: Deck | str) -> list[StoredCard]:
        """Return current, available deck members in due order."""

        _deck, _state, _digest, records = self._active_records(value, include_suspended=False)
        return [card for card, _entity in sorted(records, key=self._card_sort_key)]

    @staticmethod
    def _card_sort_key(record: tuple[StoredCard, EntityState]) -> tuple[datetime, str]:
        card, _entity = record
        return datetime_as_utc(card.card().due), card.card_key.entity_id

    def due_cards(self, value: Deck | str, now: datetime, limit: int | None) -> list[StoredCard]:
        return (
            self.queue_cards(value, now, due_only=True)[:limit]
            if limit is not None
            else self.queue_cards(value, now)
        )

    def _queue_records(self, value: Deck | str) -> list[tuple[StoredCard, QueueKind]]:
        deck, state, _digest, records = self._active_records(value, include_suspended=False)
        result: list[tuple[StoredCard, QueueKind]] = []
        for card, _entity in records:
            try:
                queue = classify_card(
                    card.card(), len(self._reviews_for(state, card.card_key.entity_id))
                )
            except (TypeError, ValueError, StorageError) as error:
                if isinstance(error, StorageError):
                    raise
                raise StorageError("stored queue state is invalid") from error
            result.append((card, queue))
        del deck
        result.sort(
            key=lambda item: (datetime_as_utc(item[0].card().due), item[0].card_key.entity_id)
        )
        return result

    def queue_kind(self, card_key: CardKey) -> QueueKind:
        for card, queue in self._queue_records(card_key.deck_id):
            if card.card_key == card_key:
                return queue
        raise StorageError(
            f"card {card_key.entity_id!r} is not an active member of deck {card_key.deck_id!r}"
        )

    def queue_cards(
        self,
        value: Deck | str,
        now: datetime,
        queue: QueueKind | str | None = None,
        *,
        due_only: bool = True,
    ) -> list[StoredCard]:
        current = datetime_as_utc(now)
        queue_kind = None if queue is None else QueueKind(queue)
        priorities = {
            QueueKind.LEARNING: 0,
            QueueKind.RELEARNING: 1,
            QueueKind.REVIEW: 2,
            QueueKind.NEW: 3,
        }
        records = [
            (card, card_queue)
            for card, card_queue in self._queue_records(value)
            if (queue_kind is None or card_queue is queue_kind)
            and (not due_only or datetime_as_utc(card.card().due) <= current)
        ]
        records.sort(
            key=lambda item: (
                priorities[item[1]],
                datetime_as_utc(item[0].card().due),
                item[0].card_key.entity_id,
            )
        )
        return [card for card, _queue in records]

    def queue_counts(
        self,
        value: Deck | str,
        now: datetime,
        *,
        due_only: bool = True,
    ) -> QueueCounts:
        current = datetime_as_utc(now)
        counts = {queue: 0 for queue in QueueKind}
        for card, queue in self._queue_records(value):
            if not due_only or datetime_as_utc(card.card().due) <= current:
                counts[queue] += 1
        return QueueCounts.from_counts(counts)

    def daily_usage(
        self,
        value: Deck | str,
        now: datetime,
        timezone: ZoneInfo,
        limits: DailyLimits,
    ) -> DailyUsage:
        deck, state, _digest = self._read_state(value)
        del deck
        try:
            local_date, start, end = local_day_bounds(now, timezone)
            validated_limits = DailyLimits.model_validate(limits)
        except (TypeError, ValueError, ValidationError) as error:
            raise StorageError("daily usage settings are invalid") from error
        events = [
            event
            for event in state.reviews
            if datetime_as_utc(event.reviewed_at) >= start
            and datetime_as_utc(event.reviewed_at) < end
        ]
        first_events = {
            event.entity_id
            for event in events
            if not any(
                earlier.entity_id == event.entity_id
                and (earlier.reviewed_at, earlier.review_id) < (event.reviewed_at, event.review_id)
                for earlier in state.reviews
            )
        }
        return DailyUsage(
            local_date=local_date,
            limits=validated_limits,
            new_used=len(first_events),
            reviews_used=len(events),
        )

    def _daily_usage_for_state(
        self,
        state: ReviewState,
        reviewed_at: datetime,
        timezone: ZoneInfo,
        limits: DailyLimits,
    ) -> DailyUsage:
        local_date, start, end = local_day_bounds(reviewed_at, timezone)
        events = [
            event for event in state.reviews if start <= datetime_as_utc(event.reviewed_at) < end
        ]
        first_events = {
            event.entity_id
            for event in events
            if not any(
                earlier.entity_id == event.entity_id
                and (earlier.reviewed_at, earlier.review_id) < (event.reviewed_at, event.review_id)
                for earlier in state.reviews
            )
        }
        return DailyUsage(
            local_date=local_date,
            limits=limits,
            new_used=len(first_events),
            reviews_used=len(events),
        )

    def forgotten_cards(
        self,
        value: Deck | str,
        since: datetime,
        limit: int | None,
    ) -> list[StoredCard]:
        _deck, state, _digest, records = self._active_records(value, include_suspended=False)
        since = datetime_as_utc(since)
        failed = {
            entity_id
            for entity_id in {card.card_key.entity_id for card, _entity in records}
            if any(
                event.entity_id == entity_id
                and event.rating is Rating.Again
                and datetime_as_utc(event.reviewed_at) >= since
                for event in state.reviews
            )
        }
        result = [card for card, _entity in records if card.card_key.entity_id in failed]
        result.sort(
            key=lambda card: (
                max(
                    datetime_as_utc(event.reviewed_at)
                    for event in state.reviews
                    if event.entity_id == card.card_key.entity_id and event.rating is Rating.Again
                ),
                card.card_key.entity_id,
            ),
            reverse=True,
        )
        return result[:limit] if limit is not None else result

    def future_cards(
        self,
        value: Deck | str,
        after: datetime,
        through: datetime,
        limit: int | None,
    ) -> list[StoredCard]:
        after = datetime_as_utc(after)
        through = datetime_as_utc(through)
        _deck, _state, _digest, records = self._active_records(value, include_suspended=False)
        result = [
            card for card, _entity in records if after < datetime_as_utc(card.card().due) <= through
        ]
        result.sort(key=lambda card: (datetime_as_utc(card.card().due), card.card_key.entity_id))
        return result[:limit] if limit is not None else result

    def get_card(self, value: Deck | str, card_key: CardKey) -> StoredCard | None:
        deck, state, digest = self._read_state(value)
        if card_key.deck_id != deck.name:
            return None
        entity_state = state.entities.get(card_key.entity_id)
        if entity_state is None:
            return None
        return self._stored_card(deck, card_key.entity_id, entity_state, digest, state.revision)

    def review_history(self, value: Deck | str, through: datetime) -> tuple[ReviewRecord, ...]:
        deck, state, _digest = self._read_state(value)
        through = datetime_as_utc(through)
        records = [
            ReviewRecord(
                review_id=event.review_id,
                card_key=CardKey.exercise(deck.name, event.entity_id),
                rating=event.rating,
                reviewed_at=event.reviewed_at,
                previous_interval_seconds=event.previous_interval_seconds,
                scheduled_interval_seconds=event.scheduled_interval_seconds,
                retrievability=event.retrievability,
            )
            for event in state.reviews
            if datetime_as_utc(event.reviewed_at) <= through
        ]
        records.sort(key=lambda record: (record.reviewed_at, record.review_id))
        return tuple(records)

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
        expected_digest: str | None = None,
        expected_revision: int | None = None,
    ) -> str:
        """Save the new schedule and immutable review event in one file replacement."""

        if card.card_id is None or review_log.card_id is None:
            raise StorageError("FSRS review is missing a card ID")
        card_json = card.to_json()

        def change(deck: Deck, state: ReviewState) -> tuple[ReviewState, str]:
            if card_key.deck_id != deck.name:
                raise StorageError(
                    f"card {card_key.entity_id} does not belong to deck {deck.name!r}"
                )
            if card_key.entity_id not in set(self._active_ids(deck)):
                raise StorageError(
                    f"cannot review unavailable entity {card_key.entity_id} in deck {deck.name!r}"
                )
            existing = state.entities.get(card_key.entity_id)
            if existing is None:
                raise StaleReviewError(
                    f"cannot review missing card {deck.name}/{card_key.entity_id}; reload or sync "
                    "before trying again"
                )
            stored = self._stored_card(deck, card_key.entity_id, existing, "", state.revision)
            if stored.card_json != source_card_json:
                raise StaleReviewError(
                    f"cannot review stale card snapshot {deck.name}/{card_key.entity_id}; "
                    "reload the card and try again"
                )
            if existing.suspended:
                raise StorageError(
                    f"cannot review unavailable entity {card_key.entity_id} in deck {deck.name!r}"
                )
            if existing.fsrs.card_id != card.card_id or review_log.card_id != card.card_id:
                raise StorageError("review card ID does not match stored FSRS state")
            if daily_limits is not None:
                if timezone is None:
                    raise StorageError("daily usage timezone is required")
                try:
                    limits = DailyLimits.model_validate(daily_limits)
                except (TypeError, ValueError, ValidationError) as error:
                    raise StorageError("daily usage settings are invalid") from error
                usage = self._daily_usage_for_state(
                    state, review_log.review_datetime, timezone, limits
                )
                if usage.reviews_remaining <= 0:
                    raise DailyLimitError("reviews", 0)
                if not self._reviews_for(state, card_key.entity_id) and usage.new_remaining <= 0:
                    raise DailyLimitError("new", 0)
            next_id = max((event.review_id for event in state.reviews), default=0) + 1
            try:
                event = ReviewEvent(
                    review_id=next_id,
                    entity_id=card_key.entity_id,
                    card_id=review_log.card_id,
                    rating=review_log.rating,
                    reviewed_at=review_log.review_datetime,
                    duration=review_log.review_duration,
                    previous_interval_seconds=previous_interval_seconds,
                    scheduled_interval_seconds=(
                        datetime_as_utc(card.due) - datetime_as_utc(review_log.review_datetime)
                    ).total_seconds(),
                    retrievability=retrievability,
                )
                updated_entity = existing.model_copy(update={"fsrs": FsrsCardState.from_card(card)})
                updated = state.model_copy(
                    update={
                        "entities": {
                            **state.entities,
                            card_key.entity_id: updated_entity,
                        },
                        "reviews": (*state.reviews, event),
                    }
                )
            except (TypeError, ValueError, ValidationError) as error:
                raise StorageError("review analytics metadata is invalid") from error
            return updated, card_json

        return self._mutate(
            card_key.deck_id,
            change,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
            stale_review=True,
        )

    def _all_statuses(
        self, value: Deck | str
    ) -> tuple[Deck, ReviewState, str, tuple[CardStatus, ...]]:
        deck, state, digest, records = self._active_records(value, include_suspended=True)
        result: list[CardStatus] = []
        for stored, entity_state in records:
            card = stored.card()
            events = self._reviews_for(state, stored.card_key.entity_id)
            latest = max(
                events, key=lambda event: (event.reviewed_at, event.review_id), default=None
            )
            if (latest is None) != (card.last_review is None):
                raise StorageError("stored card schedule and review history do not match")
            if (
                latest is not None
                and card.last_review is not None
                and datetime_as_utc(card.last_review) != datetime_as_utc(latest.reviewed_at)
            ):
                raise StorageError("stored card schedule and review history do not match")
            result.append(
                CardStatus(
                    card_key=stored.card_key,
                    card_json=stored.card_json,
                    fsrs_state=card.state.name.lower(),
                    fsrs_step=card.step,
                    stability=card.stability,
                    difficulty=card.difficulty,
                    review_count=len(events),
                    due_at=datetime_as_utc(card.due),
                    last_review_at=latest.reviewed_at if latest is not None else None,
                    last_rating=latest.rating if latest is not None else None,
                    suspended=entity_state.suspended,
                    suspension_reason=entity_state.suspension_reason,
                    queue=classify_card(card, len(events)),
                    snapshot_digest=digest,
                    state_revision=state.revision,
                )
            )
        result.sort(key=lambda item: (item.due_at, item.card_key.entity_id))
        return deck, state, digest, tuple(result)

    def card_statuses(self, value: Deck | str) -> tuple[CardStatus, ...]:
        return self._all_statuses(value)[3]

    def status(
        self,
        value: Deck | str,
        now: datetime,
        scheduling: DeckSchedulingSettings | None = None,
    ) -> DeckStatus:
        deck, state, _digest, statuses = self._all_statuses(value)
        now = datetime_as_utc(now)
        settings = scheduling or self.deck_settings(deck, deck.scheduling)
        available = [status for status in statuses if not status.suspended]
        queue_counts = self.queue_counts(deck, now)
        return DeckStatus(
            available=len(available),
            suspended=len(statuses) - len(available),
            new=sum(status.review_count == 0 and not status.suspended for status in statuses),
            due=sum(status.due_at <= now and not status.suspended for status in statuses),
            future=sum(status.due_at > now and not status.suspended for status in statuses),
            queue_counts=queue_counts,
            queue_order=queue_order(settings),
            scheduling=settings,
        )

    def queue_status(
        self,
        value: Deck | str,
        now: datetime,
        scheduling: DeckSchedulingSettings | ZoneInfo | None = None,
        timezone: ZoneInfo | DailyLimits | None = None,
        limits: DailyLimits | None = None,
    ) -> DeckQueueStatus:
        if isinstance(scheduling, ZoneInfo):
            actual_scheduling = None
            actual_timezone = scheduling
            actual_limits = timezone if isinstance(timezone, DailyLimits) else limits
        else:
            actual_scheduling = scheduling
            actual_timezone = timezone if isinstance(timezone, ZoneInfo) else ZoneInfo("UTC")
            actual_limits = limits
        deck = self._resolve_deck(value)
        actual_limits = actual_limits or self.daily_limits(deck, deck.daily_limits)
        base = self.status(deck, now, actual_scheduling)
        daily = self.daily_usage(deck, now, actual_timezone, actual_limits)
        capacities = queue_selection_capacities(base.queue_counts, daily)
        hidden = QueueCounts.from_counts(
            {
                queue: max(0, base.queue_counts.for_queue(queue) - capacities.for_queue(queue))
                for queue in QueueKind
            }
        )
        return DeckQueueStatus(
            available=base.available,
            suspended=base.suspended,
            new=base.new,
            due=base.due,
            future=base.future,
            queue_counts=base.queue_counts,
            queue_order=base.queue_order,
            scheduling=base.scheduling,
            hidden_counts=hidden,
            daily_usage=daily,
        )


__all__ = [
    "CardStatus",
    "DeckFileStateStore",
    "DeckQueueStatus",
    "DeckStatus",
    "ReviewRecord",
    "StoredCard",
    "SuspensionUpdate",
    "datetime_as_utc",
    "datetime_to_text",
    "normalize_suspension_reason",
    "utc_now",
]
