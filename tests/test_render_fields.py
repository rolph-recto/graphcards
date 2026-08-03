from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from graphcards.decks import Deck, EntityRenderValue, RenderConfig
from graphcards.errors import ConfigError
from graphcards.models import FrozenModel


def write_deck(path: Path, document: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def basic_document(**exercise_overrides: object) -> dict[str, object]:
    exercise: dict[str, object] = {
        "id": "basic",
        "type": "basic",
        "entities": ["france"],
    }
    exercise.update(exercise_overrides)
    return {
        "entities": [
            {
                "id": "france",
                "country": "France",
                "capital": "Paris",
                "name": "France name",
                "prompt": "Country?",
                "answer": "Paris answer",
            }
        ],
        "exercises": [exercise],
    }


def test_basic_templates_receive_resolved_logical_values(tmp_path: Path) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "custom" / "deck.json",
            basic_document(
                render={"question": "country", "answer": "capital"},
                front_template="{{ entity.question }}|{{ target.question }}|{{ target.id }}",
                back_template="{{ entity.answer }}|{{ target.answer }}|{{ entity.name }}",
            ),
        )
    )

    card = next(iter(deck.generate_all(rng=random.Random(0)).values()))
    view = deck.render(card)

    assert (view.front, view.back) == (
        "France|France|france",
        "Paris|Paris|France name",
    )
    assert card.model_dump() == {
        "card_key": {"deck_id": deck.name, "entity_id": "france"},
        "generator_id": "basic",
        "target_id": "france",
    }


def test_entity_render_context_is_a_frozen_pydantic_model(tmp_path: Path) -> None:
    deck = Deck.load(write_deck(tmp_path / "models" / "deck.json", basic_document()))
    generator = deck.generators[0]
    target = generator.render_entity(deck.entities["france"])

    assert isinstance(target, EntityRenderValue)
    assert isinstance(target, FrozenModel)
    assert target.question == "Country?"

    with pytest.raises(ValidationError, match="frozen"):
        target.id = "changed"


def test_absent_render_keeps_hardcoded_fallbacks(tmp_path: Path) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "fallback" / "deck.json",
            basic_document(
                front_template="{{ entity.question }}",
                back_template="{{ entity.answer }}",
            ),
        )
    )

    card = next(iter(deck.generate_all().values()))
    assert deck.render(card).front == "Country?"
    assert deck.render(card).back == "Paris answer"


def test_partial_render_uses_fallback_for_omitted_slots(tmp_path: Path) -> None:
    deck = Deck.load(
        write_deck(
            tmp_path / "partial" / "deck.json",
            basic_document(
                render={"answer": "capital"},
                front_template="{{ entity.question }}",
                back_template="{{ entity.answer }}",
            ),
        )
    )

    card = next(iter(deck.generate_all().values()))
    assert deck.render(card).front == "Country?"
    assert deck.render(card).back == "Paris"


def test_fallback_uses_the_first_present_value_even_when_empty(tmp_path: Path) -> None:
    document = basic_document(
        front_template="{{ entity.question }}",
        back_template="{{ entity.answer }}",
    )
    document["entities"] = [
        {
            "id": "france",
            "front": "",
            "prompt": "Prompt fallback",
            "back": "",
            "answer": "Answer fallback",
        }
    ]
    deck = Deck.load(write_deck(tmp_path / "empty-fallback" / "deck.json", document))
    card = next(iter(deck.generate_all().values()))

    assert deck.render(card).front == ""
    assert deck.render(card).back == ""


def test_render_slots_are_defined_by_the_generator(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="render slot 'label'.*basic"):
        Deck.load(
            write_deck(
                tmp_path / "wrong-slot" / "deck.json",
                basic_document(render={"label": "name"}),
            )
        )


@pytest.mark.parametrize(
    "field_name",
    ["", " ", "_private", "metadata.value", "not-valid", "model_dump", "class"],
)
def test_render_field_names_are_direct_public_identifiers(field_name: str) -> None:
    with pytest.raises(ValidationError, match="render|field|invalid|private|reserved"):
        RenderConfig.model_validate({"question": field_name})


def test_missing_selected_field_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="configured render field 'missing'"):
        Deck.load(
            write_deck(
                tmp_path / "missing" / "deck.json",
                basic_document(
                    render={"question": "missing"},
                ),
            )
        )


def test_missing_selected_field_in_a_collection_is_caught_during_preflight(
    tmp_path: Path,
) -> None:
    document = {
        "entities": [
            {"id": "target", "question": "Target", "answer": "Target answer"},
            {"id": "good", "question": "Good", "answer": "Good answer"},
            {"id": "bad", "answer": "Bad answer"},
        ],
        "exercises": [
            {
                "id": "choices",
                "type": "multiple_choice",
                "max_choices": 2,
                "choices": {"target": ["good", "bad"]},
                "render": {"question": "question", "choice_label": "question"},
            }
        ],
    }
    with pytest.raises(ConfigError, match="entity 'bad'.*configured render field 'question'"):
        Deck.load(write_deck(tmp_path / "collection-missing" / "deck.json", document))


def test_render_mapping_rejects_nested_fields_but_nested_values_are_renderable(
    tmp_path: Path,
) -> None:
    document = basic_document(
        render={"question": "metadata.value"},
    )
    document["entities"] = [{"id": "france", "metadata": {"value": "France"}}]
    with pytest.raises(ConfigError, match="direct top-level"):
        Deck.load(write_deck(tmp_path / "nested-name" / "deck.json", document))

    document = basic_document(
        render={"question": "metadata"},
        front_template="{{ entity.question.value }}",
    )
    document["entities"] = [
        {
            "id": "france",
            "metadata": {"value": "France"},
            "capital": "Paris",
        }
    ]
    deck = Deck.load(write_deck(tmp_path / "nested-value" / "deck.json", document))
    card = next(iter(deck.generate_all().values()))
    assert deck.render(card).front == "France"


