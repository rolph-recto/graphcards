"""Polymorphic deck kinds that own presentation grouping and front formatting."""

from __future__ import annotations

import random
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from inspect import isabstract
from typing import Annotated, ClassVar, Self

from pydantic import Field, ValidationError, model_validator
from rdflib import Literal
from rdflib.namespace import XSD
from rdflib.term import Identifier

from rdfcards.errors import PresentationError
from rdfcards.models import CardKey, RdfModel, TargetKind

DEFAULT_MAX_CHOICES = 4


class DeckKind(RdfModel, ABC):
    """A generated front/back presentation with kind-specific query behavior."""

    config_name: ClassVar[str]
    required_variables: ClassVar[frozenset[str]]
    _registry: ClassVar[dict[str, type[DeckKind]]] = {}

    card_key: CardKey
    front: Identifier
    back: Identifier

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Register concrete kinds that explicitly declare a configuration name."""

        super().__pydantic_init_subclass__(**kwargs)
        if "config_name" not in cls.__dict__ or isabstract(cls):
            return
        cls.validate_kind_class(cls)
        existing = cls._registry.get(cls.config_name)
        if existing is not None and existing is not cls:
            raise TypeError(
                f"deck kind name {cls.config_name!r} is already registered by {existing.__name__}"
            )
        cls._registry[cls.config_name] = cls

    @classmethod
    def validate_kind_class(cls, kind: object) -> type[DeckKind]:
        """Validate a programmatically supplied kind before a deck can use it."""

        if not isinstance(kind, type) or not issubclass(kind, cls):
            raise ValueError("kind must be a DeckKind subclass")
        if isabstract(kind):
            raise ValueError("kind must be a concrete DeckKind subclass")
        config_name = getattr(kind, "config_name", None)
        if not isinstance(config_name, str) or not config_name:
            raise ValueError("kind must define a non-empty config_name")
        required = getattr(kind, "required_variables", None)
        if (
            not isinstance(required, frozenset)
            or not required
            or not all(isinstance(variable, str) and variable for variable in required)
        ):
            raise ValueError("kind must define required_variables as non-empty strings")
        return kind

    @classmethod
    def from_name(cls, name: str) -> type[DeckKind]:
        """Resolve the stable TOML name for a concrete deck kind."""

        try:
            kind = cls._registry[name]
            if not issubclass(kind, cls):
                raise KeyError(name)
            return kind
        except KeyError as error:
            available = ", ".join(
                repr(value)
                for value, kind in sorted(cls._registry.items())
                if issubclass(kind, cls)
            )
            raise ValueError(f"kind must be {available}") from error

    @classmethod
    @abstractmethod
    def group(
        cls,
        result: object,
        *,
        target: TargetKind,
        deck_name: str,
        expected: set[str],
        max_choices: int | None,
    ) -> dict[str, Self]:
        """Convert validated SPARQL rows into presentations keyed by card ID."""

    def front_text(self, rng: random.Random) -> str:
        """Format the front; kinds may use the RNG for presentation-only variation."""

        del rng
        return str(self.front)

    @staticmethod
    def _row_values(row: object) -> dict[str, Identifier]:
        return {str(key): value for key, value in row.asdict().items()}  # type: ignore[attr-defined]

    @staticmethod
    def _require_bound(
        values: dict[str, Identifier],
        expected: set[str],
        deck_name: str,
        row_number: int,
    ) -> None:
        missing = sorted(name for name in expected if values.get(name) is None)
        if missing:
            joined = ", ".join(f"?{name}" for name in missing)
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} has unbound required variables: {joined}"
            )

    @staticmethod
    def _card_key(
        values: dict[str, Identifier],
        target: TargetKind,
        deck_name: str,
        row_number: int,
    ) -> CardKey:
        try:
            return CardKey.from_bindings(target, values)
        except PresentationError as error:
            raise PresentationError(f"deck {deck_name!r} row {row_number}: {error}") from error

    @classmethod
    def _by_digest(cls, presentations: list[Self]) -> dict[str, Self]:
        # Comparing identities as well as hashes prevents a collision from
        # silently merging two distinct RDF cards.
        by_digest: dict[str, Self] = {}
        for presentation in presentations:
            card_id = presentation.card_key.digest
            existing = by_digest.get(card_id)
            if existing is not None and existing.card_key != presentation.card_key:
                raise PresentationError("SHA-256 collision between two different card identities")
            by_digest[card_id] = presentation
        return by_digest


class Basic(DeckKind):
    """A front/back presentation that the student rates manually."""

    config_name = "basic"
    required_variables = frozenset({"front", "back"})

    @classmethod
    def group(
        cls,
        result: object,
        *,
        target: TargetKind,
        deck_name: str,
        expected: set[str],
        max_choices: int | None,
    ) -> dict[str, Self]:
        del max_choices
        # Identical duplicate rows are harmless, but differing presentations
        # for one identity are ambiguous.
        grouped: dict[CardKey, set[tuple[Identifier, Identifier]]] = defaultdict(set)
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = cls._row_values(row)
            cls._require_bound(values, expected, deck_name, row_number)
            card_key = cls._card_key(values, target, deck_name, row_number)
            grouped[card_key].add((values["front"], values["back"]))

        presentations: list[Self] = []
        for card_key, pairs in grouped.items():
            if len(pairs) != 1:
                raise PresentationError(
                    f"deck {deck_name!r} returns conflicting front/back values for card "
                    f"{card_key.digest}"
                )
            front, back = next(iter(pairs))
            presentations.append(cls(card_key=card_key, front=front, back=back))
        return cls._by_digest(presentations)


class ChoiceOption(RdfModel):
    """One candidate answer and its normalized distractor-selection priority."""

    choice: Identifier
    priority: Annotated[int, Field(strict=True, ge=0)] = 0


class MultipleChoice(DeckKind):
    """A self-rated presentation with shuffled choices and a correct back."""

    config_name = "multiple_choice"
    required_variables = frozenset({"front", "choice", "is_correct"})

    choices: tuple[ChoiceOption, ...]
    max_choices: Annotated[int, Field(strict=True, ge=2)] = DEFAULT_MAX_CHOICES

    @model_validator(mode="after")
    def validate_choices(self) -> MultipleChoice:
        """Keep directly constructed presentations as valid as query-built ones."""

        if len(self.choices) < 2:
            raise ValueError("a multiple-choice presentation needs at least two choices")
        choice_values = tuple(option.choice for option in self.choices)
        if len(set(choice_values)) != len(choice_values):
            raise ValueError("a multiple-choice presentation cannot contain duplicate choices")
        if self.back not in choice_values:
            raise ValueError("the multiple-choice back must be one of its choices")
        return self

    @staticmethod
    def _boolean(value: Identifier, deck_name: str, row_number: int) -> bool:
        # RDFLib may coerce malformed lexical forms, so inspect the RDF literal
        # before accepting its converted Python value.
        if not isinstance(value, Literal) or value.datatype != XSD.boolean:
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} ?is_correct must be an xsd:boolean literal"
            )
        if str(value) not in {"true", "false", "1", "0"}:
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} has an invalid xsd:boolean lexical value"
            )
        converted = value.toPython()
        if not isinstance(converted, bool):
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} has an invalid xsd:boolean value"
            )
        return converted

    @staticmethod
    def _priority(value: Identifier | None, deck_name: str, row_number: int) -> int:
        if value is None:
            return 0
        if not isinstance(value, Literal) or value.datatype != XSD.integer:
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} ?priority must be an xsd:integer literal"
            )
        if re.fullmatch(r"[+-]?[0-9]+", str(value)) is None:
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} has an invalid xsd:integer "
                "lexical value for ?priority"
            )
        converted = value.toPython()
        if isinstance(converted, bool) or not isinstance(converted, int):
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} has an invalid xsd:integer "
                "value for ?priority"
            )
        if converted < 0:
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} ?priority must be zero or greater"
            )
        return converted

    @classmethod
    def group(
        cls,
        result: object,
        *,
        target: TargetKind,
        deck_name: str,
        expected: set[str],
        max_choices: int | None,
    ) -> dict[str, Self]:
        fronts: dict[CardKey, set[Identifier]] = defaultdict(set)
        choices: dict[CardKey, dict[Identifier, tuple[bool, int]]] = defaultdict(dict)
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = cls._row_values(row)
            cls._require_bound(values, expected, deck_name, row_number)
            card_key = cls._card_key(values, target, deck_name, row_number)
            fronts[card_key].add(values["front"])
            choice = values["choice"]
            is_correct = cls._boolean(values["is_correct"], deck_name, row_number)
            priority = cls._priority(values.get("priority"), deck_name, row_number)
            existing = choices[card_key].get(choice)
            if existing is not None:
                existing_correct, existing_priority = existing
                if existing_correct != is_correct:
                    raise PresentationError(
                        f"deck {deck_name!r} marks the same choice both correct and incorrect "
                        f"for card {card_key.digest}"
                    )
                if existing_priority != priority:
                    raise PresentationError(
                        f"deck {deck_name!r} assigns conflicting priorities to the same choice "
                        f"for card {card_key.digest}"
                    )
            choices[card_key][choice] = (is_correct, priority)

        presentations: list[Self] = []
        for card_key, front_values in fronts.items():
            if len(front_values) != 1:
                raise PresentationError(
                    f"deck {deck_name!r} returns conflicting fronts for card {card_key.digest}"
                )
            card_choices = choices[card_key]
            if len(card_choices) < 2:
                raise PresentationError(
                    f"deck {deck_name!r} needs at least two choices for card {card_key.digest}"
                )
            if sum(is_correct for is_correct, _priority in card_choices.values()) != 1:
                raise PresentationError(
                    f"deck {deck_name!r} needs exactly one correct choice for card "
                    f"{card_key.digest}"
                )
            try:
                presentations.append(
                    cls(
                        card_key=card_key,
                        front=next(iter(front_values)),
                        back=next(
                            value
                            for value, (is_correct, _priority) in card_choices.items()
                            if is_correct
                        ),
                        choices=tuple(
                            ChoiceOption(choice=value, priority=priority)
                            for value, (_is_correct, priority) in card_choices.items()
                        ),
                        max_choices=(
                            max_choices if max_choices is not None else DEFAULT_MAX_CHOICES
                        ),
                    )
                )
            except ValidationError as error:
                message = str(error.errors(include_url=False)[0]["msg"])
                raise PresentationError(
                    f"deck {deck_name!r} has an invalid multiple-choice presentation "
                    f"for card {card_key.digest}: {message.removeprefix('Value error, ')}"
                ) from error
        return cls._by_digest(presentations)

    def _selected_distractors(self, rng: random.Random) -> list[Identifier]:
        """Randomize each priority tier before retaining distractors."""

        tiers: dict[int, list[Identifier]] = defaultdict(list)
        for option in self.choices:
            if option.choice != self.back:
                tiers[option.priority].append(option.choice)

        remaining = self.max_choices - 1
        distractors: list[Identifier] = []
        for priority in sorted(tiers, reverse=True):
            tier = sorted(tiers[priority], key=lambda choice: choice.n3())
            rng.shuffle(tier)
            retained = tier[:remaining]
            distractors.extend(retained)
            remaining -= len(retained)
            if remaining == 0:
                break
        return distractors

    def selected_choices(self, rng: random.Random) -> tuple[Identifier, ...]:
        """Select prioritized distractors, then shuffle all retained choices."""

        selected = [self.back, *self._selected_distractors(rng)]
        rng.shuffle(selected)
        return tuple(selected)

    def front_text(self, rng: random.Random) -> str:
        lines = [str(self.front)]
        lines.extend(
            f"  {index}. {choice}"
            for index, choice in enumerate(self.selected_choices(rng), start=1)
        )
        return "\n".join(lines)
