"""Flask application factory, routes, validation, and error handling."""

from __future__ import annotations

import math
import sqlite3
from http import HTTPStatus
from typing import cast
from urllib.parse import parse_qs, urlencode

from flask import Flask, Response, current_app, redirect, render_template, request, url_for
from fsrs import Rating
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from werkzeug.exceptions import HTTPException, InternalServerError

from rdfcards.errors import ConfigError, RdfCardsError
from rdfcards.storage import utc_now
from rdfcards.web.controller import StudyController
from rdfcards.web.status import (
    CARD_PAGE_SIZE,
    DIRECTION_OPTIONS,
    SCHEDULE_OPTIONS,
    SORT_OPTIONS,
    STATE_OPTIONS,
    CardStatusQuery,
    pagination,
    schedule_matches,
    sort_status_cards,
    status_row,
)
from rdfcards.web.study import RequestFailure, StudyMode, StudySession, completion_summary

MAX_FORM_BYTES = 4096
CONTROLLER_EXTENSION = "rdfcards_controller"
EXPECTED_HOST_CONFIG = "RDFCARDS_EXPECTED_HOST"
_MAX_FIELDS = 32
_ASCII_HEX_DIGITS = frozenset(b"0123456789abcdefABCDEF")


class _SessionStartSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csrf_token: str = Field(min_length=1, max_length=256)
    deck_name: str = Field(min_length=1)
    mode: StudyMode
    days: int = Field(default=1, ge=1, le=365)
    limit: int = Field(default=20, ge=0)


class _RevealSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_token: str = Field(min_length=1, max_length=256)
    card_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class _RatingSubmission(_RevealSubmission):
    rating: int = Field(ge=1, le=4)


def _controller() -> StudyController:
    return cast(StudyController, current_app.extensions[CONTROLLER_EXTENSION])


def _session() -> StudySession:
    session = _controller().session
    if session is None:
        raise RequestFailure(HTTPStatus.CONFLICT, "No study session is active.")
    return session


