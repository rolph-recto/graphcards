"""Flask application factory, routes, validation, and error handling."""

from __future__ import annotations

import json
import math
from http import HTTPStatus
from pathlib import Path
from typing import Literal, cast
from urllib.parse import parse_qs, urlencode

from flask import (
    Flask,
    Response,
    current_app,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from fsrs import Rating
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from werkzeug.exceptions import HTTPException, InternalServerError

from graphcards.errors import ConfigError, GraphCardsError, StateConflictError
from graphcards.models import CardKey
from graphcards.references import EntityId
from graphcards.scheduling import (
    MAX_DAILY_LIMIT,
    DailyLimits,
    DeckSchedulingSettings,
    InterdayLearningReviewOrder,
    NewCardGatherOrder,
    NewCardSortOrder,
    NewReviewOrder,
    ReviewSortOrder,
)
from graphcards.storage import normalize_suspension_reason, utc_now
from graphcards.web.controller import StudyController
from graphcards.web.status import (
    AVAILABILITY_OPTIONS,
    CARD_PAGE_SIZE,
    DIRECTION_OPTIONS,
    HISTORY_RANGE_OPTIONS,
    QUEUE_GATHER_OPTIONS,
    QUEUE_INTERDAY_OPTIONS,
    QUEUE_NEW_REVIEW_OPTIONS,
    QUEUE_NEW_SORT_OPTIONS,
    QUEUE_REVIEW_SORT_OPTIONS,
    SCHEDULE_OPTIONS,
    SORT_OPTIONS,
    STATE_OPTIONS,
    AvailabilityFilter,
    CardDetailQuery,
    CardDetailTab,
    CardSort,
    CardStatusQuery,
    FsrsStateFilter,
    HistoryRange,
    InfoTab,
    ScheduleFilter,
    SortDirection,
    normalize_search_text,
    pagination,
    schedule_matches,
    search_matches,
    sort_status_cards,
    status_row,
)
from graphcards.web.study import RequestFailure, StudyMode, StudySession, completion_summary

# A valid 500-character reason can occupy 6,000 bytes once UTF-8 is percent-encoded.
MAX_FORM_BYTES = 8192
MAX_SESSION_LIMIT = 1000
CONTROLLER_EXTENSION = "graphcards_controller"
EXPECTED_HOST_CONFIG = "GRAPHCARDS_EXPECTED_HOST"
_MAX_FIELDS = 32
_ASCII_HEX_DIGITS = frozenset(b"0123456789abcdefABCDEF")
_IMAGE_MEDIA_TYPES = {
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_STUDY_ENDPOINTS = frozenset(
    {
        "study",
        "reveal",
        "rate",
        "next_practice",
        "suspend_study_card",
        "deck_asset",
        "static",
    }
)


class _SessionStartSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csrf_token: str = Field(min_length=1, max_length=256)
    deck_name: str = Field(min_length=1)
    mode: StudyMode
    days: int = Field(default=1, ge=1, le=365)
    limit: int = Field(default=20, ge=0, le=MAX_SESSION_LIMIT)


class _RevealSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_token: str = Field(min_length=1, max_length=256)
    entity_id: EntityId


class _RatingSubmission(_RevealSubmission):
    rating: int = Field(ge=1, le=4)


class _StudySuspensionSubmission(_RevealSubmission):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return normalize_suspension_reason(value)


class _StatusActionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csrf_token: str = Field(min_length=1, max_length=256)
    entity_id: EntityId | None = None
    generator_id: str | None = Field(default=None, min_length=1, max_length=512)
    page: int = Field(default=1, ge=1)
    search: str = Field(default="", max_length=512)
    availability: AvailabilityFilter = AvailabilityFilter.ALL
    schedule: ScheduleFilter = ScheduleFilter.ALL
    state: FsrsStateFilter = FsrsStateFilter.ALL
    sort: CardSort = CardSort.NEXT_REVIEW
    direction: SortDirection = SortDirection.ASCENDING
    range: HistoryRange = HistoryRange.NINETY_DAYS

    @field_validator("search")
    @classmethod
    def validate_search(cls, value: str) -> str:
        return normalize_search_text(value)

    @model_validator(mode="after")
    def require_card_reference(self) -> _StatusActionSubmission:
        if self.entity_id is None:
            raise ValueError("a card reference is required")
        return self

    def status_query(self) -> CardStatusQuery:
        return CardStatusQuery(
            page=self.page,
            search=self.search,
            availability=self.availability,
            schedule=self.schedule,
            state=self.state,
            sort=self.sort,
            direction=self.direction,
            range=self.range,
            tab=InfoTab.STATUS,
        )


class _DeckSettingsSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csrf_token: str = Field(min_length=1, max_length=256)
    new_review_order: NewReviewOrder | None = None
    interday_learning_review_order: InterdayLearningReviewOrder | None = None
    new_card_gather_order: NewCardGatherOrder | None = None
    new_card_sort_order: NewCardSortOrder | None = None
    review_sort_order: ReviewSortOrder | None = None
    new_cards_per_day: int | None = Field(default=None, ge=0, le=MAX_DAILY_LIMIT)
    reviews_per_day: int | None = Field(default=None, ge=0, le=MAX_DAILY_LIMIT)

    @model_validator(mode="after")
    def require_one_settings_group(self) -> _DeckSettingsSubmission:
        queue_values = (
            self.new_review_order,
            self.interday_learning_review_order,
            self.new_card_gather_order,
            self.new_card_sort_order,
            self.review_sort_order,
        )
        queue_complete = all(value is not None for value in queue_values)
        daily_complete = self.new_cards_per_day is not None and self.reviews_per_day is not None
        if queue_complete == daily_complete:
            raise ValueError("submit either complete queue settings or complete daily limits")
        return self

    def settings(self) -> DeckSchedulingSettings:
        if self.new_review_order is None:
            raise ValueError("queue settings are missing")
        return DeckSchedulingSettings(
            new_review_order=self.new_review_order,
            interday_learning_review_order=self.interday_learning_review_order,
            new_card_gather_order=self.new_card_gather_order,
            new_card_sort_order=self.new_card_sort_order,
            review_sort_order=self.review_sort_order,
        )

    def daily_limits(self) -> DailyLimits:
        if self.new_cards_per_day is None or self.reviews_per_day is None:
            raise ValueError("daily limits are missing")
        return DailyLimits(
            new_cards_per_day=self.new_cards_per_day,
            reviews_per_day=self.reviews_per_day,
        )


class _StatusSuspensionSubmission(_StatusActionSubmission):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return normalize_suspension_reason(value)


class _StatusBulkSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csrf_token: str = Field(min_length=1, max_length=256)
    selected_card_key: list[CardKey] = Field(min_length=1, max_length=100)
    bulk_action: Literal["suspend", "resume"]
    reason: str | None = Field(default=None, max_length=500)
    page: int = Field(default=1, ge=1)
    search: str = Field(default="", max_length=512)
    availability: AvailabilityFilter = AvailabilityFilter.ALL
    schedule: ScheduleFilter = ScheduleFilter.ALL
    state: FsrsStateFilter = FsrsStateFilter.ALL
    sort: CardSort = CardSort.NEXT_REVIEW
    direction: SortDirection = SortDirection.ASCENDING
    range: HistoryRange = HistoryRange.NINETY_DAYS

    @field_validator("selected_card_key", mode="before")
    @classmethod
    def normalize_selection(cls, value: object) -> object:
        values: list[object]
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, (list, tuple)):
            values = list(value)
        else:
            return value
        keys: list[CardKey] = []
        for raw_value in values:
            if isinstance(raw_value, str):
                try:
                    raw_value = json.loads(raw_value)
                except (json.JSONDecodeError, TypeError, ValueError) as error:
                    raise ValueError("a selected card key is invalid") from error
            try:
                keys.append(CardKey.model_validate(raw_value))
            except ValidationError as error:
                raise ValueError("a selected card key is invalid") from error
        if len(keys) != len({key.identity_parts for key in keys}):
            raise ValueError("a card must be selected only once")
        return keys

    @field_validator("search")
    @classmethod
    def validate_search(cls, value: str) -> str:
        return normalize_search_text(value)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return normalize_suspension_reason(value)

    def status_query(self) -> CardStatusQuery:
        return CardStatusQuery(
            page=self.page,
            search=self.search,
            availability=self.availability,
            schedule=self.schedule,
            state=self.state,
            sort=self.sort,
            direction=self.direction,
            range=self.range,
            tab=InfoTab.STATUS,
        )


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
    if len(request.query_string) > MAX_FORM_BYTES:
        raise RequestFailure(HTTPStatus.BAD_REQUEST, "The card-status filters are too large.")
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


def _is_search_validation_error(error: ValidationError) -> bool:
    errors = error.errors()
    return bool(errors) and all(entry.get("loc") == ("search",) for entry in errors)


def _status_url(deck_name: str, query: CardStatusQuery, page: int) -> str:
    values = query.model_dump(mode="json", exclude_none=True)
    values["page"] = page
    if not query.search:
        values.pop("search", None)
    values.pop("preview_entity", None)
    values.pop("preview_generator", None)
    return f"{url_for('card_status', deck_name=deck_name)}?{urlencode(values)}"


def _tab_url(deck_name: str, query: CardStatusQuery, tab: InfoTab) -> str:
    return _status_url(deck_name, query.model_copy(update={"tab": tab}), 1)


def _detail_url(deck_name: str, entity_id: str, query: CardStatusQuery) -> str:
    values = query.model_dump(mode="json", exclude_none=True)
    if not query.search:
        values.pop("search", None)
    values.pop("preview_entity", None)
    values.pop("preview_generator", None)
    values["tab"] = CardDetailTab.GENERATORS.value
    return f"{url_for('card_detail', deck_name=deck_name, entity_id=entity_id)}?{urlencode(values)}"


def _detail_tab_url(
    deck_name: str,
    entity_id: str,
    query: CardDetailQuery,
    tab: CardDetailTab,
) -> str:
    values = query.model_dump(mode="json", exclude_none=True)
    values["tab"] = tab.value
    values.pop("preview_generator", None)
    return f"{url_for('card_detail', deck_name=deck_name, entity_id=entity_id)}?{urlencode(values)}"


def _deck_asset_path(deck_path: Path, image_path: str) -> tuple[Path, str]:
    """Resolve one supported raster asset below the deck directory."""

    if "\\" in image_path:
        raise RequestFailure(HTTPStatus.NOT_FOUND, "That image does not exist.")
    relative_path = Path(image_path)
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise RequestFailure(HTTPStatus.NOT_FOUND, "That image does not exist.")
    media_type = _IMAGE_MEDIA_TYPES.get(relative_path.suffix.casefold())
    if media_type is None:
        raise RequestFailure(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "That image type is not supported.")
    deck_directory = deck_path.parent.resolve()
    resolved = (deck_directory / relative_path).resolve()
    try:
        resolved.relative_to(deck_directory)
    except ValueError as error:
        raise RequestFailure(HTTPStatus.NOT_FOUND, "That image does not exist.") from error
    try:
        if not resolved.is_file():
            raise RequestFailure(HTTPStatus.NOT_FOUND, "That image does not exist.")
        with resolved.open("rb"):
            pass
    except OSError as error:
        raise RequestFailure(HTTPStatus.NOT_FOUND, "That image could not be read.") from error
    return resolved, media_type


def create_flask_app(controller: StudyController) -> Flask:
    """Create one Flask application around an initialized study controller."""

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

    @app.before_request
    def end_session_outside_study_flow() -> None:
        if request.endpoint not in _STUDY_ENDPOINTS:
            _controller().end_session()

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self'; style-src 'self'; script-src 'self'; "
            "form-action 'self'; "
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

    def handle_application_failure(error: GraphCardsError) -> tuple[str, int]:
        return _render_error(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "Could not complete this request.",
        )

    app.register_error_handler(GraphCardsError, handle_application_failure)

    @app.errorhandler(StateConflictError)
    def handle_state_conflict(_error: StateConflictError) -> tuple[str, int]:
        return _render_error(
            HTTPStatus.CONFLICT,
            "The deck file changed outside GraphCards. Reload the deck and try again.",
        )

    def handle_dependency_failure(_error: Exception) -> tuple[str, int]:
        return _render_error(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "Could not complete this request.",
        )

    for error_type in (OSError,):
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
                "Shuffle through available cards without changing their schedules.",
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

    @app.post("/decks/<path:deck_name>/settings")
    def update_deck_settings(deck_name: str) -> Response:
        submission = _validated_form(
            _DeckSettingsSubmission,
            "The deck-status settings form is invalid.",
        )
        if submission.new_cards_per_day is not None:
            _controller().set_daily_limits(
                csrf_token=submission.csrf_token,
                deck_name=deck_name,
                limits=submission.daily_limits(),
            )
        else:
            _controller().set_scheduling(
                csrf_token=submission.csrf_token,
                deck_name=deck_name,
                settings=submission.settings(),
            )
        return redirect(
            url_for("card_status", deck_name=deck_name, tab=InfoTab.DECK_STATUS.value),
            code=HTTPStatus.SEE_OTHER,
        )

    @app.get("/study")
    def study() -> str:
        current = _session()
        current.refresh_availability()
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

    @app.get("/decks/<path:deck_name>/assets/<path:image_path>")
    def deck_asset(deck_name: str, image_path: str) -> Response:
        current = _controller()
        try:
            deck = current.config.deck(deck_name)
        except ConfigError as error:
            raise RequestFailure(HTTPStatus.NOT_FOUND, "That deck does not exist.") from error
        path, media_type = _deck_asset_path(deck.path, image_path)
        return send_file(path, mimetype=media_type, conditional=False)

    @app.post("/study/reveal")
    def reveal() -> Response:
        submission = _validated_form(
            _RevealSubmission,
            "The study form is invalid.",
        )
        _session().reveal(submission.session_token, submission.entity_id)
        return redirect(url_for("study"), code=HTTPStatus.SEE_OTHER)

    @app.post("/study/rate")
    def rate() -> Response:
        submission = _validated_form(
            _RatingSubmission,
            "The rating form is invalid.",
        )
        _session().rate(
            submission.session_token,
            submission.entity_id,
            Rating(submission.rating),
        )
        return redirect(url_for("study"), code=HTTPStatus.SEE_OTHER)

    @app.post("/study/next")
    def next_practice() -> Response:
        submission = _validated_form(
            _RevealSubmission,
            "The study form is invalid.",
        )
        _session().next_practice(submission.session_token, submission.entity_id)
        return redirect(url_for("study"), code=HTTPStatus.SEE_OTHER)

    @app.post("/study/suspend")
    def suspend_study_card() -> Response:
        submission = _validated_form(
            _StudySuspensionSubmission,
            "The suspension form is invalid.",
        )
        _session().suspend(
            submission.session_token,
            submission.entity_id,
            submission.reason,
        )
        return redirect(url_for("study"), code=HTTPStatus.SEE_OTHER)

    @app.post("/decks/<path:deck_name>/cards/suspend")
    def suspend_card(deck_name: str) -> Response:
        submission = _validated_form(
            _StatusSuspensionSubmission,
            "The suspension form is invalid.",
        )
        _controller().set_suspension(
            csrf_token=submission.csrf_token,
            deck_name=deck_name,
            entity_id=submission.entity_id,
            generator_id=submission.generator_id,
            suspended=True,
            reason=submission.reason,
        )
        return redirect(
            _status_url(deck_name, submission.status_query(), 1) + "#card-status",
            code=HTTPStatus.SEE_OTHER,
        )

    @app.post("/decks/<path:deck_name>/cards/resume")
    def resume_card(deck_name: str) -> Response:
        submission = _validated_form(
            _StatusActionSubmission,
            "The resume form is invalid.",
        )
        _controller().set_suspension(
            csrf_token=submission.csrf_token,
            deck_name=deck_name,
            entity_id=submission.entity_id,
            generator_id=submission.generator_id,
            suspended=False,
        )
        return redirect(
            _status_url(deck_name, submission.status_query(), 1) + "#card-status",
            code=HTTPStatus.SEE_OTHER,
        )

    @app.post("/decks/<path:deck_name>/cards/bulk")
    def bulk_card_action(deck_name: str) -> Response:
        submission = _validated_form(
            _StatusBulkSubmission,
            "The bulk card-status form is invalid.",
        )
        _controller().set_suspensions(
            csrf_token=submission.csrf_token,
            deck_name=deck_name,
            card_keys=tuple(submission.selected_card_key),
            suspended=submission.bulk_action == "suspend",
            reason=submission.reason,
        )
        return redirect(
            _status_url(deck_name, submission.status_query(), 1) + "#card-status",
            code=HTTPStatus.SEE_OTHER,
        )

    @app.get("/decks/<path:deck_name>/cards/detail/<path:entity_id>")
    def card_detail(deck_name: str, entity_id: str) -> str:
        current = _controller()
        try:
            deck = current.config.deck(deck_name)
        except ConfigError as error:
            raise RequestFailure(HTTPStatus.NOT_FOUND, "That deck does not exist.") from error
        try:
            query = CardDetailQuery.model_validate(_query_data())
        except ValidationError as error:
            raise RequestFailure(
                HTTPStatus.BAD_REQUEST,
                "The card-detail request is invalid.",
            ) from error
        now = utc_now()
        status = current.entity_status(deck, entity_id, now)
        card = status_row(status, now, current.config.display_timezone)
        generators = current.generators_for_entity(deck, entity_id)
        preview = None
        if query.preview_generator is not None:
            if query.tab is not CardDetailTab.GENERATORS:
                raise RequestFailure(
                    HTTPStatus.BAD_REQUEST,
                    "The exercise preview request is invalid.",
                )
            preview = current.preview_generator_for_entity(
                deck,
                entity_id,
                query.preview_generator,
            )
        return render_template(
            "card_detail.html",
            deck=deck,
            entity_id=entity_id,
            card=card,
            generators=generators,
            query=query,
            tab=query.tab,
            tab_urls={
                CardDetailTab.REVIEW_HISTORY: _detail_tab_url(
                    deck.name,
                    entity_id,
                    query,
                    CardDetailTab.REVIEW_HISTORY,
                ),
                CardDetailTab.GENERATORS: _detail_tab_url(
                    deck.name,
                    entity_id,
                    query,
                    CardDetailTab.GENERATORS,
                ),
            },
            reviews=current.card_review_history(deck, entity_id, now),
            preview=preview,
            back_url=_status_url(deck.name, query.status_query(), query.page),
        )

    @app.get("/decks/<path:deck_name>/cards")
    def card_status(deck_name: str) -> str:
        current = _controller()
        try:
            deck = current.config.deck(deck_name)
        except ConfigError as error:
            raise RequestFailure(HTTPStatus.NOT_FOUND, "That deck does not exist.") from error
        query_data = _query_data()
        search_error = None
        raw_search = query_data.get("search")
        search_value = raw_search if isinstance(raw_search, str) else ""
        try:
            query = CardStatusQuery.model_validate(query_data)
        except ValidationError as error:
            if not _is_search_validation_error(error):
                raise RequestFailure(
                    HTTPStatus.BAD_REQUEST,
                    "The card-status filters are invalid.",
                ) from error
            fallback_data = {**query_data, "search": ""}
            try:
                query = CardStatusQuery.model_validate(fallback_data)
            except ValidationError as fallback_error:
                raise RequestFailure(
                    HTTPStatus.BAD_REQUEST,
                    "The card-status filters are invalid.",
                ) from fallback_error
            search_error = "The search syntax is invalid. Use AND, OR, NOT, and parentheses."
        if search_error is None:
            search_value = query.search

        now = utc_now()
        all_cards = current.card_statuses(deck, now)
        deck_status = current.deck_status(deck, now)
        queue_status = current.queue_status(deck, now)
        filtered = [
            row
            for row in all_cards
            if schedule_matches(row, query, now)
            and search_matches(
                row,
                query,
                now,
                current.config.display_timezone,
                deck_name=deck.name,
                deck_display_name=deck.display_name,
            )
        ]
        ordered = sort_status_cards(filtered, query)
        total = len(ordered)
        pages = max(1, math.ceil(total / CARD_PAGE_SIZE))
        if query.tab is InfoTab.STATUS and query.page > pages:
            raise RequestFailure(
                HTTPStatus.NOT_FOUND,
                "That card-status page does not exist.",
            )
        start = (query.page - 1) * CARD_PAGE_SIZE
        page_cards = tuple(ordered[start : start + CARD_PAGE_SIZE])
        rows = (
            tuple(
                status_row(
                    row,
                    now,
                    current.config.display_timezone,
                )
                for row in page_cards
            )
            if query.tab is InfoTab.STATUS
            else ()
        )
        empty_message = None
        if query.tab is InfoTab.STATUS and not rows:
            empty_message = (
                "This deck has no active cards."
                if not all_cards
                else "No cards match these filters."
            )
        preview = None
        if query.preview_entity is not None:
            if query.tab is not InfoTab.STATUS or query.preview_generator is not None:
                raise RequestFailure(
                    HTTPStatus.BAD_REQUEST, "The exercise preview request is invalid."
                )
            preview = current.preview_entity(deck, query.preview_entity)
        elif query.preview_generator is not None:
            if query.tab is not InfoTab.GENERATORS:
                raise RequestFailure(
                    HTTPStatus.BAD_REQUEST, "The exercise preview request is invalid."
                )
            preview = current.preview_generator(deck, query.preview_generator)
        return render_template(
            "card_status.html",
            deck=deck,
            query=query,
            search_error=search_error,
            search_value=search_value,
            rows=rows,
            available_count=sum(not row.status.suspended for row in all_cards),
            suspended_count=sum(row.status.suspended for row in all_cards),
            csrf_token=current.csrf_token,
            daily_limit_maximum=MAX_DAILY_LIMIT,
            queue_status=queue_status,
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
            availability_options=AVAILABILITY_OPTIONS,
            state_options=STATE_OPTIONS,
            sort_options=SORT_OPTIONS,
            direction_options=DIRECTION_OPTIONS,
            history=(
                current.card_history(deck, query.range, now)
                if query.tab is InfoTab.HISTORY
                else None
            ),
            history_range_options=HISTORY_RANGE_OPTIONS,
            tab=query.tab,
            tab_urls={
                InfoTab.DECK_STATUS: _tab_url(deck.name, query, InfoTab.DECK_STATUS),
                InfoTab.STATUS: _tab_url(deck.name, query, InfoTab.STATUS),
                InfoTab.HISTORY: _tab_url(deck.name, query, InfoTab.HISTORY),
                InfoTab.GENERATORS: _tab_url(deck.name, query, InfoTab.GENERATORS),
            },
            generators=(
                current.generator_rows(deck, now) if query.tab is InfoTab.GENERATORS else ()
            ),
            deck_status=deck_status,
            queue_new_review_options=QUEUE_NEW_REVIEW_OPTIONS,
            queue_interday_options=QUEUE_INTERDAY_OPTIONS,
            queue_gather_options=QUEUE_GATHER_OPTIONS,
            queue_new_sort_options=QUEUE_NEW_SORT_OPTIONS,
            queue_review_sort_options=QUEUE_REVIEW_SORT_OPTIONS,
            preview=preview,
            detail_urls={
                row.entity_id: _detail_url(deck.name, row.entity_id, query) for row in rows
            },
        )

    return app
