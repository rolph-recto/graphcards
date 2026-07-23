"""RDF loading plus SPARQL query execution and validation."""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph

from rdfcards.config import DeckDefinition
from rdfcards.decks import DeckKind
from rdfcards.errors import PresentationError
from rdfcards.models import CardKey, TargetKind

IDENTITY_VARIABLES = {
    TargetKind.TRIPLE: {"subject", "predicate", "object"},
    TargetKind.ENTITY: {"entity"},
}


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


def _read_query(deck: DeckDefinition) -> str:
    try:
        return deck.query_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise PresentationError(
            f"query file for deck {deck.name!r} not found: {deck.query_path}"
        ) from error
    except OSError as error:
        raise PresentationError(
            f"could not read query file for deck {deck.name!r}: {error}"
        ) from error


def execute_presentations(
    graph: Graph,
    deck: DeckDefinition,
    card_key: CardKey | None = None,
) -> dict[str, DeckKind]:
    """Run and validate a deck query, optionally restricted to one stored identity."""

    query = _read_query(deck)
    bindings = None
    if card_key is not None:
        if card_key.target_kind != deck.target:
            raise PresentationError(
                f"deck {deck.name!r} targets {deck.target} cards but received a "
                f"{card_key.target_kind} card"
            )
        # Study-time rendering must use current metadata without allowing the query
        # to silently switch to a different identity.
        bindings = card_key.query_bindings
    try:
        result = graph.query(query, initBindings=bindings)
    except Exception as error:
        raise PresentationError(f"SPARQL query for deck {deck.name!r} failed: {error}") from error
    if result.type != "SELECT":
        raise PresentationError(f"deck {deck.name!r} must use a SELECT query")

    expected = IDENTITY_VARIABLES[deck.target] | deck.kind.required_variables
    selected = {str(variable) for variable in result.vars or ()}
    missing = sorted(expected - selected)
    if missing:
        joined = ", ".join(f"?{name}" for name in missing)
        raise PresentationError(f"deck {deck.name!r} does not SELECT required variables: {joined}")

    presentations = deck.kind.group(
        result,
        target=deck.target,
        deck_name=deck.name,
        expected=expected,
    )
    if card_key is not None:
        unexpected = [item.card_key for item in presentations.values() if item.card_key != card_key]
        if unexpected:
            raise PresentationError(
                f"deck {deck.name!r} ignored the supplied card bindings while rendering"
            )
    return presentations
