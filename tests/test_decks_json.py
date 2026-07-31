from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from graphcards.decks import (
    AnalogyExercise,
    BasicExercise,
    BasicExerciseGenerator,
    CommonRelationExercise,
    CommonRelationExerciseGenerator,
    Deck,
    DeckDocument,
    Entity,
    ExerciseGeneratorContext,
    MissingSequenceItemExercise,
    MultipleChoiceExercise,
)
from graphcards.errors import ConfigError, PresentationError


def test_loads_typed_generators_and_nested_entity_data(deck: Deck) -> None:
    assert tuple(type(generator).__name__ for generator in deck.generators) == (
        "BasicExerciseGenerator",
        "MultipleChoiceExerciseGenerator",
        "MissingSequenceItemExerciseGenerator",
    )
    assert deck.entities["france"].front == "France"
    assert deck.entities["france"].id == "france"


def test_json_validation_dispatches_typed_generator_definitions() -> None:
    document = DeckDocument.model_validate_json(
        json.dumps(
            {
                "entities": [{"id": "target"}],
                "exercises": [{"id": "basic", "type": "basic", "entities": ["target"]}],
            }
        )
    )
    assert isinstance(document.exercises[0], BasicExerciseGenerator)


def test_common_relation_is_dispatched_and_exported() -> None:
    document = DeckDocument.model_validate(
        {
            "entities": [
                {"id": "target"},
                {"id": "related-1"},
                {"id": "related-2"},
            ],
            "exercises": [
                {
                    "id": "common",
                    "type": "common_relation",
                    "relations": {"target": ["related-1", "related-2"]},
                }
            ],
        }
    )
    generator = document.exercises[0]
    assert isinstance(generator, CommonRelationExerciseGenerator)
    assert generator.relations["target"] == ("related-1", "related-2")
    assert generator.target_ids == ("target",)


def test_common_relation_defaults_render_related_entities(tmp_path: Path, write_deck) -> None:
    target_id = "europe"
    related_ids = ["france", "germany"]
    entities = [
        {"id": target_id, "label": "Europe"},
        *[
            {"id": related_id, "label": name}
            for related_id, name in zip(
                related_ids,
                ["France", "Germany"],
                strict=True,
            )
        ],
    ]
    deck = Deck.load(
        write_deck(
            tmp_path / "default" / "deck.json",
            {
                "entities": entities,
                "exercises": [
                    {
                        "id": "common",
                        "type": "common_relation",
                        "relations": {target_id: related_ids},
                    }
                ],
            },
        )
    )
    card = next(iter(deck.generate_all(rng=random.Random(0)).values()))
    assert isinstance(card, CommonRelationExercise)
    view = deck.render(card)
    assert view.front == "France — ?\nGermany — ?"
    assert view.back == "Europe"


def test_common_relation_labels_use_all_fallbacks_and_payload_is_semantic(
    tmp_path: Path, write_deck
) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "fallbacks" / "deck.json",
            {
                "entities": [
                    {"id": "target", "answer": "Target answer"},
                    {"id": "related-label", "label": "Related label"},
                    {"id": "related-id"},
                ],
                "exercises": [
                    {
                        "id": "common",
                        "type": "common_relation",
                        "relations": {"target": ["related-label", "related-id"]},
                    }
                ],
            },
        )
    )
    card = next(iter(deck.generate_all(rng=random.Random(5)).values()))
    assert isinstance(card, CommonRelationExercise)
    assert card.related_ids == ("related-label", "related-id")
    assert "Target answer" not in card.model_dump_json()
    assert deck.render(card).front == "Related label — ?\nrelated-id — ?"
    assert deck.render(card).back == "Target answer"


