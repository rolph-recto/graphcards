from __future__ import annotations

import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from graphcards.config import load_config
from graphcards.decks import (
    Deck,
    ImageOcclusionExercise,
    ImageOcclusionExerciseGenerator,
    ImageOcclusionPlacement,
)
from graphcards.errors import ConfigError
from graphcards.scaffold import initialize_workspace
from graphcards.storage import Repository
from graphcards.web.app import EXPECTED_HOST_CONFIG, create_flask_app
from graphcards.web.controller import StudyController
from graphcards.web.study import StudyMode


def _document(
    *,
    image_path: str = "diagram.png",
    front_template: str | None = None,
    back_template: str | None = None,
) -> dict[str, object]:
    generator: dict[str, object] = {
        "id": "diagram",
        "type": "image_occlusion",
        "image_path": image_path,
        "image_alt": "A diagram",
        "occlusions": [
            {"target_id": "first", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
            {"target_id": "second", "x": 0.6, "y": 0.1, "width": 0.2, "height": 0.25},
        ],
    }
    if front_template is not None:
        generator["front_template"] = front_template
    if back_template is not None:
        generator["back_template"] = back_template
    return {
        "entities": [
            {"id": "first", "answer": "First answer"},
            {"id": "second", "answer": "Second answer"},
        ],
        "exercises": [generator],
    }


def test_image_occlusion_generates_one_card_per_target_and_renders_geometry(
    tmp_path: Path, write_deck
) -> None:
    deck = Deck.load(write_deck(tmp_path / "occlusions" / "deck.json", _document()))

    cards = deck.generate_all(rng=random.Random(0))

    assert set(cards) == {"first", "second"}
    assert all(isinstance(card, ImageOcclusionExercise) for card in cards.values())
    first = cards["first"]
    assert first.target_id == first.card_key.entity_id == "first"
    assert first.occlusions[0].x == 0.1
    view = deck.render(first)
    assert "/decks/occlusions/assets/diagram.png" in view.front
    assert 'class="image-occlusion__canvas"><img' in view.front
    assert 'class="image-occlusion__mask-layer"' in view.front
    assert 'x="10.0" y="20.0" width="30.0" height="40.0"' in view.front
    assert 'class="image-occlusion__mask-text" x="25.0" y="40.0">?</text>' in view.front
    assert "First answer" in view.back
    assert "Second answer" not in view.back
    assert "<img" not in view.back


def test_image_occlusion_templates_escape_inserted_values(tmp_path: Path, write_deck) -> None:
    document = _document(
        front_template='<img src="{{ image_url }}" alt="{{ image_alt }}">{{ placement.width }}',
        back_template="{{ target.answer }}",
    )
    document["entities"] = [{"id": "first", "answer": '<script>alert("x")</script>'}]
    document["exercises"] = [
        {
            **document["exercises"][0],  # type: ignore[index]
            "occlusions": [{"target_id": "first", "x": 0, "y": 0, "width": 1, "height": 1}],
        }
    ]
    deck = Deck.load(write_deck(tmp_path / "escaping" / "deck.json", document))

    card = next(iter(deck.generate_all().values()))
    view = deck.render(card)
    assert "&lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt;" in view.back
    assert "<script>" not in view.back
    assert view.front.endswith(">100.0")


@pytest.mark.parametrize(
    "field, value",
    [
        ("x", -0.01),
        ("y", 1.01),
        ("width", 0),
        ("height", 0),
    ],
)
def test_image_occlusion_rejects_invalid_geometry(field: str, value: float) -> None:
    values = {"target_id": "target", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}
    values[field] = value

    with pytest.raises(ValidationError):
        ImageOcclusionPlacement.model_validate(values)


def test_image_occlusion_rejects_overflow_duplicate_and_unknown_targets() -> None:
    with pytest.raises(ValidationError, match="at most 1"):
        ImageOcclusionPlacement(target_id="target", x=0.9, y=0, width=0.2, height=0.1)
    with pytest.raises(ValidationError, match="duplicate"):
        ImageOcclusionExerciseGenerator(
            id="diagram",
            image_path="diagram.png",
            occlusions=[
                {"target_id": "target", "x": 0, "y": 0, "width": 0.1, "height": 0.1},
                {"target_id": "target", "x": 0.2, "y": 0, "width": 0.1, "height": 0.1},
            ],
        )


def test_image_occlusion_rejects_unknown_target_before_sync(tmp_path: Path, write_deck) -> None:
    document = _document()
    document["exercises"] = [
        {
            **document["exercises"][0],  # type: ignore[index]
            "occlusions": [{"target_id": "missing", "x": 0, "y": 0, "width": 0.1, "height": 0.1}],
        }
    ]

    with pytest.raises(ConfigError, match="unknown target entity"):
        Deck.load(write_deck(tmp_path / "invalid-target" / "deck.json", document))


@pytest.mark.parametrize("filename", ["deck.json", "deck.toml", "deck.yaml"])
def test_image_occlusion_examples_have_the_same_cards(tmp_path: Path, filename: str) -> None:
    source = Path(__file__).parents[1] / "src/graphcards/templates/image-occlusion" / filename
    destination = tmp_path / "image-occlusion" / filename
    destination.parent.mkdir()
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    deck = Deck.load(destination)

    cards = deck.generate_all()
    assert set(cards) == {"sun", "earth"}
    assert isinstance(deck.generators[0], ImageOcclusionExerciseGenerator)
    assert ">?</text>" in deck.render(cards["sun"]).front


def test_image_occlusion_template_copies_its_binary_image_asset(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "image-occlusion", "image-occlusion")

    image = workspace / "assets" / "solar-system.jpg"
    assert image.is_file()
    assert image.read_bytes().startswith(b"\xff\xd8\xff")
    assert Deck.load(workspace / "deck.json").path == (workspace / "deck.json").resolve()


def test_image_asset_route_is_deck_scoped_and_rejects_unsafe_files(
    tmp_path: Path, write_deck, write_config
) -> None:
    deck_path = write_deck(tmp_path / "asset-deck" / "deck.json", _document())
    (deck_path.parent / "diagram.png").write_bytes(b"PNG test bytes")
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"secret")
    config = load_config(write_config(tmp_path / "graphcards.toml", [deck_path]))
    repository = Repository(config.state_path)
    controller = StudyController(config, repository, random.Random(0))
    app = create_flask_app(controller)
    app.config[EXPECTED_HOST_CONFIG] = "localhost"
    client = app.test_client()
    try:
        response = client.get("/decks/asset-deck/assets/diagram.png")
        assert response.status_code == 200
        assert response.mimetype == "image/png"
        assert response.data == b"PNG test bytes"
        response.close()
        assert client.get("/decks/asset-deck/assets/%2e%2e/secret.png").status_code == 404
        (deck_path.parent / "notes.txt").write_text("not an image", encoding="utf-8")
        assert client.get("/decks/asset-deck/assets/notes.txt").status_code == 415
        assert client.get("/decks/asset-deck/assets/missing.png").status_code == 404
        controller.start_session(
            csrf_token=controller.csrf_token,
            deck_name="asset-deck",
            mode=StudyMode.PRACTICE,
            days=1,
            requested_limit=1,
        )
        study = client.get("/study")
        assert study.status_code == 200
        assert b"/decks/asset-deck/assets/diagram.png" in study.data
        assert b"image-occlusion__mask" in study.data
    finally:
        repository.close()
