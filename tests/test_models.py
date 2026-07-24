from __future__ import annotations

import pytest
from pydantic import ValidationError
from rdflib import BNode, Literal, URIRef
from rdflib.namespace import XSD

from graphcards.errors import PresentationError
from graphcards.models import CardKey, TargetKind

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


def test_hash_preserves_literal_language_and_datatype() -> None:
    plain = triple(Literal("one"))
    english = triple(Literal("one", lang="en"))
    integer = triple(Literal("1", datatype=XSD.integer))
    string = triple(Literal("1", datatype=XSD.string))
    assert len({plain.digest, english.digest, integer.digest, string.digest}) == 4


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


def test_n3_round_trip() -> None:
    original = triple(Literal("bonjour", lang="fr"))
    restored = CardKey.from_n3(TargetKind.TRIPLE, original.n3_terms)
    assert restored == original
    assert restored.digest == original.digest


def test_entity_hash_is_stable_and_separate_from_triple_hashes() -> None:
    entity = CardKey.entity(URIRef(EX + "s"))
    assert entity.digest == CardKey.entity(URIRef(EX + "s")).digest
    assert entity.digest != triple().digest
    assert entity.target_kind is TargetKind.ENTITY


@pytest.mark.parametrize("term", [Literal("entity"), BNode()])
def test_entity_key_requires_an_iri(term: object) -> None:
    with pytest.raises(PresentationError, match="IRI"):
        CardKey.entity(term)  # type: ignore[arg-type]


def test_entity_n3_round_trip() -> None:
    original = CardKey.entity(URIRef(EX + "entity"))
    restored = CardKey.from_n3(TargetKind.ENTITY, original.n3_terms)
    assert restored == original
    assert restored.digest == original.digest


def test_card_keys_are_immutable_pydantic_models() -> None:
    key = triple()
    with pytest.raises(ValidationError, match="frozen"):
        key.target_kind = TargetKind.ENTITY  # type: ignore[misc]
