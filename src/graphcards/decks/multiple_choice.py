"""Multiple-choice card generation and stateless rendering."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Annotated

from pydantic import Field, ValidationError, model_validator
from rdflib import Literal
from rdflib.namespace import XSD
from rdflib.term import Identifier

from graphcards.decks.base import (
    DEFAULT_MAX_CHOICES,
    DeckDefinition,
    TemplateSource,
)
from graphcards.errors import PresentationError
from graphcards.models import Card, CardKey, validation_message


class MultipleChoiceCard(Card):
    """A question with its already-selected, already-ordered answer choices."""

    front: Identifier
    back: Identifier
    choices: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_choices(self) -> MultipleChoiceCard:
        if len(self.choices) < 2:
            raise ValueError("a multiple-choice card needs at least two choices")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("a multiple-choice card cannot contain duplicate choices")
        if self.back not in self.choices:
            raise ValueError("the multiple-choice back must be one of its choices")
        return self


class MultipleChoiceDeck(DeckDefinition):
    """Configured multiple-choice generation and rendering behavior."""

    config_name = "multiple_choice"
    required_variables = frozenset({"front", "choice", "is_correct"})
    card_type = MultipleChoiceCard
    front_template: TemplateSource = (
        "{{ front }}{% for choice in choices %}\n  {{ loop.index }}. {{ choice }}{% endfor %}"
    )
    back_template: TemplateSource = "{{ back }}"

    max_choices: Annotated[int, Field(strict=True, ge=2)] = DEFAULT_MAX_CHOICES

    def _boolean(self, value: Identifier, row_number: int) -> bool:
        if not isinstance(value, Literal) or value.datatype != XSD.boolean:
            raise PresentationError(
                f"deck {self.name!r} row {row_number} ?is_correct must be an xsd:boolean literal"
            )
        if str(value) not in {"true", "false", "1", "0"}:
            raise PresentationError(
                f"deck {self.name!r} row {row_number} has an invalid xsd:boolean lexical value"
            )
        converted = value.toPython()
        if not isinstance(converted, bool):
            raise PresentationError(
                f"deck {self.name!r} row {row_number} has an invalid xsd:boolean value"
            )
        return converted

    def _priority(self, value: Identifier | None, row_number: int) -> int:
        if value is None:
            return 0
        return self._rdf_integer(
            value,
            variable="priority",
            minimum=0,
            minimum_description="zero or greater",
            row_number=row_number,
        )

    def _selected_choices(
        self,
        choices: dict[Identifier, tuple[bool, int]],
        rng: random.Random,
    ) -> tuple[Identifier, ...]:
        correct = next(value for value, (is_correct, _priority) in choices.items() if is_correct)
        tiers: dict[int, list[Identifier]] = defaultdict(list)
        for value, (is_correct, priority) in choices.items():
            if not is_correct:
                tiers[priority].append(value)

        remaining = self.max_choices - 1
        selected = [correct]
        for priority in sorted(tiers, reverse=True):
            tier = sorted(tiers[priority], key=lambda choice: choice.n3())
            rng.shuffle(tier)
            retained = tier[:remaining]
            selected.extend(retained)
            remaining -= len(retained)
            if remaining == 0:
                break
        rng.shuffle(selected)
        return tuple(selected)

    def group(
        self,
        result: object,
        *,
        expected: set[str],
        card_key: CardKey | None = None,
        rng: random.Random,
    ) -> dict[str, Card]:
        del card_key
        fronts: dict[CardKey, set[Identifier]] = defaultdict(set)
        choices: dict[CardKey, dict[Identifier, tuple[bool, int]]] = defaultdict(dict)
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = self._row_values(row)
            self._require_bound(values, expected, row_number)
            key = self._card_key(values, row_number)
            fronts[key].add(values["front"])
            choice = values["choice"]
            is_correct = self._boolean(values["is_correct"], row_number)
            priority = self._priority(values.get("priority"), row_number)
            existing = choices[key].get(choice)
            if existing is not None:
                existing_correct, existing_priority = existing
                if existing_correct != is_correct:
                    raise PresentationError(
                        f"deck {self.name!r} marks the same choice both correct and incorrect "
                        f"for card {key.digest}"
                    )
                if existing_priority != priority:
                    raise PresentationError(
                        f"deck {self.name!r} assigns conflicting priorities to the same choice "
                        f"for card {key.digest}"
                    )
            choices[key][choice] = (is_correct, priority)

        cards: list[Card] = []
        for key, front_values in fronts.items():
            if len(front_values) != 1:
                raise PresentationError(
                    f"deck {self.name!r} returns conflicting fronts for card {key.digest}"
                )
            card_choices = choices[key]
            if len(card_choices) < 2:
                raise PresentationError(
                    f"deck {self.name!r} needs at least two choices for card {key.digest}"
                )
            if sum(is_correct for is_correct, _priority in card_choices.values()) != 1:
                raise PresentationError(
                    f"deck {self.name!r} needs exactly one correct choice for card {key.digest}"
                )
            try:
                cards.append(
                    MultipleChoiceCard(
                        card_key=key,
                        front=next(iter(front_values)),
                        back=next(
                            value
                            for value, (is_correct, _priority) in card_choices.items()
                            if is_correct
                        ),
                        choices=self._selected_choices(card_choices, rng),
                    )
                )
            except ValidationError as error:
                raise PresentationError(
                    f"deck {self.name!r} has an invalid multiple-choice card "
                    f"for card {key.digest}: {validation_message(error)}"
                ) from error
        return self._by_digest(cards)
