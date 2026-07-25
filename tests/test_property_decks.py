from __future__ import annotations

import random
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from rdflib import URIRef

from graphcards.decks import (
    AnalogyCard,
    AnalogyDeck,
    BasicCard,
    MultipleChoiceCard,
    MultipleChoiceDeck,
    OrderedListCard,
    OrderedListDeck,
)
from graphcards.errors import PresentationError
from graphcards.models import CardKey, TargetKind
from tests.strategies import (
    PROPERTY_SETTINGS,
    analogy_cards,
    basic_cards,
    multiple_choice_cards,
    ordered_list_cards,
    prioritized_candidates,
)


@given(card=multiple_choice_cards())
@PROPERTY_SETTINGS
def test_multiple_choice_views_have_one_answer_and_unique_choices(card: MultipleChoiceCard) -> None:
    # Property: multiple-choice views retain exactly one correct, unique answer choice.
    deck = MultipleChoiceDeck(
        name="choices",
        target=TargetKind.ENTITY,
        query_path=Path("unused.rq"),
    )

    view = deck.render(card)

    assert view.back == str(card.back)
    assert len(card.choices) == len(set(card.choices))
    assert card.choices.count(card.back) == 1


@given(candidates=prioritized_candidates(), max_choices=st.integers(min_value=2, max_value=6))
@PROPERTY_SETTINGS
def test_multiple_choice_selection_prefers_highest_priority_tiers(
    candidates: list[tuple[object, bool, int]],
    max_choices: int,
) -> None:
    # Property: multiple-choice selection fills its bounded display from the highest priority tiers.
    deck = MultipleChoiceDeck(
        name="choices",
        target=TargetKind.ENTITY,
        query_path=Path("unused.rq"),
        max_choices=max_choices,
    )
    choices = {choice: (is_correct, priority) for choice, is_correct, priority in candidates}
    selected = deck._selected_choices(choices, random.Random(0))  # type: ignore[arg-type]
    incorrect_priorities = [
        priority for choice, (correct, priority) in choices.items() if not correct
    ]
    selected_priorities = [choices[choice][1] for choice in selected if not choices[choice][0]]
    expected = sorted(incorrect_priorities, reverse=True)[: max_choices - 1]

    assert len(selected) <= max_choices
    assert sum(choices[choice][0] for choice in selected) == 1
    assert sorted(selected_priorities, reverse=True) == sorted(expected, reverse=True)


@given(card=ordered_list_cards(), window_size=st.integers(min_value=0, max_value=8))
@PROPERTY_SETTINGS
def test_ordered_list_views_have_contiguous_rows_one_hidden_target_and_bounded_windows(
    card: OrderedListCard,
    window_size: int,
) -> None:
    # Property: ordered-list views keep contiguous positions, one hidden target, the answer on
    # the back,
    # and a visible window no larger than the configured bound.
    deck = OrderedListDeck(
        name="ordered",
        target=TargetKind.ENTITY,
        query_path=Path("unused.rq"),
        window_size=window_size,
    )
    context = deck.render_context(card)
    rows = context["rows"]
    positions = [row["position"] for row in rows]  # type: ignore[index]
    hidden = [row for row in rows if row["value"] == "?"]  # type: ignore[index]
    maximum = len(card.ordered_rows)

    assert [row.position for row in card.ordered_rows] == list(range(1, maximum + 1))
    assert len(hidden) == 1
    assert context["answer"] == str(card.ordered_rows[card.hidden_position - 1].label)
    assert positions == list(range(positions[0], positions[-1] + 1))
    if window_size:
        assert len(rows) <= window_size
    else:
        assert len(rows) == maximum

    view = deck.render(card)
    assert view.back == context["answer"]
    assert view.front.count("?") == 1


@given(card=analogy_cards())
@PROPERTY_SETTINGS
def test_analogy_views_preserve_relation_and_derive_the_hidden_answer(card: AnalogyCard) -> None:
    # Property: analogy views preserve a distinct source with the target predicate and derive the
    # answer
    # from the hidden subject or object.
    deck = AnalogyDeck(
        name="analogy",
        target=TargetKind.TRIPLE,
        query_path=Path("unused.rq"),
    )
    context = deck.render_context(card)
    target_subject, target_predicate, target_object = card.card_key.terms

    assert card.source_predicate == target_predicate
    assert (card.source_subject, card.source_predicate, card.source_object) != card.card_key.terms
    expected = (
        AnalogyCard._text(target_subject, card.subject_label)
        if card.hide == "subject"
        else AnalogyCard._text(target_object, card.object_label)
    )
    assert context["answer"] == expected
    assert deck.render(card).back == expected


@given(card=basic_cards())
@PROPERTY_SETTINGS
def test_renderers_reject_incompatible_semantic_cards(card: BasicCard) -> None:
    # Property: renderers reject semantic cards whose model type does not match the deck contract.
    deck = MultipleChoiceDeck(
        name="choices",
        target=card.card_key.target_kind,
        query_path=Path("unused.rq"),
    )

    with pytest.raises(PresentationError, match="renders"):
        deck.render(card)


def test_invalid_analogy_source_and_ordered_list_invariants_are_user_facing() -> None:
    # Property: invalid analogy source identity is exposed as a validation error rather than
    # accepted.
    target = CardKey.triple(
        URIRef("https://example.org/target"),
        URIRef("https://example.org/predicate"),
        URIRef("https://example.org/object"),
    )
    with pytest.raises(ValueError, match="distinct"):
        AnalogyCard(
            card_key=target,
            source_subject=target.terms[0],
            source_predicate=target.terms[1],
            source_object=target.terms[2],
            hide="object",
        )
