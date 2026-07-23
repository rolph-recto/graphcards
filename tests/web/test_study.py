from __future__ import annotations

import random
import sqlite3
from datetime import timedelta

import pytest
from fsrs import Rating
from rdflib import Literal

from rdfcards.app import StudyService
from rdfcards.config import AppConfig
from rdfcards.decks import Basic, ChoiceOption, MultipleChoice
from rdfcards.errors import PresentationError
from rdfcards.presentation import load_graph
from rdfcards.storage import Repository, utc_now
from rdfcards.web.study import StudyMode, StudySession
from tests.web.support import (
    FlaskHub,
    current_form,
    exchange,
    make_test_hub,
    review_count,
    set_card_due,
    start_form,
    start_session,
)


def test_regular_study_uses_all_due_cards_and_hides_answer_until_reveal(
    hub_server: FlaskHub,
) -> None:
    session = start_session(hub_server)
    assert len(session.cards) == 2
    current = session.current
    assert current is not None

    status, _, body = exchange(hub_server, "GET", "/study")
    assert status == 200
    assert current.front in body
    assert current.back not in body
    assert "Reveal answer" in body

    status, headers, _ = exchange(
        hub_server,
        "POST",
        "/study/reveal",
        current_form(hub_server),
    )
    assert status == 303
    assert headers["location"] == "/study"

    status, _, body = exchange(hub_server, "GET", "/study")
    assert status == 200
    assert current.back in body
    assert all(label in body for label in ("Again", "Hard", "Good", "Easy"))
    assert all(
        class_name in body
        for class_name in ("rating-again", "rating-hard", "rating-good", "rating-easy")
    )


@pytest.mark.parametrize("rating", list(Rating))
def test_every_http_rating_is_persisted(
    config: AppConfig,
    rating: Rating,
) -> None:
    server = make_test_hub(config)
    try:
        start_session(server)
        fields = current_form(server)
        assert exchange(server, "POST", "/study/reveal", fields)[0] == 303
        assert exchange(server, "POST", "/study/rate", fields | {"rating": rating.value})[0] == 303

        stored_rating = server.repository.connection.execute(
            "SELECT rating FROM reviews"
        ).fetchone()[0]
        assert stored_rating == rating.value
        assert server.app.session is not None
        assert server.app.session.completed_count == 1
    finally:
        server.close()


def test_index_offers_resume_and_new_session_replaces_current(
    hub_server: FlaskHub,
) -> None:
    first = start_session(hub_server, "capitals-basic")

    body = exchange(hub_server, "GET", "/")[2]
    assert "Study session in progress" in body
    assert "capitals-basic" in body
    assert 'href="/study">Resume' in body

    replacement = start_session(
        hub_server,
        "capitals-choice",
        StudyMode.PRACTICE,
        limit=1,
    )
    assert replacement is not first
    assert replacement.deck.name == "capitals-choice"
    assert replacement.mode is StudyMode.PRACTICE


def test_invalid_session_forms_do_not_replace_active_session(
    hub_server: FlaskHub,
) -> None:
    original = start_session(hub_server)
    valid = start_form(hub_server, "capitals-choice", StudyMode.PRACTICE)

    cases = (
        (valid | {"csrf_token": "wrong"}, 403),
        (valid | {"deck_name": "missing"}, 400),
        (valid | {"mode": "unknown"}, 400),
        (valid | {"days": 0}, 400),
        (valid | {"days": 366}, 400),
        (valid | {"limit": -1}, 400),
    )
    for fields, expected_status in cases:
        assert exchange(hub_server, "POST", "/sessions", fields)[0] == expected_status
        assert hub_server.app.session is original


def test_invalid_and_repeated_rating_forms_do_not_duplicate_reviews(
    hub_server: FlaskHub,
) -> None:
    start_session(hub_server)
    fields = current_form(hub_server)

    assert exchange(hub_server, "POST", "/study/rate", fields | {"rating": 3})[0] == 409
    assert (
        exchange(
            hub_server,
            "POST",
            "/study/reveal",
            fields | {"session_token": "wrong"},
        )[0]
        == 403
    )
    assert exchange(hub_server, "POST", "/study/reveal", fields)[0] == 303
    assert exchange(hub_server, "POST", "/study/rate", fields | {"rating": 5})[0] == 400
    assert review_count(hub_server.repository) == 0

    assert exchange(hub_server, "POST", "/study/rate", fields | {"rating": 3})[0] == 303
    assert review_count(hub_server.repository) == 1
    assert exchange(hub_server, "POST", "/study/rate", fields | {"rating": 3})[0] == 409
    assert review_count(hub_server.repository) == 1


