from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest
from fsrs import Rating
from hypothesis import given
from hypothesis import strategies as st

from graphcards.models import Card as SemanticCard
from graphcards.models import CardKey
from graphcards.storage import Repository, ReviewRecord, utc_now
from graphcards.web.app import MAX_FORM_BYTES
from graphcards.web.status import (
    CardStatusQuery,
    HistoryRange,
    history_view,
    pagination,
)
from graphcards.web.study import StudyMode
from tests.strategies import (
    EXPENSIVE_PROPERTY_SETTINGS,
    PROPERTY_SETTINGS,
    card_ids,
    invalid_card_ids,
    malformed_query_values,
    status_queries,
    suspension_reasons,
    tokens,
)


def _reset_web_context(controller: object, repository: Repository) -> None:
    with repository.connection:
        repository.connection.execute("DELETE FROM reviews")
        repository.connection.execute("DELETE FROM deck_cards")
        repository.connection.execute("DELETE FROM cards")
    controller.session = None
    for deck in controller.config.decks:
        controller.study_service.sync(deck, utc_now())


def _start_session(client: object, controller: object, mode: StudyMode = StudyMode.DUE) -> object:
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
    return controller.session


def _expected_status_rows(rows: list[object], query: CardStatusQuery, now: object) -> list[object]:
    filtered = []
    for row in rows:
        status = row.status
        if query.availability.value == "available" and status.suspended:
            continue
        if query.availability.value == "suspended" and not status.suspended:
            continue
        if query.schedule.value == "new" and status.review_count != 0:
            continue
        if query.schedule.value == "due" and status.due_at > now:
            continue
        if query.schedule.value == "future" and status.due_at <= now:
            continue
        if query.state.value != "all" and status.fsrs_state != query.state.value:
            continue
        filtered.append(row)

    def sort_value(row: object) -> object:
        status = row.status
        return {
            "next_review": status.due_at,
            "last_review": status.last_review_at,
            "review_count": status.review_count,
            "stability": status.stability,
            "difficulty": status.difficulty,
            "retrievability": row.retrievability,
        }[query.sort.value]

    ordered = sorted(filtered, key=lambda row: row.status.card_id)
    present = [row for row in ordered if sort_value(row) is not None]
    missing = [row for row in ordered if sort_value(row) is None]
    present.sort(key=sort_value, reverse=query.direction.value == "desc")
    return present + missing


def test_malformed_status_filters_do_not_mutate_state(
    web_context: tuple[object, object, Repository],
) -> None:
    # Property: malformed status filters return a controlled 4xx without changing storage.
    client, _controller, repository = web_context
    before = repository.status("capitals", utc_now())
    response = client.get("/decks/capitals/cards?sort=not-a-sort", headers={"Host": "localhost"})
    after = repository.status("capitals", utc_now())

    assert response.status_code == 400
    assert before == after


@pytest.mark.parametrize(
    ("endpoint", "data", "expected_status"),
    [
        ("/sessions", {"csrf_token": "wrong"}, 403),
        ("/study/reveal", {"session_token": "wrong"}, 403),
    ],
)
def test_malformed_or_unauthorized_web_submissions_are_rejected(
    web_context: tuple[object, object, Repository],
    endpoint: str,
    data: dict[str, str],
    expected_status: int,
) -> None:
    # Property: malformed or unauthorized submissions are rejected before any state mutation.
    client, controller, _repository = web_context
    if endpoint == "/study/reveal":
        session = _start_session(client, controller)
        assert session.current is not None
        data = {**data, "card_id": session.current.card.card_id}
    else:
        data = {
            "csrf_token": data["csrf_token"],
            "deck_name": "capitals",
            "mode": StudyMode.DUE.value,
            "days": "1",
            "limit": "1",
        }

    response = client.post(endpoint, data=data, headers={"Host": "localhost"})

    assert response.status_code == expected_status


