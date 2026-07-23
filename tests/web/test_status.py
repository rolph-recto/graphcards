from __future__ import annotations

import html
import random
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import pytest
from fsrs import Rating
from rdflib import Literal, URIRef

import rdfcards.web.app as web_app_module
from rdfcards.config import AppConfig
from rdfcards.decks import Basic
from rdfcards.errors import PresentationError
from rdfcards.models import CardKey
from rdfcards.storage import datetime_to_text, utc_now
from rdfcards.web.study import StudyMode
from tests.web.support import (
    FlaskHub,
    exchange,
    make_test_hub,
    review_count,
    start_form,
)


def test_card_status_route_url_decodes_configured_deck_name(config: AppConfig) -> None:
    deck = config.deck("capitals-basic").model_copy(update={"name": "capitals/basic & more"})
    special_config = config.model_copy(update={"decks": (deck,)})
    server = make_test_hub(special_config)
    try:
        index = exchange(server, "GET", "/")[2]
        match = re.search(r'href="([^"]+)">\s*View card status', index)
        assert match is not None
        path = html.unescape(match.group(1))

        encoded_name = path.removeprefix("/decks/").removesuffix("/cards")
        assert unquote(encoded_name) == deck.name
        status, _, body = exchange(server, "GET", path)
        assert status == 200
        assert "capitals/basic &amp; more" in body
    finally:
        server.close()


def test_card_status_page_shows_active_cards_without_mutating_state(
    hub_server: FlaskHub,
) -> None:
    before_cards = {
        card.card_id: card.card_json
        for card in hub_server.repository.active_cards("capitals-basic")
    }

    status, headers, body = exchange(
        hub_server,
        "GET",
        "/decks/capitals-basic/cards",
    )

    assert status == 200
    assert "Card schedules and FSRS memory metrics." in body
    assert "Capital of France?" in body
    assert "Capital of Germany?" in body
    assert body.count('<div class="card-front">') == 2
    assert "Last rating: —" in body
    assert "Stability: —" in body
    assert "Difficulty: —" in body
    assert "Retrievability: —" in body
    assert "<time datetime=" in body
    assert "&lt;https://example.org/" in body
    assert '<div class="table-wrap">' in body
    assert headers["cache-control"] == "no-store"
    assert headers["x-frame-options"] == "DENY"
    assert hub_server.app.session is None
    assert review_count(hub_server.repository) == 0
    assert {
        card.card_id: card.card_json
        for card in hub_server.repository.active_cards("capitals-basic")
    } == before_cards