def test_builtin_templates_use_direct_attribute_fallbacks(tmp_path: Path, write_deck) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "direct-fallbacks" / "deck.json",
            {
                "entities": [
                    {"id": "basic-target"},
                    {"id": "multiple-target", "prompt": "Choose", "answer": "Correct"},
                    {"id": "multiple-choice", "label": "Distractor"},
                    {"id": "ordered-one"},
                    {"id": "ordered-two", "back": "Second"},
                    {"id": "ordered-group"},
                    {
                        "id": "analogy-source",
                        "question": "Source question",
                        "label": "Source label",
                    },
                    {
                        "id": "analogy-target",
                        "front": "Target front",
                        "answer": "Target answer",
                    },
                    {"id": "relation-target", "label": "Relation answer"},
                    {"id": "relation-related", "answer": "Related answer"},
                ],
                "exercises": [
                    {"id": "basic", "type": "basic", "entities": ["basic-target"]},
                    {
                        "id": "multiple",
                        "type": "multiple_choice",
                        "choices": {"multiple-target": ["multiple-choice"]},
                    },
                    {
                        "id": "ordered",
                        "type": "missing_sequence_item",
                        "groups": {"ordered-group": ["ordered-one", "ordered-two"]},
                    },
                    {
                        "id": "analogy",
                        "type": "analogy",
                        "sources": {"analogy-target": ["analogy-source"]},
                    },
                    {
                        "id": "relation",
                        "type": "common_relation",
                        "relations": {"relation-target": ["relation-related", "basic-target"]},
                    },
                ],
            },
        )
    )
    cards = deck.generate_all(rng=random.Random(0))
    views = {
        "basic": deck.render(next(card for card in cards.values() if card.generator_id == "basic")),
        "multiple": deck.render(
            next(card for card in cards.values() if card.generator_id == "multiple")
        ),
        "ordered": deck.render(
            next(
                card
                for card in cards.values()
                if card.generator_id == "ordered" and card.target_id == "ordered-one"
            )
        ),
        "analogy": deck.render(
            next(card for card in cards.values() if card.generator_id == "analogy")
        ),
        "relation": deck.render(
            next(card for card in cards.values() if card.generator_id == "relation")
        ),
    }

    assert (views["basic"].front, views["basic"].back) == ("basic-target", "basic-target")
    assert views["multiple"].front.startswith("Choose\n")
    assert {
        line.split(". ", maxsplit=1)[1] for line in views["multiple"].front.splitlines()[1:]
    } == {"Correct", "Distractor"}
    assert views["multiple"].back == "Correct"
    assert views["ordered"].front == "1. ?\n2. Second"
    assert views["ordered"].back == "ordered-one"
    assert views["analogy"].front == "Source question is to Source label as Target front is to ?"
    assert views["analogy"].back == "Target answer"
    assert views["relation"].front == "Related answer — ?\nbasic-target — ?"
    assert views["relation"].back == "Relation answer"


def test_common_relation_label_precedence_covers_each_entity_role(
    tmp_path: Path, write_deck
) -> None:
    entities: list[dict[str, object]] = []
    relations: dict[str, list[str]] = {}
    expected: list[tuple[str, str]] = []
    for index, source in enumerate(["label", "back", "answer", "id"], start=1):
        target_id = f"target-{index}"
        related_ids = [f"related-{index}-a", f"related-{index}-b"]
        entities.append(
            {"id": target_id, **({source: f"Target {index}"} if source != "id" else {})}
        )
        for related_id, suffix in zip(related_ids, ["a", "b"], strict=True):
            entities.append(
                {
                    "id": related_id,
                    **({source: f"Related {index}{suffix}"} if source != "id" else {}),
                }
            )
        relations[target_id] = related_ids
        target_label = f"Target {index}" if source != "id" else target_id
        related_label = f"Related {index}a" if source != "id" else related_ids[0]
        expected.append((target_label, related_label))

    deck = Deck.load(
        write_deck(
            tmp_path / "precedence" / "deck.json",
            {
                "entities": entities,
                "exercises": [
                    {
                        "id": "common",
                        "type": "common_relation",
                        "relations": relations,
                    }
                ],
            },
        )
    )
    cards = deck.generate_all(rng=random.Random(0))
    for target_id, (target_label, related_label) in zip(relations, expected, strict=True):
        card = cards[next(card_id for card_id in cards if cards[card_id].target_id == target_id)]
        view = deck.render(card)
        assert view.front == (f"{related_label} — ?\n{related_label[:-1]}b — ?")
        assert view.back == target_label