def test_study_rejects_wrong_card_and_repeated_reveal(
    web_context: tuple[object, object, Repository],
) -> None:
    # Property: study reveal accepts only the current card and is not repeatable.
    client, controller, _repository = web_context
    session = _start_session(client, controller)
    assert session.current is not None
    token = session.session_token
    card_id = session.current.card.card_id

    wrong_card = client.post(
        "/study/reveal",
        data={"session_token": token, "card_id": "0" * 64},
        headers={"Host": "localhost"},
    )
    first_reveal = client.post(
        "/study/reveal",
        data={"session_token": token, "card_id": card_id},
        headers={"Host": "localhost"},
    )
    repeated_reveal = client.post(
        "/study/reveal",
        data={"session_token": token, "card_id": card_id},
        headers={"Host": "localhost"},
    )

    assert wrong_card.status_code == 409
    assert first_reveal.status_code == 303
    assert repeated_reveal.status_code == 409


@given(mode=st.sampled_from([StudyMode.DUE, StudyMode.PRACTICE]))
@EXPENSIVE_PROPERTY_SETTINGS
def test_study_refresh_and_navigation_preserve_current_card(
    web_context: tuple[object, object, Repository], mode: StudyMode
) -> None:
    # Property: refreshing or navigating study preserves the current card and reveal state.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    session = _start_session(client, controller, mode)
    assert session.current is not None
    current = session.current
    index = session.index
    assert client.get("/study", headers={"Host": "localhost"}).status_code == 200
    assert client.get("/", headers={"Host": "localhost"}).status_code == 200
    assert session.current is current
    assert session.index == index
    assert current.revealed is False
    assert (
        client.post(
            "/study/reveal",
            data={"session_token": session.session_token, "card_id": current.card.card_id},
            headers={"Host": "localhost"},
        ).status_code
        == 303
    )
    assert client.get("/study", headers={"Host": "localhost"}).status_code == 200
    assert session.current is current
    assert current.revealed is True
    assert repository.review_history("capitals", utc_now()) == ()


def test_status_actions_reject_invalid_csrf_without_mutation(
    web_context: tuple[object, object, Repository],
) -> None:
    # Property: invalid CSRF tokens prevent status actions and leave card state unchanged.
    client, _controller, repository = web_context
    card_id = repository.active_cards("capitals")[0].card_id
    before = repository.card_statuses("capitals")

    response = client.post(
        "/decks/capitals/cards/suspend",
        data={"csrf_token": "wrong", "card_id": card_id, "reason": "bad token"},
        headers={"Host": "localhost"},
    )

    assert response.status_code == 403
    assert repository.card_statuses("capitals") == before


@given(page=st.integers(min_value=1, max_value=3))
@PROPERTY_SETTINGS
def test_pagination_preserves_valid_page_ranges(page: int) -> None:
    # Property: pagination bounds are monotonic and clipped to the available result count.
    query = CardStatusQuery(page=page)
    view = pagination(query, 201, 3, lambda number: str(number))
    assert view.pages == 3
    assert view.first == (page - 1) * 100 + 1
    assert view.last == min(page * 100, 201)


def test_status_endpoint_supports_a_second_page(
    web_context: tuple[object, object, Repository],
) -> None:
    # Property: a valid second status page returns only the cards in that page.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    deck = controller.config.deck("capitals")
    generated = controller.study_service.generate_all(deck)
    extras = {
        key.digest: SemanticCard(card_key=key)
        for key in (
            CardKey.exercise("capitals", "property", f"extra-{index}") for index in range(110)
        )
    }
    repository.sync_deck("capitals", {**generated, **extras}, utc_now())
    response = client.get(
        "/decks/capitals/cards?page=2",
        headers={"Host": "localhost"},
    )
    assert response.status_code == 200
    expected_page_size = len(generated) + len(extras) - 100
    assert (
        len(re.findall(rb'name="card_id" value="([0-9a-f]{64})"', response.data))
        == expected_page_size
    )


