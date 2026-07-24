"""Shared deck-definition execution and presentation models."""

from __future__ import annotations

import random
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from inspect import isabstract
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import ConfigDict, Field, ValidationInfo, field_validator
from rdflib import Graph, Literal
from rdflib.namespace import XSD
from rdflib.term import Identifier

from graphcards.errors import PresentationError
from graphcards.models import CardKey, FrozenModel, RdfModel, TargetKind, resolve_config_path

DEFAULT_MAX_CHOICES = 4
DEFAULT_WINDOW_SIZE = 5

IDENTITY_VARIABLES = {
    TargetKind.TRIPLE: {"subject", "predicate", "object"},
    TargetKind.ENTITY: {"entity"},
}


class Presentation(RdfModel):
    """One generated learner-facing card presentation."""

    card_key: CardKey
    front: Identifier
    back: Identifier

    def front_text(self, rng: random.Random) -> str:
        """Format the front; presentations may use RNG for display-only variation."""

        del rng
        return str(self.front)


class DeckDefinition(FrozenModel, ABC):
    """Configured deck behavior selected by a stable TOML kind name."""

    model_config = FrozenModel.model_config | ConfigDict(
        validate_by_alias=True,
        validate_by_name=True,
    )

    config_name: ClassVar[str]
    required_variables: ClassVar[frozenset[str]]
    uses_card_bindings: ClassVar[bool] = True
    exact_projection: ClassVar[tuple[str, ...] | None] = None
    _registry: ClassVar[dict[str, type[DeckDefinition]]] = {}

    name: Annotated[str, Field(min_length=1)]
    target: TargetKind
    query_path: Path = Field(validation_alias="query")

    @field_validator("query_path", mode="before")
    @classmethod
    def resolve_query_path(cls, value: object, info: ValidationInfo) -> Path:
        return resolve_config_path(value, info)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Register concrete definitions that declare a configuration name."""

        super().__pydantic_init_subclass__(**kwargs)
        if "config_name" not in cls.__dict__ or isabstract(cls):
            return
        cls.validate_definition_class(cls)
        existing = cls._registry.get(cls.config_name)
        if existing is not None and existing is not cls:
            raise TypeError(
                f"deck kind name {cls.config_name!r} is already registered by {existing.__name__}"
            )
        cls._registry[cls.config_name] = cls

    @classmethod
    def validate_definition_class(cls, definition: object) -> type[DeckDefinition]:
        """Validate a programmatically supplied definition class."""

        if not isinstance(definition, type) or not issubclass(definition, cls):
            raise ValueError("deck definition must be a DeckDefinition subclass")
        if isabstract(definition):
            raise ValueError("deck definition must be concrete")
        config_name = getattr(definition, "config_name", None)
        if not isinstance(config_name, str) or not config_name:
            raise ValueError("deck definition must define a non-empty config_name")
        required = getattr(definition, "required_variables", None)
        if (
            not isinstance(required, frozenset)
            or not required
            or not all(isinstance(variable, str) and variable for variable in required)
        ):
            raise ValueError("deck definition must define required_variables as non-empty strings")
        return definition

    @classmethod
    def from_name(cls, name: str) -> type[DeckDefinition]:
        """Resolve the registered definition for a stable TOML kind name."""

        try:
            return cls._registry[name]
        except KeyError as error:
            available = ", ".join(repr(value) for value in sorted(cls._registry))
            raise ValueError(f"kind must be {available}") from error

    @classmethod
    def from_config(
        cls,
        value: object,
        *,
        context: dict[str, object] | None = None,
    ) -> DeckDefinition:
        """Dispatch one raw TOML deck table to its registered definition."""

        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("each deck must be a table")
        raw_kind = value.get("kind")
        if not isinstance(raw_kind, str):
            raise ValueError("deck kind must be a string")
        definition = cls.from_name(raw_kind.strip())
        data = dict(value)
        del data["kind"]
        return definition.model_validate(data, context=context)

    def _read_query(self) -> str:
        try:
            return self.query_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise PresentationError(
                f"query file for deck {self.name!r} not found: {self.query_path}"
            ) from error
        except OSError as error:
            raise PresentationError(
                f"could not read query file for deck {self.name!r}: {error}"
            ) from error

    def execute_presentations(
        self,
        graph: Graph,
        card_key: CardKey | None = None,
    ) -> dict[str, Presentation]:
        """Run this deck's query and build current presentations."""

        if card_key is not None and card_key.target_kind != self.target:
            raise PresentationError(
                f"deck {self.name!r} targets {self.target} cards but received a "
                f"{card_key.target_kind} card"
            )
        bindings = (
            card_key.query_bindings if card_key is not None and self.uses_card_bindings else None
        )
        try:
            result = graph.query(self._read_query(), initBindings=bindings)
        except Exception as error:
            raise PresentationError(
                f"SPARQL query for deck {self.name!r} failed: {error}"
            ) from error
        if result.type != "SELECT":
            raise PresentationError(f"deck {self.name!r} must use a SELECT query")

        expected = IDENTITY_VARIABLES[self.target] | self.required_variables
        selected = {str(variable) for variable in result.vars or ()}
        if self.exact_projection is not None and selected != set(self.exact_projection):
            variables = ", ".join(f"?{name}" for name in self.exact_projection[:-1])
            variables += f", and ?{self.exact_projection[-1]}"
            label = self.config_name.replace("_", "-")
            raise PresentationError(
                f"deck {self.name!r} {label} queries must SELECT exactly {variables}"
            )
        missing = sorted(expected - selected)
        if missing:
            joined = ", ".join(f"?{name}" for name in missing)
            raise PresentationError(
                f"deck {self.name!r} does not SELECT required variables: {joined}"
            )

        presentations = self.group(result, expected=expected, card_key=card_key)
        if card_key is not None:
            unexpected = [
                item.card_key for item in presentations.values() if item.card_key != card_key
            ]
            if unexpected:
                raise PresentationError(
                    f"deck {self.name!r} ignored the supplied card bindings while rendering"
                )
        return presentations

    @abstractmethod
    def group(
        self,
        result: object,
        *,
        expected: set[str],
        card_key: CardKey | None = None,
    ) -> dict[str, Presentation]:
        """Convert validated SPARQL rows into presentations keyed by card ID."""

    @staticmethod
    def _row_values(row: object) -> dict[str, Identifier]:
        return {str(key): value for key, value in row.asdict().items()}  # type: ignore[attr-defined]

    def _require_bound(
        self,
        values: dict[str, Identifier],
        expected: set[str],
        row_number: int,
    ) -> None:
        missing = sorted(name for name in expected if values.get(name) is None)
        if missing:
            joined = ", ".join(f"?{name}" for name in missing)
            raise PresentationError(
                f"deck {self.name!r} row {row_number} has unbound required variables: {joined}"
            )

    def _card_key(self, values: dict[str, Identifier], row_number: int) -> CardKey:
        try:
            return CardKey.from_bindings(self.target, values)
        except PresentationError as error:
            raise PresentationError(f"deck {self.name!r} row {row_number}: {error}") from error

    def _rdf_integer(
        self,
        value: Identifier,
        *,
        variable: str,
        minimum: int,
        minimum_description: str,
        row_number: int,
    ) -> int:
        """Validate an RDF integer without accepting RDFLib coercions."""

        if not isinstance(value, Literal) or value.datatype != XSD.integer:
            raise PresentationError(
                f"deck {self.name!r} row {row_number} ?{variable} must be an xsd:integer literal"
            )
        if re.fullmatch(r"[+-]?[0-9]+", str(value)) is None:
            raise PresentationError(
                f"deck {self.name!r} row {row_number} has an invalid xsd:integer "
                f"lexical value for ?{variable}"
            )
        converted = value.toPython()
        if isinstance(converted, bool) or not isinstance(converted, int):
            raise PresentationError(
                f"deck {self.name!r} row {row_number} has an invalid xsd:integer "
                f"value for ?{variable}"
            )
        if converted < minimum:
            raise PresentationError(
                f"deck {self.name!r} row {row_number} ?{variable} must be {minimum_description}"
            )
        return converted

    @staticmethod
    def _by_digest(presentations: list[Presentation]) -> dict[str, Presentation]:
        # Comparing identities as well as hashes prevents a collision from
        # silently merging two distinct RDF cards.
        by_digest: dict[str, Presentation] = {}
        for presentation in presentations:
            card_id = presentation.card_key.digest
            existing = by_digest.get(card_id)
            if existing is not None and existing.card_key != presentation.card_key:
                raise PresentationError("SHA-256 collision between two different card identities")
            by_digest[card_id] = presentation
        return by_digest
