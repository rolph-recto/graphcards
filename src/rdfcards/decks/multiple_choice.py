"""Multiple-choice decks and presentations."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Annotated

from pydantic import Field, ValidationError, model_validator
from rdflib import Literal
from rdflib.namespace import XSD
from rdflib.term import Identifier

from rdfcards.decks.base import (
    DEFAULT_MAX_CHOICES,
    DeckDefinition,
    Presentation,
)
from rdfcards.errors import PresentationError
from rdfcards.models import CardKey, RdfModel, validation_message


class ChoiceOption(RdfModel):
    """One candidate answer and its normalized distractor-selection priority."""

    choice: Identifier
    priority: Annotated[int, Field(strict=True, ge=0)] = 0


class MultipleChoicePresentation(Presentation):
    """A self-rated presentation with shuffled choices and a correct back."""

    choices: tuple[ChoiceOption, ...]
    max_choices: Annotated[int, Field(strict=True, ge=2)] = DEFAULT_MAX_CHOICES

    @model_validator(mode="after")
    def validate_choices(self) -> MultipleChoicePresentation:
        if len(self.choices) < 2:
            raise ValueError("a multiple-choice presentation needs at least two choices")
        choice_values = tuple(option.choice for option in self.choices)
        if len(set(choice_values)) != len(choice_values):
            raise ValueError("a multiple-choice presentation cannot contain duplicate choices")
        if self.back not in choice_values:
            raise ValueError("the multiple-choice back must be one of its choices")
        return self

    def _selected_distractors(self, rng: random.Random) -> list[Identifier]:
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


class MultipleChoiceDeck(DeckDefinition):
    """Configured multiple-choice query behavior."""

    config_name = "multiple_choice"
    required_variables = frozenset({"front", "choice", "is_correct"})

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

    def group(
        self,
        result: object,
        *,
        expected: set[str],
        card_key: CardKey | None = None,
    ) -> dict[str, Presentation]:
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

        presentations: list[Presentation] = []
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
                presentations.append(
                    MultipleChoicePresentation(
                        card_key=key,
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
                        max_choices=self.max_choices,
                    )
                )
            except ValidationError as error:
                raise PresentationError(
                    f"deck {self.name!r} has an invalid multiple-choice presentation "
                    f"for card {key.digest}: {validation_message(error)}"
                ) from error
        return self._by_digest(presentations)
