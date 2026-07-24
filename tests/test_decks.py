from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError
from rdflib import Literal, URIRef

from graphcards.decks import (
    BasicCard,
    BasicDeck,
    MultipleChoiceCard,
    MultipleChoiceDeck,
    OrderedListCard,
    OrderedListRow,
)
from graphcards.errors import PresentationError
from graphcards.models import Card, CardKey, TargetKind


def card_key() -> CardKey:
    return CardKey.triple(
        URIRef("https://example.org/subject"),
        URIRef("https://example.org/predicate"),
        URIRef("https://example.org/object"),
    )


def basic_deck(**overrides: object) -> BasicDeck:
    return BasicDeck(
        name="basic",
        target=TargetKind.TRIPLE,
        query_path=Path("unused.rq"),
        **overrides,
    )


def multiple_choice_deck(**overrides: object) -> MultipleChoiceDeck:
    return MultipleChoiceDeck(
        name="multiple-choice",
        target=TargetKind.TRIPLE,
        query_path=Path("unused.rq"),
        **overrides,
    )


def test_basic_card_renders_to_a_card_view() -> None:
    card = BasicCard(
        card_key=card_key(),
        front=Literal("front"),
        back=Literal("back"),
    )

    view = basic_deck().render(card)

    assert view.card_key == card.card_key
    assert view.front == "front"
    assert view.back == "back"


def test_configured_templates_support_conditions_loops_and_whitespace() -> None:
    card = MultipleChoiceCard(
        card_key=card_key(),
        front=Literal("question"),
        back=Literal("correct"),
        choices=(Literal("incorrect"), Literal("correct")),
    )
    deck = multiple_choice_deck(
        front_template="  {% if front %}{{ front }}\nsecond line{% endif %}  \n",
        back_template="{% for choice in choices %}[{{ choice }}]{% endfor %}",
    )

    view = deck.render(card)

    assert view.front == "  question\nsecond line  \n"
    assert view.back == "[incorrect][correct]"


def test_deck_rejects_an_incompatible_card_type() -> None:
    card = BasicCard(
        card_key=card_key(),
        front=Literal("front"),
        back=Literal("back"),
    )

    with pytest.raises(PresentationError, match="renders MultipleChoiceCard"):
        multiple_choice_deck().render(card)


def test_deck_translates_jinja_runtime_failure() -> None:
    card = BasicCard(
        card_key=card_key(),
        front=Literal("front"),
        back=Literal("back"),
    )

    with pytest.raises(PresentationError, match="division by zero") as caught:
        basic_deck(front_template="{{ 1 / 0 }}").render(card)

    assert isinstance(caught.value.__cause__, ZeroDivisionError)


def test_deck_translates_undefined_template_values() -> None:
    card = BasicCard(
        card_key=card_key(),
        front=Literal("front"),
        back=Literal("back"),
    )

    with pytest.raises(PresentationError, match="'missing' is undefined"):
        basic_deck(front_template="{{ missing }}").render(card)


def test_deck_preserves_render_context_presentation_errors() -> None:
    class RejectingDeck(BasicDeck):
        def render_context(
            self,
            card: Card,
        ) -> Mapping[str, object]:
            del self, card
            raise PresentationError("custom presentation rejection")

    card = BasicCard(
        card_key=card_key(),
        front=Literal("front"),
        back=Literal("back"),
    )

    deck = RejectingDeck(
        name="rejecting",
        target=TargetKind.TRIPLE,
        query_path=Path("unused.rq"),
    )

    with pytest.raises(PresentationError, match="custom presentation rejection") as caught:
        deck.render(card)

    assert caught.value.__cause__ is None


def test_deck_passes_validated_configuration_to_render_context() -> None:
    class PrefixDeck(BasicDeck):
        prefix: str

        def render_context(
            self,
            card: Card,
        ) -> Mapping[str, object]:
            context = dict(super().render_context(card))
            context["front"] = f"{self.prefix} {context['front']}"
            return context

    card = BasicCard(
        card_key=card_key(),
        front=Literal("front"),
        back=Literal("back"),
    )

    deck = PrefixDeck(
        name="prefixed",
        target=TargetKind.TRIPLE,
        query_path=Path("unused.rq"),
        prefix="Typed:",
    )
    view = deck.render(card)

    assert view.front == "Typed: front"


def test_multiple_choice_rendering_preserves_generated_choice_order() -> None:
    card = MultipleChoiceCard(
        card_key=card_key(),
        front=Literal("question"),
        back=Literal("correct"),
        choices=(Literal("incorrect"), Literal("correct")),
    )

    deck = multiple_choice_deck()
    first = deck.render(card)
    second = deck.render(card)

    assert first == second
    assert first.front == "question\n  1. incorrect\n  2. correct"
    assert first.back == "correct"
    assert card.choices == (Literal("incorrect"), Literal("correct"))


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
def test_multiple_choice_card_rejects_invalid_semantic_data(
    choices: tuple[Literal, ...],
    back: Literal,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        MultipleChoiceCard(
            card_key=card_key(),
            front=Literal("question"),
            back=back,
            choices=choices,
        )


def ordered_rows() -> tuple[OrderedListRow, OrderedListRow]:
    return (
        OrderedListRow(
            entity=URIRef("https://example.org/first"),
            group=URIRef("https://example.org/group"),
            position=1,
            label=Literal("First"),
        ),
        OrderedListRow(
            entity=URIRef("https://example.org/second"),
            group=URIRef("https://example.org/group"),
            position=2,
            label=Literal("Second"),
        ),
    )


def test_ordered_list_card_accepts_valid_semantic_data() -> None:
    rows = ordered_rows()

    card = OrderedListCard(
        card_key=CardKey.entity(rows[1].entity),
        ordered_rows=rows,
        hidden_position=2,
    )

    assert card.ordered_rows == rows
    assert card.hidden_position == 2


@pytest.mark.parametrize(
    ("rows", "card_key_value", "message"),
    [
        (
            ordered_rows()[:1],
            CardKey.entity(ordered_rows()[0].entity),
            "at least two rows",
        ),
        (
            (
                ordered_rows()[0],
                ordered_rows()[1].model_copy(update={"position": 1}),
            ),
            CardKey.entity(ordered_rows()[1].entity),
            "unique positions",
        ),
        (
            (
                ordered_rows()[0],
                ordered_rows()[1].model_copy(
                    update={"group": URIRef("https://example.org/other-group")}
                ),
            ),
            CardKey.entity(ordered_rows()[1].entity),
            "one group",
        ),
        (
            ordered_rows(),
            CardKey.entity(ordered_rows()[0].entity),
            "hidden row must match the card identity",
        ),
    ],
)
def test_ordered_list_card_rejects_invalid_semantic_data(
    rows: tuple[OrderedListRow, ...],
    card_key_value: CardKey,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        OrderedListCard(
            card_key=card_key_value,
            ordered_rows=rows,
            hidden_position=1 if len(rows) == 1 else 2,
        )
