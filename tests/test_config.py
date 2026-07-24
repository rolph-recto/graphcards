from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from graphcards.config import FsrsSettings, load_config
from graphcards.decks import (
    BasicDeck,
    DeckDefinition,
    MultipleChoiceDeck,
    OrderedListDeck,
    Presentation,
)
from graphcards.errors import ConfigError
from graphcards.models import CardKey, TargetKind


def test_paths_are_relative_to_config(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(workspace.parent)
    config = load_config(workspace / "graphcards.toml")
    assert config.state_path == workspace / ".graphcards" / "state.sqlite3"
    assert config.sources == (workspace / "data" / "knowledge.ttl",)
    assert config.deck("capitals-basic").query_path == workspace / "queries" / "capitals-basic.rq"
    assert config.deck("capitals-basic").target is TargetKind.TRIPLE
    assert config.deck("capitals-choice").target is TargetKind.ENTITY
    assert isinstance(config.deck("capitals-basic"), BasicDeck)
    assert isinstance(config.deck("capitals-choice"), MultipleChoiceDeck)


@pytest.mark.parametrize(
    "body, message",
    [
        (
            'sources = ["data.ttl"]\n[[decks]]\nname="x"\nkind="unknown"\nquery="x.rq"\n',
            "kind",
        ),
        (
            'sources = ["data.ttl"]\n[[decks]]\nname="x"\nkind="basic"\n'
            'target="unknown"\nquery="x.rq"\n',
            "target",
        ),
        (
            'sources = ["data.ttl"]\n[[decks]]\nname="x"\nkind="basic"\nquery="x.rq"\n',
            "target",
        ),
        (
            'sources=["x"]\n[[decks]]\nname="x"\nkind="basic"\nquery="x"\n'
            'target="triple"\n[[decks]]\nname="x"\nkind="basic"\nquery="y"\n'
            'target="triple"\n',
            "duplicate",
        ),
        (
            'sources=["x"]\n[fsrs]\ndesired_retention=0\n'
            '[[decks]]\nname="x"\nkind="basic"\ntarget="triple"\nquery="x"\n',
            "desired_retention",
        ),
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, body: str, message: str) -> None:
    path = tmp_path / "graphcards.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_empty_config_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "graphcards.toml"
    path.write_text("", encoding="utf-8")
    config = load_config(path)
    assert config.sources == ()
    assert config.decks == ()


def test_display_timezone_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "graphcards.toml"
    path.write_text('display_timezone = "America/New_York"\n', encoding="utf-8")

    config = load_config(path)

    assert config.display_timezone.key == "America/New_York"

    path.write_text('display_timezone = "not/a-zone"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="display_timezone"):
        load_config(path)


def test_deck_definition_resolves_configuration_names() -> None:
    assert DeckDefinition.from_name("basic") is BasicDeck
    assert DeckDefinition.from_name("multiple_choice") is MultipleChoiceDeck
    assert DeckDefinition.from_name("ordered_list") is OrderedListDeck
    with pytest.raises(ValueError, match="basic"):
        DeckDefinition.from_name("unknown")


def test_custom_deck_definition_registers_and_dispatches(tmp_path: Path) -> None:
    class RegisteredDeck(BasicDeck):
        config_name = "registered_config_test"
        prefix: str

    assert DeckDefinition.from_name("registered_config_test") is RegisteredDeck
    deck = DeckDefinition.from_config(
        {
            "kind": "registered_config_test",
            "name": "registered",
            "target": "entity",
            "query": "query.rq",
            "prefix": "Custom",
        },
        context={"base": tmp_path},
    )
    assert isinstance(deck, RegisteredDeck)
    assert deck.query_path == tmp_path / "query.rq"
    assert deck.prefix == "Custom"


def test_duplicate_deck_definition_name_is_rejected() -> None:
    with pytest.raises(TypeError, match="already registered"):

        class DuplicateBasic(BasicDeck):
            config_name = "basic"


def test_abstract_and_incomplete_definitions_are_rejected() -> None:
    with pytest.raises(ValueError, match="concrete"):
        DeckDefinition.validate_definition_class(DeckDefinition)

    class IncompleteDefinition(DeckDefinition):
        def group(
            self,
            result: object,
            *,
            expected: set[str],
            card_key: CardKey | None = None,
        ) -> dict[str, Presentation]:
            del result, expected, card_key
            return {}

    with pytest.raises(ValueError, match="config_name"):
        DeckDefinition.validate_definition_class(IncompleteDefinition)


def test_unknown_deck_lists_available(config: object) -> None:
    with pytest.raises(ConfigError, match="capitals-basic"):
        config.deck("missing")  # type: ignore[attr-defined]


def test_unknown_configuration_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "graphcards.toml"
    path.write_text(
        'sources=["data.ttl"]\nunknown=true\n'
        '[[decks]]\nname="x"\ntarget="triple"\nkind="basic"\nquery="x.rq"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unknown"):
        load_config(path)


def test_multiple_choice_max_choices_defaults_to_four(tmp_path: Path) -> None:
    deck = MultipleChoiceDeck(
        name="choices",
        target=TargetKind.ENTITY,
        query_path=tmp_path / "query.rq",
    )

    assert deck.max_choices == 4


def test_multiple_choice_accepts_explicit_max_choices(tmp_path: Path) -> None:
    deck = MultipleChoiceDeck(
        name="choices",
        target=TargetKind.ENTITY,
        query_path=tmp_path / "query.rq",
        max_choices=6,
    )

    assert deck.max_choices == 6


@pytest.mark.parametrize("value", [0, 1, True, 2.5, "2"])
def test_invalid_configured_max_choices_is_rejected(tmp_path: Path, value: object) -> None:
    with pytest.raises(ValidationError, match="max_choices"):
        MultipleChoiceDeck(
            name="choices",
            target=TargetKind.ENTITY,
            query_path=tmp_path / "query.rq",
            max_choices=value,
        )


def test_basic_deck_rejects_max_choices(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="max_choices"):
        BasicDeck(
            name="basic",
            target=TargetKind.ENTITY,
            query_path=tmp_path / "query.rq",
            max_choices=4,
        )


def test_invalid_toml_max_choices_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "graphcards.toml"
    path.write_text(
        '[[decks]]\nname="choices"\ntarget="entity"\nkind="multiple_choice"\n'
        'query="choices.rq"\nmax_choices=1\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="max_choices"):
        load_config(path)


def test_ordered_list_window_size_defaults_to_five(tmp_path: Path) -> None:
    deck = OrderedListDeck(
        name="ordered",
        target=TargetKind.ENTITY,
        query_path=tmp_path / "query.rq",
    )

    assert deck.window_size == 5


def test_deck_constraints_are_inherited_by_custom_definitions(tmp_path: Path) -> None:
    class CustomOrderedList(OrderedListDeck):
        config_name = "custom_ordered_constraints_test"

    deck = CustomOrderedList(
        name="ordered",
        target=TargetKind.ENTITY,
        query_path=tmp_path / "query.rq",
    )

    assert deck.window_size == 5
    with pytest.raises(ValidationError, match="entity"):
        CustomOrderedList(
            name="ordered",
            target=TargetKind.TRIPLE,
            query_path=tmp_path / "query.rq",
        )


def test_ordered_list_accepts_zero_window_size(tmp_path: Path) -> None:
    deck = OrderedListDeck(
        name="ordered",
        target=TargetKind.ENTITY,
        query_path=tmp_path / "query.rq",
        window_size=0,
    )

    assert deck.window_size == 0


@pytest.mark.parametrize("value", [-1, True, 2.5, "5"])
def test_invalid_ordered_list_window_size_is_rejected(tmp_path: Path, value: object) -> None:
    with pytest.raises(ValidationError, match="window_size"):
        OrderedListDeck(
            name="ordered",
            target=TargetKind.ENTITY,
            query_path=tmp_path / "query.rq",
            window_size=value,
        )


def test_ordered_list_requires_entity_target(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="entity"):
        OrderedListDeck(
            name="ordered",
            target=TargetKind.TRIPLE,
            query_path=tmp_path / "query.rq",
        )


def test_basic_rejects_window_size(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="window_size"):
        BasicDeck(
            name="basic",
            target=TargetKind.ENTITY,
            query_path=tmp_path / "query.rq",
            window_size=5,
        )


def test_fsrs_step_overflow_is_an_actionable_config_error() -> None:
    settings = FsrsSettings(learning_steps_minutes=(10**18,))
    with pytest.raises(ConfigError, match="invalid FSRS settings"):
        settings.create_scheduler()
