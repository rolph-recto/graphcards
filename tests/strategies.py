"""Small, composable Hypothesis strategies shared by property suites."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

from graphcards.decks.base import _RESERVED_ENTITY_FIELDS
from graphcards.models import CardKey
from graphcards.web.status import (
    AvailabilityFilter,
    CardSort,
    FsrsStateFilter,
    HistoryRange,
    ScheduleFilter,
    SortDirection,
)

PROPERTY_SETTINGS = settings(
    max_examples=30,
    deadline=None,
    database=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
EXPENSIVE_PROPERTY_SETTINGS = settings(
    max_examples=8,
    deadline=None,
    database=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

SAFE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-_"
identity_strings = st.text(
    alphabet=SAFE_ALPHABET,
    min_size=1,
    max_size=16,
).filter(lambda value: value.strip() == value)
valid_identity_strings = identity_strings
invalid_identity_strings = st.one_of(
    st.sampled_from(["", " ", "\t", "\n", "\r"]),
    st.sampled_from(["valid\nvalue", "valid\u200bvalue", "valid\u2028value"]),
)

json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-100_000, max_value=100_000),
    st.floats(
        min_value=-100_000,
        max_value=100_000,
        allow_nan=False,
        allow_infinity=False,
        width=32,
    ),
    st.text(max_size=32),
)
json_keys = st.text(alphabet=SAFE_ALPHABET, min_size=1, max_size=10)
json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(json_keys, children, max_size=4),
    ),
    max_leaves=20,
)
_ENTITY_DATA_KEYS = json_keys.filter(
    lambda key: key != "id" and not key.startswith("_") and key not in _RESERVED_ENTITY_FIELDS
)
entity_data = st.dictionaries(
    _ENTITY_DATA_KEYS,
    json_values,
    max_size=4,
)


@st.composite
def entity_ids(draw: st.DrawFn, *, min_size: int = 2, max_size: int = 6) -> list[str]:
    return draw(
        st.lists(
            valid_identity_strings,
            min_size=min_size,
            max_size=max_size,
            unique=True,
        )
    )


@st.composite
def valid_deck_documents(draw: st.DrawFn) -> dict[str, Any]:
    ids = draw(entity_ids(min_size=4, max_size=6))
    generator_type = draw(
        st.sampled_from(
            [
                "basic",
                "multiple_choice",
                "missing_sequence_item",
                "scrambled_list",
                "analogy",
                "common_relation",
            ]
        )
    )
    entities = [{"id": entity_id, "label": f"label-{entity_id}"} for entity_id in ids]
    if generator_type == "basic":
        generator = {"id": "generator", "type": "basic", "entities": ids[:3]}
    elif generator_type == "multiple_choice":
        generator = {
            "id": "generator",
            "type": "multiple_choice",
            "max_choices": draw(st.integers(min_value=2, max_value=4)),
            "choices": {ids[0]: ids[1:]},
        }
    elif generator_type == "missing_sequence_item":
        generator = {
            "id": "generator",
            "type": "missing_sequence_item",
            "window_size": draw(st.integers(min_value=0, max_value=len(ids))),
            "groups": {ids[0]: ids[1:]},
        }
    elif generator_type == "scrambled_list":
        generator = {
            "id": "generator",
            "type": "scrambled_list",
            "groups": {ids[0]: ids[1:]},
        }
    elif generator_type == "analogy":
        generator = {
            "id": "generator",
            "type": "analogy",
            "sources": {ids[0]: ids[1:]},
        }
    else:
        relations = {ids[0]: ids[2:]}
        if len(ids) == 6 and draw(st.booleans()):
            relations[ids[2]] = ids[4:]
        smallest_group = min(len(related) for related in relations.values())
        min_examples = draw(st.integers(min_value=2, max_value=smallest_group))
        generator = {
            "id": "generator",
            "type": "common_relation",
            "min_examples": min_examples,
            "max_related": draw(st.sampled_from([0, *range(min_examples, len(ids[2:]) + 3)])),
            "relations": relations,
        }
    return {"entities": entities, "exercises": [generator]}


@st.composite
def valid_generator_documents(draw: st.DrawFn) -> dict[str, Any]:
    return draw(valid_deck_documents())


@st.composite
def card_keys(draw: st.DrawFn, *, deck_id: str = "deck") -> CardKey:
    return CardKey.exercise(
        deck_id,
        draw(valid_identity_strings),
        draw(valid_identity_strings),
    )


def aware_datetimes() -> st.SearchStrategy[datetime]:
    return st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2035, 12, 31, 23, 59, 59),
        timezones=st.sampled_from(
            [UTC, timezone(timedelta(hours=5)), timezone(timedelta(hours=-7))]
        ),
    )


def card_ids() -> st.SearchStrategy[str]:
    return st.binary(min_size=32, max_size=32).map(lambda value: value.hex())


def tokens() -> st.SearchStrategy[str]:
    return st.text(alphabet=SAFE_ALPHABET, min_size=1, max_size=32)


def invalid_card_ids() -> st.SearchStrategy[str]:
    return st.one_of(st.text(max_size=12), st.binary(max_size=31).map(lambda value: value.hex()))


def status_queries() -> st.SearchStrategy[dict[str, object]]:
    return st.fixed_dictionaries(
        {
            "page": st.integers(min_value=1, max_value=4),
            "availability": st.sampled_from(list(AvailabilityFilter)),
            "schedule": st.sampled_from(list(ScheduleFilter)),
            "state": st.sampled_from(list(FsrsStateFilter)),
            "sort": st.sampled_from(list(CardSort)),
            "direction": st.sampled_from(list(SortDirection)),
            "range": st.sampled_from(list(HistoryRange)),
        }
    )


def url_values() -> st.SearchStrategy[str]:
    return st.one_of(
        valid_identity_strings,
        st.sampled_from(["", "<b>unsafe</b>", "a+b", "%FF", "%ZZ", "a\nvalue"]),
    )


def form_values() -> st.SearchStrategy[str]:
    return st.one_of(url_values(), st.integers(min_value=-2, max_value=400).map(str))


def malformed_query_values() -> st.SearchStrategy[str]:
    return st.sampled_from(
        [
            "%ZZ",
            "%A",
            "%FF",
            "state=unknown",
            "sort=unknown&sort=asc",
            "page=0",
            "page=-1",
            "page=nope",
            "page=1&page=2",
        ]
    )


def suspension_reasons() -> st.SearchStrategy[str]:
    return st.one_of(
        st.text(alphabet=SAFE_ALPHABET + " <>", max_size=40),
        st.sampled_from(["", "<b>unsafe</b>", "\u200binvalid", "line\u2028break", "x" * 501]),
    )


def fsrs_fragments() -> st.SearchStrategy[dict[str, object]]:
    return st.fixed_dictionaries(
        {
            "desired_retention": st.floats(
                min_value=0.01, max_value=1, allow_nan=False, allow_infinity=False
            ),
            "maximum_interval": st.integers(min_value=1, max_value=36500),
            "learning_steps_minutes": st.lists(st.integers(1, 120), min_size=1, max_size=3),
            "relearning_steps_minutes": st.lists(st.integers(1, 120), min_size=1, max_size=3),
            "enable_fuzzing": st.booleans(),
        }
    )


def nested_json(depth: int) -> object:
    value: object = "leaf"
    for _ in range(depth):
        value = {"nested": value}
    return value


def future_or_past_datetimes() -> st.SearchStrategy[datetime]:
    return aware_datetimes().map(lambda value: value + timedelta(days=1))
