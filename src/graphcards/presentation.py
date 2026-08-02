"""Semantic exercise generation and Jinja rendering at the presentation boundary."""

from __future__ import annotations

import random

from graphcards.decks import Deck
from graphcards.models import Card, CardKey, CardView


def execute_cards(
    deck: Deck,
    card_key: CardKey | None = None,
    *,
    rng: random.Random | None = None,
) -> dict[str, Card]:
    """Generate semantic exercises without rereading the deck source file."""

    if card_key is None:
        return deck.generate_all(rng=rng)
    exercise = deck.generate(card_key, rng=rng)
    return {exercise.card_key.entity_id: exercise}


def render_card(deck: Deck, card: Card) -> CardView:
    """Render a validated semantic exercise through its owning deck."""

    return deck.render(card)  # type: ignore[arg-type]


__all__ = ["execute_cards", "render_card"]
