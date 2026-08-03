from __future__ import annotations

import json
import random
from io import StringIO
from pathlib import Path

import pytest

from graphcards.cli import build_parser, main
from graphcards.config import load_config
from graphcards.decks import Deck
from graphcards.errors import ConfigError
from graphcards.scaffold import initialize_workspace
from graphcards.storage import DeckFileStateStore

DOCUMENT = {
    "name": "Parity study",
    "entities": [
        {"id": "target", "front": "Target", "back": "Answer"},
        {"id": "source", "front": "Source", "back": "Source answer"},
        {"id": "choice", "label": "Choice"},
        {"id": "other", "label": "Other"},
        {"id": "ordered-a", "label": "Ordered A"},
        {"id": "ordered-b", "label": "Ordered B"},
        {"id": "related-a", "label": "Related A"},
        {"id": "related-b", "label": "Related B"},
    ],
    "exercises": [
        {"id": "basic", "type": "basic", "entities": ["target"]},
        {
            "id": "choice-generator",
            "type": "multiple_choice",
            "choices": {"choice": ["target", "other"]},
        },
        {
            "id": "ordered",
            "type": "missing_sequence_item",
            "groups": {"target": ["ordered-a", "ordered-b"]},
        },
        {"id": "analogy", "type": "analogy", "sources": {"target": ["source"]}},
        {
            "id": "common",
            "type": "common_relation",
            "relations": {"target": ["related-a", "related-b"]},
        },
    ],
}

TOML_DOCUMENT = """\
name = "Parity study"

[[entities]]
id = "target"
front = "Target"
back = "Answer"

[[entities]]
id = "source"
front = "Source"
back = "Source answer"

[[entities]]
id = "choice"
label = "Choice"

[[entities]]
id = "other"
label = "Other"

[[entities]]
id = "ordered-a"
label = "Ordered A"

[[entities]]
id = "ordered-b"
label = "Ordered B"

[[entities]]
id = "related-a"
label = "Related A"

[[entities]]
id = "related-b"
label = "Related B"

[[exercises]]
id = "basic"
type = "basic"
entities = ["target"]

[[exercises]]
id = "choice-generator"
type = "multiple_choice"
[exercises.choices]
choice = ["target", "other"]

[[exercises]]
id = "ordered"
type = "missing_sequence_item"
[exercises.groups]
target = ["ordered-a", "ordered-b"]

[[exercises]]
id = "analogy"
type = "analogy"
[exercises.sources]
target = ["source"]

[[exercises]]
id = "common"
type = "common_relation"
[exercises.relations]
target = ["related-a", "related-b"]
"""


def write_parity_decks(tmp_path: Path) -> tuple[Path, Path]:
    directory = tmp_path / "parity"
    directory.mkdir()
    json_path = directory / "deck.json"
    toml_path = directory / "deck.TOML"
    json_path.write_text(json.dumps(DOCUMENT), encoding="utf-8")
    toml_path.write_text(TOML_DOCUMENT, encoding="utf-8")
    return json_path, toml_path


def test_toml_and_json_share_validation_generation_identity_and_rendering(tmp_path: Path) -> None:
    json_path, toml_path = write_parity_decks(tmp_path)

    json_deck = Deck.load(json_path)
    toml_deck = Deck.load(toml_path)

    assert toml_deck.document.model_dump() == json_deck.document.model_dump()
    for seed in (0, 7, 99):
        json_cards = json_deck.generate_all(rng=random.Random(seed))
        toml_cards = toml_deck.generate_all(rng=random.Random(seed))
        assert json_cards == toml_cards
        assert {
            card_id: toml_deck.render(card, rng=random.Random(seed))
            for card_id, card in toml_cards.items()
        } == {
            card_id: json_deck.render(card, rng=random.Random(seed))
            for card_id, card in json_cards.items()
        }


def test_deck_parser_is_selected_by_case_insensitive_suffix(tmp_path: Path) -> None:
    _, toml_path = write_parity_decks(tmp_path)
    json_path = toml_path.with_name("deck.JSON")
    json_path.write_text(json.dumps(DOCUMENT), encoding="utf-8")

    deck = Deck.load(toml_path)
    json_deck = Deck.load(json_path)

    assert deck.path == toml_path.resolve()
    assert deck.name == "parity"
    assert json_deck.document.model_dump() == deck.document.model_dump()