@given(values=status_queries())
@EXPENSIVE_PROPERTY_SETTINGS
def test_generated_status_filters_sort_and_paginate_without_server_errors(
    web_context: tuple[object, object, Repository], values: dict[str, object]
) -> None:
    # Property: valid generated filters produce the same sorted page the status view computes.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    query = CardStatusQuery.model_validate(values)
    deck = controller.config.deck("capitals")
    initial_cards = repository.active_cards("capitals")
    controller.study_service.review(deck, initial_cards[0], Rating.Good, utc_now())
    repository.suspend_card("capitals", initial_cards[1].card_id, "paused")
    now = utc_now()
    rows = list(controller.card_statuses(deck, now))
    before_request = repository.card_statuses("capitals")
    ordered = _expected_status_rows(rows, query, now)
    page_count = max(1, (len(ordered) + 99) // 100)

    response = client.get(
        "/decks/capitals/cards?" + urlencode(values, doseq=True),
        headers={"Host": "localhost"},
    )
    if query.page <= page_count:
        assert response.status_code == 200
        page_rows = ordered[(query.page - 1) * 100 : query.page * 100]
        actual_ids = [
            value.decode()
            for value in re.findall(rb'name="card_id" value="([0-9a-f]{64})"', response.data)
        ]
        assert actual_ids == [row.status.card_id for row in page_rows]
    else:
        assert response.status_code == 404
    assert repository.card_statuses("capitals") == before_request
    assert repository.status("capitals", utc_now()).available >= 0


@given(query=malformed_query_values())
@EXPENSIVE_PROPERTY_SETTINGS
def test_malformed_encoded_queries_are_controlled_client_errors(
    web_context: tuple[object, object, Repository], query: str
) -> None:
    # Property: malformed encoded query values return 400 and are not reflected or persisted.
    client, _controller, repository = web_context
    _reset_web_context(_controller, repository)
    before = repository.card_statuses("capitals")
    response = client.get(
        "/decks/capitals/cards?sort=" + query,
        headers={"Host": "localhost"},
    )
    assert response.status_code == 400
    assert repository.card_statuses("capitals") == before
    assert query.encode() not in response.data


@given(size=st.integers(min_value=MAX_FORM_BYTES + 1, max_value=MAX_FORM_BYTES + 512))
@EXPENSIVE_PROPERTY_SETTINGS
def test_oversized_queries_are_rejected_without_state_changes(
    web_context: tuple[object, object, Repository], size: int
) -> None:
    # Property: oversized query input is rejected before it can affect repository state.
    client, _controller, repository = web_context
    before = repository.card_statuses("capitals")
    response = client.get(
        "/decks/capitals/cards?x=" + "a" * size,
        headers={"Host": "localhost"},
    )
    assert response.status_code == 400
    assert repository.card_statuses("capitals") == before


@given(case=st.sampled_from(["csrf", "deck", "mode", "days", "limit-low", "limit-high", "extra"]))
@EXPENSIVE_PROPERTY_SETTINGS
def test_malformed_session_forms_do_not_mutate_state(
    web_context: tuple[object, object, Repository], case: str
) -> None:
    # Property: every malformed session form is a controlled 400 with no session or storage change.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    before = repository.status("capitals", utc_now())
    data: dict[str, object] = {
        "csrf_token": controller.csrf_token,
        "deck_name": "capitals",
        "mode": StudyMode.DUE.value,
        "days": "1",
        "limit": "1",
    }
    if case == "csrf":
        data.pop("csrf_token")
    elif case == "deck":
        data.pop("deck_name")
    elif case == "mode":
        data["mode"] = "invalid"
    elif case == "days":
        data["days"] = "0"
    elif case == "limit-low":
        data["limit"] = "-1"
    elif case == "limit-high":
        data["limit"] = "1001"
    else:
        data["unexpected"] = "value"
    response = client.post("/sessions", data=data, headers={"Host": "localhost"})
    assert response.status_code == 400
    assert controller.session is None
    assert repository.status("capitals", utc_now()) == before


@given(selected=st.sampled_from(list(HistoryRange)))
@EXPENSIVE_PROPERTY_SETTINGS
def test_empty_history_ranges_have_consistent_zero_totals(
    web_context: tuple[object, object, Repository], selected: HistoryRange
) -> None:
    # Property: empty history ranges have internally consistent zero-valued aggregates.
    _client, controller, repository = web_context
    _reset_web_context(controller, repository)
    history = controller.card_history(controller.config.deck("capitals"), selected, utc_now())
    assert history.selected_range is selected
    assert history.total_reviews == 0
    assert history.active_days == history.current_streak == history.longest_streak == 0
    assert sum(bucket.count for bucket in history.buckets) == 0
    assert sum(rating.count for rating in history.ratings) == 0


@given(selected=st.sampled_from(list(HistoryRange)))
@PROPERTY_SETTINGS
def test_history_ranges_include_only_reviews_in_the_selected_window(selected: HistoryRange) -> None:
    # Property: history totals include exactly the reviews inside the selected time window.
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)
    records = (
        ReviewRecord(
            review_id=1,
            card_id="old",
            deck_name="deck",
            rating=Rating.Good,
            reviewed_at=now - timedelta(days=100),
            previous_interval_seconds=None,
            scheduled_interval_seconds=86400,
            retrievability=None,
        ),
        ReviewRecord(
            review_id=2,
            card_id="recent",
            deck_name="deck",
            rating=Rating.Easy,
            reviewed_at=now - timedelta(days=1),
            previous_interval_seconds=86400,
            scheduled_interval_seconds=172800,
            retrievability=0.8,
        ),
    )
    history = history_view(records, selected, now, ZoneInfo("UTC"))
    expected_total = 2 if selected in {HistoryRange.ONE_YEAR, HistoryRange.ALL} else 1
    assert history.total_reviews == expected_total
    assert sum(bucket.count for bucket in history.buckets) == history.total_reviews


