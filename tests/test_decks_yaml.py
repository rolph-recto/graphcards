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
from graphcards.storage import Repository
from tests.test_decks_toml import DOCUMENT, TOML_DOCUMENT

YAML_DOCUMENT = """\
name: Parity study
entities:
  - id: target
    front: Target
    back: Answer
  - id: source
    front: Source
    back: Source answer
  - id: choice
    label: Choice
  - id: other
    label: Other
  - id: ordered-a
    label: Ordered A
  - id: ordered-b
    label: Ordered B
  - id: related-a
    label: Related A
  - id: related-b
    label: Related B
exercises:
  - id: basic
    type: basic
    entities: [target]
  - id: choice-generator
    type: multiple_choice
    choices:
      choice: [target, other]
  - id: ordered
    type: ordered_list
    groups:
      target: [ordered-a, ordered-b]
  - id: analogy
    type: analogy
    sources:
      target: [source]
  - id: common
    type: common_relation
    relations:
      target: [related-a, related-b]
"""


def write_yaml(path: Path, content: str = YAML_DOCUMENT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_yaml_loads_every_generator_and_matches_json_and_toml(tmp_path: Path) -> None:
    directory = tmp_path / "parity"
    directory.mkdir()
    json_path = directory / "deck.json"
    toml_path = directory / "deck.toml"
    yaml_path = directory / "deck.yaml"
    json_path.write_text(json.dumps(DOCUMENT), encoding="utf-8")
    toml_path.write_text(TOML_DOCUMENT, encoding="utf-8")
    write_yaml(yaml_path)

    json_deck, toml_deck, yaml_deck = (
        Deck.load(path) for path in (json_path, toml_path, yaml_path)
    )
    assert yaml_deck.document.model_dump() == json_deck.document.model_dump()
    assert yaml_deck.document.model_dump() == toml_deck.document.model_dump()
    for seed in (0, 7, 99):
        json_cards = json_deck.generate_all(rng=random.Random(seed))
        toml_cards = toml_deck.generate_all(rng=random.Random(seed))
        yaml_cards = yaml_deck.generate_all(rng=random.Random(seed))
        assert toml_cards == json_cards
        assert yaml_cards == toml_cards
        assert {
            card_id: yaml_deck.render(card, rng=random.Random(seed))
            for card_id, card in yaml_cards.items()
        } == {
            card_id: json_deck.render(card, rng=random.Random(seed))
            for card_id, card in json_cards.items()
        }
        assert {
            card_id: yaml_deck.render(card, rng=random.Random(seed))
            for card_id, card in yaml_cards.items()
        } == {
            card_id: toml_deck.render(card, rng=random.Random(seed))
            for card_id, card in toml_cards.items()
        }


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".YAML", ".YmL"])
def test_yaml_suffix_is_case_insensitive(tmp_path: Path, suffix: str) -> None:
    path = write_yaml(tmp_path / f"deck{suffix}")
    deck = Deck.load(path)
    assert deck.display_name == "Parity study"
    assert len(deck.generate_all(rng=random.Random(0))) == 4


def test_yaml_preserves_nested_metadata_and_templates(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path / "nested" / "deck.yaml",
        """\
name: Nested
entities:
  - id: target
    label: Target
    metadata:
      tags: [one, two]
      details:
        unicode: café
exercises:
  - id: basic
    type: basic
    entities: [target]
    front_template: '{{ entity.data.get("label") }}'
    back_template: '{{ entity.data.get("metadata").get("details").get("unicode") }}'
""",
    )
    card = next(iter(Deck.load(path).generate_all().values()))
    view = Deck.load(path).render(card)
    assert view.front == "Target"
    assert view.back == "café"


