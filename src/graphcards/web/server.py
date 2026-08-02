"""Loopback Werkzeug server and CLI lifecycle."""

from __future__ import annotations

import random
import webbrowser
from collections.abc import Callable
from socketserver import BaseServer
from typing import TextIO

from flask import Flask
from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server

from graphcards.config import AppConfig
from graphcards.storage import DeckFileStateStore
from graphcards.web.app import EXPECTED_HOST_CONFIG, create_flask_app
from graphcards.web.controller import StudyController


class _QuietRequestHandler(WSGIRequestHandler):
    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        del code, size


class LocalStudyServer:
    """Single-threaded Werkzeug server carrying the file-backed study store."""

    def __init__(self, flask_app: Flask, controller: StudyController) -> None:
        self.flask_app = flask_app
        self.app = controller
        self.store = controller.store
        self._closed = False
        self._server: BaseWSGIServer = make_server(
            "127.0.0.1",
            0,
            flask_app,
            threaded=False,
            request_handler=_QuietRequestHandler,
        )
        flask_app.config[EXPECTED_HOST_CONFIG] = self.expected_host

    @property
    def server_address(self) -> tuple[str, int]:
        host, port = self._server.server_address
        return str(host), int(port)

    @property
    def expected_host(self) -> str:
        host, port = self.server_address
        return f"{host}:{port}"

    @property
    def url(self) -> str:
        return f"http://{self.expected_host}/"

    @property
    def timeout(self) -> float | None:
        return self._server.timeout

    @timeout.setter
    def timeout(self, value: float | None) -> None:
        self._server.timeout = value

    def handle_request(self) -> None:
        self._server.handle_request()

    def serve_forever(self) -> None:
        # Werkzeug catches KeyboardInterrupt in its override. Calling the standard
        # implementation lets the CLI preserve its Ctrl-C exit behavior.
        BaseServer.serve_forever(self._server)

    def server_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._server.server_close()
        finally:
            self.store.close()


def create_web_server(
    config: AppConfig,
    rng: random.Random | None = None,
) -> LocalStudyServer:
    """Synchronize all decks and bind the Flask deck hub."""

    state_store = DeckFileStateStore(config.decks)
    try:
        controller = StudyController(config, state_store, rng or random.Random())
        flask_app = create_flask_app(controller)
        return LocalStudyServer(flask_app, controller)
    except Exception:
        state_store.close()
        raise


def run_server(
    config: AppConfig,
    *,
    output: TextIO,
    error: TextIO,
    rng: random.Random,
    open_browser: Callable[[str], bool] | None = None,
) -> None:
    """Run the local Flask deck hub until the user interrupts it."""

    server = create_web_server(config, rng)
    try:
        print(f"Serving GraphCards at {server.url}", file=output, flush=True)
        print("Press Ctrl-C to stop the web server.", file=output, flush=True)
        opener = open_browser or webbrowser.open
        try:
            opened = opener(server.url)
        except OSError, webbrowser.Error:
            opened = False
        if not opened:
            print(
                f"Could not open a browser automatically; open {server.url}",
                file=error,
                flush=True,
            )
        server.serve_forever()
    finally:
        server.server_close()
