from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from graphcards.decks import (
    AnalogyExercise,
    CommonRelationExercise,
    Deck,
    MultipleChoiceExercise,
    OrderedListExercise,
)
from graphcards.errors import ConfigError
from tests.strategies import PROPERTY_SETTINGS, valid_deck_documents, valid_identity_strings


@given(document=valid_deck_documents())
@PROPERTY_SETTINGS
def test_generated_decks_load_generate_and_render_all_targets(
    document: dict[str, object], tmp_path: Path, write_deck
) -> None:
    # Property: generated valid decks cover every declared target with stable scoped identities.
    path = write_deck(tmp_path / "generated" / "deck.json", document)
    deck = Deck.load(path)
    first = deck.generate_all(rng=random.Random(0))
    second = deck.generate_all(rng=random.Random(99))

    raw_generator = document["exercises"][0]
    generator_type = raw_generator["type"]
    if generator_type == "basic":
        raw_targets = raw_generator["entities"]
    elif generator_type == "multiple_choice":
        raw_targets = raw_generator["choices"].keys()
    elif generator_type == "ordered_list":
        raw_targets = [target for group in raw_generator["groups"].values() for target in group]
    elif generator_type == "analogy":
        raw_targets = raw_generator["sources"].keys()
    else:
        raw_targets = raw_generator["relations"].keys()
    expected = {(raw_generator["id"], target_id) for target_id in raw_targets}
    actual = {(card.generator_id, card.target_id) for card in first.values()}
    assert actual == expected
    assert set(first) == set(second)
    for card in first.values():
        view = deck.render(card)
        assert view.card_key == card.card_key
        assert isinstance(view.front, str)
        assert isinstance(view.back, str)
        target = deck.entities[card.target_id]
        generator = next(item for item in deck.generators if item.id == card.generator_id)
        if generator.type == "basic":
            expected_answer = target.data.get("back", target.data.get("answer", target.id))
        elif generator.type == "analogy":
            expected_answer = target.data.get(
                "back", target.data.get("answer", target.data.get("label", target.id))
            )
        else:
            expected_answer = target.data.get(
                "label", target.data.get("back", target.data.get("answer", target.id))
            )
        assert view.back == str(expected_answer)


