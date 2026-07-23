from __future__ import annotations

import random

import pytest
from pydantic import ValidationError
from rdflib import Literal, URIRef

from rdfcards.decks import Basic, MultipleChoice
from rdfcards.models import CardKey


def card_key() -> CardKey:
    return CardKey.triple(
        URIRef("https://example.org/subject"),
        URIRef("https://example.org/predicate"),
        URIRef("https://example.org/object"),
    )


class ReverseRandom(random.Random):
    def shuffle(self, values: list[object]) -> None:
        values.reverse()


def test_basic_front_text_is_the_front_value() -> None:
    presentation = Basic(card_key=card_key(), front=Literal("front"), back=Literal("back"))

    assert presentation.front_text(random.Random(0)) == "front"


def test_multiple_choice_front_text_shuffles_a_copy_of_choices() -> None:
    presentation = MultipleChoice(
        card_key=card_key(),
        front=Literal("question"),
        back=Literal("correct"),
        choices=(Literal("correct"), Literal("incorrect")),
    )

    text = presentation.front_text(ReverseRandom())

    assert text == "question\n  1. incorrect\n  2. correct"
    assert presentation.choices == (Literal("correct"), Literal("incorrect"))


@pytest.mark.parametrize(
    ("choices", "back", "message"),
    [
        ((Literal("only"),), Literal("only"), "at least two choices"),
        (
            (Literal("same"), Literal("same")),
            Literal("same"),
            "cannot contain duplicate choices",
        ),
        (
            (Literal("first"), Literal("second")),
            Literal("missing"),
            "back must be one of its choices",
        ),
    ],
)
def test_multiple_choice_rejects_invalid_direct_construction(
    choices: tuple[Literal, ...],
    back: Literal,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        MultipleChoice(
            card_key=card_key(),
            front=Literal("question"),
            back=back,
            choices=choices,
        )
