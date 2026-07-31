"""Immutable domain models for generated exercises and rendered views."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    model_validator,
)

from graphcards.references import EntityId


def validation_message(error: ValidationError) -> str:
    """Return the first Pydantic failure without implementation-specific decoration."""

    message = str(error.errors(include_url=False)[0]["msg"])
    return message.removeprefix("Value error, ")


class FrozenModel(BaseModel):
    """Immutable, strict base for configuration and domain models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


def resolve_config_path(value: object, info: ValidationInfo) -> Path:
    """Resolve a configured path relative to its TOML file."""

    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("must be a non-empty file path")
    try:
        path = Path(value).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ValueError(f"could not resolve path: {error}") from error
    context = info.context if isinstance(info.context, dict) else {}
    base = context.get("base")
    if not path.is_absolute() and isinstance(base, Path):
        path = base / path
    try:
        return path.resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ValueError(f"could not resolve path: {error}") from error


class CardKey(FrozenModel):
    """Stable persistence identity composed from deck and entity IDs."""

    deck_id: StrictStr
    entity_id: EntityId

    @model_validator(mode="after")
    def validate_identity(self) -> CardKey:
        if any(not value.strip() for value in (self.deck_id, self.entity_id)):
            raise ValueError("exercise identity parts must be non-blank strings")
        if any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            for value in self.identity_parts
            for character in value
        ):
            raise ValueError("exercise identity parts must not contain control characters")
        return self

    @classmethod
    def exercise(
        cls,
        deck_id: str,
        entity_id: str,
    ) -> CardKey:
        return cls(deck_id=deck_id, entity_id=entity_id)

    @property
    def identity_parts(self) -> tuple[str, ...]:
        return self.deck_id, self.entity_id


class Card(FrozenModel):
    """Validated semantic data for one regenerable exercise."""

    card_key: CardKey


class Exercise(FrozenModel):
    """Validated semantic exercise data produced by a deck generator."""

    card_key: CardKey
    generator_id: StrictStr = Field(min_length=1)
    target_id: EntityId

    @model_validator(mode="after")
    def validate_scope(self) -> Exercise:
        if self.card_key.entity_id != self.target_id:
            raise ValueError("exercise target ID does not match its card identity")
        return self


class CardView(FrozenModel):
    """Learner-facing strings produced by a stateless presentation renderer."""

    card_key: CardKey
    front: Annotated[str, StringConstraints(strip_whitespace=False)]
    back: Annotated[str, StringConstraints(strip_whitespace=False)]