@given(content_type=st.sampled_from(["application/json", "text/plain", "multipart/form-data"]))
@EXPENSIVE_PROPERTY_SETTINGS
def test_non_urlencoded_forms_are_rejected_before_mutation(
    web_context: tuple[object, object, Repository], content_type: str
) -> None:
    # Property: non-form content types are rejected before session creation or mutation.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    before = repository.status("capitals", utc_now())
    response = client.open(
        "/sessions",
        method="POST",
        data=b"csrf_token=bad&deck_name=capitals&mode=due",
        content_type=content_type,
        headers={"Host": "localhost"},
    )
    assert response.status_code == 400
    assert controller.session is None
    assert repository.status("capitals", utc_now()) == before


@given(card_id=invalid_card_ids())
@EXPENSIVE_PROPERTY_SETTINGS
def test_invalid_study_ids_do_not_mutate_state(
    web_context: tuple[object, object, Repository], card_id: str
) -> None:
    # Property: malformed card IDs return 400 without changing study or review state.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    session = _start_session(client, controller)
    assert session.current is not None
    current = session.current
    before_index = session.index
    before_complete = session.complete
    before = {card.card_id: card.card_json for card in repository.active_cards("capitals")}
    response = client.post(
        "/study/reveal",
        data={
            "session_token": session.session_token,
            "card_id": card_id,
        },
        headers={"Host": "localhost"},
    )
    assert response.status_code == 400
    assert {card.card_id: card.card_json for card in repository.active_cards("capitals")} == before
    assert repository.review_history("capitals", utc_now()) == ()
    assert session.current is current
    assert current.revealed is False
    assert session.index == before_index
    assert session.complete is before_complete


@given(token=tokens())
@EXPENSIVE_PROPERTY_SETTINGS
def test_invalid_study_tokens_do_not_mutate_state(
    web_context: tuple[object, object, Repository], token: str
) -> None:
    # Property: malformed session tokens return 403 without changing the active study card.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    session = _start_session(client, controller)
    assert session.current is not None
    current = session.current
    response = client.post(
        "/study/reveal",
        data={"session_token": token, "card_id": current.card.card_id},
        headers={"Host": "localhost"},
    )
    assert response.status_code == 403
    assert session.current is current
    assert current.revealed is False


def test_inactive_membership_status_actions_are_not_mutating(
    web_context: tuple[object, object, Repository],
) -> None:
    # Property: actions against inactive memberships return 404 and preserve their database row.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    card_id = repository.active_cards("capitals")[0].card_id
    repository.sync_deck("capitals", {}, utc_now())
    before = repository.connection.execute(
        "SELECT suspended, suspension_reason FROM deck_cards WHERE deck_name = ? AND card_id = ?",
        ("capitals", card_id),
    ).fetchone()
    for endpoint in ("suspend", "resume"):
        response = client.post(
            f"/decks/capitals/cards/{endpoint}",
            data={"csrf_token": controller.csrf_token, "card_id": card_id},
            headers={"Host": "localhost"},
        )
        assert response.status_code == 404
    after = repository.connection.execute(
        "SELECT suspended, suspension_reason FROM deck_cards WHERE deck_name = ? AND card_id = ?",
        ("capitals", card_id),
    ).fetchone()
    assert after == before


