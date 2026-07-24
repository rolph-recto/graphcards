from __future__ import annotations

import sqlite3
from urllib.parse import urlencode

import pytest

from graphcards.web.study import StudyMode
from tests.web.support import FlaskHub, exchange, start_form


def test_index_lists_decks_counts_and_advanced_options(
    hub_server: FlaskHub,
) -> None:
    status, headers, body = exchange(hub_server, "GET", "/")

    assert status == 200
    assert "capitals-basic" in body
    assert "capitals-choice" in body
    assert body.count("<strong>2</strong> available") == 2
    assert body.count("<strong>0</strong> suspended") == 2
    assert body.count("<strong>2</strong> due") == 2
    assert "Review forgotten" in body
    assert "Practice deck" in body
    assert "Review ahead" in body
    assert 'href="/decks/capitals-basic/cards"' in body
    assert body.count("View card status") == 2
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert "form-action 'self'" in headers["content-security-policy"]


def test_flask_serves_packaged_css_with_tight_headers_and_no_session_cookie(
    hub_server: FlaskHub,
) -> None:
    status, headers, body = exchange(hub_server, "GET", "/")

    assert status == 200
    assert 'href="/static/style.css"' in body
    assert "style-src 'self'" in headers["content-security-policy"]
    assert "'unsafe-inline'" not in headers["content-security-policy"]
    assert "set-cookie" not in headers

    status, css_headers, css = exchange(hub_server, "GET", "/static/style.css")
    assert status == 200
    assert css_headers["content-type"].startswith("text/css")
    assert css_headers["cache-control"] == "no-store"
    assert ".rating-again" in css
    assert "#b5383b" in css
    assert "set-cookie" not in css_headers


def test_flask_rejects_wrong_hosts_and_malformed_form_bodies(
    hub_server: FlaskHub,
) -> None:
    client = hub_server.flask_app.test_client()
    wrong_host = client.get("/", base_url="http://wrong.example")
    assert wrong_host.status_code == 400
    assert "The request host is not valid." in wrong_host.get_data(as_text=True)

    valid = start_form(hub_server, "capitals-basic", StudyMode.DUE)
    duplicate = (
        f"csrf_token={valid['csrf_token']}&csrf_token={valid['csrf_token']}"
        "&deck_name=capitals-basic&mode=due"
    ).encode()
    cases = (
        (duplicate, "application/x-www-form-urlencoded"),
        (b"csrf_token", "application/x-www-form-urlencoded"),
        (b"csrf_token=%&deck_name=capitals-basic&mode=due", "application/x-www-form-urlencoded"),
        (b"csrf_token=%A&deck_name=capitals-basic&mode=due", "application/x-www-form-urlencoded"),
        (
            b"csrf_token=%ZZ&deck_name=capitals-basic&mode=due",
            "application/x-www-form-urlencoded",
        ),
        (b"x=" + b"a" * 5000, "application/x-www-form-urlencoded"),
        (urlencode(valid).encode(), "text/plain"),
    )
    for body, content_type in cases:
        response = client.post(
            "/sessions",
            data=body,
            content_type=content_type,
            base_url=f"http://{hub_server.expected_host}",
        )
        assert response.status_code == 400
        assert "Study request failed" in response.get_data(as_text=True)
        assert hub_server.app.session is None


@pytest.mark.parametrize(
    "path",
    (
        "/decks/capitals-basic/cards?schedule=%",
        "/decks/capitals-basic/cards?schedule=%A",
        "/decks/capitals-basic/cards?schedule=%ZZ",
    ),
)
def test_flask_rejects_malformed_query_percent_escapes(
    hub_server: FlaskHub,
    path: str,
) -> None:
    status, _, body = exchange(hub_server, "GET", path)

    assert status == 400
    assert "The card-status filters are malformed." in body


@pytest.mark.parametrize(
    "failure",
    (
        OSError("private path: /secret/state.db"),
        sqlite3.OperationalError("no such table: private_reviews"),
    ),
)
def test_flask_hides_raw_dependency_failures(
    hub_server: FlaskHub,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    def fail() -> None:
        raise failure

    monkeypatch.setattr(hub_server.app, "deck_statuses", fail)

    status, _, body = exchange(hub_server, "GET", "/")

    assert status == 500
    assert "Could not complete this request." in body
    assert str(failure) not in body


def test_flask_uses_custom_method_error_page(hub_server: FlaskHub) -> None:
    status, _, body = exchange(hub_server, "POST", "/", {})

    assert status == 405
    assert "405 Method Not Allowed" in body
    assert "That request method is not allowed." in body
