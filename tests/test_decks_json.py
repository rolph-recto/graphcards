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
    Deck,
    DeckDocument,
    Entity,
    ExerciseGeneratorContext,
    MultipleChoiceExercise,
    OrderedListExercise,
)
from graphcards.errors import ConfigError, PresentationError


def test_loads_typed_generators_and_nested_entity_data(deck: Deck) -> None:
    assert tuple(type(generator).__name__ for generator in deck.generators) == (
        "BasicExerciseGenerator",
        "MultipleChoiceExerciseGenerator",
        "OrderedListExerciseGenerator",
    )
    assert deck.entities["france"].data["front"] == "France"
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


def test_entity_accepts_arbitrary_nested_json_data() -> None:
    entity = Entity(id="nested", metadata={"items": [1, {"enabled": True}]})
    metadata = entity.data["metadata"]
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
    ordered = next(card for card in cards if isinstance(card, OrderedListExercise))
    assert ordered.group_id == "europe"
    assert ordered.ordered_ids == ("france", "germany")
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
                    "type": "ordered_list",
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
        if isinstance(card, OrderedListExercise) and card.target_id == "3"
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
                    "front_template": "\n  BASIC: {{ entity.data.get('front') }}  \n",
                    "back_template": "{{ entity.data.get('back') }}!",
                },
                {
                    "id": "choice",
                    "type": "multiple_choice",
                    "choices": {"target": ["distractor"]},
                    "front_template": (
                        "MC: {{ target.data.get('front') }} / "
                        "{% for choice in choice_entities %}{{ choice.data.get('back') }}"
                        "{% if not loop.last %}, {% endif %}{% endfor %}"
                    ),
                    "back_template": "MC ANSWER: {{ target.data.get('back') }}",
                },
                {
                    "id": "ordered",
                    "type": "ordered_list",
                    "groups": {"source": ["source", "target"]},
                    "front_template": (
                        "ORDER: {% for row in rows %}{% if row.is_target %}?{% else %}"
                        "{{ row.entity.data.get('back') }}{% endif %}"
                        "{% if not loop.last %} > {% endif %}{% endfor %}"
                    ),
                    "back_template": "ORDER ANSWER: {{ target.data.get('back') }}",
                },
                {
                    "id": "analogy",
                    "type": "analogy",
                    "sources": {"target": ["source"]},
                    "front_template": (
                        "ANALOGY: {{ source.data.get('front') }} -> {{ target.data.get('front') }}"
                    ),
                    "back_template": "ANALOGY ANSWER: {{ target.data.get('back') }}",
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
                    "front_template": "{{ entity.data.get('missing').value }}",
                }
            ],
        },
    )
    with pytest.raises(ConfigError, match="could not render card template"):
        Deck.load(path)


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
            deck.entities[choice_id].data.get(
                "label",
                deck.entities[choice_id].data.get(
                    "back", deck.entities[choice_id].data.get("answer", choice_id)
                ),
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


def test_ordered_list_groups_are_metadata_and_members_cannot_overlap(
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
                    "type": "ordered_list",
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
