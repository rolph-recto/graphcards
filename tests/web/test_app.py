from __future__ import annotations


def test_flask_rejects_wrong_hosts_and_sets_security_headers(
    web_context: tuple[object, object, object],
) -> None:
    client, _controller, _repository = web_context
    wrong_host = client.get("/", headers={"Host": "evil.example"})
    response = client.get("/", headers={"Host": "localhost"})

    assert wrong_host.status_code == 400
    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")


def test_malformed_study_form_is_a_controlled_client_error(
    web_context: tuple[object, object, object],
) -> None:
    client, controller, _repository = web_context
    response = client.post(
        "/sessions",
        data={"deck_name": "capitals"},
        headers={"Host": "localhost"},
    )

    assert response.status_code == 400
    assert controller.session is None
