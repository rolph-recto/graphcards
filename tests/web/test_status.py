from __future__ import annotations

from fsrs import Rating

from graphcards.storage import utc_now


def test_status_page_lists_cards_and_filters(web_context: tuple[object, object, object]) -> None:
    client, controller, repository = web_context
    deck = controller.config.deck("capitals")
    reviewed = repository.active_cards("capitals")[0]
    controller.study_service.review(deck, reviewed, Rating.Good, utc_now())
    response = client.get("/decks/capitals/cards?schedule=new", headers={"Host": "localhost"})
    all_cards = client.get("/decks/capitals/cards?schedule=all", headers={"Host": "localhost"})

    assert response.status_code == 200
    assert b"Card status" in response.data
    assert reviewed.card_id.encode() not in response.data
    assert reviewed.card_id.encode() in all_cards.data


def test_status_suspend_and_resume_round_trip(web_context: tuple[object, object, object]) -> None:
    client, controller, repository = web_context
    card_id = repository.active_cards("capitals")[0].card_id
    suspend = client.post(
        "/decks/capitals/cards/suspend",
        data={"csrf_token": controller.csrf_token, "card_id": card_id, "reason": "later"},
        headers={"Host": "localhost"},
    )
    suspended_status = repository.card_statuses("capitals")[0]
    available_after_suspend = {item.card_id for item in repository.active_cards("capitals")}
    resume = client.post(
        "/decks/capitals/cards/resume",
        data={"csrf_token": controller.csrf_token, "card_id": card_id},
        headers={"Host": "localhost"},
    )
    resumed_status = repository.card_statuses("capitals")[0]

    assert suspend.status_code == 303
    assert suspended_status.suspended is True
    assert suspended_status.suspension_reason == "later"
    assert card_id not in available_after_suspend
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
