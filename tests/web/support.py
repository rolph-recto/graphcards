from __future__ import annotations

import random
from datetime import datetime
from urllib.parse import urlencode

from flask import Flask

from rdfcards.config import AppConfig
from rdfcards.presentation import load_graph
from rdfcards.storage import Repository, datetime_to_text
from rdfcards.web import create_flask_app
from rdfcards.web.controller import StudyController
from rdfcards.web.server import LocalStudyServer
from rdfcards.web.study import StudyMode, StudySession


class FlaskHub:
    def __init__(self, flask_app: Flask, controller: StudyController) -> None:
        self.flask_app = flask_app
        self.app = controller
        self.repository = controller.repository
        self.expected_host = "localhost"
        flask_app.config["RDFCARDS_EXPECTED_HOST"] = self.expected_host

    def close(self) -> None:
        self.repository.close()


def make_test_hub(config: AppConfig) -> FlaskHub:
    graph = load_graph(config.sources)
    repository = Repository(config.state_path)
    try:
        controller = StudyController(config, graph, repository, random.Random(0))
        return FlaskHub(create_flask_app(controller), controller)
    except Exception:
        repository.close()
        raise


def exchange(
    server: FlaskHub | LocalStudyServer,
    method: str,
    path: str,
    fields: dict[str, object] | None = None,
) -> tuple[int, dict[str, str], str]:
    """Send one socket-free request through Flask's test client."""

    body = urlencode(fields).encode() if fields is not None else None
    content_type = "application/x-www-form-urlencoded" if fields is not None else None
    response = server.flask_app.test_client().open(
        path,
        method=method,
        data=body,
        content_type=content_type,
        base_url=f"http://{server.expected_host}",
    )
    try:
        return (
            response.status_code,
            {name.casefold(): value for name, value in response.headers.items()},
            response.get_data(as_text=True),
        )
    finally:
        response.close()


def start_form(
    server: FlaskHub | LocalStudyServer,
    deck_name: str,
    mode: StudyMode,
    *,
    days: int = 1,
    limit: int = 20,
) -> dict[str, object]:
    return {
        "csrf_token": server.app.csrf_token,
        "deck_name": deck_name,
        "mode": mode.value,
        "days": days,
        "limit": limit,
    }


def current_form(server: FlaskHub | LocalStudyServer) -> dict[str, object]:
    session = server.app.session
    assert session is not None
    assert session.current is not None
    return {
        "session_token": session.session_token,
        "card_id": session.current.card.card_id,
    }


def status_action_form(
    server: FlaskHub | LocalStudyServer,
    card_id: str,
    *,
    reason: str | None = None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "csrf_token": server.app.csrf_token,
        "card_id": card_id,
        "availability": "all",
        "schedule": "all",
        "state": "all",
        "sort": "next_review",
        "direction": "asc",
        "range": "90d",
    }
    if reason is not None:
        fields["reason"] = reason
    return fields


def review_count(repository: Repository) -> int:
    return repository.connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]


def set_card_due(repository: Repository, card_id: str, due: datetime) -> None:
    stored = repository.get_card(card_id)
    assert stored is not None
    card = stored.card()
    card.due = due
    repository.connection.execute(
        "UPDATE cards SET card_json = ?, due_at = ? WHERE card_id = ?",
        (card.to_json(), datetime_to_text(due), card_id),
    )


def start_session(
    server: FlaskHub | LocalStudyServer,
    deck_name: str = "capitals-basic",
    mode: StudyMode = StudyMode.DUE,
    *,
    days: int = 1,
    limit: int = 20,
) -> StudySession:
    status, headers, _ = exchange(
        server,
        "POST",
        "/sessions",
        start_form(server, deck_name, mode, days=days, limit=limit),
    )
    assert status == 303
    assert headers["location"] == "/study"
    assert server.app.session is not None
    return server.app.session
