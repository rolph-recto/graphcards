from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

from fsrs import Rating
from hypothesis import given
from hypothesis import strategies as st
from markupsafe import escape as markup_escape

from graphcards.config import load_config
from graphcards.scaffold import initialize_workspace
from graphcards.web.study import StudyMode
from tests.strategies import (
    EXPENSIVE_PROPERTY_SETTINGS,
    PROPERTY_SETTINGS,
    invalid_card_ids,
    pagination_inputs,
    safe_labels,
    session_tokens,
)
from tests.web.support import (
    current_form,
    exchange,
    make_test_hub,
    review_count,
    start_session,
    status_action_form,
)


def _server() -> tuple[TemporaryDirectory[str], object]:
    directory = TemporaryDirectory()
    workspace = Path(directory.name)
    initialize_workspace(workspace, template="capitals")
    return directory, make_test_hub(load_config(workspace / "graphcards.toml"))


@given(
    query=st.sampled_from(
        [
            "schedule=%ZZ",
            "schedule=%A",
            "schedule=%FF",
            "schedule",
            "schedule=all&schedule=due",
            "range=30d&range=90d",
            "%FF=value",
        ]
    )
)
@EXPENSIVE_PROPERTY_SETTINGS
def test_malformed_query_parameters_are_controlled_client_errors(query: str) -> None:
    # Property: malformed query strings produce controlled client errors rather than server
    # failures.
    directory, server = _server()
    try:
        status, _, _ = exchange(server, "GET", f"/decks/capitals-basic/cards?{query}")
        assert 400 <= status < 500
    finally:
        server.close()
        directory.cleanup()


@given(content_type=st.sampled_from(["application/json", "text/plain", "multipart/form-data"]))
@EXPENSIVE_PROPERTY_SETTINGS
def test_non_urlencoded_form_content_types_do_not_reach_state_transitions(
    content_type: str,
) -> None:
    # Property: non-form content types are rejected before a session or review state transition.
    directory, server = _server()
    try:
        client = server.flask_app.test_client()
        response = client.open(
            "/sessions",
            method="POST",
            data=b"csrf_token=bad&deck_name=capitals-basic&mode=due",
            content_type=content_type,
            base_url="http://localhost",
        )
        try:
            assert 400 <= response.status_code < 500
            assert server.app.session is None
            assert review_count(server.repository) == 0
        finally:
            response.close()
    finally:
        server.close()
        directory.cleanup()


@given(card_id=invalid_card_ids, token=session_tokens)
@EXPENSIVE_PROPERTY_SETTINGS
def test_invalid_study_credentials_and_ids_do_not_mutate_state(
    card_id: str,
    token: str,
) -> None:
    # Property: invalid study credentials and card IDs cannot mutate sessions, schedules, or
    # reviews.
    directory, server = _server()
    try:
        start_session(server)
        session = server.app.session
        assert session is not None
        before_cards = {
            card.card_id: card.card_json
            for card in server.repository.active_cards("capitals-basic")
        }
        fields = current_form(server) | {"card_id": card_id, "session_token": token}
        status = exchange(server, "POST", "/study/reveal", fields)[0]
        assert 400 <= status < 500
        assert review_count(server.repository) == 0
        assert {
            card.card_id: card.card_json
            for card in server.repository.active_cards("capitals-basic")
        } == before_cards
        assert server.app.session is session
    finally:
        server.close()
        directory.cleanup()


@given(rating=st.sampled_from(list(Rating)), stale_token=session_tokens)
@EXPENSIVE_PROPERTY_SETTINGS
def test_generated_study_lifecycle_requires_reveal_and_accepts_one_rating(
    rating: Rating,
    stale_token: str,
) -> None:
    # Property: study lifecycle enforces reveal-before-rate and accepts exactly one rating per
    # current card.
    directory, server = _server()
    try:
        session = start_session(server, mode=StudyMode.DUE)
        assert session.current is not None
        current = session.current
        fields = current_form(server)
        assert exchange(server, "GET", "/study")[0] == 200
        assert exchange(server, "POST", "/study/rate", fields | {"rating": rating.value})[0] == 409
        assert review_count(server.repository) == 0

        wrong = stale_token if stale_token != session.session_token else "wrong"
        assert exchange(server, "POST", "/study/reveal", fields | {"session_token": wrong})[0] in {
            400,
            403,
        }
        assert not current.revealed
        assert exchange(server, "GET", "/study")[0] == 200

        assert exchange(server, "POST", "/study/reveal", fields)[0] == 303
        assert exchange(server, "POST", "/study/reveal", fields)[0] == 409
        assert exchange(server, "POST", "/study/rate", fields | {"rating": rating.value})[0] == 303
        assert review_count(server.repository) == 1
        assert exchange(server, "POST", "/study/rate", fields | {"rating": rating.value})[0] == 409
        assert review_count(server.repository) == 1
    finally:
        server.close()
        directory.cleanup()


@given(
    values=st.fixed_dictionaries(
        {
            "availability": st.sampled_from(["all", "available", "suspended"]),
            "schedule": st.sampled_from(["all", "new", "due", "future"]),
            "state": st.sampled_from(["all", "learning", "review", "relearning"]),
            "sort": st.sampled_from(
                [
                    "next_review",
                    "last_review",
                    "review_count",
                    "stability",
                    "difficulty",
                    "retrievability",
                ]
            ),
            "direction": st.sampled_from(["asc", "desc"]),
            "range": st.sampled_from(["30d", "90d", "1y", "all"]),
            "page": pagination_inputs,
        }
    )
)
@EXPENSIVE_PROPERTY_SETTINGS
def test_generated_status_filters_return_only_documented_status_classes(
    values: dict[str, str],
) -> None:
    # Property: generated status filters and pagination return only documented client/success
    # statuses.
    directory, server = _server()
    try:
        path = "/decks/capitals-basic/cards?" + urlencode(values)
        status, _, _ = exchange(server, "GET", path)
        assert status in {200, 400, 404}
        assert status != 500
    finally:
        server.close()
        directory.cleanup()


@given(reason=safe_labels)
@PROPERTY_SETTINGS
def test_user_controlled_suspension_reasons_are_escaped_and_do_not_review(
    reason: str,
) -> None:
    # Property: user-controlled suspension reasons are escaped in HTML and never create reviews.
    directory, server = _server()
    try:
        card = server.repository.active_cards("capitals-basic")[0]
        status, _, _ = exchange(
            server,
            "POST",
            "/decks/capitals-basic/cards/suspend",
            status_action_form(server, card.card_id, reason=reason),
        )
        assert status in {303, 400}
        assert review_count(server.repository) == 0
        if reason.strip() and status == 303:
            body = exchange(
                server,
                "GET",
                "/decks/capitals-basic/cards?availability=suspended",
            )[2]
            assert str(markup_escape(reason.strip())) in body
            assert server.repository.card_suspended("capitals-basic", card.card_id)
    finally:
        server.close()
        directory.cleanup()


def test_invalid_encoded_form_bytes_are_400_and_leave_sessions_uncreated() -> None:
    # Property: invalid percent-encoded form bytes are rejected without creating a session.
    directory, server = _server()
    try:
        client = server.flask_app.test_client()
        response = client.open(
            "/sessions",
            method="POST",
            data=b"csrf_token=%FF&deck_name=capitals-basic&mode=due",
            content_type="application/x-www-form-urlencoded",
            base_url="http://localhost",
        )
        try:
            assert response.status_code == 400
            assert server.app.session is None
        finally:
            response.close()
    finally:
        server.close()
        directory.cleanup()
