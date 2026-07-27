"""Immutable domain models for generated exercises and rendered views."""

from __future__ import annotations

import unicodedata
from hashlib import sha256
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
    path = Path(value).expanduser()
    context = info.context if isinstance(info.context, dict) else {}
    base = context.get("base")
    if not path.is_absolute() and isinstance(base, Path):
        path = base / path
    try:
        return path.resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError(f"could not resolve path: {error}") from error


class CardKey(FrozenModel):
    """Stable persistence identity composed from deck, generator, and entity IDs."""

    deck_id: StrictStr
    generator_id: StrictStr
    entity_id: StrictStr

    @model_validator(mode="after")
    def validate_identity(self) -> CardKey:
        if any(not value.strip() for value in (self.deck_id, self.generator_id, self.entity_id)):
            raise ValueError("exercise identity parts must be non-blank strings")
        if any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            for value in self.identity_parts
            for character in value
        ):
            raise ValueError("exercise identity parts must not contain control characters")
        return self

    @classmethod
    def exercise(cls, deck_id: str, generator_id: str, entity_id: str) -> CardKey:
        return cls(deck_id=deck_id, generator_id=generator_id, entity_id=entity_id)

    @property
    def identity_parts(self) -> tuple[str, str, str]:
        return self.deck_id, self.generator_id, self.entity_id

    @property
    def digest(self) -> str:
        digest = sha256(b"graphcards:exercise:v1\0")
        for value in self.identity_parts:
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()


class Card(FrozenModel):
    """Validated semantic data for one regenerable exercise."""

    card_key: CardKey


class Exercise(FrozenModel):
    """Validated semantic exercise data produced by a deck generator."""

    card_key: CardKey
    generator_id: StrictStr = Field(min_length=1)
    target_id: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scope(self) -> Exercise:
        if self.card_key.generator_id != self.generator_id:
            raise ValueError("exercise generator ID does not match its card identity")
        if self.card_key.entity_id != self.target_id:
            raise ValueError("exercise target ID does not match its card identity")
        return self


class CardView(FrozenModel):
    """Learner-facing strings produced by a stateless presentation renderer."""

    card_key: CardKey
    front: Annotated[str, StringConstraints(strip_whitespace=False)]
    back: Annotated[str, StringConstraints(strip_whitespace=False)]
