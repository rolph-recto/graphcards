"""Basic front/back decks."""

from __future__ import annotations

import random
from collections import defaultdict

from rdflib.term import Identifier

from graphcards.decks.base import DeckDefinition, TemplateSource
from graphcards.errors import PresentationError
from graphcards.models import Card, CardKey


class BasicCard(Card):
    """Raw front/back values for a manually rated card."""

    front: Identifier
    back: Identifier


class BasicDeck(DeckDefinition):
    """Configured basic front/back query and rendering behavior."""

    config_name = "basic"
    required_variables = frozenset({"front", "back"})
    card_type = BasicCard
    front_template: TemplateSource = "{{ front }}"
    back_template: TemplateSource = "{{ back }}"

    def group(
        self,
        result: object,
        *,
        expected: set[str],
        card_key: CardKey | None = None,
        rng: random.Random,
    ) -> dict[str, Card]:
        del card_key, rng
        grouped: dict[CardKey, set[tuple[Identifier, Identifier]]] = defaultdict(set)
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = self._row_values(row)
            self._require_bound(values, expected, row_number)
            key = self._card_key(values, row_number)
            grouped[key].add((values["front"], values["back"]))

        cards: list[Card] = []
        for key, pairs in grouped.items():
            if len(pairs) != 1:
                raise PresentationError(
                    f"deck {self.name!r} returns conflicting front/back values for card "
                    f"{key.digest}"
                )
            front, back = next(iter(pairs))
            cards.append(BasicCard(card_key=key, front=front, back=back))
        return self._by_digest(cards)
