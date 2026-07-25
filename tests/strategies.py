"""Small, bounded Hypothesis strategies shared by the property suites."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fsrs import Card as FsrsCard
from hypothesis import settings
from hypothesis import strategies as st
from rdflib import BNode, Literal, URIRef, Variable
from rdflib.namespace import XSD
from rdflib.term import Identifier

from graphcards.decks import (
    AnalogyCard,
    BasicCard,
    MultipleChoiceCard,
    OrderedListCard,
    OrderedListRow,
)
from graphcards.models import CardKey
from graphcards.storage import StoredCard

# The profile is deliberately local to the test package: application code does not
# inherit Hypothesis settings, and expensive suites opt into their smaller profile.
settings.register_profile(
    "graphcards",
    max_examples=30,
    derandomize=True,
    deadline=None,
)
settings.register_profile(
    "graphcards_expensive",
    max_examples=8,
    derandomize=True,
    deadline=None,
)
settings.load_profile("graphcards")

PROPERTY_SETTINGS = settings(max_examples=30, derandomize=True, deadline=None)
EXPENSIVE_PROPERTY_SETTINGS = settings(max_examples=8, derandomize=True, deadline=None)

_SEGMENT_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
_LABEL_ALPHABET = "abcXYZ012 -_<>&'\""
_LANGUAGES = st.sampled_from(["en", "en-US", "fr", "de"])
_DATATYPES = st.sampled_from([XSD.string, XSD.integer, XSD.boolean])


safe_labels = st.text(alphabet=_LABEL_ALPHABET, min_size=0, max_size=24)
nonempty_labels = safe_labels.filter(bool)
deck_names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=16)
iri_segments = st.text(alphabet=_SEGMENT_ALPHABET, min_size=1, max_size=16)
iris = iri_segments.map(lambda value: URIRef(f"https://example.org/{value}"))


@st.composite
def literals(draw: st.DrawFn) -> Literal:
    value = draw(safe_labels)
    kind = draw(st.sampled_from(["plain", "language", "datatype"]))
    if kind == "language":
        return Literal(value, lang=draw(_LANGUAGES))
    if kind == "datatype":
        datatype = draw(_DATATYPES)
        if datatype == XSD.integer:
            value = str(draw(st.integers(-100, 100)))
        elif datatype == XSD.boolean:
            value = draw(st.sampled_from(["true", "false", "1", "0"]))
        return Literal(value, datatype=datatype)
    return Literal(value)


rdf_identifiers = st.one_of(iris, literals())
triple_objects = st.one_of(iris, literals())
non_iri_terms = st.one_of(
    literals(), st.builds(BNode, iri_segments), st.builds(Variable, iri_segments)
)
non_learnable_objects = st.one_of(st.builds(BNode, iri_segments), st.builds(Variable, iri_segments))
malformed_n3 = st.sampled_from(
    ["", "not n3", "<", "<https://example.org/missing", '"unterminated', "_:blank"]
)


@st.composite
def entity_keys(draw: st.DrawFn) -> CardKey:
    return CardKey.entity(draw(iris))


@st.composite
def triple_keys(draw: st.DrawFn) -> CardKey:
    return CardKey.triple(draw(iris), draw(iris), draw(triple_objects))


card_keys = st.one_of(entity_keys(), triple_keys())


@st.composite
def basic_cards(draw: st.DrawFn) -> BasicCard:
    return BasicCard(
        card_key=draw(card_keys),
        front=draw(rdf_identifiers),
        back=draw(rdf_identifiers),
    )


@st.composite
def multiple_choice_cards(draw: st.DrawFn) -> MultipleChoiceCard:
    choices = draw(
        st.lists(rdf_identifiers, min_size=2, max_size=6, unique_by=lambda term: term.n3())
    )
    return MultipleChoiceCard(
        card_key=draw(entity_keys()),
        front=draw(rdf_identifiers),
        back=draw(st.sampled_from(choices)),
        choices=tuple(choices),
    )


@st.composite
def ordered_list_cards(draw: st.DrawFn) -> OrderedListCard:
    count = draw(st.integers(min_value=2, max_value=8))
    entities = draw(st.lists(iris, min_size=count, max_size=count, unique_by=str))
    labels = draw(st.lists(rdf_identifiers, min_size=count, max_size=count))
    group = draw(iris)
    rows = tuple(
        OrderedListRow(entity=entity, group=group, position=position, label=label)
        for position, (entity, label) in enumerate(zip(entities, labels, strict=True), start=1)
    )
    hidden_index = draw(st.integers(min_value=0, max_value=count - 1))
    return OrderedListCard(
        card_key=CardKey.entity(entities[hidden_index]),
        ordered_rows=rows,
        hidden_position=hidden_index + 1,
    )


@st.composite
def analogy_cards(draw: st.DrawFn) -> AnalogyCard:
    target_subject = draw(iris)
    predicate = draw(iris)
    target_object = draw(triple_objects)
    source_subject = draw(iris)
    source_object = draw(triple_objects)
    if (source_subject, predicate, source_object) == (
        target_subject,
        predicate,
        target_object,
    ):
        source_subject = URIRef(f"{source_subject}#source")
    optional_label = st.one_of(st.none(), rdf_identifiers)
    return AnalogyCard(
        card_key=CardKey.triple(target_subject, predicate, target_object),
        source_subject=source_subject,
        source_predicate=predicate,
        source_object=source_object,
        hide=draw(st.sampled_from(["subject", "object"])),
        subject_label=draw(optional_label),
        predicate_label=draw(optional_label),
        object_label=draw(optional_label),
        source_subject_label=draw(optional_label),
        source_predicate_label=draw(optional_label),
        source_object_label=draw(optional_label),
    )


@st.composite
def prioritized_candidates(draw: st.DrawFn) -> list[tuple[Identifier, bool, int]]:
    count = draw(st.integers(min_value=2, max_value=8))
    values = draw(
        st.lists(rdf_identifiers, min_size=count, max_size=count, unique_by=lambda x: x.n3())
    )
    correct_index = draw(st.integers(min_value=0, max_value=count - 1))
    priorities = draw(st.lists(st.integers(0, 4), min_size=count, max_size=count))
    return [
        (value, index == correct_index, priority)
        for index, (value, priority) in enumerate(zip(values, priorities, strict=True))
    ]


@st.composite
def stored_cards(draw: st.DrawFn) -> StoredCard:
    key = draw(card_keys)
    fsrs_card = FsrsCard()
    return StoredCard(card_id=key.digest, card_key=key, card_json=fsrs_card.to_json())


aware_datetimes = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31, 23, 59, 59),
    timezones=st.just(UTC),
)
durations = st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=365))
fsrs_fragments = st.fixed_dictionaries(
    {
        "desired_retention": st.floats(
            min_value=0.01, max_value=1, allow_nan=False, allow_infinity=False
        ),
        "maximum_interval": st.integers(min_value=1, max_value=36500),
        "enable_fuzzing": st.booleans(),
    }
)
config_fragments = st.fixed_dictionaries(
    {
        "state_path": iri_segments.map(lambda name: Path(f".graphcards/{name}.sqlite3")),
        "display_timezone": st.sampled_from(["UTC", "America/New_York", "Europe/Paris"]),
        "sources": st.lists(iri_segments.map(lambda name: Path(f"data/{name}.ttl")), max_size=2),
    },
    optional={"fsrs": fsrs_fragments},
)

valid_card_ids = card_keys.map(lambda key: key.digest)
invalid_card_ids = st.one_of(
    st.text(alphabet="0123456789abcdef", min_size=0, max_size=63),
    st.text(alphabet="0123456789ABCDEFxyz-", min_size=1, max_size=80),
)
session_tokens = st.one_of(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=32),
    st.sampled_from(["wrong", "", "not-a-token"]),
)
url_values = st.one_of(
    safe_labels,
    st.sampled_from(["%", "%A", "%ZZ", "%FF", "a+b", "<script>", "\ud800"]),
)
pagination_inputs = st.one_of(
    st.integers(min_value=1, max_value=105).map(str),
    st.sampled_from(["0", "-1", "1.5", "", "999999999999999999999"]),
)
form_values: st.SearchStrategy[Any] = st.one_of(url_values, invalid_card_ids, session_tokens)
