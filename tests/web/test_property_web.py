from __future__ import annotations

import pytest

from graphcards.storage import Repository, utc_now
from graphcards.web.study import StudyMode


def _start_session(client: object, controller: object) -> object:
    response = client.post(
        "/sessions",
        data={
            "csrf_token": controller.csrf_token,
            "deck_name": "capitals",
            "mode": StudyMode.DUE.value,
            "days": "1",
            "limit": "1",
        },
        headers={"Host": "localhost"},
    )
    assert response.status_code == 303
    assert controller.session is not None
    return controller.session


def test_malformed_status_filters_do_not_mutate_state(
    web_context: tuple[object, object, Repository],
) -> None:
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


def test_status_actions_reject_invalid_csrf_without_mutation(
    web_context: tuple[object, object, Repository],
) -> None:
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