def _parse_urlencoded(encoded: bytes, failure_message: str) -> dict[str, object]:
    try:
        for index, value in enumerate(encoded):
            if value == ord("%") and (
                index + 2 >= len(encoded)
                or encoded[index + 1] not in _ASCII_HEX_DIGITS
                or encoded[index + 2] not in _ASCII_HEX_DIGITS
            ):
                raise ValueError("invalid percent escape")
        parsed = parse_qs(
            encoded.decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=_MAX_FIELDS,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise RequestFailure(HTTPStatus.BAD_REQUEST, failure_message) from error
    return {name: values[0] if len(values) == 1 else values for name, values in parsed.items()}


def _form_data() -> dict[str, object]:
    if request.mimetype.casefold() != "application/x-www-form-urlencoded":
        raise RequestFailure(
            HTTPStatus.BAD_REQUEST,
            "Study forms must use URL-encoded data.",
        )
    content_length = request.content_length
    if content_length is None or content_length < 0:
        raise RequestFailure(HTTPStatus.BAD_REQUEST, "The form length is invalid.")
    if content_length > MAX_FORM_BYTES:
        raise RequestFailure(HTTPStatus.BAD_REQUEST, "The study form is too large.")
    return _parse_urlencoded(request.get_data(cache=False), "The study form is malformed.")


def _query_data() -> dict[str, object]:
    return _parse_urlencoded(
        request.query_string,
        "The card-status filters are malformed.",
    )


def _validated_form[SubmissionModel: BaseModel](
    model: type[SubmissionModel],
    failure_message: str,
) -> SubmissionModel:
    try:
        return model.model_validate(_form_data())
    except ValidationError as error:
        raise RequestFailure(HTTPStatus.BAD_REQUEST, failure_message) from error


def _render_error(status: HTTPStatus, message: str) -> tuple[str, int]:
    return render_template("error.html", status=status, message=message), status.value


def _status_url(deck_name: str, query: CardStatusQuery, page: int) -> str:
    values = query.model_dump(mode="json")
    values["page"] = page
    return f"{url_for('card_status', deck_name=deck_name)}?{urlencode(values)}"


def create_flask_app(controller: StudyController) -> Flask:
    """Create one Flask application around a synchronized study controller."""

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )
    app.config["MAX_CONTENT_LENGTH"] = MAX_FORM_BYTES
    app.config[EXPECTED_HOST_CONFIG] = None
    app.extensions[CONTROLLER_EXTENSION] = controller

    @app.before_request
    def require_expected_host() -> None:
        expected_host = current_app.config[EXPECTED_HOST_CONFIG]
        if not isinstance(expected_host, str) or request.host != expected_host:
            raise RequestFailure(HTTPStatus.BAD_REQUEST, "The request host is not valid.")

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.errorhandler(RequestFailure)
    def handle_request_failure(error: RequestFailure) -> tuple[str, int]:
        return _render_error(error.status, error.message)

    @app.errorhandler(HTTPException)
    def handle_http_failure(error: HTTPException) -> tuple[str, int]:
        status = HTTPStatus(error.code or HTTPStatus.INTERNAL_SERVER_ERROR)
        message = {
            HTTPStatus.NOT_FOUND: "That page does not exist.",
            HTTPStatus.METHOD_NOT_ALLOWED: "That request method is not allowed.",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "The study form is too large.",
        }.get(status, error.description)
        return _render_error(status, message)

    def handle_application_failure(error: RdfCardsError) -> tuple[str, int]:
        return _render_error(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            f"Could not complete this request: {error}",
        )

    app.register_error_handler(RdfCardsError, handle_application_failure)

    def handle_dependency_failure(_error: Exception) -> tuple[str, int]:
        return _render_error(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "Could not complete this request.",
        )

    for error_type in (OSError, sqlite3.Error):
        app.register_error_handler(error_type, handle_dependency_failure)

    @app.errorhandler(InternalServerError)
    def handle_internal_failure(_error: InternalServerError) -> tuple[str, int]:
        return _render_error(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "An unexpected error occurred.",
        )

    @app.get("/")
    def index() -> str:
        current = _controller()
        advanced_modes = (
            (
                StudyMode.FORGOTTEN,
                "Revisit cards rated Again in a recent time window.",
            ),
            (
                StudyMode.PRACTICE,
                "Shuffle through active cards without changing their schedules.",
            ),
            (
                StudyMode.AHEAD,
                "Review cards scheduled within an upcoming time window.",
            ),
        )
        return render_template(
            "index.html",
            controller=current,
            decks=current.deck_statuses(),
            advanced_modes=advanced_modes,
        )

    @app.post("/sessions")
    def start_session() -> Response:
        submission = _validated_form(
            _SessionStartSubmission,
            "The session form is invalid.",
        )
        _controller().start_session(
            csrf_token=submission.csrf_token,
            deck_name=submission.deck_name,
            mode=submission.mode,
            days=submission.days,
            requested_limit=submission.limit,
        )
        return redirect(url_for("study"), code=HTTPStatus.SEE_OTHER)

    @app.get("/study")
    def study() -> str:
        current = _session()
        completion_title = completion_text = None
        if current.complete:
            completion_title, completion_text = completion_summary(current)
        progress = min(current.index + (0 if current.complete else 1), len(current.cards))
        return render_template(
            "study.html",
            session=current,
            current=current.current,
            progress=progress,
            maximum=max(len(current.cards), 1),
            completion_title=completion_title,
            completion_summary=completion_text,
        )

    @app.post("/study/reveal")
    def reveal() -> Response:
        submission = _validated_form(
            _RevealSubmission,
            "The study form is invalid.",
        )
        _session().reveal(submission.session_token, submission.card_id)
        return redirect(url_for("study"), code=HTTPStatus.SEE_OTHER)

    @app.post("/study/rate")
    def rate() -> Response:
        submission = _validated_form(
            _RatingSubmission,
            "The rating form is invalid.",
        )
        _session().rate(
            submission.session_token,
            submission.card_id,
            Rating(submission.rating),
        )
        return redirect(url_for("study"), code=HTTPStatus.SEE_OTHER)

    @app.post("/study/next")
    def next_practice() -> Response:
        submission = _validated_form(
            _RevealSubmission,
            "The study form is invalid.",
        )
        _session().next_practice(submission.session_token, submission.card_id)
        return redirect(url_for("study"), code=HTTPStatus.SEE_OTHER)

    @app.get("/decks/<path:deck_name>/cards")
    def card_status(deck_name: str) -> str:
        current = _controller()
        try:
            deck = current.config.deck(deck_name)
        except ConfigError as error:
            raise RequestFailure(HTTPStatus.NOT_FOUND, "That deck does not exist.") from error
        try:
            query = CardStatusQuery.model_validate(_query_data())
        except ValidationError as error:
            raise RequestFailure(
                HTTPStatus.BAD_REQUEST,
                "The card-status filters are invalid.",
            ) from error

        now = utc_now()
        all_cards = current.card_statuses(deck, now)
        filtered = [row for row in all_cards if schedule_matches(row, query, now)]
        ordered = sort_status_cards(filtered, query)
        total = len(ordered)
        pages = max(1, math.ceil(total / CARD_PAGE_SIZE))
        if query.page > pages:
            raise RequestFailure(
                HTTPStatus.NOT_FOUND,
                "That card-status page does not exist.",
            )
        start = (query.page - 1) * CARD_PAGE_SIZE
        page_cards = tuple(ordered[start : start + CARD_PAGE_SIZE])
        fronts = current.card_fronts(deck, page_cards) if page_cards else {}
        rows = tuple(status_row(row, fronts.get(row.status.card_id), now) for row in page_cards)
        empty_message = None
        if not rows:
            empty_message = (
                "This deck has no active cards."
                if not all_cards
                else "No cards match these filters."
            )
        return render_template(
            "card_status.html",
            deck=deck,
            query=query,
            rows=rows,
            active_count=len(all_cards),
            empty_message=empty_message,
            pagination=(
                pagination(
                    query,
                    total,
                    pages,
                    lambda page: _status_url(deck.name, query, page),
                )
                if rows
                else None
            ),
            schedule_options=SCHEDULE_OPTIONS,
            state_options=STATE_OPTIONS,
            sort_options=SORT_OPTIONS,
            direction_options=DIRECTION_OPTIONS,
        )

    return app
