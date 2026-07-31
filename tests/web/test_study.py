from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

from graphcards.config import load_config
from graphcards.storage import Repository
from graphcards.web.app import EXPECTED_HOST_CONFIG, create_flask_app
from graphcards.web.controller import StudyController
from graphcards.web.study import StudyMode


def _start_session(client: object, controller: object, mode: StudyMode) -> None:
    response = client.post(
        "/sessions",
        data={
            "csrf_token": controller.csrf_token,
            "deck_name": "capitals",
            "mode": mode.value,
            "days": "1",
            "limit": "1",
        },
        headers={"Host": "localhost"},
    )
    assert response.status_code == 303
    assert controller.session is not None


def test_study_requires_reveal_before_rating(web_context: tuple[object, object, object]) -> None:
    client, controller, _repository = web_context
    _start_session(client, controller, StudyMode.DUE)
    current = controller.session.current
    assert current is not None
    response = client.post(
        "/study/rate",
        data={
            "session_token": controller.session.session_token,
            "entity_id": current.card.card_key.entity_id,
            "rating": "3",
        },
        headers={"Host": "localhost"},
    )

    assert response.status_code == 409
    assert b"Reveal the answer" in response.data


def test_study_accepts_entity_ids_longer_than_512_characters(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, _repository = web_context
    _start_session(client, controller, StudyMode.DUE)
    current = controller.session.current
    assert current is not None
    response = client.post(
        "/study/reveal",
        data={
            "session_token": controller.session.session_token,
            "entity_id": "x" * 513,
        },
        headers={"Host": "localhost"},
    )

    assert response.status_code == 409


def test_study_reveal_and_rating_persist_review(web_context: tuple[object, object, object]) -> None:
    client, controller, repository = web_context
    _start_session(client, controller, StudyMode.DUE)
    current = controller.session.current
    assert current is not None
    token = controller.session.session_token
    reveal = client.post(
        "/study/reveal",
        data={"session_token": token, "entity_id": current.card.card_key.entity_id},
        headers={"Host": "localhost"},
    )
    rate = client.post(
        "/study/rate",
        data={"session_token": token, "entity_id": current.card.card_key.entity_id, "rating": "3"},
        headers={"Host": "localhost"},
    )
    history = repository.review_history("capitals", datetime.now(UTC))

    assert reveal.status_code == 303
    assert rate.status_code == 303
    assert len(history) == 1


def test_practice_next_does_not_create_review(web_context: tuple[object, object, object]) -> None:
    client, controller, repository = web_context
    _start_session(client, controller, StudyMode.PRACTICE)
    current = controller.session.current
    assert current is not None
    initial_index = controller.session.index
    token = controller.session.session_token
    client.post(
        "/study/reveal",
        data={"session_token": token, "entity_id": current.card.card_key.entity_id},
        headers={"Host": "localhost"},
    )
    next_response = client.post(
        "/study/next",
        data={"session_token": token, "entity_id": current.card.card_key.entity_id},
        headers={"Host": "localhost"},
    )
    history = repository.review_history("capitals", datetime.now(UTC))

    assert next_response.status_code == 303
    assert controller.session.index == initial_index + 1
    assert history == ()


def test_leaving_for_the_deck_list_ends_the_session(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, _repository = web_context
    _start_session(client, controller, StudyMode.DUE)

    index = client.get("/", headers={"Host": "localhost"})
    study = client.get("/study", headers={"Host": "localhost"})

    assert index.status_code == 200
    assert b"Study session in progress" not in index.data
    assert controller.session is None
    assert study.status_code == 409


def test_leaving_for_deck_info_ends_the_session(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, _repository = web_context
    _start_session(client, controller, StudyMode.DUE)

    status = client.get("/decks/capitals/cards", headers={"Host": "localhost"})

    assert status.status_code == 200
    assert controller.session is None


def test_study_pages_and_static_assets_keep_the_session(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, _repository = web_context
    _start_session(client, controller, StudyMode.DUE)

    study = client.get("/study", headers={"Host": "localhost"})
    stylesheet = client.get("/static/style.css", headers={"Host": "localhost"}, buffered=True)

    assert study.status_code == 200
    assert stylesheet.status_code == 200
    assert controller.session is not None


def test_study_renders_html_from_jinja_card_templates(tmp_path: Path) -> None:
    deck_path = tmp_path / "html" / "deck.json"
    deck_path.parent.mkdir()
    deck_path.write_text(
        json.dumps(
            {
                "entities": [{"id": "target", "front": "Target", "back": "<b>Unsafe</b>"}],
                "exercises": [
                    {
                        "id": "basic",
                        "type": "basic",
                        "entities": ["target"],
                        "front_template": "<strong>{{ entity.front }}</strong>",
                        "back_template": "<em>{{ entity.back }}</em>",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "graphcards.toml"
    config_path.write_text(
        f'state_path = "{tmp_path / "state.sqlite3"}"\ndecks = ["{deck_path}"]\n',
        encoding="utf-8",
    )
    config = load_config(config_path)
    repository = Repository(config.state_path)
    controller = StudyController(config, repository, random.Random(0))
    app = create_flask_app(controller)
    app.config[EXPECTED_HOST_CONFIG] = "localhost"
    try:
        client = app.test_client()
        start = client.post(
            "/sessions",
            data={
                "csrf_token": controller.csrf_token,
                "deck_name": "html",
                "mode": StudyMode.DUE.value,
                "days": "1",
                "limit": "1",
            },
            headers={"Host": "localhost"},
        )
        assert start.status_code == 303

        study = client.get("/study", headers={"Host": "localhost"})
        assert b"<strong>Target</strong>" in study.data
        assert b"&lt;strong&gt;Target&lt;/strong&gt;" not in study.data

        current = controller.session.current
        assert current is not None
        reveal = client.post(
            "/study/reveal",
            data={
                "session_token": controller.session.session_token,
                "entity_id": current.card.card_key.entity_id,
            },
            headers={"Host": "localhost"},
        )
        assert reveal.status_code == 303
        revealed = client.get("/study", headers={"Host": "localhost"})
        assert b"<em>&lt;b&gt;Unsafe&lt;/b&gt;</em>" in revealed.data
    finally:
        repository.close()
