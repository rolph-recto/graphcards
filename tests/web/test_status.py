from __future__ import annotations

import json
import random
import re

import pytest
from fsrs import Rating
from werkzeug.datastructures import MultiDict

from graphcards.decks import BasicExerciseGenerator, Deck, DeckDocument, Entity
from graphcards.scheduling import (
    InterdayLearningReviewOrder,
    NewCardGatherOrder,
    NewCardSortOrder,
    NewReviewOrder,
    ReviewSortOrder,
)
from graphcards.storage import utc_now
from graphcards.web.app import EXPECTED_HOST_CONFIG, create_flask_app
from graphcards.web.status import (
    MAX_SEARCH_DEPTH,
    MAX_SEARCH_LENGTH,
    CardStatusQuery,
    SearchAnd,
    SearchOr,
    StatusCard,
    parse_search_expression,
    parse_search_terms,
    search_matches,
    status_row,
)
from graphcards.web.study import RequestFailure


def _first_status_row_cells(data: bytes) -> list[bytes]:
    row = re.search(rb'<tr class="status-card">(.*?)</tr>', data, re.DOTALL)
    assert row is not None
    contents = re.sub(rb"<!--.*?-->", b"", row.group(1), flags=re.DOTALL)
    return re.findall(rb"<td>(.*?)</td>", contents, re.DOTALL)


def _generator_cards(data: bytes) -> list[bytes]:
    return re.findall(rb'<article class="generator-card">.*?</article>', data, re.DOTALL)


def _preview_panel(data: bytes) -> bytes:
    panel = re.search(
        rb'<aside class="exercise-preview exercise-preview-panel".*?</aside>',
        data,
        re.DOTALL,
    )
    assert panel is not None
    return panel.group(0)


def test_status_page_lists_cards_and_filters(web_context: tuple[object, object, object]) -> None:
    client, controller, repository = web_context
    deck = controller.config.deck("capitals")
    reviewed = repository.active_cards("capitals")[0]
    controller.study_service.review(deck, reviewed, Rating.Good, utc_now())
    response = client.get(
        "/decks/capitals/cards?tab=status&schedule=new",
        headers={"Host": "localhost"},
    )
    all_cards = client.get(
        "/decks/capitals/cards?tab=status&schedule=all",
        headers={"Host": "localhost"},
    )

    assert response.status_code == 200
    assert b"Card status" in response.data
    assert b'entity_id="france"' not in response.data
    assert b"france" in all_cards.data


