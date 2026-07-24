"""RDF loading plus SPARQL query execution and validation."""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph

from graphcards.decks import DeckDefinition, Presentation
from graphcards.errors import PresentationError
from graphcards.models import CardKey


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


def execute_presentations(
    graph: Graph,
    deck: DeckDefinition,
    card_key: CardKey | None = None,
) -> dict[str, Presentation]:
    """Delegate query execution to the configured concrete deck definition."""

    return deck.execute_presentations(graph, card_key)
