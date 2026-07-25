from __future__ import annotations

import pytest
from hypothesis import given
from pydantic import ValidationError
from rdflib import Literal, URIRef
from rdflib.namespace import XSD

from graphcards.errors import PresentationError, StorageError
from graphcards.models import CardKey, CardView, TargetKind
from tests.strategies import (
    PROPERTY_SETTINGS,
    card_keys,
    iris,
    malformed_n3,
    non_iri_terms,
    non_learnable_objects,
    safe_labels,
    triple_keys,
)


@given(key=card_keys)
@PROPERTY_SETTINGS
def test_valid_card_keys_round_trip_through_n3(key: CardKey) -> None:
    # Property: valid entity and triple CardKeys round-trip through canonical N3 storage without
    # changing their bindings, identity, or digest.
    restored = CardKey.from_n3(key.target_kind, key.n3_terms)

    assert restored == key
    assert restored.n3_terms == key.n3_terms
    assert restored.digest == key.digest
    assert restored.query_bindings == key.query_bindings


@given(entity=iris)
@PROPERTY_SETTINGS
def test_entity_and_triple_identities_are_domain_separated(entity: URIRef) -> None:
    # Property: entity and triple identities remain distinct even when they share an RDF subject.
    entity_key = CardKey.entity(entity)
    triple_key = CardKey.triple(entity, URIRef(f"{entity}#predicate"), Literal("value"))

    assert entity_key.target_kind is TargetKind.ENTITY
    assert triple_key.target_kind is TargetKind.TRIPLE
    assert entity_key.digest != triple_key.digest


@given(key=triple_keys())
@PROPERTY_SETTINGS
def test_triple_term_order_and_boundaries_affect_the_canonical_digest(key: CardKey) -> None:
    # Property: changing triple term order or term boundaries changes the canonical SHA-256 digest.
    subject, predicate, object_ = key.terms
    other_subject = URIRef(f"{subject}#subject") if subject == predicate else predicate
    reordered = CardKey.triple(other_subject, subject, object_)

    assert reordered != key
    assert reordered.digest != key.digest
    assert len(key.digest) == 64


@given(value=safe_labels)
@PROPERTY_SETTINGS
def test_literal_language_and_datatype_are_preserved_in_n3_and_digest(value: str) -> None:
    # Property: literal language and datatype annotations survive N3 serialization and affect
    # identity.
    text = value or "x"
    subject = URIRef("https://example.org/subject")
    predicate = URIRef("https://example.org/predicate")
    variants = {
        CardKey.triple(subject, predicate, Literal(text)),
        CardKey.triple(subject, predicate, Literal(text, lang="en")),
        CardKey.triple(subject, predicate, Literal("1", datatype=XSD.integer)),
        CardKey.triple(subject, predicate, Literal("1", datatype=XSD.string)),
    }

    assert all(key.n3_terms[2] for key in variants)
    assert len(variants) == 4
    assert len({key.digest for key in variants}) == 4


@given(term=non_iri_terms)
@PROPERTY_SETTINGS
def test_invalid_entity_terms_are_translated_to_presentation_errors(term: object) -> None:
    # Property: invalid entity terms are translated into repository-facing PresentationError values.
    with pytest.raises(PresentationError):
        CardKey.entity(term)  # type: ignore[arg-type]


@given(term=non_iri_terms)
@PROPERTY_SETTINGS
def test_non_iri_triple_subjects_and_predicates_are_rejected(term: object) -> None:
    # Property: non-IRI subjects and predicates are rejected as invalid learnable triple identities.
    with pytest.raises(PresentationError):
        CardKey.triple(term, URIRef("https://example.org/predicate"), Literal("object"))  # type: ignore[arg-type]
    with pytest.raises(PresentationError):
        CardKey.triple(URIRef("https://example.org/subject"), term, Literal("object"))  # type: ignore[arg-type]


@given(term=non_learnable_objects)
@PROPERTY_SETTINGS
def test_blank_or_variable_triple_objects_are_rejected(term: object) -> None:
    # Property: blank nodes and variables cannot be used as learnable triple objects.
    with pytest.raises(PresentationError):
        CardKey.triple(
            URIRef("https://example.org/subject"),
            URIRef("https://example.org/predicate"),
            term,  # type: ignore[arg-type]
        )


@given(values=malformed_n3)
@PROPERTY_SETTINGS
def test_malformed_or_non_learnable_n3_is_storage_error(values: str) -> None:
    # Property: malformed or non-learnable persisted N3 terms become StorageError values.
    with pytest.raises(StorageError):
        CardKey.from_n3(TargetKind.ENTITY, (values,))


@given(key=card_keys)
@PROPERTY_SETTINGS
def test_missing_target_bindings_are_repository_facing_errors(key: CardKey) -> None:
    # Property: missing identity bindings are reported as controlled PresentationError values.
    bindings = key.query_bindings
    missing = dict(bindings)
    missing.pop(next(iter(missing)))

    with pytest.raises(PresentationError, match="missing binding"):
        CardKey.from_bindings(key.target_kind, missing)


def test_card_view_is_frozen_and_rejects_mutation() -> None:
    # Property: frozen learner-facing models reject mutation after validation.
    view = CardView(
        card_key=CardKey.entity(URIRef("https://example.org/entity")),
        front="front",
        back="back",
    )

    with pytest.raises(ValidationError):
        view.front = "changed"  # type: ignore[misc]


@given(key=card_keys)
@PROPERTY_SETTINGS
def test_model_copy_preserves_validated_card_identity(key: CardKey) -> None:
    # Property: copying a validated CardKey preserves its validated identity and serialized fields.
    copied = key.model_copy()

    assert copied == key
    assert copied.model_dump() == key.model_dump()


@given(key=card_keys)
@PROPERTY_SETTINGS
def test_card_keys_are_frozen_after_validation(key: CardKey) -> None:
    # Property: every validated CardKey rejects mutation of its identity fields.
    with pytest.raises(ValidationError, match="frozen"):
        key.target_kind = key.target_kind  # type: ignore[misc]