def test_common_relation_cap_is_exact_ordered_and_identity_stable(
    tmp_path: Path, write_deck
) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "capped" / "deck.json",
            {
                "entities": [{"id": entity_id} for entity_id in ["target", "a", "b", "c", "d"]],
                "exercises": [
                    {
                        "id": "common",
                        "type": "common_relation",
                        "max_related": 2,
                        "relations": {"target": ["a", "b", "c", "d"]},
                    }
                ],
            },
        )
    )
    cards = [next(iter(deck.generate_all(rng=random.Random(seed)).values())) for seed in range(8)]
    assert all(isinstance(card, CommonRelationExercise) for card in cards)
    assert all(len(card.related_ids) == len(set(card.related_ids)) == 2 for card in cards)
    assert all(set(card.related_ids) <= {"a", "b", "c", "d"} for card in cards)
    assert all(
        card.related_ids
        == tuple(entity_id for entity_id in ["a", "b", "c", "d"] if entity_id in card.related_ids)
        for card in cards
    )
    assert len({card.card_key for card in cards}) == 1


def test_common_relation_cap_covering_group_does_not_consume_rng(
    tmp_path: Path, write_deck
) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "uncapped" / "deck.json",
            {
                "entities": [{"id": entity_id} for entity_id in ["target", "a", "b"]],
                "exercises": [
                    {
                        "id": "common",
                        "type": "common_relation",
                        "max_related": 4,
                        "relations": {"target": ["a", "b"]},
                    }
                ],
            },
        )
    )
    rng = random.Random(9)
    before = rng.getstate()
    card = next(iter(deck.generate_all(rng=rng).values()))
    assert isinstance(card, CommonRelationExercise)
    assert card.related_ids == ("a", "b")
    assert rng.getstate() == before


def test_common_relation_custom_templates_receive_only_semantic_context(
    tmp_path: Path, write_deck
) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "custom" / "deck.json",
            {
                "entities": [{"id": entity_id} for entity_id in ["target", "a", "b"]],
                "exercises": [
                    {
                        "id": "common",
                        "type": "common_relation",
                        "relations": {"target": ["a", "b"]},
                        "front_template": (
                            "{{ target.id }}|{{ related_entities[0].id }}|"
                            "{{ related_entities[1].id }}"
                        ),
                        "back_template": "{{ related_entities[1].id }}|{{ target.id }}",
                    }
                ],
            },
        )
    )
    card = next(iter(deck.generate_all().values()))
    assert deck.render(card, rng=random.Random(99)).front == "target|a|b"
    assert deck.render(card, rng=random.Random(99)).back == "b|target"


def test_jinja_templates_keep_html_and_escape_inserted_values(tmp_path: Path, write_deck) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "html" / "deck.json",
            {
                "entities": [
                    {
                        "id": "target",
                        "label": "<b>Unsafe</b>",
                    }
                ],
                "exercises": [
                    {
                        "id": "basic",
                        "type": "basic",
                        "entities": ["target"],
                        "front_template": "<strong>{{ entity.label }}</strong>",
                        "back_template": "<em>{{ entity.label }}</em>",
                    }
                ],
            },
        )
    )

    card = next(iter(deck.generate_all().values()))
    view = deck.render(card)

    assert view.front == "<strong>&lt;b&gt;Unsafe&lt;/b&gt;</strong>"
    assert view.back == "<em>&lt;b&gt;Unsafe&lt;/b&gt;</em>"


def test_common_relation_preflight_covers_every_related_entity_under_cap(
    tmp_path: Path, write_deck
) -> None:
    path = write_deck(
        tmp_path / "preflight" / "deck.json",
        {
            "entities": [
                {"id": "target"},
                {"id": "good-a", "answer": {"value": "A"}},
                {"id": "good-b", "answer": {"value": "B"}},
                {"id": "bad-c"},
            ],
            "exercises": [
                {
                    "id": "common",
                    "type": "common_relation",
                    "max_related": 2,
                    "relations": {"target": ["good-a", "good-b", "bad-c"]},
                    "front_template": (
                        "{% for related_entity in related_entities %}"
                        "{{ related_entity.answer.value }}{% endfor %}"
                    ),
                }
            ],
        },
    )
    with pytest.raises(ConfigError, match="could not render card template"):
        Deck.load(path)