def test_unsupported_deck_suffix_is_explicit_and_does_not_sniff_content(tmp_path: Path) -> None:
    path = tmp_path / "parity" / "deck.txt"
    path.parent.mkdir()
    path.write_text(json.dumps(DOCUMENT), encoding="utf-8")

    with pytest.raises(ConfigError, match=r"unsupported deck file extension.*deck\.txt"):
        Deck.load(path)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('entities = "not an array"\n', "valid tuple"),
        (
            '[[exercises]]\nid = "bad"\ntype = "unknown"\n',
            "unknown exercise generator type",
        ),
        (
            """\
[[entities]]
id = "target"

[[exercises]]
id = "bad"
type = "multiple_choice"
[exercises.choices]
target = ["missing"]
""",
            "unknown",
        ),
        (
            """\
[[entities]]
id = "target"
published = 1979-05-27T07:32:00Z
""",
            "JSON-compatible",
        ),
        (
            """\
[[entities]]
id = "target"
published = 1979-05-27
""",
            "JSON-compatible",
        ),
        (
            """\
[[entities]]
id = "target"
published = 07:32:00
""",
            "JSON-compatible",
        ),
    ],
)
def test_invalid_toml_decks_are_repository_facing_errors(
    tmp_path: Path, body: str, message: str
) -> None:
    path = tmp_path / "invalid" / "deck.toml"
    path.parent.mkdir()
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        Deck.load(path)


def test_malformed_toml_preserves_parser_location(tmp_path: Path) -> None:
    path = tmp_path / "invalid" / "deck.toml"
    path.parent.mkdir()
    path.write_text('[[entities]\nid = "target"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match=r"invalid TOML deck.*line 1"):
        Deck.load(path)


def test_toml_config_paths_can_mix_decks_and_cli_validate_status(tmp_path: Path) -> None:
    json_path = tmp_path / "mixed-json" / "deck.json"
    toml_path = tmp_path / "mixed-toml" / "deck.toml"
    json_path.parent.mkdir()
    toml_path.parent.mkdir()
    json_path.write_text(json.dumps(DOCUMENT), encoding="utf-8")
    toml_path.write_text(TOML_DOCUMENT, encoding="utf-8")
    config_path = tmp_path / "workspace" / "graphcards.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        'decks = ["../mixed-json/deck.json", "../mixed-toml/deck.toml"]\n',
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert tuple(deck.path for deck in config.decks) == (json_path.resolve(), toml_path.resolve())

    output = StringIO()
    assert main(["--config", str(config_path), "validate"], output=output) == 0
    assert output.getvalue().count("valid (4 cards)") == 2
    assert main(["--config", str(config_path), "status"], output=StringIO()) == 0
    with DeckFileStateStore(config.decks) as state_store:
        assert len(state_store.active_cards("mixed-json")) == 4
        assert len(state_store.active_cards("mixed-toml")) == 4


def test_validate_help_mentions_supported_deck_formats(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["validate", "--help"])

    assert "validate JSON/TOML/YAML deck study content" in capsys.readouterr().out


@pytest.mark.parametrize("loader", [Deck.load, load_config])
def test_invalid_path_values_become_config_errors(loader) -> None:
    with pytest.raises(ConfigError, match="could not resolve"):
        loader("\x00")


def test_unknown_user_paths_become_config_errors(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'state_path = "~graphcards-definitely-no-such-user/state.sqlite3"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="invalid configuration"):
        load_config(config_path)
    with pytest.raises(ConfigError, match="could not resolve workspace path"):
        initialize_workspace(Path("~graphcards-definitely-no-such-user"))


def test_deeply_nested_toml_becomes_config_error(tmp_path: Path) -> None:
    path = tmp_path / "deep.toml"
    path.write_text("nested = " + "[" * 2000 + "0" + "]" * 2000, encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path)


def test_scaffold_rejects_dangling_symlink_destinations(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "deck.json").symlink_to(tmp_path / "outside-deck.json")

    with pytest.raises(ConfigError, match="symlinked workspace paths"):
        initialize_workspace(workspace, "analogy-capitals")

    assert not (tmp_path / "outside-deck.json").exists()


def test_scaffold_rejects_symlinked_workspace_roots(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    workspace = tmp_path / "workspace-link"
    workspace.symlink_to(target, target_is_directory=True)

    with pytest.raises(ConfigError, match="symlinked workspace path"):
        initialize_workspace(workspace, "analogy-capitals")

    assert not (target / "deck.json").exists()
