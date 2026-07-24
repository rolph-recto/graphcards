"""RDF loading plus semantic card generation."""

from __future__ import annotations

import random
from pathlib import Path

from rdflib import Graph

from graphcards.decks import DeckDefinition
from graphcards.errors import PresentationError
from graphcards.models import Card, CardKey


def load_graph(sources: tuple[Path, ...]) -> Graph:
    graph = Graph()
    for source in sources:
        if not source.is_file():
            raise PresentationError(f"RDF source not found: {source}")
        try:
            graph.parse(source)
        except Exception as error:
            raise PresentationError(f"could not parse RDF source {source}: {error}") from error
    return graph


def execute_cards(
    graph: Graph,
    deck: DeckDefinition,
    card_key: CardKey | None = None,
    *,
    rng: random.Random | None = None,
) -> dict[str, Card]:
    """Generate semantic cards, including random choices, from one query."""

    return deck.execute_cards(graph, card_key, rng=rng or random.Random())
