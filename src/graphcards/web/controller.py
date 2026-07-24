"""Application controller for the local deck hub."""

from __future__ import annotations

import random
import secrets
from datetime import datetime, timedelta
from http import HTTPStatus

from rdflib import Graph

from graphcards.app import StudyService
from graphcards.config import AppConfig
from graphcards.decks import DeckDefinition
from graphcards.errors import ConfigError
from graphcards.storage import DeckStatus, Repository, utc_now
from graphcards.web.status import HistoryRange, HistoryView, StatusCard, history_view
from graphcards.web.study import RequestFailure, StudyMode, StudySession


class StudyController:
    """Deck catalog, persistent services, and the optional active session."""

    def __init__(
        self,
        config: AppConfig,
        graph: Graph,
        repository: Repository,
        rng: random.Random,
    ) -> None:
        self.config = config
        self.repository = repository
        self.rng = rng
        self.csrf_token = secrets.token_urlsafe(32)
        self.study_service = StudyService(
            graph,
            repository,
            config.fsrs.create_scheduler(),
            rng,
        )
        self.session: StudySession | None = None
        sync_time = utc_now()
        for deck in config.decks:
            self.study_service.sync(deck, sync_time)

    def deck_statuses(self) -> tuple[tuple[DeckDefinition, DeckStatus], ...]:
        now = utc_now()
        return tuple((deck, self.repository.status(deck.name, now)) for deck in self.config.decks)

    def card_statuses(
        self,
        deck: DeckDefinition,
        now: datetime,
    ) -> tuple[StatusCard, ...]:
        """Load active schedules and derive their time-dependent FSRS metric."""

        rows: list[StatusCard] = []
        for status in self.repository.card_statuses(deck.name):
            retrievability = None
            if status.stability is not None and status.last_review_at is not None:
                retrievability = self.study_service.scheduler.get_card_retrievability(
                    status.stored_card().card(),
                    current_datetime=now,
                )
            rows.append(StatusCard(status=status, retrievability=retrievability))
        return tuple(rows)

    def card_history(
        self,
        deck: DeckDefinition,
        selected_range: HistoryRange,
        now: datetime,
    ) -> HistoryView:
        """Aggregate immutable review events for one deck."""

        records = self.repository.review_history(deck.name, now)
        return history_view(
            records,
            selected_range,
            now,
            self.config.display_timezone,
        )

    def set_suspension(
        self,
        *,
        csrf_token: str,
        deck_name: str,
        card_id: str,
        suspended: bool,
        reason: str | None = None,
    ) -> None:
        if not secrets.compare_digest(csrf_token, self.csrf_token):
            raise RequestFailure(HTTPStatus.FORBIDDEN, "This card-status form is not valid.")
        try:
            deck = self.config.deck(deck_name)
        except ConfigError as error:
            raise RequestFailure(HTTPStatus.NOT_FOUND, "That deck does not exist.") from error
        if not self.repository.has_membership(deck.name, card_id):
            raise RequestFailure(
                HTTPStatus.NOT_FOUND,
                "That card is not known in this deck.",
            )
        if suspended:
            self.study_service.suspend(deck, card_id, reason)
        else:
            self.study_service.resume(deck, card_id)
        if self.session is not None and self.session.deck.name == deck.name:
            self.session.refresh_availability()

    def start_session(
        self,
        *,
        csrf_token: str,
        deck_name: str,
        mode: StudyMode,
        days: int,
        requested_limit: int,
    ) -> StudySession:
        if not secrets.compare_digest(csrf_token, self.csrf_token):
            raise RequestFailure(HTTPStatus.FORBIDDEN, "This session form is not valid.")
        try:
            deck = self.config.deck(deck_name)
        except ConfigError as error:
            raise RequestFailure(HTTPStatus.BAD_REQUEST, str(error)) from error

        now = utc_now()
        limit = None if requested_limit == 0 else requested_limit
        if mode is StudyMode.DUE:
            cards = self.repository.due_cards(deck.name, now, None)
        elif mode is StudyMode.FORGOTTEN:
            cards = self.repository.forgotten_cards(
                deck.name,
                now - timedelta(days=days),
                limit,
            )
        elif mode is StudyMode.PRACTICE:
            cards = self.repository.active_cards(deck.name)
            self.rng.shuffle(cards)
            if limit is not None:
                cards = cards[:limit]
        else:
            cards = self.repository.future_cards(
                deck.name,
                now,
                now + timedelta(days=days),
                limit,
            )
        self.session = StudySession(
            deck,
            self.study_service,
            cards,
            mode,
            days,
            requested_limit,
        )
        return self.session
