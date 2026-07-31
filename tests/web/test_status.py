from __future__ import annotations

import random
import re

import pytest
from fsrs import Rating

from graphcards.decks import BasicExerciseGenerator, Deck, DeckDocument, Entity
from graphcards.storage import utc_now
from graphcards.web.app import EXPECTED_HOST_CONFIG, create_flask_app
from graphcards.web.status import status_row
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
    response = client.get("/decks/capitals/cards?schedule=new", headers={"Host": "localhost"})
    all_cards = client.get("/decks/capitals/cards?schedule=all", headers={"Host": "localhost"})

    assert response.status_code == 200
    assert b"Card status" in response.data
    assert b'entity_id="france"' not in response.data
    assert b"france" in all_cards.data


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
    suspended_page = client.get("/decks/capitals/cards", headers={"Host": "localhost"})
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

    index = client.get("/", headers={"Host": "localhost"})
    status = client.get("/decks/capitals/cards", headers={"Host": "localhost"})
    history = client.get(
        "/decks/capitals/cards?tab=history&range=30d",
        headers={"Host": "localhost"},
    )
    generators = client.get(
        "/decks/capitals/cards?tab=generators",
        headers={"Host": "localhost"},
    )
    script = client.get("/static/status.js", headers={"Host": "localhost"})

    assert b"View Deck Info" in index.data
    assert b"View card status" not in index.data
    assert b"Card Status" in status.data
    assert b'id="card-status"' in status.data
    assert b'id="history"' not in status.data
    assert b"Reason" not in status.data
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

    response = client.get("/decks/capitals/cards", headers={"Host": "localhost"})

    assert response.status_code == 200
    assert b"<th>Entity</th>" in response.data
    assert b"<th>Review history</th>" in response.data
    assert b"<th>Next review</th>" in response.data
    assert b"<th>Schedule</th>" in response.data
    assert b"<th>FSRS Status</th>" in response.data
    assert b"<th>Actions</th>" in response.data
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
        f"/decks/capitals/cards?{query}",
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
            "tab": "status",
            "preview_generator": "basics",
        },
        headers={"Host": "localhost"},
    )
    suspend = client.get("/decks/capitals/cards/suspend", headers={"Host": "localhost"})
    resume = client.get("/decks/capitals/cards/resume", headers={"Host": "localhost"})

    expected_query = (
        b"page=1&amp;availability=all&amp;schedule=all&amp;state=all&amp;sort=review_count&amp;"
        b"direction=desc&amp;range=30d&amp;tab=status"
    )
    assert status.status_code == 200
    assert b'href="/decks/capitals/cards/detail/france?' + expected_query + b'"' in status.data
    assert detail.status_code == 200
    assert b'href="/decks/capitals/cards?' + expected_query + b'"' in detail.data
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
                b'name="tab" value="status"',
                b'name="preview_generator" value="basics"',
            )
        )
        for form in detail_forms
    )
    assert preview.status_code == 200
    assert b'id="exercise-preview-title"' in preview.data
    assert b'href="/decks/capitals/cards?' + expected_query + b'"' in preview.data
    assert suspend.status_code == 405
    assert resume.status_code == 405


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