def test_card_status_page_shows_latest_review_and_time_dependent_retrievability(
    hub_server: FlaskHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deck = hub_server.app.config.deck("capitals-basic")
    reviewed_at = datetime(2026, 7, 23, 12, tzinfo=UTC)
    card = hub_server.repository.active_cards(deck.name)[0]
    reviewed = hub_server.app.study_service.review(
        deck,
        card,
        Rating.Good,
        reviewed_at,
    )
    exact_review = "2026-07-23T12:00:00.000000Z"
    monkeypatch.setattr(web_app_module, "utc_now", lambda: reviewed_at)

    first = exchange(hub_server, "GET", "/decks/capitals-basic/cards")[2]

    assert "1 review(s)" in first
    assert "Last rating: Good" in first
    assert exact_review in first
    assert f"Stability: {reviewed.card().stability:.2f} days" in first
    assert f"Difficulty: {reviewed.card().difficulty:.2f}" in first
    assert "Retrievability: 100.0%" in first

    later = reviewed_at + timedelta(days=3)
    monkeypatch.setattr(web_app_module, "utc_now", lambda: later)
    expected = hub_server.app.study_service.scheduler.get_card_retrievability(
        reviewed.card(),
        current_datetime=later,
    )
    second = exchange(hub_server, "GET", "/decks/capitals-basic/cards")[2]

    assert f"Retrievability: {expected:.1%}" in second
    assert second != first


def test_card_status_filters_sorting_and_invalid_queries(
    hub_server: FlaskHub,
) -> None:
    new_cards = exchange(
        hub_server,
        "GET",
        "/decks/capitals-basic/cards?schedule=new",
    )[2]
    no_future_cards = exchange(
        hub_server,
        "GET",
        "/decks/capitals-basic/cards?schedule=future",
    )[2]
    assert new_cards.count('<div class="card-front">') == 2
    assert "No cards match these filters." in no_future_cards

    deck = hub_server.app.config.deck("capitals-basic")
    now = utc_now()
    first, second = hub_server.repository.active_cards(deck.name)
    first = hub_server.app.study_service.review(deck, first, Rating.Good, now)
    hub_server.app.study_service.review(
        deck,
        first,
        Rating.Hard,
        now + timedelta(minutes=1),
    )
    hub_server.app.study_service.review(deck, second, Rating.Again, now)

    descending = exchange(
        hub_server,
        "GET",
        "/decks/capitals-basic/cards?sort=review_count&direction=desc",
    )[2]
    ascending = exchange(
        hub_server,
        "GET",
        "/decks/capitals-basic/cards?sort=review_count&direction=asc",
    )[2]
    assert descending.index(first.card_id) < descending.index(second.card_id)
    assert ascending.index(second.card_id) < ascending.index(first.card_id)

    invalid_paths = (
        "/decks/capitals-basic/cards?schedule=unknown",
        "/decks/capitals-basic/cards?unknown=value",
        "/decks/capitals-basic/cards?schedule",
        "/decks/capitals-basic/cards?schedule=all&schedule=due",
    )
    assert all(exchange(hub_server, "GET", path)[0] == 400 for path in invalid_paths)
    assert exchange(hub_server, "GET", "/decks/capitals-basic/cards?page=2")[0] == 404
    assert exchange(hub_server, "GET", "/decks/missing/cards")[0] == 404


def test_card_status_fronts_are_stable_escaped_and_isolate_failures(
    hub_server: FlaskHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StatusFront(Basic):
        config_name = "custom_status_front"

        def front_text(self, rng: random.Random) -> str:
            return f"<script>{rng.randrange(1000)}</script>"

    class BrokenStatusFront(Basic):
        config_name = "broken_status_front"

        def front_text(self, rng: random.Random) -> str:
            del rng
            raise PresentationError("cannot format status front")

    cards = hub_server.repository.active_cards("capitals-basic")
    presentations = {
        cards[0].card_id: StatusFront(
            card_key=cards[0].card_key,
            front=Literal("ignored"),
            back=Literal("answer"),
        ),
        cards[1].card_id: BrokenStatusFront(
            card_key=cards[1].card_key,
            front=Literal("ignored"),
            back=Literal("answer"),
        ),
    }
    monkeypatch.setattr(
        hub_server.app.study_service,
        "render_all",
        lambda _deck: presentations,
    )

    first = exchange(hub_server, "GET", "/decks/capitals-basic/cards")[2]
    second = exchange(hub_server, "GET", "/decks/capitals-basic/cards")[2]

    assert first == second
    assert "&lt;script&gt;" in first
    assert "<script>" not in first
    assert "Unable to render" in first


def test_card_status_paginates_one_hundred_cards(
    hub_server: FlaskHub,
) -> None:
    deck = hub_server.app.config.deck("capitals-basic")
    now = utc_now()
    presentations = {}
    for index in range(101):
        card_key = CardKey.triple(
            URIRef(f"https://example.org/subject-{index}"),
            URIRef("https://example.org/predicate"),
            Literal(f"object-{index}"),
        )
        presentations[card_key.digest] = Basic(
            card_key=card_key,
            front=Literal(f"Front {index}"),
            back=Literal(f"Back {index}"),
        )
    hub_server.repository.sync_deck(deck.name, presentations, now)
    hub_server.app.study_service.render_all = lambda _deck: presentations  # type: ignore[method-assign]

    first = exchange(hub_server, "GET", "/decks/capitals-basic/cards")[2]
    second = exchange(
        hub_server,
        "GET",
        "/decks/capitals-basic/cards?page=2&schedule=all&state=all&sort=next_review&direction=asc",
    )[2]

    assert first.count('<div class="card-front">') == 100
    assert "1–100 of 101 card(s) · Page 1 of 2" in first
    assert "page=2&amp;schedule=all&amp;state=all" in first
    assert second.count('<div class="card-front">') == 1
    assert "101–101 of 101 card(s) · Page 2 of 2" in second
    assert exchange(hub_server, "GET", "/decks/capitals-basic/cards?page=3")[0] == 404


def test_empty_and_corrupt_card_status_pages_are_safe(
    hub_server: FlaskHub,
) -> None:
    deck = hub_server.app.config.deck("capitals-basic")
    hub_server.repository.sync_deck(deck.name, {}, utc_now())
    empty = exchange(hub_server, "GET", "/decks/capitals-basic/cards")[2]
    assert "This deck has no active cards." in empty

    hub_server.app.study_service.sync(deck, utc_now())
    card = hub_server.repository.active_cards(deck.name)[0]
    hub_server.repository.connection.execute(
        "UPDATE cards SET card_json = ? WHERE card_id = ?",
        ("not JSON", card.card_id),
    )
    status, _, body = exchange(hub_server, "GET", "/decks/capitals-basic/cards")
    assert status == 500
    assert "stored card schedule is invalid" in body
    assert "Traceback" not in body
    assert review_count(hub_server.repository) == 0

    hub_server.repository.connection.execute(
        "UPDATE cards SET card_json = ? WHERE card_id = ?",
        (sqlite3.Binary(b"{}"), card.card_id),
    )
    status, _, body = exchange(hub_server, "GET", "/decks/capitals-basic/cards")
    assert status == 500
    assert "stored card schedule is not JSON text" in body
    assert "validation error" not in body.casefold()
    assert "Traceback" not in body


def test_due_mirror_corruption_fails_hub_status_and_queue_creation_safely(
    hub_server: FlaskHub,
) -> None:
    deck = hub_server.app.config.deck("capitals-basic")
    card = hub_server.repository.active_cards(deck.name)[0]
    corrupt_due = utc_now() + timedelta(days=1)
    hub_server.repository.connection.execute(
        "UPDATE cards SET due_at = ? WHERE card_id = ?",
        (datetime_to_text(corrupt_due), card.card_id),
    )

    for method, path, fields in (
        ("GET", "/", None),
        ("GET", f"/decks/{deck.name}/cards", None),
        (
            "POST",
            "/sessions",
            start_form(hub_server, deck.name, StudyMode.DUE),
        ),
    ):
        status, _, body = exchange(hub_server, method, path, fields)
        assert status == 500
        assert "stored card due timestamp does not match its schedule" in body
        assert "Traceback" not in body
    assert review_count(hub_server.repository) == 0
