"""Relational analogy decks and presentations."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal as TypingLiteral

from pydantic import ValidationError, field_validator, model_validator
from rdflib import Literal
from rdflib.namespace import XSD
from rdflib.term import Identifier

from graphcards.decks.base import DeckDefinition, Presentation
from graphcards.errors import PresentationError
from graphcards.models import CardKey, TargetKind, validation_message


class AnalogyPresentation(Presentation):
    """A relational analogy that hides one term of a target triple."""

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
    def validate_analogy(self) -> AnalogyPresentation:
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
        expected_front, expected_back = self.front_and_back(
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
        del predicate
        relation = str(predicate_label) if predicate_label is not None else ":"
        rendered_object = "?" if hidden == "object" else cls._text(object_, object_label)
        rendered_subject = "?" if hidden == "subject" else cls._text(subject, subject_label)
        return f"{rendered_subject} {relation} {rendered_object}"

    @classmethod
    def front_and_back(
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

    def duplicate_key(self) -> tuple[object, ...]:
        return (
            self.source_subject,
            self.source_predicate,
            self.source_object,
            str(self.hide),
            str(self.front),
            str(self.back),
        )


class AnalogyDeck(DeckDefinition):
    """Configured relational analogy query behavior."""

    config_name = "analogy"
    required_variables = frozenset({"source_subject", "source_predicate", "source_object", "hide"})

    target: TypingLiteral[TargetKind.TRIPLE]

    @field_validator("target", mode="before")
    @classmethod
    def require_triple_target(cls, value: object) -> object:
        if value not in (TargetKind.TRIPLE, TargetKind.TRIPLE.value):
            raise ValueError("analogy decks must target triple cards")
        return value

    def group(
        self,
        result: object,
        *,
        expected: set[str],
        card_key: CardKey | None = None,
    ) -> dict[str, Presentation]:
        del card_key
        grouped: dict[
            CardKey,
            dict[tuple[object, ...], AnalogyPresentation],
        ] = defaultdict(dict)
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = self._row_values(row)
            self._require_bound(values, expected, row_number)
            key = self._card_key(values, row_number)
            target_subject, target_predicate, target_object = key.terms
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
                front, back = AnalogyPresentation.front_and_back(
                    target_subject=target_subject,
                    target_predicate=target_predicate,
                    target_object=target_object,
                    source_subject=values["source_subject"],
                    source_predicate=values["source_predicate"],
                    source_object=values["source_object"],
                    hide=values["hide"],  # type: ignore[arg-type]
                    **labels,
                )
                presentation = AnalogyPresentation(
                    card_key=key,
                    front=front,
                    back=back,
                    source_subject=values["source_subject"],
                    source_predicate=values["source_predicate"],
                    source_object=values["source_object"],
                    hide=values["hide"],
                    **labels,
                )
            except (ValidationError, ValueError) as error:
                message = (
                    validation_message(error) if isinstance(error, ValidationError) else str(error)
                )
                raise PresentationError(
                    f"deck {self.name!r} row {row_number}: {message}"
                ) from error
            grouped[key][presentation.duplicate_key()] = presentation

        presentations: list[Presentation] = []
        for key, values in grouped.items():
            if len(values) != 1:
                raise PresentationError(
                    f"deck {self.name!r} returns conflicting analogy source, hide mode, or "
                    f"display labels for card {key.digest}"
                )
            presentations.append(next(iter(values.values())))
        return self._by_digest(presentations)
