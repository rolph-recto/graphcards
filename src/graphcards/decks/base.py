"""Shared configured card-generation and rendering definitions."""

from __future__ import annotations

import random
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from functools import lru_cache
from inspect import isabstract
from pathlib import Path
from typing import Annotated, ClassVar

from jinja2 import Environment, StrictUndefined, Template
from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)
from rdflib import Graph, Literal
from rdflib.namespace import XSD
from rdflib.term import Identifier

from graphcards.errors import PresentationError
from graphcards.models import (
    Card,
    CardKey,
    CardView,
    FrozenModel,
    TargetKind,
    resolve_config_path,
)

DEFAULT_MAX_CHOICES = 4
DEFAULT_WINDOW_SIZE = 5

IDENTITY_VARIABLES = {
    TargetKind.TRIPLE: {"subject", "predicate", "object"},
    TargetKind.ENTITY: {"entity"},
}


_TEMPLATE_ENVIRONMENT = Environment(
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
    undefined=StrictUndefined,
)


@lru_cache
def _template(source: str) -> Template:
    return _TEMPLATE_ENVIRONMENT.from_string(source)


def _validate_template_source(source: str) -> str:
    if not source.strip():
        raise ValueError("must be a non-blank Jinja template")
    try:
        _template(source)
    except Exception as error:
        raise ValueError(f"must be a valid Jinja template: {error}") from error
    return source


TemplateSource = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False),
    AfterValidator(_validate_template_source),
]


class DeckDefinition(FrozenModel, ABC):
    """Configured deck behavior selected by a stable TOML kind name."""

    model_config = FrozenModel.model_config | ConfigDict(
        validate_by_alias=True,
        validate_by_name=True,
    )

    config_name: ClassVar[str]
    required_variables: ClassVar[frozenset[str]]
    card_type: ClassVar[type[Card]]
    uses_card_bindings: ClassVar[bool] = True
    exact_projection: ClassVar[tuple[str, ...] | None] = None
    _registry: ClassVar[dict[str, type[DeckDefinition]]] = {}

    name: Annotated[str, Field(min_length=1)]
    target: TargetKind
    query_path: Path = Field(validation_alias="query")
    front_template: TemplateSource
    back_template: TemplateSource

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
        card_type = getattr(definition, "card_type", None)
        if not isinstance(card_type, type) or not issubclass(card_type, Card):
            raise ValueError("deck definition must define a Card subclass as card_type")
        for name in ("front_template", "back_template"):
            field = definition.model_fields.get(name)
            contract = DeckDefinition.model_fields[name]
            if (
                field is None
                or field.annotation != contract.annotation
                or field.metadata != contract.metadata
            ):
                raise ValueError(
                    f"deck definition must declare {name} with the TemplateSource type"
                )
            if not field.is_required() and field.default_factory is None:
                try:
                    if not isinstance(field.default, str):
                        raise ValueError("must be a string")
                    _validate_template_source(field.default)
                except ValueError as error:
                    raise ValueError(
                        f"deck definition has an invalid {name} default: {error}"
                    ) from error
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

    def execute_cards(
        self,
        graph: Graph,
        card_key: CardKey | None = None,
        *,
        rng: random.Random,
    ) -> dict[str, Card]:
        """Run this deck's query and generate current semantic cards."""

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

        cards = self.group(result, expected=expected, card_key=card_key, rng=rng)
        if card_key is not None:
            unexpected = [item.card_key for item in cards.values() if item.card_key != card_key]
            if unexpected:
                raise PresentationError(
                    f"deck {self.name!r} ignored the supplied card bindings while generating"
                )
        return cards

    def render_context(self, card: Card) -> Mapping[str, object]:
        """Return the curated semantic data exposed to this deck's templates."""

        return card.model_dump(exclude={"card_key"})

    def render(self, card: Card) -> CardView:
        """Render one compatible semantic card through this configured deck."""

        if not isinstance(card, self.card_type):
            raise PresentationError(
                f"deck {self.name!r} renders {self.card_type.__name__}, not {type(card).__name__}"
            )
        try:
            context = self.render_context(card)
            front = _template(self.front_template).render(**context)
            back = _template(self.back_template).render(**context)
        except PresentationError:
            raise
        except Exception as error:
            raise PresentationError(
                f"deck {self.name!r} could not render its card: {error}"
            ) from error
        return CardView(card_key=card.card_key, front=front, back=back)

    @abstractmethod
    def group(
        self,
        result: object,
        *,
        expected: set[str],
        card_key: CardKey | None = None,
        rng: random.Random,
    ) -> dict[str, Card]:
        """Convert validated SPARQL rows into semantic cards keyed by card ID."""

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
    def _by_digest(cards: list[Card]) -> dict[str, Card]:
        # Comparing identities as well as hashes prevents a collision from
        # silently merging two distinct RDF cards.
        by_digest: dict[str, Card] = {}
        for card in cards:
            card_id = card.card_key.digest
            existing = by_digest.get(card_id)
            if existing is not None and existing.card_key != card.card_key:
                raise PresentationError("SHA-256 collision between two different card identities")
            by_digest[card_id] = card
        return by_digest