def test_repeated_reveal_is_rejected_without_recording_a_review(
    hub_server: FlaskHub,
) -> None:
    start_session(hub_server)
    fields = current_form(hub_server)

    assert exchange(hub_server, "POST", "/study/reveal", fields)[0] == 303
    assert exchange(hub_server, "POST", "/study/reveal", fields)[0] == 409
    assert review_count(hub_server.repository) == 0


def test_cross_session_tokens_are_rejected_before_mode_specific_actions(
    hub_server: FlaskHub,
) -> None:
    start_session(hub_server, mode=StudyMode.PRACTICE)
    practice_fields = current_form(hub_server) | {"session_token": "wrong"}
    assert (
        exchange(
            hub_server,
            "POST",
            "/study/rate",
            practice_fields | {"rating": Rating.Good.value},
        )[0]
        == 403
    )

    start_session(hub_server, mode=StudyMode.DUE)
    due_fields = current_form(hub_server) | {"session_token": "wrong"}
    assert exchange(hub_server, "POST", "/study/next", due_fields)[0] == 403
    assert review_count(hub_server.repository) == 0


def test_rating_does_not_depend_on_a_fallible_post_commit_reload(
    hub_server: FlaskHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = start_session(hub_server)
    fields = current_form(hub_server)
    assert exchange(hub_server, "POST", "/study/reveal", fields)[0] == 303

    def fail_reload(_card_id: str) -> None:
        raise sqlite3.OperationalError("post-commit reload failed")

    monkeypatch.setattr(hub_server.repository, "get_card", fail_reload)

    assert (
        exchange(
            hub_server,
            "POST",
            "/study/rate",
            fields | {"rating": Rating.Good.value},
        )[0]
        == 303
    )
    assert session.completed_count == 1
    assert review_count(hub_server.repository) == 1
    assert (
        exchange(
            hub_server,
            "POST",
            "/study/rate",
            fields | {"rating": Rating.Good.value},
        )[0]
        == 409
    )
    assert review_count(hub_server.repository) == 1


def test_practice_is_stable_and_never_updates_scheduling(
    hub_server: FlaskHub,
) -> None:
    before = {
        card.card_id: card.card_json
        for card in hub_server.repository.active_cards("capitals-basic")
    }
    session = start_session(
        hub_server,
        "capitals-basic",
        StudyMode.PRACTICE,
        limit=0,
    )
    assert len(session.cards) == 2

    first = exchange(hub_server, "GET", "/study")[2]
    second = exchange(hub_server, "GET", "/study")[2]
    assert first == second
    fields = current_form(hub_server)
    assert exchange(hub_server, "POST", "/study/next", fields)[0] == 409
    assert exchange(hub_server, "POST", "/study/reveal", fields)[0] == 303
    assert exchange(hub_server, "POST", "/study/rate", fields | {"rating": 3})[0] == 409
    assert exchange(hub_server, "POST", "/study/next", fields)[0] == 303

    after = {
        card.card_id: card.card_json
        for card in hub_server.repository.active_cards("capitals-basic")
    }
    assert after == before
    assert review_count(hub_server.repository) == 0


def test_forgotten_session_uses_window_and_persists_new_rating(
    hub_server: FlaskHub,
) -> None:
    deck = hub_server.app.config.deck("capitals-basic")
    now = utc_now()
    cards = hub_server.repository.due_cards(deck.name, now, None)
    hub_server.app.study_service.review(deck, cards[0], Rating.Again, now - timedelta(days=2))
    hub_server.app.study_service.review(deck, cards[1], Rating.Again, now)

    session = start_session(
        hub_server,
        deck.name,
        StudyMode.FORGOTTEN,
        days=1,
        limit=20,
    )
    assert [card.card_id for card in session.cards] == [cards[1].card_id]

    fields = current_form(hub_server)
    assert exchange(hub_server, "POST", "/study/reveal", fields)[0] == 303
    assert exchange(hub_server, "POST", "/study/rate", fields | {"rating": 3})[0] == 303
    assert review_count(hub_server.repository) == 3


def test_review_ahead_uses_horizon_limit_and_reschedules(
    hub_server: FlaskHub,
) -> None:
    deck = hub_server.app.config.deck("capitals-basic")
    now = utc_now()
    cards = hub_server.repository.due_cards(deck.name, now, None)
    for card in cards:
        hub_server.app.study_service.review(deck, card, Rating.Good, now)
    near, far = cards
    set_card_due(hub_server.repository, near.card_id, now + timedelta(hours=12))
    set_card_due(hub_server.repository, far.card_id, now + timedelta(days=2))

    session = start_session(
        hub_server,
        deck.name,
        StudyMode.AHEAD,
        days=1,
        limit=1,
    )
    assert [card.card_id for card in session.cards] == [near.card_id]

    fields = current_form(hub_server)
    assert exchange(hub_server, "POST", "/study/reveal", fields)[0] == 303
    assert exchange(hub_server, "POST", "/study/rate", fields | {"rating": 4})[0] == 303
    assert review_count(hub_server.repository) == 3


def test_empty_advanced_filter_explains_result(hub_server: FlaskHub) -> None:
    session = start_session(
        hub_server,
        "capitals-basic",
        StudyMode.FORGOTTEN,
        days=1,
    )
    assert session.cards == ()

    body = exchange(hub_server, "GET", "/study")[2]
    assert "No forgotten cards" in body
    assert "last 1 day(s)" in body
    assert "Back to decks" in body


def test_no_active_session_and_unknown_routes_are_rejected(
    hub_server: FlaskHub,
) -> None:
    assert exchange(hub_server, "GET", "/study")[0] == 409
    assert exchange(hub_server, "GET", "/missing")[0] == 404
    assert exchange(hub_server, "POST", "/missing", {})[0] == 404


def test_corrupt_card_schedule_returns_safe_error_without_review(
    hub_server: FlaskHub,
) -> None:
    session = start_session(hub_server)
    assert session.current is not None
    session.current.card = session.current.card.model_copy(update={"card_json": "not JSON"})
    fields = current_form(hub_server)

    assert exchange(hub_server, "POST", "/study/reveal", fields)[0] == 303
    status, _, body = exchange(
        hub_server,
        "POST",
        "/study/rate",
        fields | {"rating": 3},
    )

    assert status == 500
    assert "stored card schedule is invalid" in body
    assert "Traceback" not in body
    assert review_count(hub_server.repository) == 0


def test_session_skips_presentation_errors(config: AppConfig) -> None:
    deck = config.deck("capitals-basic")
    graph = load_graph(config.sources)
    with Repository(config.state_path) as repository:
        app = StudyService(graph, repository, config.fsrs.create_scheduler())
        now = utc_now()
        app.sync(deck, now)
        cards = repository.due_cards(deck.name, now, None)
        original_render = app.render
        failed_card_id = cards[0].card_id

        def render_with_failure(deck_definition, card):
            if card.card_id == failed_card_id:
                raise PresentationError("cannot render test card")
            return original_render(deck_definition, card)

        app.render = render_with_failure  # type: ignore[method-assign]
        session = StudySession(
            deck,
            app,
            cards,
            StudyMode.DUE,
            1,
            0,
            random.Random(0),
        )

        assert session.index == 1
        assert session.current is not None
        assert session.current.card.card_id == cards[1].card_id
        assert len(session.skipped) == 1
        assert "cannot render test card" in session.skipped[0]


def test_session_uses_custom_deck_kind_front_text(config: AppConfig) -> None:
    class CustomKind(Basic):
        config_name = "custom_web_hub_test"

        def front_text(self, rng: random.Random) -> str:
            return f"Web custom: {super().front_text(rng)}"

    deck = config.deck("capitals-basic")
    graph = load_graph(config.sources)
    with Repository(config.state_path) as repository:
        app = StudyService(graph, repository, config.fsrs.create_scheduler())
        now = utc_now()
        app.sync(deck, now)
        cards = repository.due_cards(deck.name, now, 1)

        def render_custom(_deck, card):
            return CustomKind(
                card_key=card.card_key,
                front=Literal("custom front"),
                back=Literal("custom back"),
            )

        app.render = render_custom  # type: ignore[method-assign]
        session = StudySession(
            deck,
            app,
            cards,
            StudyMode.DUE,
            1,
            0,
            random.Random(0),
        )

        assert session.current is not None
        assert session.current.front == "Web custom: custom front"


def test_browser_multiple_choice_uses_priority_limit_and_keeps_correct_answer(
    config: AppConfig,
) -> None:
    class NoShuffleRandom(random.Random):
        def shuffle(self, values: list[object]) -> None:
            del values

    deck = config.deck("capitals-choice")
    graph = load_graph(config.sources)
    with Repository(config.state_path) as repository:
        app = StudyService(graph, repository, config.fsrs.create_scheduler())
        now = utc_now()
        app.sync(deck, now)
        cards = repository.due_cards(deck.name, now, 1)

        def render_limited(_deck, card):
            return MultipleChoice(
                card_key=card.card_key,
                front=Literal("question"),
                back=Literal("correct"),
                choices=(
                    ChoiceOption(choice=Literal("correct")),
                    ChoiceOption(choice=Literal("high-a"), priority=2),
                    ChoiceOption(choice=Literal("high-b"), priority=2),
                    ChoiceOption(choice=Literal("low"), priority=1),
                ),
                max_choices=3,
            )

        app.render = render_limited  # type: ignore[method-assign]
        session = StudySession(
            deck,
            app,
            cards,
            StudyMode.DUE,
            1,
            0,
            NoShuffleRandom(),
        )

        assert session.current is not None
        assert session.current.front == "question\n  1. correct\n  2. high-a\n  3. high-b"
        assert session.current.back == "correct"
        assert "low" not in session.current.front
