from __future__ import annotations

import random

import pytest
from pydantic import ValidationError
from rdflib import Literal, URIRef

from rdfcards.decks import Basic, ChoiceOption, MultipleChoice
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


def option(value: str, priority: int = 0) -> ChoiceOption:
    return ChoiceOption(choice=Literal(value), priority=priority)


def test_basic_front_text_is_the_front_value() -> None:
    presentation = Basic(card_key=card_key(), front=Literal("front"), back=Literal("back"))

    assert presentation.front_text(random.Random(0)) == "front"


def test_multiple_choice_front_text_shuffles_a_copy_of_choices() -> None:
    presentation = MultipleChoice(
        card_key=card_key(),
        front=Literal("question"),
        back=Literal("correct"),
        choices=(option("correct"), option("incorrect")),
    )

    text = presentation.front_text(ReverseRandom())

    assert text == "question\n  1. incorrect\n  2. correct"
    assert presentation.choices == (option("correct"), option("incorrect"))


def test_multiple_choice_exhausts_priority_tiers_and_includes_correct_answer() -> None:
    presentation = MultipleChoice(
        card_key=card_key(),
        front=Literal("question"),
        back=Literal("correct"),
        choices=(
            option("low", 1),
            option("high-b", 2),
            option("correct"),
            option("default"),
            option("high-a", 2),
        ),
        max_choices=4,
    )

    selected = set(presentation.selected_choices(random.Random(0)))

    assert selected == {
        Literal("correct"),
        Literal("high-a"),
        Literal("high-b"),
        Literal("low"),
    }
    assert Literal("default") not in selected


def test_multiple_choice_randomizes_a_cutoff_tie_deterministically() -> None:
    choices = (
        option("correct"),
        option("tied-a", 2),
        option("tied-b", 2),
        option("lower", 1),
    )
    presentation = MultipleChoice(
        card_key=card_key(),
        front=Literal("question"),
        back=Literal("correct"),
        choices=choices,
        max_choices=2,
    )
    reordered = presentation.model_copy(update={"choices": tuple(reversed(choices))})

    first = presentation.selected_choices(random.Random(7))
    repeated = presentation.selected_choices(random.Random(7))
    from_reordered_rows = reordered.selected_choices(random.Random(7))

    assert first == repeated == from_reordered_rows
    assert Literal("correct") in first
    assert len(set(first) & {Literal("tied-a"), Literal("tied-b")}) == 1
    assert Literal("lower") not in first


def test_multiple_choice_repeated_renders_vary_tied_selection_and_display_order() -> None:
    presentation = MultipleChoice(
        card_key=card_key(),
        front=Literal("question"),
        back=Literal("correct"),
        choices=(
            option("correct"),
            option("high", 3),
            option("tied-a", 2),
            option("tied-b", 2),
            option("tied-c", 2),
            option("low", 1),
        ),
        max_choices=3,
    )
    rng = random.Random(1)

    renders = tuple(presentation.selected_choices(rng) for _ in range(8))
    tied = {Literal("tied-a"), Literal("tied-b"), Literal("tied-c")}

    assert all({Literal("correct"), Literal("high")} <= set(rendered) for rendered in renders)
    assert all(len(set(rendered) & tied) == 1 for rendered in renders)
    assert all(Literal("low") not in rendered for rendered in renders)
    assert len({frozenset(set(rendered) & tied) for rendered in renders}) > 1
    assert len({rendered.index(Literal("correct")) for rendered in renders}) > 1


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
            choices=tuple(ChoiceOption(choice=choice) for choice in choices),
        )


@pytest.mark.parametrize("max_choices", [0, 1, True, 2.5, "2"])
def test_multiple_choice_rejects_invalid_max_choices(max_choices: object) -> None:
    with pytest.raises(ValidationError, match="max_choices"):
        MultipleChoice(
            card_key=card_key(),
            front=Literal("question"),
            back=Literal("correct"),
            choices=(option("correct"), option("incorrect")),
            max_choices=max_choices,
        )