def test_collection_contexts_use_resolved_values(tmp_path: Path) -> None:
    document = {
        "entities": [
            {"id": "target", "question": "Target question", "answer": "Target answer"},
            {"id": "choice", "question": "Choice question", "answer": "Choice answer"},
            {"id": "other", "question": "Other question", "answer": "Other answer"},
        ],
        "exercises": [
            {
                "id": "choices",
                "type": "multiple_choice",
                "choices": {"target": ["choice", "other"]},
                "render": {
                    "question": "question",
                    "choice_label": "question",
                    "answer": "answer",
                },
                "front_template": (
                    "{{ target.question }}|{% for choice_value in choice %}"
                    "{{ choice_value.choice_label }}{% if not loop.last %},{% endif %}{% endfor %}"
                ),
                "back_template": "{{ target.answer }}|{{ target.question }}|{{ target.answer }}",
            }
        ],
    }
    deck = Deck.load(write_deck(tmp_path / "collection" / "deck.json", document))
    card = next(iter(deck.generate_all(rng=random.Random(0)).values()))
    view = deck.render(card)

    assert view.front.startswith("Target question|")
    assert set(view.front.split("|", maxsplit=1)[1].split(",")) == {
        "Target question",
        "Choice question",
        "Other question",
    }
    assert view.back == "Target answer|Target question|Target answer"


def test_row_and_cloze_contexts_expose_resolved_values(tmp_path: Path) -> None:
    sequence = {
        "entities": [
            {"id": "group", "name": "Sequence"},
            {"id": "one", "name": "One", "answer": "First"},
            {"id": "two", "name": "Two", "answer": "Second"},
        ],
        "exercises": [
            {
                "id": "sequence",
                "type": "missing_sequence_item",
                "render": {"row_label": "name", "answer": "answer"},
                "groups": {"group": ["one", "two"]},
                "front_template": "{% for item in row %}{{ item.entity.row_label }}{% endfor %}",
                "back_template": "{{ target.answer }}",
            }
        ],
    }
    sequence_deck = Deck.load(write_deck(tmp_path / "sequence" / "deck.json", sequence))
    sequence_card = next(iter(sequence_deck.generate_all().values()))
    assert sequence_deck.render(sequence_card).back in {"First", "Second"}

    cloze = {
        "entities": [{"id": "sentence", "text": "The [[answer::sky]] is blue."}],
        "exercises": [
            {
                "id": "cloze",
                "type": "cloze",
                "cloze_field": "text",
                "render": {"entity_label": "text"},
                "entities": ["sentence"],
                "front_template": "{{ cloze_id }}|{{ cloze_value }}|{{ front }}",
                "back_template": "{{ back }}|{{ target.entity_label }}",
            }
        ],
    }
    cloze_deck = Deck.load(write_deck(tmp_path / "cloze" / "deck.json", cloze))
    cloze_card = next(iter(cloze_deck.generate_all().values()))
    assert cloze_deck.render(cloze_card).front == "answer|sky|The [...] is blue."
    assert cloze_deck.render(cloze_card).back == "The sky is blue.|The [[answer::sky]] is blue."


def test_render_values_are_reused_without_changing_generation(tmp_path: Path) -> None:
    path = tmp_path / "same-deck" / "deck.json"
    fallback = Deck.load(write_deck(path, basic_document()))
    custom = Deck.load(
        write_deck(path, basic_document(render={"question": "country", "answer": "capital"}))
    )

    fallback_card = next(iter(fallback.generate_all(rng=random.Random(12)).values()))
    custom_card = next(iter(custom.generate_all(rng=random.Random(12)).values()))
    assert fallback_card.card_key == custom_card.card_key
    assert fallback_card.model_dump() == custom_card.model_dump()
    assert custom.render(custom_card) == custom.render(custom_card)


@pytest.mark.parametrize("suffix", ["json", "toml", "yaml"])
def test_render_mapping_has_format_parity(tmp_path: Path, suffix: str) -> None:
    directory = tmp_path / suffix
    directory.mkdir()
    path = directory / f"deck.{suffix}"
    if suffix == "json":
        path.write_text(
            json.dumps(
                basic_document(
                    render={"question": "country", "answer": "capital"},
                    front_template="{{ entity.question }}",
                    back_template="{{ entity.answer }}",
                )
            ),
            encoding="utf-8",
        )
    elif suffix == "toml":
        path.write_text(
            """\
[[entities]]
id = "france"
country = "France"
capital = "Paris"
prompt = "Country?"
answer = "Paris answer"

[[exercises]]
id = "basic"
type = "basic"
entities = ["france"]
front_template = "{{ entity.question }}"
back_template = "{{ entity.answer }}"

[exercises.render]
question = "country"
answer = "capital"
""",
            encoding="utf-8",
        )
    else:
        path.write_text(
            """\
entities:
  - id: france
    country: France
    capital: Paris
    prompt: Country?
    answer: Paris answer
exercises:
  - id: basic
    type: basic
    entities: [france]
    render:
      question: country
      answer: capital
    front_template: '{{ entity.question }}'
    back_template: '{{ entity.answer }}'
""",
            encoding="utf-8",
        )

    deck = Deck.load(path)
    card = next(iter(deck.generate_all().values()))
    assert (deck.render(card).front, deck.render(card).back) == ("France", "Paris")
    assert deck.generators[0].render_config is not None
    assert deck.generators[0].render_config.root["question"] == "country"