@given(rating=st.sampled_from(list(Rating)), stale_token=tokens())
@EXPENSIVE_PROPERTY_SETTINGS
def test_valid_reveal_rate_lifecycle_records_exactly_one_review(
    web_context: tuple[object, object, Repository], rating: Rating, stale_token: str
) -> None:
    # Property: the reveal/rate lifecycle records exactly one review and rejects repeats.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    session = _start_session(client, controller)
    assert session.current is not None
    card_id = session.current.card.card_id
    token = session.session_token

    assert (
        client.post(
            "/study/rate",
            data={"session_token": token, "card_id": card_id, "rating": rating.value},
            headers={"Host": "localhost"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/study/reveal",
            data={"session_token": stale_token, "card_id": card_id},
            headers={"Host": "localhost"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/study/reveal",
            data={"session_token": token, "card_id": card_id},
            headers={"Host": "localhost"},
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/study/rate",
            data={"session_token": token, "card_id": card_id, "rating": rating.value},
            headers={"Host": "localhost"},
        ).status_code
        == 303
    )
    assert len(repository.review_history("capitals", utc_now())) == 1
    assert (
        client.post(
            "/study/rate",
            data={"session_token": token, "card_id": card_id, "rating": rating.value},
            headers={"Host": "localhost"},
        ).status_code
        == 409
    )
    assert len(repository.review_history("capitals", utc_now())) == 1


@given(rating=st.sampled_from(list(Rating)))
@EXPENSIVE_PROPERTY_SETTINGS
def test_rating_after_concurrent_suspension_is_a_controlled_conflict(
    web_context: tuple[object, object, Repository], rating: Rating
) -> None:
    # Property: rating a card suspended concurrently becomes a controlled conflict with no review.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    session = _start_session(client, controller)
    assert session.current is not None
    current = session.current
    assert (
        client.post(
            "/study/reveal",
            data={"session_token": session.session_token, "card_id": current.card.card_id},
            headers={"Host": "localhost"},
        ).status_code
        == 303
    )
    repository.suspend_card("capitals", current.card.card_id, "concurrent")
    response = client.post(
        "/study/rate",
        data={
            "session_token": session.session_token,
            "card_id": current.card.card_id,
            "rating": rating.value,
        },
        headers={"Host": "localhost"},
    )
    assert response.status_code == 409
    assert repository.review_history("capitals", utc_now()) == ()


@given(reason=suspension_reasons())
@EXPENSIVE_PROPERTY_SETTINGS
def test_generated_status_form_values_never_create_reviews(
    web_context: tuple[object, object, Repository], reason: str
) -> None:
    # Property: generated suspension form values never create review history and validate safely.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    card_id = repository.active_cards("capitals")[0].card_id
    before = repository.card_statuses("capitals")
    response = client.post(
        "/decks/capitals/cards/suspend",
        data={"csrf_token": controller.csrf_token, "card_id": card_id, "reason": reason},
        headers={"Host": "localhost"},
    )
    valid_reason = len(reason) <= 500 and not any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in reason
    )
    assert response.status_code == (303 if valid_reason else 400)
    assert repository.review_history("capitals", utc_now()) == ()
    if valid_reason:
        status = next(
            item for item in repository.card_statuses("capitals") if item.card_id == card_id
        )
        assert status.suspended is True
        page = client.get("/decks/capitals/cards", headers={"Host": "localhost"})
        if "<" in reason:
            assert reason.encode() not in page.data
    else:
        assert repository.card_statuses("capitals") == before


@given(card_id=card_ids())
@EXPENSIVE_PROPERTY_SETTINGS
def test_unknown_valid_shape_card_ids_are_controlled_client_errors(
    web_context: tuple[object, object, Repository], card_id: str
) -> None:
    # Property: unknown but well-shaped card IDs return 404 without mutating status state.
    client, controller, repository = web_context
    _reset_web_context(controller, repository)
    known = {card.card_id for card in repository.active_cards("capitals")}
    if card_id in known:
        return
    before = repository.card_statuses("capitals")
    response = client.post(
        "/decks/capitals/cards/suspend",
        data={"csrf_token": controller.csrf_token, "card_id": card_id},
        headers={"Host": "localhost"},
    )
    assert response.status_code == 404
    assert repository.card_statuses("capitals") == before