@pytest.mark.parametrize("field", ["target", "related"])
def test_common_relation_unknown_references_are_config_errors(
    field: str, tmp_path: Path, write_deck
) -> None:
    ids = {"target", "related-1", "related-2"}
    document = {
        "entities": [{"id": entity_id} for entity_id in ids],
        "exercises": [
            {
                "id": "common",
                "type": "common_relation",
                "relations": {"target": ["related-1", "related-2"]},
            }
        ],
    }
    if field == "target":
        document["exercises"][0]["relations"] = {"missing": ["related-1", "related-2"]}
    else:
        document["exercises"][0]["relations"]["target"][1] = "missing"
    with pytest.raises(ConfigError, match="unknown"):
        Deck.load(write_deck(tmp_path / field / "deck.json", document))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda item: item.update({"direction": "object"}), "Extra inputs are not permitted"),
        (lambda item: item.update({"min_examples": 1}), "greater than or equal to 2"),
        (lambda item: item.update({"max_related": 1}), "max_related"),
        (lambda item: item["relations"]["target"].append("related-1"), "duplicate"),
        (lambda item: item["relations"].update({"target": ["related-1"]}), "at least"),
        (lambda item: item.update({"extra": True}), "Extra"),
    ],
)
def test_common_relation_rejects_invalid_definitions(
    mutation, message: str, tmp_path: Path, write_deck
) -> None:
    item = {
        "id": "common",
        "type": "common_relation",
        "relations": {"target": ["related-1", "related-2"]},
    }
    mutation(item)
    document = {
        "entities": [{"id": entity_id} for entity_id in ["target", "related-1", "related-2"]],
        "exercises": [item],
    }
    with pytest.raises(ConfigError, match=message):
        Deck.load(write_deck(tmp_path / "invalid" / "deck.json", document))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item.update({"relations": {}}),
        lambda item: item["relations"].update(
            {"target": {"predicate": "obsolete", "related": ["related-1", "related-2"]}}
        ),
        lambda item: item["relations"].update({"\ttarget": item["relations"].pop("target")}),
        lambda item: item["relations"].update({" ": item["relations"].pop("target")}),
        lambda item: item["relations"].update({"target": ["related-1\u200b", "related-2"]}),
        lambda item: item["relations"].update({"target": [" ", "related-2"]}),
        lambda item: item.update({"min_examples": True}),
        lambda item: item.update({"max_related": "2"}),
        lambda item: item["relations"].update({"target": "related-1"}),
    ],
)
def test_common_relation_rejects_malformed_nested_input(
    mutation, tmp_path: Path, write_deck
) -> None:
    item = {
        "id": "common",
        "type": "common_relation",
        "relations": {"target": ["related-1", "related-2"]},
    }
    mutation(item)
    document = {
        "entities": [{"id": entity_id} for entity_id in ["target", "related-1", "related-2"]],
        "exercises": [item],
    }
    with pytest.raises(ConfigError):
        Deck.load(write_deck(tmp_path / "malformed" / "deck.json", document))


def test_common_relation_does_not_expose_predicate_template_context(
    tmp_path: Path, write_deck
) -> None:
    path = write_deck(
        tmp_path / "predicate-context" / "deck.json",
        {
            "entities": [{"id": entity_id} for entity_id in ["target", "a", "b"]],
            "exercises": [
                {
                    "id": "common",
                    "type": "common_relation",
                    "relations": {"target": ["a", "b"]},
                    "front_template": "{{ predicate }}",
                }
            ],
        },
    )
    with pytest.raises(ConfigError, match="unknown template variable"):
        Deck.load(path)