def test_deck_status_settings_are_rendered_and_persisted(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, repository = web_context

    status = client.get("/decks/capitals/cards", headers={"Host": "localhost"})
    assert status.status_code == 200
    assert b'aria-current="page">Deck status' in status.data
    assert b"Study queues" in status.data
    assert b"New/review order" in status.data
    assert b"Interday learning/review order" in status.data
    assert b"New-card gather order" in status.data
    assert b"New-card sort order" in status.data
    assert b"Review sort order" in status.data
    assert b"Save queue settings" in status.data

    saved = client.post(
        "/decks/capitals/settings",
        data={
            "csrf_token": controller.csrf_token,
            "new_review_order": NewReviewOrder.NEW_FIRST.value,
            "interday_learning_review_order": InterdayLearningReviewOrder.REVIEWS_FIRST.value,
            "new_card_gather_order": NewCardGatherOrder.RANDOM_CARDS.value,
            "new_card_sort_order": NewCardSortOrder.RANDOM.value,
            "review_sort_order": ReviewSortOrder.DESCENDING_INTERVAL.value,
        },
        headers={"Host": "localhost"},
    )
    assert saved.status_code == 303
    assert "tab=deck_status" in saved.headers["Location"]
    settings = repository.deck_settings("capitals")
    assert settings.new_review_order is NewReviewOrder.NEW_FIRST
    assert settings.interday_learning_review_order is InterdayLearningReviewOrder.REVIEWS_FIRST
    assert settings.new_card_gather_order is NewCardGatherOrder.RANDOM_CARDS
    assert settings.new_card_sort_order is NewCardSortOrder.RANDOM
    assert settings.review_sort_order is ReviewSortOrder.DESCENDING_INTERVAL


def test_deck_status_settings_reject_invalid_values_and_csrf(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, repository = web_context
    before = repository.deck_settings("capitals")
    values = {
        "csrf_token": controller.csrf_token,
        "new_review_order": NewReviewOrder.NEW_FIRST.value,
        "interday_learning_review_order": InterdayLearningReviewOrder.REVIEWS_FIRST.value,
        "new_card_gather_order": NewCardGatherOrder.DECK.value,
        "new_card_sort_order": NewCardSortOrder.ORDER_GATHERED.value,
        "review_sort_order": ReviewSortOrder.DUE_DATE.value,
    }

    invalid = client.post(
        "/decks/capitals/settings",
        data={**values, "review_sort_order": "not-a-supported-sort"},
        headers={"Host": "localhost"},
    )
    assert invalid.status_code == 400
    assert repository.deck_settings("capitals") == before

    invalid_csrf = client.post(
        "/decks/capitals/settings",
        data={**values, "csrf_token": "wrong"},
        headers={"Host": "localhost"},
    )
    assert invalid_csrf.status_code == 403
    assert repository.deck_settings("capitals") == before


def test_status_page_searches_entity_fields_and_rejects_bad_syntax(
    web_context: tuple[object, object, object],
) -> None:
    client, _controller, _repository = web_context

    field_search = client.get(
        "/decks/capitals/cards?tab=status&search=field%3Afront%3DFrance",
        headers={"Host": "localhost"},
    )
    text_search = client.get(
        "/decks/capitals/cards?tab=status&search=Germany",
        headers={"Host": "localhost"},
    )
    boolean_search = client.get(
        "/decks/capitals/cards?tab=status&search=field%3Afront%3DFrance%20OR%20field%3Afront%3DGermany",
        headers={"Host": "localhost"},
    )
    id_search = client.get(
        "/decks/capitals/cards?tab=status&search=id%3A%22france%22",
        headers={"Host": "localhost"},
    )
    malformed = client.get(
        "/decks/capitals/cards?tab=status&search=%22unclosed",
        headers={"Host": "localhost"},
    )

    assert field_search.status_code == 200
    assert b'aria-label="More details for france"' in field_search.data
    assert b'aria-label="More details for germany"' not in field_search.data
    assert text_search.status_code == 200
    assert b'aria-label="More details for germany"' in text_search.data
    assert b'aria-label="More details for france"' not in text_search.data
    assert boolean_search.status_code == 200
    assert b'aria-label="More details for france"' in boolean_search.data
    assert b'aria-label="More details for germany"' in boolean_search.data
    assert id_search.status_code == 200
    assert b'aria-label="More details for france"' in id_search.data
    assert b'aria-label="More details for germany"' not in id_search.data
    assert malformed.status_code == 200
    assert b'role="alert"' in malformed.data
    assert b"The search syntax is invalid." in malformed.data
    assert b'value="%22unclosed"' not in malformed.data


def test_status_search_query_validates_typed_terms() -> None:
    query = CardStatusQuery(search="id:earth reviews>=2 due>=2026-01-01")

    assert query.search.startswith("id:earth")
    assert len(parse_search_terms(query.search)) == 3
    quoted_state = CardStatusQuery(search='state:"review"')
    assert quoted_state.search_terms[0].value == "review"
    quoted_id = CardStatusQuery(search='id:"earth"')
    assert quoted_id.search_terms[0].kind == "id"
    assert quoted_id.search_terms[0].value == "earth"
    with pytest.raises(ValueError):
        CardStatusQuery(search="stability=not-a-number")


def test_status_search_boolean_precedence_and_parentheses(
    web_context: tuple[object, object, object],
) -> None:
    _client, controller, _repository = web_context
    deck = controller.config.deck("capitals")
    now = utc_now()
    source = controller.card_statuses(deck, now)[0]
    tagged = StatusCard(
        status=source.status,
        entity=Entity(id=source.entity.id, front="France", tags=["travel"]),
        retrievability=source.retrievability,
    )

    expression = parse_search_expression("field:front=France OR field:front=Germany state:new")
    assert isinstance(expression, SearchOr)
    assert isinstance(expression.expressions[1], SearchAnd)
    assert parse_search_expression("state:new OR state:review") is not None
    assert parse_search_expression('"AND"') is not None
    with pytest.raises(ValueError):
        parse_search_expression("state:new state:review")

    def matches(search: str) -> bool:
        return search_matches(
            tagged,
            CardStatusQuery(search=search),
            now,
            controller.config.display_timezone,
            deck_name=deck.name,
            deck_display_name=deck.display_name,
        )

    assert matches("field:front=France OR field:front=Germany state:new")
    assert matches("(field:front=France OR field:front=Germany) AND state:new")
    assert matches("field:front=France AND NOT field:front=Germany")


def test_status_search_matches_review_properties(
    web_context: tuple[object, object, object],
) -> None:
    _client, controller, repository = web_context
    deck = controller.config.deck("capitals")
    now = utc_now()
    source = controller.card_statuses(deck, now)[0]
    tagged = StatusCard(
        status=source.status,
        entity=Entity(id=source.entity.id, front="France", tags=["travel"]),
        retrievability=source.retrievability,
    )

    query = CardStatusQuery(search="field:front=France state:new reviews=0")
    assert search_matches(
        tagged,
        query,
        now,
        controller.config.display_timezone,
        deck_name=deck.name,
        deck_display_name=deck.display_name,
    )

    stored = repository.active_cards("capitals")[0]
    controller.study_service.review(deck, stored, Rating.Good, now)
    reviewed = next(
        row for row in controller.card_statuses(deck, now) if row.status.card_key == stored.card_key
    )
    reviewed_query = CardStatusQuery(
        search=("reviews>=1 last_review>=2026-01-01 stability>=0 difficulty>=0 retrievability>=0")
    )
    assert reviewed.retrievability is not None
    assert search_matches(
        reviewed,
        reviewed_query,
        now,
        controller.config.display_timezone,
        deck_name=deck.name,
        deck_display_name=deck.display_name,
    )


@pytest.mark.parametrize(
    "search",
    [
        "state:new state:review",
        "tag:travel",
        "deck:capitals",
        "is:due",
        "rating:good",
        "tag:travel OR",
        "(tag:travel",
        "NOT",
        "tag:travel AND )",
        "(" * (MAX_SEARCH_DEPTH + 1) + "id:travel" + ")" * (MAX_SEARCH_DEPTH + 1),
        "reviews~2",
        "due=not-a-date",
        "field:=value",
        "\x00",
        " ".join("term" for _ in range(33)),
        "x" * (MAX_SEARCH_LENGTH + 1),
    ],
)
def test_status_search_rejects_invalid_terms(search: str) -> None:
    with pytest.raises(ValueError):
        CardStatusQuery(search=search)


def test_schedule_badges_do_not_repeat_fsrs_state(
    web_context: tuple[object, object, object],
) -> None:
    _client, controller, repository = web_context
    deck = controller.config.deck("capitals")
    card = repository.active_cards("capitals")[0]
    controller.study_service.review(deck, card, Rating.Good, utc_now())
    now = utc_now()
    row = next(
        row for row in controller.card_statuses(deck, now) if row.status.card_key == card.card_key
    )
    view = status_row(row, now, controller.config.display_timezone)

    assert view.fsrs_label.startswith(row.status.fsrs_state.title())
    assert row.status.fsrs_state.title() not in view.badges


def test_status_suspend_and_resume_round_trip(web_context: tuple[object, object, object]) -> None:
    client, controller, repository = web_context
    entity_id = repository.active_cards("capitals")[0].card_key.entity_id
    suspend = client.post(
        "/decks/capitals/cards/suspend",
        data={"csrf_token": controller.csrf_token, "entity_id": entity_id, "reason": "later"},
        headers={"Host": "localhost"},
    )
    suspended_status = repository.card_statuses("capitals")[0]
    available_after_suspend = {
        item.card_key.entity_id for item in repository.active_cards("capitals")
    }
    suspended_page = client.get(
        "/decks/capitals/cards?tab=status",
        headers={"Host": "localhost"},
    )
    suspended_cells = _first_status_row_cells(suspended_page.data)
    resume = client.post(
        "/decks/capitals/cards/resume",
        data={"csrf_token": controller.csrf_token, "entity_id": entity_id},
        headers={"Host": "localhost"},
    )
    resumed_status = repository.card_statuses("capitals")[0]

    assert suspend.status_code == 303
    assert suspended_status.suspended is True
    assert suspended_status.suspension_reason == "later"
    assert b"later" not in suspended_page.data
    assert len(suspended_cells) == 6
    assert b"More details" in suspended_cells[0]
    assert b"Resume" in suspended_cells[5]
    assert entity_id not in available_after_suspend
    assert resume.status_code == 303
    assert resumed_status.suspended is False
    assert resumed_status.suspension_reason is None


def test_status_bulk_suspend_and_resume_is_atomic(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, repository = web_context
    entity_ids = [card.card_key.entity_id for card in repository.active_cards("capitals")[:2]]
    before = {
        item.card_key.entity_id: (item.card_json, item.due_at, item.review_count)
        for item in repository.card_statuses("capitals")
    }
    data = MultiDict(
        [
            ("csrf_token", controller.csrf_token),
            ("bulk_action", "suspend"),
            ("reason", "focus later"),
            *[
                (
                    "selected_card_key",
                    json.dumps(
                        {"deck_id": "capitals", "entity_id": entity_id},
                        separators=(",", ":"),
                    ),
                )
                for entity_id in entity_ids
            ],
        ]
    )

    suspend = client.post(
        "/decks/capitals/cards/bulk",
        data=data,
        headers={"Host": "localhost"},
    )

    assert suspend.status_code == 303
    assert all(repository.card_suspended("capitals", entity_id) for entity_id in entity_ids)

    resume = client.post(
        "/decks/capitals/cards/bulk",
        data=MultiDict(
            [
                ("csrf_token", controller.csrf_token),
                ("bulk_action", "resume"),
                *[
                    (
                        "selected_card_key",
                        json.dumps(
                            {"deck_id": "capitals", "entity_id": entity_id},
                            separators=(",", ":"),
                        ),
                    )
                    for entity_id in entity_ids
                ],
            ]
        ),
        headers={"Host": "localhost"},
    )

    assert resume.status_code == 303
    assert all(repository.card_available("capitals", entity_id) for entity_id in entity_ids)
    after = {
        item.card_key.entity_id: (item.card_json, item.due_at, item.review_count)
        for item in repository.card_statuses("capitals")
    }
    assert after == before


def test_status_bulk_rejects_duplicate_and_cross_deck_selections(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, repository = web_context
    entity_id = repository.active_cards("capitals")[0].card_key.entity_id
    selection = json.dumps(
        {"deck_id": "capitals", "entity_id": entity_id},
        separators=(",", ":"),
    )
    duplicate = client.post(
        "/decks/capitals/cards/bulk",
        data=MultiDict(
            [
                ("csrf_token", controller.csrf_token),
                ("bulk_action", "suspend"),
                ("selected_card_key", selection),
                ("selected_card_key", selection),
            ]
        ),
        headers={"Host": "localhost"},
    )
    cross_deck = client.post(
        "/decks/capitals/cards/bulk",
        data=MultiDict(
            [
                ("csrf_token", controller.csrf_token),
                ("bulk_action", "suspend"),
                (
                    "selected_card_key",
                    json.dumps(
                        {"deck_id": "other", "entity_id": entity_id},
                        separators=(",", ":"),
                    ),
                ),
            ]
        ),
        headers={"Host": "localhost"},
    )

    assert duplicate.status_code == 400
    assert cross_deck.status_code == 409
    assert repository.card_available("capitals", entity_id)


def test_status_rejects_malformed_filters_without_state_change(
    web_context: tuple[object, object, object],
) -> None:
    client, _controller, repository = web_context
    before = repository.status("capitals", utc_now())
    response = client.get("/decks/capitals/cards?state=%FF", headers={"Host": "localhost"})
    after = repository.status("capitals", utc_now())

    assert response.status_code == 400
    assert before == after


def test_deck_info_tabs_have_isolated_content_and_updated_controls(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, _repository = web_context
    deck = controller.config.deck("capitals")

    index = client.get("/", headers={"Host": "localhost"})
    status = client.get("/decks/capitals/cards?tab=status", headers={"Host": "localhost"})
    default_status = client.get("/decks/capitals/cards", headers={"Host": "localhost"})
    history = client.get(
        "/decks/capitals/cards?tab=history&range=30d",
        headers={"Host": "localhost"},
    )
    deck_status = client.get(
        "/decks/capitals/cards?tab=deck_status",
        headers={"Host": "localhost"},
    )
    generators = client.get(
        "/decks/capitals/cards?tab=generators",
        headers={"Host": "localhost"},
    )
    script = client.get("/static/status.js", headers={"Host": "localhost"})

    assert b"View Deck Info" in index.data
    assert b"View card status" not in index.data
    assert b'aria-current="page">Deck status' in default_status.data
    assert b"Study queues" in default_status.data
    assert b"Card Status" in status.data
    assert b'id="card-status"' in status.data
    assert b"Daily limits" not in status.data
    assert b'id="history"' not in status.data
    assert b"Reason for suspension" not in status.data
    assert b"Suspend selected" not in status.data
    assert b"Resume selected" not in status.data
    assert b"selected_card_key" not in status.data
    assert deck_status.status_code == 200
    assert b'aria-current="page">Deck status' in deck_status.data
    assert b'id="deck-status"' in deck_status.data
    assert b"Study queues" in deck_status.data
    assert b"Daily limits" in deck_status.data
    assert b'name="new_cards_per_day"' in deck_status.data
    assert b'name="reviews_per_day"' in deck_status.data
    assert deck_status.data.index(b">Deck status</a>") < deck_status.data.index(b">Card Status</a>")

    settings = client.post(
        "/decks/capitals/settings",
        data={
            "csrf_token": controller.csrf_token,
            "new_cards_per_day": "7",
            "reviews_per_day": "11",
        },
        headers={"Host": "localhost"},
    )
    assert settings.status_code == 303
    assert settings.location.endswith("/decks/capitals/cards?tab=deck_status")
    assert controller.study_service.daily_limits(deck).new_cards_per_day == 7
    assert controller.study_service.daily_limits(deck).reviews_per_day == 11

    updated_deck_status = client.get(
        "/decks/capitals/cards?tab=deck_status",
        headers={"Host": "localhost"},
    )
    assert b'value="7"' in updated_deck_status.data
    assert b'value="11"' in updated_deck_status.data
    assert b"Review History" in history.data
    assert b'id="history"' in history.data
    assert b'id="card-status"' not in history.data
    assert b"Apply" not in history.data
    assert b"data-submit-on-change" in history.data
    assert "script-src 'self'" in history.headers["Content-Security-Policy"]
    assert b"Last 30 days" in history.data
    assert b'value="30d" selected' in history.data
    assert b"Refresh range" in history.data
    assert script.status_code == 200
    assert b"requestSubmit" in script.data
    script.close()
    assert b"Exercise Generators" in generators.data
    assert b"basics" in generators.data
    assert b"choices" in generators.data
    assert b"order" in generators.data
    assert b'id="card-status"' not in generators.data

    history_page = client.get(
        "/decks/capitals/cards?tab=history&page=2",
        headers={"Host": "localhost"},
    )
    assert history_page.status_code == 200

    session_start = client.post(
        "/sessions",
        data={
            "csrf_token": controller.csrf_token,
            "deck_name": "capitals",
            "mode": "due",
            "days": "1",
            "limit": "1",
        },
        headers={"Host": "localhost"},
    )
    assert session_start.status_code == 303
    study = client.get("/study", headers={"Host": "localhost"})
    assert b"Reason" not in study.data


def test_exercise_previews_are_rendered_without_mutating_state(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, repository = web_context
    before_status = repository.card_statuses("capitals")
    before_history = repository.review_history("capitals", utc_now())
    rng_state = controller.rng.getstate()

    card_preview = client.get(
        "/decks/capitals/cards?tab=status&preview_entity=france",
        headers={"Host": "localhost"},
    )
    generator_preview = client.get(
        "/decks/capitals/cards?tab=generators&preview_generator=choices",
        headers={"Host": "localhost"},
    )

    assert card_preview.status_code == 200
    assert b"Exercise preview" in card_preview.data
    assert generator_preview.status_code == 200
    assert b"Exercise preview" in generator_preview.data
    assert b"choices" in generator_preview.data
    assert b'aria-current="page">Exercise Generators' in generator_preview.data
    assert (
        b'<div class="grid grid-cols-1 items-start gap-4 md:grid-cols-2">' in generator_preview.data
    )
    assert repository.card_statuses("capitals") == before_status
    assert repository.review_history("capitals", utc_now()) == before_history
    assert controller.rng.getstate() == rng_state


def test_exercise_previews_reject_unknown_references(
    web_context: tuple[object, object, object],
) -> None:
    client, _controller, repository = web_context
    before = repository.card_statuses("capitals")

    unknown_entity = client.get(
        "/decks/capitals/cards?tab=status&preview_entity=missing",
        headers={"Host": "localhost"},
    )
    unknown_generator = client.get(
        "/decks/capitals/cards?tab=generators&preview_generator=missing",
        headers={"Host": "localhost"},
    )

    assert unknown_entity.status_code == 404
    assert unknown_generator.status_code == 404
    assert repository.card_statuses("capitals") == before


def test_status_actions_validate_card_ownership_fields(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, repository = web_context
    before = repository.card_statuses("capitals")

    response = client.post(
        "/decks/capitals/cards/suspend",
        data={
            "csrf_token": controller.csrf_token,
            "entity_id": "not-the-card",
        },
        headers={"Host": "localhost"},
    )

    assert response.status_code == 404
    assert repository.card_statuses("capitals") == before


def test_targetless_generator_preview_is_a_controlled_error(
    web_context: tuple[object, object, object],
) -> None:
    _client, controller, _repository = web_context
    capitals = controller.config.deck("capitals")
    deck = Deck.from_document(
        DeckDocument(
            entities=(capitals.document.entities[0],),
            exercises=(BasicExerciseGenerator(id="empty", entities=()),),
        ),
        name="empty",
        path=capitals.path,
    )

    with pytest.raises(RequestFailure, match="no eligible targets"):
        controller.preview_generator(deck, "empty")


def test_status_table_is_minimal_and_links_to_entity_details(
    web_context: tuple[object, object, object],
) -> None:
    client, _controller, _repository = web_context

    response = client.get("/decks/capitals/cards?tab=status", headers={"Host": "localhost"})

    assert response.status_code == 200
    assert b"<th>Entity</th>" in response.data
    assert b"<th>Review history</th>" in response.data
    assert b"<th>Next review</th>" in response.data
    assert b"<th>Schedule</th>" in response.data
    assert b"<th>FSRS Status</th>" in response.data
    assert b"<th>Actions</th>" in response.data
    assert b'placeholder="id:earth OR (state:review AND NOT field:front=France)"' in response.data
    assert b"<label>Availability" not in response.data
    assert b"<label>Schedule" not in response.data
    assert b"<label>FSRS state" not in response.data
    assert b"<label>Sort by" in response.data
    assert b'<option value="entity_id">Entity ID</option>' in response.data
    assert b"<label>Direction" in response.data
    assert b">Search</button>" in response.data
    assert b">Clear</a>" in response.data
    assert b">Apply</button>" not in response.data
    assert (
        b"<thead><tr><th>Entity</th><th>Review history</th><th>Next review</th>"
        b"<th>Schedule</th><th>FSRS Status</th><th>Actions</th></tr></thead>" in response.data
    )
    cells = _first_status_row_cells(response.data)
    assert len(cells) == 6
    assert b"More details" in cells[0]
    assert b"status-actions" not in cells[0]
    assert b"Due" in cells[3] or b"Future" in cells[3]
    assert b"New" in cells[3] or b"Review" in cells[4]
    assert b"Suspend" in cells[5]
    assert b"<th>Exercise generators</th>" not in response.data
    assert b"Generate exercise" not in response.data
    assert b"More details" in response.data
    assert b'aria-label="More details for france"' in response.data
    assert b"/decks/capitals/cards/detail/france" in response.data


def test_card_detail_preserves_status_filters_and_invalid_action_paths_stay_405(
    web_context: tuple[object, object, object],
) -> None:
    client, _controller, _repository = web_context
    query = "page=1&sort=review_count&direction=desc&range=30d"

    status = client.get(
        f"/decks/capitals/cards?{query}&tab=status",
        headers={"Host": "localhost"},
    )
    detail = client.get(
        f"/decks/capitals/cards/detail/france?{query}",
        headers={"Host": "localhost"},
    )
    preview = client.get(
        "/decks/capitals/cards/detail/france",
        query_string={
            "page": "1",
            "availability": "all",
            "schedule": "all",
            "state": "all",
            "sort": "review_count",
            "direction": "desc",
            "range": "30d",
            "tab": "generators",
            "preview_generator": "basics",
        },
        headers={"Host": "localhost"},
    )
    suspend = client.get("/decks/capitals/cards/suspend", headers={"Host": "localhost"})
    resume = client.get("/decks/capitals/cards/resume", headers={"Host": "localhost"})

    expected_detail_query = (
        b"page=1&amp;availability=all&amp;schedule=all&amp;state=all&amp;sort=review_count&amp;"
        b"direction=desc&amp;range=30d&amp;tab=generators"
    )
    expected_status_query = expected_detail_query.replace(b"tab=generators", b"tab=status")
    assert status.status_code == 200
    assert (
        b'href="/decks/capitals/cards/detail/france?' + expected_detail_query + b'"' in status.data
    )
    assert detail.status_code == 200
    assert b'href="/decks/capitals/cards?' + expected_status_query + b'"' in detail.data
    assert b'name="sort" value="review_count"' in detail.data
    assert b'name="direction" value="desc"' in detail.data
    assert b'name="range" value="30d"' in detail.data
    detail_forms = re.findall(
        rb"<form[^>]*>(.*?)</form>",
        detail.data,
        re.DOTALL,
    )
    assert any(
        all(
            field in form
            for field in (
                b'name="page" value="1"',
                b'name="sort" value="review_count"',
                b'name="direction" value="desc"',
                b'name="range" value="30d"',
                b'name="tab" value="generators"',
                b'name="preview_generator" value="basics"',
            )
        )
        for form in detail_forms
    )
    assert preview.status_code == 200
    assert b'id="exercise-preview-title"' in preview.data
    assert b'href="/decks/capitals/cards?' + expected_status_query + b'"' in preview.data
    assert suspend.status_code == 405
    assert resume.status_code == 405


def test_card_detail_shows_state_and_card_review_history_tabs(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, repository = web_context
    deck = controller.config.deck("capitals")
    france = next(
        card for card in repository.active_cards("capitals") if card.card_key.entity_id == "france"
    )
    controller.study_service.review(deck, france, Rating.Good, utc_now())

    history = client.get(
        "/decks/capitals/cards/detail/france?tab=history",
        headers={"Host": "localhost"},
    )
    generators = client.get(
        "/decks/capitals/cards/detail/france?tab=generators",
        headers={"Host": "localhost"},
    )
    invalid_preview = client.get(
        "/decks/capitals/cards/detail/france?tab=history&preview_generator=basics",
        headers={"Host": "localhost"},
    )

    assert history.status_code == 200
    assert b'id="card-state-title">Card state' in history.data
    assert b"Availability" in history.data
    assert b"Available" in history.data
    assert b"FSRS state" in history.data
    assert b"Reviews" in history.data
    assert b'aria-current="page">Review History' in history.data
    assert b'id="review-history"' in history.data
    assert b"All reviews for this card." in history.data
    assert b"Good" in history.data
    assert b"Generate exercise" not in history.data

    assert generators.status_code == 200
    assert b'aria-current="page">Exercise Generators' in generators.data
    assert b"Generate exercise" in generators.data
    assert b"Review History" in generators.data
    assert b"md:grid-cols-2" in generators.data
    assert invalid_preview.status_code == 400

    status = client.get("/decks/capitals/cards?tab=status", headers={"Host": "localhost"})
    assert b'<a class="underline" aria-label="More details for france"' in status.data


def test_shared_preview_panels_keep_generator_sections_unchanged(
    web_context: tuple[object, object, object],
) -> None:
    client, _controller, repository = web_context
    before = repository.card_statuses("capitals")
    before_history = repository.review_history("capitals", utc_now())

    generators = client.get(
        "/decks/capitals/cards?tab=generators&preview_generator=choices",
        headers={"Host": "localhost"},
    )
    generators_without_preview = client.get(
        "/decks/capitals/cards?tab=generators",
        headers={"Host": "localhost"},
    )
    details = client.get(
        "/decks/capitals/cards/detail/france?preview_generator=basics",
        headers={"Host": "localhost"},
    )
    details_without_preview = client.get(
        "/decks/capitals/cards/detail/france",
        headers={"Host": "localhost"},
    )

    assert generators.status_code == 200
    assert b"generator-card" in generators.data
    assert generators.data.count(b'class="exercise-preview exercise-preview-panel"') == 1
    assert b'id="exercise-preview-title"' in generators.data
    assert b"inline-preview" not in generators.data
    generator_panel = _preview_panel(generators.data)
    assert b'<div class="prompt">' in generator_panel
    assert b'<div class="answer"' in generator_panel
    assert generators.data.index(b'<div class="generator-list">') < generators.data.index(
        b'<aside class="exercise-preview exercise-preview-panel"'
    )
    assert _generator_cards(generators.data) == _generator_cards(generators_without_preview.data)
    assert details.status_code == 200
    assert b"Card details" in details.data
    assert b"basics" in details.data
    assert b"order" in details.data
    assert details.data.count(b'class="exercise-preview exercise-preview-panel"') == 1
    assert b'id="exercise-preview-title"' in details.data
    assert b"inline-preview" not in details.data
    detail_panel = _preview_panel(details.data)
    assert b'<div class="prompt">' in detail_panel
    assert b'<div class="answer"' in detail_panel
    assert details.data.index(b'<div class="generator-list">') < details.data.index(
        b'<aside class="exercise-preview exercise-preview-panel"'
    )
    assert _generator_cards(details.data) == _generator_cards(details_without_preview.data)
    assert b"Generate exercise" in details.data
    assert repository.card_statuses("capitals") == before
    assert repository.review_history("capitals", utc_now()) == before_history


def test_card_detail_validates_entity_and_generator_ownership(
    web_context: tuple[object, object, object],
) -> None:
    client, _controller, repository = web_context
    before = repository.card_statuses("capitals")

    unknown_entity = client.get(
        "/decks/capitals/cards/detail/missing",
        headers={"Host": "localhost"},
    )
    unknown_generator = client.get(
        "/decks/capitals/cards/detail/france?preview_generator=choices",
        headers={"Host": "localhost"},
    )

    assert unknown_entity.status_code == 404
    assert unknown_generator.status_code == 404
    assert repository.card_statuses("capitals") == before


def test_detail_namespace_allows_action_named_entity_ids(
    web_context: tuple[object, object, object],
) -> None:
    _client, controller, repository = web_context
    capitals = controller.config.deck("capitals")
    reserved = Deck.from_document(
        DeckDocument(
            entities=(Entity(id="suspend"), Entity(id="resume")),
            exercises=(BasicExerciseGenerator(id="basics", entities=("suspend", "resume")),),
        ),
        name="reserved",
        path=capitals.path,
    )
    config = controller.config.model_copy(update={"decks": (reserved,)})
    reserved_controller = type(controller)(config, repository, random.Random(0))
    app = create_flask_app(reserved_controller)
    app.config[EXPECTED_HOST_CONFIG] = "localhost"
    client = app.test_client()

    suspend = client.get(
        "/decks/reserved/cards/detail/suspend",
        headers={"Host": "localhost"},
    )
    resume = client.get(
        "/decks/reserved/cards/detail/resume",
        headers={"Host": "localhost"},
    )

    assert suspend.status_code == 200
    assert b">suspend<" in suspend.data
    assert resume.status_code == 200
    assert b">resume<" in resume.data
