from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rdfcards.config import DeckDefinition, FsrsSettings, load_config
from rdfcards.decks import Basic, DeckKind, MultipleChoice
from rdfcards.errors import ConfigError
from rdfcards.models import TargetKind


def test_paths_are_relative_to_config(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(workspace.parent)
    config = load_config(workspace / "rdfcards.toml")
    assert config.state_path == workspace / ".rdfcards" / "state.sqlite3"
    assert config.sources == (workspace / "data" / "knowledge.ttl",)
    assert config.deck("capitals-basic").query_path == workspace / "queries" / "capitals-basic.rq"
    assert config.deck("capitals-basic").target is TargetKind.TRIPLE
    assert config.deck("capitals-choice").target is TargetKind.ENTITY
    assert config.deck("capitals-basic").kind is Basic
    assert config.deck("capitals-choice").kind is MultipleChoice


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
    path = tmp_path / "rdfcards.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_empty_config_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "rdfcards.toml"
    path.write_text("", encoding="utf-8")
    config = load_config(path)
    assert config.sources == ()
    assert config.decks == ()


def test_deck_kind_resolves_configuration_names() -> None:
    assert DeckKind.from_name("basic") is Basic
    assert DeckKind.from_name("multiple_choice") is MultipleChoice
    with pytest.raises(ValueError, match="basic"):
        DeckKind.from_name("unknown")


def test_custom_deck_kind_registers_its_configuration_name() -> None:
    class RegisteredKind(Basic):
        config_name = "registered_config_test"

    assert DeckKind.from_name("registered_config_test") is RegisteredKind


def test_duplicate_deck_kind_name_is_rejected() -> None:
    with pytest.raises(TypeError, match="already registered"):

        class DuplicateBasic(Basic):
            config_name = "basic"


def test_abstract_deck_kind_is_rejected_by_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="concrete DeckKind"):
        DeckDefinition(
            name="abstract",
            target=TargetKind.TRIPLE,
            kind=DeckKind,
            query_path=tmp_path / "query.rq",
        )


def test_incomplete_deck_kind_is_rejected_by_configuration(tmp_path: Path) -> None:
    class IncompleteKind(DeckKind):
        @classmethod
        def group(cls, *_args: object, **_kwargs: object):
            return {}

    with pytest.raises(ValidationError, match="config_name"):
        DeckDefinition(
            name="incomplete",
            target=TargetKind.TRIPLE,
            kind=IncompleteKind,
            query_path=tmp_path / "query.rq",
        )


def test_unknown_deck_lists_available(config: object) -> None:
    with pytest.raises(ConfigError, match="capitals-basic"):
        config.deck("missing")  # type: ignore[attr-defined]


def test_unknown_configuration_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rdfcards.toml"
    path.write_text(
        'sources=["data.ttl"]\nunknown=true\n'
        '[[decks]]\nname="x"\ntarget="triple"\nkind="basic"\nquery="x.rq"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unknown"):
        load_config(path)


def test_multiple_choice_max_choices_defaults_to_four(tmp_path: Path) -> None:
    deck = DeckDefinition(
        name="choices",
        target=TargetKind.ENTITY,
        kind=MultipleChoice,
        query_path=tmp_path / "query.rq",
    )

    assert deck.max_choices is None
    assert deck.effective_max_choices == 4


def test_multiple_choice_accepts_explicit_max_choices(tmp_path: Path) -> None:
    deck = DeckDefinition(
        name="choices",
        target=TargetKind.ENTITY,
        kind=MultipleChoice,
        query_path=tmp_path / "query.rq",
        max_choices=6,
    )

    assert deck.effective_max_choices == 6


@pytest.mark.parametrize("value", [0, 1, True, 2.5, "2"])
def test_invalid_configured_max_choices_is_rejected(tmp_path: Path, value: object) -> None:
    with pytest.raises(ValidationError, match="max_choices"):
        DeckDefinition(
            name="choices",
            target=TargetKind.ENTITY,
            kind=MultipleChoice,
            query_path=tmp_path / "query.rq",
            max_choices=value,
        )


def test_basic_deck_rejects_max_choices(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="only valid for multiple_choice"):
        DeckDefinition(
            name="basic",
            target=TargetKind.ENTITY,
            kind=Basic,
            query_path=tmp_path / "query.rq",
            max_choices=4,
        )


def test_invalid_toml_max_choices_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "rdfcards.toml"
    path.write_text(
        '[[decks]]\nname="choices"\ntarget="entity"\nkind="multiple_choice"\n'
        'query="choices.rq"\nmax_choices=1\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="max_choices"):
        load_config(path)


def test_fsrs_step_overflow_is_an_actionable_config_error() -> None:
    settings = FsrsSettings(learning_steps_minutes=(10**18,))
    with pytest.raises(ConfigError, match="invalid FSRS settings"):
        settings.create_scheduler()