def test_common_relation_runtime_payload_failures_are_presentation_errors(
    tmp_path: Path, write_deck
) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "runtime" / "deck.json",
            {
                "entities": [{"id": entity_id} for entity_id in ["target", "a", "b"]],
                "exercises": [
                    {
                        "id": "common",
                        "type": "common_relation",
                        "relations": {"target": ["a", "b"]},
                    }
                ],
            },
        )
    )
    generator = deck.generators[0]
    key = generator._key("target", deck.name)
    malformed = CommonRelationExercise.model_construct(
        card_key=key,
        generator_id="common",
        target_id="target",
        related_ids=("a",),
    )
    with pytest.raises(PresentationError, match="inconsistent"):
        deck.render(malformed)

    malformed_card_key = CommonRelationExercise.model_construct(
        card_key=None,
        generator_id="common",
        target_id="target",
        related_ids=("a", "b"),
    )
    with pytest.raises(PresentationError, match="card identity"):
        deck.render(malformed_card_key)

    malformed_generator_id = CommonRelationExercise.model_construct(
        card_key=key,
        target_id="target",
        related_ids=("a", "b"),
    )
    with pytest.raises(PresentationError, match="generator identity"):
        deck.render(malformed_generator_id)

    malformed_related_ids = CommonRelationExercise.model_construct(
        card_key=key,
        generator_id="common",
        target_id="target",
        related_ids="ab",
    )
    with pytest.raises(PresentationError, match="inconsistent"):
        deck.render(malformed_related_ids)

    runtime_cases = [
        {"related_ids": ("a", "missing")},
        {"related_ids": ("a", "a")},
        {"related_ids": ("a", "b"), "target_id": "missing"},
    ]
    for values in runtime_cases:
        runtime_payload = CommonRelationExercise.model_construct(
            card_key=key,
            generator_id="common",
            target_id=values.get("target_id", "target"),
            related_ids=values["related_ids"],
        )
        with pytest.raises(PresentationError, match="inconsistent"):
            deck.render(runtime_payload)

    wrong_identity = CommonRelationExercise.model_construct(
        card_key=generator._key("target", "other-deck"),
        generator_id="common",
        target_id="target",
        related_ids=("a", "b"),
    )
    with pytest.raises(PresentationError, match="deck"):
        deck.render(wrong_identity)

    wrong_type = BasicExercise(card_key=key, generator_id="common", target_id="target")
    with pytest.raises(PresentationError, match="cannot render"):
        deck.render(wrong_type)


def test_entity_accepts_arbitrary_nested_json_data() -> None:
    entity = Entity(id="nested", metadata={"items": [1, {"enabled": True}]})
    metadata = entity.metadata
    assert metadata["items"][0] == 1  # type: ignore[index]
    assert metadata["items"][1]["enabled"] is True  # type: ignore[index]
    with pytest.raises(ValidationError, match="JSON-compatible"):
        Entity(id="bad", metadata=object())


