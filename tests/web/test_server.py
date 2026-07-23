from __future__ import annotations

import io
import random
import sqlite3

import pytest

import rdfcards.web.server as web_server_module
from rdfcards.config import AppConfig
from rdfcards.web import create_flask_app, create_web_server, run_server


def test_package_exports_public_web_entry_points() -> None:
    assert callable(create_flask_app)
    assert callable(create_web_server)
    assert callable(run_server)


def test_werkzeug_server_binds_ephemeral_loopback_and_closes_repository_once(
    config: AppConfig,
) -> None:
    server = create_web_server(config, random.Random(0))
    repository = server.repository

    assert server.server_address[0] == "127.0.0.1"
    assert server.server_address[1] > 0
    assert server.url == f"http://{server.expected_host}/"
    assert server.flask_app.config["RDFCARDS_EXPECTED_HOST"] == server.expected_host

    server.server_close()
    server.server_close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        repository.connection.execute("SELECT 1")


def test_werkzeug_server_preserves_keyboard_interrupt(
    config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = create_web_server(config, random.Random(0))

    def interrupt(_server: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(web_server_module.BaseServer, "serve_forever", interrupt)
    try:
        with pytest.raises(KeyboardInterrupt):
            server.serve_forever()
    finally:
        server.server_close()


def test_browser_open_failure_leaves_url_visible_and_closes_server(
    config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeServer:
        url = "http://127.0.0.1:12345/"
        served = False
        closed = False

        def serve_forever(self) -> None:
            self.served = True
            raise KeyboardInterrupt

        def server_close(self) -> None:
            self.closed = True

    server = FakeServer()
    monkeypatch.setattr(web_server_module, "create_web_server", lambda *_args: server)
    output = io.StringIO()
    error = io.StringIO()

    with pytest.raises(KeyboardInterrupt):
        run_server(
            config,
            output=output,
            error=error,
            rng=random.Random(0),
            open_browser=lambda _url: False,
        )

    assert server.served
    assert server.closed
    assert server.url in output.getvalue()
    assert server.url in error.getvalue()
