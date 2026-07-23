from __future__ import annotations

import io
import random

import pytest
from fsrs import Rating
from rdflib import Literal, URIRef

from rdfcards.decks import Basic, Choice, MultipleChoice
from rdfcards.models import CardKey


def inputs(*values: str):
    iterator = iter(values)
    return lambda: next(iterator)


def card_key() -> CardKey:
    return CardKey.triple(
        URIRef("https://example.org/subject"),
        URIRef("https://example.org/predicate"),
        URIRef("https://example.org/object"),
    )


@pytest.mark.parametrize(
    ("answer", "rating"),
    [
        ("1", Rating.Again),
        ("2", Rating.Hard),
        ("3", Rating.Good),
        ("4", Rating.Easy),
    ],
)
def test_basic_answer_maps_every_rating(answer: str, rating: Rating) -> None:
    presentation = Basic(card_key=card_key(), front=Literal("front"), back=Literal("back"))

    result = presentation.answer(inputs("", answer), io.StringIO(), random.Random(0))

    assert result is rating


def test_basic_answer_retries_invalid_rating() -> None:
    presentation = Basic(card_key=card_key(), front=Literal("front"), back=Literal("back"))
    output = io.StringIO()

    result = presentation.answer(inputs("", "invalid", "2"), output, random.Random(0))

    assert result is Rating.Hard
    assert "Please enter 1, 2, 3, 4, or q." in output.getvalue()


@pytest.mark.parametrize("answers", [("q",), ("", "q")])
def test_basic_answer_can_quit_without_a_rating(answers: tuple[str, ...]) -> None:
    presentation = Basic(card_key=card_key(), front=Literal("front"), back=Literal("back"))

    assert presentation.answer(inputs(*answers), io.StringIO(), random.Random(0)) is None


class NoShuffle(random.Random):
    def shuffle(self, values: list[object]) -> None:
        del values


def multiple_choice() -> MultipleChoice:
    return MultipleChoice(
        card_key=card_key(),
        front=Literal("question"),
        choices=(
            Choice(value=Literal("correct"), is_correct=True),
            Choice(value=Literal("incorrect"), is_correct=False),
        ),
    )


def test_multiple_choice_answer_retries_invalid_choices() -> None:
    output = io.StringIO()

    result = multiple_choice().answer(inputs("invalid", "3", "1"), output, NoShuffle())

    assert result is Rating.Good
    assert output.getvalue().count("Please enter a number from 1 to 2, or q.") == 2


def test_multiple_choice_answer_can_quit_without_a_rating() -> None:
    assert multiple_choice().answer(inputs("q"), io.StringIO(), NoShuffle()) is None
