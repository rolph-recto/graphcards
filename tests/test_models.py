from __future__ import annotations

import pytest
from rdflib import BNode, Literal, URIRef

from graphcards.errors import PresentationError
from graphcards.models import CardKey

EX = "https://example.org/"


def triple(object_: object = URIRef(EX + "o")) -> CardKey:
    return CardKey.triple(
        URIRef(EX + "s"),
        URIRef(EX + "p"),
        object_,  # type: ignore[arg-type]
    )


def test_hash_is_stable_and_order_sensitive() -> None:
    first = triple()
    assert first.digest == triple().digest
    assert first.digest == "dfbb3aa1d4034c83e3cf563f64aacfd4de6bfdc418f26facb0d5755fe99661d3"
    reversed_terms = CardKey.triple(*reversed(first.terms))
    assert first.digest != reversed_terms.digest
    assert len(first.digest) == 64


def test_length_prefixes_prevent_term_boundary_ambiguity() -> None:
    first = CardKey.triple(URIRef(EX + "ab"), URIRef(EX + "c"), Literal("d"))
    second = CardKey.triple(URIRef(EX + "a"), URIRef(EX + "bc"), Literal("d"))
    assert first.digest != second.digest


@pytest.mark.parametrize("position", ["subject", "object"])
def test_blank_nodes_are_rejected(position: str) -> None:
    values = {
        "subject": URIRef(EX + "s"),
        "predicate": URIRef(EX + "p"),
        "object": URIRef(EX + "o"),
    }
    values[position] = BNode()
    with pytest.raises(PresentationError, match="blank nodes"):
        CardKey.triple(values["subject"], values["predicate"], values["object"])