@given(document=valid_deck_documents())
@PROPERTY_SETTINGS
def test_generated_generator_invariants_hold(
    document: dict[str, object], tmp_path: Path, write_deck
) -> None:
    # Property: each generator preserves its target, uniqueness, bounds, and window invariants.
    deck = Deck.load(write_deck(tmp_path / "generated" / "deck.json", document))
    for card in deck.generate_all(rng=random.Random(4)).values():
        if isinstance(card, MultipleChoiceExercise):
            assert card.target_id in card.choices
            assert len(card.choices) == len(set(card.choices))
            generator = next(item for item in deck.generators if item.id == card.generator_id)
            assert len(card.choices) <= generator.max_choices
            assert set(card.choices) <= {card.target_id, *generator.choices[card.target_id]}
        elif isinstance(card, OrderedListExercise):
            assert card.target_id in card.ordered_ids
            assert len(card.ordered_ids) == len(set(card.ordered_ids))
            assert len(card.ordered_ids) >= 2
            front = deck.render(card).front
            assert front.count("?") == 1
            positions = [int(match.group(1)) for match in re.finditer(r"(?m)^(\d+)\. ", front)]
            assert positions == list(range(positions[0], positions[-1] + 1))
            generator = next(item for item in deck.generators if item.id == card.generator_id)
            if generator.window_size:
                assert len(positions) <= generator.window_size
            assert card.ordered_ids.index(card.target_id) + 1 in positions
        elif isinstance(card, AnalogyExercise):
            assert card.source_id != card.target_id
            generator = next(item for item in deck.generators if item.id == card.generator_id)
            assert card.source_id in generator.sources[card.target_id]
        elif isinstance(card, CommonRelationExercise):
            generator = next(item for item in deck.generators if item.id == card.generator_id)
            assert card.direction == generator.direction
            related = generator.relations[card.target_id]
            assert len(card.related_ids) == len(set(card.related_ids))
            assert len(card.related_ids) >= generator.min_examples
            assert set(card.related_ids) <= set(related)
            assert card.related_ids == tuple(
                related_id for related_id in related if related_id in card.related_ids
            )
            if generator.max_related:
                assert len(card.related_ids) == min(generator.max_related, len(related))
            else:
                assert card.related_ids == related
            assert deck.render(card).back == f"label-{card.target_id}"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda document: document["entities"].append({"id": "e0"}), "duplicate entity ID"),
        (
            lambda document: document["exercises"][0]["entities"].append("missing"),
            "unknown entity",
        ),
        (
            lambda document: document["exercises"][0].update({"front_template": "{{ unknown }}"}),
            "unknown template variable",
        ),
    ],
)
def test_invalid_generated_deck_documents_are_repository_facing_errors(
    mutation, message: str, tmp_path: Path, write_deck
) -> None:
    # Property: duplicate IDs, missing references, and bad templates become ConfigErrors.
    document = {
        "entities": [{"id": "e0"}, {"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
        "exercises": [{"id": "generator", "type": "basic", "entities": ["e0"]}],
    }
    mutation(document)
    with pytest.raises(ConfigError, match=message):
        Deck.load(write_deck(tmp_path / "invalid" / "deck.json", document))


@pytest.mark.parametrize(
    ("generator", "message"),
    [
        (
            {"id": "generator", "type": "analogy", "sources": {}},
            "define analogy sources",
        ),
        (
            {"id": "generator", "type": "analogy", "sources": {"e0": []}},
            "at least one source",
        ),
        (
            {"id": "generator", "type": "analogy", "sources": {"e0": ["e1", "e1"]}},
            "duplicate sources",
        ),
        (
            {"id": "generator", "type": "multiple_choice", "choices": {"e0": ["e0"]}},
            "cannot be in its distractor pool",
        ),
        (
            {
                "id": "generator",
                "type": "ordered_list",
                "groups": {"e0": ["e1", "e1"]},
            },
            "duplicate members",
        ),
        (
            {"id": "generator", "type": "analogy", "sources": {"e0": ["e0"]}},
            "cannot use itself",
        ),
    ],
)
def test_each_generator_rejects_invalid_pools_groups_and_sources(
    generator: dict[str, object], message: str, tmp_path: Path, write_deck
) -> None:
    # Property: generator pools, groups, and analogy sources reject invalid relationships.
    document = {
        "entities": [{"id": "e0"}, {"id": "e1"}, {"id": "e2"}],
        "exercises": [generator],
    }
    with pytest.raises(ConfigError, match=message):
        Deck.load(write_deck(tmp_path / "invalid" / "deck.json", document))


@given(
    kind=st.sampled_from(
        ["basic", "multiple_choice", "ordered_list", "analogy", "common_relation"]
    ),
    unknown=valid_identity_strings.filter(lambda value: value not in {"e0", "e1", "e2"}),
)
@PROPERTY_SETTINGS
def test_generated_invalid_references_are_config_errors(
    kind: str, unknown: str, tmp_path: Path, write_deck
) -> None:
    # Property: every generated unknown entity reference is rejected before generation.
    if kind == "basic":
        generator = {"id": "generator", "type": kind, "entities": [unknown]}
    elif kind == "multiple_choice":
        generator = {"id": "generator", "type": kind, "choices": {"e0": [unknown]}}
    elif kind == "ordered_list":
        generator = {"id": "generator", "type": kind, "groups": {"e0": ["e1", unknown]}}
    elif kind == "analogy":
        generator = {"id": "generator", "type": kind, "sources": {"e0": [unknown]}}
    else:
        generator = {
            "id": "generator",
            "type": kind,
            "direction": "object",
            "relations": {"e0": ["e2", unknown]},
        }
    document = {
        "entities": [{"id": "e0"}, {"id": "e1"}, {"id": "e2"}],
        "exercises": [generator],
    }
    with pytest.raises(ConfigError, match="unknown"):
        Deck.load(write_deck(tmp_path / "invalid-generated" / "deck.json", document))


@given(
    related=st.lists(
        valid_identity_strings.filter(lambda value: value != "target"),
        min_size=0,
        max_size=4,
        unique=True,
    ),
    min_examples=st.integers(min_value=2, max_value=4),
    max_related=st.integers(min_value=0, max_value=3),
)
@PROPERTY_SETTINGS
def test_generated_common_relation_invalid_bounds_are_config_errors(
    related: list[str], min_examples: int, max_related: int, tmp_path: Path, write_deck
) -> None:
    assume(len(related) < min_examples or (max_related != 0 and max_related < min_examples))
    document = {
        "entities": [{"id": entity_id} for entity_id in ["target", *related]],
        "exercises": [
            {
                "id": "generator",
                "type": "common_relation",
                "direction": "object",
                "min_examples": min_examples,
                "max_related": max_related,
                "relations": {"target": related},
            }
        ],
    }
    with pytest.raises(ConfigError):
        Deck.load(write_deck(tmp_path / "invalid-common-bounds" / "deck.json", document))


@given(duplicate=valid_identity_strings)
@PROPERTY_SETTINGS
def test_generated_duplicate_entity_ids_are_config_errors(
    duplicate: str, tmp_path: Path, write_deck
) -> None:
    # Property: duplicate generated entity IDs cannot be loaded as a deck.
    document = {
        "entities": [{"id": "e0"}, {"id": duplicate}, {"id": duplicate}],
        "exercises": [],
    }
    with pytest.raises(ConfigError, match="duplicate entity ID"):
        Deck.load(write_deck(tmp_path / "duplicate" / "deck.json", document))


@given(template=st.sampled_from(["{{ unknown }}", "{{", "{% for value in entity %}"]))
@PROPERTY_SETTINGS
def test_generated_invalid_templates_are_config_errors(
    template: str, tmp_path: Path, write_deck
) -> None:
    # Property: malformed or unknown templates are rejected during deck validation.
    document = {
        "entities": [{"id": "e0", "label": "Entity"}],
        "exercises": [
            {
                "id": "generator",
                "type": "basic",
                "entities": ["e0"],
                "front_template": template,
            }
        ],
    }
    with pytest.raises(ConfigError):
        Deck.load(write_deck(tmp_path / "invalid-template" / "deck.json", document))


def test_analogy_preflight_checks_every_declared_source(tmp_path: Path, write_deck) -> None:
    # Property: analogy preflight validates rendering for every declared source, not just one.
    path = write_deck(
        tmp_path / "invalid-analogy" / "deck.json",
        {
            "entities": [
                {"id": "good", "answer": "Good"},
                {"id": "bad"},
                {"id": "target", "front": "Target"},
            ],
            "exercises": [
                {
                    "id": "analogy",
                    "type": "analogy",
                    "sources": {"target": ["good", "bad"]},
                    "front_template": "{{ source.data.get('answer').value }}",
                }
            ],
        },
    )
    with pytest.raises(ConfigError, match="could not render card template"):
        Deck.load(path)


def test_deck_documents_reject_duplicate_json_fields(tmp_path: Path, write_deck) -> None:
    # Property: duplicate JSON object fields are surfaced as repository-facing configuration errors.
    path = tmp_path / "invalid" / "deck.json"
    path.parent.mkdir()
    path.write_text(
        '{"entities":[{"id":"e0"}],"entities":[{"id":"e1"}],"exercises":[]}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate JSON field"):
        Deck.load(path)


def test_generated_document_is_json_round_trippable(tmp_path: Path, write_deck) -> None:
    # Property: JSON serialization preserves the meaning of a generated deck document.
    document = {
        "entities": [{"id": "e0", "data": {"items": [1, True]}}],
        "exercises": [],
    }
    raw = json.loads(json.dumps(document))
    assert (
        Deck.load(write_deck(tmp_path / "round-trip" / "deck.json", raw)).entities["e0"].id == "e0"
    )
