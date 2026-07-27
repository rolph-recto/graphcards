from __future__ import annotations

from graphcards.web.study import StudyMode


def test_web_uses_the_same_json_deck_and_presentation_as_cli(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, repository = web_context
    index = client.get("/", headers={"Host": "localhost"})
    assert index.status_code == 200
    assert b"Capital study" in index.data
    assert b"RDFCARDS" not in index.data

    response = client.post(
        "/sessions",
        data={
            "csrf_token": controller.csrf_token,
            "deck_name": "capitals",
            "mode": StudyMode.PRACTICE.value,
            "days": "1",
            "limit": "1",
        },
        headers={"Host": "localhost"},
    )
    assert response.status_code == 303
    study = client.get("/study", headers={"Host": "localhost"})
    assert study.status_code == 200
    assert b"Capital study" in study.data
    current = controller.session.current
    assert current is not None
    assert current.front.encode() in study.data
    reveal = client.post(
        "/study/reveal",
        data={
            "session_token": controller.session.session_token,
            "card_id": current.card.card_id,
        },
        headers={"Host": "localhost"},
    )
    assert reveal.status_code == 303
    revealed = client.get("/study", headers={"Host": "localhost"})
    assert current.back.encode() in revealed.data

    status = client.get("/decks/capitals/cards", headers={"Host": "localhost"})
    assert status.status_code == 200
    card_id = repository.active_cards("capitals")[0].card_id
    suspended = client.post(
        "/decks/capitals/cards/suspend",
        data={"csrf_token": controller.csrf_token, "card_id": card_id},
        headers={"Host": "localhost"},
    )
    assert suspended.status_code == 303
    resumed = client.post(
        "/decks/capitals/cards/resume",
        data={"csrf_token": controller.csrf_token, "card_id": card_id},
        headers={"Host": "localhost"},
    )
    assert resumed.status_code == 303