@pytest.mark.parametrize(
    ("label", "content"),
    [
        (
            "duplicate root key",
            "name: one\nname: two\nentities: []\nexercises: []\n",
        ),
        (
            "duplicate nested key",
            "name: one\nentities:\n  - id: target\n    metadata:\n"
            "      x: 1\n      x: 2\nexercises: []\n",
        ),
        (
            "custom tag",
            "name: !custom one\nentities: []\nexercises: []\n",
        ),
        (
            "unsafe object",
            "name: !!python/object/apply:os.system [echo unsafe]\nentities: []\nexercises: []\n",
        ),
        (
            "multiple documents",
            "name: one\nentities: []\nexercises: []\n---\nname: two\nentities: []\nexercises: []\n",
        ),
        ("non-mapping root", "- one\n- two\n"),
        (
            "non-string key",
            "name: one\nentities:\n  - id: target\n    metadata:\n      1: value\nexercises: []\n",
        ),
        (
            "timestamp",
            "name: one\nentities:\n  - id: target\n    metadata: 2024-01-01\nexercises: []\n",
        ),
        (
            "set",
            "name: one\nentities:\n  - id: target\n    metadata: !!set {a: null}\nexercises: []\n",
        ),
        (
            "binary",
            "name: one\nentities:\n  - id: target\n    metadata: !!binary "
            "aGVsbG8=\nexercises: []\n",
        ),
        (
            "non-finite number",
            "name: one\nentities:\n  - id: target\n    metadata: .inf\nexercises: []\n",
        ),
        (
            "anchor",
            "name: &name one\nentities: []\nexercises: []\n",
        ),
        (
            "alias",
            "name: one\nentities: &entities []\nexercises: *entities\n",
        ),
        (
            "merge key",
            "name: one\nbase: {x: value}\n<<: {y: value}\nentities: []\nexercises: []\n",
        ),
        ("empty document", ""),
    ],
)
def test_yaml_safety_failures_are_path_qualified(tmp_path: Path, label: str, content: str) -> None:
    path = write_yaml(tmp_path / f"{label.replace(' ', '-')}.yaml", content)
    with pytest.raises(ConfigError) as error:
        Deck.load(path)
    message = str(error.value)
    assert str(path) in message
    assert "invalid YAML deck" in message or "invalid deck" in message


def test_yaml_parser_error_includes_location(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path / "malformed.yaml",
        "name: malformed\nentities:\n  - id: target\n    broken: [one\nexercises: []\n",
    )
    with pytest.raises(ConfigError, match=r"invalid YAML deck.*line [0-9]+, column [0-9]+"):
        Deck.load(path)


@pytest.mark.parametrize(
    "content",
    [
        "name: one\nentities: []\nexercises:\n  - id: unknown\n    type: unknown\n",
        "name: one\nentities: []\nexercises:\n  - id: basic\n"
        "    type: basic\n    entities: [missing]\n",
        "name: one\nentities:\n  - id: target\nexercises:\n  - id: choices\n"
        "    type: multiple_choice\n    choices:\n      target: not-a-sequence\n",
    ],
)
def test_yaml_schema_failures_are_path_qualified(tmp_path: Path, content: str) -> None:
    path = write_yaml(tmp_path / "invalid-schema.yaml", content)
    with pytest.raises(ConfigError, match=r"invalid deck .+invalid-schema\.yaml"):
        Deck.load(path)


def test_yaml_missing_and_directory_paths_are_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="could not access deck file"):
        Deck.load(tmp_path / "missing.yaml")

    directory = tmp_path / "directory.yaml"
    directory.mkdir()
    with pytest.raises(ConfigError, match="deck path is not a file"):
        Deck.load(directory)


def test_yaml_load_config_and_cli_support_relative_mixed_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    json_path = tmp_path / "json-deck" / "deck.json"
    toml_path = tmp_path / "toml-deck" / "deck.toml"
    yaml_path = tmp_path / "yaml-deck" / "deck.yml"
    json_path.parent.mkdir()
    toml_path.parent.mkdir()
    json_path.write_text(json.dumps(DOCUMENT), encoding="utf-8")
    toml_path.write_text(TOML_DOCUMENT, encoding="utf-8")
    write_yaml(yaml_path)
    config_path = tmp_path / "graphcards.toml"
    config_path.write_text(
        'state_path = "state.sqlite3"\n'
        'decks = ["json-deck/deck.json", "toml-deck/deck.toml", "yaml-deck/deck.yml"]\n',
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert tuple(deck.path for deck in config.decks) == (
        json_path.resolve(),
        toml_path.resolve(),
        yaml_path.resolve(),
    )
    output = StringIO()
    assert main(["--config", str(config_path), "validate"], output=output) == 0
    assert output.getvalue().count("valid (4 cards)") == 3
    assert main(["--config", str(config_path), "sync"], output=StringIO()) == 0
    with Repository(config.state_path) as repository:
        assert len(repository.active_cards("yaml-deck")) == 4

    with pytest.raises(SystemExit):
        build_parser().parse_args(["validate", "--help"])
    assert "validate JSON/TOML/YAML deck study content" in capsys.readouterr().out
