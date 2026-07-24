"""Relational analogy cards, generation, and rendering."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping
from typing import Literal as TypingLiteral

from pydantic import ValidationError, field_validator, model_validator
from rdflib import Literal
from rdflib.namespace import XSD
from rdflib.term import Identifier

from graphcards.decks.base import DeckDefinition, TemplateSource
from graphcards.errors import PresentationError
from graphcards.models import Card, CardKey, TargetKind, validation_message


class AnalogyCard(Card):
    """Semantic source/target relation data with one hidden target position."""

    source_subject: Identifier
    source_predicate: Identifier
    source_object: Identifier
    hide: TypingLiteral["subject", "object"]
    subject_label: Identifier | None = None
    predicate_label: Identifier | None = None
    object_label: Identifier | None = None
    source_subject_label: Identifier | None = None
    source_predicate_label: Identifier | None = None
    source_object_label: Identifier | None = None

    @field_validator("hide", mode="before")
    @classmethod
    def normalize_hide(cls, value: object) -> str:
        if type(value) is str and value in {"subject", "object"}:
            return value
        if (
            not isinstance(value, Literal)
            or value.language is not None
            or value.datatype not in (None, XSD.string)
            or str(value) not in {"subject", "object"}
        ):
            raise ValueError("?hide must be a literal with value subject or object")
        return str(value)

    @model_validator(mode="after")
    def validate_analogy(self) -> AnalogyCard:
        if self.card_key.target_kind is not TargetKind.TRIPLE:
            raise ValueError("an analogy card must use a triple card identity")
        _subject, predicate, object_ = self.card_key.terms
        if self.source_predicate != predicate:
            raise ValueError("the source and target predicates must match")
        if (self.source_subject, self.source_predicate, self.source_object) == (
            self.card_key.terms[0],
            predicate,
            object_,
        ):
            raise ValueError("the source triple must be distinct from the target triple")
        return self

    @staticmethod
    def _text(term: Identifier, label: Identifier | None) -> str:
        return str(label if label is not None else term)

    def duplicate_key(self) -> tuple[object, ...]:
        subject, _predicate, object_ = self.card_key.terms
        relation_label = (
            self.predicate_label
            if self.predicate_label is not None
            else self.source_predicate_label
        )
        return (
            self.source_subject,
            self.source_predicate,
            self.source_object,
            self.hide,
            self._text(self.source_subject, self.source_subject_label),
            str(relation_label) if relation_label is not None else ":",
            self._text(self.source_object, self.source_object_label),
            self._text(subject, self.subject_label),
            self._text(object_, self.object_label),
        )


class AnalogyDeck(DeckDefinition):
    """Configured relational analogy query and rendering behavior."""

    config_name = "analogy"
    required_variables = frozenset({"source_subject", "source_predicate", "source_object", "hide"})
    card_type = AnalogyCard
    front_template: TemplateSource = (
        "{{ source_subject }} {{ relation }} {{ source_object }} :: "
        '{% if hide == "subject" %}?{% else %}{{ target_subject }}{% endif %} '
        "{{ relation }} "
        '{% if hide == "object" %}?{% else %}{{ target_object }}{% endif %}'
    )
    back_template: TemplateSource = "{{ answer }}"

    target: TypingLiteral[TargetKind.TRIPLE]

    def render_context(self, card: Card) -> Mapping[str, object]:
        if not isinstance(card, AnalogyCard):
            return {}
        subject, _predicate, object_ = card.card_key.terms
        relation_label = (
            card.predicate_label
            if card.predicate_label is not None
            else card.source_predicate_label
        )
        answer = (
            AnalogyCard._text(subject, card.subject_label)
            if card.hide == "subject"
            else AnalogyCard._text(object_, card.object_label)
        )
        return {
            "source_subject": AnalogyCard._text(card.source_subject, card.source_subject_label),
            "source_object": AnalogyCard._text(card.source_object, card.source_object_label),
            "target_subject": AnalogyCard._text(subject, card.subject_label),
            "target_object": AnalogyCard._text(object_, card.object_label),
            "relation": str(relation_label) if relation_label is not None else ":",
            "hide": card.hide,
            "answer": answer,
        }

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
        rng: random.Random,
    ) -> dict[str, Card]:
        del card_key, rng
        grouped: dict[
            CardKey,
            dict[tuple[object, ...], AnalogyCard],
        ] = defaultdict(dict)
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = self._row_values(row)
            self._require_bound(values, expected, row_number)
            key = self._card_key(values, row_number)
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
                card = AnalogyCard(
                    card_key=key,
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
            grouped[key][card.duplicate_key()] = card

        cards: list[Card] = []
        for key, values in grouped.items():
            if len(values) != 1:
                raise PresentationError(
                    f"deck {self.name!r} returns conflicting analogy source, hide mode, or "
                    f"display labels for card {key.digest}"
                )
            cards.append(next(iter(values.values())))
        return self._by_digest(cards)
