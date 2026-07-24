"""Polymorphic deck kinds that own presentation grouping and front formatting."""

from __future__ import annotations

import random
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from inspect import isabstract
from typing import Annotated, ClassVar, Self

from pydantic import Field, ValidationError, field_validator, model_validator
from rdflib import Literal, URIRef
from rdflib.namespace import XSD
from rdflib.term import Identifier

from rdfcards.errors import PresentationError
from rdfcards.models import CardKey, RdfModel, TargetKind

DEFAULT_MAX_CHOICES = 4
DEFAULT_WINDOW_SIZE = 5


def _validation_message(error: ValidationError) -> str:
    message = str(error.errors(include_url=False)[0]["msg"])
    return message.removeprefix("Value error, ")


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


class Analogy(DeckKind):
    """A relational analogy that hides one term of a target triple."""

    config_name = "analogy"
    required_variables = frozenset({"source_subject", "source_predicate", "source_object", "hide"})

    source_subject: Identifier
    source_predicate: Identifier
    source_object: Identifier
    hide: Identifier
    subject_label: Identifier | None = None
    predicate_label: Identifier | None = None
    object_label: Identifier | None = None
    source_subject_label: Identifier | None = None
    source_predicate_label: Identifier | None = None
    source_object_label: Identifier | None = None

    @field_validator("hide", mode="after")
    @classmethod
    def normalize_hide(cls, value: Identifier) -> Literal:
        if (
            not isinstance(value, Literal)
            or value.language is not None
            or value.datatype not in (None, XSD.string)
            or str(value) not in {"subject", "object"}
        ):
            raise ValueError("?hide must be a literal with value subject or object")
        return Literal(str(value))

    @model_validator(mode="after")
    def validate_analogy(self) -> Analogy:
        """Keep the source relationship and hidden-answer contract explicit."""

        if self.card_key.target_kind is not TargetKind.TRIPLE:
            raise ValueError("an analogy presentation must use a triple card identity")
        subject, predicate, object_ = self.card_key.terms
        if self.source_predicate != predicate:
            raise ValueError("the source and target predicates must match")
        if (self.source_subject, self.source_predicate, self.source_object) == (
            subject,
            predicate,
            object_,
        ):
            raise ValueError("the source triple must be distinct from the target triple")
        if (
            not isinstance(self.hide, Literal)
            or self.hide.language is not None
            or self.hide.datatype not in (None, XSD.string)
            or str(self.hide) not in {"subject", "object"}
        ):
            raise ValueError("?hide must be a literal with value subject or object")
        expected_front, expected_back = self._front_and_back(
            target_subject=subject,
            target_predicate=predicate,
            target_object=object_,
            source_subject=self.source_subject,
            source_predicate=self.source_predicate,
            source_object=self.source_object,
            hide=self.hide,
            subject_label=self.subject_label,
            predicate_label=self.predicate_label,
            object_label=self.object_label,
            source_subject_label=self.source_subject_label,
            source_predicate_label=self.source_predicate_label,
            source_object_label=self.source_object_label,
        )
        if self.front != expected_front:
            raise ValueError("the analogy front does not match its target and source terms")
        if self.back != expected_back:
            raise ValueError("the analogy back does not match its hidden target term")
        return self

    @staticmethod
    def _text(term: Identifier, label: Identifier | None) -> str:
        return str(label if label is not None else term)

    @classmethod
    def _side_text(
        cls,
        subject: Identifier,
        predicate: Identifier,
        object_: Identifier,
        *,
        subject_label: Identifier | None,
        predicate_label: Identifier | None,
        object_label: Identifier | None,
        hidden: str | None = None,
    ) -> str:
        # A colon is the compact relation marker used in the approved examples.
        # When a predicate label is supplied, it makes the relationship explicit.
        relation = str(predicate_label) if predicate_label is not None else ":"
        rendered_object = "?" if hidden == "object" else cls._text(object_, object_label)
        rendered_subject = "?" if hidden == "subject" else cls._text(subject, subject_label)
        return f"{rendered_subject} {relation} {rendered_object}"

    @classmethod
    def _front_and_back(
        cls,
        *,
        target_subject: Identifier,
        target_predicate: Identifier,
        target_object: Identifier,
        source_subject: Identifier,
        source_predicate: Identifier,
        source_object: Identifier,
        hide: Literal,
        subject_label: Identifier | None,
        predicate_label: Identifier | None,
        object_label: Identifier | None,
        source_subject_label: Identifier | None,
        source_predicate_label: Identifier | None,
        source_object_label: Identifier | None,
    ) -> tuple[Literal, Identifier]:
        hide_mode = str(hide)
        relation_label = predicate_label if predicate_label is not None else source_predicate_label
        source_text = cls._side_text(
            source_subject,
            source_predicate,
            source_object,
            subject_label=source_subject_label,
            predicate_label=relation_label,
            object_label=source_object_label,
        )
        target_text = cls._side_text(
            target_subject,
            target_predicate,
            target_object,
            subject_label=subject_label,
            predicate_label=relation_label,
            object_label=object_label,
            hidden=hide_mode,
        )
        answer = subject_label if hide_mode == "subject" and subject_label is not None else None
        if answer is None and hide_mode == "object" and object_label is not None:
            answer = object_label
        if answer is None:
            answer = target_subject if hide_mode == "subject" else target_object
        return Literal(f"{source_text} :: {target_text}"), answer

    def _duplicate_key(self) -> tuple[object, ...]:
        """Return source terms plus the effective learner-facing metadata."""

        target_subject, _target_predicate, target_object = self.card_key.terms
        relation_label = (
            self.predicate_label
            if self.predicate_label is not None
            else self.source_predicate_label
        )
        return (
            self.source_subject,
            self.source_predicate,
            self.source_object,
            str(self.hide),
            self._text(target_subject, self.subject_label),
            str(relation_label) if relation_label is not None else ":",
            self._text(target_object, self.object_label),
            self._text(self.source_subject, self.source_subject_label),
            self._text(self.source_object, self.source_object_label),
        )

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
        if target is not TargetKind.TRIPLE:
            raise PresentationError(f"deck {deck_name!r} analogy decks must target triple cards")

        grouped: dict[CardKey, dict[tuple[object, ...], Analogy]] = defaultdict(dict)
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = cls._row_values(row)
            cls._require_bound(values, expected, deck_name, row_number)
            card_key = cls._card_key(values, target, deck_name, row_number)
            target_subject, target_predicate, target_object = card_key.terms
            labels = {
                name: values.get(name)
                for name in (
                    "subject_label",
                    "predicate_label",
                    "object_label",
                    "source_subject_label",
                    "source_predicate_label",
                    "source_object_label",
                )
            }
            try:
                front, back = cls._front_and_back(
                    target_subject=target_subject,
                    target_predicate=target_predicate,
                    target_object=target_object,
                    source_subject=values["source_subject"],
                    source_predicate=values["source_predicate"],
                    source_object=values["source_object"],
                    hide=values["hide"],
                    **labels,
                )
                presentation = cls(
                    card_key=card_key,
                    front=front,
                    back=back,
                    source_subject=values["source_subject"],
                    source_predicate=values["source_predicate"],
                    source_object=values["source_object"],
                    hide=values["hide"],
                    **labels,
                )
            except (ValidationError, ValueError) as error:
                if isinstance(error, ValidationError):
                    message = _validation_message(error)
                else:
                    message = str(error)
                raise PresentationError(
                    f"deck {deck_name!r} row {row_number}: {message}"
                ) from error
            grouped[card_key][presentation._duplicate_key()] = presentation

        presentations: list[Self] = []
        for card_key, values in grouped.items():
            if len(values) != 1:
                raise PresentationError(
                    f"deck {deck_name!r} returns conflicting analogy source, hide mode, or "
                    f"display labels for card {card_key.digest}"
                )
            presentations.append(next(iter(values.values())))
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


