"""Validated review-state documents stored inside deck files."""

from __future__ import annotations

import math
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Literal

from fsrs import Card, Rating, State
from pydantic import (
    AliasChoices,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from graphcards.models import FrozenModel
from graphcards.references import EntityId
from graphcards.scheduling import DailyLimits, DeckSchedulingSettings

MAX_SUSPENSION_REASON_LENGTH = 500
_UNSAFE_REASON_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def _utc_timestamp(value: object) -> object:
    """Validate one state timestamp and normalize it to UTC."""

    if isinstance(value, (bool, int, float)):
        raise ValueError("timestamp must be a timestamp string")
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _finite_float(value: object) -> object:
    """Accept JSON numbers and reject booleans, infinities, and NaN values."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError("must be a finite number")
    return converted


def _reason(value: object) -> object:
    """Normalize one suspension reason at the state boundary."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("suspension reason must be text")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_SUSPENSION_REASON_LENGTH:
        raise ValueError(
            f"suspension reason must not exceed {MAX_SUSPENSION_REASON_LENGTH} characters"
        )
    if any(
        unicodedata.category(character) in _UNSAFE_REASON_CATEGORIES for character in normalized
    ):
        raise ValueError(
            "suspension reason cannot contain control characters, format controls, "
            "or line separators"
        )
    return normalized


class FsrsCardState(FrozenModel):
    """The JSON-compatible fields required to rebuild one FSRS card."""

    card_id: StrictInt = Field(gt=0)
    state: StrictInt = Field(ge=1, le=3)
    step: StrictInt | None = Field(default=None, ge=0)
    stability: Annotated[
        StrictFloat | None,
        Field(default=None, gt=0, allow_inf_nan=False),
    ]
    difficulty: Annotated[
        StrictFloat | None,
        Field(default=None, gt=0, le=10, allow_inf_nan=False),
    ]
    due: datetime
    last_review: datetime | None = None

    @field_validator("due", "last_review", mode="before")
    @classmethod
    def validate_timestamp_input(cls, value: object) -> object:
        return _utc_timestamp(value)

    @field_validator("stability", "difficulty", mode="before")
    @classmethod
    def validate_float_input(cls, value: object) -> object:
        if value is None:
            return None
        return _finite_float(value)

    @model_validator(mode="after")
    def validate_fsrs_card(self) -> FsrsCardState:
        try:
            Card.from_dict(self.model_dump(mode="json", exclude_none=False))
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError("FSRS card data is invalid") from error
        try:
            State(self.state)
        except (TypeError, ValueError) as error:
            raise ValueError("FSRS card state is invalid") from error
        return self

    @classmethod
    def from_card(cls, card: Card) -> FsrsCardState:
        """Build validated file state from a library card."""

        try:
            return cls.model_validate(card.to_dict())
        except (TypeError, ValueError, ValidationError) as error:
            raise ValueError("FSRS card data is invalid") from error

    def to_card(self) -> Card:
        """Rebuild a library card after validating the complete state."""

        try:
            return Card.from_dict(self.model_dump(mode="json", exclude_none=False))
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError("FSRS card data is invalid") from error


class EntityState(FrozenModel):
    """Durable schedule and suspension metadata for one entity ID."""

    fsrs: FsrsCardState
    suspended: StrictBool = False
    suspension_reason: str | None = None
    last_seen_at: datetime | None = None

    @field_validator("suspension_reason", mode="before")
    @classmethod
    def validate_reason(cls, value: object) -> object:
        return _reason(value)

    @field_validator("last_seen_at", mode="before")
    @classmethod
    def validate_last_seen(cls, value: object) -> object:
        return _utc_timestamp(value)

    @model_validator(mode="after")
    def validate_suspension(self) -> EntityState:
        if not self.suspended and self.suspension_reason is not None:
            raise ValueError("a resumed entity cannot have a suspension reason")
        return self


class ReviewEvent(FrozenModel):
    """One immutable review event and its FSRS analytics values."""

    model_config = FrozenModel.model_config | ConfigDict(
        populate_by_name=True,
        serialize_by_alias=True,
    )

    review_id: StrictInt = Field(
        gt=0,
        validation_alias=AliasChoices("id", "review_id"),
        serialization_alias="id",
    )
    entity_id: EntityId
    card_id: StrictInt | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("card_id", "fsrs_card_id"),
        serialization_alias="card_id",
    )
    rating: Rating
    reviewed_at: datetime = Field(
        validation_alias=AliasChoices("reviewed_at", "review_datetime", "timestamp"),
        serialization_alias="reviewed_at",
    )
    duration: StrictInt | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("duration", "review_duration"),
        serialization_alias="duration",
    )
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
        if isinstance(value, Rating):
            return value
        if type(value) is not int:
            raise ValueError("rating must be an integer")
        return value

    @field_validator("reviewed_at", mode="before")
    @classmethod
    def validate_review_timestamp_input(cls, value: object) -> object:
        return _utc_timestamp(value)

    @field_validator(
        "previous_interval_seconds", "scheduled_interval_seconds", "retrievability", mode="before"
    )
    @classmethod
    def validate_analytics_number(cls, value: object) -> object:
        if value is None:
            return None
        return _finite_float(value)

    @field_validator("reviewed_at")
    @classmethod
    def normalize_review_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @property
    def review_duration(self) -> int | None:
        """Expose the FSRS name used by review views."""

        return self.duration


class SavedDeckSettings(FrozenModel):
    """Optional settings saved in the review-state object."""

    daily_limits: DailyLimits | None = None
    queue_settings: DeckSchedulingSettings | None = Field(
        default=None,
        validation_alias=AliasChoices("queue_settings", "scheduling"),
    )


class ReviewState(FrozenModel):
    """Versioned, strict review state embedded in one deck document."""

    version: Literal[1] = 1
    revision: StrictInt = Field(ge=1)
    entities: dict[EntityId, EntityState] = Field(default_factory=dict)
    reviews: tuple[ReviewEvent, ...] = ()
    settings: SavedDeckSettings | None = None

    @model_validator(mode="after")
    def validate_references_and_ids(self) -> ReviewState:
        review_ids = [event.review_id for event in self.reviews]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("review state contains duplicate review IDs")
        for entity_id, event in ((event.entity_id, event) for event in self.reviews):
            if entity_id not in self.entities:
                raise ValueError(f"review state references unknown entity {entity_id!r}")
            entity_state = self.entities[entity_id]
            if event.card_id is not None and event.card_id != entity_state.fsrs.card_id:
                raise ValueError(
                    f"review state review {event.review_id} has an invalid FSRS card ID"
                )
        return self

    def entity(self, entity_id: str) -> EntityState:
        """Return one entity state or raise a clear key error."""

        try:
            return self.entities[entity_id]
        except KeyError as error:
            raise KeyError(f"unknown review-state entity {entity_id!r}") from error


__all__ = [
    "EntityState",
    "FsrsCardState",
    "ReviewEvent",
    "ReviewState",
    "SavedDeckSettings",
]