def test_deck_version_field_is_rejected(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "versioned.json"
    write_deck(
        path,
        {
            "version": 1,
            "entities": [{"id": "target"}],
            "exercises": [],
        },
    )
    with pytest.raises(ConfigError, match="Extra inputs are not permitted"):
        Deck.load(path)


def test_deck_loader_rejects_directories(deck_path: Path) -> None:
    with pytest.raises(ConfigError, match="not a file"):
        Deck.load(deck_path.parent)


def test_generators_produce_semantic_exercises(deck: Deck) -> None:
    cards = tuple(deck.generate_all(rng=random.Random(4)).values())
    basic = next(card for card in cards if isinstance(card, BasicExercise))
    assert set(basic.model_dump()) == {"card_key", "generator_id", "target_id"}
    assert not hasattr(basic, "front")
    assert not hasattr(basic, "back")
    choice = next(card for card in cards if isinstance(card, MultipleChoiceExercise))
    assert choice.target_id == "italy"
    assert choice.target_id in choice.choices
    assert len(choice.choices) == 3
    assert not hasattr(choice, "correct_id")
    assert not hasattr(choice, "prompt")
    missing_item = next(card for card in cards if isinstance(card, MissingSequenceItemExercise))
    assert missing_item.group_id == "europe"
    assert missing_item.ordered_ids == ("france", "germany")
    rendered_choice = deck.render(choice)
    assert rendered_choice.back == "Rome"
    assert "italy" in rendered_choice.front
    assert "Paris" in rendered_choice.front
    assert "Madrid" in rendered_choice.front
    assert len(cards) == len(deck.target_entity_ids) == 3


def test_analogy_generator_uses_entity_source_and_target_data(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "analogy" / "deck.json"
    write_deck(
        path,
        {
            "entities": [
                {"id": "france", "front": "France", "back": "Paris"},
                {"id": "germany", "front": "Germany", "back": "Berlin"},
            ],
            "exercises": [
                {
                    "id": "capital-analogy",
                    "type": "analogy",
                    "sources": {"germany": ["france"]},
                }
            ],
        },
    )
    deck = Deck.load(path)
    exercise = next(iter(deck.generate_all().values()))
    assert isinstance(exercise, AnalogyExercise)
    assert deck.render(exercise).front == "France is to Paris as Germany is to ?"
    assert deck.render(exercise).back == "Berlin"


def test_generator_rendering_settings_come_from_deck_json(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "settings" / "deck.json"
    write_deck(
        path,
        {
            "entities": [{"id": str(index), "label": f"Entity {index}"} for index in range(6)],
            "exercises": [
                {
                    "id": "choices",
                    "type": "multiple_choice",
                    "max_choices": 2,
                    "choices": {"0": ["1", "2", "3"]},
                },
                {
                    "id": "ordered",
                    "type": "missing_sequence_item",
                    "window_size": 3,
                    "groups": {"0": ["1", "2", "3", "4", "5"]},
                },
            ],
        },
    )
    deck = Deck.load(path)
    cards = deck.generate_all(rng=random.Random(4))
    choice = next(card for card in cards.values() if isinstance(card, MultipleChoiceExercise))
    rendered_choice = deck.render(choice)
    assert "1." in rendered_choice.front
    assert "2." in rendered_choice.front
    assert "3." not in rendered_choice.front
    ordered = next(
        card
        for card in cards.values()
        if isinstance(card, MissingSequenceItemExercise) and card.target_id == "3"
    )
    rendered = deck.render(ordered)
    assert rendered.front == "…\n2. Entity 2\n3. ?\n4. Entity 4\n…"


def test_generator_templates_are_configurable_in_deck_json(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "custom" / "deck.json"
    write_deck(
        path,
        {
            "entities": [
                {"id": "source", "front": "Source", "back": "Source answer"},
                {"id": "target", "front": "Target", "back": "Target answer"},
                {"id": "distractor", "front": "Distractor", "back": "Distractor answer"},
            ],
            "exercises": [
                {
                    "id": "basic",
                    "type": "basic",
                    "entities": ["target"],
                    "front_template": "\n  BASIC: {{ entity.front }}  \n",
                    "back_template": "{{ entity.back }}!",
                },
                {
                    "id": "choice",
                    "type": "multiple_choice",
                    "choices": {"target": ["distractor"]},
                    "front_template": (
                        "MC: {{ target.front }} / "
                        "{% for choice in choice_entities %}{{ choice.back }}"
                        "{% if not loop.last %}, {% endif %}{% endfor %}"
                    ),
                    "back_template": "MC ANSWER: {{ target.back }}",
                },
                {
                    "id": "ordered",
                    "type": "missing_sequence_item",
                    "groups": {"source": ["source", "target"]},
                    "front_template": (
                        "ORDER: {% for row in rows %}{% if row.is_target %}?{% else %}"
                        "{{ row.entity.back }}{% endif %}"
                        "{% if not loop.last %} > {% endif %}{% endfor %}"
                    ),
                    "back_template": "ORDER ANSWER: {{ target.back }}",
                },
                {
                    "id": "analogy",
                    "type": "analogy",
                    "sources": {"target": ["source"]},
                    "front_template": ("ANALOGY: {{ source.front }} -> {{ target.front }}"),
                    "back_template": "ANALOGY ANSWER: {{ target.back }}",
                },
            ],
        },
    )
    deck = Deck.load(path)
    context = ExerciseGeneratorContext(deck.name, deck.entities, random.Random(0))
    rendered = {
        generator.id: deck.render(
            generator.generate(
                "target" if generator.id == "ordered" else generator.target_ids[0],
                context,
            )
        )
        for generator in deck.generators
    }
    assert rendered["basic"].front == "\n  BASIC: Target  \n"
    assert rendered["basic"].back == "Target answer!"
    assert rendered["choice"].front in {
        "MC: Target / Distractor answer, Target answer",
        "MC: Target / Target answer, Distractor answer",
    }
    assert rendered["choice"].back == "MC ANSWER: Target answer"
    assert rendered["ordered"].front == "ORDER: Source answer > ?"
    assert rendered["ordered"].back == "ORDER ANSWER: Target answer"
    assert rendered["analogy"].front == "ANALOGY: Source -> Target"
    assert rendered["analogy"].back == "ANALOGY ANSWER: Target answer"


def test_invalid_generator_template_is_a_config_error(tmp_path: Path, write_deck) -> None:
    for template, message in (
        ("{{", "front_template is not valid Jinja"),
        ("{{ prompt }}", "unknown template variable"),
    ):
        path = tmp_path / f"invalid-{len(template)}" / "deck.json"
        write_deck(
            path,
            {
                "entities": [{"id": "target"}],
                "exercises": [
                    {
                        "id": "basic",
                        "type": "basic",
                        "entities": ["target"],
                        "front_template": template,
                    }
                ],
            },
        )
        with pytest.raises(ConfigError, match=message):
            Deck.load(path)


def test_nested_template_data_errors_are_config_errors(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "missing-data" / "deck.json"
    write_deck(
        path,
        {
            "entities": [{"id": "target", "front": "Target"}],
            "exercises": [
                {
                    "id": "basic",
                    "type": "basic",
                    "entities": ["target"],
                    "front_template": "{{ entity.missing.value }}",
                }
            ],
        },
    )
    with pytest.raises(ConfigError, match="could not render card template"):
        Deck.load(path)


@pytest.mark.parametrize(
    "expression",
    [
        "entity.model_extra.get('front')",
        "entity.model_computed_fields",
        "entity.model_config",
        "entity.model_dump().get('front')",
        "entity.model_dump_json()",
        "entity.model_copy().front",
        "entity.model_construct(id='forged').front",
        "entity.model_fields",
        "entity.model_parametrized_name",
        "entity.model_post_init",
        "entity.model_validate",
        "entity.model_validate_json",
        "entity.construct(id='forged')",
        "entity.copy(update={'id': 'forged'})",
        "entity.dict()",
        "entity.json()",
    ],
)
def test_template_cannot_access_entity_serialization_helpers(
    expression: str, tmp_path: Path, write_deck
) -> None:
    path = tmp_path / f"private-entity-api-{len(expression)}" / "deck.json"
    write_deck(
        path,
        {
            "entities": [{"id": "target", "front": "Target"}],
            "exercises": [
                {
                    "id": "basic",
                    "type": "basic",
                    "entities": ["target"],
                    "front_template": f"{{{{ {expression} }}}}",
                }
            ],
        },
    )
    with pytest.raises(ConfigError, match="could not render card template"):
        Deck.load(path)


def test_template_can_access_an_ordinary_data_field_directly(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "ordinary-data-field" / "deck.json"
    write_deck(
        path,
        {
            "entities": [{"id": "target", "data": {"answer": "Nested answer"}}],
            "exercises": [
                {
                    "id": "basic",
                    "type": "basic",
                    "entities": ["target"],
                    "front_template": "{{ entity.data.answer }}",
                }
            ],
        },
    )
    deck = Deck.load(path)
    card = next(iter(deck.generate_all().values()))
    assert deck.render(card).front == "Nested answer"


def test_template_arithmetic_is_bounded(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "arithmetic" / "deck.json"
    write_deck(
        path,
        {
            "entities": [{"id": "target"}],
            "exercises": [
                {
                    "id": "basic",
                    "type": "basic",
                    "entities": ["target"],
                    "front_template": "{{ 'x' * 1000001 }}",
                }
            ],
        },
    )
    with pytest.raises(ConfigError, match="template multiplication exceeds"):
        Deck.load(path)


def test_generation_rejects_target_outside_generator_scope(deck: Deck) -> None:
    generator = deck.generators[0]
    with pytest.raises(PresentationError, match="does not generate"):
        generator.generate(
            "germany", ExerciseGeneratorContext(deck.name, deck.entities, random.Random(0))
        )


def test_multiple_choice_choices_are_generated_and_rendered_from_the_exercise(
    deck: Deck,
) -> None:
    generator = next(item for item in deck.generators if item.type == "multiple_choice")
    first = generator.generate(
        "italy", ExerciseGeneratorContext(deck.name, deck.entities, random.Random(1))
    )
    second = generator.generate(
        "italy", ExerciseGeneratorContext(deck.name, deck.entities, random.Random(2))
    )
    assert isinstance(first, MultipleChoiceExercise)
    assert isinstance(second, MultipleChoiceExercise)
    assert first.choices != second.choices
    rendered = deck.render(first)
    rendered_choices = [
        line.strip().split(". ", maxsplit=1)[1]
        for line in rendered.front.splitlines()
        if ". " in line
    ]
    expected_choices = [
        str(
            next(
                (
                    getattr(deck.entities[choice_id], field_name)
                    for field_name in ("label", "back", "answer")
                    if hasattr(deck.entities[choice_id], field_name)
                ),
                choice_id,
            )
        )
        for choice_id in first.choices
    ]
    assert rendered_choices == expected_choices
    assert all(choice_id in deck.entities for choice_id in first.choices)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"entities": [{"id": "same"}, {"id": "same"}]}, "duplicate entity"),
        (
            {
                "entities": [{"id": "one"}],
                "exercises": [{"id": "g", "type": "basic", "entities": ["missing"]}],
            },
            "unknown",
        ),
        (
            {
                "entities": [{"id": "one"}],
                "exercises": [{"id": "g", "type": "unknown", "entities": []}],
            },
            "unknown exercise generator type",
        ),
        (
            {
                "entities": [{"id": "one"}],
                "exercises": [{"id": "g", "type": "basic", "entities": ["one"], "extra": True}],
            },
            "Extra",
        ),
        (
            {
                "entities": [{"id": "target"}, {"id": "other"}],
                "exercises": [
                    {
                        "id": "mc",
                        "type": "multiple_choice",
                        "entities": {"target": "pool"},
                        "choices": {"pool": ["other"]},
                    }
                ],
            },
            "Extra",
        ),
    ],
)
def test_invalid_deck_content_is_a_config_error(
    tmp_path: Path, write_deck, change: dict[str, object], message: str
) -> None:
    path = tmp_path / "broken.json"
    write_deck(
        path,
        {"entities": [{"id": "one"}], "exercises": []} | change,
    )
    with pytest.raises(ConfigError, match=message):
        Deck.load(path)


def test_multiple_choice_rejects_empty_choices_and_correct_distractor(
    tmp_path: Path, write_deck
) -> None:
    for entities, exercises, message in (
        (
            [{"id": "target"}, {"id": "other"}],
            [
                {
                    "id": "mc",
                    "type": "multiple_choice",
                    "choices": {"target": []},
                }
            ],
            "at least one distractor",
        ),
        (
            [{"id": "target"}, {"id": "other"}],
            [
                {
                    "id": "mc",
                    "type": "multiple_choice",
                    "choices": {"target": ["target"]},
                }
            ],
            "cannot be in its distractor pool",
        ),
    ):
        path = write_deck(
            tmp_path / f"{message}.json",
            {"entities": entities, "exercises": exercises},
        )
        with pytest.raises(ConfigError, match=message):
            Deck.load(path)


def test_basic_generator_rejects_duplicate_targets(tmp_path: Path, write_deck) -> None:
    path = tmp_path / "duplicate.json"
    write_deck(
        path,
        {
            "entities": [{"id": "target"}],
            "exercises": [{"id": "basic", "type": "basic", "entities": ["target", "target"]}],
        },
    )
    with pytest.raises(ConfigError, match="duplicate target"):
        Deck.load(path)


def test_missing_sequence_item_groups_are_metadata_and_members_cannot_overlap(
    tmp_path: Path, write_deck
) -> None:
    path = tmp_path / "order.json"
    write_deck(
        path,
        {
            "entities": [{"id": value} for value in ("g1", "g2", "a", "b", "c")],
            "exercises": [
                {
                    "id": "order",
                    "type": "missing_sequence_item",
                    "groups": {"g1": ["a", "b"], "g2": ["b", "c"]},
                }
            ],
        },
    )
    with pytest.raises(ConfigError, match="belongs to multiple groups"):
        Deck.load(path)


def test_identity_is_stable_across_order_and_random_choices(
    deck_path: Path, tmp_path: Path, write_deck
) -> None:
    first = Deck.load(deck_path)
    cards_first = first.generate_all(rng=random.Random(1))
    raw = json.loads(deck_path.read_text(encoding="utf-8"))
    raw["exercises"] = list(reversed(raw["exercises"]))
    second_path = write_deck(tmp_path / "reordered" / "capitals" / "deck.json", raw)
    second = Deck.load(second_path)
    cards_second = second.generate_all(rng=random.Random(99))
    assert set(cards_first) == set(cards_second)


def test_same_target_in_two_generators_has_one_stable_exercise(deck: Deck) -> None:
    cards = deck.generate_all()
    target_cards = [card for card in cards.values() if card.card_key.entity_id == "france"]
    assert len(target_cards) == 1
    assert target_cards[0].generator_id == "basics"
    assert len(cards) == len(deck.target_entity_ids)


def test_old_query_configuration_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "graphcards.toml"
    path.write_text(
        'sources = ["knowledge.ttl"]\n[[decks]]\nname = "old"\nkind = "basic"\nquery = "x.rq"\n',
        encoding="utf-8",
    )
    from graphcards.config import load_config

    with pytest.raises(ConfigError, match="decks|sources"):
        load_config(path)