class OrderedListRow(RdfModel):
    """One validated row in an ordered-list query result."""

    entity: URIRef
    group: Identifier
    position: Annotated[int, Field(strict=True, ge=1)]
    label: Identifier


class OrderedListCompletion(DeckKind):
    """An entity card that hides one member of a non-cyclic ordered list."""

    config_name = "ordered_list"
    required_variables = frozenset({"group", "position", "label"})

    @staticmethod
    def _position(value: Identifier, deck_name: str, row_number: int) -> int:
        """Validate an RDF integer without accepting RDFLib coercions."""

        if not isinstance(value, Literal) or value.datatype != XSD.integer:
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} ?position must be an xsd:integer literal"
            )
        if re.fullmatch(r"[+-]?[0-9]+", str(value)) is None:
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} has an invalid xsd:integer lexical value "
                "for ?position"
            )
        converted = value.toPython()
        if isinstance(converted, bool) or not isinstance(converted, int):
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} has an invalid xsd:integer value "
                "for ?position"
            )
        if converted < 1:
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} ?position must be at least 1"
            )
        return converted

    @classmethod
    def _row(
        cls,
        values: dict[str, Identifier],
        *,
        deck_name: str,
        row_number: int,
    ) -> OrderedListRow:
        try:
            return OrderedListRow(
                entity=values["entity"],
                group=values["group"],
                position=cls._position(values["position"], deck_name, row_number),
                label=values["label"],
            )
        except PresentationError:
            raise
        except ValidationError as error:
            message = str(error.errors(include_url=False)[0]["msg"])
            raise PresentationError(
                f"deck {deck_name!r} row {row_number} has an invalid ordered-list row: "
                f"{message.removeprefix('Value error, ')}"
            ) from error

    @staticmethod
    def _window(rows: list[OrderedListRow], target: OrderedListRow, window_size: int) -> str:
        """Return a bounded, contiguous numbered window around ``target``."""

        if window_size == 0 or window_size >= len(rows):
            visible = rows
            omitted_before = omitted_after = False
        else:
            target_index = target.position - 1
            start = max(0, target_index - window_size // 2)
            start = min(start, len(rows) - window_size)
            end = start + window_size
            visible = rows[start:end]
            omitted_before = start > 0
            omitted_after = end < len(rows)

        lines: list[str] = []
        if omitted_before:
            lines.append("…")
        lines.extend(f"{row.position}. {'?' if row is target else row.label}" for row in visible)
        if omitted_after:
            lines.append("…")
        return "\n".join(lines)

    @classmethod
    def group(
        cls,
        result: object,
        *,
        target: TargetKind,
        deck_name: str,
        expected: set[str],
        max_choices: int | None,
        card_key: CardKey | None = None,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ) -> dict[str, Self]:
        del max_choices
        if target is not TargetKind.ENTITY:
            raise PresentationError(f"deck {deck_name!r} ordered-list cards must target entities")
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 0:
            raise PresentationError(f"deck {deck_name!r} ordered-list window_size is invalid")

        rows_by_group: dict[Identifier, list[OrderedListRow]] = defaultdict(list)
        entity_groups: dict[URIRef, Identifier] = {}
        entity_keys: dict[URIRef, CardKey] = {}
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = cls._row_values(row)
            cls._require_bound(values, expected, deck_name, row_number)
            key = cls._card_key(values, target, deck_name, row_number)
            parsed = cls._row(values, deck_name=deck_name, row_number=row_number)
            existing_group = entity_groups.get(parsed.entity)
            if existing_group is not None:
                if existing_group != parsed.group:
                    raise PresentationError(
                        f"deck {deck_name!r} entity {parsed.entity.n3()} belongs to multiple "
                        "ordered-list groups"
                    )
                raise PresentationError(
                    f"deck {deck_name!r} returns duplicate ordered-list rows for "
                    f"entity {parsed.entity.n3()}"
                )
            entity_groups[parsed.entity] = parsed.group
            entity_keys[parsed.entity] = key
            rows_by_group[parsed.group].append(parsed)

        presentations: list[Self] = []
        for group, group_rows in rows_by_group.items():
            positions = sorted(row.position for row in group_rows)
            if len(group_rows) < 2:
                raise PresentationError(
                    f"deck {deck_name!r} ordered-list group {group.n3()} must contain "
                    "at least two rows"
                )
            expected_positions = list(range(1, len(group_rows) + 1))
            if positions != expected_positions:
                reason = "unique" if len(set(positions)) != len(positions) else "contiguous 1-based"
                raise PresentationError(
                    f"deck {deck_name!r} ordered-list group {group.n3()} must have {reason} "
                    "positions"
                )

            ordered_rows = sorted(group_rows, key=lambda row: row.position)
            for row in ordered_rows:
                key = entity_keys[row.entity]
                if card_key is not None and key != card_key:
                    continue
                try:
                    presentations.append(
                        cls(
                            card_key=key,
                            front=Literal(cls._window(ordered_rows, row, window_size)),
                            back=row.label,
                        )
                    )
                except ValidationError as error:
                    message = str(error.errors(include_url=False)[0]["msg"])
                    raise PresentationError(
                        f"deck {deck_name!r} has an invalid ordered-list presentation for "
                        f"card {key.digest}: {message.removeprefix('Value error, ')}"
                    ) from error

        if card_key is not None and not presentations:
            raise PresentationError(
                f"deck {deck_name!r} ordered-list query does not contain card {card_key.digest}"
            )
        return cls._by_digest(presentations)


# Keep the shorter name available to callers while using one registered kind.
OrderedList = OrderedListCompletion
