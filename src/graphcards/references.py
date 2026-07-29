"""Shared validated types for references to deck entities."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Annotated

from pydantic import AfterValidator, StrictStr


def validate_entity_id(value: object) -> str:
    """Validate one strict, non-blank entity ID."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-blank string")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value
    ):
        raise ValueError("must not contain control characters")
    return value


EntityId = Annotated[StrictStr, AfterValidator(validate_entity_id)]


@dataclass(frozen=True, slots=True)
class EntityIdListMarker:
    """Annotation metadata marking a list position eligible for group aliases."""


EntityIdList = Annotated[tuple[EntityId, ...], EntityIdListMarker()]


__all__ = ["EntityId", "EntityIdList", "EntityIdListMarker", "validate_entity_id"]
